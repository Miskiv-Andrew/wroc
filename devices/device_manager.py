# devices/device_manager.py
from PySide6.QtCore import QObject, Signal, QTimer
import serial.tools.list_ports
from devices.device_info import DeviceInfo
from devices.device_package import DevicePacket

from devices.commands import (
    COMMAND_RAD_DOSE,
    COMMAND_SER_NUM,
    COMMAND_RAD_INTENS,
    COMMAND_TEMP,
    COMMAND_START_SIMPLE_SPECTRE,
    COMMAND_GET_SIMPLE_SPECTRE
)

import time
import hashlib
import struct

from enum import Enum, auto

class PollState(Enum):
    IDLE = auto()                  # ожидание запуска
    POLLING = auto()               # готов к отправке запроса (короткий таймер)
    WAITING_FOR_RESPONSE = auto()  # запрос отправлен, ждём ответ
    # CYCLE_COMPLETE = auto()        # полный обход завершён
    


class DeviceManager(QObject):
    # сигналы для связи с GUI
    # сигнал результата поиска портов
    ports_updated = Signal(list)
    # сигнал результата поиска девайсов
    device_found = Signal(list) 
    # первый параметр — источник ошибки (например, "config.txt"), второй — текст ошибки
    device_error = Signal(str, str)  
   
                           

    def __init__(self):

        super().__init__()

        # список найденных устройств
        self.devices: list[DeviceInfo] = []

        # список доступных портов RPII-6BD
        self.available_ports: list[str] = []

        
        # основной таймер опроса приборов
        self.poll_timer = QTimer()
        self.poll_timer.setSingleShot(True)
        self.poll_timer.timeout.connect(self.dispatch_poll_step)

        # таймер контроля неответа прибора
        self.error_timer = QTimer()
        self.error_timer.setSingleShot(True)
        self.error_timer.timeout.connect(self.handle_timeout)

################################################ БЛОК РАБОТЫ С КОНФИГУРАЦИОННЫМ ФАЙЛОМ  И ФАЙЛОМ ХЕША ######################################################

    def verify_config_file(self) -> bool:
        """
            Проверяет целостность файла config.txt по контрольной сумме SHA-256.
            Сравнивает вычисленный хэш с эталонным значением из hash.txt.
            
            Возвращает:
                True  - если контрольная сумма совпадает
                False - если контрольная сумма не совпадает или произошла ошибка
            
            В случае ошибки или несовпадения вызывает сигнал config_error,
            чтобы передать информацию в app.py.
        """
        
        try:
            # Открываем config.txt в бинарном режиме и читаем содержимое
            with open("devices/config.txt", "rb") as f:
                file_data = f.read()

            # Вычисляем SHA-256 хэш
            sha256_hash = hashlib.sha256(file_data).hexdigest()

            # Загружаем эталонное значение хэша из hash.txt
            with open("devices/hash.txt", "r") as h:
                stored_hash = h.read().strip()

            # Сравниваем вычисленный хэш с эталонным
            if sha256_hash == stored_hash:
                return True
            else:
                # Если не совпадает — отправляем сигнал об ошибке
                self.device_error.emit("config.txt", "Контрольная сумма не совпадает")
                return False

        except Exception as e:
            # Если произошла ошибка при чтении или вычислении — отправляем сигнал
            self.device_error.emit("config.txt", f"Ошибка проверки: {e}")
            return False

