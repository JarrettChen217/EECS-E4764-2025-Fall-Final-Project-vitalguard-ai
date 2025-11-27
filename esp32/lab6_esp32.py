# ===== Smartwatch HAR: Streaming & On-Demand Prediction =====
#
# This version streams accelerometer data point-by-point and then
# triggers a prediction from the server on-demand.

import network
import urequests
import time
import struct
from machine import Pin, SPI, I2C
from ssd1306 import SSD1306_I2C

# ===== OLED Display Configuration =====
OLED_WIDTH = 128
OLED_HEIGHT = 32
OLED_SCL_PIN = 20
OLED_SDA_PIN = 22

i2c = I2C(0, scl=Pin(OLED_SCL_PIN), sda=Pin(OLED_SDA_PIN))
oled = SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c)


def show_text(line1, line2="", line3=""):
    """Utility function to display three lines of text on the OLED."""
    oled.fill(0)
    oled.text(line1, 0, 0)
    oled.text(line2, 0, 10)
    oled.text(line3, 0, 25)
    oled.show()


# ===== ADXL345 Accelerometer SPI Driver =====
# (This class remains unchanged from your original code)
class PhysicsEngine:
    # ADXL345 Constants
    SPI_READ = 0x80
    SPI_MULTI_BYTE = 0x40
    DEVID = 0x00
    POWER_CTL = 0x2D
    DATAX0 = 0x32
    SCALE_FACTOR = 0.004

    # Physics arguments
    DAMPING = 0.95
    ACCEL_SENSITIVITY = 0.2
    TEXT_BLOCK_WIDTH = 56
    TEXT_BLOCK_HEIGHT = 16

    def __init__(self, spi, cs, oled_width, oled_height):

        self.disable = False

        self.spi = spi
        self.cs = cs
        self.oled_width = oled_width
        self.oled_height = oled_height

        self.text_x = self.oled_width / 4
        self.text_y = self.oled_height / 4
        self.vel_x = 0
        self.vel_y = 0

        self._initialize_adxl345()

    def _write_reg(self, reg, value):
        self.cs.value(0)
        self.spi.write(bytearray([reg, value]))
        self.cs.value(1)

    def _read_regs(self, reg, n_bytes):
        self.cs.value(0)
        cmd = self.SPI_READ | self.SPI_MULTI_BYTE | reg
        self.spi.write(bytearray([cmd]))
        buf = bytearray(n_bytes)
        self.spi.readinto(buf)
        self.cs.value(1)
        return buf

    def _initialize_adxl345(self):
        print("Checking ADXL345...")
        self.cs.value(0)
        self.spi.write(bytearray([self.SPI_READ | self.DEVID]))
        device_id = self.spi.read(1)[0]
        self.cs.value(1)

        if device_id != 0xE5:
            raise RuntimeError("ADXL345 not found!")

        print("ADXL345 detected. Initializing...")
        self._write_reg(self.POWER_CTL, 0x08)

    def get_accel_data(self):
        data = self._read_regs(self.DATAX0, 6)
        x_raw = (data[1] << 8) | data[0]
        y_raw = (data[3] << 8) | data[2]
        z_raw = (data[5] << 8) | data[4]
        if x_raw & (1 << 15): x_raw -= (1 << 16)
        if y_raw & (1 << 15): y_raw -= (1 << 16)
        if z_raw & (1 << 15): z_raw -= (1 << 16)

        x_g = x_raw * self.SCALE_FACTOR
        y_g = y_raw * self.SCALE_FACTOR
        z_g = z_raw * self.SCALE_FACTOR

        return x_g, y_g, z_g

    def update_position(self):
        if self.disable:
            return

        x_g, y_g, _ = self.get_accel_data()

        self.vel_x += x_g * self.ACCEL_SENSITIVITY
        self.vel_y += y_g * self.ACCEL_SENSITIVITY
        self.vel_x *= self.DAMPING
        self.vel_y *= self.DAMPING
        self.text_x -= self.vel_x
        self.text_y += self.vel_y

        # Wrap around strategy
        if self.text_x > self.oled_width:
            self.text_x = -self.TEXT_BLOCK_WIDTH
        elif self.text_x + self.TEXT_BLOCK_WIDTH < 0:
            self.text_x = self.oled_width
        if self.text_y > self.oled_height:
            self.text_y = -self.TEXT_BLOCK_HEIGHT
        elif self.text_y + self.TEXT_BLOCK_HEIGHT < 0:
            self.text_y = self.oled_height

    def disable_physics(self):
        self.disable = True
        self.text_x = self.oled_width / 4
        self.text_y = self.oled_height / 4

