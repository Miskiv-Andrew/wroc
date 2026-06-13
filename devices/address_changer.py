import serial
import serial.tools.list_ports
import time
from PySide6.QtCore import QObject, Signal

from devices.commands import COMMAND_SER_NUM, COMMAND_CHANGE_ADDRESS
from devices.device_manager import DeviceManager


class AddressChanger(QObject):
    found = Signal(str, str, int)
    status = Signal(str)
    error = Signal(str)
    
    # def __init__(self):
    #     super().__init__()
    #     self.device_manager = DeviceManager()

    def __init__(self, db_manager):
        super().__init__()
        self.device_manager = DeviceManager(db_manager)
    
    def find_new_device(self, addresses=[200, 201], timeout=0.5):
        available_ports = self._get_available_ports()
        
        for port_name in available_ports:
            for addr in addresses:
                try:
                    with serial.Serial(port_name, baudrate=19200, timeout=timeout) as ser:
                        packet = bytearray(COMMAND_SER_NUM.data)
                        packet[3] = addr
                        crc = self.device_manager.calc_crc(packet)
                        packet.append(crc)
                        
                        ser.write(packet)
                        time.sleep(timeout)
                        
                        response = ser.read(COMMAND_SER_NUM.length)
                        if len(response) != COMMAND_SER_NUM.length:
                            continue
                        
                        if not self.device_manager.verify_crc(bytearray(response)):
                            continue
                        
                        serial_number = self._extract_serial_number(response)
                        
                        if serial_number:
                            self.found.emit(port_name, serial_number, addr)
                            self.status.emit(f"Знайдено прилад: SN {serial_number}")
                            return (port_name, serial_number, addr)
                            
                except serial.SerialException as e:
                    self.error.emit(f"Помилка порту {port_name}: {e}")
                    continue
        
        self.status.emit("Новий прилад не знайдено")
        return (None, None, None)
    
    def change_address(self, port, old_address, new_address, expected_sn, timeout=1.0, retries=3):
        for attempt in range(retries):
            try:
                with serial.Serial(port, baudrate=19200, timeout=timeout) as ser:
                    cmd = bytearray(COMMAND_CHANGE_ADDRESS.data)
                    cmd[3] = old_address
                    cmd[5] = new_address
                    crc = self.device_manager.calc_crc(cmd)
                    cmd.append(crc)
                    
                    ser.write(cmd)
                    time.sleep(timeout)
                    
                    response = ser.read(COMMAND_CHANGE_ADDRESS.length)
                    
                    if len(response) != COMMAND_CHANGE_ADDRESS.length:
                        self.error.emit(f"Спроба {attempt+1}: Неправильна довжина відповіді")
                        continue
                    
                    if not self.device_manager.verify_crc(bytearray(response)):
                        self.error.emit(f"Спроба {attempt+1}: Помилка CRC")
                        continue
                    
                    if response[3] != old_address:
                        self.error.emit(f"Спроба {attempt+1}: Неправильна відповідь адреси")
                        continue
                    
                    self.status.emit(f"Адресу приладу {expected_sn} змінено з {old_address} на {new_address}")
                    return True
                    
            except serial.SerialException as e:
                self.error.emit(f"Спроба {attempt+1}: Помилка порту: {e}")
                continue
        
        self.error.emit(f"Не вдалося змінити адресу після {retries} спроб")
        return False
    
    def _get_available_ports(self):
        ports = serial.tools.list_ports.comports()
        available = []
        for port in ports:
            is_ftdi = False
            if port.vid is not None and port.vid == 0x0403:
                is_ftdi = True
            if not is_ftdi and port.manufacturer and "FTDI" in port.manufacturer:
                is_ftdi = True
            if is_ftdi:
                available.append(port.device)
        return available
    
    def _extract_serial_number(self, data: bytearray) -> str:
        if len(data) < 9:
            return ""
        s = chr((data[8] & 0x0F) + ord('0'))
        for i in range(7, 4, -1):
            high_self = (data[i] >> 4) & 0x0F
            low_self = data[i] & 0x0F
            s += chr(high_self + ord('0')) + chr(low_self + ord('0'))
        return s