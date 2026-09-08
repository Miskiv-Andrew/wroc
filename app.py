# app.py

import sys
from PySide6.QtWidgets import QApplication, QWidget, QGridLayout, QVBoxLayout, QPushButton, QLabel, QSizePolicy, QSpacerItem, QDialog, QLineEdit, QMessageBox, QHBoxLayout, QSpinBox, QMenu
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QThread, QMetaObject, QTimer , Qt, QObject, Signal, QDateTime
from devices.device_manager import DeviceManager
from PySide6.QtGui import QAction, QPixmap
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import json, numpy as np
import os, math

# from sklearn.decomposition import NMF
# from scipy.optimize import nnls

from database.db_manager import DatabaseManager
from dialogs.device_replace_dialog import DeviceReplaceDialog
import json


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

        self.total_acquisition_time = 0.0 

        self.algorithm_history = {}  # для зберігання динаміки Tc (група A та reserve)

    def clear_history(self):
        """
        Очищує історію динаміки розпаду для групи A та резервної цистерни.
        Викликається при заповненні або спорожненні цистерни.
        """
        # Якщо у картки є атрибут для зберігання історії
        if hasattr(self, 'algorithm_history'):
            self.algorithm_history = {}
        # Якщо історія зберігається в окремому словнику (наприклад, як атрибут self.history)
        # можна додати додаткові очищення за потреби.
        # Наприклад, якщо використовується self.history для групи A або reserve:
        if hasattr(self, 'history'):
            self.history = None

    
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

   
    def add_spectrum_data(self, channels):
        """
        Додає отриманий масив спектра до накопиченого буфера.
        channels: list[int] - 1024 елементи (1023 спектра + час набора)
        """
        if len(channels) != 1024:
            return
        
        # Отрумуємо і сумуємо час набора спектра (останній елемент)
        self.last_acquisition_time = channels[-1]
        self.total_acquisition_time += self.last_acquisition_time
        
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
        self.total_acquisition_time = 0.0
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
        Використовує новий алгоритм ALIM (identify_isotopes_alim).
        """
        if not hasattr(self, 'parent_app') or not self.parent_app:
            return

        # ------------------------------------------------------------
        # 1. Формуємо масив з часом набора
        # ------------------------------------------------------------
        spectrum_with_time = list(self.spectrum_buffer) + [self.total_acquisition_time]
        
        # ------------------------------------------------------------
        # 2. Викликаємо алгоритм з історією
        # ------------------------------------------------------------
        result, updated_history = self.parent_app.identify_isotopes_alim(
            spectrum_with_time,
            self.posit_number,
            self.algorithm_history
        )
        
        # Оновлюємо історію в картці
        self.algorithm_history = updated_history
        
        # ------------------------------------------------------------
        # 3. Якщо результат порожній — виходимо
        # ------------------------------------------------------------
        if not result:
            self.reset_spectrum()
            return
        
        # ------------------------------------------------------------
        # 4. Розпаковуємо результат
        # ------------------------------------------------------------
        group = result.get("group", "A")
        real_time = result.get("real_time", 1.0)
        isotopes_list = result.get("isotopes", [])
        
        # ------------------------------------------------------------
        # 5. Формуємо словники активностей та концентрацій для БД
        # ------------------------------------------------------------
        activity_dict = {}
        concentration_dict = {}
        output_lines = [f"Цистерна №{self.posit_number} (група {group}):", f"Час набора: {real_time:.1f} сек"]
        
        for name in isotopes_list:
            data = result.get(name, {})
            if not data:
                continue
            
            # Отримуємо дані
            activity = data.get("activity", 0.0)
            concentration = data.get("concentration", 0.0)
            detected = data.get("detected", "НЕМАЄ")
            sum_clean = data.get("sum_clean", 0.0)
            
            # Заповнюємо словники для БД
            if activity > 0 or concentration > 0:
                activity_dict[name] = activity
                concentration_dict[name] = concentration
            
            # Формуємо рядок для виводу
            if sum_clean > 0:
                output_lines.append(
                    f"  {name}: активність = {activity:.2f} Бк, "
                    f"концентрація = {concentration:.2f} Бк/л, статус: {detected}"
                )
            else:
                output_lines.append(f"  {name}: не виявлено (сума = 0)")
        
        # Додаємо інформацію про фон, якщо є
        if "background" in result:
            bg_data = result.get("background", {})
            if bg_data.get("subtracted", False):
                output_lines.append(f"  Фон: віднято")
        
        # Виводимо в textEdit
        self.parent_app.ui.textEdit.append("\n".join(output_lines))
        self.parent_app.ui.textEdit.append("---")
        
        # ------------------------------------------------------------
        # 6. Експорт спектрів (залишаємо як було)
        # ------------------------------------------------------------
        export_dir = "export"
        os.makedirs(export_dir, exist_ok=True)
        
        export_total_spectrum = np.array(self.spectrum_buffer, dtype=float)
        if len(export_total_spectrum) < 1024:
            export_total_spectrum = np.pad(export_total_spectrum, (0, 1024 - len(export_total_spectrum)), mode='constant')
        elif len(export_total_spectrum) > 1024:
            export_total_spectrum = export_total_spectrum[:1024]
        
        with open(os.path.join(export_dir, "spectrum_total.txt"), "w") as f:
            f.write("\n".join(str(int(x)) for x in export_total_spectrum))
        
        # Зберігаємо компоненти, якщо є
        components = result.get("components", {})
        for name, spectrum in components.items():
            spectrum_with_time_export = list(spectrum) + [real_time]
            filename = f"spectrum_{name}.txt"
            with open(os.path.join(export_dir, filename), "w") as f:
                f.write("\n".join(str(int(x)) for x in spectrum_with_time_export))
        
        # ------------------------------------------------------------
        # 7. Збереження в БД (тільки якщо є дані)
        # ------------------------------------------------------------
        if activity_dict or concentration_dict:
            # Перетворюємо на JSON-рядки
            activity_json = json.dumps(activity_dict) if activity_dict else "{}"
            concentration_json = json.dumps(concentration_dict) if concentration_dict else "{}"
            
            device_id = self.parent_app.db_manager.get_device_id(self.serial_number)
            if device_id is not None:
                fullness_status = "full" if getattr(self, 'is_full', False) else "empty"
                
                self.parent_app.db_manager.save_cistern_measurement(
                    device_id=device_id,
                    paed=self.last_paed_from_spectrum,
                    temperature=self.last_temperature,
                    activity_json=activity_json,
                    concentration_json=concentration_json,
                    low_status=self.last_low_status,
                    high_status=self.last_high_status,
                    valid=self.last_valid,
                    fullness_status=fullness_status,
                    group=group
                )
                
                self.parent_app.ui.textEdit.append(
                    f"Цистерна №{self.posit_number}: збережено в БД (активності: {activity_json}, концентрації: {concentration_json})"
                )
        
        # ------------------------------------------------------------
        # 8. Скидання буферів
        # ------------------------------------------------------------
        self.parent_app.db_manager.flush_cistern_buffer()
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

        # # связывание кнопок и сигналов
        # self.setup_connections()   

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

        # Атрибут для хранения таймера опроса внешней системы
        self.poll_timer = None


        self.spectrum_accumulation_time = 3600
        self.db_write_interval = 5
        self.zb_send_interval = 60
        self.cz_send_interval = 60

        # ============================================================
        # БЛОК КОНСТАНТ АЛГОРИТМІВ ІДЕНТИФІКАЦІЇ (ALIM)
        # ============================================================

        # --- Група A (цистерни 1, 2) ---
        self.GROUP_A_ISOTOPES = ["18F", "99mTc"]
        self.GROUP_A_WINDOWS = {
            "18F": (161, 204),
            "99mTc": (12, 64)
        }
        self.GROUP_A_COEFFICIENTS = {
            "18F": 47.0,
            "99mTc": 9.346
        }
        self.GROUP_A_HALF_LIFE = {
            "18F": 110.0,
            "99mTc": 360.1
        }
        self.GROUP_A_SIGMA = {
            "18F": 2,
            "99mTc": 2
        }
        self.GROUP_A_TC_THRESHOLD = 0.95

        # --- Група B (цистерни 4-9) ---
        self.GROUP_B_ISOTOPES = ["133I", "177Lu", "90Y"]
        self.GROUP_B_WINDOWS = {
            "133I": (90, 150),
            "177Lu": (63, 89),
            "90Y": (371, 820)
        }
        self.GROUP_B_COEFFICIENTS = {
            "133I": 40.99,
            "177Lu": 315.0,
            "90Y": 1.0
        }
        self.GROUP_B_SIGMA = {
            "133I": 2,
            "177Lu": 2,
            "90Y": 2
        }
        self.GROUP_B_ORDER = ["90Y", "133I", "177Lu"]

        # --- Група RESERVE (цистерна 3) ---
        self.GROUP_RESERVE_ISOTOPES = ["18F", "99mTc", "133I", "177Lu", "90Y"]
        self.GROUP_RESERVE_WINDOWS = {
            "18F": (161, 204),
            "99mTc": (12, 64),
            "133I": (90, 150),
            "177Lu": (63, 89),
            "90Y": (371, 820)
        }
        self.GROUP_RESERVE_COEFFICIENTS = {
            "18F": 47.0,
            "99mTc": 9.346,
            "133I": 40.99,
            "177Lu": 315.0,
            "90Y": 1.0
        }
        self.GROUP_RESERVE_SIGMA = {
            "18F": 2,
            "99mTc": 1,
            "133I": 2,
            "177Lu": 2,
            "90Y": 2
        }
        self.GROUP_RESERVE_ORDER = ["90Y", "133I", "177Lu", "18F", "99mTc"]
        self.GROUP_RESERVE_BASE_I_WINDOW = (115, 150)
        self.GROUP_RESERVE_TC_DELAY_HOURS = 6
        self.GROUP_RESERVE_TC_EXTRAPOLATION_COEFF = 0.890899

        # --- Загальні константи ---
        self.PAED_THRESHOLD = 50.0
        self.DEAD_TIME_COEFF = 0.00002
        self.SPECTRUM_CHANNELS = 1023


        # связывание кнопок и сигналов
        self.setup_connections()   


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

        self.plc_ip_edit = self.ui.findChild(QLineEdit, "lineEdit")          # поле IP
        self.plc_port_spin = self.ui.findChild(QSpinBox, "spinBox")          # поле порта
        self.btn_connect_plc = self.ui.findChild(QPushButton, "btn_connect_plc")  # кнопка
        self.indicator_plc = self.ui.findChild(QLabel, "indicator_plc")      # индикатор PLC
        self.indicator_bridge = self.ui.findChild(QLabel, "indicator_bridge") # индикатор Bridge

        self.barrel_grid = self.barrel_container.layout()
        if self.barrel_grid is None:
            self.barrel_grid = QGridLayout(self.barrel_container)
            self.barrel_grid.setSpacing(5)
            self.barrel_container.setLayout(self.barrel_grid)

        self.wall_layout = self.wall_container.layout()
        if self.wall_layout is None:
            self.wall_layout = QVBoxLayout(self.wall_container)
            self.wall_container.setLayout(self.wall_layout)

        # ============================================================
        # Додаємо пункт меню "Налаштування інтервалів"
        # ============================================================
        # Знаходимо меню "Прилади"
        menu_devices = self.ui.findChild(QMenu, "menu")
        if menu_devices:
            # Створюємо дію
            self.action_intervals = QAction("Налаштування інтервалів", self.ui)
            self.action_intervals.setObjectName("action_intervals")
            
            # Додаємо дію в меню перед "Заміна приладу" або в кінець
            # Шукаємо дію "butt_replace_device" щоб вставити перед нею
            replace_action = self.ui.findChild(QAction, "butt_replace_device")
            if replace_action:
                # Вставляємо перед "Заміна приладу"
                menu_devices.insertAction(replace_action, self.action_intervals)
                # Додаємо роздільник перед "Заміна приладу" (опціонально)
                # menu_devices.insertSeparator(replace_action)
            else:
                # Якщо "Заміна приладу" не знайдено, додаємо в кінець
                menu_devices.addAction(self.action_intervals)
            
            # Підключаємо сигнал
            self.action_intervals.triggered.connect(self.on_open_intervals)
        else:
            # Якщо меню не знайдено — створюємо його (запасний варіант)
            self.ui.textEdit.append("Увага: меню 'Прилади' не знайдено")


    def on_open_intervals(self):
        """
        Відкриває діалог налаштування інтервалів.
        """
        from dialogs.intervals_dialog import IntervalsDialog
        dialog = IntervalsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            # Отримуємо значення з діалогу
            self.spectrum_accumulation_time = dialog.get_spectrum_time()
            self.db_write_interval = dialog.get_db_interval()
            self.zb_send_interval = dialog.get_zb_interval()
            self.cz_send_interval = dialog.get_cz_interval()
            
            self.ui.textEdit.append(
                f"Налаштування інтервалів збережено: "
                f"спектр={self.spectrum_accumulation_time}с, "
                f"ZB={self.zb_send_interval}с, "
                f"CZ={self.cz_send_interval}с, "
                f"БД={self.db_write_interval}хв"
            )

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

        # Кнопка подключения к PLC
        self.btn_connect_plc.clicked.connect(self.on_connect_plc_clicked)



    def on_connect_plc_clicked(self):
        ip = self.plc_ip_edit.text().strip()
        port = self.plc_port_spin.value()
        self.ui.textEdit.append(f"Подключение к ПЛК {ip}:{port} (заглушка)")
        # Позже здесь будет запуск C++ процесса и подключение к Bridge

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
        # Останавливаем таймер опроса внешней системы
        if hasattr(self, 'poll_timer') and self.poll_timer is not None:
            self.poll_timer.stop()
            self.poll_timer = None
        
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
                            group = self.cistern_groups.get(card.posit_number, "A")
                            # Додаємо в буфер цистерни з порожніми JSON (активність і концентрація будуть пізніше)
                            self.db_manager.buffer_cistern_measurement(
                                device_id=device_id,
                                paed=dose,
                                temperature=temp_value,
                                low_status=1 if low_failure else 0,
                                high_status=1 if high_failure else 0,
                                valid=1 if result_valid else 0,
                                fullness_status=fullness_status,
                                group=group,
                                activity_json="{}",
                                concentration_json="{}"
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
                    
                    # Збереження ПАЕД в буфер цистерни (з порожніми JSON)
                    device_id = self.db_manager.get_device_id(sn)
                    if device_id is not None and card.location_type == "cistern":
                        temp_value = getattr(card, 'last_temperature', 0.0)
                        fullness_status = "full" if getattr(card, 'is_full', False) else "empty"
                        group = self.cistern_groups.get(card.posit_number, "A")
                        self.db_manager.buffer_cistern_measurement(
                            device_id=device_id,
                            paed=paed_value,
                            temperature=temp_value,
                            low_status=1 if low_failure else 0,
                            high_status=1 if high_failure else 0,
                            valid=1 if result_valid else 0,
                            fullness_status=fullness_status,
                            group=group,
                            activity_json="{}",
                            concentration_json="{}"
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
        Загружает данные о заполненности цистерн, списках изотопов и группах из файла.
        Если файл отсутствует или повреждён, создаёт дефолтные данные для 20 цистерн
        с предустановленными группами:
            - цистерны 1, 2 → группа "A"
            - цистерна 3 → группа "reserve"
            - цистерны 4–9 → группа "B"
            - цистерны 10–20 → группа "A" (по умолчанию)
        """
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.cistern_dict = {}       # {номер: full}
            self.cistern_isotopes = {}   # {номер: [изотопы]}
            self.cistern_groups = {}     # {номер: группа}
            
            for k, v in data.items():
                pos = int(k)
                self.cistern_dict[pos] = bool(v.get("full", False))
                self.cistern_isotopes[pos] = v.get("isotopes", [])
                self.cistern_groups[pos] = v.get("group", "A")  # если поля нет — группа A
                    
        except (FileNotFoundError, json.JSONDecodeError):
            # Файл отсутствует или битый — создаём дефолт
            print(f"Файл {json_file} відсутній або пошкоджений. Створюємо дефолтні дані (20 порожніх цистерн)")
            
            self.cistern_dict = {i: False for i in range(1, 21)}
            self.cistern_isotopes = {i: [] for i in range(1, 21)}
            self.cistern_groups = {}
            
            # Задаём группы для цистерн 1–9, остальные по умолчанию A
            for i in range(1, 10):
                if i == 1 or i == 2:
                    self.cistern_groups[i] = "A"
                elif i == 3:
                    self.cistern_groups[i] = "reserve"
                elif 4 <= i <= 9:
                    self.cistern_groups[i] = "B"
                else:
                    self.cistern_groups[i] = "A"
            for i in range(10, 21):
                self.cistern_groups[i] = "A"
            
            # Записываем новый файл с полной структурой
            with open(json_file, "w", encoding="utf-8") as f:
                export_data = {}
                for i in range(1, 21):
                    export_data[str(i)] = {
                        "full": False,
                        "isotopes": [],
                        "group": self.cistern_groups.get(i, "A")
                    }
                json.dump(export_data, f, ensure_ascii=False, indent=4)

    
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
                
                # Если цистерна стала пустой - сбрасываем спектральные данные и историю
                if old_full != new_full and not new_full:
                    # Цистерна опустошена - сброс спектра и истории
                    if hasattr(card, 'reset_spectrum'):
                        card.reset_spectrum()
                    if hasattr(card, 'clear_history'):
                        card.clear_history()
                    # Выводим информацию в лог
                    self.ui.textEdit.append(f"Цистерна №{posit} спорожнена. Спектр та історію скинуто.")
                
                # Если цистерна стала полной - сбрасываем спектральные данные и историю (начало нового цикла)
                if old_full != new_full and new_full:
                    if hasattr(card, 'reset_spectrum'):
                        card.reset_spectrum()
                    if hasattr(card, 'clear_history'):
                        card.clear_history()
                    self.ui.textEdit.append(f"Цистерна №{posit} заповнена. Спектр та історію скинуто.")
                        
            except Exception as e:
                continue

    def start_test_polling(self, json_file: str):
        """
            Запускает имитационный опрос Системы Управления (состояние заполненности цистерн).
            Каждые 30 секунд получает словарь с новыми данными и сравнивает его
            с self.cistern_dict. При изменении обновляет словарь, приборы и файл.
        """
        # Если таймер уже существует — останавливаем его
        if self.poll_timer is not None and self.poll_timer.isActive():
            self.poll_timer.stop()
        
        self.poll_timer = QTimer()
        self.poll_timer.setInterval(30_000)  # 30 секунд
        self.poll_timer.timeout.connect(lambda: self.poll_system(json_file))
        self.poll_timer.start()



    def poll_system(self, json_file: str, new_data: dict = None):
        """
        Опрос Системы Управления.
        Сравниваем новые данные new_data со словарём self.cistern_dict.
        При изменении обновляем словарь, приборы и файл.
        Если в новых данных есть номер цистерны, которого нет в словаре —
        фиксируем ошибку и предупреждаем администратора.
        """
        # Если new_data не передан — используем данные из lineEdit (имитация)
        # if new_data is None:
        #     text = self.ui.lineEdit.text().strip()
        #     if text == "Full":
        #         new_data = {1: True}                
        #     elif text == "Empty":
        #         new_data = {1: False}                
        #     else:                
        #         return

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

        # Если были изменения — перезаписываем файл cistern.json и синхронизируем с DeviceManager
        if updated:
            with open(json_file, "w", encoding="utf-8") as f:
                export_data = {}
                for pos, full in self.cistern_dict.items():
                    export_data[str(pos)] = {
                        "full": full,
                        "isotopes": self.cistern_isotopes.get(pos, []),
                        "group": self.cistern_groups.get(pos, "A")
                    }
                json.dump(export_data, f, ensure_ascii=False, indent=4)
                try:
                    self.sync_cisterns_to_manager.emit(self.cistern_dict)
                except Exception:
                    pass

    
    def cleanup(self):
        # Останавливаем таймер опроса внешней системы
        if hasattr(self, 'poll_timer') and self.poll_timer is not None:
            self.poll_timer.stop()
            self.poll_timer = None
        
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
        Запуск опроса приборов.
        Блокирует кнопки, чтобы предотвратить повторный запуск.
        """
        if self.butt_replace_device:
            self.butt_replace_device.setEnabled(False)
        
        if hasattr(self, 'butt_search_dev'):
            self.butt_search_dev.setEnabled(False)
        
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



    def _normalize_spectrum(self, spectrum, T):
        """
            Корекція вхідного спектру на мертвий час та нормування по часу.
            
            Вхід:
                spectrum - list[float] або list[int] масив 1023 каналів (k_i)
                T - час вимірювання в секундах (напр. 3600)
            
            Вихід:
                arr1 - list[float] нормований спектр (n_i = k_i / T1)
            
            Алгоритм:
                1. sum_k = sum(spectrum) - сума імпульсів по всіх каналах
                2. T1 = T - 0.00002 * sum_k - скоригований час
                3. n_i = k_i / T1 - інтенсивність в кожному каналі
        """
        sum_k = sum(spectrum)
        T1 = T - self.DEAD_TIME_COEFF * sum_k
        if T1 <= 0:
            T1 = T  # захист від негативного часу
        arr1 = [k / T1 for k in spectrum]
        return arr1 

    def _subtract_background(self, arr1):
        """
        Віднімання базового фону з нормованого спектру.
        
        Вхід:
            arr1 - list[float] нормований спектр (після _normalize_spectrum)
        
        Вихід:
            arr2 - list[float] спектр з віднятим фоном
        
        Алгоритм:
            Для кожного каналу i: arr2[i] = arr1[i] - background[i]
        
        Примітка:
            Файл фону завантажується з self.calibration_spectra["background"]
            Якщо фон не завантажено - повертаємо arr1 без змін
        """
        bg = self.calibration_spectra.get("background")
        if bg is None or len(bg) < 1023:
            # Якщо фону немає - повертаємо без змін
            return arr1.copy()
        
        # Обрізаємо до 1023 каналів (якщо більше)
        bg = bg[:1023]
        
        # Віднімаємо
        arr2 = [arr1[i] - bg[i] for i in range(1023)]
        return arr2


    def _calculate_window_sum(self, spectrum, start, end):
        """
            Обчислення суми значень каналів у заданому вікні.
            
            Вхід:
                spectrum - list[float] спектр
                start - початковий канал (включно)
                end - кінцевий канал (включно)
            
            Вихід:
                float - сума значень у вікні
            
            Примітка:
                Канали в спектрі індексуються з 0, але в описі алгоритму - з 1.
                Тому start і end передаються як в описі (з 1),
                а в коді використовується зсув на -1.
        """
        # Перевірка меж
        if start < 1:
            start = 1
        if end > 1023:
            end = 1023
        
        # Зсув індексу (канал 1 -> індекс 0)
        idx_start = start - 1
        idx_end = end - 1  # включно
        
        return sum(spectrum[idx_start:idx_end + 1])


    def _calculate_limits(self, sum_clean, sum_raw, T, sigma=2):
        """
        Розрахунок верхньої та нижньої меж статистичного відхилення.
            
            Вхід:
                sum_clean - сума по вікну з ARR_2 (після віднімання фону)
                sum_raw - сума по вікну з ARR_1 (до віднімання фону)
                T - час вимірювання в секундах
                sigma - коефіцієнт (2 - стандарт, 1 - для Tc в резерві)
            
            Вихід:
                dict { "upper": float, "lower": float }
            
            Формула:
                upper = sum_clean + sigma * sqrt(sum_raw / T)
                lower = sum_clean - sigma * sqrt(sum_raw / T)
        """       
        
        std = math.sqrt(sum_raw / T) if T > 0 else 0.0
        delta = sigma * std
        
        return {
            "upper": sum_clean + delta,
            "lower": sum_clean - delta
        }


    def _load_base_spectrum(self, name):
        """
        Завантаження базового спектру з self.calibration_spectra.
        
        Вхід:
            name - ім'я файлу без розширення (напр. "base_I")
        
        Вихід:
            list[float] - спектр довжиною 1023 (обрізаний або доповнений)
            None - якщо спектр не знайдено
        """
        spectrum = self.calibration_spectra.get(name)
        if spectrum is None:
            return None
        
        # Приводимо до 1023 каналів
        if len(spectrum) >= 1023:
            return list(spectrum[:1023])
        else:
            # Доповнюємо нулями
            result = list(spectrum)
            result.extend([0.0] * (1023 - len(result)))
            return result

    def _calculate_decay_coefficient(self, T, half_life_minutes):
        """
        Розрахунок коефіцієнта розпаду за час вимірювання.
        
        Вхід:
            T - час вимірювання в секундах
            half_life_minutes - період напіврозпаду в хвилинах
        
        Вихід:
            float - коефіцієнт розпаду
        
        Формула:
            K = (1/2) ^ ((T/60) / half_life_minutes)
        """
        time_hours = T / 60.0  # хвилини
        return (0.5) ** (time_hours / half_life_minutes)

    
    def _get_cistern_volume(self, posit_number):
        """
        Повертає об'єм цистерни в літрах за її номером.
        
        Вхід:
            posit_number - int номер цистерни (1..9)
        
        Вихід:
            float - об'єм у літрах
        
        Дані:
            ZB1, ZB2 -> 12020 л
            ZB3..ZB9 -> 13394 л
        """
        if posit_number in (1, 2):
            return 12020.0
        elif posit_number in (3, 4, 5, 6, 7, 8, 9):
            return 13394.0
        else:
            # Якщо номер невідомий, повертаємо значення за замовчуванням (13 394 л)
            # і логуємо попередження
            self.ui.textEdit.append(f"Увага: невідомий номер цистерни {posit_number}, використано об'єм 13394 л")
            return 13394.0



    def _identify_group_A(self, arr1, arr2, real_time, volume, history):
        """
        Ідентифікація ізотопів для групи A (цистерни 1, 2).
        
        Вхід:
            arr1 - list[float] нормований спектр (ARR_1) - до віднімання фону
            arr2 - list[float] спектр після віднімання фону (ARR_2)
            real_time - float час вимірювання в секундах (T)
            volume - float об'єм цистерни в літрах
            history - dict або None, історія попередніх вимірювань для Tc
                    (очікується словник з ключами: "sum_F_arr1", "sum_F_arr2", "sum_Tc_arr2")
        
        Вихід:
            dict з результатами:
            {
                "group": "A",
                "isotopes": ["18F", "99mTc"],
                "18F": {
                    "activity": float,          # загальна активність, Бк
                    "concentration": float,     # питома активність, Бк/л
                    "activity_upper": float,    # верхня межа активності, Бк
                    "activity_lower": float,    # нижня межа активності, Бк
                    "conc_upper": float,        # верхня межа концентрації, Бк/л
                    "conc_lower": float,        # нижня межа концентрації, Бк/л
                    "detected": str,            # "Є" / "МОЖЕ БУТИ" / "НЕМАЄ"
                    "sum_clean": float,         # сума по ARR_2
                    "sum_raw": float,           # сума по ARR_1
                    "limits": {"upper": float, "lower": float}
                },
                "99mTc": {
                    ... аналогічно ...
                },
                "real_time": float,
                "history_updated": dict        # оновлена історія для наступного виклику
            }
        """
        
        # --- 1. Розрахунок для фтору (18F) ---
        isotope_F = "18F"
        window_F = self.GROUP_A_WINDOWS[isotope_F]
        coeff_F = self.GROUP_A_COEFFICIENTS[isotope_F]
        sigma_F = self.GROUP_A_SIGMA[isotope_F]
        
        sum_F_clean = self._calculate_window_sum(arr2, window_F[0], window_F[1])
        sum_F_raw = self._calculate_window_sum(arr1, window_F[0], window_F[1])
        
        limits_F = self._calculate_limits(sum_F_clean, sum_F_raw, real_time, sigma_F)
        
        conc_F = sum_F_clean * coeff_F
        activity_F = conc_F * volume
        
        conc_F_upper = limits_F["upper"] * coeff_F
        conc_F_lower = limits_F["lower"] * coeff_F
        activity_F_upper = conc_F_upper * volume
        activity_F_lower = conc_F_lower * volume
        
        if limits_F["upper"] > 0 and limits_F["lower"] > 0:
            detected_F = "Є"
        elif limits_F["upper"] > 0 and limits_F["lower"] <= 0:
            detected_F = "МОЖЕ БУТИ"
        else:
            detected_F = "НЕМАЄ"
        
        # --- 2. Розрахунок для технецію (99mTc) ---
        isotope_Tc = "99mTc"
        window_Tc = self.GROUP_A_WINDOWS[isotope_Tc]
        coeff_Tc = self.GROUP_A_COEFFICIENTS[isotope_Tc]
        sigma_Tc = self.GROUP_A_SIGMA[isotope_Tc]
        
        sum_Tc_clean_current = self._calculate_window_sum(arr2, window_Tc[0], window_Tc[1])
        sum_Tc_raw_current = self._calculate_window_sum(arr1, window_Tc[0], window_Tc[1])
        
        if history is None or not history:
            # Перша година
            sum_Tc_clean = sum_Tc_clean_current
            sum_Tc_raw = sum_Tc_raw_current
            
            history_updated = {
                "sum_F_arr1": sum_F_raw,
                "sum_F_arr2": sum_F_clean,
                "sum_Tc_arr2": sum_Tc_clean_current,
                "sum_Tc_arr1": sum_Tc_raw_current,
                "hour": 1
            }
        else:
            # Наступні години
            K_F = self._calculate_decay_coefficient(real_time, self.GROUP_A_HALF_LIFE[isotope_F])
            K_Tc = self._calculate_decay_coefficient(real_time, self.GROUP_A_HALF_LIFE[isotope_Tc])
            
            prev_sum_Tc_arr2 = history["sum_Tc_arr2"]
            
            denom = K_Tc - K_F
            if abs(denom) < 1e-12:
                sum_Tc_clean = sum_Tc_clean_current
                sum_Tc_raw = sum_Tc_raw_current
            else:
                sum_Tc_clean = (sum_Tc_clean_current - K_F * prev_sum_Tc_arr2) / denom
                sum_Tc_raw = sum_Tc_raw_current
            
            # Перевірка умови переходу до прямих площ
            if sum_Tc_clean_current > 0 and (sum_Tc_clean / sum_Tc_clean_current) < self.GROUP_A_TC_THRESHOLD:
                sum_Tc_clean = sum_Tc_clean_current
                sum_Tc_raw = sum_Tc_raw_current
            
            history_updated = {
                "sum_F_arr1": sum_F_raw,
                "sum_F_arr2": sum_F_clean,
                "sum_Tc_arr2": sum_Tc_clean_current,
                "sum_Tc_arr1": sum_Tc_raw_current,
                "hour": history.get("hour", 0) + 1
            }
        
        limits_Tc = self._calculate_limits(sum_Tc_clean, sum_Tc_raw, real_time, sigma_Tc)
        
        conc_Tc = sum_Tc_clean * coeff_Tc
        activity_Tc = conc_Tc * volume
        
        conc_Tc_upper = limits_Tc["upper"] * coeff_Tc
        conc_Tc_lower = limits_Tc["lower"] * coeff_Tc
        activity_Tc_upper = conc_Tc_upper * volume
        activity_Tc_lower = conc_Tc_lower * volume
        
        if limits_Tc["upper"] > 0 and limits_Tc["lower"] > 0:
            detected_Tc = "Є"
        elif limits_Tc["upper"] > 0 and limits_Tc["lower"] <= 0:
            detected_Tc = "МОЖЕ БУТИ"
        else:
            detected_Tc = "НЕМАЄ"
        
        # --- Результат ---
        result = {
            "group": "A",
            "isotopes": ["18F", "99mTc"],
            "18F": {
                "activity": activity_F,
                "concentration": conc_F,
                "activity_upper": activity_F_upper,
                "activity_lower": activity_F_lower,
                "conc_upper": conc_F_upper,
                "conc_lower": conc_F_lower,
                "detected": detected_F,
                "sum_clean": sum_F_clean,
                "sum_raw": sum_F_raw,
                "limits": limits_F
            },
            "99mTc": {
                "activity": activity_Tc,
                "concentration": conc_Tc,
                "activity_upper": activity_Tc_upper,
                "activity_lower": activity_Tc_lower,
                "conc_upper": conc_Tc_upper,
                "conc_lower": conc_Tc_lower,
                "detected": detected_Tc,
                "sum_clean": sum_Tc_clean,
                "sum_raw": sum_Tc_raw,
                "limits": limits_Tc,
                "delay_hours": 1
            },
            "real_time": real_time,
            "history_updated": history_updated
        }
        
        return result


    def _identify_group_B(self, arr1, arr2, real_time, volume):
        """
        Ідентифікація ізотопів для групи B (цистерни 4–9).
        Ізотопи: 133I, 177Lu, 90Y.
        Порядок розрахунку: 90Y → 133I (з базовим спектром) → 177Lu.
        
        Вхід:
            arr1 - list[float] нормований спектр (ARR_1) - до віднімання фону
            arr2 - list[float] спектр після віднімання фону (ARR_2)
            real_time - float час вимірювання в секундах (T)
            volume - float об'єм цистерни в літрах
        
        Вихід:
            dict з результатами:
            {
                "group": "B",
                "isotopes": ["133I", "177Lu", "90Y"],
                "133I": {
                    "activity": float,
                    "concentration": float,
                    "activity_upper": float,
                    "activity_lower": float,
                    "conc_upper": float,
                    "conc_lower": float,
                    "detected": str,           # "Є" / "МОЖЕ БУТИ" / "НЕМАЄ"
                    "sum_clean": float,
                    "sum_raw": float,
                    "limits": {"upper": float, "lower": float}
                },
                "177Lu": { ... аналогічно ... },
                "90Y": { ... аналогічно ... },
                "real_time": float
            }
        """
        
        # --- 1. Розрахунок для ітрію (90Y) ---
        isotope_Y = "90Y"
        window_Y = self.GROUP_B_WINDOWS[isotope_Y]
        coeff_Y = self.GROUP_B_COEFFICIENTS[isotope_Y]
        sigma_Y = self.GROUP_B_SIGMA[isotope_Y]
        
        sum_Y_clean = self._calculate_window_sum(arr2, window_Y[0], window_Y[1])
        sum_Y_raw = self._calculate_window_sum(arr1, window_Y[0], window_Y[1])
        
        limits_Y = self._calculate_limits(sum_Y_clean, sum_Y_raw, real_time, sigma_Y)
        
        conc_Y = sum_Y_clean * coeff_Y
        activity_Y = conc_Y * volume
        
        conc_Y_upper = limits_Y["upper"] * coeff_Y
        conc_Y_lower = limits_Y["lower"] * coeff_Y
        activity_Y_upper = conc_Y_upper * volume
        activity_Y_lower = conc_Y_lower * volume
        
        if limits_Y["upper"] > 0 and limits_Y["lower"] > 0:
            detected_Y = "Є"
        elif limits_Y["upper"] > 0 and limits_Y["lower"] <= 0:
            detected_Y = "МОЖЕ БУТИ"
        else:
            detected_Y = "НЕМАЄ"
        
        # --- 2. Розрахунок для йоду (133I) з використанням базового спектру ---
        isotope_I = "133I"
        window_I = self.GROUP_B_WINDOWS[isotope_I]
        coeff_I = self.GROUP_B_COEFFICIENTS[isotope_I]
        sigma_I = self.GROUP_B_SIGMA[isotope_I]
        
        # Завантажуємо базовий спектр йоду (очікується файл "base_I" в self.calibration_spectra)
        base_spectrum = self._load_base_spectrum("base_I")
        if base_spectrum is None:
            # Якщо базовий спектр відсутній, використовуємо пряму площу без масштабування
            sum_I_clean = self._calculate_window_sum(arr2, window_I[0], window_I[1])
            sum_I_raw = self._calculate_window_sum(arr1, window_I[0], window_I[1])
            limits_I = self._calculate_limits(sum_I_clean, sum_I_raw, real_time, sigma_I)
            arr3 = None
        else:
            # Обчислюємо площу базового спектру у вікні I
            sum_base_I = self._calculate_window_sum(base_spectrum, window_I[0], window_I[1])
            if sum_base_I <= 0:
                # Якщо базова площа нульова — масштабування неможливе
                sum_I_clean = self._calculate_window_sum(arr2, window_I[0], window_I[1])
                sum_I_raw = self._calculate_window_sum(arr1, window_I[0], window_I[1])
                limits_I = self._calculate_limits(sum_I_clean, sum_I_raw, real_time, sigma_I)
                arr3 = None
            else:
                # Коефіцієнт масштабування: (площа I з ARR_2) / (площа базового I)
                sum_I_clean = self._calculate_window_sum(arr2, window_I[0], window_I[1])
                scale = sum_I_clean / sum_base_I
                
                # Масштабуємо базовий спектр (ARR_3 = base * scale)
                arr3 = [val * scale for val in base_spectrum]
                
                # Площа I з масштабованого базового спектру (ARR_3)
                sum_I_clean = self._calculate_window_sum(arr3, window_I[0], window_I[1])
                sum_I_raw = self._calculate_window_sum(arr1, window_I[0], window_I[1])
                
                limits_I = self._calculate_limits(sum_I_clean, sum_I_raw, real_time, sigma_I)
        
        conc_I = sum_I_clean * coeff_I
        activity_I = conc_I * volume
        
        conc_I_upper = limits_I["upper"] * coeff_I
        conc_I_lower = limits_I["lower"] * coeff_I
        activity_I_upper = conc_I_upper * volume
        activity_I_lower = conc_I_lower * volume
        
        if limits_I["upper"] > 0 and limits_I["lower"] > 0:
            detected_I = "Є"
        elif limits_I["upper"] > 0 and limits_I["lower"] <= 0:
            detected_I = "МОЖЕ БУТИ"
        else:
            detected_I = "НЕМАЄ"
        
        # --- 3. Розрахунок для лютецію (177Lu) після віднімання масштабованого йоду ---
        isotope_Lu = "177Lu"
        window_Lu = self.GROUP_B_WINDOWS[isotope_Lu]
        coeff_Lu = self.GROUP_B_COEFFICIENTS[isotope_Lu]
        sigma_Lu = self.GROUP_B_SIGMA[isotope_Lu]
        
        # Формуємо спектр ARR_4 = ARR_2 - ARR_3 (якщо arr3 існує)
        if arr3 is not None:
            arr4 = [arr2[i] - arr3[i] for i in range(len(arr2))]
        else:
            arr4 = arr2  # якщо масштабованого йоду немає, використовуємо ARR_2 без змін
        
        sum_Lu_clean = self._calculate_window_sum(arr4, window_Lu[0], window_Lu[1])
        sum_Lu_raw = self._calculate_window_sum(arr1, window_Lu[0], window_Lu[1])
        
        limits_Lu = self._calculate_limits(sum_Lu_clean, sum_Lu_raw, real_time, sigma_Lu)
        
        conc_Lu = sum_Lu_clean * coeff_Lu
        activity_Lu = conc_Lu * volume
        
        conc_Lu_upper = limits_Lu["upper"] * coeff_Lu
        conc_Lu_lower = limits_Lu["lower"] * coeff_Lu
        activity_Lu_upper = conc_Lu_upper * volume
        activity_Lu_lower = conc_Lu_lower * volume
        
        if limits_Lu["upper"] > 0 and limits_Lu["lower"] > 0:
            detected_Lu = "Є"
        elif limits_Lu["upper"] > 0 and limits_Lu["lower"] <= 0:
            detected_Lu = "МОЖЕ БУТИ"
        else:
            detected_Lu = "НЕМАЄ"
        
        # --- Результат ---
        result = {
            "group": "B",
            "isotopes": ["133I", "177Lu", "90Y"],
            "133I": {
                "activity": activity_I,
                "concentration": conc_I,
                "activity_upper": activity_I_upper,
                "activity_lower": activity_I_lower,
                "conc_upper": conc_I_upper,
                "conc_lower": conc_I_lower,
                "detected": detected_I,
                "sum_clean": sum_I_clean,
                "sum_raw": sum_I_raw,
                "limits": limits_I
            },
            "177Lu": {
                "activity": activity_Lu,
                "concentration": conc_Lu,
                "activity_upper": activity_Lu_upper,
                "activity_lower": activity_Lu_lower,
                "conc_upper": conc_Lu_upper,
                "conc_lower": conc_Lu_lower,
                "detected": detected_Lu,
                "sum_clean": sum_Lu_clean,
                "sum_raw": sum_Lu_raw,
                "limits": limits_Lu
            },
            "90Y": {
                "activity": activity_Y,
                "concentration": conc_Y,
                "activity_upper": activity_Y_upper,
                "activity_lower": activity_Y_lower,
                "conc_upper": conc_Y_upper,
                "conc_lower": conc_Y_lower,
                "detected": detected_Y,
                "sum_clean": sum_Y_clean,
                "sum_raw": sum_Y_raw,
                "limits": limits_Y
            },
            "real_time": real_time
        }
        
        return result

    def _identify_group_reserve(self, arr1, arr2, real_time, volume, history):
        """
        Ідентифікація ізотопів для резервної цистерни (цистерна 3).
        Усі 5 ізотопів: 18F, 99mTc, 133I, 177Lu, 90Y.
        
        Порядок розрахунку:
            1. 90Y (371–820)
            2. 133I (базове окно 115–150 для масштабування, фінальне 90–150)
            3. Віднімання масштабованого I
            4. 177Lu (63–89)
            5. 18F (161–204)
            6. 99mTc (12–64, 1 сигма, динаміка з затримкою 6 годин)
        
        Вхід:
            arr1 - list[float] нормований спектр (ARR_1) - до віднімання фону
            arr2 - list[float] спектр після віднімання фону (ARR_2)
            real_time - float час вимірювання в секундах (T)
            volume - float об'єм цистерни в літрах
            history - dict або None, історія для Tc:
                {
                    "hours": [sum_Tc_clean, ...],  # список площ Tc по годинах
                    "hour_index": int,              # поточна година (1..n)
                    "extrapolation_started": bool,  # чи вже перейшли до екстраполяції
                    "last_upper": float,            # останнє значення верхньої межі для екстраполяції
                    "last_lower": float             # останнє значення нижньої межі для екстраполяції
                }
        
        Вихід:
            dict з результатами для всіх 5 ізотопів +
            "history_updated" для Tc
        """
        
        # --- 1. Розрахунок для ітрію (90Y) ---
        isotope_Y = "90Y"
        window_Y = self.GROUP_RESERVE_WINDOWS[isotope_Y]
        coeff_Y = self.GROUP_RESERVE_COEFFICIENTS[isotope_Y]
        sigma_Y = self.GROUP_RESERVE_SIGMA[isotope_Y]
        
        sum_Y_clean = self._calculate_window_sum(arr2, window_Y[0], window_Y[1])
        sum_Y_raw = self._calculate_window_sum(arr1, window_Y[0], window_Y[1])
        limits_Y = self._calculate_limits(sum_Y_clean, sum_Y_raw, real_time, sigma_Y)
        
        conc_Y = sum_Y_clean * coeff_Y
        activity_Y = conc_Y * volume
        conc_Y_upper = limits_Y["upper"] * coeff_Y
        conc_Y_lower = limits_Y["lower"] * coeff_Y
        activity_Y_upper = conc_Y_upper * volume
        activity_Y_lower = conc_Y_lower * volume
        
        if limits_Y["upper"] > 0 and limits_Y["lower"] > 0:
            detected_Y = "Є"
        elif limits_Y["upper"] > 0 and limits_Y["lower"] <= 0:
            detected_Y = "МОЖЕ БУТИ"
        else:
            detected_Y = "НЕМАЄ"
        
        # --- 2. Розрахунок для йоду (133I) з базовим спектром ---
        isotope_I = "133I"
        window_I = self.GROUP_RESERVE_WINDOWS[isotope_I]           # фінальне окно (90–150)
        base_window_I = self.GROUP_RESERVE_BASE_I_WINDOW           # окно для масштабування (115–150)
        coeff_I = self.GROUP_RESERVE_COEFFICIENTS[isotope_I]
        sigma_I = self.GROUP_RESERVE_SIGMA[isotope_I]
        
        # Завантажуємо базовий спектр йоду
        base_spectrum = self._load_base_spectrum("base_I")
        if base_spectrum is None:
            # Якщо базового спектра немає — використовуємо пряму площу
            sum_I_clean = self._calculate_window_sum(arr2, window_I[0], window_I[1])
            sum_I_raw = self._calculate_window_sum(arr1, window_I[0], window_I[1])
            limits_I = self._calculate_limits(sum_I_clean, sum_I_raw, real_time, sigma_I)
            arr3 = None
        else:
            # Площа I з ARR_2 у базовому вікні (115–150)
            sum_I_arr2_base = self._calculate_window_sum(arr2, base_window_I[0], base_window_I[1])
            # Площа базового спектра у базовому вікні (115–150)
            sum_base_I = self._calculate_window_sum(base_spectrum, base_window_I[0], base_window_I[1])
            
            if sum_base_I <= 0:
                sum_I_clean = self._calculate_window_sum(arr2, window_I[0], window_I[1])
                sum_I_raw = self._calculate_window_sum(arr1, window_I[0], window_I[1])
                limits_I = self._calculate_limits(sum_I_clean, sum_I_raw, real_time, sigma_I)
                arr3 = None
            else:
                scale = sum_I_arr2_base / sum_base_I
                arr3 = [val * scale for val in base_spectrum]
                sum_I_clean = self._calculate_window_sum(arr3, window_I[0], window_I[1])
                sum_I_raw = self._calculate_window_sum(arr1, window_I[0], window_I[1])
                limits_I = self._calculate_limits(sum_I_clean, sum_I_raw, real_time, sigma_I)
        
        conc_I = sum_I_clean * coeff_I
        activity_I = conc_I * volume
        conc_I_upper = limits_I["upper"] * coeff_I
        conc_I_lower = limits_I["lower"] * coeff_I
        activity_I_upper = conc_I_upper * volume
        activity_I_lower = conc_I_lower * volume
        
        if limits_I["upper"] > 0 and limits_I["lower"] > 0:
            detected_I = "Є"
        elif limits_I["upper"] > 0 and limits_I["lower"] <= 0:
            detected_I = "МОЖЕ БУТИ"
        else:
            detected_I = "НЕМАЄ"
        
        # --- 3. Віднімання масштабованого йоду (ARR_4 = ARR_2 - ARR_3) ---
        if arr3 is not None:
            arr4 = [arr2[i] - arr3[i] for i in range(len(arr2))]
        else:
            arr4 = arr2
        
        # --- 4. Розрахунок для лютецію (177Lu) ---
        isotope_Lu = "177Lu"
        window_Lu = self.GROUP_RESERVE_WINDOWS[isotope_Lu]
        coeff_Lu = self.GROUP_RESERVE_COEFFICIENTS[isotope_Lu]
        sigma_Lu = self.GROUP_RESERVE_SIGMA[isotope_Lu]
        
        sum_Lu_clean = self._calculate_window_sum(arr4, window_Lu[0], window_Lu[1])
        sum_Lu_raw = self._calculate_window_sum(arr1, window_Lu[0], window_Lu[1])
        limits_Lu = self._calculate_limits(sum_Lu_clean, sum_Lu_raw, real_time, sigma_Lu)
        
        conc_Lu = sum_Lu_clean * coeff_Lu
        activity_Lu = conc_Lu * volume
        conc_Lu_upper = limits_Lu["upper"] * coeff_Lu
        conc_Lu_lower = limits_Lu["lower"] * coeff_Lu
        activity_Lu_upper = conc_Lu_upper * volume
        activity_Lu_lower = conc_Lu_lower * volume
        
        if limits_Lu["upper"] > 0 and limits_Lu["lower"] > 0:
            detected_Lu = "Є"
        elif limits_Lu["upper"] > 0 and limits_Lu["lower"] <= 0:
            detected_Lu = "МОЖЕ БУТИ"
        else:
            detected_Lu = "НЕМАЄ"
        
        # --- 5. Розрахунок для фтору (18F) ---
        isotope_F = "18F"
        window_F = self.GROUP_RESERVE_WINDOWS[isotope_F]
        coeff_F = self.GROUP_RESERVE_COEFFICIENTS[isotope_F]
        sigma_F = self.GROUP_RESERVE_SIGMA[isotope_F]
        
        sum_F_clean = self._calculate_window_sum(arr4, window_F[0], window_F[1])
        sum_F_raw = self._calculate_window_sum(arr1, window_F[0], window_F[1])
        limits_F = self._calculate_limits(sum_F_clean, sum_F_raw, real_time, sigma_F)
        
        conc_F = sum_F_clean * coeff_F
        activity_F = conc_F * volume
        conc_F_upper = limits_F["upper"] * coeff_F
        conc_F_lower = limits_F["lower"] * coeff_F
        activity_F_upper = conc_F_upper * volume
        activity_F_lower = conc_F_lower * volume
        
        if limits_F["upper"] > 0 and limits_F["lower"] > 0:
            detected_F = "Є"
        elif limits_F["upper"] > 0 and limits_F["lower"] <= 0:
            detected_F = "МОЖЕ БУТИ"
        else:
            detected_F = "НЕМАЄ"
        
        # --- 6. Розрахунок для технецію (99mTc) з динамікою ---
        isotope_Tc = "99mTc"
        window_Tc = self.GROUP_RESERVE_WINDOWS[isotope_Tc]
        coeff_Tc = self.GROUP_RESERVE_COEFFICIENTS[isotope_Tc]
        sigma_Tc = self.GROUP_RESERVE_SIGMA[isotope_Tc]  # 1 сигма
        
        sum_Tc_clean_current = self._calculate_window_sum(arr4, window_Tc[0], window_Tc[1])
        sum_Tc_raw_current = self._calculate_window_sum(arr1, window_Tc[0], window_Tc[1])
        
        # Ініціалізація історії
        if history is None:
            history = {
                "hours": [],
                "hour_index": 0,
                "extrapolation_started": False,
                "last_upper": 0.0,
                "last_lower": 0.0
            }
        
        # Поточна година (1-based)
        current_hour = history.get("hour_index", 0) + 1
        history["hour_index"] = current_hour
        
        # --- Обробка Tc ---
        if current_hour <= 6:
            # Години 1–6: просто накопичуємо площі
            history["hours"].append(sum_Tc_clean_current)
            
            # Поки що використовуємо пряму площу
            sum_Tc_clean = sum_Tc_clean_current
            sum_Tc_raw = sum_Tc_raw_current
            limits_Tc = self._calculate_limits(sum_Tc_clean, sum_Tc_raw, real_time, sigma_Tc)
            
            detected_Tc = "НЕМАЄ"  # ідентифікація поки не виконується
            delay_hours = 0
            history_updated = history
            
        elif current_hour == 7:
            # 7-ма година: перехід до динаміки
            # Беремо площу з 1-ї години
            if len(history["hours"]) >= 1:
                sum_Tc_1st = history["hours"][0]
            else:
                sum_Tc_1st = sum_Tc_clean_current
            
            # Обчислюємо відношення
            ratio = sum_Tc_1st / sum_Tc_clean_current if sum_Tc_clean_current > 0 else float('inf')
            
            # Коефіцієнти розпаду за 6 годин
            K_Tc = self._calculate_decay_coefficient(real_time * 6, self.GROUP_A_HALF_LIFE[isotope_Tc])
            K_Lu = self._calculate_decay_coefficient(real_time * 6, 9570.0)  # період Lu
            K_F = self._calculate_decay_coefficient(real_time * 6, self.GROUP_A_HALF_LIFE[isotope_F])
            
            if ratio < 1.5:
                # Варіант C: одразу екстраполяція
                # Беремо межі з поточної площі (1 сигма)
                limits_Tc = self._calculate_limits(sum_Tc_clean_current, sum_Tc_raw_current, real_time, sigma_Tc)
                last_upper = limits_Tc["upper"]
                last_lower = limits_Tc["lower"]
                
                history["extrapolation_started"] = True
                history["last_upper"] = last_upper
                history["last_lower"] = last_lower
                
                sum_Tc_clean = sum_Tc_clean_current
                sum_Tc_raw = sum_Tc_raw_current
                delay_hours = 0
                
            elif ratio <= 2:
                # Варіант A: Tc + Lu
                upper = (limits_Tc["lower"] - K_Lu * limits_Y["upper"]) / (K_Tc - K_Lu)
                lower = (limits_Tc["upper"] - K_Lu * limits_Y["lower"]) / (K_Tc - K_Lu)
                
                limits_Tc = {"upper": upper, "lower": lower}
                sum_Tc_clean = (sum_Tc_clean_current - K_Lu * sum_Y_clean) / (K_Tc - K_Lu)
                sum_Tc_raw = sum_Tc_raw_current
                
                # Встановлюємо межі для екстраполяції
                history["last_upper"] = upper
                history["last_lower"] = lower
                delay_hours = 6
                
            else:
                # Варіант B: Tc + F
                upper = (limits_Tc["lower"] - K_F * limits_F["upper"]) / (K_Tc - K_F)
                lower = (limits_Tc["upper"] - K_F * limits_F["lower"]) / (K_Tc - K_F)
                
                limits_Tc = {"upper": upper, "lower": lower}
                sum_Tc_clean = (sum_Tc_clean_current - K_F * sum_F_clean) / (K_Tc - K_F)
                sum_Tc_raw = sum_Tc_raw_current
                
                history["last_upper"] = upper
                history["last_lower"] = lower
                delay_hours = 6
            
            # Ідентифікація Tc
            if limits_Tc["upper"] > 0 and limits_Tc["lower"] > 0:
                detected_Tc = "Є"
            elif limits_Tc["upper"] > 0 and limits_Tc["lower"] <= 0:
                detected_Tc = "МОЖЕ БУТИ"
            else:
                detected_Tc = "НЕМАЄ"
            
            history_updated = history
            
        else:
            # Години 8+: екстраполяція
            if history.get("extrapolation_started", False) or current_hour > 7:
                history["extrapolation_started"] = True
                # Множимо попередні значення на коефіцієнт 0.890899
                last_upper = history.get("last_upper", 0.0)
                last_lower = history.get("last_lower", 0.0)
                
                new_upper = last_upper * self.GROUP_RESERVE_TC_EXTRAPOLATION_COEFF
                new_lower = last_lower * self.GROUP_RESERVE_TC_EXTRAPOLATION_COEFF
                
                history["last_upper"] = new_upper
                history["last_lower"] = new_lower
                
                limits_Tc = {"upper": new_upper, "lower": new_lower}
                
                # Для активності використовуємо екстрапольовані межі
                sum_Tc_clean = (new_upper + new_lower) / 2  # середнє
                sum_Tc_raw = sum_Tc_raw_current
                
                if limits_Tc["upper"] > 0 and limits_Tc["lower"] > 0:
                    detected_Tc = "Є"
                elif limits_Tc["upper"] > 0 and limits_Tc["lower"] <= 0:
                    detected_Tc = "МОЖЕ БУТИ"
                else:
                    detected_Tc = "НЕМАЄ"
                
                delay_hours = 6
                history_updated = history
            else:
                # Запасний варіант
                sum_Tc_clean = sum_Tc_clean_current
                sum_Tc_raw = sum_Tc_raw_current
                limits_Tc = self._calculate_limits(sum_Tc_clean, sum_Tc_raw, real_time, sigma_Tc)
                detected_Tc = "НЕМАЄ"
                delay_hours = 0
                history_updated = history
        
        # Розрахунок активності Tc
        conc_Tc = sum_Tc_clean * coeff_Tc
        activity_Tc = conc_Tc * volume
        conc_Tc_upper = limits_Tc["upper"] * coeff_Tc
        conc_Tc_lower = limits_Tc["lower"] * coeff_Tc
        activity_Tc_upper = conc_Tc_upper * volume
        activity_Tc_lower = conc_Tc_lower * volume
        
        # --- Результат ---
        result = {
            "group": "reserve",
            "isotopes": ["18F", "99mTc", "133I", "177Lu", "90Y"],
            "18F": {
                "activity": activity_F,
                "concentration": conc_F,
                "activity_upper": activity_F_upper,
                "activity_lower": activity_F_lower,
                "conc_upper": conc_F_upper,
                "conc_lower": conc_F_lower,
                "detected": detected_F,
                "sum_clean": sum_F_clean,
                "sum_raw": sum_F_raw,
                "limits": limits_F
            },
            "99mTc": {
                "activity": activity_Tc,
                "concentration": conc_Tc,
                "activity_upper": activity_Tc_upper,
                "activity_lower": activity_Tc_lower,
                "conc_upper": conc_Tc_upper,
                "conc_lower": conc_Tc_lower,
                "detected": detected_Tc,
                "sum_clean": sum_Tc_clean,
                "sum_raw": sum_Tc_raw,
                "limits": limits_Tc,
                "delay_hours": delay_hours
            },
            "133I": {
                "activity": activity_I,
                "concentration": conc_I,
                "activity_upper": activity_I_upper,
                "activity_lower": activity_I_lower,
                "conc_upper": conc_I_upper,
                "conc_lower": conc_I_lower,
                "detected": detected_I,
                "sum_clean": sum_I_clean,
                "sum_raw": sum_I_raw,
                "limits": limits_I
            },
            "177Lu": {
                "activity": activity_Lu,
                "concentration": conc_Lu,
                "activity_upper": activity_Lu_upper,
                "activity_lower": activity_Lu_lower,
                "conc_upper": conc_Lu_upper,
                "conc_lower": conc_Lu_lower,
                "detected": detected_Lu,
                "sum_clean": sum_Lu_clean,
                "sum_raw": sum_Lu_raw,
                "limits": limits_Lu
            },
            "90Y": {
                "activity": activity_Y,
                "concentration": conc_Y,
                "activity_upper": activity_Y_upper,
                "activity_lower": activity_Y_lower,
                "conc_upper": conc_Y_upper,
                "conc_lower": conc_Y_lower,
                "detected": detected_Y,
                "sum_clean": sum_Y_clean,
                "sum_raw": sum_Y_raw,
                "limits": limits_Y
            },
            "real_time": real_time,
            "history_updated": history_updated
        }
        
        return result

   

   

    def identify_isotopes_alim(self, spectrum, cistern_position, history=None):
        """
        Головний метод ідентифікації ізотопів (ALIM).
        
        Вхід:
            spectrum - list[float] масив 1024 елементів (1023 спектра + час набора в кінці)
            cistern_position - int номер цистерни
            history - dict або None, історія для груп A та reserve
        
        Вихід:
            (result, updated_history) - кортеж:
                result - dict з результатами (структура залежить від групи)
                updated_history - dict оновлена історія для наступного виклику
        """
        # ------------------------------------------------------------
        # 1. Витягуємо час набора та спектр
        # ------------------------------------------------------------
        real_time = spectrum[-1] if len(spectrum) > 0 else 3600.0
        if real_time <= 0:
            real_time = 3600.0
        
        # Відокремлюємо спектр (1023 канали)
        raw_spectrum = spectrum[:1023]
        
        # ------------------------------------------------------------
        # 2. Нормалізація спектру (ARR_1)
        # ------------------------------------------------------------
        arr1 = self._normalize_spectrum(raw_spectrum, real_time)
        
        # ------------------------------------------------------------
        # 3. Віднімання фону (ARR_2)
        # ------------------------------------------------------------
        arr2 = self._subtract_background(arr1)
        
        # ------------------------------------------------------------
        # 4. Визначаємо групу та отримуємо об'єм
        # ------------------------------------------------------------
        group = self.cistern_groups.get(cistern_position, "A")
        volume = self._get_cistern_volume(cistern_position)
        
        # ------------------------------------------------------------
        # 5. Виклик відповідного алгоритму
        # ------------------------------------------------------------
        if group == "A":
            result = self._identify_group_A(arr1, arr2, real_time, volume, history)
            updated_history = result.pop("history_updated", {})
        elif group == "B":
            result = self._identify_group_B(arr1, arr2, real_time, volume)
            updated_history = {}  # для групи B історія не потрібна
        elif group == "reserve":
            result = self._identify_group_reserve(arr1, arr2, real_time, volume, history)
            updated_history = result.pop("history_updated", {})
        else:
            # Невідома група — повертаємо порожній результат
            result = {
                "group": "unknown",
                "isotopes": [],
                "real_time": real_time
            }
            updated_history = {}
        
        # ------------------------------------------------------------
        # 6. Повертаємо результат та оновлену історію
        # ------------------------------------------------------------
        return result, updated_history
    
  

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
