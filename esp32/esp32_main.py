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

MAX_ADDR = 0x57

class MAX30102:
    def __init__(self, i2c):
        self.i2c = i2c

        # Configure sensor registers
        self.i2c.writeto_mem(MAX_ADDR, 0x09, bytes([0x40]))  # Rest
        time.sleep_ms(10)

        self.i2c.writeto_mem(MAX_ADDR, 0x08, bytes([0x4F]))  # FIFO config
        self.i2c.writeto_mem(MAX_ADDR, 0x09, bytes([0x03]))  # SpO2 mode
        self.i2c.writeto_mem(MAX_ADDR, 0x0A, bytes([0x2F]))  # 400Hz sample rate
        self.i2c.writeto_mem(MAX_ADDR, 0x0C, bytes([0x80]))  # LED RED
        self.i2c.writeto_mem(MAX_ADDR, 0x0D, bytes([0x80]))  # LED IR

    def read_sample(self):
        data = self.i2c.readfrom_mem(MAX_ADDR, 0x07, 6)
        red = ((data[0]<<16)|(data[1]<<8)|data[2]) & 0x3FFFF
        ir  = ((data[3]<<16)|(data[4]<<8)|data[5]) & 0x3FFFF
        return red, ir


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
SERVER_PORT = 9999
DEVICE_ID = "esp32_001"  # Modify as needed

BASE_URL = "http://%s:%d" % (SERVER_IP, SERVER_PORT)
VITALS_API_URL = BASE_URL + "/api/vitals"

# Batch configuration
BATCH_SIZE = 20  # <<< adjustable batch size


class VitalBatchSender:
    """
    Handles buffering of vital sign data points and sending them to server in batches.
    """

    def __init__(self, device_id, url, batch_size):
        self.device_id = device_id
        self.url = url
        self.batch_size = batch_size
        self.buffer = []

    def add_point(self, point):
        """
        Add a data point and send batch when buffer is full.
        """
        self.buffer.append(point)

        if len(self.buffer) >= self.batch_size:
            self._send_buffer()

    def _send_buffer(self):
        """
        Send buffered data as one batch to the server.
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
            resp = urequests.post(self.url, json=payload, timeout=10)
            print("Batch sent. Status:", resp.status_code)
            resp.close()

            # Clear buffer only if request did not raise exception
            self.buffer = []

        except Exception as e:
            # Log error; keep buffer so we might retry later
            print("ERROR: Failed to send batch:", e)
            # NOTE: You could add retry logic or buffer size limit here to avoid OOM.

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
    red, ir = sensor_ppg.read_sample()

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
    if time.ticks_diff(now_ms, last_send) > 200:
        last_send = now_ms

        force_value = fsr_raw

        cycle = cycle_counter.next()

        data_point = {
            "cycle": cycle,
            "timestamp": now_ms,
            "vital_signs": {
                "ppg": {
                    "ir": ir,
                    "red": red
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

    time.sleep_ms(5)