######################################################################################################################################################

    def find_rpii_ports(self):
        """
        Поиск доступных COM-портов, фильтрация по производителю FTDI.
        Сохраняем только нужные порты в self.available_ports.
        """
        self.available_ports.clear()

        ports = serial.tools.list_ports.comports()

        for port in ports:
            # port.manufacturer может содержать строку "FTDI"
            if port.manufacturer and "FTDI" in port.manufacturer:
                self.available_ports.append(port.device)

        # уведомляем GUI, что список портов обновился, и передаем список портов        
        self.ports_updated.emit(self.available_ports)


    def try_request(self, ser, package: bytes, addr: int, pause: float, expected_length: int) -> bytearray | None:
        """
        Универсальный метод отправки пакета и проверки ответа.
        - ser: объект COM-порта
        - package: базовый пакет команды (без CRC и адреса)
        - addr: адрес прибора
        - pause: время ожидания ответа
        - expected_length: ожидаемая длина ответа
        Возвращает валидный пакет или None.
        """

        def _send_once() -> bytearray | None:
            # Формируем пакет: вставляем адрес в 3-й байт
            packet = bytearray(package)
            packet[3] = addr

            # Считаем CRC и добавляем в конец
            crc = self.calc_crc(packet)
            packet.append(crc)

            # Отправляем пакет
            ser.write(packet)
            time.sleep(pause)

            # Читаем ответ
            response = ser.read_all()
            if not response:
                return None

            # Проверяем длину
            if len(response) < expected_length:
                return None

            # Находим начало пакета (0x55, 0xAA)
            start_index = response.find(b"\x55\xAA")
            if start_index == -1:
                ser.reset_input_buffer()
                return None

            # Отбрасываем мусор до заголовка
            response = response[start_index:]

            # Если длина больше ожидаемой — лишнее отбрасываем
            if len(response) > expected_length:
                response = response[:expected_length]

            # Проверяем CRC
            if not self.verify_crc(response):
                ser.reset_input_buffer()
                return None

            return response

        # Первая попытка
        resp = _send_once()
        if resp is not None:
            return resp

        # Повтор через 1 сек
        time.sleep(1.0)
        return _send_once()


    def scan_devices(self):
        """
        Опрос всех доступных портов и адресов (1..6).
        Для каждого адреса отправляется запрос серийного номера.
        Ответ проверяется по длине, заголовку, CRC.
        При успешном ответе формируется объект DeviceInfo.
        """

        self.devices.clear()

        for port_name in self.available_ports:
            try:
                with serial.Serial(port_name, baudrate=19200, timeout=0.5) as ser:
                    for addr in range(1, 7):
                        # Запрос серийного номера
                        response = self.try_request(
                            ser = ser,
                            package = COMMAND_SER_NUM.data,
                            addr = addr,
                            pause = 0.5,
                            expected_length = COMMAND_SER_NUM.length
                        )

                        if response is None:                            
                            continue

                        # Извлекаем серийный номер
                        serial_number = self._ser_num_data(response)

                        # Записываем данные в объект DeviceInfo
                        device = DeviceInfo(
                            port = port_name,
                            address = addr,
                            device_type = "БДБГ-09S-23",  
                            serial_number = serial_number,
                            description = "Прилад виявлено"
                        )

                        # По умолчанию - заполненность = False
                        device.set_full(False)

                        # Добавляем прибор к списку приборов
                        self.devices.append(device)

            except serial.SerialException as e:
                print(f"Ошибка открытия порта {port_name}: {e}")


        

        # Проводим сверку и заполнение данными конфигурационного файла
        if self.verify_config_file():
            self.match_devices_with_config()


    def match_devices_with_config(self):
        """
            Сопоставляет найденные приборы (self.devices) с данными из config.txt.
                - Загружает config.txt
                - Для каждого прибора ищет запись по серийному номеру
                - Дополняет объект DeviceInfo параметрами location_type, posit_number, expected_address
                - Проверяет совпадение адреса прибора с ожидаемым из config.txt
                - Если прибор отсутствует или адрес не совпадает — отправляет сигнал ошибки в app.py
                - В конце отправляет обновлённый список приборов через сигнал devices_updated
        """

        try:
            # Загружаем config.txt
            config_data = {}
            with open("devices/config.txt", "r") as f:
                for line in f:
                    # Пропускаем комментарии и пустые строки
                    if line.startswith("#") or not line.strip():
                        continue
                    # Разбираем строку: serial_number;location_type;posit_number;address
                    parts = line.strip().split(";")
                    if len(parts) == 4:
                        serial, loc_type, posit, addr = parts
                        config_data[serial] = {
                            "location_type": loc_type,
                            "posit_number": int(posit),
                            "expected_address": int(addr)
                        }

            # Сопоставляем найденные приборы с конфигурацией
            for device in self.devices:
                if device.serial_number in config_data:
                    cfg = config_data[device.serial_number]
                    device.location_type = cfg["location_type"]
                    device.posit_number = cfg["posit_number"]
                    device.expected_address = cfg["expected_address"]

                    # Проверяем совпадение адреса
                    if device.address != device.expected_address:
                        self.device_error.emit(
                            "config.txt",
                            f"Несовпадение адреса для прибора SN {device.serial_number}: "
                            f"ожидался {device.expected_address}, найден {device.address}"
                        )
                else:
                    # Прибор найден, но его нет в config.txt
                    self.device_error.emit(
                        "config.txt",
                        f"Прибор SN {device.serial_number} найден, но отсутствует в конфигурации"
                    )

            # Отправляем обновлённый список приборов в app.py
            self.device_found.emit(self.devices)

        except Exception as e:
            # Ошибка при чтении или обработке config.txt                                        
            self.device_error.emit("config.txt", f"Ошибка обработки файла: {e}")

