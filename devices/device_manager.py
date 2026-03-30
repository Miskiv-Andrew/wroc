# devices/device_manager.py
from PySide6.QtCore import QObject, Signal, QTimer, Slot, QIODevice
from PySide6.QtSerialPort import QSerialPort



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
import json




class DeviceManager(QObject):
    # сигналы для связи с GUI

    # сигнал результата поиска портов ( уже не нужен )
    device_info = Signal(str)

    # сигнал результата поиска девайсов
    device_found = Signal(list) 

    # первый параметр — источник ошибки (например, "config.txt"), второй — текст ошибки
    device_error = Signal(str, str) 

    # сигнал передачи данных опроса в GUI
    device_response = Signal(object)   
                           

    def __init__(self):

        super().__init__()

        # список найденных устройств
        self.devices: list[DeviceInfo] = []

        # список доступных портов RPII-6BD
        self.available_ports: list[str] = []


        # Глобальный объект порта (один на все приборы)
        self.serial_port = QSerialPort(self)
        self.serial_port.setBaudRate(19200)

        # Подключаем сигнал readyRead к обработчику
        self.serial_port.readyRead.connect(self.handle_ready_read)

        
        # основной таймер опроса приборов
        self.poll_timer = QTimer(self)
        self.poll_timer.setSingleShot(True)
        self.poll_timer.timeout.connect(self.dispatch_poll_step)

        # таймер контроля неответа прибора
        self.error_timer = QTimer(self)
        self.error_timer.setSingleShot(True)
        self.error_timer.timeout.connect(self.handle_timeout_error)

        # Атрибуты опроса приборов
        self.rx_buffer           = bytearray()  # глобальный массив для приема ответов приборов
        self.current_index       = -1           # индекс текущего прибора в цикле                 
        self.short_interval_ms   = 3_000        # интервал между приборами
        self.long_interval_ms    = 20_000       # пауза между циклами
        self.timeout_interval_ms = 3_000        # таймаут ожидания неответа прибора
        self.max_retries         = 3            # максимально допустимое число неответов прибора  
        self.last_command = None                # хранит последнюю отправленную команду 
        self.temperature_index   = 0            # индекс температуры приборов -  каждый 10 цикл опроса получаем температуру

        # Атрибут выбора режима запуска - None = обычный режим, 1 = отладка
        self.debug_mode: int | None = None        

        # Список приборов в цистернах
        self.cistern_dict = {"2400089" : 1}   

        # Список приборов в помещении
        self.room_dict    = {"2400126" : 1, "2400127" : 2,  "2400128" : 3}   


############################################################ БЛОК  ЗАВЕРШЕНИЯ РАБОТЫ ############################################################



    @Slot()
    def stop_all(self):
        """
            Корректно останавливает таймеры, закрывает порт и сбрасывает состояния.
        """
        try:
            self.running = False
        except Exception:
            pass

        try:
            if hasattr(self, "poll_timer") and self.poll_timer.isActive():
                self.poll_timer.stop()
        except Exception:
            pass

        try:
            if hasattr(self, "error_timer") and self.error_timer.isActive():
                self.error_timer.stop()
        except Exception:
            pass

        try:
            # очистка приёмного буфера
            if hasattr(self, "rx_buffer"):
                self.rx_buffer.clear()
        except Exception:
            pass

        try:
            # корректное закрытие последовательного порта
            if hasattr(self, "serial_port") and self.serial_port.isOpen():
                self.serial_port.close()
        except Exception:
            pass

        try:
            # сброс служебных полей
            self.current_index = -1
            self.last_command = None
        except Exception:
            pass





