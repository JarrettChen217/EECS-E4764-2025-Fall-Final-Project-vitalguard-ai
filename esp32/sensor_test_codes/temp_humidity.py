from machine import Pin, I2C
import time

# --- data handout constants ---
# I2C address of the HDC1080
HDC1080_ADDR = 0x40

# HDC1080 register addresses
CONFIG_REG = 0x02
TEMP_REG = 0x00
HUMID_REG = 0x01

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

# --- Initialize I2C bus ---
i2c = I2C(0, scl=Pin(20), sda=Pin(22), freq=400000)

tca_select(i2c, 1)

def configure_sensor():
    """
    Setup the HDC1080 sensor by writing to its configuration register.
    - Bit 12 = 1: continuous mode (temperature followed by humidity)
    - Bit 10 = 0: temp measurement resolution is 14 bits
    - Bit 9:8 = 00: humidity measurement resolution is 14 bits
    """
    config_data = b'\x10\x00'
    i2c.writeto_mem(HDC1080_ADDR, CONFIG_REG, config_data)
    print("传感器配置完成: 设置为 14 位分辨率，温湿度连续测量模式。")
    # 等待一小段时间让配置生效
    time.sleep_ms(15)


def read_temperature_humidity():
    """
    从 HDC1080 读取温度和湿度数据。
    """
    # 1. 触发一次测量
    # 向传感器的温度寄存器地址写入一个空字节，以启动温湿度测量序列
    i2c.writeto(HDC1080_ADDR, b'\x00')

    # 2. 等待测量完成 (14位分辨率需要约 13ms，我们等待 20ms 以确保稳定)
    time.sleep_ms(20)

    # 3. 读取 4 个字节的数据
    # 前 2 个字节是温度，后 2 个字节是湿度
    data = i2c.readfrom(HDC1080_ADDR, 4)

    # 4. 组合数据并将原始数据转换为实际值
    # 将两个字节（8位）合并成一个 16 位整数
    raw_temp = (data[0] << 8) | data[1]
    raw_humidity = (data[2] << 8) | data[3]

    # 应用数据手册中的转换公式
    temp_c = (raw_temp / 65536.0) * 165.0 - 40.0
    humidity_rh = (raw_humidity / 65536.0) * 100.0

    return temp_c, humidity_rh


# --- 主程序 ---
try:
    # 检查 I2C 总线上是否有设备
    devices = i2c.scan()
    if HDC1080_ADDR in devices:
        print(f"在地址 0x{HDC1080_ADDR:02x} 找到 HDC1080 传感器！")

        # 配置传感器
        configure_sensor()

        # 循环读取并打印数据
        while True:
            temp, humidity = read_temperature_humidity()

            # 使用 f-string 格式化输出，保留两位小数
            print(f"温度 (Temperature): {temp:.2f} °C, 相对湿度 (Humidity): {humidity:.2f} %RH")

            # 每隔 2 秒读取一次
            time.sleep(2)

    else:
        print("错误: 未在 I2C 总线上找到 HDC1080 传感器。")
        print("请检查接线或传感器地址是否正确。")
        if devices:
            print(f"扫描到的设备地址: {[hex(d) for d in devices]}")

except Exception as e:
    print(f"发生错误: {e}")

