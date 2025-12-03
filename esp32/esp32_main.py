"""
Devices we used:
Temperature & humidity sensor, heart-rate sensor, accelerometer, pressure sensor, and the TCA9548A I²C multiplexer.

Wiring Guide (SCX and SDX refer to the pins on the TCA9548A module):

1. Temperature & Humidity Sensor (Using TCA9548A Channel 1)
SCL → SC1
SDA → SD1
VCC → 3.3V
GND → GND

2. Heart-rate Sensor (Using TCA9548A Channel 0)
INT → A0 (GPIO32) (optional, interrupt pin)
SDA →SD0
SCL → SC0
VIN → 3.3V
GND → GND

3. Pressure Sensor (Using ESP32 ADC)
The two pins of the FSR are equivalent.
Connect the FSR in series with a 22 kΩ resistor (value not fully confirmed yet):
The junction point → ADC A1 (GPIO26)
Other end of the resistor → GND
Other end of the FSR sensor → 3.3V
(This forms a voltage divider for ADC measurement.)

4. Accelerometer Sensor (Using TCA9548A Channel 2)
CS → 3.3V
SDO → GND (I²C address = 0x53)
VIN → 3.3V
GND → GND
SDA → SD2
SCL → SC2

5. TCA9548A I²C Multiplexer
SDA → ESP32 SDA
SCL → ESP32 SCL
VIN → 3.3V
GND → GND
The remaining SCx/SDx pins are connected to the respective device channels as described above.
"""

from machine import I2C, Pin, ADC
import time
import ujson
import ustruct
import network
import urequests
import gc

# --- Constants for estimation ---

SAMPLE_RATE_HZ = 10            # actual effective sampling rate
SLEEP_MS = 1000 // SAMPLE_RATE_HZ

##################################################
# 1. TCA9548A MULTIPLEXER
#    TCA9548A I2C 多路选择器，用于切换多个 I2C 通道
#    This multiplexer selects one of 8 I2C channels.
##################################################

TCA_ADDR = 0x70

def tca_select(i2c, channel):   # we can use channel 0-7
    if channel > 7:
        return
    i2c.writeto(TCA_ADDR, bytes([1 << channel]))
    time.sleep_ms(5)  # Required settling time


##################################################
# 2. DRIVER: HDC1080 (Temperature + Humidity)
#    温湿度传感器
#    Temperature & humidity sensor
##################################################

HDC1080_ADDR = 0x40

class HDC1080:
    def __init__(self, i2c):
        self.i2c = i2c

    def _read_temp_raw(self):    # Read raw temperature value (16-bit)
        self.i2c.writeto(HDC1080_ADDR, b'\x00')
        time.sleep_ms(15)
        d = self.i2c.readfrom(HDC1080_ADDR, 2)
        return (d[0] << 8) | d[1]

    def _read_humi_raw(self):    # Read raw humidity value (16-bit)
        self.i2c.writeto(HDC1080_ADDR, b'\x01')
        time.sleep_ms(15)
        d = self.i2c.readfrom(HDC1080_ADDR, 2)
        return (d[0] << 8) | d[1]

    def read_temp_c(self):
        raw = self._read_temp_raw()
        temp_c = (raw / 65536.0) * 165.0 - 40.0
        return temp_c

    def read_humi_rh(self):
        raw = self._read_humi_raw()
        humidity = (raw / 65536.0) * 100.0
        return humidity


##################################################
# 3. DRIVER: MAX30102 (Heart rate / SpO2 PPG)
#    心率血氧传感器
#    Photoplethysmography (PPG) sensor
##################################################

# MAX30102 I2C address
MAX30102_ADDR = 0x57

# --- Algorithm related constants ---
WINDOW_SECONDS = 8             # Length of HR analysis window (seconds)
MIN_WINDOW_SECONDS = 4         # HR estimation minimal data length (seconds)
MAX_SAMPLES = SAMPLE_RATE_HZ * WINDOW_SECONDS

# The actual internal sample rate of MAX30102 (set by register 0x0A)
SENSOR_SAMPLE_RATE_HZ = 100

# Simple integer downsampling factor. Avoid overwhelming the ESP32. TODO: try different rates
DOWNSAMPLE_FACTOR = SENSOR_SAMPLE_RATE_HZ // SAMPLE_RATE_HZ

# Register addresses (MAX30102)
REG_INTR_STATUS_1 = 0x00
REG_INTR_STATUS_2 = 0x01
REG_INTR_ENABLE_1 = 0x02
REG_INTR_ENABLE_2 = 0x03