################################################ БЛОК CRC ######################################################

    def calc_crc(self, buff: bytearray) -> int:
        """
            Функция расчета CRC для массива bytearray
        """ 
        crc = 0
        for b in buff:
            crc += b
            if (crc & 0x0100) == 0x0100:
                crc = (crc & 0xFF) + 1
        return crc

    def verify_crc(self, buff: bytearray) -> bool:
        """
            Функция контроля CRC для массив
            Возвращает True(совпало) или False(не совпало)
        """
        if len(buff) < 2:
            return False
        expected_crc = buff[-1]
        calculated_crc = self.calc_crc(buff[:-1])
        return calculated_crc == expected_crc
    

################################################ БЛОК МЕТОДОВ ДАННЫХ ПРИБОРОВ ######################################################
    

    def _ser_num_data(self, data: bytearray) -> str:
        """       
            Возвращает строку с серийным номером.
        """
        # начинаем с младших 4 бит байта 8
        s = chr((data[8] & 0x0F) + ord('0'))

        # идём от 7 до 5 включительно, в обратном порядке
        for i in range(7, 4, -1):
            high_self = (data[i] >> 4) & 0x0F
            low_self = data[i] & 0x0F
            s += chr(high_self + ord('0')) + chr(low_self + ord('0'))

        return s

    def _temp_data(self, data: bytearray, b1: int = 0) -> str | None:
        """       
            Возвращает строку с значением температуры
        """
        
        # Проверка валидности
        if data[4+b1] & 0x80:
            return None

        # Собираем слово из двух байтов
        temp_w = (data[3+b1]) | (data[4+b1] << 8)

        # Проверка знака
        if data[4+b1] & 0x10:
            temp_w = (~temp_w) & 0xFFF
            temp_w += 1
            sign = "-"
        else:
            sign = ""

        # Берём младшие 12 бит и делим на 16
        temp_r = (temp_w & 0xFFF) / 16.0
        return f"{sign}{temp_r:.1f}°C"
    

    def _rad_intens_data(self, data: bytearray) -> int:
        """
            Функция получает интенсивность излучения (CPS) за 100 мсек
            Возвращает INT значение интенсивности
        """
        byte5 = data[5]
        byte6 = data[6]        
        
        Intense = struct.unpack('<H', bytes([byte5, byte6]))[0]        
        
        return Intense
    
    def _paed_data(data: bytearray) -> dict:
        """
            Обработка данных ПАЕД
            Возвращает словарь с параметрами 
        """
        num = struct.unpack('<I', data[5:9])[0]   
        ped = 0
        
        byte_to_check = data[10]
        
        high_sens_detect_failure = True
        low_sens_detector_failure = True
        result_valid = True        
        
        if byte_to_check & 0b00000001:   # D0 = 1 - отказ высокочувствительного детектора
            high_sens_detect_failure = False     
        
        if byte_to_check & 0b00000010:   # D1 = 1 - отказ низкочувствительного детектора
            low_sens_detector_failure = False  
        
        if byte_to_check & 0b00000100:   # D2 = 1 - результат невалидный
            result_valid = False 
            
        if byte_to_check & 0b10000000:   # Коэффициент перерасчета ПЕД 
            ped = num * 0.1        
        else:
            ped = num * 0.01 
        
        return {
            "ped_value": ped,
            "high_sens_failure": high_sens_detect_failure,
            "low_sens_failure": low_sens_detector_failure,
            "result_valid": result_valid
        }
    










   
