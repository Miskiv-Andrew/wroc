import sys
from PySide6.QtWidgets import QApplication, QWidget, QGridLayout, QVBoxLayout, QPushButton, QLabel, QSizePolicy
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QThread, QMetaObject, QTimer , Qt, QObject, Signal
from devices.device_manager import DeviceManager
from PySide6.QtGui import QAction, QPixmap
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import json, numpy as np
import threading, os, math

class SpectrumWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)

        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        self.ax = self.figure.add_subplot(111)
        self.plot()

    def plot(self):
        self.ax.clear()
        data = np.random.normal(1000, 200, 1000)  # fake counts
        self.ax.hist(data, bins=30)
        self.canvas.draw()

class DeviceCardBarrel(QWidget):
    """
        Клас детектору у контейнері
    """
    def __init__(self):
        super().__init__()

        loader = QUiLoader()
        ui_file = QFile("_UI/dashboardbarrel.ui")
        ui_file.open(QFile.ReadOnly)

        self.ui = loader.load(ui_file)
        ui_file.close()

        if self.ui is None:
            raise RuntimeError("Не удалось загрузить dashboardbarrel.ui")

        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(5, 5, 5, 5)
        #self.layout().setSpacing(0)
        self.layout().addWidget(self.ui)
        #self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        #self.ui.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # label = self.ui.findChild(QLabel, "barrelLabel")
        # path = os.path.abspath("_UI/barrelresized.png")
        # if label:
        #     label.setPixmap(QPixmap(path))
    
    def set_serial(self, serial):
        label = self.ui.findChild(QLabel, "serialLabel")
        if label:
            label.setText(f"SN: {serial}")

    def set_position(self, position):
        label = self.ui.findChild(QLabel, "positionLabel")
        if label:
            label.setText(f"Контейнер № {position}")

    def set_status(self, status):
        label = self.ui.findChild(QLabel, "statusLabel")
        if status == "active":
            color = "#2ecc71"   # green
        elif status == "warning":
            color = "#f1c40f"   # yellow
        elif status == "error":
            color = "#e74c3c"   # red
        else:
            color = "#7f8c8d"

        label.setStyleSheet(f"""
        QLabel {{
            background-color: {color};
            border-radius: 6px;
        }} """)
    
    def set_barrel_image(self, full: bool):
        label = self.ui.findChild(QLabel, "barrelLabel")
        if not label:
                return

        image_name = "barrelfull.svg" if full else "barrelempty.svg"
        path = os.path.abspath(os.path.join("_UI", image_name))
        #label.setPixmap(QPixmap(path))
        pixmap = QPixmap(path)

        # actual_size = label.size()
        # if actual_size.width() > 0 and actual_size.height() > 0:
        #     scaled_pixmap = pixmap.scaled(actual_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        #     label.setPixmap(scaled_pixmap)
        # else:
        #     label.setScaledContents(True)
        #     label.setPixmap(pixmap)
        scaled_pixmap = pixmap.scaledToWidth(80, Qt.SmoothTransformation)
        label.setPixmap(scaled_pixmap)
    
    def set_dose_value(self, dose, acc):
        label = self.ui.findChild(QLabel, "doseValue")
        if label:
            label.setText(f"{dose:.2f} мкЗв/год ± {acc}%")

    def set_temp_value(self, value):
        label = self.ui.findChild(QLabel, "tempValue")
        if label:
            label.setText(f"{value}")
    
    def add_spectrum(self):
        self.spectrum = SpectrumWidget()
        layout = self.ui.spectrumWidget.layout()
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.spectrum)
    

    def set_detector_status(self, low_failure: bool, high_failure: bool, result_valid: bool):
        """
        Устанавливает состояние детекторов и валидность результата.
        low_failure: True - отказ низкочувствительного детектора, False - норма
        high_failure: True - отказ высокочувствительного детектора, False - норма
        result_valid: True - результат валидный, False - невалидный
        """
        # Низкочувствительный детектор
        low_label = self.ui.findChild(QLabel, "lowDetectorValue")
        if low_label:
            if not low_failure:
                low_label.setText("Відмова")
                low_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            else:
                low_label.setText("Норма")
                low_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
        
        # Высокочувствительный детектор
        high_label = self.ui.findChild(QLabel, "highDetectorValue")
        if high_label:
            if not high_failure:
                high_label.setText("Відмова")
                high_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            else:
                high_label.setText("Норма")
                high_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
        
        # Валидность результата
        valid_label = self.ui.findChild(QLabel, "validityValue")
        if valid_label:
            if result_valid:
                valid_label.setText("Норма")
                valid_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
            else:
                valid_label.setText("Невалідний")
                valid_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")

        # status_label = self.ui.findChild(QLabel, "statusValue")
        # status_label.setText("Норма")
        # status_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
   
    def set_connection_status(self, connected: bool, crc_error: bool = False):
        """
        Устанавливает статус связи с прибором.
        connected: True - связь есть, False - нет связи
        crc_error: True - ошибка CRC (пакет получен, но повреждён)
        """
        status_label = self.ui.findChild(QLabel, "statusValue")
        low_label = self.ui.findChild(QLabel, "lowDetectorValue")
        high_label = self.ui.findChild(QLabel, "highDetectorValue")
        valid_label = self.ui.findChild(QLabel, "validityValue")
        
        if not connected:
            # Нет связи
            if status_label:
                status_label.setText("Немає зв'язку")
                status_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            if low_label:
                low_label.setText("-----")
                low_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            if high_label:
                high_label.setText("-----")
                high_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            if valid_label:
                valid_label.setText("-----")
                valid_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
        
        elif crc_error:
            # Ошибка CRC (связь есть, но пакет повреждён)
            if status_label:
                status_label.setText("Норма")
                status_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
            if low_label:
                low_label.setText("-----")
                low_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            if high_label:
                high_label.setText("-----")
                high_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            if valid_label:
                valid_label.setText("Помилка CRC")
                valid_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
        
        else:
            # Нормальная связь
            if status_label:
                status_label.setText("Норма")
                status_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")

        