############################################################ БЛОК  ПОИСКА ПРИБОРОВ ################################################################
    @Slot()
    def find_rpii_ports(self):
        """
            Поиск доступных COM-портов, фильтрация по производителю FTDI.
            Сохраняем только нужные порты в self.available_ports
            Если порты найдены, сразу приступаем к опросу приборов
        """
        self.available_ports.clear()

        ports = serial.tools.list_ports.comports()

        for port in ports:
            # port.manufacturer может содержать строку "FTDI"
            if port.manufacturer and "FTDI" in port.manufacturer:
                self.available_ports.append(port.device)

        # уведомляем GUI, что список портов обновился, и передаем список портов        
        # self.ports_updated.emit(self.available_ports)     

        # если порты найдены — сразу запускаем поиск приборов
        if self.available_ports:
            self.scan_devices()

        # порты не найдены —  сообщаем об ошибке 
        else:
            self.device_error.emit("find_rpii_ports", "Не знайдено жодного розширювачу портів RTII")



    def try_request(self, ser, package: bytes, addr: int, pause: float, expected_length: int) -> bytearray | None:
        """
            Метод отправки пакета и проверки ответа.
            - ser: объект COM-порта
            - package: базовый пакет команды (без CRC и адреса)
            - addr: адрес прибора
            - pause: время ожидания ответа
            - expected_length: ожидаемая длина ответа
            - возвращает валидный пакет "Серийный номер" или None.
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
    

    def verify_config_file(self) -> bool:
        """
            Проверяет целостность файла config.txt по контрольной сумме SHA-256.
            Сравнивает вычисленный хэш содержимого config.txt  с эталонным значением из hash.txt.
            
            Возвращает:
                True  - если контрольная сумма совпадает
                False - если контрольная сумма не совпадает или произошла ошибка
            
            В случае ошибки или несовпадения вызывает сигнал config_error,
            чтобы передать информацию в app.py.
        """
        
        try:
            # Открываем config.txt в бинарном режиме и читаем содержимое
            with open("config/config.txt", "rb") as f:
                file_data = f.read()

            # Вычисляем SHA-256 хэш
            sha256_hash = hashlib.sha256(file_data).hexdigest()

            # Загружаем эталонное значение хэша из hash.txt            
            with open("config/hash.txt", "r") as h:
                stored_hash = h.read().strip()

            # Сравниваем вычисленный хэш с эталонным
            if sha256_hash == stored_hash:
                return True
            else:
                # Если не совпадает — отправляем сигнал об ошибке
                self.device_error.emit("config.txt", "Помилка у конфігураційному файлі,\nфайл було змінено")
                return False

        except Exception as e:
            # Если произошла ошибка при чтении или вычислении — отправляем сигнал
            self.device_error.emit("config.txt", f"Помилка при відкритті конфігураційних файлів: {e}")
            return False


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
                with serial.Serial(port_name, baudrate = 19200, timeout = 0.5) as ser:
                    for addr in range(1, 7):
                        # Отправляем очередной запрос серийного номера
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

                        # По умолчанию цистерна пустая
                        device.set_full(False)                       

                        # Добавляем прибор в список приборов
                        self.devices.append(device)

            except serial.SerialException as e:
                print(f"Ошибка открытия порта {port_name}: {e}")

       
        # --- Режим отладки---
        if self.debug_mode == 1:
            # В режиме разработчика не проводим сверку - выодим найденные приборы и формируем новые конфигурационные файлы
            self.match_devices_with_config()
            return

        # --- Обычный режим ---
        if self.verify_config_file():
            self.match_devices_with_config()


    def load_config_file(self) -> dict:
        """
        Загружает конфигурацию из файла devices/config.txt.
        Возвращает словарь вида:
        {
            "2400126": {"location_type": "room", "posit_number": 1, "expected_address": 2},
            "2400089": {"location_type": "cistern", "posit_number": 3, "expected_address": 1},
            ...
        }
        """
        config_data = {}
        try:
            # with open("devices/config.txt", "r", encoding="utf-8") as f:
            with open("config/config.txt", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(";")
                    if len(parts) != 4:
                        continue
                    serial_number, location_type, posit_number, expected_address = parts
                    config_data[serial_number] = {
                        "location_type": location_type,
                        "posit_number": int(posit_number),
                        "expected_address": int(expected_address)
                    }
        except Exception as e:
            self.device_error.emit("config.txt", f"Ошибка загрузки конфигурации: {e}")
        return config_data  


    def match_devices_with_config(self):

        # Если приборов нет — не трогаем конфигурацию
        if not self.devices:
            self.device_error.emit("config.txt", "Порты RTII знайдено, але жодного приладу не виявлено. Конфігурацію не оновлена.")
            return

        # --- Режим настройки системы ---
        if self.debug_mode == 1:
            found_text = "Знайдено прилади:\n"
            for device in self.devices:
                found_text += f"Порт: {device.port}, Адреса: {device.address}, SN: {device.serial_number}\n"

            lines = []
            cistern_json_data = {}

            for device in self.devices:
                if device.serial_number in self.cistern_dict:
                    location_type = "cistern"
                    posit_number = self.cistern_dict[device.serial_number]
                    line = f"{device.serial_number};{location_type};{posit_number};{device.address}"
                    lines.append(line)
                    # В cistern.json храним состояние цистерн (по умолчанию False)
                    cistern_json_data[posit_number] = False

                elif device.serial_number in self.room_dict:
                    location_type = "room"
                    posit_number = self.room_dict[device.serial_number]
                    line = f"{device.serial_number};{location_type};{posit_number};{device.address}"
                    lines.append(line)

                else:
                    # Если SN не найден ни в одном словаре — сигнализируем
                    self.device_error.emit(
                        "config.txt",
                        f"SN {device.serial_number} не внесён в словари cistern_dict/room_dict"
                    )

            config_text = "# serial_number;location_type;posit_number;address\n" + "\n".join(lines)

            try:
                # Записываем config.txt
                with open("config/config.txt", "w", encoding="utf-8") as f:
                    f.write(config_text)

                # Читаем обратно и считаем хэш
                with open("config/config.txt", "rb") as f:
                    data = f.read()
                sha256_hash = hashlib.sha256(data).hexdigest()

                # Записываем hash.txt
                with open("config/hash.txt", "w", encoding="utf-8") as f:
                    f.write(sha256_hash)

                # Перезаписываем cistern.json
                with open("config/cistern.json", "w", encoding="utf-8") as f:
                    json.dump(cistern_json_data, f, ensure_ascii=False, indent=4)

                output_text = f"{found_text}\nНові дані занесено у файли конфігурації"
                self.device_info.emit(output_text)

            except Exception as e:
                self.device_error.emit("config", f"Помилка запису файлів: {e}")

            return

        # --- Обычный режим ---
        config_data = self.load_config_file()
        valid_devices = []

        for device in self.devices:
            if device.serial_number in config_data:
                cfg = config_data[device.serial_number]
                device.location_type = cfg["location_type"]
                device.posit_number = cfg["posit_number"]
                device.expected_address = cfg["expected_address"]

                if device.address != device.expected_address:
                    self.device_error.emit(
                        "config.txt",
                        f"Несовпадение адреса для SN {device.serial_number}: "
                        f"ожидался {device.expected_address}, найден {device.address}"
                    )
                    continue
                valid_devices.append(device)
            else:
                self.device_error.emit(
                    "config.txt",
                    f"SN {device.serial_number} найден, но отсутствует в конфигурации"
                )

        if valid_devices:
            """
                self.device_found.emit(valid_devices)
                Преобразуем каждый объект DeviceInfo в безопасный словарь.
                Это предотвращает передачу QObject/виджетов между потоками и
                позволяет GUI создавать виджеты исключительно в главном потоке.
            """
            serializable_list = [self._device_to_dict(d) for d in valid_devices]            

            # Эмитим список словарей. Слот в App должен ожидать list[dict].
            self.device_found.emit(serializable_list)


    def _device_to_dict(self, device):
        """
            Преобразует объект DeviceInfo в простой словарь с только теми полями,
            которые нужны GUI для создания/инициализации карточки прибора.

            Важно:
            - Возвращаемые значения — только простые типы (str, int, None и т.д.).
            - Никаких ссылок на QObject, QWidget или другие объекты, живущие в потоках.
            - Это делает передачу данных между потоками безопасной.
        """
        return {
            # уникальный идентификатор прибора (строка)
            "serial_number": getattr(device, "serial_number", None),

            # порт, к которому привязан прибор (строка, например "COM3" или "/dev/ttyUSB0")
            "port": getattr(device, "port", None),

            # адрес прибора в шине (int)
            "address": getattr(device, "address", None),

            # тип прибора для отображения (строка)
            "device_type": getattr(device, "device_type", None),

            # где установлен прибор: "cistern" или "room" (строка)
            "location_type": getattr(device, "location_type", None),

            # номер позиции/цистерны (int) — может быть None для room
            "posit_number": getattr(device, "posit_number", None),

            # реальный сенсор (например "G" или "S") — пригодится для логики спектра
            "real_sensor": getattr(device, "real_sensor", None)
        }


################################################ БЛОК CRC ######################################################  

    def calc_crc(self, buff: bytearray | bytes) -> int:
        """
            Функция расчета CRC для массива байтов
        """
        crc = 0
        # Приводим вход к обычному bytes, чтобы не было сюрпризов
        data = bytes(buff)

        for b in data:
            # b гарантированно int (0..255)
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
    
    def _paed_data(self, data: bytearray) -> dict:
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

################################################ БЛОК ОБНОВЛЕНИЯ ДАННЫХ ЦИСТЕРН ######################################################

    @Slot(dict)
    def set_cistern_states(self, states: dict):
        """Обновляет состояние цистерн в объектах DeviceInfo — выполняется в потоке DeviceManager."""
        for dev in self.devices:
            try:
                posit = getattr(dev, "posit_number", None)
                if posit is not None and int(posit) in states:
                    dev.set_full(bool(states[int(posit)]))
            except Exception:
                continue

################################################ БЛОК ЦИКЛИЧЕСКОГО ОПРОСА ПРИБОРОВ ######################################################   

    def make_request(self, request_type: str = None) -> bytearray:
        """
            Формирует запрос к текущему прибору на основе его состояния.
            Если указан request_type — выбираем команду по нему.
        """
        device: DeviceInfo = self.devices[self.current_index]

        base_cmd = None

        # Стандартный режим работы - ПАЕД или спектр
        if request_type is None:
            # Обычная логика выбора команды
            if device.location_type == "room":
                base_cmd = COMMAND_RAD_DOSE   
               

            elif device.location_type == "cistern":
                if device.real_sensor == "G":
                    base_cmd = COMMAND_RAD_DOSE
                elif device.real_sensor == "S":
                    if not device.get_full():
                        base_cmd = COMMAND_RAD_DOSE
                    else:
                        if not device.state_spectre:
                            base_cmd = COMMAND_START_SIMPLE_SPECTRE
                            device.state_spectre = True
                        else:
                            base_cmd = COMMAND_GET_SIMPLE_SPECTRE
                else:
                    raise ValueError(f"Unknown real_sensor: {device.real_sensor}")
            else:
                raise ValueError(f"Unknown location_type: {device.location_type}")
            
        # Запрашиваем температуру
        elif request_type == "temperature":
            base_cmd = COMMAND_TEMP


        # Запоминаем команду
        self.last_command = base_cmd

        # Добавляем адрес и контрольную сумму
        command = bytearray(base_cmd.data)
        command[3] = device.address
        crc = self.calc_crc(command)
        command.append(crc)

        return command

    
    @Slot()
    def dispatch_poll_step(self):
        """
            Основной метод опроса приборов
        """
        # 1. Инкрементируем глобальный индекс текущего прибора
        self.current_index += 1

        # 2. Проверяем конец списка
        if self.current_index >= len(self.devices):
            # цикл завершён, все приборы опрошены → длинная пауза
            self.current_index = -1
            self.poll_timer.start(self.long_interval_ms)
            return

        # 3. Берём объект DeviceInfo - очередной прибор
        device: DeviceInfo = self.devices[self.current_index]

        self.temperature_index += 1

        # 4. Формируем запрос с учётом адреса прибора
        if self.temperature_index < 10:
            request = self.make_request()  

        # Каждый 10 запрос - получаем температуру
        elif self.temperature_index >= 10:
            self.temperature_index = 0
            request = self.make_request("temperature") 
            
          
        # 5. Отправляем запрос через RTII порт, указанный в DeviceInfo
        try:            
            # 5. Настраиваем глобальный QSerialPort на нужный COM
            self.serial_port.setPortName(device.port)

            if not self.serial_port.isOpen():
                if not self.serial_port.open(QIODevice.ReadWrite):
                    self.device_error.emit(device.port, "Не удалось открыть порт")
                    self.poll_timer.start(self.short_interval_ms) 
                    return
                
            # 6. Отправляем запрос
            # self.serial_port.write(request)

            written = self.serial_port.write(request)
            if written != len(request):
                self.device_error.emit(
                    self.devices[self.current_index].port,
                    f"Ошибка записи: записано {written} байт из {len(request)}"
                )
            else:
                hex_str = " ".join(f"0x{b:02X}" for b in request)
                self.device_info.emit(f"Записан пакет: {hex_str}")

            

        except serial.SerialException as e:
            # Если порт не открылся или ошибка при записи
            self.device_error.emit(device.port, f"Ошибка работы с портом: {e}")
            self.poll_timer.start(self.short_interval_ms)        
            return     
       

        # 6. Запускаем аварийный таймер ожидания ответа
        self.error_timer.start(self.timeout_interval_ms)
        
        # очищаем приемный буфер перед новым запросом
        self.rx_buffer.clear()        

    def select_mode(self) -> str:
        """
            Возвращает строковое обозначение режима по последней команде.
        """
        if self.last_command == COMMAND_RAD_DOSE:
            return "RadDose"
        
        elif self.last_command == COMMAND_SER_NUM:
            return "SerialNumber"
        
        elif self.last_command == COMMAND_RAD_INTENS:
            return "RadIntensity"
        
        elif self.last_command == COMMAND_TEMP:
            return "Temperature"
        
        elif self.last_command == COMMAND_START_SIMPLE_SPECTRE:
            return "StartSpectre"
        
        elif self.last_command == COMMAND_GET_SIMPLE_SPECTRE:
            return "GetSpectre"
        
        else:
            return "UnknownMode"
        
    def handle_timeout_error(self):
        device: DeviceInfo = self.devices[self.current_index]
        self.device_error.emit(device.port, "Прибор не ответил\n")

        # Закрываем порт, чтобы не держать его открытым зря
        if self.serial_port.isOpen():
            self.serial_port.close()

        # Запускаем poll_timer для перехода к следующему прибору
        self.poll_timer.start(self.short_interval_ms)


    def handle_ready_read(self):
        try:
            # добавляем новые байты в глобальный буфер
            self.rx_buffer.extend(bytes(self.serial_port.readAll()))

            # проверяем, собрался ли полный пакет
            if len(self.rx_buffer) < self.last_command.length:
                # пока данных мало — ждём следующих readyRead
                return

            # если данных достаточно — останавливаем таймер
            self.error_timer.stop()

            # ищем начало пакета (например, 0x55 0xAA)
            start_index = self.rx_buffer.find(b'\x55\xAA')
            if start_index == -1:
                self.device_error.emit(
                    self.devices[self.current_index].port,
                    "Помилка: не знайдено початок пакету"
                )
                self.rx_buffer.clear()
                self.poll_timer.start(self.short_interval_ms)
                return

            # отбрасываем мусор до начала пакета
            self.rx_buffer = self.rx_buffer[start_index:]

            # проверка длины
            if len(self.rx_buffer) != self.last_command.length:
                self.device_error.emit(
                    self.devices[self.current_index].port,
                    f"Помилка: довжина пакету {len(self.rx_buffer)}, очікувалось {self.last_command.length}"
                )
                self.rx_buffer.clear()
                self.poll_timer.start(self.short_interval_ms)
                return

            # проверка CRC
            crc_calc = self.calc_crc(self.rx_buffer[:-1])
            crc_recv = self.rx_buffer[-1]
            if crc_calc != crc_recv:
                self.device_error.emit(
                    self.devices[self.current_index].port,
                    f"Помилка CRC: отримано {crc_recv}, очікувалось {crc_calc}"
                )
                self.rx_buffer.clear()
                return

            # формируем пакет
            mode = self.select_mode()
            packet = DevicePacket(
                self.devices[self.current_index].serial_number,
                self.rx_buffer[:-1],
                mode
            )

            # передаём пакет дальше
            self.device_response.emit(packet)

            # очищаем буфер для следующего запроса
            self.rx_buffer.clear()

            # закрываем порт (если логика требует освобождения COM)
            if self.serial_port.isOpen():
                self.serial_port.close()

            # запускаем переход к следующему прибору
            self.poll_timer.start(self.short_interval_ms)

        except Exception as e:
            self.device_error.emit(
                self.devices[self.current_index].port,
                f"Ошибка при обработке ответа: {e}"
            )
            self.rx_buffer.clear()
            if self.serial_port.isOpen():
                self.serial_port.close()
            self.poll_timer.start(self.short_interval_ms)


    
    