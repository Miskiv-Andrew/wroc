# app.py

import sys
from PySide6.QtWidgets import QApplication, QWidget, QGridLayout, QVBoxLayout, QPushButton, QLabel, QSizePolicy, QSpacerItem, QDialog, QLineEdit, QMessageBox, QHBoxLayout
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QThread, QMetaObject, QTimer , Qt, QObject, Signal, QDateTime
from devices.device_manager import DeviceManager
from PySide6.QtGui import QAction, QPixmap
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import json, numpy as np
import os, math
from sklearn.decomposition import NMF
from scipy.optimize import nnls

from database.db_manager import DatabaseManager
from dialogs.device_replace_dialog import DeviceReplaceDialog


# ============================================================
# ДІАЛОГ ВВОДУ ПАРОЛЯ
# ============================================================
class PasswordDialog(QDialog):
    """
    Діалогове вікно для введення пароля перед запуском програми.
    Паролі зберігаються безпосередньо в коді.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        # Заголовок і розмір вікна
        self.setWindowTitle("Авторизація")
        self.setFixedSize(350, 150)

        # ------------------------------------------------------------
        # Список дозволених паролів (можна розширювати)
        # ------------------------------------------------------------
        self.valid_passwords = ["qwerty"]  # тут зберігаються паролі

        # ------------------------------------------------------------
        # Створюємо елементи інтерфейсу
        # ------------------------------------------------------------
        layout = QVBoxLayout(self)

        # Текст-підказка
        label = QLabel("Введіть пароль для доступу до програми:")
        layout.addWidget(label)

        # Поле для введення пароля (символи приховані)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)

        # Рядок з кнопками OK / Скасувати
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.cancel_button = QPushButton("Скасувати")

        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        # ------------------------------------------------------------
        # Підключаємо сигнали кнопок
        # ------------------------------------------------------------
        self.ok_button.clicked.connect(self.check_password)
        self.cancel_button.clicked.connect(self.reject)  # закриває діалог з кодом відмови

        # Якщо користувач натискає Enter у полі введення — це те саме, що натиснути OK
        self.password_input.returnPressed.connect(self.check_password)

    def check_password(self):
        """
        Перевіряє введений пароль.
        Якщо пароль правильний — закриває діалог з кодом успіху (accept).
        Якщо неправильний — показує помилку та очищує поле.
        """
        password = self.password_input.text()

        if password in self.valid_passwords:
            self.accept()  # пароль правильний — закриваємо діалог із успіхом
        else:
            # Показуємо повідомлення про помилку
            QMessageBox.critical(
                self,
                "Помилка",
                "Неправильний пароль. Спробуйте ще раз."
            )
            self.password_input.clear()  # очищаємо поле
            self.password_input.setFocus()  # ставимо курсор у поле



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
  
    def __init__(self, parent_app=None):
        super().__init__()
        self.parent_app = parent_app
        self.repeat_counter = 100

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
        self.set_spectrum_ui_enabled(False)

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
        self.is_full = False  

        self.last_acquisition_time = 0.0     


    
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

        scaled_pixmap = pixmap.scaledToWidth(80, Qt.SmoothTransformation)
        label.setPixmap(scaled_pixmap)  

        self.is_full = full
        self.set_spectrum_ui_enabled(full)
    
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
    
    def set_temp_value(self, value):
        label = self.ui.findChild(QLabel, "tempValue")
        if label:
            label.setText(f"{value}")
            # Сохраняем числовое значение
            try:
                self.last_temperature = float(value.split()[0])
            except:
                pass
    
    def set_spectrum_ui_enabled(self, enabled: bool):
        if not hasattr(self, 'selector_graph') or self.selector_graph is None:
            self.selector_graph = self.ui.findChild(QWidget, "selectorGraph")
        if not hasattr(self, 'spectrum_widget') or self.spectrum_widget is None:
            self.spectrum_widget = self.ui.findChild(QWidget, "spectrumWidget")
        if not hasattr(self, 'histogram_widget') or self.histogram_widget is None:
            self.histogram_widget = self.ui.findChild(QWidget, "histogramWidget")
        if self.selector_graph:
            self.selector_graph.setEnabled(enabled)
        if self.spectrum_widget:
            self.spectrum_widget.setVisible(enabled)
        if self.histogram_widget:
            self.histogram_widget.setVisible(enabled)
        
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
        
        # # Сохраняем для БД
        self.last_low_status = 1 if low_failure else 0
        self.last_high_status = 1 if high_failure else 0
        self.last_valid = 1 if result_valid else 0
 
        #  # # Сохраняем для БД - инвертировали логику
        # low_status = 0 if low_failure else 1
        # high_status = 0 if high_failure else 1
        # valid = 0 if result_valid else 1
   
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

    # def add_spectrum_data(self, channels):
    #     """
    #     Добавляет полученный массив спектра к накопленному буферу
    #     channels: list[int] - 1024 канала
    #     """
    #     if len(channels) != 1024:
    #         return
        
    #     # Почленное сложение
    #     for i in range(1023):
    #         self.spectrum_buffer[i] += channels[i]
        
    #     self.spectrum_counter += 1
        
    #     # Опционально: обновление отображения спектра
    #     self.update_spectrum_display()
        
    #     # Проверка: достигнут ли лимит 600 спектров
    #     if self.spectrum_counter >= self.repeat_counter:   #600:  10 - для проверки обработки спектра
    #         self.calculate_activity()

    def add_spectrum_data(self, channels):
        """
        Додає отриманий масив спектра до накопиченого буфера.
        channels: list[int] - 1024 елементи (1023 спектра + час набора)
        """
        if len(channels) != 1024:
            return
        
        # Зберігаємо час набора спектра (останній елемент)
        self.last_acquisition_time = channels[-1]
        
        # Сумуємо тільки спектр (перші 1023 елементи)
        for i in range(1023):
            self.spectrum_buffer[i] += channels[i]
        
        self.spectrum_counter += 1
        
        self.update_spectrum_display()
        
        if self.spectrum_counter >= self.repeat_counter:
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
   

    def calculate_activity(self):
        """
        Розрахунок активності та ідентифікація ізотопів.
        """
        # ------------------------------------------------------------
        # 1. Розрахунок загальної активності за всім накопиченим спектром
        # ------------------------------------------------------------
        total_counts = sum(self.spectrum_buffer)
        activity = total_counts / 600 / 1000

        timestamp = QDateTime.currentDateTime()

        self.activity_history.append({
            "timestamp": timestamp,
            "activity": activity
        })

        # ------------------------------------------------------------
        # 2. Ідентифікація ізотопів
        # ------------------------------------------------------------
        if hasattr(self, 'parent_app') and self.parent_app:

            # result = self.parent_app.identify_isotopes(
            #     self.spectrum_buffer,
            #     self.posit_number
            # )

            spectrum_with_time = list(self.spectrum_buffer) + [self.last_acquisition_time]
            result = self.parent_app.identify_isotopes(
            spectrum_with_time,
            self.posit_number
            )

            if result:
                # ------------------------------------------------------------
                # 3. Отримуємо дані з результату
                # ------------------------------------------------------------
                presence = result.get("isotope_presence", {})
                isotope_percents = result.get("isotope_percents", {})
                component_sums = result.get("component_sums", {})
                background_found = result.get("background_found", False)

                self.parent_app.ui.textEdit.append(
                    f"Цистерна №{self.posit_number}:"
                )
                self.parent_app.ui.textEdit.append("")  # пустий рядок

                # ------------------------------------------------------------
                # 4. Виводимо ізотопи
                # ------------------------------------------------------------              
               
                isotopes_list = self.parent_app.cistern_isotopes.get(
                    self.posit_number,
                    []
                )

                # Отримуємо час набора реального спектра
                real_time = result.get("real_time", 1.0)

                # Виводимо час набора реального спектра
                self.parent_app.ui.textEdit.append(f"Час набора реального спектра: {real_time} сек")
                self.parent_app.ui.textEdit.append("")  # пустий рядок

                for name in isotopes_list:
                    detected = presence.get(name, False)
                    percent = isotope_percents.get(name, 0)
                    sum_val_norm = component_sums.get(name, 0)
                    sum_val_abs = sum_val_norm * real_time  # переводимо в абсолютні значення

                    status = "обнаружен" if detected else "не обнаружен"

                    self.parent_app.ui.textEdit.append(
                        f"{name}:"
                    )
                    self.parent_app.ui.textEdit.append(
                        f"    вклад = {int(sum_val_abs):,} имп."
                    )
                    self.parent_app.ui.textEdit.append(
                        f"    доля = {percent:.1f} %"
                    )
                    self.parent_app.ui.textEdit.append(
                        f"    {status}"
                    )
                    self.parent_app.ui.textEdit.append("")  # пустий рядок

                # ------------------------------------------------------------
                # 5. Виводимо фон
                # ------------------------------------------------------------
                # if background_found:
                #     bg_sum = component_sums.get("background", 0)
                #     self.parent_app.ui.textEdit.append(
                #         f"Фон: вклад = {int(bg_sum):,} имп., обнаружен"
                #     )
                # else:
                #     self.parent_app.ui.textEdit.append(
                #         "Фон: не обнаружен"
                #     )
                # self.parent_app.ui.textEdit.append("")  # пустий рядок

                if background_found:
                    bg_sum_norm = component_sums.get("background", 0)
                    bg_sum_abs = bg_sum_norm * real_time
                    self.parent_app.ui.textEdit.append(
                        f"Фон: вклад = {int(bg_sum_abs):,} имп., обнаружен"
                    )
                else:
                    self.parent_app.ui.textEdit.append(
                        "Фон: не обнаружен"
                    )

                # ------------------------------------------------------------
                # 6. Виводимо якість апроксимації
                # ------------------------------------------------------------
                relative_error = result.get("relative_error", None)

                if relative_error is not None:
                    self.parent_app.ui.textEdit.append(
                        f"Ошибка аппроксимации: {relative_error * 100:.2f} %"
                    )
                else:
                    error_sum = result.get("error_sum", 0)
                    self.parent_app.ui.textEdit.append(
                        f"Ошибка аппроксимации: {error_sum:.6f}"
                    )

                self.parent_app.ui.textEdit.append("---")

                # ------------------------------------------------------------
                # 7. Підготовка папки для експорту спектрів
                # ------------------------------------------------------------
                export_dir = "export"
                os.makedirs(export_dir, exist_ok=True)

                # ------------------------------------------------------------
                # 8. Приводимо загальний спектр до 1024 каналів
                # ------------------------------------------------------------
                target_len = 1024

                export_total_spectrum = np.array(
                    self.spectrum_buffer,
                    dtype=float
                )

                if len(export_total_spectrum) < target_len:
                    export_total_spectrum = np.pad(
                        export_total_spectrum,
                        (0, target_len - len(export_total_spectrum)),
                        mode='constant',
                        constant_values=0
                    )
                elif len(export_total_spectrum) > target_len:
                    export_total_spectrum = export_total_spectrum[:target_len]

                # ------------------------------------------------------------
                # 9. Зберігаємо загальний спектр
                # ------------------------------------------------------------
                with open(os.path.join(export_dir, "spectrum_total.txt"), "w") as f:
                    f.write(
                        "\n".join(str(int(x)) for x in export_total_spectrum)
                    )

                # ------------------------------------------------------------
                # 10. Зберігаємо всі розділені спектри
                # ------------------------------------------------------------
                components = result.get("components", {})

                for name, spectrum in components.items():
                    filename = f"spectrum_{name}.txt"
                    filepath = os.path.join(export_dir, filename)

                    with open(filepath, "w") as f:
                        f.write(
                            "\n".join(str(int(x)) for x in spectrum)
                        )

            # ------------------------------------------------------------
            # 11. Збереження результату вимірювання в БД
            # ------------------------------------------------------------
            device_id = self.parent_app.db_manager.get_device_id(
                self.serial_number
            )

            if device_id is not None:

                fullness_status = "full" if getattr(self, 'is_full', False) else "empty"

                self.parent_app.db_manager.save_cistern_measurement(
                    device_id=device_id,
                    paed=self.last_paed_from_spectrum,
                    temperature=self.last_temperature,
                    activity=activity,
                    low_status=self.last_low_status,
                    high_status=self.last_high_status,
                    valid=self.last_valid,
                    fullness_status=fullness_status,
                    ready_to_drain=0
                )

                self.parent_app.ui.textEdit.append(
                    f"Цистерна №{self.posit_number}: сохранено в БД "
                    f"(активность = {activity:.2f} кБк)"
                )

        # ------------------------------------------------------------
        # 12. Скидаємо буфер цистерни в БД
        # ------------------------------------------------------------
        if hasattr(self, 'parent_app') and self.parent_app:
            self.parent_app.db_manager.flush_cistern_buffer()

        # ------------------------------------------------------------
        # 13. Очищаємо буфер спектра після завершення обробки
        # ------------------------------------------------------------
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

        # Начальное состояние кнопок (до поиска приборов)
        if hasattr(self, 'butt_system_start'):
            self.butt_system_start.setEnabled(False)
        if hasattr(self, 'butt_system_stop'):
            self.butt_system_stop.setEnabled(False)


        # Загрузка эталонных спектров
        self.load_calibration_spectra()


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
        # self.device_manager = DeviceManager()  
        self.device_manager = DeviceManager(self.db_manager)   
        self.device_manager.moveToThread(self.device_manager_thread)
        self.device_manager_thread.finished.connect(self.device_manager.deleteLater)
        self.device_manager_thread.start()        

    def setup_connections(self):
        """
            Связываем кнопки интерфейса с методами DeviceManager и сигналы с обработчиками
        """ 

        # Сигнал старта поиска приборов
        self.butt_search_dev = self.ui.findChild(QAction, "butt_search_dev") 

        self.butt_search_dev.triggered.connect(self.on_search_devices)
        self.search_devices.connect(self.device_manager.find_rpii_ports)
        
        # Сигнал старта опроса приборов
        self.butt_system_start = self.ui.findChild(QAction, "butt_system_start")        
        self.butt_system_start.triggered.connect(self.start_polling_and_test_system)

        self.start_polling.connect(self.device_manager.dispatch_poll_step) 

        # Зупинка системи
        self.butt_system_stop = self.ui.findChild(QAction, "butt_system_stop_3")        
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
        self.butt_replace_device.setEnabled(True)
        if self.butt_replace_device:
            self.butt_replace_device.triggered.connect(self.open_replace_dialog)

    def load_calibration_spectra(self):
        """
        Загружает эталонные спектры из папки calibration/.
        Каждый файл должен содержать 1024 числа (по одному на строку).
        """
        self.calibration_spectra = {}
        calib_dir = "calibration"
        
        if not os.path.exists(calib_dir):
            self.ui.textEdit.append("Папка calibration/ не найдена")
            return
        
        for filename in os.listdir(calib_dir):
            if filename.endswith(".txt"):
                filepath = os.path.join(calib_dir, filename)
                try:
                    data = np.loadtxt(filepath)
                    # Приводим к 1024
                    if len(data) < 1024:
                        data = np.pad(data, (0, 1024 - len(data)), 'constant')
                    elif len(data) > 1024:
                        data = data[:1024]
                    
                    name = os.path.splitext(filename)[0]  # имя файла без расширения
                    self.calibration_spectra[name] = data
                    # self.ui.textEdit.append(f"Загружен эталон: {name}")
                    self.ui.textEdit.append(f"Загружен эталон: {name}, время набора: {data[1023]} сек")
                except Exception as e:
                    self.ui.textEdit.append(f"Ошибка загрузки {filename}: {e}")


    def on_system_event(self, serial_number, event_type, description):
        device_id = self.db_manager.get_device_id(serial_number) if serial_number else None
        self.db_manager.save_system_event(device_id, event_type, description)
    

    def on_show_info(self, info: str):
        """
            Слот выведения текстовых данных
        """
        self.ui.textEdit.append(info)   
  

    def stop_system(self):
        """
            Остановка опроса приборов
        """
        if self.device_manager:
            self.device_manager.stop_all()
            self.ui.textEdit.append("Систему зупинено")
            
            # Разблокируем кнопку замены
            if self.butt_replace_device:
                self.butt_replace_device.setEnabled(True)
            
            # Возвращаем состояние кнопок
            if self.butt_system_start:
                self.butt_system_start.setEnabled(True)
            if self.butt_system_stop:
                self.butt_system_stop.setEnabled(False)
            
            # Разблокируем кнопку поиска
            if hasattr(self, 'butt_search_dev'):
                self.butt_search_dev.setEnabled(True)   



    def on_device_packet(self, packet):
        """
        Обробка пакетів від приладів.
        Отримує пакет від DeviceManager через сигнал device_response.
        В залежності від режиму (RadDose, Temperature, StartSpectre, GetSpectre)
        виконує відповідну обробку та оновлює інтерфейс.
        """
        card = self.cards_by_sn.get(packet.serial_number)
        if card is None:
            return

        sn = packet.serial_number
        mode = packet.mode
        size = packet.size
        buff = packet.buff

        try:
            if mode == "RadDose":
                data = self.device_manager._paed_data(buff)
                if data:
                    dose = data["ped_value"]
                    accuracy = data["accuracy"]
                    card.set_dose_value(dose, accuracy)
                    
                    # Відправляємо ПАЕД в DeviceManager для оновлення стану приладу
                    self.device_manager.update_device_paed.emit(sn, dose)
                    
                    low_failure = data.get("low_sens_failure", True)
                    high_failure = data.get("high_sens_failure", True)
                    result_valid = data.get("result_valid", False)
                    
                    card.set_detector_status(low_failure, high_failure, result_valid)
                    
                    # Збереження в БД через буфер для цистерн,
                    # для настінних — через буфер настінних.
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
                            temp_value = getattr(card, 'last_temperature', 0.0)
                            fullness_status = "full" if getattr(card, 'is_full', False) else "empty"
                            # Додаємо в буфер цистерни, запис в БД відбудеться при досягненні repeat_counter
                            self.db_manager.buffer_cistern_measurement(
                                device_id=device_id,
                                paed=dose,
                                temperature=temp_value,
                                low_status=1 if low_failure else 0,
                                high_status=1 if high_failure else 0,
                                valid=1 if result_valid else 0,
                                fullness_status=fullness_status
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

            elif mode == "StartSpectre":
                self.ui.textEdit.append(f"Початок збору спектру для {sn}")

            elif mode == "GetSpectre":
                if isinstance(packet.buff, dict):
                    channels = packet.buff.get("channels", [])
                    paed_value = packet.buff.get("paed_value", 0.0)
                    accuracy = packet.buff.get("accuracy", 0)
                    test_byte = packet.buff.get("test_byte", 0)
                    result_valid = packet.buff.get("valid", False)

                    card.last_acquisition_time = packet.buff.get("acquisition_time", 0)
                    
                    # Відправляємо ПАЕД в DeviceManager
                    self.device_manager.update_device_paed.emit(sn, paed_value)
                    
                    # Запам'ятовуємо ПАЕД для використання в calculate_activity
                    card.last_paed_from_spectrum = paed_value
                    
                    # Передаємо дані в картку приладу (накопичення спектру)
                    card.add_spectrum_data(channels)
                    
                    # Оновлюємо ПАЕД на картці
                    card.set_dose_value(paed_value, accuracy)
                    
                    # Оновлюємо стан детекторів з test_byte
                    # Інверсія: 1 = норма, 0 = відмова (відповідно до логіки виведення)
                    high_failure = not bool(test_byte & 0b00000001)
                    low_failure = not bool(test_byte & 0b00000010)
                    card.set_detector_status(low_failure, high_failure, result_valid)
                    
                    # Збереження ПАЕД в буфер цистерни
                    device_id = self.db_manager.get_device_id(sn)
                    if device_id is not None and card.location_type == "cistern":
                        temp_value = getattr(card, 'last_temperature', 0.0)
                        fullness_status = "full" if getattr(card, 'is_full', False) else "empty"
                        # Додаємо в буфер цистерни
                        self.db_manager.buffer_cistern_measurement(
                            device_id=device_id,
                            paed=paed_value,
                            temperature=temp_value,
                            low_status=1 if low_failure else 0,
                            high_status=1 if high_failure else 0,
                            valid=1 if result_valid else 0,
                            fullness_status=fullness_status
                        )
                    elif device_id is None:
                        self.ui.textEdit.append(f"Помилка: прилад {sn} не знайдено в БД")
                    
                    # Перевіряємо, чи досягнуто ліміт накопичених спектрів
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

        # Отправляем начальное состояние цистерн в DeviceManager
        self.sync_cisterns_to_manager.emit(self.cistern_dict)

        # Начинаем процедуру опроса внешней Системы Управления
        self.start_test_polling("config/cistern.json")

        # Разблокируем кнопку поиска
        self.butt_search_dev.setEnabled(True)

         # Устанавливаем состояние кнопок после завершения поиска
        if self.butt_system_start:
            self.butt_system_start.setEnabled(True)
        if self.butt_system_stop:
            self.butt_system_stop.setEnabled(False)

    

    def on_objects_error(self, source: str, message: str):
        """
            Обрабатывает ошибки, возникшие в объектах созданных классов            
                Параметры:
                    source  - источник ошибки (например, "config.txt")
                    message - текст ошибки (например, "Контрольная сумма не совпадает")
            
            Выводит сообщение в textEdit, чтобы администратор видел проблему.
        """
        self.ui.textEdit.append(f"Помилка в  {source} : {message}")

        # Разблокируем кнопку поиска при ошибке        
        self.butt_search_dev.setEnabled(True)

        # Старт и Стоп неактивны - приборов нет    
        self.butt_system_start.setEnabled(False)    
        self.butt_system_stop.setEnabled(False)


    def load_cistern_data(self, json_file: str):
        """
        Загружает данные о заполненности цистерн и списках изотопов из файла.
        """
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.cistern_dict = {}
            self.cistern_isotopes = {}
            
            for k, v in data.items():
                pos = int(k)
                self.cistern_dict[pos] = bool(v.get("full", False))
                self.cistern_isotopes[pos] = v.get("isotopes", [])
                    
        except (FileNotFoundError, json.JSONDecodeError):
            print(f"Файл {json_file} відсутній або пошкоджений. Створюємо дефолтні дані (20 порожніх цистерн)")
            self.cistern_dict = {i: False for i in range(1, 21)}
            self.cistern_isotopes = {i: [] for i in range(1, 21)}
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump({str(i): {"full": False, "isotopes": []} for i in range(1, 21)}, f, ensure_ascii=False, indent=4)

    
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
                # print(f"Зміна стану цистерни №{num}: {current_value} → {new_value}")
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
                export_data = {}
                for pos, full in self.cistern_dict.items():
                    export_data[str(pos)] = {
                        "full": full,
                        "isotopes": self.cistern_isotopes.get(pos, [])
                    }
                json.dump(export_data, f, ensure_ascii=False, indent=4)
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
            Запуск опроса приборов
            Блокируем кнопку замены    
        """
        
        if self.butt_replace_device:
            self.butt_replace_device.setEnabled(False)
        
        # Блокируем кнопку поиска
        if hasattr(self, 'butt_search_dev'):
            self.butt_search_dev.setEnabled(False)
        
        # Старт активен? Нет, стоп активен
        if self.butt_system_start:
            self.butt_system_start.setEnabled(False)
        if self.butt_system_stop:
            self.butt_system_stop.setEnabled(True)
        
        # Запуск опроса
        self.start_polling.emit()
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
        """
            Открывает диалог замены/активации приборов.
            Активные  и неактивные приборы для замены 
            берутся из БД (is_active = 1, 0),
            
        """
        # Активные приборы (для замены) - берем из БД
        active_devices = self.db_manager.get_all_active_devices()
        
        # Неактивные приборы (для активации) - берем из БД
        inactive_devices = self.db_manager.get_inactive_devices()
        
        dialog = DeviceReplaceDialog(self.db_manager, active_devices, inactive_devices, self.ui)
        dialog.exec()

    def on_search_devices(self):
        """
            Запуск поиска приборов с блокировкой кнопки
        """
        # Блокируем кнопки поиска и опроса
        self.butt_search_dev.setEnabled(False)
        self.butt_system_start.setEnabled(False)    
        self.butt_system_stop.setEnabled(False)

        self.ui.textEdit.append("Пошук приладів...")
        # Запускаем поиск
        self.search_devices.emit()       

   
    # def identify_isotopes(self, spectrum, cistern_position):
    #     """
    #     Метод раскладывает общий измеренный спектр на компоненты:

    #         общий спектр ≈ фон + I-131 + Tc-99m

    #     В этой версии используется взвешенный NNLS.

    #     Этапы работы:
    #     1. Подготовка спектра и эталонов.
    #     2. Первичное разложение на фон + изотопы.
    #     3. Выделение остатка (невязки).
    #     4. Вторичное разложение остатка только на фон.
    #     5. Корректировка результатов в зависимости от обнаружения фона.
    #     6. Расчёт долей изотопов относительно скорректированной суммы.
    #     """

    #     # ------------------------------------------------------------
    #     # 1. Преобразуем входной спектр в numpy-массив
    #     # ------------------------------------------------------------
    #     spectrum = np.array(spectrum, dtype=float)

    #     # ------------------------------------------------------------
    #     # 2. Проверяем, загружены ли эталонные спектры
    #     # ------------------------------------------------------------
    #     if not hasattr(self, 'calibration_spectra') or not self.calibration_spectra:
    #         self.ui.textEdit.append("Ошибка: эталонные спектры не загружены")
    #         return None

    #     # ------------------------------------------------------------
    #     # 3. Получаем список изотопов для данной цистерны
    #     # ------------------------------------------------------------
    #     isotopes_list = self.cistern_isotopes.get(cistern_position, [])

    #     if not isotopes_list:
    #         self.ui.textEdit.append(
    #             f"Предупреждение: для цистерны {cistern_position} не заданы изотопы"
    #         )

    #     # ------------------------------------------------------------
    #     # 4. Формируем список компонентов
    #     # ------------------------------------------------------------
    #     # Фон всегда участвует в разложении.
    #     names = ["background"] + isotopes_list

    #     # Здесь храним реальные, НЕ нормированные эталонные спектры.
    #     etalons = []

    #     # ------------------------------------------------------------
    #     # 5. Загружаем эталоны из self.calibration_spectra
    #     # ------------------------------------------------------------
    #     for name in names:
    #         if name in self.calibration_spectra:
    #             etalon = np.array(self.calibration_spectra[name], dtype=float)
    #             etalons.append(etalon)
    #         else:
    #             self.ui.textEdit.append(f"Ошибка: эталон '{name}' не найден")
    #             return None

    #     # ------------------------------------------------------------
    #     # 6. Проверяем, что общий спектр не пустой
    #     # ------------------------------------------------------------
    #     if spectrum.size == 0:
    #         self.ui.textEdit.append("Ошибка: общий спектр пустой")
    #         return None

    #     # ------------------------------------------------------------
    #     # 7. Приводим общий спектр к 1024 каналам
    #     # ------------------------------------------------------------
    #     target_len = 1024

    #     if len(spectrum) < target_len:
    #         self.ui.textEdit.append(
    #             f"Предупреждение: спектр содержит {len(spectrum)} каналов. "
    #             f"Выполнено дополнение до {target_len} каналов."
    #         )
    #         spectrum = np.pad(
    #             spectrum,
    #             (0, target_len - len(spectrum)),
    #             mode='constant',
    #             constant_values=0
    #         )
    #     elif len(spectrum) > target_len:
    #         self.ui.textEdit.append(
    #             f"Предупреждение: спектр содержит {len(spectrum)} каналов. "
    #             f"Выполнено обрезание до {target_len} каналов."
    #         )
    #         spectrum = spectrum[:target_len]

    #     # ------------------------------------------------------------
    #     # 8. Проверяем длину эталонов
    #     # ------------------------------------------------------------
    #     for name, etalon in zip(names, etalons):
    #         if len(etalon) != target_len:
    #             self.ui.textEdit.append(
    #                 f"Ошибка: эталон '{name}' имеет длину {len(etalon)} "
    #                 f"каналов вместо {target_len}"
    #             )
    #             return None

    #     # ------------------------------------------------------------
    #     # 9. Формируем матрицу эталонов
    #     # ------------------------------------------------------------
    #     A = np.column_stack(etalons)

    #     # ------------------------------------------------------------
    #     # 10. Выполняем взвешенный NNLS
    #     # ------------------------------------------------------------
    #     weights = 1.0 / np.sqrt(spectrum + 1.0)
    #     A_weighted = A * weights[:, np.newaxis]
    #     spectrum_weighted = spectrum * weights
    #     coefs, residual = nnls(A_weighted, spectrum_weighted)

    #     # ------------------------------------------------------------
    #     # 11. Формируем компоненты спектра
    #     # ------------------------------------------------------------
    #     components = {}
    #     for i, name in enumerate(names):
    #         components[name] = coefs[i] * etalons[i]

    #     # ------------------------------------------------------------
    #     # 12. Восстанавливаем спектр и считаем остаток
    #     # ------------------------------------------------------------
    #     reconstructed = A @ coefs
    #     residual_spectrum = spectrum - reconstructed

    #     # ------------------------------------------------------------
    #     # 13. ВТОРИЧНОЕ РАЗЛОЖЕНИЕ ОСТАТКА ТОЛЬКО НА ФОН
    #     # ------------------------------------------------------------
    #     # Цель: проверить, есть ли в остатке фон.
    #     # Для этого берём остаток и пытаемся разложить его только на фон.
    #     background_found = False
    #     background_component = np.zeros(target_len)
    #     background_sum = 0.0

    #     # Проверяем, есть ли эталон фона
    #     if "background" in self.calibration_spectra:
    #         bg_etalon = np.array(self.calibration_spectra["background"], dtype=float)

    #         # Приводим фон к той же длине
    #         if len(bg_etalon) != target_len:
    #             if len(bg_etalon) < target_len:
    #                 bg_etalon = np.pad(bg_etalon, (0, target_len - len(bg_etalon)), mode='constant')
    #             else:
    #                 bg_etalon = bg_etalon[:target_len]

    #         # Разлагаем остаток только на фон (одна компонента)
    #         A_bg = bg_etalon.reshape(-1, 1)

    #         # Взвешиваем для остатка
    #         weights_bg = 1.0 / np.sqrt(np.abs(residual_spectrum) + 1.0)
    #         A_bg_weighted = A_bg * weights_bg[:, np.newaxis]
    #         residual_weighted = residual_spectrum * weights_bg

    #         # Решаем однокомпонентную задачу
    #         coef_bg, _ = nnls(A_bg_weighted, residual_weighted)

    #         # Если коэффициент фона > 0, значит фон обнаружен
    #         if coef_bg[0] > 0:
    #             background_found = True
    #             background_component = coef_bg[0] * bg_etalon
    #             background_sum = np.sum(background_component)

    #     # ------------------------------------------------------------
    #     # 14. КОРРЕКТИРОВКА РЕЗУЛЬТАТОВ
    #     # ------------------------------------------------------------
    #     # В зависимости от того, найден ли фон, корректируем компоненты
    #     # и сумму для расчёта долей.

    #     corrected_components = {}
    #     corrected_component_sums = {}

    #     if background_found:
    #         # Фон обнаружен:
    #         # - в качестве фона используем найденный из остатка
    #         # - изотопы остаются как были (из первого разложения)
    #         corrected_components["background"] = background_component
    #         corrected_component_sums["background"] = background_sum

    #         for name in isotopes_list:
    #             corrected_components[name] = components.get(name, np.zeros(target_len))
    #             corrected_component_sums[name] = np.sum(corrected_components[name])

    #         # Сумма для расчёта долей: общий спектр минус найденный фон
    #         total_for_percents = np.sum(spectrum) - background_sum

    #         # Статус фона: обнаружен
    #         background_status = True

    #     else:
    #         # Фон не обнаружен:
    #         # - фон = нулевой спектр
    #         # - изотопы остаются как были
    #         corrected_components["background"] = np.zeros(target_len)
    #         corrected_component_sums["background"] = 0.0

    #         for name in isotopes_list:
    #             corrected_components[name] = components.get(name, np.zeros(target_len))
    #             corrected_component_sums[name] = np.sum(corrected_components[name])

    #         # Сумма для расчёта долей: общий спектр (ничего не вычитаем)
    #         total_for_percents = np.sum(spectrum)

    #         # Статус фона: не обнаружен
    #         background_status = False

    #     # ------------------------------------------------------------
    #     # 15. ПЕРЕРАСЧЁТ ДОЛЕЙ ИЗОТОПОВ
    #     # ------------------------------------------------------------
    #     # Доля изотопа = вклад изотопа / сумма для расчёта долей
    #     isotope_percents = {}

    #     for name in isotopes_list:
    #         if total_for_percents > 0:
    #             isotope_percents[name] = (corrected_component_sums.get(name, 0) / total_for_percents) * 100.0
    #         else:
    #             isotope_percents[name] = 0.0

    #     # ------------------------------------------------------------
    #     # 16. ОПРЕДЕЛЕНИЕ ПРИСУТСТВИЯ ИЗОТОПОВ
    #     # ------------------------------------------------------------
    #     presence_threshold = 0.03
    #     isotope_presence = {}

    #     for name in isotopes_list:
    #         if total_for_percents > 0:
    #             relative_part = corrected_component_sums.get(name, 0) / total_for_percents
    #         else:
    #             relative_part = 0
    #         isotope_presence[name] = relative_part >= presence_threshold

    #     # ------------------------------------------------------------
    #     # 17. РАСЧЁТ ОШИБКИ АППРОКСИМАЦИИ (ОТНОСИТЕЛЬНО ИСХОДНОГО СПЕКТРА)
    #     # ------------------------------------------------------------
    #     # Используем исходный спектр и восстановленный (без корректировки фона)
    #     difference = spectrum - reconstructed
    #     error_sum = np.sum(difference ** 2)
    #     spectrum_power = np.sum(spectrum ** 2)

    #     if spectrum_power > 0:
    #         relative_error = error_sum / spectrum_power
    #     else:
    #         relative_error = None

    #     # ------------------------------------------------------------
    #     # 18. ФОРМИРУЕМ СЛОВАРЬ КОЭФФИЦИЕНТОВ (СКОРРЕКТИРОВАННЫЙ)
    #     # ------------------------------------------------------------
    #     coefficients = {}

    #     # Для фона используем скорректированный коэффициент
    #     if background_found:
    #         coefficients["background"] = 1.0  # условно, т.к. фон теперь отдельно
    #     else:
    #         coefficients["background"] = 0.0

    #     # Для изотопов оставляем исходные коэффициенты
    #     for i, name in enumerate(names):
    #         if name != "background":
    #             coefficients[name] = coefs[i]

    #     # ------------------------------------------------------------
    #     # 19. ФОРМИРУЕМ ДОПОЛНИТЕЛЬНУЮ ИНФОРМАЦИЮ ДЛЯ ВЫВОДА
    #     # ------------------------------------------------------------
    #     # Добавляем в результат:
    #     # - доли изотопов в процентах
    #     # - статус фона (обнаружен/не обнаружен)
    #     # - сумма для расчёта долей (общий спектр минус фон)
    #     # - скорректированные компоненты

    #     result = {
    #         "coefficients": coefficients,
    #         "components": corrected_components,
    #         "component_sums": corrected_component_sums,
    #         "isotope_presence": isotope_presence,
    #         "isotope_percents": isotope_percents,
    #         "background_found": background_found,
    #         "total_for_percents": total_for_percents,
    #         "reconstructed": reconstructed,
    #         "error_sum": error_sum,
    #         "relative_error": relative_error,
    #         "residual": residual
    #     }

    #     return result

    def identify_isotopes(self, spectrum, cistern_position):
        """
        Метод раскладывает общий измеренный спектр на компоненты:

            общий спектр ≈ фон + I-131 + Tc-99m

        В этой версии используется взвешенный NNLS.

        Важно:
        - эталонные спектры НЕ нормируются;
        - матрица A строится из реальных эталонов;
        - веса используются только для решения задачи NNLS;
        - восстановление компонентов выполняется через реальные эталоны.
        """

        # ------------------------------------------------------------
        # 1. Преобразуем входной спектр в numpy-массив
        # ------------------------------------------------------------
        spectrum = np.array(spectrum, dtype=float)

        # ------------------------------------------------------------
        # 2. Извлекаем время набора реального спектра (последний элемент)
        # ------------------------------------------------------------
        # В спектре 1024 элемента: первые 1023 — спектр, последний — время набора в секундах.
        real_time = spectrum[-1] if len(spectrum) > 0 else 1.0
        if real_time <= 0:
            real_time = 1.0
        spectrum_data = spectrum[:1023]  # отделяем спектр от времени
        spectrum_norm = spectrum_data / real_time  # нормируем на время

        # ------------------------------------------------------------
        # 3. Проверяем, загружены ли эталонные спектры
        # ------------------------------------------------------------
        if not hasattr(self, 'calibration_spectra') or not self.calibration_spectra:
            self.ui.textEdit.append("Ошибка: эталонные спектры не загружены")
            return None

        # ------------------------------------------------------------
        # 4. Получаем список изотопов для данной цистерны
        # ------------------------------------------------------------
        isotopes_list = self.cistern_isotopes.get(cistern_position, [])

        if not isotopes_list:
            self.ui.textEdit.append(
                f"Предупреждение: для цистерны {cistern_position} не заданы изотопы"
            )

        # ------------------------------------------------------------
        # 5. Формируем список компонентов
        # ------------------------------------------------------------
        # Фон всегда участвует в разложении.
        names = ["background"] + isotopes_list

        # Здесь храним реальные, НЕ нормированные эталонные спектры.
        etalons = []

        # Здесь храним нормированные на время эталонные спектры.
        etalons_norm = []

        # ------------------------------------------------------------
        # 6. Загружаем эталоны из self.calibration_spectra
        # ------------------------------------------------------------
        for name in names:

            if name in self.calibration_spectra:

                # ВАЖНО:
                # Эталон берём как есть.
                # Никакой нормировки на сумму каналов здесь НЕ делаем.
                etalon = np.array(self.calibration_spectra[name], dtype=float)

                # Извлекаем время набора эталона (последний элемент)
                etalon_time = etalon[-1] if len(etalon) > 0 else 1.0
                if etalon_time <= 0:
                    etalon_time = 1.0
                etalon_data = etalon[:1023]  # отделяем спектр от времени
                etalon_norm = etalon_data / etalon_time  # нормируем на время

                etalons.append(etalon_data)
                etalons_norm.append(etalon_norm)

            else:
                self.ui.textEdit.append(f"Ошибка: эталон '{name}' не найден")
                return None

        # ------------------------------------------------------------
        # 7. Проверяем, что общий спектр не пустой
        # ------------------------------------------------------------
        if spectrum_norm.size == 0:
            self.ui.textEdit.append("Ошибка: общий спектр пустой")
            return None

        # ------------------------------------------------------------
        # 8. Приводим общий спектр к 1023 каналам (без времени)
        # ------------------------------------------------------------
        # Все эталонные спектры имеют длину 1023 (без учёта времени).
        # Поэтому входной спектр должен быть приведён к тому же размеру.
        target_len = 1023

        if len(spectrum_norm) < target_len:

            self.ui.textEdit.append(
                f"Предупреждение: спектр содержит {len(spectrum_norm)} каналов. "
                f"Выполнено дополнение до {target_len} каналов."
            )

            spectrum_norm = np.pad(
                spectrum_norm,
                (0, target_len - len(spectrum_norm)),
                mode='constant',
                constant_values=0
            )

        elif len(spectrum_norm) > target_len:

            self.ui.textEdit.append(
                f"Предупреждение: спектр содержит {len(spectrum_norm)} каналов. "
                f"Выполнено обрезание до {target_len} каналов."
            )

            spectrum_norm = spectrum_norm[:target_len]

        # ------------------------------------------------------------
        # 9. Проверяем длину эталонов
        # ------------------------------------------------------------
        for name, etalon in zip(names, etalons):

            if len(etalon) != target_len:

                self.ui.textEdit.append(
                    f"Ошибка: эталон '{name}' имеет длину {len(etalon)} "
                    f"каналов вместо {target_len}"
                )

                return None

        # ------------------------------------------------------------
        # 10. Формируем матрицу эталонов из НОРМИРОВАННЫХ спектров
        # ------------------------------------------------------------
        # ВАЖНО:
        # Матрица A строится из нормированных эталонов.
        A = np.column_stack(etalons_norm)

        # ------------------------------------------------------------
        # 11. Выполняем взвешенный NNLS на НОРМИРОВАННЫХ данных
        # ------------------------------------------------------------
        # Веса:
        #   weight = 1 / sqrt(spectrum_norm + 1)
        weights = 1.0 / np.sqrt(spectrum_norm + 1.0)

        A_weighted = A * weights[:, np.newaxis]
        spectrum_weighted = spectrum_norm * weights

        coefs, residual = nnls(A_weighted, spectrum_weighted)

        # ------------------------------------------------------------
        # 12. Восстанавливаем спектр в НОРМИРОВАННЫХ значениях
        # ------------------------------------------------------------
        reconstructed_norm = A @ coefs

        # ------------------------------------------------------------
        # 13. Считаем ошибку аппроксимации в нормированных значениях
        # ------------------------------------------------------------
        difference = spectrum_norm - reconstructed_norm

        error_sum = np.sum(difference ** 2)

        spectrum_power = np.sum(spectrum_norm ** 2)

        if spectrum_power > 0:
            relative_error = error_sum / spectrum_power
        else:
            relative_error = None

        # ------------------------------------------------------------
        # 14. Формируем отдельные компоненты спектра
        # ------------------------------------------------------------
        # ВАЖНО:
        # Здесь используем нормированные эталоны.
        #
        # component = coefficient * etalon_norm
        components_norm = {}

        for i, name in enumerate(names):
            components_norm[name] = coefs[i] * etalons_norm[i]

        # ------------------------------------------------------------
        # 15. Считаем интегральный вклад каждой компоненты
        # ------------------------------------------------------------
        component_sums = {}

        for name in names:
            component_sums[name] = np.sum(components_norm[name])

        total_component_sum = sum(component_sums.values())

        # ------------------------------------------------------------
        # 16. Определяем присутствие изотопов
        # ------------------------------------------------------------
        presence_threshold = 0.03

        isotope_presence = {}

        for name in isotopes_list:

            if total_component_sum > 0:
                relative_component_part = component_sums[name] / total_component_sum
            else:
                relative_component_part = 0

            isotope_presence[name] = relative_component_part >= presence_threshold

        # ------------------------------------------------------------
        # 17. Формируем словарь коэффициентов
        # ------------------------------------------------------------
        coefficients = {}

        for i, name in enumerate(names):
            coefficients[name] = coefs[i]

        # ------------------------------------------------------------
        # 18. ВТОРИЧНОЕ РАЗЛОЖЕНИЕ ОСТАТКА ТОЛЬКО НА ФОН
        # ------------------------------------------------------------
        # Цель: проверить, есть ли в остатке фон.
        # Для этого берём остаток и пытаемся разложить его только на фон.
        background_found = False
        background_component = np.zeros(target_len)
        background_sum = 0.0

        # Проверяем, есть ли эталон фона
        if "background" in self.calibration_spectra:
            # Берем нормированный эталон фона (он уже есть в etalons_norm)
            bg_etalon_norm = None
            for i, name in enumerate(names):
                if name == "background":
                    bg_etalon_norm = etalons_norm[i]
                    break

            if bg_etalon_norm is not None:
                # Разлагаем остаток только на фон (одна компонента)
                A_bg = bg_etalon_norm.reshape(-1, 1)

                # Взвешиваем для остатка
                residual_spectrum = spectrum_norm - reconstructed_norm
                weights_bg = 1.0 / np.sqrt(np.abs(residual_spectrum) + 1.0)
                A_bg_weighted = A_bg * weights_bg[:, np.newaxis]
                residual_weighted = residual_spectrum * weights_bg

                # Решаем однокомпонентную задачу
                coef_bg, _ = nnls(A_bg_weighted, residual_weighted)

                # Если коэффициент фона > 0, значит фон обнаружен
                if coef_bg[0] > 0:
                    background_found = True
                    background_component = coef_bg[0] * bg_etalon_norm
                    background_sum = np.sum(background_component)

        # ------------------------------------------------------------
        # 19. КОРРЕКТИРОВКА РЕЗУЛЬТАТОВ
        # ------------------------------------------------------------
        # В зависимости от того, найден ли фон, корректируем компоненты
        # и сумму для расчёта долей.

        corrected_components = {}
        corrected_component_sums = {}

        if background_found:
            # Фон обнаружен:
            # - в качестве фона используем найденный из остатка
            # - изотопы остаются как были (из первого разложения)
            corrected_components["background"] = background_component
            corrected_component_sums["background"] = background_sum

            for name in isotopes_list:
                corrected_components[name] = components_norm.get(name, np.zeros(target_len))
                corrected_component_sums[name] = np.sum(corrected_components[name])

            # Сумма для расчёта долей: общий спектр минус найденный фон
            total_for_percents = np.sum(spectrum_norm) - background_sum

            # Статус фона: обнаружен
            background_status = True

        else:
            # Фон не обнаружен:
            # - фон = нулевой спектр
            # - изотопы остаются как были
            corrected_components["background"] = np.zeros(target_len)
            corrected_component_sums["background"] = 0.0

            for name in isotopes_list:
                corrected_components[name] = components_norm.get(name, np.zeros(target_len))
                corrected_component_sums[name] = np.sum(corrected_components[name])

            # Сумма для расчёта долей: общий спектр (ничего не вычитаем)
            total_for_percents = np.sum(spectrum_norm)

            # Статус фона: не обнаружен
            background_status = False

        # ------------------------------------------------------------
        # 20. ПЕРЕРАСЧЁТ ДОЛЕЙ ИЗОТОПОВ
        # ------------------------------------------------------------
        # Доля изотопа = вклад изотопа / сумма для расчёта долей
        isotope_percents = {}

        for name in isotopes_list:
            if total_for_percents > 0:
                isotope_percents[name] = (corrected_component_sums.get(name, 0) / total_for_percents) * 100.0
            else:
                isotope_percents[name] = 0.0

        # ------------------------------------------------------------
        # 21. ОПРЕДЕЛЕНИЕ ПРИСУТСТВИЯ ИЗОТОПОВ (ПОВТОРНО С УЧЁТОМ КОРРЕКТИРОВКИ)
        # ------------------------------------------------------------
        presence_threshold = 0.03
        isotope_presence = {}

        for name in isotopes_list:
            if total_for_percents > 0:
                relative_part = corrected_component_sums.get(name, 0) / total_for_percents
            else:
                relative_part = 0
            isotope_presence[name] = relative_part >= presence_threshold

        # ------------------------------------------------------------
        # 22. ФОРМИРУЕМ СЛОВАРЬ КОЭФФИЦИЕНТОВ (СКОРРЕКТИРОВАННЫЙ)
        # ------------------------------------------------------------
        coefficients = {}

        # Для фона используем скорректированный коэффициент
        if background_found:
            coefficients["background"] = 1.0  # условно, т.к. фон теперь отдельно
        else:
            coefficients["background"] = 0.0

        # Для изотопов оставляем исходные коэффициенты
        for i, name in enumerate(names):
            if name != "background":
                coefficients[name] = coefs[i]

        # ------------------------------------------------------------
        # 23. ФОРМИРУЕМ ДОПОЛНИТЕЛЬНУЮ ИНФОРМАЦИЮ ДЛЯ ВЫВОДА
        # ------------------------------------------------------------
        # Добавляем в результат:
        # - доли изотопов в процентах
        # - статус фона (обнаружен/не обнаружен)
        # - сумма для расчёта долей (общий спектр минус фон)
        # - скорректированные компоненты
        # - нормированный общий спектр
        # - время набора реального спектра

        result = {
            "coefficients": coefficients,
            "components": corrected_components,
            "component_sums": corrected_component_sums,
            "isotope_presence": isotope_presence,
            "isotope_percents": isotope_percents,
            "background_found": background_found,
            "total_for_percents": total_for_percents,
            "reconstructed": reconstructed_norm,
            "error_sum": error_sum,
            "relative_error": relative_error,
            "residual": residual,
            "spectrum_norm": spectrum_norm,
            "real_time": real_time
        }

        return result

    
# def main():
#     """
#         Точка входа в приложение
#     """
#     app = QApplication(sys.argv) # создаём объект приложения
#     window = App()                # создаём наш класс App (он загрузит интерфейс и настроит связи)
#     app.aboutToQuit.connect(window.cleanup)
#     sys.exit(app.exec())          # запускаем цикл обработки событий и корректно завершаем работу

def main():
    """
    Точка входу в програму.
    Спочатку перевіряємо пароль, потім запускаємо основне вікно.
    """
    # Створюємо об'єкт програми Qt
    app = QApplication(sys.argv)

    # ------------------------------------------------------------
    # 1. Показуємо діалог вводу пароля
    # ------------------------------------------------------------
    password_dialog = PasswordDialog()
    result = password_dialog.exec()  # exec() повертає QDialog.Accepted або QDialog.Rejected

    # Якщо користувач натиснув Cancel або ввів неправильний пароль — виходимо
    if result != QDialog.Accepted:
        sys.exit(0)  # завершуємо програму без помилок

    # ------------------------------------------------------------
    # 2. Пароль правильний — створюємо головне вікно
    # ------------------------------------------------------------
    window = App()
    app.aboutToQuit.connect(window.cleanup)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
