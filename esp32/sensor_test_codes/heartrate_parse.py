from machine import Pin, I2C
import time

# --- MAX30102 constants based on datasheet ---
MAX30102_ADDR = 0x57

# Register addresses
REG_INT_STATUS_1 = 0x00
REG_INT_ENABLE_1 = 0x02
REG_FIFO_WR_PTR = 0x04
REG_OVF_COUNTER = 0x05
REG_FIFO_RD_PTR = 0x06
REG_FIFO_DATA = 0x07
REG_FIFO_CONFIG = 0x08
REG_MODE_CONFIG = 0x09
REG_SPO2_CONFIG = 0x0A
REG_LED1_PA = 0x0C  # RED
REG_LED2_PA = 0x0D  # IR
REG_PART_ID = 0xFF

# --- Algorithm related constants ---
SAMPLE_RATE_HZ = 100          # Must match SPO2_SR setting (here 100 sps)
WINDOW_SECONDS = 8            # Length of analysis window
MIN_WINDOW_SECONDS = 4        # Minimal data length for HR estimation
MAX_SAMPLES = SAMPLE_RATE_HZ * WINDOW_SECONDS

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


class MAX30102:
    def __init__(self, i2c):
        self.i2c = i2c
        part_id = self._read_reg(REG_PART_ID)
        if part_id != 0x15:
            raise Exception("MAX30102 not found, part_id=0x%02X" % part_id)
        self.setup()

    def _read_reg(self, reg, n_bytes=1):
        """Read N bytes from register."""
        data = self.i2c.readfrom_mem(MAX30102_ADDR, reg, n_bytes)
        if n_bytes == 1:
            return data[0]
        return data

    def _write_reg(self, reg, val):
        """Write one byte to register."""
        self.i2c.writeto_mem(MAX30102_ADDR, reg, bytes([val]))

    def setup(self):
        """Configure MAX30102 for SpO2 mode @100sps, 18-bit."""
        # Reset
        self._write_reg(REG_MODE_CONFIG, 0x40)  # RESET bit = 1
        time.sleep_ms(100)

        # FIFO config:
        # SMP_AVE = 4 samples, FIFO_ROLLOVER_EN = 1, FIFO_A_FULL = 15
        # 0b0101_1111 = 0x5F
        self._write_reg(REG_FIFO_CONFIG, 0x5F)

        # Mode config: SpO2 mode (Red + IR)
        self._write_reg(REG_MODE_CONFIG, 0x03)

        # SpO2 config:
        # SPO2_ADC_RGE = 01 (4096 nA full scale)
        # SPO2_SR = 001 (100 samples per second)
        # LED_PW = 11 (411 us, 18-bit resolution)
        # 0b0010_0111 = 0x27
        self._write_reg(REG_SPO2_CONFIG, 0x27)

        # LED pulse amplitude (~7mA, decent starting point)
        self._write_reg(REG_LED1_PA, 0x24)  # Red LED
        self._write_reg(REG_LED2_PA, 0x24)  # IR LED

        # Clear FIFO pointers
        self._write_reg(REG_FIFO_WR_PTR, 0x00)
        self._write_reg(REG_OVF_COUNTER, 0x00)
        self._write_reg(REG_FIFO_RD_PTR, 0x00)

        print("MAX30102 configured.")

    def read_fifo(self):
        """
        Read all available samples from FIFO.

        :return: list of (ir, red) tuples. May be empty if no new samples.
        """
        # Clear interrupt status
        self._read_reg(REG_INT_STATUS_1)

        # Read FIFO read/write pointers
        read_ptr = self._read_reg(REG_FIFO_RD_PTR)
        write_ptr = self._read_reg(REG_FIFO_WR_PTR)

        # Compute number of samples in FIFO (circular buffer of 32 samples)
        num_samples = write_ptr - read_ptr
        if num_samples < 0:
            num_samples += 32

        if num_samples <= 0:
            return []

        # Each sample = 6 bytes (3 bytes RED + 3 bytes IR) in SpO2 mode
        raw_bytes = self._read_reg(REG_FIFO_DATA, num_samples * 6)

        samples = []
        for i in range(num_samples):
            base = i * 6
            # According to datasheet, FIFO is left-justified 18-bit
            # Mask out upper unused bits with 0x03FFFF
            ir_val = ((raw_bytes[base] << 16) |
                      (raw_bytes[base + 1] << 8) |
                      raw_bytes[base + 2]) & 0x03FFFF
            red_val = ((raw_bytes[base + 3] << 16) |
                       (raw_bytes[base + 4] << 8) |
                       raw_bytes[base + 5]) & 0x03FFFF
            samples.append((ir_val, red_val))

        return samples


