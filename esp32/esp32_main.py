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
INT → A0 (GPIO25) (optional, interrupt pin)
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

    def read_temp_raw(self):    # Read raw temperature value (16-bit)
        self.i2c.writeto(HDC1080_ADDR, b'\x00')
        time.sleep_ms(15)
        d = self.i2c.readfrom(HDC1080_ADDR, 2)
        return (d[0] << 8) | d[1]

    def read_humi_raw(self):    # Read raw humidity value (16-bit)
        self.i2c.writeto(HDC1080_ADDR, b'\x01')
        time.sleep_ms(15)
        d = self.i2c.readfrom(HDC1080_ADDR, 2)
        return (d[0] << 8) | d[1]


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
#    Pressure sensor via ADC (GPIO25)
##################################################

fsr_pin = ADC(Pin(25))
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
# 8. CONTINUOUS STREAMING MODE
# Continuously send sensor JSON packets to computer
##################################################

print("Start continuous streaming")

last_send = time.ticks_ms()

while True:

    # MAX30102 — CH0
    tca_select(i2c, 0)
    red, ir = sensor_ppg.read_sample()

    # HDC1080 — CH1
    tca_select(i2c, 1)
    t_raw = sensor_hdc.read_temp_raw()
    h_raw = sensor_hdc.read_humi_raw()

    # ADXL345 — CH2
    tca_select(i2c, 2)
    ax, ay, az = sensor_acc.read_xyz()

    # FSR402 (ADC)
    fsr_raw = read_fsr()

    # Send every 200ms
    if time.ticks_diff(time.ticks_ms(), last_send) > 200:

        packet = {
            "MAX30102_CH0": { "ir": ir, "red": red },
            "HDC1080_CH1": { "temp_raw": t_raw, "humi_raw": h_raw },
            "ADXL345_CH2": { "ax": ax, "ay": ay, "az": az },
            "FSR402_ADC25": fsr_raw,
            "timestamp_ms": time.ticks_ms()
        }

        print(ujson.dumps(packet))
        last_send = time.ticks_ms()

    time.sleep_ms(5)
