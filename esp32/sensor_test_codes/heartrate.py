# 导入所需要的库
from machine import Pin, I2C
import time

# --- 根据数据手册定义常量 ---
MAX30102_ADDR = 0x57

# 寄存器地址
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


class MAX30102:
    def __init__(self, i2c):
        self.i2c = i2c
        # 检查设备ID
        part_id = self._read_reg(REG_PART_ID)
        if part_id != 0x15:
            raise Exception("MAX30102 not found")
        self.setup()

    def _read_reg(self, reg, n_bytes=1):
        """ 读取寄存器 """
        val = self.i2c.readfrom_mem(MAX30102_ADDR, reg, n_bytes)
        return val[0] if n_bytes == 1 else val

    def _write_reg(self, reg, val):
        """ 写入寄存器 """
        self.i2c.writeto_mem(MAX30102_ADDR, reg, bytes([val]))

    def setup(self):
        """ 配置传感器 """
        # 重置传感器
        self._write_reg(REG_MODE_CONFIG, 0x40)
        time.sleep_ms(100)

        # 配置 FIFO: 采样平均=4, FIFO 满时循环写入, FIFO 几乎满中断在剩 15 个空位时触发
        self._write_reg(REG_FIFO_CONFIG, 0x5F)

        # 模式配置: SpO2 模式
        self._write_reg(REG_MODE_CONFIG, 0x03)

        # SpO2 配置: ADC 量程=4096nA, 采样率=100sps, 脉宽=411us (18-bit)
        self._write_reg(REG_SPO2_CONFIG, 0x27)

        # LED 亮度配置 (0x24 约 7mA, 这是一个不错的起点)
        self._write_reg(REG_LED1_PA, 0x24)  # Red LED
        self._write_reg(REG_LED2_PA, 0x24)  # IR LED

        # 清空 FIFO 指针
        self._write_reg(REG_FIFO_WR_PTR, 0)
        self._write_reg(REG_OVF_COUNTER, 0)
        self._write_reg(REG_FIFO_RD_PTR, 0)
        print("MAX30102 配置完成。")

    def read_fifo(self):
        """ 从 FIFO 中读取数据 """
        # 读取中断状态以清除
        self._read_reg(REG_INT_STATUS_1)

        # 读取 FIFO 读写指针
        read_ptr = self._read_reg(REG_FIFO_RD_PTR)
        write_ptr = self._read_reg(REG_FIFO_WR_PTR)

        # 计算可用样本数
        num_samples = write_ptr - read_ptr
        if num_samples < 0:
            num_samples += 32

        if num_samples > 0:
            # 读取 6 字节 (1 个样本)
            data = self._read_reg(REG_FIFO_DATA, 6)

            # 组合 3 个字节为一个 18 位数据
            # 屏蔽掉最高的 2 个未用位
            ir_val = ((data[0] << 16) | (data[1] << 8) | data[2]) & 0x03FFFF
            red_val = ((data[3] << 16) | (data[4] << 8) | data[5]) & 0x03FFFF

            return ir_val, red_val
        else:
            return None, None


# --- 主程序 ---
try:
    # --- 初始化 I2C 总线 ---
    # 请根据你的 ESP32 开发板和接线修改 SCL 和 SDA 引脚号
    i2c = I2C(0, scl=Pin(20), sda=Pin(22), freq=400000)

    devices = i2c.scan()
    if MAX30102_ADDR in devices:
        print(f"在地址 0x{MAX30102_ADDR:02x} 找到 MAX30102 传感器！")

        sensor = MAX30102(i2c)

        while True:
            ir, red = sensor.read_fifo()
            # 只有当有新数据时才打印
            if ir is not None and red is not None:
                # 打印的是原始的 ADC 计数值，反映了光的反射强度
                print(f"IR: {ir}, Red: {red}")
            time.sleep_ms(100)  # 每 100ms 检查一次

    else:
        print("错误: 未在 I2C 总线上找到 MAX30102 传感器。")
        print("请检查接线或传感器地址。")
        if devices:
            print(f"扫描到的设备地址: {[hex(d) for d in devices]}")

except Exception as e:
    print(f"发生错误: {e}")