# --- Very simple HR estimation functions (no numpy) ---

def moving_average(signal, window):
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
    # Pad front to match original length
    pad_len = window - 1
    return [out[0]] * pad_len + out


def estimate_hr_simple(ir_buffer):
    """
    Estimate heart rate from IR buffer.

    :param ir_buffer: list of last N IR samples (ints)
    :return: heart rate in BPM or None if not enough / unreliable
    """
    n = len(ir_buffer)
    min_samples = int(SAMPLE_RATE_HZ * MIN_WINDOW_SECONDS)
    if n < min_samples:
        return None

    # Use only last WINDOW_SECONDS of data
    if n > MAX_SAMPLES:
        data = ir_buffer[-MAX_SAMPLES:]
    else:
        data = ir_buffer[:]

    # 1) Remove DC component
    mean_val = sum(data) / len(data)
    ac = [x - mean_val for x in data]

    # 2) Smooth with small moving average
    smoothed = moving_average(ac, 5)

    # 3) Peak detection
    max_val = max(smoothed)
    if max_val <= 0:
        return None

    threshold = 0.3 * max_val  # 30% of max amplitude
    # Minimal distance between peaks (in samples), assuming max HR 200 bpm
    min_distance = int(0.3 * SAMPLE_RATE_HZ)  # 0.3s

    peaks = []
    last_peak = -min_distance

    # Simple local maxima detection
    for i in range(1, len(smoothed) - 1):
        if smoothed[i] > threshold and smoothed[i] > smoothed[i - 1] and smoothed[i] > smoothed[i + 1]:
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


# --- Main program ---
try:
    # Initialize I2C
    # !!! Adjust pins according to your ESP32 board wiring !!!
    # Common for classic ESP32: scl=Pin(22), sda=Pin(21)
    i2c = I2C(0, scl=Pin(20), sda=Pin(22), freq=400000)

    tca_select(i2c, 0)

    devices = i2c.scan()
    if MAX30102_ADDR in devices:
        print("MAX30102 found at 0x%02X" % MAX30102_ADDR)

        sensor = MAX30102(i2c)

        ir_buffer = []          # Store recent IR samples
        last_hr_print_ms = time.ticks_ms()

        while True:
            samples = sensor.read_fifo()
            if samples:
                for ir, red in samples:
                    # Append IR sample to buffer
                    ir_buffer.append(ir)
                    if len(ir_buffer) > MAX_SAMPLES * 2:
                        # Keep buffer from growing too large
                        ir_buffer = ir_buffer[-MAX_SAMPLES:]

                    # (Optional) print raw values for debugging
                    # print("IR:", ir, "Red:", red)

                # Estimate HR every ~1 second
                now = time.ticks_ms()
                if time.ticks_diff(now, last_hr_print_ms) > 1000:
                    hr = estimate_hr_simple(ir_buffer)
                    if hr is not None:
                        print("Estimated HR: %.1f BPM" % hr)
                    else:
                        print("Estimating HR... (need more/cleaner data)")
                    last_hr_print_ms = now

            # Small delay to avoid busy loop
            time.sleep_ms(10)

    else:
        print("ERROR: MAX30102 not found on I2C bus.")
        print("Scanned devices:", [hex(d) for d in devices])

except Exception as e:
    print("Error:", e)
