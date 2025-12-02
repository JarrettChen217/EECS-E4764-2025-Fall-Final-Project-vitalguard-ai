from machine import Pin, I2C
import time

# --- Sampling configuration ---
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
        # Soft reset
        self._write_reg(REG_MODE_CONFIG, 0x40)  # Reset bit
        time.sleep_ms(50)

        # FIFO configuration:
        #  - Sample average = 4
        #  - FIFO rollover disabled
        #  - FIFO almost full = 15 (unused here, but common default)
        # 0b0100_1111 = 0x4F
        self._write_reg(REG_FIFO_CONFIG, 0x4F)

        # SpO2 mode: RED + IR
        self._write_reg(REG_MODE_CONFIG, 0x03)

        # SpO2 configuration:
        #  - SPO2_ADC_RGE = 01 (4096 nA full scale)
        #  - SPO2_SR      = 0001 (100 samples per second)
        #  - LED_PW       = 11 (411 us, 18-bit resolution)
        # 0b0100_0111 = 0x27
        self._write_reg(REG_SPO2_CONFIG, 0x27)

        # LED pulse amplitudes (~7 mA, a safe starting point; adjust as needed)
        self._write_reg(REG_LED1_PA, 0x24)  # Red LED
        self._write_reg(REG_LED2_PA, 0x24)  # IR LED

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
        Read all available samples from FIFO.

        :return: list of (red, ir) tuples (raw 18-bit values); may be empty.
        """
        # Clear interrupt status registers (required pattern)
        _ = self._read_reg(REG_INTR_STATUS_1)
        _ = self._read_reg(REG_INTR_STATUS_2)

        # Read FIFO read/write pointers
        read_ptr = self._read_reg(REG_FIFO_RD_PTR)
        write_ptr = self._read_reg(REG_FIFO_WR_PTR)

        # Compute number of samples currently in FIFO (depth = 32 samples)
        num_samples = write_ptr - read_ptr
        if num_samples < 0:
            num_samples += 32

        if num_samples <= 0:
            return []

        # Each sample is 6 bytes: 3 bytes RED + 3 bytes IR
        bytes_to_read = num_samples * 6
        raw = self._read_reg(REG_FIFO_DATA, bytes_to_read)

        samples = []
        for i in range(num_samples):
            base = i * 6

            # Extract 18-bit RED (left-justified)
            red = ((raw[base] << 16) |
                   (raw[base + 1] << 8) |
                   raw[base + 2]) & 0x03FFFF

            # Extract 18-bit IR
            ir = ((raw[base + 3] << 16) |
                  (raw[base + 4] << 8) |
                  raw[base + 5]) & 0x03FFFF

            samples.append((red, ir))

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


# --- Main program ---
try:
    # Initialize I2C
    # !!! Adjust pins according to your ESP32 board wiring !!!
    # Common for classic ESP32: scl=Pin(22), sda=Pin(21)
    i2c = I2C(0, scl=Pin(20), sda=Pin(22), freq=400000)

    tca_select(i2c, 0)

    devices = i2c.scan()

    # MAX30102 — CH0
    tca_select(i2c, 0)
    if MAX30102_ADDR in devices:
        print("MAX30102 found at 0x%02X" % MAX30102_ADDR)

        sensor = MAX30102(i2c)

        last_hr_print_ms = time.ticks_ms()

        while True:
            red, ir = sensor.get_latest_pair()
            if (red is None) or (ir is None):
                # No new data yet
                time.sleep_ms(10)
                continue

            # (Optional) print raw values for debugging
            # print("IR:", ir, "Red:", red)

            # Estimate HR every ~1 second
            now = time.ticks_ms()
            if time.ticks_diff(now, last_hr_print_ms) >= SLEEP_MS:
                heartrate = sensor.estimate_hr_simple()
                spo2 = sensor.estimate_spo2_simple()
                if (heartrate is not None) and (spo2 is not None):
                    print("HR: %.1f bpm, SpO2: %.1f%%" % (heartrate, spo2))
                elif heartrate is not None:
                    print("HR: %.1f bpm, SpO2: --%%" % (heartrate))
                elif spo2 is not None:
                    print("HR: -- bpm, SpO2: %.1f%%" % (spo2))
                else:
                    print("HR: -- bpm, SpO2: --%%")
                last_hr_print_ms = now

            # Small delay to avoid busy loop
            time.sleep_ms(10)

    else:
        print("ERROR: MAX30102 not found on I2C bus.")
        print("Scanned devices:", [hex(d) for d in devices])

except Exception as e:
    print("Error:", e)
