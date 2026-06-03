# app.py

import sys
from PySide6.QtWidgets import QApplication, QWidget, QGridLayout, QVBoxLayout, QPushButton, QLabel, QSizePolicy, QSpacerItem
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QThread, QMetaObject, QTimer , Qt, QObject, Signal, QDateTime
from devices.device_manager import DeviceManager
from PySide6.QtGui import QAction, QPixmap
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import json, numpy as np
import threading, os, math

from database.db_manager import DatabaseManager

class SpectrumWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)

        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas)
        self.ax = self.figure.add_subplot(111)
        self.data = []  # хранение текущих данных

    def update_data(self, data):
        """Обновляет данные и перерисовывает график"""
        self.data = data
        self.plot()
    
    def plot(self):
        self.ax.clear()
        if self.data and len(self.data) > 0:
            # Отрисовка спектра (гистограмма или линейный график)
            self.ax.plot(self.data, linewidth=0.5)
            self.ax.set_ylim(bottom=0)
            self.ax.set_xlim(left=0)
            self.ax.set_xlabel("Канал")
            self.ax.set_ylabel("Кількість імпульсів")
        else:
            self.ax.text(0.5, 0.5, "Немає даних", transform=self.ax.transAxes, ha='center')
        self.canvas.draw()

class DeviceCardBarrel(QWidget):
    """
        Клас детектору у контейнері
    """
    # def __init__(self):
    #     super().__init__()

    #     loader = QUiLoader()
    #     ui_file = QFile("_UI/dashboardbarrel.ui")
    #     ui_file.open(QFile.ReadOnly)

    #     self.ui = loader.load(ui_file)
    #     ui_file.close()

    #     if self.ui is None:
    #         raise RuntimeError("Не удалось загрузить dashboardbarrel.ui")

    #     self.setLayout(QVBoxLayout())
    #     self.layout().setContentsMargins(5, 5, 5, 5)
    #     #self.layout().setSpacing(0)
    #     self.layout().addWidget(self.ui)
    #     #self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    #     #self.ui.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    #     # label = self.ui.findChild(QLabel, "barrelLabel")
    #     # path = os.path.abspath("_UI/barrelresized.png")
    #     # if label:
    #     #     label.setPixmap(QPixmap(path))

    #     # Инициализация спектральных данных
    #     self.spectrum_buffer = [0] * 1024   # массив для накопления спектра (1024 канала)
    #     self.spectrum_counter = 0           # счётчик полученных спектров (0..600)

    def __init__(self, parent_app=None):
        super().__init__()
        self.parent_app = parent_app

        loader = QUiLoader()
        ui_file = QFile("_UI/dashboardbarrel.ui")
        ui_file.open(QFile.ReadOnly)

        self.ui = loader.load(ui_file)
        ui_file.close()

        if self.ui is None:
            raise RuntimeError("Не удалось загрузить dashboardbarrel.ui")

        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(5, 5, 5, 5)
        self.layout().addWidget(self.ui)
        self.add_spectrum()
        self.set_barrel_icon()
        self.set_dose_icon()
        self.set_temp_icon()
        self.set_activity_icon()
        self.set_isotope_icon()

        # Инициализация спектральных данных
        self.spectrum_buffer = [0] * 1024   # массив для накопления спектра (1024 канала)
        self.spectrum_counter = 0           # счётчик полученных спектров (0..600)
        
        # История активности
        self.activity_history = []

        # Подключение кнопки построения гистограммы
        btn_hist = self.ui.findChild(QPushButton, "makeHist")
        if btn_hist:
            btn_hist.clicked.connect(self.plot_activity_histogram)

        
        self.last_temperature = 0.0

        # Для хранения последних значений
        self.last_paed = 0.0
        self.last_paed_from_spectrum = 0.0
        self.last_low_status = 1   # по умолчанию отказ
        self.last_high_status = 1  # по умолчанию отказ
        self.last_valid = 0        # по умолчанию невалидный


    
    def set_serial(self, serial):
        label = self.ui.findChild(QLabel, "serialValue")
        if label:
            label.setText(f"{serial}")
    
    def set_position(self, position):
        label = self.ui.findChild(QLabel, "positionValue")
        if label:
            label.setText(f"{position}")
    
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
    
    def set_barrel_icon(self):
        """Set the barrel detector icon"""
        label = self.ui.findChild(QLabel, "detectorIcon")
        path = os.path.abspath(os.path.join("_UI", "icons", "barrel_icon.png"))
        pixmap = QPixmap(path)
        if label:
            label.setPixmap(pixmap)
    
    def set_dose_icon(self):
        """Set the radiation dose icon"""
        label = self.ui.findChild(QLabel, "iconDose")
        path = os.path.abspath(os.path.join("_UI", "icons", "dose_rate_icon.png"))
        pixmap = QPixmap(path)
        if label:
            label.setPixmap(pixmap)
    
    def set_temp_icon(self):
        """Set the temperature icon"""
        label = self.ui.findChild(QLabel, "iconTemp")
        path = os.path.abspath(os.path.join("_UI", "icons", "temperature_icon.png"))
        pixmap = QPixmap(path)
        if label:
            label.setPixmap(pixmap)

    def set_activity_icon(self):
        """Set the activity icon"""
        label = self.ui.findChild(QLabel, "iconActivity")
        path = os.path.abspath(os.path.join("_UI", "icons", "activity_icon.png"))
        pixmap = QPixmap(path)
        if label:
            label.setPixmap(pixmap)

    def set_isotope_icon(self):
        """Set the isotope icon"""
        label = self.ui.findChild(QLabel, "iconIsotope")
        path = os.path.abspath(os.path.join("_UI", "icons", "isotope_icon.png"))
        pixmap = QPixmap(path)
        if label:
            label.setPixmap(pixmap) 
    
    def set_dose_value(self, dose, acc):
        labelDose = self.ui.findChild(QLabel, "doseValue")
        labelAcc = self.ui.findChild(QLabel, "accValue")
        if labelDose:
            labelDose.setText(f"{dose:.2f}")
            self.last_paed = dose
        if labelAcc:
            labelAcc.setText(f"± {acc} %")

    # def set_dose_value(self, dose, acc):
    #     label = self.ui.findChild(QLabel, "doseValue")
    #     if label:
    #         label.setText(f"{dose:.2f} мкЗв/год ± {acc}%")
    #         self.last_paed = dose

    def set_temp_value(self, value):
        label = self.ui.findChild(QLabel, "tempValue")
        if label:
            label.setText(f"{value}")
            # Сохраняем числовое значение
            try:
                self.last_temperature = float(value.split()[0])
            except:
                pass


    
    
    def add_spectrum(self):
        self.spectrum = SpectrumWidget()
        layout = self.ui.spectrumWidget.layout()
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.spectrum)
    

    # def set_detector_status(self, low_failure: bool, high_failure: bool, result_valid: bool):
    #     """
    #     Устанавливает состояние детекторов и валидность результата.
    #     low_failure: True - отказ низкочувствительного детектора, False - норма
    #     high_failure: True - отказ высокочувствительного детектора, False - норма
    #     result_valid: True - результат валидный, False - невалидный
    #     """
    #     # Низкочувствительный детектор
    #     low_label = self.ui.findChild(QLabel, "lowDetectorValue")
    #     if low_label:
    #         if not low_failure:
    #             low_label.setText("Відмова")
    #             low_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
    #         else:
    #             low_label.setText("Норма")
    #             low_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
        
    #     # Высокочувствительный детектор
    #     high_label = self.ui.findChild(QLabel, "highDetectorValue")
    #     if high_label:
    #         if not high_failure:
    #             high_label.setText("Відмова")
    #             high_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
    #         else:
    #             high_label.setText("Норма")
    #             high_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
        
    #     # Валидность результата
    #     valid_label = self.ui.findChild(QLabel, "validityValue")
    #     if valid_label:
    #         if result_valid:
    #             valid_label.setText("Норма")
    #             valid_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
    #         else:
    #             valid_label.setText("Невалідний")
    #             valid_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")

    #     # status_label = self.ui.findChild(QLabel, "statusValue")
    #     # status_label.setText("Норма")
    #     # status_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")

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
            if low_failure:
                low_label.setText("Відмова")
                low_label.setStyleSheet("color: red; font: 600 11pt 'Segoe UI';")
            else:
                low_label.setText("Норма")
                low_label.setStyleSheet("color: green; font: 600 11pt 'Segoe UI';")
        
        # Высокочувствительный детектор
        high_label = self.ui.findChild(QLabel, "highDetectorValue")
        if high_label:
            if high_failure:
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
        
        # Сохраняем для БД
        self.last_low_status = 1 if low_failure else 0
        self.last_high_status = 1 if high_failure else 0
        self.last_valid = 1 if result_valid else 0
   
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

    # app.py - класс DeviceCardBarrel - метод add_spectrum_data

    def add_spectrum_data(self, channels):
        """
        Добавляет полученный массив спектра к накопленному буферу
        channels: list[int] - 1024 канала
        """
        if len(channels) != 1024:
            return
        
        # Почленное сложение
        for i in range(1024):
            self.spectrum_buffer[i] += channels[i]
        
        self.spectrum_counter += 1
        
        # Опционально: обновление отображения спектра
        self.update_spectrum_display()
        
        # Проверка: достигнут ли лимит 600 спектров
        if self.spectrum_counter >= 600:
            self.calculate_activity()

    def is_spectrum_ready(self) -> bool:
        """Проверяет, накоплено ли 600 спектров"""
        return self.spectrum_counter >= 600

    
    def reset_spectrum(self):
        """
            Сбрасывает накопленный спектр и счётчик
        """
        self.spectrum_buffer = [0] * 1024
        self.spectrum_counter = 0
        self.update_spectrum_display()
        
        # Сохраняем событие
        if hasattr(self, 'parent_app') and self.parent_app:
            device_id = self.parent_app.db_manager.get_device_id(self.serial_number)
            if device_id:
                self.parent_app.db_manager.save_system_event(device_id, "spectrum_reset", "Спектр скинуто")

    def get_spectrum_buffer(self):
        """Возвращает накопленный буфер спектра"""
        return self.spectrum_buffer

    def get_spectrum_counter(self):
        """Возвращает текущее значение счётчика"""
        return self.spectrum_counter

    def update_spectrum_display(self):
        """
        Отображает текущий накопленный спектр в spectrumWidget
        """
        # Проверяем, есть ли виджет спектра
        if hasattr(self, 'spectrum') and self.spectrum:
            # Передаём данные в SpectrumWidget для отрисовки
            self.spectrum.update_data(self.spectrum_buffer)

    # app.py - класс DeviceCardBarrel - метод calculate_activity

    # def calculate_activity(self):
    #     """
    #     Расчёт активности раствора на основе накопленного спектра (600 спектров = ~30 минут)
    #     Сохраняет результат в историю и сбрасывает буфер для следующего цикла.
    #     """
               
    #     # Заглушка расчёта активности
    #     # Позже формула будет заменена на реальную
    #     total_counts = sum(self.spectrum_buffer)
        
    #     # Условная формула (заглушка)
    #     activity = total_counts / 600 / 1000  # кБк
        
    #     # Сохраняем в историю с текущей датой/временем
    #     timestamp = QDateTime.currentDateTime()
        
    #     self.activity_history.append({
    #         "timestamp": timestamp,
    #         "activity": activity
    #     })
        
    #     # Выводим в лог
    #     if hasattr(self, 'parent_app') and self.parent_app:
    #         self.parent_app.ui.textEdit.append(
    #             f"Цистерна №{self.posit_number}: розраховано активність = {activity:.2f} кБк "
    #             f"(сумарно {total_counts} імпульсів за 600 спектрів)"
    #         )
        
    #     # Сбрасываем буфер и счётчик для следующего цикла накопления
    #     self.reset_spectrum()

   
    def calculate_activity(self):
        """
        Расчёт активности раствора на основе накопленного спектра (600 спектров = ~30 минут)
        Сохраняет результат в историю и в БД, затем сбрасывает буфер.
        """
        from PySide6.QtCore import QDateTime
        
        total_counts = sum(self.spectrum_buffer)
        
        # Заглушка расчёта активности (позже заменится на реальную формулу)
        activity = total_counts / 600 / 1000  # кБк
        
        timestamp = QDateTime.currentDateTime()
        
        # Сохраняем в историю (для гистограммы)
        self.activity_history.append({
            "timestamp": timestamp,
            "activity": activity
        })
        
        # Сохраняем в БД
        if hasattr(self, 'parent_app') and self.parent_app:
            device_id = self.parent_app.db_manager.get_device_id(self.serial_number)
            
            if device_id is not None:
                fullness_status = "full" if self.is_full else "empty"
                ready_to_drain = 0  # заглушка, позже будет рассчитываться
                
                self.parent_app.db_manager.save_cistern_measurement(
                    device_id=device_id,
                    paed=self.last_paed_from_spectrum,
                    activity=activity,
                    low_status=self.last_low_status,
                    high_status=self.last_high_status,
                    valid=self.last_valid,
                    fullness_status=fullness_status,
                    ready_to_drain=ready_to_drain
                )
                
                self.parent_app.ui.textEdit.append(
                    f"Цистерна №{self.posit_number}: збережено вимірювання в БД (активність = {activity:.2f} кБк)"
                )
            else:
                self.parent_app.ui.textEdit.append(
                    f"Помилка: прилад {self.serial_number} не знайдено в БД"
                )
        
        # Сбрасываем буфер и счётчик для следующего цикла накопления
        self.reset_spectrum()




    def plot_activity_histogram(self):
        """
        Строит гистограмму активности по сохранённой истории.
        Вызывается по кнопке "Побудувати" на вкладке "Гістограма".
        """
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure
        
        if not self.activity_history:
            if hasattr(self, 'parent_app') and self.parent_app:
                self.parent_app.ui.textEdit.append(
                    f"Цистерна №{self.posit_number}: немає даних активності для побудови графіка"
                )
            return
        
        # Получаем виджет для гистограммы
        hist_widget = self.ui.findChild(QWidget, "histogramWidget")
        if not hist_widget:
            return
        
        # Очищаем старый график
        for child in hist_widget.children():
            if isinstance(child, FigureCanvas):
                child.deleteLater()
        
        # Создаём новый график
        figure = Figure()
        canvas = FigureCanvas(figure)
        ax = figure.add_subplot(111)
        
        # Подготовка данных
        activities = [item["activity"] for item in self.activity_history]
        indices = range(1, len(activities) + 1)
        
        # Построение гистограммы (столбцы)
        ax.bar(indices, activities, width=0.8, color='steelblue')
        ax.set_xlabel("Номер вимірювання")
        ax.set_ylabel("Активність, кБк")
        ax.set_title(f"Активність цистерни №{self.posit_number}")
        ax.grid(True, alpha=0.3)
        
        # Добавляем подписи над столбцами
        if activities:
            max_activity = max(activities)
            for i, act in enumerate(activities):
                ax.text(i + 1, act + 0.01 * max_activity, f"{act:.1f}", 
                        ha='center', va='bottom', fontsize=8)
        
        canvas.draw()
        
        # Размещаем график
        layout = QVBoxLayout(hist_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(canvas)
        

class DeviceCardWall(QWidget):
    """
        Клас настінного детектору(у кімнаті)
    """
    def __init__(self, parent_app=None):
        super().__init__()
        self.parent_app = parent_app

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
        self.set_wall_icon()
        self.set_dose_icon()
        self.set_temp_icon()
        #self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        #self.ui.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.last_temperature = 0.0
 
    def set_serial(self, serial):
        label = self.ui.findChild(QLabel, "serialValue")
        if label:
            label.setText(f"{serial}")
    
    def set_position(self, position):
        label = self.ui.findChild(QLabel, "positionValue")
        if label:
            label.setText(f"{position}")
    
    def set_wall_icon(self):
        """Set the wall detector icon"""
        label = self.ui.findChild(QLabel, "detectorIcon")
        path = os.path.abspath(os.path.join("_UI", "icons", "wall_detector_icon.png"))
        pixmap = QPixmap(path)
        if label:
            label.setPixmap(pixmap)
    
    def set_dose_icon(self):
        """Set the radiation dose icon"""
        label = self.ui.findChild(QLabel, "iconDose")
        path = os.path.abspath(os.path.join("_UI", "icons", "dose_rate_icon.png"))
        pixmap = QPixmap(path)
        if label:
            label.setPixmap(pixmap)
    
    def set_temp_icon(self):
        """Set the temperature icon"""
        label = self.ui.findChild(QLabel, "iconTemp")
        path = os.path.abspath(os.path.join("_UI", "icons", "temperature_icon.png"))
        pixmap = QPixmap(path)
        if label:
            label.setPixmap(pixmap)
    
    def set_dose_value(self, dose, acc):
        labelDose = self.ui.findChild(QLabel, "doseValue")
        labelAcc = self.ui.findChild(QLabel, "accValue")
        if labelDose:
            labelDose.setText(f"{dose:.2f}")
        if labelAcc:
            labelAcc.setText(f"± {acc} %")

    # def set_dose_value(self, dose, acc):
    #     label = self.ui.findChild(QLabel, "doseValue")
    #     if label:
    #         label.setText(f"{dose:.2f} мкЗв/год ± {acc}%")


    # def set_temp_value(self, value):
    #     label = self.ui.findChild(QLabel, "tempValue")
    #     if label:
    #         label.setText(f"{value}")

    def set_temp_value(self, value):
        label = self.ui.findChild(QLabel, "tempValue")
        if label:
            label.setText(f"{value}")
            # Сохраняем числовое значение
            try:
                self.last_temperature = float(value.split()[0])
            except:
                pass


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
    sync_cisterns_to_manager = Signal(object)


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

        # атрибут - объект для работы с базами данных
        self.db_manager = DatabaseManager()

        self.db_manager.save_system_event(None, "app_start", "Програма запущена")

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

        self.missing_device_sn = None


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


    def setup_ui(self):
        """
            Розмітка контейнерів для карток приладів
        """
        self.barrel_container = self.ui.findChild(QWidget, "containerBarrel")
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

    def db_window(self):
        """
        Вивід вікна для бази даних
        """
        from database.db_view_window import DBViewWindow
        self.db_window_instance = DBViewWindow(self.db_manager, self.ui)
        self.db_window_instance.resize(1200, 800)
        self.db_window_instance.show()


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

        # Зупинка системи
        self.butt_system_stop = self.ui.findChild(QAction, "butt_system_stop_3")
        if self.butt_system_stop:
            self.butt_system_stop.triggered.connect(self.stop_system)

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

        # Сигнал обновления ПАЕД в DeviceManager
        self.device_manager.update_device_paed.connect(self.device_manager.set_device_paed)

        self.device_manager.system_event.connect(self.on_system_event)

        # Сигнал пропажи прибора
        self.device_manager.device_missing.connect(self.on_device_missing)

        # Пункт меню замены прибора
        self.butt_replace_device = self.ui.findChild(QAction, "butt_replace_device")
        if self.butt_replace_device:
            self.butt_replace_device.triggered.connect(self.open_replace_dialog)


    def on_system_event(self, serial_number, event_type, description):
        device_id = self.db_manager.get_device_id(serial_number) if serial_number else None
        self.db_manager.save_system_event(device_id, event_type, description)
    

    def on_show_info(self, info: str):
        """
            Слот выведения текстовых данных
        """
        self.ui.textEdit.append(info)    

    def stop_system(self):
        """Зупиняє опитування приладів"""
        if self.device_manager:
            self.device_manager.stop_all()
            self.ui.textEdit.append("Систему зупинено")
            # Деактивуємо пункт меню зупинки
            if hasattr(self, 'butt_system_stop') and self.butt_system_stop:
                self.butt_system_stop.setEnabled(False)

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
                    
                    # Отправляем ПАЕД в DeviceManager
                    self.device_manager.update_device_paed.emit(sn, dose)
                    
                    low_failure = data.get("low_sens_failure", True)
                    high_failure = data.get("high_sens_failure", True)
                    result_valid = data.get("result_valid", False)
                    
                    card.set_detector_status(low_failure, high_failure, result_valid)
                    
                    # Сохранение в БД
                    device_id = self.db_manager.get_device_id(sn)
                    if device_id is not None:
                        if card.location_type == "room":
                            temp_value = getattr(card, 'last_temperature', 0.0)
                            self.db_manager.buffer_wall_measurement(
                                device_id=device_id,
                                paed=dose,
                                temperature=temp_value,
                                low_status=1 if low_failure else 0,
                                high_status=1 if high_failure else 0,
                                valid=1 if result_valid else 0
                            )
                        elif card.location_type == "cistern":
                            fullness_status = "full" if getattr(card, 'is_full', False) else "empty"
                            self.db_manager.save_cistern_measurement(
                                device_id=device_id,
                                paed=dose,
                                activity=0.0,
                                low_status=1 if low_failure else 0,
                                high_status=1 if high_failure else 0,
                                valid=1 if result_valid else 0,
                                fullness_status=fullness_status,
                                ready_to_drain=0
                            )
                    else:
                        self.ui.textEdit.append(f"Помилка: прилад {sn} не знайдено в БД")

            elif mode == "Temperature":
                data = self.device_manager._temp_data(buff)
                if data:
                    card.set_temp_value(data)
                    try:
                        temp_float = float(data.split()[0])
                        card.last_temperature = temp_float
                    except:
                        pass
                    self.ui.textEdit.append(f"Parsed temperature for {sn}:  {data}\n-------------------")

            elif mode == "StartSpectre":
                self.ui.textEdit.append(f"Початок збору спектру для {sn}")

            elif mode == "GetSpectre":
                if isinstance(packet.buff, dict):
                    channels = packet.buff.get("channels", [])
                    paed_value = packet.buff.get("paed_value", 0.0)
                    test_byte = packet.buff.get("test_byte", 0)
                    result_valid = packet.buff.get("valid", False)
                    
                    self.ui.textEdit.append(f"Spectrum for {sn}: {len(channels)} channels, PAED={paed_value:.2f} μSv/h, valid={result_valid}")
                    
                    # Отправляем ПАЕД в DeviceManager
                    self.device_manager.update_device_paed.emit(sn, paed_value)
                    
                    # Запоминаем ПАЕД для использования в calculate_activity
                    card.last_paed_from_spectrum = paed_value
                    
                    # Передаём данные в карточку прибора
                    card.add_spectrum_data(channels)
                    
                    # Обновляем ПАЕД
                    card.set_dose_value(paed_value, 0)
                    
                    # Обновляем состояние детекторов из test_byte
                    high_failure = bool(test_byte & 0b00000001)
                    low_failure = bool(test_byte & 0b00000010)
                    card.set_detector_status(low_failure, high_failure, result_valid)
                    
                    # Сохраняем измерение в БД (без активности)
                    device_id = self.db_manager.get_device_id(sn)
                    if device_id is not None and card.location_type == "cistern":
                        fullness_status = "full" if getattr(card, 'is_full', False) else "empty"
                        self.db_manager.save_cistern_measurement(
                            device_id=device_id,
                            paed=paed_value,
                            activity=0.0,
                            low_status=1 if low_failure else 0,
                            high_status=1 if high_failure else 0,
                            valid=1 if result_valid else 0,
                            fullness_status=fullness_status,
                            ready_to_drain=0
                        )
                    elif device_id is None:
                        self.ui.textEdit.append(f"Помилка: прилад {sn} не знайдено в БД")
                    
                    # Проверяем, достигнут ли лимит в 600 спектров
                    if card.is_spectrum_ready():
                        card.calculate_activity()
                else:
                    self.ui.textEdit.append(f"Помилка: отримано некоректні дані спектру для {sn}")

        except Exception as e:
            self.ui.textEdit.append(f"Error parsing packet for {sn}: {e}\n-------------------")        
    
   

    def create_device_card(self, device):
        """
            Створення вікна для приладу
        """
        if device.get("location_type") == "cistern":
            card = DeviceCardBarrel(parent_app=self)
            card.location_type = "cistern"
        elif device.get("location_type") == "room":
            card = DeviceCardWall(parent_app=self)
            card.location_type = "room"
        else:
            self.ui.textEdit.append(
                f"Помилка: невідомий тип розташування '{device.get('location_type')}' "
                f"для приладу SN {device.get('serial_number')}"
            )
            return None
        
        # Общие атрибуты для всех карточек
        card.posit_number = device.get("posit_number")
        card.serial_number = device.get("serial_number")
        card.location_type = device.get("location_type")
        
        return card

 

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
        
        #опціонально, щоб картка не розширювалась на весь контейнер
        spacerB = QSpacerItem(1, 1, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        spacerW = QSpacerItem(1, 1, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        self.barrel_grid.addItem(spacerB)
        self.wall_layout.addItem(spacerW)

        # Вносим в приборы данные про цистерны
        self.sync_devices_with_cisterns()

        # Начинаем процедуру опроса внешней Системы Управления
        self.start_test_polling("config/cistern.json")

    

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

    
    # def sync_devices_with_cisterns(self):
    #     """
    #         Синхронизируем только GUI-карточки с self.cistern_dict.
    #         НИКОГДА не вызываем методы объектов DeviceManager из GUI-потока.
    #     """
    #     # Проверка: если cistern_dict пуст или не загружен - принудительно загружаем
    #     if not self.cistern_dict:
    #         self.load_cistern_data("config/cistern.json")
        
    #     for sn, card in self.cards_by_sn.items():
    #         try:
    #             # пытаемся получить posit из карточки (если карточка его сохранила)
    #             posit = getattr(card, "posit_number", None) or getattr(card, "posit", None)
    #             if posit is None:
    #                 continue
    #             # сохраняем состояние на карточке (визуальное обновление реализовать в карточке)
    #             setattr(card, "is_full", bool(self.cistern_dict.get(int(posit), False)))
    #             # card.set_barrel_image(card.is_full)  # раскомментировать если нужно обновить иконку
    #         except Exception:
    #             continue


    def sync_devices_with_cisterns(self):
        """
            Синхронизируем только GUI-карточки с self.cistern_dict.
            НИКОГДА не вызываем методы объектов DeviceManager из GUI-потока.
        """
        if not self.cistern_dict:
            self.load_cistern_data("config/cistern.json")
        
        for sn, card in self.cards_by_sn.items():
            try:
                posit = getattr(card, "posit_number", None) or getattr(card, "posit", None)
                if posit is None:
                    continue
                
                old_full = getattr(card, "is_full", False)
                new_full = bool(self.cistern_dict.get(int(posit), False))
                
                # Сохраняем новое состояние
                card.is_full = new_full
                card.set_barrel_image(new_full)
                
                # Если цистерна стала пустой - сбрасываем спектральные данные
                if old_full != new_full and not new_full:
                    # Цистерна опустошена - сброс спектра
                    if hasattr(card, 'reset_spectrum'):
                        card.reset_spectrum()
                        # Выводим информацию в лог
                        self.ui.textEdit.append(f"Цистерна №{posit} спорожнена. Спектр скинуто.")
                
                # Если цистерна стала полной - сброс спектра (начало нового накопления)
                if old_full != new_full and new_full:
                    if hasattr(card, 'reset_spectrum'):
                        card.reset_spectrum()
                        self.ui.textEdit.append(f"Цистерна №{posit} заповнена. Початок накопичення спектру.")
                        
            except Exception as e:
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
        # Если new_data не передан — используем данные из lineEdit (имитация)
        if new_data is None:
            text = self.ui.lineEdit.text().strip()
            if text == "Full":
                new_data = {1: True}                
            elif text == "Empty":
                new_data = {1: False}                
            else:                
                return

        updated = False
        for num, new_value in new_data.items():
            if num not in self.cistern_dict:
                # Ошибка: цистерна отсутствует в конфигурации
                self.ui.textEdit.append(
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

                # Обновляем GUI‑карточки и сбрасываем спектр при изменении состояния
                for sn, card in self.cards_by_sn.items():
                    if getattr(card, "posit_number", None) == num or getattr(card, "posit", None) == num:
                        old_full = getattr(card, "is_full", False)
                        card.is_full = new_value
                        card.set_barrel_image(new_value)
                        
                        # Если состояние изменилось
                        if old_full != new_value:
                            if new_value:
                                # Цистерна стала полной
                                if hasattr(card, 'reset_spectrum'):
                                    card.reset_spectrum()
                                    self.ui.textEdit.append(f"Цистерна №{num} заповнена. Початок накопичення спектру.")
                                # Системное событие - заполнение цистерны
                                device_id = self.db_manager.get_device_id(card.serial_number)
                                if device_id:
                                    self.db_manager.save_system_event(device_id, "cistern_filled", f"Цистерна №{num} заповнена")
                            else:
                                # Цистерна стала пустой
                                if hasattr(card, 'reset_spectrum'):
                                    card.reset_spectrum()
                                    self.ui.textEdit.append(f"Цистерна №{num} спорожнена. Спектр скинуто.")
                                # Системное событие - слив цистерны
                                device_id = self.db_manager.get_device_id(card.serial_number)
                                if device_id:
                                    self.db_manager.save_system_event(device_id, "cistern_drained", f"Цистерна №{num} спорожнена")
                        break

        #self.ui.textEdit.append(f"App: emitting cistern_dict (type={type(self.cistern_dict)}): {self.cistern_dict!r}")
        # Если были изменения — перезаписываем файл cistern.json и синхронизируем с DeviceManager
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
        self.db_manager.save_system_event(None, "app_stop", "Програма зупинена")
        self.db_manager.close()

    def start_polling_and_test_system(self):
        """
            Слот, запускаемый по нажатию кнопки "Старт системы".
            Запускает циклический опрос приборов и имитацию опроса внешней системы.
        """
        # Запуск основного опроса приборов
        self.start_polling.emit()
        
        # Запуск имитации опроса внешней системы (состояние цистерн)
        self.start_test_polling("config/cistern.json")
    
    def on_device_connection_status(self, serial_number: str, connected: bool, crc_error: bool):
        """
        Обработка изменения статуса связи прибора
        """
        card = self.cards_by_sn.get(serial_number)
        if card:
            card.set_connection_status(connected, crc_error)   

    def on_device_missing(self, serial_number: str):
        """Прибор пропал — активируем пункт меню замены"""
        if hasattr(self, 'butt_replace_device') and self.butt_replace_device:
            self.butt_replace_device.setEnabled(True)
        self.missing_device_sn = serial_number

    def open_replace_dialog(self):
        """Открывает диалог замены прибора"""
        from dialogs.device_replace_dialog import DeviceReplaceDialog
        
        # Собираем список пропавших приборов из DeviceManager
        missing_devices = []
        for device in self.device_manager.devices:
            if device.no_answer_count >= 5:
                missing_devices.append({
                    "serial_number": device.serial_number,
                    "location_type": device.location_type,
                    "position_number": device.posit_number
                })
        
        if not missing_devices:
            self.ui.textEdit.append("Немає приладів для заміни")
            return
        
        dialog = DeviceReplaceDialog(self.db_manager, missing_devices, self.ui)
        dialog.exec()
        
        # После закрытия диалога деактивируем пункт меню
        if self.butt_replace_device:
            self.butt_replace_device.setEnabled(False) 


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