REG_FIFO_WR_PTR   = 0x04
REG_OVF_COUNTER   = 0x05
REG_FIFO_RD_PTR   = 0x06
REG_FIFO_DATA     = 0x07
REG_FIFO_CONFIG   = 0x08

REG_MODE_CONFIG   = 0x09
REG_SPO2_CONFIG   = 0x0A

REG_LED1_PA       = 0x0C   # RED LED pulse amplitude
REG_LED2_PA       = 0x0D   # IR LED pulse amplitude

REG_TEMP_INT      = 0x1F
REG_TEMP_FRAC     = 0x20

REG_PART_ID       = 0xFF   # Should be 0x15 for MAX30102


class MAX30102:
    """
    MAX30102 driver with:
      - FIFO-based reading
      - Internal downsampled window buffer
      - Simple heart-rate estimation from IR channel

    Public methods:
      - get_latest_pair()  -> (red, ir) or (None, None)
      - estimate_hr_simple() -> hr_bpm (float) or None
    """

    def __init__(self, i2c):
        self.i2c = i2c

        # --- Internal buffers for downsampled data (for HR / SpO2 estimation) ---
        self.ir_window = []           # Downsampled IR samples
        self.red_window = []          # Downsampled RED samples
        self._downsample_counter = 0  # Counter for integer decimation

        # --- SpO2 estimation state ---
        self._last_spo2 = None       # Last smoothed SpO2 value
        self._spo2_alpha = 0.3       # EMA smoothing factor (0..1)

        # --- Basic configuration and sanity check ---
        self._check_part_id()
        self._configure_sensor()
        self._clear_fifo_pointers()


    # -------------------------------------------------------------------------
    #  Low-level I2C helpers
    # -------------------------------------------------------------------------
    def _read_reg(self, reg, n_bytes=1):
        """Read 1 or more bytes from a register."""
        data = self.i2c.readfrom_mem(MAX30102_ADDR, reg, n_bytes)
        if n_bytes == 1:
            return data[0]
        return data

    def _write_reg(self, reg, value):
        """Write 1 byte to a register."""
        self.i2c.writeto_mem(MAX30102_ADDR, reg, bytes([value & 0xFF]))

    # -------------------------------------------------------------------------
    #  Sensor configuration
    # -------------------------------------------------------------------------
    def _check_part_id(self):
        """Verify that a MAX30102 is present on the bus."""
        try:
            part_id = self._read_reg(REG_PART_ID)
        except OSError:
            raise Exception("MAX30102 not responding on I2C bus")

        if part_id != 0x15:
            raise Exception("Unexpected PART_ID for MAX30102: 0x%02X" % part_id)

    def _configure_sensor(self):
        """Reset and configure MAX30102 for SpO2 mode with ~100Hz sample rate."""
        # 1. Soft reset
        self._write_reg(REG_MODE_CONFIG, 0x40)  # Reset bit
        time.sleep_ms(10)

        # 2. Wait until reset bit is cleared
        for _ in range(100):
            mc = self._read_reg(REG_MODE_CONFIG)
            if (mc & 0x40) == 0:
                break
            time.sleep_ms(1)
        # print("MODE_CONFIG after reset: 0x%02X" % mc)

        # 3. FIFO configuration
        self._write_reg(REG_FIFO_CONFIG, 0x4F)

        # 4. SpO2 config (sample rate, pulse width, ADC range)
        self._write_reg(REG_SPO2_CONFIG, 0x27)

        # 5. LED pulse amplitudes
        self._write_reg(REG_LED1_PA, 0x24)  # Red LED
        self._write_reg(REG_LED2_PA, 0x24)  # IR LED

        # 6. Enable interrupts: A_FULL + PPG_RDY
        self._write_reg(REG_INTR_ENABLE_1, 0xC0)
        self._write_reg(REG_INTR_ENABLE_2, 0x00)

        # 7. Finally, set SpO2 mode
        self._write_reg(REG_MODE_CONFIG, 0x03)


    def _clear_fifo_pointers(self):
        """Reset FIFO read/write/overflow pointers."""
        self._write_reg(REG_FIFO_WR_PTR, 0x00)
        self._write_reg(REG_OVF_COUNTER, 0x00)
        self._write_reg(REG_FIFO_RD_PTR, 0x00)

        # Clear any pending interrupts
        _ = self._read_reg(REG_INTR_STATUS_1)
        _ = self._read_reg(REG_INTR_STATUS_2)

    # -------------------------------------------------------------------------
    #  FIFO reading and window management
    # -------------------------------------------------------------------------
    def _read_fifo_samples(self):
        """
        Robust FIFO reading for buggy pointer chips.
        - Uses Observer pattern: observe INT_STATUS1 to decide reads.
        - Producer-Consumer: sensor produces samples, we consume until empty.
        - Error handling: timeout, I2C exceptions, invalid data checks.
        """
        samples = []
        max_reads = 32  # Max to prevent infinite loop (FIFO depth)
        read_count = 0

        try:
            while read_count < max_reads:
                # Clear and check interrupt status
                intr1 = self._read_reg(REG_INTR_STATUS_1)
                _ = self._read_reg(REG_INTR_STATUS_2)

                # If no PPG_RDY, stop
                if (intr1 & 0x40) == 0:
                    break

                # Read 1 sample (6 bytes)
                raw = self._read_reg(REG_FIFO_DATA, 6)

                # Extract and validate
                red = ((raw[0] << 16) | (raw[1] << 8) | raw[2]) & 0x03FFFF
                ir = ((raw[3] << 16) | (raw[4] << 8) | raw[5]) & 0x03FFFF

                # Basic validation: skip if data is zero/invalid
                if red == 0 and ir == 0:
                    continue

                samples.append((red, ir))
                read_count += 1

                # Small delay to avoid I2C overload
                time.sleep_ms(1)

        except OSError as e:
            print("I2C error in FIFO read:", e)
            return []  # Return empty on error

        # logging for production debugging
        # if read_count > 0:
        #     print("Read %d samples from FIFO" % read_count)

        return samples

    def _update_window_from_sensor(self):
        """
        Read all available FIFO samples, downsample them, and update the
        internal RED/IR sliding windows.
        """
        samples = self._read_fifo_samples()
        if not samples:
            return

        for red, ir in samples:
            # Integer decimation: keep one sample every DOWNSAMPLE_FACTOR
            self._downsample_counter += 1
            if self._downsample_counter < DOWNSAMPLE_FACTOR:
                continue
            self._downsample_counter = 0

            self.red_window.append(red)
            self.ir_window.append(ir)

            # Limit window length to MAX_SAMPLES
            if len(self.ir_window) > MAX_SAMPLES:
                # For small windows (e.g., 80 samples), pop(0) cost is acceptable
                self.ir_window.pop(0)
                self.red_window.pop(0)

    # -------------------------------------------------------------------------
    #  Public data access
    # -------------------------------------------------------------------------
    def get_latest_pair(self):
        """
        Update internal window from FIFO and return the latest (red, ir) pair.

        :return: (red, ir) tuple or (None, None) if no data yet.
        """
        # First, pull in all pending samples from sensor
        self._update_window_from_sensor()

        if not self.ir_window:
            return None, None

        # Keep API simple: always return (red, ir)
        return self.red_window[-1], self.ir_window[-1]

    # -------------------------------------------------------------------------
    #  Simple heart rate estimation (from internal IR window)
    # -------------------------------------------------------------------------
    @staticmethod
    def _moving_average(signal, window):
        """Simple moving average, padded to original length."""
        n = len(signal)
        if window <= 1 or n <= window:
            return signal[:]
        out = []
        s = 0
        for i in range(window):
            s += signal[i]
        out.append(s / window)
        for i in range(window, n):
            s += signal[i] - signal[i - window]
            out.append(s / window)
        pad_len = window - 1
        return [out[0]] * pad_len + out

    def estimate_hr_simple(self):
        """
        Estimate heart rate (BPM) from the internal IR window.

        Uses:
          - SAMPLE_RATE_HZ as effective sampling rate on the window
          - MIN_WINDOW_SECONDS and WINDOW_SECONDS for data length checks

        :return: heart rate in BPM (float) or None if not enough / unreliable
        """
        ir_buffer = self.ir_window
        n = len(ir_buffer)

        # Require at least MIN_WINDOW_SECONDS worth of data
        min_samples = int(SAMPLE_RATE_HZ * MIN_WINDOW_SECONDS)
        if n < min_samples:
            return None

        # Use only last WINDOW_SECONDS of data
        if n > MAX_SAMPLES:
            data = ir_buffer[-MAX_SAMPLES:]
        else:
            data = ir_buffer[:]

        if not data:
            return None

        # 1) Remove DC component
        mean_val = sum(data) / len(data)
        ac = [x - mean_val for x in data]

        # 2) Smooth with a small moving average window
        smoothed = MAX30102._moving_average(ac, 5)

        # 3) Peak detection
        max_val = max(smoothed)
        if max_val <= 0:
            return None

        threshold = 0.3 * max_val  # 30% of peak amplitude
        # Minimal distance between peaks (in samples), assuming max HR ~200 bpm
        min_distance = int(0.3 * SAMPLE_RATE_HZ)  # 0.3 s

        peaks = []
        last_peak = -min_distance

        # Simple local maxima detection
        for i in range(1, len(smoothed) - 1):
            if (smoothed[i] > threshold and
                smoothed[i] > smoothed[i - 1] and
                smoothed[i] > smoothed[i + 1]):
                if i - last_peak >= min_distance:
                    peaks.append(i)
                    last_peak = i

        if len(peaks) < 2:
            return None

        # 4) Compute RR intervals and HR
        intervals = []
        for i in range(1, len(peaks)):
            dt_samples = peaks[i] - peaks[i - 1]
            if dt_samples <= 0:
                continue
            rr = dt_samples / float(SAMPLE_RATE_HZ)
            intervals.append(rr)

        if not intervals:
            return None

        rr_mean = sum(intervals) / len(intervals)
        if rr_mean <= 0:
            return None

        hr_bpm = 60.0 / rr_mean
        return hr_bpm

    def estimate_spo2_simple(self):
        """
        SpO2 estimation using ratio-of-ratios on RED/IR windows, with
        basic signal-quality checks and simple exponential smoothing.

        Returns:
            Smoothed SpO2 percentage (float) or None if data is unreliable.
        """
        red_buffer = self.red_window
        ir_buffer = self.ir_window

        # -------------------------------
        # 0) Check minimal data length
        # -------------------------------
        try:
            min_seconds = max(4.0, MIN_WINDOW_SECONDS)  # Prefer at least ~4s for SpO2
            min_samples = int(SAMPLE_RATE_HZ * min_seconds)
        except NameError:
            # Fallback if constants are not defined
            min_samples = 80  # e.g., ~3–4s at 20–30 Hz effective rate

        n = min(len(red_buffer), len(ir_buffer))
        if n < min_samples:
            return None

        # Use up to MAX_SAMPLES most recent data if defined, otherwise use all
        try:
            window_len = min(n, MAX_SAMPLES)
        except NameError:
            window_len = n

        red_data = red_buffer[-window_len:]
        ir_data = ir_buffer[-window_len:]

        if not red_data or not ir_data:
            return None

        # -------------------------------
        # 1) DC components (mean values)
        # -------------------------------
        red_dc = sum(red_data) / len(red_data)
        ir_dc = sum(ir_data) / len(ir_data)

        # DC level sanity checks
        # Threshold values are heuristic and may need tuning for your hardware.
        if red_dc < 5000 or ir_dc < 5000:
            # Very low DC suggests poor contact or no finger
            return None

        # -------------------------------
        # 2) AC components (peak-to-peak)
        # -------------------------------
        red_ac_signal = [x - red_dc for x in red_data]
        ir_ac_signal = [x - ir_dc for x in ir_data]

        red_ac = max(red_ac_signal) - min(red_ac_signal)
        ir_ac = max(ir_ac_signal) - min(ir_ac_signal)

        # AC must be clearly above noise; thresholds are rough heuristics.
        if red_ac <= 0 or ir_ac <= 0:
            return None

        # Perfusion index-like checks: AC/DC should not be too small
        red_ratio = red_ac / red_dc
        ir_ratio = ir_ac / ir_dc

        # For typical finger PPG, these ratios are small (e.g., ~0.01–0.1).
        # If both are extremely small, likely no usable pulsatile signal.
        if red_ratio < 0.001 and ir_ratio < 0.001:
            return None

        # -------------------------------
        # 3) Ratio-of-ratios R
        # -------------------------------
        if red_ratio <= 0 or ir_ratio <= 0:
            return None

        R = red_ratio / ir_ratio

        # Plausibility check for R
        # Typical physiological R roughly between ~0.3 and 1.5
        if R < 0.2 or R > 3.0:
            return None

        # -------------------------------
        # 4) Raw SpO2 estimation
        # -------------------------------
        # NOTE: This is a generic empirical formula; for medical-grade
        # accuracy, a device-specific calibration curve is required.
        raw_spo2 = 110.0 - 25.0 * R

        # Clamp to plausible range
        if raw_spo2 < 70.0:
            raw_spo2 = 70.0
        elif raw_spo2 > 100.0:
            raw_spo2 = 100.0

        # -------------------------------
        # 5) Simple exponential smoothing
        # -------------------------------
        if self._last_spo2 is None:
            smoothed_spo2 = raw_spo2
        else:
            alpha = self._spo2_alpha
            smoothed_spo2 = (1.0 - alpha) * self._last_spo2 + alpha * raw_spo2

        self._last_spo2 = smoothed_spo2
        return smoothed_spo2