class DeviceCardWall(QWidget):
    """
        Клас настінного детектору(у кімнаті)
    """
    def __init__(self):
        super().__init__()

        loader = QUiLoader()
        ui_file = QFile("_UI/dashboardwall.ui")
        ui_file.open(QFile.ReadOnly)

        self.ui = loader.load(ui_file)
        ui_file.close()

        if self.ui is None:
            raise RuntimeError("Не удалось загрузить dashboardwall.ui")

        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(5, 5, 5, 5)
        self.layout().addWidget(self.ui)
        #self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        #self.ui.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
 
    def set_serial(self, serial):
        label = self.ui.findChild(QLabel, "serialLabel")
        if label:
            label.setText(f"SN: {serial}")
    
    def set_position(self, position):
        label = self.ui.findChild(QLabel, "positionLabel")
        if label:
            label.setText(f"Детектор № {position}")

    def set_status(self, status):
        label = self.ui.findChild(QLabel, "statusLabel")
        if status == "active":
            color = "#2ecc71"   # green
        elif status == "warning":
            color = "#f1c40f"   # yellow
        elif status == "error":
            color = "#e74c3c"   # red
        else:
            color = "#7f8c8d"

        label.setStyleSheet(f"""
        QLabel {{
            background-color: {color};
            border-radius: 6px;
        }} """)
    
    def set_dose_value(self, dose, acc):
        label = self.ui.findChild(QLabel, "doseValue")
        if label:
            label.setText(f"{dose:.2f} мкЗв/год ± {acc}%")


    def set_temp_value(self, value):
        label = self.ui.findChild(QLabel, "tempValue")
        if label:
            label.setText(f"{value}")

    def add_spectrum(self):
        self.spectrum = SpectrumWidget()
        layout = self.ui.spectrumWidget.layout()
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.spectrum)

    
    def set_detector_status(self, low_failure: bool, high_failure: bool, result_valid: bool):
        """
        Устанавливает состояние детекторов и валидность результата.
        low_failure: True - отказ низкочувствительного детектора, False - норма
        high_failure: True - отказ высокочувствительного детектора, False - норма
        result_valid: True - результат валидный, False - невалидный
        """
        # Низкочувствительный детектор
        low_label = self.ui.findChild(QLabel, "lowDetectorValue")
        if low_label:
            if not low_failure:
                low_label.setText("Відмова")
                low_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            else:
                low_label.setText("Норма")
                low_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
        
        # Высокочувствительный детектор
        high_label = self.ui.findChild(QLabel, "highDetectorValue")
        if high_label:
            if not high_failure:
                high_label.setText("Відмова")
                high_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            else:
                high_label.setText("Норма")
                high_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
        
        # Валидность результата
        valid_label = self.ui.findChild(QLabel, "validityValue")
        if valid_label:
            if result_valid:
                valid_label.setText("Норма")
                valid_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
            else:
                valid_label.setText("Невалідний")
                valid_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")

        # status_label = self.ui.findChild(QLabel, "statusValue")
        # status_label.setText("Норма")
        # status_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")

    def set_connection_status(self, connected: bool, crc_error: bool = False):
        """
        Устанавливает статус связи с прибором.
        connected: True - связь есть, False - нет связи
        crc_error: True - ошибка CRC (пакет получен, но повреждён)
        """
        status_label = self.ui.findChild(QLabel, "statusValue")
        low_label = self.ui.findChild(QLabel, "lowDetectorValue")
        high_label = self.ui.findChild(QLabel, "highDetectorValue")
        valid_label = self.ui.findChild(QLabel, "validityValue")
        
        if not connected:
            # Нет связи
            if status_label:
                status_label.setText("Немає зв'язку")
                status_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            if low_label:
                low_label.setText("-----")
                low_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            if high_label:
                high_label.setText("-----")
                high_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            if valid_label:
                valid_label.setText("-----")
                valid_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
        
        elif crc_error:
            # Ошибка CRC (связь есть, но пакет повреждён)
            if status_label:
                status_label.setText("Норма")
                status_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
            if low_label:
                low_label.setText("-----")
                low_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            if high_label:
                high_label.setText("-----")
                high_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            if valid_label:
                valid_label.setText("Помилка CRC")
                valid_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
        
        else:
            # Нормальная связь
            if status_label:
                status_label.setText("Норма")
                status_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")


