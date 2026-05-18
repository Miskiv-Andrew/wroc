from dataclasses import dataclass
import threading

@dataclass
class DeviceInfo:
    """
        Класс для хранения информации о приборе.
    """

    def __init__(self, port: str, address: int, serial_number: str, device_type: str = "БДБГ-09S-23", 
                 description: str = "", no_answer:int = 0, old_ped:float = 0.0, 
                 real_sensor:str = "G", state_spectre:bool = False):
        
        # Атрибуты, получаемые при поиске приборов
        self.port = port                    # COM-порт, к которому подключен прибор
        self.address = address              # Адрес прибора в протоколе опроса
        self.serial_number = serial_number  # Серийный номер прибора
        self.device_type = device_type      # Тип прибора (пока "БДБГ-09S-23")

        # Атрибуты, загружаемые из config.txt
        self.location_type = None           # Тип расположения: "cistern" или "room"          
        self.posit_number = None            # Номер цистерны (int) или места в помещении
        self.expected_address = None        # Адрес из config.txt (для сверки)        
        self.description = description      # строка: для комментариев

        # Атрибут числа неответов прибора
        self.no_answer = no_answer

        # Атрибуты заполненности цистерны и блокировки
        self.__full = False                # Флаг заполненности цистерны - по умолчанию цистерна пустая((False)
        self.__lock = threading.Lock()     # Блокировка для атрибута self.__full ( избежать гонки )

        # Атрибуты для выбора режима опроса
        self.old_ped = old_ped  
        self.real_sensor = real_sensor 
        self.state_spectre = state_spectre  

        # Атрибуты для работы со спектром
        self.spectrum_buffer = [0] * 1024   # массив для накопления спектра (1024 канала)
        self.spectrum_counter = 0           # счётчик полученных спектров (0..600)
        self.spectrum_active = False        # флаг, что идёт набор спектра

        self.start_spectre_retries = 0  # счётчик неудачных попыток запуска спектра (максимум 3)


    def set_full(self, value: bool):
        """
            Установить состояние заполненности цистерны данного прибора
        """
        with self.__lock:
            self.__full = value

            
    def get_full(self) -> bool:
        """
            Получить состояние заполненности цистерны  данного прибора
        """
        with self.__lock:
            return self.__full
        
    def reset_spectrum(self):
        """
            Обнуляет буфер спектра и счётчик
        """
        self.spectrum_buffer = [0] * 1024
        self.spectrum_counter = 0

    def add_to_spectrum(self, channels):
        """
            Почленно складывает полученный массив с буфером
        """
        for i in range(1024):
            self.spectrum_buffer[i] += channels[i]
        self.spectrum_counter += 1

    def get_spectrum_buffer(self):
        """
            Возвращает текущий буфер спектра
        """
        return self.spectrum_buffer

    def get_spectrum_counter(self):
        """
            Возвращает текущее значение счётчика
        """
        return self.spectrum_counter

    def is_spectrum_ready(self):
        """
            Проверяет, достигнут ли лимит в 600 получений
        """
        return self.spectrum_counter >= 600

    def __repr__(self):
        """
            Текстовое представление объекта для отладки.
        """
        return (f"DeviceInfo(port = {self.port}, address = {self.address}, "
                f"serial_number = {self.serial_number}, "
                f"location_type = {self.location_type}, "
                f"posit_number = {self.posit_number}, "
                f"expected_address = {self.expected_address}, "
                f"full = {self.get_full()})")