##################################################
# 4. DRIVER: ADXL345 (3-axis accelerometer)
#    三轴加速度计
#    3-axis accelerometer
##################################################

ADXL345_ADDR = 0x53

class ADXL345:
    def __init__(self, i2c):
        self.i2c = i2c

        # Set to measurement mode
        self.i2c.writeto_mem(ADXL345_ADDR, 0x2D, bytes([0x08]))

        # Full resolution ±2g
        self.i2c.writeto_mem(ADXL345_ADDR, 0x31, bytes([0x08]))

    def read_xyz(self):
        """读取 X/Y/Z 三轴加速度 (signed 16-bit)
           Read X/Y/Z acceleration values
        """
        data = self.i2c.readfrom_mem(ADXL345_ADDR, 0x32, 6)
        x, y, z = ustruct.unpack("<hhh", data)
        return x, y, z


##################################################
# 5. FSR402 (Analog pressure sensor)
#    压力传感器（模拟输入）
#    Pressure sensor via ADC (GPIO32)
##################################################

fsr_pin = ADC(Pin(32))
fsr_pin.atten(ADC.ATTN_11DB)      # enable 0–3.3V
fsr_pin.width(ADC.WIDTH_12BIT)    # 12-bit precision

def read_fsr():
    return fsr_pin.read()