class DatabaseWindow(QWidget):
    """
        Клас вікна для доступу до бази даних
    """
    def __init__(self):
        super().__init__()

        loader = QUiLoader()
        ui_file = QFile("_UI/db_window.ui")
        ui_file.open(QFile.ReadOnly)

        self.ui = loader.load(ui_file)
        ui_file.close()

        if self.ui is None:
            raise RuntimeError("Не удалось загрузить db_window.ui")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.ui)

        self.setWindowTitle("База даних")
       
        
class App(QObject):
    """
        Основной класс приложения
    """

    search_devices = Signal()
    start_polling = Signal()
    sync_cisterns_to_manager = Signal(dict)


    def __init__(self):

        super().__init__()

        # атрибут загруженных интерфейсов приборов
        self.cards_by_sn = {}

        # атрибут менеджера приборов
        self.device_manager = None

        # атрибут потока менеджера приборов ( работу менеджера производим в отдельном потоке )
        self.device_manager_thread = None   

        # атрибут - словарь состояния цистерн - формат : номер - флаг ( 1 : True, 2 : False) 
        self.cistern_dict = {}  

        self.current_columns = 1   

        # атрибут интерфейса
        self.ui = None

        self.barrel_container = None
        self.barrel_grid = None
        self.wall_container = None
        self.wall_layout = None

        # загрузка формы из .ui файла
        self.load_ui() 

        # создание потока и объекта DeviceManager
        self.setup_device_manager()

        # связывание кнопок и сигналов
        self.setup_connections()   

        # Загружаем файл состояния цистерн
        self.load_cistern_data("config/cistern.json")

        # Розмітка контейнеру для вікон приладів
        self.setup_ui()


    def load_ui(self):
        """
            Загружаем интерфейс из main_window.ui
        """
        loader = QUiLoader()                            # создаём загрузчик .ui файлов
        ui_file = QFile("_UI/main_window_form.ui")      # указываем путь к файлу
        ui_file.open(QFile.ReadOnly)                    # открываем файл только для чтения
        self.ui = loader.load(ui_file)                  # загружаем интерфейс
        ui_file.close()                                 # закрываем файл

        if self.ui is None:
            # если загрузка не удалась — выбрасываем исключение
            raise RuntimeError("Не удалось загрузить main_window.ui")

        # показываем окно во весь экран
        self.ui.showMaximized()
    
    # def setup_ui(self):
        # """
        #     Розмітка(grid) для вікон приладів
        # """
        # self.container = self.ui.findChild(QWidget, "containerCard")
        # if self.container:
        #     self.grid = self.container.layout()
        #     #Install event filter to catch resize events
        #     #self.container.installEventFilter(self)
        # else:
        #     # Fallback
        #     self.grid = QGridLayout(self.container)

    # def setup_ui(self):
    #     """
    #         Розмітка(grid) для вікон приладів
    #     """
    #     self.container = self.ui.findChild(QWidget, "containerCard")
        
    #     if self.container is None:
    #         # Если контейнер не найден, создаём его и размещаем в centralwidget
    #         self.container = QWidget(self.ui.centralwidget)
    #         layout = QVBoxLayout(self.ui.centralwidget)
    #         layout.setContentsMargins(0, 0, 0, 0)
    #         layout.addWidget(self.container)
        
    #     self.grid = self.container.layout()
        
    #     if self.grid is None:
    #         # Если у контейнера нет layout, создаём QGridLayout
    #         self.grid = QGridLayout(self.container)
    #         self.grid.setSpacing(5)
    #         self.container.setLayout(self.grid)
    
    def setup_ui(self):
        self.barrel_container = self.ui.findChild(QWidget, "containerCard")
        self.wall_container = self.ui.findChild(QWidget, "containerWall")

        self.barrel_grid = self.barrel_container.layout()
        if self.barrel_grid is None:
            self.barrel_grid = QGridLayout(self.barrel_container)
            self.barrel_grid.setSpacing(5)
            self.barrel_container.setLayout(self.barrel_grid)

        self.wall_layout = self.wall_container.layout()
        if self.wall_layout is None:
            self.wall_layout = QVBoxLayout(self.wall_container)
            self.wall_container.setLayout(self.wall_layout)

    def eventFilter(self, obj, event):
        """
            Catch resize events on the container
        """
        if obj == self.container and event.type() == event.Type.Resize:
            self.recalculate_grid()
        return super().eventFilter(obj, event)

    def db_window(self):
        """
            Вивід вікна для бази даних
        """
        self.window = DatabaseWindow()
        self.window.resize(self.ui.size() * 0.7)
        self.window.show()

    def setup_device_manager(self):
        """
            Создаём поток ,переносим туда DeviceManager и запускаем поток
        """
        self.device_manager_thread = QThread()     
        self.device_manager = DeviceManager()     
        self.device_manager.moveToThread(self.device_manager_thread)
        self.device_manager_thread.finished.connect(self.device_manager.deleteLater)
        self.device_manager_thread.start()        

    def setup_connections(self):
        """
            Связываем кнопки интерфейса с методами DeviceManager и сигналы с обработчиками
        """ 

        # Сигнал старта поиска приборов
        self.butt_search_dev = self.ui.findChild(QAction, "butt_search_dev") 
        self.butt_search_dev.triggered.connect(self.search_devices.emit) 
        self.search_devices.connect(self.device_manager.find_rpii_ports)
        
        # Сигнал старта опроса приборов
        self.butt_system_start = self.ui.findChild(QAction, "butt_system_start") 

        # self.butt_system_start.triggered.connect(self.start_polling.emit) 
        self.butt_system_start.triggered.connect(self.start_polling_and_test_system)

        self.start_polling.connect(self.device_manager.dispatch_poll_step) 

        # Сигнал виводу вікна для бази даних
        self.butt_db_window = self.ui.findChild(QAction, "open_bd")
        self.butt_db_window.triggered.connect(self.db_window) 

        # Сигнал передачи данных по цистернам в DeviceManager
        self.sync_cisterns_to_manager.connect(self.device_manager.set_cistern_states)      

        # сигналы DeviceManager 
        # сигнал для вывода текстовой информации
        self.device_manager.device_info.connect(self.on_show_info, Qt.ConnectionType.QueuedConnection)

        # сигнал для вывода найденных девайсов
        self.device_manager.device_found.connect(self.on_devices_updated, Qt.ConnectionType.QueuedConnection)   

        # Общий сигнал для вывода ошибок
        self.device_manager.device_error.connect(self.on_objects_error, Qt.ConnectionType.QueuedConnection)  

        # Тестовый сигнал для отработки опроса приборов
        self.device_manager.device_response.connect(self.on_device_packet, Qt.ConnectionType.QueuedConnection) 

        # сигнал для информирования о состоянии связи
        self.device_manager.device_connection_status.connect(self.on_device_connection_status, Qt.ConnectionType.QueuedConnection)
  

    def on_show_info(self, info: str):
        """
            Слот выведения текстовых данных
        """
        self.ui.textEdit.append(info)

   
    def on_device_packet(self, packet):
        """
            Обработка пакетов от приборов
        """
        card = self.cards_by_sn.get(packet.serial_number)
        if card is None:
            return

        sn = packet.serial_number
        mode = packet.mode
        size = packet.size
        buff = packet.buff
        self.ui.textEdit.append(f"Packet from {sn}: mode={mode}, size={size}")

        try:
            if mode == "RadDose":
                data = self.device_manager._paed_data(buff)
                if data:
                    dose = data["ped_value"]
                    accuracy = data["accuracy"]
                    card.set_dose_value(dose, accuracy)
                    self.ui.textEdit.append(f"Parsed dose for {sn}:  {dose:.2f} μSv/h ± {accuracy}%\n-------------------")
                    
                    # Добавлено: установка состояния детекторов и валидности
                    card.set_detector_status(
                        low_failure=data.get("low_sens_failure", True),
                        high_failure=data.get("high_sens_failure", True),
                        result_valid=data.get("result_valid", False)
                    )

            elif mode == "Temperature":
                data = self.device_manager._temp_data(buff)
                if data:
                    card.set_temp_value(data)
                    self.ui.textEdit.append(f"Parsed temperature for {sn}:  {data}\n-------------------")

        except Exception as e:
            self.ui.textEdit.append(f"Error parsing packet for {sn}: {e}\n-------------------")
    
    
    def create_device_card(self, device):
        """
            Створення вікна для приладу
        """
        if device.get("location_type") == "cistern":
            card = DeviceCardBarrel()
        elif device.get("location_type") == "room":
            card = DeviceCardWall()
        else:
            # Неизвестный тип расположения - выводим ошибку и возвращаем None
            self.ui.textEdit.append(
                f"Помилка: невідомий тип розташування '{device.get('location_type')}' "
                f"для приладу SN {device.get('serial_number')}"
            )
            return None
        return card

    
    def recalculate_grid(self):
        """Recalculate grid rows/columns on window resize"""
        if not self.cards_by_sn or not self.grid:
            return
        
        container = self.ui.findChild(QWidget, "containerCard")
        if not container:
            return
        
        width = self.container.width()
        card_width = 400
        spacing = self.grid.spacing()
        #new_columns = max(1, width // (card_width + spacing))
        n = len(self.cards_by_sn)
        if n <= 3:
            new_columns = max(1, n)
        elif n > 3:
            new_columns = math.ceil(math.sqrt(n))
        else:
            new_columns = 1

        # Check if column count actually changed
        if not hasattr(self, 'current_columns') or self.current_columns != new_columns:
            self.current_columns = new_columns
            self.reflow_grid()


    def reflow_grid(self):
        """Reorganize cards in grid with new column count"""
        cards_list = list(self.cards_by_sn.values())
        
        # Clear grid
        self.clear_layout(delete_widgets=False)
        
        # Re-add cards in new layout
        for i, card in enumerate(cards_list):
            row = i // self.current_columns
            col = i % self.current_columns
            self.grid.addWidget(card, row, col)
    
    # def clear_layout(self, delete_widgets=True):
    #     while self.grid.count():
    #         item = self.grid.takeAt(0)
    #         w = item.widget()
    #         if w is not None:
    #             if delete_widgets:
    #                 w.setParent(None)
    #                 w.deleteLater()
    #             else:
    #                 # Just remove from layout, keep the widget alive
    #                 w.setParent(None)

    def clear_layout(self, delete_widgets=True):
        for layout in (self.barrel_grid, self.wall_layout):
            if layout is None:
                continue
            while layout.count():
                item = layout.takeAt(0)
                if item is None:
                    break
                w = item.widget()
                if w is not None:
                    if delete_widgets:
                        w.setParent(None)
                        w.deleteLater()
                    else:
                        w.setParent(None)

    # def on_devices_updated(self, devices):
    #     """
    #         Слот выведения найденных приборов 
    #     """
    #     if not devices:
    #         self.ui.textEdit.append("Прилади не знайдено. Перевірте підключення та спробуйте ще раз.")
    #         self.cards_by_sn.clear()
    #         self.clear_layout()
    #         return
        
    #     self.ui.textEdit.append("Знайдено прилади:")        
    #     self.cards_by_sn.clear()      

    #     n = len(devices)
    #     if n <= 3:
    #         columns = max(1, n)
    #     elif n > 3:
    #         columns = math.ceil(math.sqrt(n))
    #     else:
    #         columns = 1
        
    #     self.clear_layout()

    #     for i, device in enumerate(devices):

    #         card = self.create_device_card(device)
    #         if card is None:
    #             continue

    #         if isinstance(card, DeviceCardBarrel):
    #             card.set_barrel_image(bool(self.cistern_dict.get(device.get("posit_number"), False)))

    #         card.posit_number = device.get("posit_number")
    #         card.serial_number = device.get("serial_number")
    #         self.cards_by_sn[card.serial_number] = card

    #         card.set_serial(device.get("serial_number"))
    #         card.set_position(device.get("posit_number"))
    #         card.set_status("active")
    #         #card.add_spectrum()
    #         card.setMinimumSize(0, 0)
    #         card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    #         row = i // columns
    #         col = i % columns

    #         self.grid.addWidget(card, row, col)  
    
    #         self.ui.textEdit.append(f"Порт: {device.get('port')}, Адреса: {device.get('address')}, SN: {device.get('serial_number')}")
        
    #     # Вносим в приборы данные про цистерны
    #     self.sync_devices_with_cisterns()

    #     # Начинаем процедуру опроса внешней Системы Управления
    #     # self.start_test_polling("devices/cistern.json")

    def on_devices_updated(self, devices):
        """
            Слот выведения найденных приборов 
        """
        if not devices:
            self.ui.textEdit.append("Прилади не знайдено. Перевірте підключення та спробуйте ще раз.")
            self.cards_by_sn.clear()
            self.clear_layout()
            return

        self.ui.textEdit.append("Знайдено прилади:")
        self.cards_by_sn.clear()
        self.clear_layout()

        barrel_devices = [i for i in devices if i.get("location_type") == "cistern"]
        wall_devices = [i for i in devices if i.get("location_type") == "room"]

        columns = max(1, math.ceil(math.sqrt(len(barrel_devices)))) if barrel_devices else 1

        barrel_index = 0
        for device in barrel_devices + wall_devices:
            card = self.create_device_card(device)
            if card is None:
                continue

            if isinstance(card, DeviceCardBarrel):
                card.set_barrel_image(bool(self.cistern_dict.get(device.get("posit_number"), False)))

            card.posit_number = device.get("posit_number")
            card.serial_number = device.get("serial_number")
            self.cards_by_sn[card.serial_number] = card

            card.set_serial(device.get("serial_number"))
            card.set_position(device.get("posit_number"))
            card.set_status("active")
            card.setMinimumSize(0, 0)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

            if isinstance(card, DeviceCardBarrel):
                row = barrel_index // columns
                col = barrel_index % columns
                self.barrel_grid.addWidget(card, row, col)
                barrel_index += 1
            else:
                self.wall_layout.addWidget(card)

            self.ui.textEdit.append(
                f"Порт: {device.get('port')}, Адреса: {device.get('address')}, SN: {device.get('serial_number')}"
            )

        # Вносим в приборы данные про цистерны
        self.sync_devices_with_cisterns()

        # Начинаем процедуру опроса внешней Системы Управления
        self.start_test_polling("devices/cistern.json")

    

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
            Синхронизируем только GUI-карточки с self.cistern_dict.
            НИКОГДА не вызываем методы объектов DeviceManager из GUI-потока.
        """
        # Проверка: если cistern_dict пуст или не загружен - принудительно загружаем
        if not self.cistern_dict:
            self.load_cistern_data("config/cistern.json")
        
        for sn, card in self.cards_by_sn.items():
            try:
                # пытаемся получить posit из карточки (если карточка его сохранила)
                posit = getattr(card, "posit_number", None) or getattr(card, "posit", None)
                if posit is None:
                    continue
                # сохраняем состояние на карточке (визуальное обновление реализовать в карточке)
                setattr(card, "is_full", bool(self.cistern_dict.get(int(posit), False)))
                # card.set_barrel_image(card.is_full)  # раскомментировать если нужно обновить иконку
            except Exception:
                continue


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
                # for device in self.device_manager.devices:
                #     if device.location_type == "cistern" and device.posit_number == num:
                #         device.set_full(new_value)
                #         break

                # Обновляем только GUI‑карточки; не трогаем объекты DeviceManager из GUI‑потока
                for sn, card in self.cards_by_sn.items():
                    try:
                        if getattr(card, "posit_number", None) == num or getattr(card, "posit", None) == num:
                            setattr(card, "is_full", bool(new_value))
                            card.set_barrel_image(card.is_full)
                            break
                    except Exception:
                        continue


        # Если были изменения — перезаписываем файл cistern.json
        if updated:
            with open(json_file, "w", encoding="utf-8") as f:                
                json.dump(self.cistern_dict, f, ensure_ascii=False, indent=4)
                try:
                    self.sync_cisterns_to_manager.emit(self.cistern_dict)
                except Exception:
                    pass

    
    def cleanup(self):
        # DeviceManager корректно останавливаем в его потоке
        try:
            QMetaObject.invokeMethod(self.device_manager, "stop_all", Qt.ConnectionType.QueuedConnection)
        except Exception:
            pass
        # Корректно завершаем поток менеджера
        if self.device_manager_thread is not None and self.device_manager_thread.isRunning():
            self.device_manager_thread.quit()
            self.device_manager_thread.wait(2000)

    def start_polling_and_test_system(self):
        """
            Слот, запускаемый по нажатию кнопки "Старт системы".
            Запускает циклический опрос приборов и имитацию опроса внешней системы.
        """
        # Запуск основного опроса приборов
        self.start_polling.emit()
        
        # Запуск имитации опроса внешней системы (состояние цистерн)
        self.start_test_polling("devices/cistern.json")
    
    def on_device_connection_status(self, serial_number: str, connected: bool, crc_error: bool):
        """
        Обработка изменения статуса связи прибора
        """
        card = self.cards_by_sn.get(serial_number)
        if card:
            card.set_connection_status(connected, crc_error)


    


def main():
    """
        Точка входа в приложение
    """
    app = QApplication(sys.argv) # создаём объект приложения
    window = App()                # создаём наш класс App (он загрузит интерфейс и настроит связи)
    app.aboutToQuit.connect(window.cleanup)
    sys.exit(app.exec())          # запускаем цикл обработки событий и корректно завершаем работу


if __name__ == "__main__":
    main()