class HardwareManager:
    def __init__(self):
        print("Initializing hardware...")
        # --- I2C and OLED ---
        # self.i2c = I2C(0, scl=Pin(20), sda=Pin(22))
        # self.oled = SSD1306_I2C(128, 32, self.i2c)
        # self.OLED_WIDTH = 128
        # self.OLED_HEIGHT = 32

        # --- SPI and ADXL345 ---
        self.spi = SPI(1, baudrate=5000000, polarity=1, phase=1, sck=Pin(5), mosi=Pin(19), miso=Pin(21))
        self.cs = Pin(15, Pin.OUT, value=1)

        # # --- RTC ---
        # self.rtc = RTC()
        #
        # # --- Buttons ---
        # self.btn_select = Pin(32, Pin.IN, Pin.PULL_UP)
        # self.btn_inc = Pin(33, Pin.IN, Pin.PULL_UP)
        # self.btn_dec = Pin(27, Pin.IN, Pin.PULL_UP)
        #
        # # --- ADC Sensor for Brightness ---
        # self.ldr = ADC(Pin(36))
        # self.ldr.atten(ADC.ATTN_11DB)
        # self.ldr.width(ADC.WIDTH_12BIT)
        #
        # # --- LED and Buzzer ---
        # self.led = Pin(26, Pin.OUT)
        # self.buzzer = PWM(Pin(14))
        # self.buzzer.duty_u16(0)
        print("Hardware initialized.")


# ===== Hardware Initialization =====
hw = HardwareManager()
sensor = PhysicsEngine(hw.spi, hw.cs, OLED_WIDTH, OLED_HEIGHT)
time.sleep(1)

# ===== WiFi Configuration =====
WIFI_SSID = "Columbia University"
WIFI_PASS = ""


def connect_wifi():
    """Connects the device to WiFi."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID)
    while not wlan.isconnected():
        show_text("WiFi Connecting")
        time.sleep(0.5)
    show_text("WiFi OK")
    print("WiFi Connected:", wlan.ifconfig())

connect_wifi()
time.sleep(1)

# ===== HAR Service Configuration =====
# IMPORTANT: Use the IP address of the machine running your Flask server
SERVER_IP = "136.115.219.129"  # <-- Change to your PC's IP address
SERVER_PORT = 9999
BASE_URL = f"http://{SERVER_IP}:{SERVER_PORT}"
ACCEL_API_URL = f"{BASE_URL}/api/accelerometer"
PREDICT_API_URL = f"{BASE_URL}/api/har_predict"
# PREDICT_API_URL = f"{BASE_URL}/api/har_predict_torch"


# ===== HAR Parameters =====
SAMPLING_FREQ_HZ = 20  # 20 Hz sampling rate
WINDOW_SIZE = 128  # We need 128 points to trigger a prediction

show_text("HAR Ready", f"Win: {WINDOW_SIZE}pts", f"Freq: {SAMPLING_FREQ_HZ}Hz")
time.sleep(2)

data_window = []

# ===== Main Application Loop =====
while True:
    # 1. Read data from the accelerometer
    try:
        ax, ay, az = sensor.get_accel_data()
    except Exception as e:
        print(f"ERROR: Failed to read from sensor: {e}")
        time.sleep(1)
        continue  # Skip this loop iteration
    # 2. Construct the JSON payload for a single data point

    point = {
        "x": ax,
        "y": ay,
        "z": az
    }

    data_window.append(point)

    points_collected = len(data_window)
    print(f"INFO: Collected point {points_collected}/{WINDOW_SIZE}")
    show_text("Collecting...", f"Pts: {points_collected}/{WINDOW_SIZE}")

    # 4. Check if a full window of data has been sent
    if points_collected >= WINDOW_SIZE:
        print("INFO: Full window collected. Sending data and triggering prediction...")
        show_text("Streaming...", f"{WINDOW_SIZE} Pts")
        # 4. Prepare the payload for the entire window.
        payload = {
            "data": data_window
        }
        # 3. Stream the data point to the server
        try:
            # We don't need to check the response for every point to save time.
            # A timeout is set to prevent the loop from blocking.
            urequests.post(ACCEL_API_URL, json=payload, timeout=5)
            print(f"INFO: Sent point ")
            data_window = []  # Clear the window after sending

        except Exception as e:
            print(f"ERROR: Failed to send data point: {e}")
            show_text("Net Fail", "Data Send")
            time.sleep(1)  # Wait before retrying

        print("INFO: Full window sent. Triggering prediction...")
        show_text("Requesting...", "Prediction")

        try:
            # 5. Call the prediction API
            res = urequests.get(PREDICT_API_URL, timeout=45)
            result_json = res.json()
            res.close()

            # 6. Parse the response and display the result
            if result_json.get("success"):
                activity = result_json.get("prediction", {}).get("label", "UNKNOWN")
                print(f"SUCCESS: Predicted Activity: {activity}")
                show_text("Activity:", f"-> {activity.upper()}")
            else:
                error_msg = result_json.get("error", {}).get("code", "API_ERROR")
                print(f"ERROR: API returned an error: {error_msg}")
                show_text("API Error", error_msg)

        except Exception as e:
            print(f"ERROR: Failed to get prediction: {e}")
            show_text("Net Fail", "Predict GET")

        # 7. Reset the counter and wait before starting the next window
        print("INFO: Resetting window counter.")
        points_sent_in_window = 0
        time.sleep(2)  # Pause to display the result on the screen

    # 8. Control the sampling frequency
    time.sleep(1.0 / SAMPLING_FREQ_HZ)
