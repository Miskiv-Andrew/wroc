import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QThread
from devices.device_manager import DeviceManager
import json

from PySide6.QtCore import QTimer 

class App:
    """
        Основной класс приложения
    """

    def __init__(self):

        # атрибут менеджера приборов
        self.device_manager = None

        # атрибут потока менеджера приборов ( работу менеджера производим в отдельном потоке )
        self.device_manager_thread = None   

        # атрибут - словарь состояния цистерн - формат : номер - флаг ( 1 : True, 2 : False) 
        self.cistern_dict = {}     

        # атрибут интерфейса
        self.ui = None

        # загрузка формы из .ui файла
        self.load_ui() 

        # создание потока и объекта DeviceManager
        self.setup_device_manager()

        # связывание кнопок и сигналов
        self.setup_connections()   

        # Загружаем файл состояния цистерн
        self.load_cistern_data("config/cistern.json")


    def load_ui(self):
        """
            Загружаем интерфейс из main_window.ui
        """
        loader = QUiLoader()                   # создаём загрузчик .ui файлов
        ui_file = QFile("_UI/main_window.ui")  # указываем путь к файлу
        ui_file.open(QFile.ReadOnly)           # открываем файл только для чтения
        self.ui = loader.load(ui_file)         # загружаем интерфейс
        ui_file.close()                        # закрываем файл

        if self.ui is None:
            # если загрузка не удалась — выбрасываем исключение
            raise RuntimeError("Не удалось загрузить main_window.ui")

        # показываем окно во весь экран
        self.ui.showMaximized()

    def setup_device_manager(self):
        """
            Создаём поток ,переносим туда DeviceManager и запускаем поток
        """
        self.device_manager_thread = QThread()     
        self.device_manager = DeviceManager()     
        self.device_manager.moveToThread(self.device_manager_thread)
        self.device_manager_thread.start()        

    def setup_connections(self):
        """
            Связываем кнопки интерфейса с методами DeviceManager и сигналы с обработчиками
        """ 

        # Сигнал старта поиска приборов      
        self.ui.butt_search_dev.clicked.connect(self.device_manager.find_rpii_ports)

        # Сигнал старта опроса приборов  
        self.ui.butt_system_start.clicked.connect(self.device_manager.dispatch_poll_step) 


        # сигналы DeviceManager 

        # сигнал для вывода текстовой информации
        self.device_manager.device_info.connect(self.on_show_info)

        # сигнал для вывода найденных девайсов
        self.device_manager.device_found.connect(self.on_devices_updated)   

        # Общий сигнал для вывода ошибок
        self.device_manager.device_error.connect(self.on_objects_error)  

        # Тестовый сигнал для отработки опроса приборов
        self.device_manager.device_response.connect(self.on_device_packet)




    def on_show_info(self, info: str):
        """
            Слот выведения текстовых данных
        """
        self.ui.textEdit.append(info)


    def on_device_packet(self, packet):
        """
            Тестовый метод - отработка опроса приборов
        """
        sn = packet.serial_number
        mode = packet.mode
        size = packet.size
        self.ui.textEdit.append(f"Packet from {sn}: mode={mode}, size={size}\n-------------------\n")



    def on_devices_updated(self, devices):
        """
            Слот выведения найденных приборов 
        """
        self.ui.textEdit.append("Знайдено прилади:")
        for device in devices:
            if device.serial_number == "------":
                continue           

            self.ui.textEdit.append(f"Порт: {device.port}, Адреса: {device.address}, SN: {device.serial_number}")

        # Вносим в приборы данные про цистерны
        self.sync_devices_with_cisterns()

        # Начинаем процедуру опроса внешней Системы Управления
        #self.start_test_polling("devices/cistern.json")

    

    def on_objects_error(self, source: str, message: str):
        """
            Обрабатывает ошибки, возникшие в объектах созданных классов            
                Параметры:
                    source  - источник ошибки (например, "config.txt")
                    message - текст ошибки (например, "Контрольная сумма не совпадает")
            
            Выводит сообщение в textEdit, чтобы администратор видел проблему.
        """
        self.ui.textEdit.append(f"Помилка в  {source} : {message}")


    def load_cistern_data(self, json_file: str):
        """
            Загружаем данные о заполненности цистерн из файла.
            Если файл повреждён или отсутствует — создаём дефолтный словарь
            и сразу перезаписываем файл.
        """
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # преобразуем ключи в int
            self.cistern_dict = {int(k): bool(v) for k, v in data.items()}

        except (FileNotFoundError, json.JSONDecodeError):
            print(f"Файл {json_file} відсутній або пошкоджений. Створюємо дефолтні дані (20 порожніх цистерн)")
            # дефолт: 20 цистерн, пустые
            self.cistern_dict = {i: False for i in range(1, 21)}
            # перезаписываем файл дефолтным содержимым
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(self.cistern_dict, f, ensure_ascii=False, indent=4)    

    def sync_devices_with_cisterns(self):
        """
            После окончания поиска приборов синхронизируем их состояние
            с данными из cistern_dict.
            Если прибор с location_type == "cistern" не имеет соответствия в словаре,
            предупреждаем администратора.
        """
        for device in self.device_manager.devices:
            # Пропускаем приборы, которые относятся к помещению
            if device.location_type == "room":
                continue

            # Для приборов-цистерн проверяем соответствие
            num = device.posit_number
            if num in self.cistern_dict:
                device.set_full(self.cistern_dict[num])
            else:               
                s =  (f"УВАГА: прилад с posit_number = {num} " 
                     f"(location_type='cistern') не має відповідного запису " 
                     f"Перевірте конфигурацію в cistern_dict та cistern.json!")
                
                self.on_objects_error("Звірка приладів і цистерн", s)


    def start_test_polling(self, json_file: str):
        """
            Запускаем имитационный опрос Системы Управления( состояние заполненности цистерн ).
            Каждые 30 секунд получаем словарь с новыми данными и сравниваем его
            с self.cistern_dict. При изменении обновляем словарь, приборы и файл.
        """
        self.timer = QTimer()
        self.timer.setInterval(30_000)  # 30 секунд
        self.timer.timeout.connect(lambda: self.poll_system(json_file))
        self.timer.start()   
   

    def poll_system(self, json_file: str, new_data: dict = None):
        """
            Опрос Системы Управления.
            Сравниваем новые данные new_data со словарём self.cistern_dict.
            При изменении обновляем словарь, приборы и файл.
            Если в новых данных есть номер цистерны, которого нет в словаре —
            фиксируем ошибку и предупреждаем администратора.
        """

        # Если new_data не передан — используем пустой словарь (имитация)
        if new_data is None:
            text = self.ui.lineEdit.text().strip()
            if text == "Full":
                new_data = {1: True}                
            elif text == "Empty":
                new_data = {1: False}                
            else:  # Некорректный ввод — игнорируем                
                return

        updated = False
        for num, new_value in new_data.items():
            if num not in self.cistern_dict:
                # Ошибка: цистерна отсутствует в конфигурации
                print(
                    f"УВАГА: отримано дані по цистерні №{num}, "
                    f"якої немає у конфігурації cistern_dict. "
                    f"Перевірте налаштування та файл cistern.json!"
                )
                continue

            current_value = self.cistern_dict[num]
            if new_value != current_value:
                print(f"Зміна стану цистерни №{num}: {current_value} → {new_value}")
                self.cistern_dict[num] = new_value
                updated = True

                # Обновляем соответствующий прибор
                for device in self.device_manager.devices:
                    if device.location_type == "cistern" and device.posit_number == num:
                        device.set_full(new_value)
                        break

        # Если были изменения — перезаписываем файл cistern.json
        if updated:
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(self.cistern_dict, f, ensure_ascii=False, indent=4)




def main():
    """
        Точка входа в приложение
    """
    app = QApplication(sys.argv) # создаём объект приложения
    window = App()                # создаём наш класс App (он загрузит интерфейс и настроит связи)
    sys.exit(app.exec())          # запускаем цикл обработки событий и корректно завершаем работу


if __name__ == "__main__":
    main()
