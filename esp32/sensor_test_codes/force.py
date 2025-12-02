from machine import I2C, Pin, ADC
import time

fsr_pin = ADC(Pin(25))
fsr_pin.atten(ADC.ATTN_11DB)      # enable 0–3.3V
fsr_pin.width(ADC.WIDTH_12BIT)    # 12-bit precision

def read_fsr():
    return fsr_pin.read()

# Example usage
while True:
    force_value = read_fsr()
    print(f"Force Sensor Value: {force_value}")
    time.sleep(1)