##################################################
# 6. SETUP I2C
#    配置主 I2C 总线
#    Setup main I2C bus
##################################################

i2c = I2C(0, scl=Pin(20), sda=Pin(22), freq=400000)


##################################################
# 7. Initialize all sensors
#    传感器初始化，注意必须先切换到对应通道
#    Sensors must be initialized after selecting their I2C channel
##################################################

tca_select(i2c, 0)
sensor_ppg = MAX30102(i2c)

tca_select(i2c, 1)
sensor_hdc = HDC1080(i2c)

tca_select(i2c, 2)
sensor_acc = ADXL345(i2c)

##################################################
# 7.5 NETWORK & BATCH CONFIG
##################################################

# WiFi Configuration
WIFI_SSID = "Columbia University"
WIFI_PASS = ""  # Fill password if needed

def connect_wifi():
    """Connect ESP32 to WiFi."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASS)
        while not wlan.isconnected():
            time.sleep(0.5)
    print("WiFi Connected:", wlan.ifconfig())

connect_wifi()
time.sleep(1)

# Server Configuration
SERVER_IP = "136.113.226.196"
# SERVER_IP = "10.206.166.137" # Local testing IP (Debug)
SERVER_PORT = 9999
DEVICE_ID = "esp32_001"  # Modify as needed

BASE_URL = "http://%s:%d" % (SERVER_IP, SERVER_PORT)
VITALS_API_URL = BASE_URL + "/api/vitals"

# Batch configuration
BATCH_SIZE = 20  # <<< adjustable batch size


class VitalBatchSender:
    """
    Simple safe batch sender for ESP32 + MicroPython.

    Features:
      - Size-based batching (batch_size)
      - Hard limit on buffer length (max_buffer_points) to avoid OOM
      - Optional time-based flush (flush_interval_ms)
    """

    def __init__(self,
                 device_id,
                 url,
                 batch_size=20,
                 max_buffer_points=200,
                 flush_interval_ms=5000):
        """
        :param device_id: Unique device ID string
        :param url: HTTP endpoint for POST
        :param batch_size: Number of points per batch
        :param max_buffer_points: Max points kept in memory
        :param flush_interval_ms: Force flush if no send for this duration
        """
        self.device_id = device_id
        self.url = url
        self.batch_size = batch_size
        self.max_buffer_points = max_buffer_points
        self.flush_interval_ms = flush_interval_ms

        self.buffer = []
        self.last_send_ms = time.ticks_ms()

    def add_point(self, point, now_ms=None):
        """
        Add one data point to buffer, and send if batch is ready.
        """
        if now_ms is None:
            now_ms = time.ticks_ms()

        self.buffer.append(point)

        # Enforce hard buffer limit (keep newest points)
        if len(self.buffer) > self.max_buffer_points:
            # Drop oldest points
            drop_count = len(self.buffer) - self.max_buffer_points
            self.buffer = self.buffer[drop_count:]

        # Size-based send
        if len(self.buffer) >= self.batch_size:
            self._send_buffer(now_ms)

    def flush_if_due(self, now_ms=None):
        """
        Time-based flush: if there are unsent points and last send
        was a while ago, send them.
        """
        if now_ms is None:
            now_ms = time.ticks_ms()

        if not self.buffer:
            return

        if time.ticks_diff(now_ms, self.last_send_ms) >= self.flush_interval_ms:
            self._send_buffer(now_ms)

    def _send_buffer(self, now_ms):
        """
        Internal: send current buffer as one HTTP POST batch.
        """
        if not self.buffer:
            return

        start_cycle = self.buffer[0]["cycle"]
        end_cycle = self.buffer[-1]["cycle"]
        total_points = len(self.buffer)

        payload = {
            "device_id": self.device_id,
            "batch_info": {
                "start_cycle": start_cycle,
                "end_cycle": end_cycle,
                "total_points": total_points
            },
            "data": self.buffer
        }

        try:
            # Shorter timeout helps avoid long blocking
            resp = urequests.post(self.url, json=payload, timeout=5)
            status = resp.status_code
            resp.close()
            print("Batch sent. Status:", status)

            # Clear buffer on success
            self.buffer = []
            self.last_send_ms = now_ms

        except Exception as e:
            # Do not clear buffer; keep latest points but enforce max_buffer_points
            print("ERROR: Failed to send batch:", e)

            if len(self.buffer) > self.max_buffer_points:
                # Keep only the newest points
                self.buffer = self.buffer[-self.max_buffer_points:]

        finally:
            # Help GC to reclaim memory
            gc.collect()

class CycleCounter:
    """
    Monotonic cycle counter with wrap-around at a configurable maximum value.
    """

    def __init__(self, max_value=1000000000):
        self.max_value = max_value
        self.value = 0

    def next(self):
        """
        Increment counter and return the next cycle value.
        Wraps back to 1 after reaching max_value.
        """
        self.value += 1
        if self.value > self.max_value:
            self.value = 1
        return self.value


##################################################
# 8. CONTINUOUS STREAMING MODE
##################################################

print("Start continuous streaming")

last_send = time.ticks_ms()

batch_sender = VitalBatchSender(DEVICE_ID, VITALS_API_URL, BATCH_SIZE)

cycle_counter = CycleCounter()

while True:

    # MAX30102 — CH0
    tca_select(i2c, 0)
    red, ir = sensor_ppg.get_latest_pair()
    heartrate = sensor_ppg.estimate_hr_simple()
    spo2 = sensor_ppg.estimate_spo2_simple()

    # HDC1080 — CH1
    tca_select(i2c, 1)
    temp_c = sensor_hdc.read_temp_c()
    humidity = sensor_hdc.read_humi_rh()

    # ADXL345 — CH2
    tca_select(i2c, 2)
    ax, ay, az = sensor_acc.read_xyz()

    # FSR402 (ADC)
    fsr_raw = read_fsr()

    # Sample every 200ms
    now_ms = time.ticks_ms()
    if time.ticks_diff(now_ms, last_send) > SLEEP_MS:
        last_send = now_ms

        force_value = fsr_raw

        cycle = cycle_counter.next()

        data_point = {
            "cycle": cycle,
            "timestamp": now_ms,
            "vital_signs": {
                "ppg": {
                    "ir": 0 if ir is None else ir,
                    "red": 0 if red is None else red,
                    "heartrate": 0 if heartrate is None else heartrate,
                    "spo2": 0 if spo2 is None else spo2
                },
                "temperature": temp_c,
                "humidity": humidity,
                "force": force_value,
                "accel": {
                    "ax": ax,
                    "ay": ay,
                    "az": az
                }
            }
        }

        # Debug if needed
        # print(ujson.dumps(data_point))

        batch_sender.add_point(data_point)
        # if cycle % 10 == 0:
        #     print("cycle:", cycle, "hr:", heartrate, "spo2:", spo2)

    time.sleep_ms(5)
