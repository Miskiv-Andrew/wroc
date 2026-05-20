# devices/device_package.py

class DevicePacket:
    def __init__(self, serial_number: str, buff: bytearray, mode: str):
        self.serial_number = serial_number   # строка, серийный номер прибора
        self.buff = buff                     # bytearray, сырые данные
        self.size = len(buff)                # int, размер массива buff
        self.mode = mode                     # строка, режим опроса (спектр, ПАЕД и т.д.)
