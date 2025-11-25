# 导入所需要的库
from machine import Pin, I2C
import time

# --- 传感器常量定义 (与之前相同) ---
MAX30102_ADDR = 0x57
# ... (其他寄存器地址与之前代码一致)
REG_INT_STATUS_1 = 0x00
REG_MODE_CONFIG = 0x09
REG_FIFO_WR_PTR = 0x04
REG_FIFO_RD_PTR = 0x06
REG_FIFO_DATA = 0x07
REG_FIFO_CONFIG = 0x08
REG_SPO2_CONFIG = 0x0A
REG_LED1_PA = 0x0C
REG_LED2_PA = 0x0D
REG_PART_ID = 0xFF


class MAX30102:
    # ... (这个类的代码与之前完全相同) ...
    def __init__(self, i2c):
        self.i2c = i2c
        part_id = self._read_reg(REG_PART_ID)
        if part_id != 0x15:
            raise Exception("MAX30102 not found")
        self.setup()

    def _read_reg(self, reg, n_bytes=1):
        val = self.i2c.readfrom_mem(MAX30102_ADDR, reg, n_bytes)
        return val[0] if n_bytes == 1 else val

    def _write_reg(self, reg, val):
        self.i2c.writeto_mem(MAX30102_ADDR, reg, bytes([val]))

    def setup(self):
        self._write_reg(REG_MODE_CONFIG, 0x40)
        time.sleep_ms(100)
        self._write_reg(REG_FIFO_CONFIG, 0x5F)
        self._write_reg(REG_MODE_CONFIG, 0x03)
        self._write_reg(REG_SPO2_CONFIG, 0x27)
        self._write_reg(REG_LED1_PA, 0x24)
        self._write_reg(REG_LED2_PA, 0x24)
        self._write_reg(REG_FIFO_WR_PTR, 0)
        self._write_reg(REG_FIFO_RD_PTR, 0)
        print("MAX30102 配置完成。")

    def read_fifo(self):
        self._read_reg(REG_INT_STATUS_1)
        read_ptr = self._read_reg(REG_FIFO_RD_PTR)
        write_ptr = self._read_reg(REG_FIFO_WR_PTR)
        num_samples = write_ptr - read_ptr
        if num_samples < 0:
            num_samples += 32

        if num_samples > 0:
            data = self._read_reg(REG_FIFO_DATA, 6)
            ir_val = ((data[0] << 16) | (data[1] << 8) | data[2]) & 0x03FFFF
            red_val = ((data[3] << 16) | (data[4] << 8) | data[5]) & 0x03FFFF
            return ir_val, red_val
        else:
            return None, None


class HeartRateMonitor:
    """ 一个简单的心率监视器类 """

    def __init__(self, history_size=100):
        self.history = []
        self.history_size = history_size
        self.bpm = 0
        self.beat_detected = False
        self.last_beat_time = 0

    def check_for_beat(self, ir_value):
        # FIX: need fix, cannot provide reliable data.
        # 简单阈值检测 - 你可能需要根据实际情况调整这个值
        # 当你的手指稳定放在传感器上时，观察 IR 值的范围，取一个中间偏上的值
        IR_THRESHOLD = 5000

        # 当信号超过阈值，并且之前是低于阈值的状态，我们认为检测到了一个节拍
        if ir_value > IR_THRESHOLD and not self.beat_detected:
            self.beat_detected = True
            current_time = time.ticks_ms()

            # 确保这不是第一次检测
            if self.last_beat_time != 0:
                time_diff = time.ticks_diff(current_time, self.last_beat_time)
                # 避免因抖动等原因产生过高的心率值
                if time_diff > 250:  # 对应最高心率 240 bpm
                    self.bpm = 60 * 1000.0 / time_diff

            self.last_beat_time = current_time
            return True  # 返回 True 表示检测到节拍

        # 当信号低于阈值，重置检测状态
        elif ir_value < IR_THRESHOLD and self.beat_detected:
            self.beat_detected = False

        return False  # 没有检测到新节拍


# --- 主程序 ---
try:
    i2c = I2C(0, scl=Pin(20), sda=Pin(22), freq=400000)
    devices = i2c.scan()
    if MAX30102_ADDR in devices:
        print(f"在地址 0x{MAX30102_ADDR:02x} 找到 MAX30102 传感器！")

        sensor = MAX30102(i2c)
        monitor = HeartRateMonitor()

        while True:
            ir, red = sensor.read_fifo()
            if ir is not None:
                if monitor.check_for_beat(ir):
                    print(f"检测到心跳! BPM: {monitor.bpm:.2f}")
                else:
                    # 为了不刷屏太快，可以只在没有检测到心跳时打印原始值
                    print(f"IR: {ir}, Red: {red}")
            time.sleep_ms(20)  # 稍微加快读取速度

    else:
        print("错误: 未在 I2C 总线上找到 MAX30102 传感器。")

except Exception as e:
    print(f"发生错误: {e}")

