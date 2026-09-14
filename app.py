# app.py

import sys
from PySide6.QtWidgets import QApplication, QWidget, QGridLayout, QVBoxLayout, QPushButton, QLabel, QSizePolicy, QSpacerItem, QDialog, QLineEdit, QMessageBox, QHBoxLayout, QSpinBox, QMenu
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QThread, QMetaObject, QTimer , Qt, QObject, Signal, QDateTime, QProcess
from devices.device_manager import DeviceManager
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtNetwork import QHostAddress
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import json, numpy as np
import os, math, time


from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator

from database.db_manager import DatabaseManager
from dialogs.device_replace_dialog import DeviceReplaceDialog
import json

from modbus_bridge_client import ModBusBridgeClient




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
        # self.repeat_counter = 100

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
        self.spectrum_buffer = [0] * 1023   # массив для накопления спектра (1024 канала)
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

        # # ------------------------------------------------------------
        # # НОВЫЙ АТРИБУТ: активен ли режим накопления спектра
        # # ------------------------------------------------------------
        # self.spectrum_active = False

                # ------------------------------------------------------------
        # ДИАГНОСТИЧЕСКОЕ ВРЕМЯ, ПОЛУЧЕННОЕ ОТ ПРИБОРА
        # ------------------------------------------------------------
        #
        # Эти значения сохраняются только для диагностики.
        #
        # Они НЕ определяют длительность полного спектрального цикла
        # и НЕ используются как расчётное время T.
        #
        # Управляющее и расчётное время цикла измеряется компьютером
        # через time.monotonic().
        self.last_acquisition_time = 0.0
        self.total_acquisition_time = 0.0

        # ------------------------------------------------------------
        # МОНОТОННОЕ ВРЕМЯ НАЧАЛА ПОЛНОГО СПЕКТРАЛЬНОГО ЦИКЛА
        # ------------------------------------------------------------
        #
        # Значение устанавливается только после получения успешного
        # ответа StartSpectre.
        #
        # None означает, что подтверждённый спектральный цикл
        # в данный момент не запущен.
        self.spectrum_start_monotonic = None

        # ------------------------------------------------------------
        # ФАКТИЧЕСКАЯ ДЛИТЕЛЬНОСТЬ ЗАВЕРШЁННОГО ЦИКЛА
        # ------------------------------------------------------------
        #
        # Сюда перед calculate_activity() записывается фактическое
        # время от успешного StartSpectre до последнего GetSpectre.
        #
        # Именно это значение используется алгоритмом как T.
        self.spectrum_elapsed_time = 0.0

        # История алгоритма Tc.
        #
        # Она сохраняется между последовательными спектральными
        # циклами одной и той же заполненной цистерны.
        self.algorithm_history = {}

        # ------------------------------------------------------------
        # Активен ли локальный спектральный цикл
        # ------------------------------------------------------------
        self.spectrum_active = False

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




    def add_spectrum_data(self, channels) -> bool:
        """
        Добавляет очередной успешно полученный участок GetSpectre
        к общему спектру текущего цикла.

        Формат channels:

            channels[0:1023] -> 1023 спектральных канала;
            channels[1023]   -> время участка, сообщённое прибором.

        ВАЖНО:

            время прибора сохраняется только для диагностики.

            Завершение полного спектрального цикла определяется
            исключительно по времени компьютера:

                time.monotonic() - spectrum_start_monotonic

            После добавления ТЕКУЩЕГО пакета вызывается
            is_spectrum_ready().

            Поэтому GetSpectre, на котором был достигнут заданный
            интервал накопления, обязательно входит в итоговый
            накопленный спектр.

        Возвращает:

            True  - текущий GetSpectre является последним пакетом
                    полного цикла;

            False - накопление необходимо продолжать.
        """

        # ============================================================
        # 1. ПРОВЕРЯЕМ ТИП ПОЛУЧЕННЫХ ДАННЫХ
        # ============================================================

        if not isinstance(channels, (list, tuple)):
            return False

        # ============================================================
        # 2. ПРОВЕРЯЕМ СТРУКТУРУ
        # ============================================================
        #
        # Текущая структура, которую формирует DeviceManager:
        #
        #     1023 спектральных канала
        #     +
        #     1 значение времени прибора.
        #
        # Итого 1024 элемента.

        if len(channels) != 1024:
            return False

        # ============================================================
        # 3. ЧИТАЕМ ДИАГНОСТИЧЕСКОЕ ВРЕМЯ ПРИБОРА
        # ============================================================

        try:
            acquisition_time = float(channels[1023])

        except (TypeError, ValueError):
            return False

        if (
            not math.isfinite(acquisition_time)
            or acquisition_time < 0.0
        ):
            return False

        # ============================================================
        # 4. ПРОВЕРЯЕМ 1023 СПЕКТРАЛЬНЫХ КАНАЛА
        # ============================================================

        spectrum_part = []

        for i in range(1023):

            try:
                value = int(channels[i])

            except (TypeError, ValueError):
                return False

            # Количество зарегистрированных импульсов не может
            # быть отрицательным.
            if value < 0:
                return False

            spectrum_part.append(value)

        # ============================================================
        # 5. ПРОВЕРЯЕМ, ЧТО StartSpectre БЫЛ ПОДТВЕРЖДЁН
        # ============================================================
        #
        # Нормальный цикл обязан иметь время начала, установленное
        # после успешного ответа StartSpectre.
        #
        # Если его нет, пакет не должен случайно сформировать
        # самостоятельный полный спектральный цикл.

        if self.spectrum_start_monotonic is None:

            if (
                self.parent_app is not None
                and getattr(self.parent_app, "ui", None) is not None
            ):
                self.parent_app.ui.textEdit.append(
                    (
                        "Помилка: отримано GetSpectre без "
                        "підтвердженого StartSpectre для "
                        f"SN {self.serial_number}."
                    )
                )

            return False

        # ============================================================
        # 6. АДДИТИВНО НАКАПЛИВАЕМ СПЕКТР
        # ============================================================

        for i in range(1023):
            self.spectrum_buffer[i] += spectrum_part[i]

        # ============================================================
        # 7. СОХРАНЯЕМ ВРЕМЯ, СООБЩЁННОЕ ПРИБОРОМ
        # ============================================================
        #
        # Эти два поля оставляем для будущей проверки на реальном
        # оборудовании.
        #
        # В алгоритме идентификации они как T не используются.

        self.last_acquisition_time = acquisition_time
        self.total_acquisition_time += acquisition_time

        # ============================================================
        # 8. СЧЁТЧИК УСПЕШНО ПОЛУЧЕННЫХ GetSpectre
        # ============================================================
        #
        # Теперь это только диагностический счётчик.
        # Он НЕ является условием окончания цикла.

        self.spectrum_counter += 1

        # ============================================================
        # 9. ОБНОВЛЯЕМ ОТОБРАЖЕНИЕ НАКОПЛЕННОГО СПЕКТРА
        # ============================================================

        self.update_spectrum_display()

        # ============================================================
        # 10. ПРОВЕРЯЕМ ВРЕМЯ ПОЛНОГО ЦИКЛА
        # ============================================================
        #
        # Проверка выполняется ПОСЛЕ суммирования текущего пакета.
        #
        # Следовательно, первый успешно полученный GetSpectre после
        # достижения заданного времени становится последним пакетом
        # текущего полного цикла.

        return self.is_spectrum_ready()



    def is_spectrum_ready(self) -> bool:
        """
        Проверяет окончание текущего полного спектрального цикла
        по фактически прошедшему компьютерному времени.

        Цикл считается готовым, когда:

            time.monotonic() - spectrum_start_monotonic
                >=
            parent_app.spectrum_accumulation_time

        ВАЖНО:

            spectrum_accumulation_time читается при каждой проверке.

        Поэтому если оператор изменил длительность накопления во
        время уже работающего цикла, новое значение начинает
        действовать сразу.
        """

        # Без подтверждённого StartSpectre цикл не существует.
        if self.spectrum_start_monotonic is None:
            return False

        # Карточка должна принадлежать основному приложению,
        # поскольку именно App хранит текущую настройку времени.
        if self.parent_app is None:
            return False

        try:
            target_time = float(
                self.parent_app.spectrum_accumulation_time
            )

        except (AttributeError, TypeError, ValueError):
            return False

        # Нулевой, отрицательный, NaN или бесконечный интервал
        # не должен приводить к мгновенному ложному завершению.
        if (
            not math.isfinite(target_time)
            or target_time <= 0.0
        ):
            return False

        elapsed = (
            time.monotonic()
            - self.spectrum_start_monotonic
        )

        return elapsed >= target_time

    

    
    def reset_spectrum(self):
        """
        Полностью сбрасывает данные текущего спектрального цикла.

        Сбрасываются:

            - накопленные 1023 канала;
            - диагностический счётчик GetSpectre;
            - диагностическое время прибора;
            - компьютерное время начала цикла;
            - фактическая длительность завершённого цикла;
            - локальный флаг spectrum_active.

        algorithm_history здесь НЕ сбрасывается.

        История Tc должна сохраняться между последовательными
        спектральными циклами одной и той же заполненной цистерны.
        Она очищается отдельно при изменении состояния цистерны.
        """

        # Накопленный спектр текущего цикла.
        self.spectrum_buffer = [0] * 1023

        # Диагностическое количество успешно принятых GetSpectre.
        self.spectrum_counter = 0

        # Диагностическое время, сообщённое прибором.
        self.last_acquisition_time = 0.0
        self.total_acquisition_time = 0.0

        # Новый цикл ещё не был подтверждён StartSpectre.
        self.spectrum_start_monotonic = None

        # Фактическое время предыдущего цикла больше не относится
        # к новому накоплению.
        self.spectrum_elapsed_time = 0.0

        # Локальный GUI-флаг спектрального режима.
        self.spectrum_active = False

        # Очищаем отображение накопленного спектра.
        self.update_spectrum_display()

        # ============================================================
        # СОХРАНЕНИЕ СОБЫТИЯ
        # ============================================================

        if (
            hasattr(self, "parent_app")
            and self.parent_app is not None
        ):

            device_id = (
                self.parent_app.db_manager.get_device_id(
                    self.serial_number
                )
            )

            if device_id:

                self.parent_app.db_manager.save_system_event(
                    device_id,
                    "spectrum_reset",
                    "Спектр скинуто"
                )


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
        Расчёт активности и идентификация изотопов.

        ================================================================
        READY_TO_DRAIN
        ================================================================

        Для решения о сливе используются ВЕРХНИЕ статистические границы:

            activity_upper
            conc_upper

        Центральные:

            activity
            concentration

        по-прежнему:

            - показываются оператору;
            - записываются в БД;
            - передаются в Bridge как результаты измерения.

        Нормативное решение ready_to_drain принимается
        консервативно — по верхним статистическим границам.

        ================================================================
        БАЗА ДАННЫХ
        ================================================================

        Для завершённого спектрального результата сохраняются:

            activity
            concentration
            activity_upper
            concentration_upper
            result_meta
            ready_to_drain
            measurement_valid

        Для резервной цистерны ZB3 в result_meta сохраняется
        дополнительная информация о результате 99mTc.
        """

        # ============================================================
        # 1. ПРОВЕРЯЕМ ДОСТУП К APP
        # ============================================================

        if (
            not hasattr(self, "parent_app")
            or
            not self.parent_app
        ):
            return

        # ============================================================
        # 2. ФАКТИЧЕСКОЕ ВРЕМЯ СПЕКТРАЛЬНОГО ЦИКЛА
        # ============================================================

        try:
            real_cycle_time = float(
                self.spectrum_elapsed_time
            )

        except (TypeError, ValueError):
            real_cycle_time = 0.0

        if (
            not math.isfinite(real_cycle_time)
            or
            real_cycle_time <= 0.0
        ):

            self.parent_app.ui.textEdit.append(
                f"Помилка: некоректний фактичний час "
                f"накопичення спектру для SN "
                f"{self.serial_number}: "
                f"{self.spectrum_elapsed_time}"
            )

            self.reset_spectrum()
            return

        # ============================================================
        # 3. ПРОВЕРЯЕМ ДЛИНУ СПЕКТРА
        # ============================================================

        if len(self.spectrum_buffer) != 1023:

            self.parent_app.ui.textEdit.append(
                f"Помилка: некоректна довжина "
                f"накопиченого спектру для SN "
                f"{self.serial_number}: "
                f"{len(self.spectrum_buffer)}"
            )

            self.reset_spectrum()
            return

        # ============================================================
        # 4. ФОРМИРУЕМ 1023 + ФАКТИЧЕСКОЕ ВРЕМЯ
        # ============================================================

        spectrum_with_time = (
            list(self.spectrum_buffer)
            + [real_cycle_time]
        )

        # ============================================================
        # 5. ВЫЗЫВАЕМ ALIM
        # ============================================================

        result, updated_history = (
            self.parent_app.identify_isotopes_alim(
                spectrum_with_time,
                self.posit_number,
                self.algorithm_history
            )
        )

        self.algorithm_history = updated_history

        if not result:
            self.reset_spectrum()
            return

        # ============================================================
        # 6. ОСНОВНЫЕ ДАННЫЕ РЕЗУЛЬТАТА
        # ============================================================

        group = result.get(
            "group",
            "A"
        )

        real_time = result.get(
            "real_time",
            real_cycle_time
        )

        calculation_time = result.get(
            "calculation_time",
            real_time
        )

        isotopes_list = result.get(
            "isotopes",
            []
        )

        measurement_valid = (
            result.get(
                "measurement_valid",
                True
            )
            is True
        )

        # ============================================================
        # 7. СЛОВАРИ ЦЕНТРАЛЬНЫХ РЕЗУЛЬТАТОВ
        # ============================================================

        activity_dict = {}
        concentration_dict = {}

        # ============================================================
        # 8. СЛОВАРИ ВЕРХНИХ СТАТИСТИЧЕСКИХ ГРАНИЦ
        # ============================================================

        activity_upper_dict = {}
        concentration_upper_dict = {}

        # ============================================================
        # 9. МЕТАДАННЫЕ РЕЗУЛЬТАТА
        # ============================================================
        #
        # Сейчас дополнительные метаданные требуются прежде всего
        # для задержанного результата 99mTc резервной цистерны ZB3.
        #
        # Структура:
        #
        # {
        #     "99mTc": {
        #         "reference_timestamp": ...,
        #         "reference_hour": ...,
        #         "delay_hours": 6,
        #         "algorithm": ...,
        #         "extrapolated": ...,
        #         "ratio": ...
        #     }
        # }
        #
        # Для групп, где таких данных нет, в БД будет сохранён
        # пустой JSON-объект {}.
        # ============================================================

        result_meta = {}

        # ============================================================
        # 10. ТЕКСТОВЫЙ ВЫВОД
        # ============================================================

        output_lines = [
            (
                f"Цистерна №{self.posit_number} "
                f"(група {group}):"
            ),
            (
                f"Фактичний час набору: "
                f"{real_time:.1f} сек"
            )
        ]

        try:
            calculation_time_f = float(
                calculation_time
            )

            real_time_f = float(
                real_time
            )

            if (
                math.isfinite(calculation_time_f)
                and
                math.isfinite(real_time_f)
                and
                abs(
                    calculation_time_f
                    - real_time_f
                ) > 1e-6
            ):
                output_lines.append(
                    f"Розрахунковий T алгоритму: "
                    f"{calculation_time_f:.1f} сек"
                )

        except (TypeError, ValueError):
            pass

        if not measurement_valid:

            invalid_reason = result.get(
                "invalid_reason"
            )

            output_lines.append(
                "  Поточний спектральний цикл "
                "невалідний."
            )

            if invalid_reason:
                output_lines.append(
                    f"  Причина: "
                    f"{invalid_reason}"
                )

        # ============================================================
        # 11. КОДЫ ИЗОТОПОВ ДЛЯ BRIDGE
        # ============================================================

        isotope_code_map = {
            "18F": 3,
            "99mTc": 2,
            "133I": 1,
            "177Lu": 4,
            "90Y": 5
        }

        isotopes_for_bridge = []

        id_counter = 1

        # ============================================================
        # 12. ОБРАБАТЫВАЕМ ИЗОТОПЫ
        # ============================================================

        for name in isotopes_list:

            data = result.get(
                name,
                {}
            )

            if not data:
                id_counter += 1
                continue

            # --------------------------------------------------------
            # 12.1. РЕЗУЛЬТАТ ЕЩЁ НЕ ДОСТУПЕН
            # --------------------------------------------------------

            if data.get(
                "available",
                True
            ) is False:

                reason = data.get(
                    "reason"
                )

                if (
                    name == "99mTc"
                    and
                    group == "reserve"
                ):

                    output_lines.append(
                        "  99mTc: результат "
                        "ще не розрахований"
                    )

                    if reason:
                        output_lines.append(
                            f"    Причина: "
                            f"{reason}"
                        )

                elif (
                    name == "99mTc"
                    and
                    group == "A"
                ):

                    output_lines.append(
                        "  99mTc: результат ще "
                        "не розрахований "
                        "(потрібен наступний "
                        "спектральний цикл)"
                    )

                else:

                    output_lines.append(
                        f"  {name}: "
                        f"результат недоступний"
                    )

                    if reason:
                        output_lines.append(
                            f"    Причина: "
                            f"{reason}"
                        )

                id_counter += 1
                continue

            # ========================================================
            # 12.2. ЦЕНТРАЛЬНЫЕ ЗНАЧЕНИЯ
            # ========================================================

            activity = data.get(
                "activity"
            )

            concentration = data.get(
                "concentration"
            )

            # ========================================================
            # 12.3. ВЕРХНИЕ СТАТИСТИЧЕСКИЕ ГРАНИЦЫ
            # ========================================================

            activity_upper = data.get(
                "activity_upper"
            )

            concentration_upper = data.get(
                "conc_upper"
            )

            detected = data.get(
                "detected",
                "НЕМАЄ"
            )

            sum_clean = data.get(
                "sum_clean"
            )

            # --------------------------------------------------------
            # Центральный результат должен существовать.
            # --------------------------------------------------------

            if (
                activity is None
                or
                concentration is None
            ):

                self.parent_app.ui.textEdit.append(
                    f"Помилка: неповний результат "
                    f"{name} для цистерни "
                    f"№{self.posit_number}."
                )

                id_counter += 1
                continue

            # --------------------------------------------------------
            # Верхние границы также обязательны.
            #
            # Без них нормативное решение ready_to_drain
            # принимать нельзя.
            # --------------------------------------------------------

            if (
                activity_upper is None
                or
                concentration_upper is None
            ):

                self.parent_app.ui.textEdit.append(
                    f"Помилка: відсутні верхні "
                    f"статистичні межі {name} "
                    f"для цистерни "
                    f"№{self.posit_number}."
                )

                id_counter += 1
                continue

            try:
                activity = float(
                    activity
                )

                concentration = float(
                    concentration
                )

                activity_upper = float(
                    activity_upper
                )

                concentration_upper = float(
                    concentration_upper
                )

            except (TypeError, ValueError):

                self.parent_app.ui.textEdit.append(
                    f"Помилка: некоректний "
                    f"числовий результат {name} "
                    f"для цистерни "
                    f"№{self.posit_number}."
                )

                id_counter += 1
                continue

            # --------------------------------------------------------
            # Ни центральные значения, ни верхние границы
            # не могут быть NaN / inf.
            # --------------------------------------------------------

            if (
                not math.isfinite(activity)
                or
                not math.isfinite(concentration)
                or
                not math.isfinite(activity_upper)
                or
                not math.isfinite(
                    concentration_upper
                )
            ):

                self.parent_app.ui.textEdit.append(
                    f"Помилка: NaN/inf у "
                    f"результаті {name} "
                    f"для цистерни "
                    f"№{self.posit_number}."
                )

                id_counter += 1
                continue

            # ========================================================
            # 12.4. ПЛОЩАДЬ — ТОЛЬКО ДИАГНОСТИКА
            # ========================================================

            if sum_clean is not None:

                try:
                    sum_clean = float(
                        sum_clean
                    )

                except (TypeError, ValueError):

                    self.parent_app.ui.textEdit.append(
                        f"Помилка: некоректна "
                        f"площа {name} "
                        f"для цистерни "
                        f"№{self.posit_number}."
                    )

                    id_counter += 1
                    continue

                if not math.isfinite(
                    sum_clean
                ):

                    self.parent_app.ui.textEdit.append(
                        f"Помилка: NaN/inf "
                        f"у площі {name} "
                        f"для цистерни "
                        f"№{self.posit_number}."
                    )

                    id_counter += 1
                    continue

            # ========================================================
            # 12.5. СОХРАНЯЕМ ЦЕНТРАЛЬНЫЕ РЕЗУЛЬТАТЫ
            # ========================================================

            activity_dict[name] = activity
            concentration_dict[name] = concentration

            # ========================================================
            # 12.6. СОХРАНЯЕМ ВЕРХНИЕ ГРАНИЦЫ
            # ========================================================

            activity_upper_dict[name] = activity_upper
            concentration_upper_dict[name] = concentration_upper

            # ========================================================
            # 12.7. ВЫВОД ОПЕРАТОРУ
            # ========================================================

            output_lines.append(
                f"  {name}: "
                f"активність = "
                f"{activity:.2f} Бк, "
                f"концентрація = "
                f"{concentration:.2f} Бк/л, "
                f"статус: {detected}"
            )

            output_lines.append(
                f"    верхня межа: "
                f"A={activity_upper:.2f} Бк, "
                f"C={concentration_upper:.2f} Бк/л"
            )

            # ========================================================
            # 12.8. RESERVE Tc:
            #       ДИАГНОСТИКА + МЕТАДАННЫЕ ДЛЯ БД
            # ========================================================

            if (
                name == "99mTc"
                and
                group == "reserve"
            ):

                reference_hour = data.get(
                    "reference_hour"
                )

                reference_timestamp = data.get(
                    "reference_timestamp"
                )

                ratio = data.get(
                    "ratio"
                )

                algorithm_name = data.get(
                    "algorithm"
                )

                extrapolated = bool(
                    data.get(
                        "extrapolated",
                        False
                    )
                )

                # ----------------------------------------------------
                # Проверяем ratio перед сохранением в JSON.
                #
                # NaN/inf в JSON сохранять нельзя.
                # ----------------------------------------------------

                ratio_for_meta = None

                if ratio is not None:

                    try:
                        ratio_f = float(
                            ratio
                        )

                        if math.isfinite(
                            ratio_f
                        ):
                            ratio_for_meta = ratio_f

                    except (
                        TypeError,
                        ValueError
                    ):
                        pass

                # ----------------------------------------------------
                # reference_hour также приводим к обычному int,
                # если алгоритм его предоставил.
                # ----------------------------------------------------

                reference_hour_for_meta = None

                if reference_hour is not None:

                    try:
                        reference_hour_for_meta = int(
                            reference_hour
                        )

                    except (
                        TypeError,
                        ValueError
                    ):
                        reference_hour_for_meta = None

                # ----------------------------------------------------
                # Для резервного Tc результат относится к измерению
                # шестичасовой давности согласно алгоритму п.15.
                # Поэтому delay_hours фиксируем явно.
                # ----------------------------------------------------

                result_meta["99mTc"] = {
                    "reference_timestamp": (
                        reference_timestamp
                        if reference_timestamp
                        else None
                    ),
                    "reference_hour": (
                        reference_hour_for_meta
                    ),
                    "delay_hours": 6,
                    "algorithm": (
                        algorithm_name
                        if algorithm_name
                        else None
                    ),
                    "extrapolated": extrapolated,
                    "ratio": ratio_for_meta
                }

                # ----------------------------------------------------
                # Существующий диагностический вывод сохраняем.
                # ----------------------------------------------------

                if reference_hour is not None:

                    output_lines.append(
                        f"    Tc результат "
                        f"відноситься до години "
                        f"№{reference_hour}"
                    )

                if reference_timestamp:

                    output_lines.append(
                        f"    Час опорного "
                        f"вимірювання: "
                        f"{reference_timestamp}"
                    )

                if ratio_for_meta is not None:

                    output_lines.append(
                        f"    Tc ratio = "
                        f"{ratio_for_meta:.6f}"
                    )

                if algorithm_name:

                    output_lines.append(
                        f"    Алгоритм Tc: "
                        f"{algorithm_name}"
                    )

                if extrapolated:

                    output_lines.append(
                        "    Tc: використано "
                        "екстраполяцію"
                    )

            # ========================================================
            # 12.9. BRIDGE
            # ========================================================

            code = isotope_code_map.get(
                name,
                0
            )

            if code != 0:

                isotopes_for_bridge.append({
                    "id": id_counter,
                    "name": code,
                    "activity": activity,
                    "concentration": concentration
                })

            id_counter += 1

        # ============================================================
        # 13. ВЫВОД РЕЗУЛЬТАТА
        # ============================================================

        if "background" in result:

            bg_data = result.get(
                "background",
                {}
            )

            if bg_data.get(
                "subtracted",
                False
            ):

                output_lines.append(
                    "  Фон: віднято"
                )

        self.parent_app.ui.textEdit.append(
            "\n".join(
                output_lines
            )
        )

        self.parent_app.ui.textEdit.append(
            "---"
        )

        # ============================================================
        # 14. ЭКСПОРТ СПЕКТРОВ
        # ============================================================

        export_dir = "export"

        os.makedirs(
            export_dir,
            exist_ok=True
        )

        export_total_spectrum = (
            list(self.spectrum_buffer)
            + [real_time]
        )

        with open(
            os.path.join(
                export_dir,
                "spectrum_total.txt"
            ),
            "w"
        ) as f:

            f.write(
                "\n".join(
                    str(x)
                    for x
                    in export_total_spectrum
                )
            )

        components = result.get(
            "components",
            {}
        )

        for name, component_spectrum in (
            components.items()
        ):

            if not isinstance(
                component_spectrum,
                (list, tuple, np.ndarray)
            ):
                continue

            spectrum_with_time_export = (
                list(component_spectrum)
                + [real_time]
            )

            filename = (
                f"spectrum_{name}.txt"
            )

            with open(
                os.path.join(
                    export_dir,
                    filename
                ),
                "w"
            ) as f:

                f.write(
                    "\n".join(
                        str(int(x))
                        for x
                        in spectrum_with_time_export
                    )
                )

        # ============================================================
        # 15. READY_TO_DRAIN
        # ============================================================
        #
        # ВАЖНО:
        # ready_to_drain теперь рассчитывается ДО записи результата
        # в БД, потому что само решение также является частью
        # исторического результата измерения.
        # ============================================================

        tc_available = True

        if group in (
            "A",
            "reserve"
        ):

            tc_data = result.get(
                "99mTc",
                {}
            )

            tc_available = (
                bool(tc_data)
                and
                tc_data.get(
                    "available",
                    True
                )
                is True
            )

        # ------------------------------------------------------------
        # Невалидный полный цикл:
        # слив запрещён независимо от остальных результатов.
        # ------------------------------------------------------------

        if not measurement_valid:

            ready_to_drain = 0

        # ------------------------------------------------------------
        # Для группы A и резервной группы окончательный Tc
        # является обязательным.
        # ------------------------------------------------------------

        elif (
            group in (
                "A",
                "reserve"
            )
            and
            not tc_available
        ):

            ready_to_drain = 0

        else:

            # --------------------------------------------------------
            # Решение принимается по ВЕРХНИМ статистическим границам.
            # --------------------------------------------------------

            ready_to_drain = (
                self.parent_app._calculate_ready_to_drain(
                    self.posit_number,
                    activity_upper_dict,
                    concentration_upper_dict
                )
            )

        # ============================================================
        # 16. СОХРАНЕНИЕ ПОЛНОГО СПЕКТРАЛЬНОГО РЕЗУЛЬТАТА В БД
        # ============================================================
        #
        # Здесь сохраняем одновременно:
        #
        #   центральные значения;
        #   верхние статистические границы;
        #   метаданные;
        #   ready_to_drain;
        #   measurement_valid.
        #
        # Таким образом одна строка БД полностью описывает решение,
        # принятое системой по завершённому спектральному циклу.
        # ============================================================

        if (
            activity_dict
            or
            concentration_dict
        ):

            activity_json = json.dumps(
                activity_dict,
                ensure_ascii=False
            )

            concentration_json = json.dumps(
                concentration_dict,
                ensure_ascii=False
            )

            activity_upper_json = json.dumps(
                activity_upper_dict,
                ensure_ascii=False
            )

            concentration_upper_json = json.dumps(
                concentration_upper_dict,
                ensure_ascii=False
            )

            result_meta_json = json.dumps(
                result_meta,
                ensure_ascii=False
            )

            device_id = (
                self.parent_app.db_manager.get_device_id(
                    self.serial_number
                )
            )

            if device_id is not None:

                fullness_status = (
                    "full"
                    if getattr(
                        self,
                        "is_full",
                        False
                    )
                    else "empty"
                )

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
                    group=group,
                    activity_upper_json=activity_upper_json,
                    concentration_upper_json=concentration_upper_json,
                    result_meta_json=result_meta_json,
                    ready_to_drain=ready_to_drain,
                    measurement_valid=(
                        1
                        if measurement_valid
                        else 0
                    )
                )

                self.parent_app.ui.textEdit.append(
                    f"Цистерна "
                    f"№{self.posit_number}: "
                    f"збережено повний результат у БД "
                    f"(ready_to_drain="
                    f"{ready_to_drain}, "
                    f"measurement_valid="
                    f"{1 if measurement_valid else 0})"
                )

        # ============================================================
        # 17. КОЛИЧЕСТВО ПОЗИЦИЙ BRIDGE
        # ============================================================

        if self.posit_number in (
            1,
            2
        ):

            isotope_count = 2

        elif self.posit_number == 3:

            isotope_count = 5

        else:

            isotope_count = 3

        # ============================================================
        # 18. СТАБИЛЬНЫЙ МАССИВ ИЗОТОПОВ ДЛЯ BRIDGE
        # ============================================================

        isotopes_for_bridge_final = []

        isotope_by_id = {
            item["id"]: item
            for item
            in isotopes_for_bridge
        }

        for i in range(
            1,
            isotope_count + 1
        ):

            if i in isotope_by_id:

                isotopes_for_bridge_final.append(
                    isotope_by_id[i]
                )

            else:

                isotopes_for_bridge_final.append({
                    "id": i,
                    "name": 0,
                    "activity": 0.0,
                    "concentration": 0.0
                })

        # ============================================================
        # 19. ФОРМИРУЕМ ZB ДЛЯ BRIDGE
        # ============================================================

        zb_object = {
            "number": self.posit_number,

            "sn": (
                int(self.serial_number)
                if self.serial_number.isdigit()
                else 0
            ),

            "temperature": (
                self.last_temperature
            ),

            "paed": (
                self.last_paed_from_spectrum
            ),

            "high_sensitivity": (
                1
                if self.last_high_status == 1
                else 0
            ),

            "low_sensitivity": (
                1
                if self.last_low_status == 1
                else 0
            ),

            "valid": (
                1
                if self.last_valid == 1
                else 0
            ),

            "device_connection": 1,

            "ready_to_drain": (
                ready_to_drain
            ),

            "isotopes": (
                isotopes_for_bridge_final
            )
        }

        # ============================================================
        # 20. ОТПРАВЛЯЕМ В BRIDGE
        # ============================================================

        self.parent_app._send_zb_data(
            [zb_object]
        )

        # ============================================================
        # 21. ЗАВЕРШЕНИЕ ЦИКЛА
        # ============================================================
        #
        # ВАЖНО:
        # Старого общего вызова:
        #
        #     db_manager.flush_cistern_buffer()
        #
        # здесь больше НЕТ.
        #
        # save_cistern_measurement() после успешной записи полного
        # результата самостоятельно удаляет из cistern_buffer только
        # старую мониторинговую запись ЭТОЙ цистерны.
        #
        # Буферы остальных цистерн остаются нетронутыми.
        # ============================================================

        self.spectrum_active = False

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
        """
        Инициализация карточки настенного детектора.

        Для температуры хранятся три независимых состояния:

            last_temperature
                Последнее успешно полученное числовое значение.

            temperature_valid
                True  -> последнее температурное измерение успешно;
                False -> актуальная температура сейчас не подтверждена.

            last_temperature_timestamp
                Время последнего УСПЕШНОГО получения температуры.

        ВАЖНО:

        Ошибка очередного температурного измерения в дальнейшем
        будет устанавливать:

            temperature_valid = False

        но НЕ будет уничтожать last_temperature и
        last_temperature_timestamp.

        Благодаря этому в БД можно отличить:

            "температура действительно равна 0"

        от:

            "температура ещё ни разу не была получена"

        и от:

            "имеется старое известное значение, но новое измерение
            температуры завершилось ошибкой".
        """

        # ============================================================
        # 1. БАЗОВАЯ ИНИЦИАЛИЗАЦИЯ QWidget
        # ============================================================

        super().__init__()

        self.parent_app = parent_app

        # ============================================================
        # 2. ЗАГРУЗКА UI
        # ============================================================

        loader = QUiLoader()

        ui_file = QFile(
            "_UI/dashboardwall.ui"
        )

        ui_file.open(
            QFile.ReadOnly
        )

        self.ui = loader.load(
            ui_file
        )

        ui_file.close()

        if self.ui is None:
            raise RuntimeError(
                "Не удалось загрузить dashboardwall.ui"
            )

        # ============================================================
        # 3. РАЗМЕЩЕНИЕ UI В КАРТОЧКЕ
        # ============================================================

        self.setLayout(
            QVBoxLayout()
        )

        self.layout().setContentsMargins(
            5,
            5,
            5,
            5
        )

        self.layout().addWidget(
            self.ui
        )

        # ============================================================
        # 4. ИКОНКИ
        # ============================================================

        self.set_wall_icon()
        self.set_dose_icon()
        self.set_temp_icon()

        # ============================================================
        # 5. СОСТОЯНИЕ ТЕМПЕРАТУРЫ
        # ============================================================
        #
        # 0.0 здесь остаётся только техническим начальным числовым
        # значением для совместимости существующего кода.
        #
        # Оно НЕ означает, что прибор действительно измерил 0 °C.
        #
        # Истинный смысл определяется temperature_valid.
        # ============================================================

        self.last_temperature = 0.0

        # ------------------------------------------------------------
        # До первого успешного температурного ответа актуальной
        # температуры у нас нет.
        # ------------------------------------------------------------

        self.temperature_valid = False

        # ------------------------------------------------------------
        # До первого успешного измерения отсутствует и время,
        # когда температура была реально получена.
        # ------------------------------------------------------------

        self.last_temperature_timestamp = None


 
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

    # Сигнал завершения одного полного цикла накопления спектра.
    #
    # Необходим для сброса DeviceInfo.spectrum_active,
    # который находится в потоке DeviceManager.
    spectrum_cycle_finished = Signal(str)


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


        # ------------------------------------------------------------
        # ДЛИТЕЛЬНОСТЬ ОДНОГО ПОЛНОГО СПЕКТРАЛЬНОГО ЦИКЛА
        # ------------------------------------------------------------
        #
        # Значение по умолчанию — 3600 секунд (1 час).
        #
        # Пользователь может изменить его через диалог интервалов.
        # Новое значение применяется сразу, в том числе к уже
        # выполняющемуся спектральному циклу.
        self.spectrum_accumulation_time = 3600

        # ------------------------------------------------------------
        # НОВЫЕ АТРИБУТЫ ДЛЯ ИНТЕРВАЛОВ СОХРАНЕНИЯ В БД
        # ------------------------------------------------------------
        self.cistern_save_interval = 3600   # секунды (по умолчанию 1 час)
        self.wall_save_interval = 1800      # секунды (по умолчанию 30 минут)

        # Устанавливаем интервалы в DatabaseManager
        self.db_manager.set_cistern_save_interval(self.cistern_save_interval)
        self.db_manager.set_wall_save_interval(self.wall_save_interval)

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

        # ============================================================
        # КОНСТАНТИ ДЛЯ РОЗРАХУНКУ ready_to_drain (Закон 1320)
        # ============================================================
        # Група A (18F, 99mTc)
        self.READY_TO_DRAIN_A_F_ACTIVITY_LIMIT = 1_000_000       # Бк
        self.READY_TO_DRAIN_A_F_CONCENTRATION_LIMIT = 10_000     # Бк/л
        self.READY_TO_DRAIN_A_TC_ACTIVITY_LIMIT = 10_000_000     # Бк
        self.READY_TO_DRAIN_A_TC_CONCENTRATION_LIMIT = 100_000   # Бк/л

        # Група B (133I, 177Lu, 90Y)
        self.READY_TO_DRAIN_B_I_ACTIVITY_LIMIT = 1_000_000       # Бк
        self.READY_TO_DRAIN_B_I_CONCENTRATION_LIMIT = 100_000    # Бк/л
        self.READY_TO_DRAIN_B_LU_ACTIVITY_LIMIT = 10_000_000     # Бк
        self.READY_TO_DRAIN_B_LU_CONCENTRATION_LIMIT = 1_000_000 # Бк/л
        self.READY_TO_DRAIN_B_Y_ACTIVITY_LIMIT = 100_000         # Бк
        self.READY_TO_DRAIN_B_Y_CONCENTRATION_LIMIT = 1_000_000  # Бк/л

        # Нижня та верхня межі для суми активностей (обидві групи)
        self.READY_TO_DRAIN_ACTIVITY_SUM_MIN = 1000
        self.READY_TO_DRAIN_ACTIVITY_SUM_MAX = 10000

        # Атрибут для хранения процесса C++ диспетчера
        self.bridge_process = None

        # --------------------------------------------------------------------
        # Екземпляр ModBusBridgeClient для зв'язку з C++ диспетчером
        # --------------------------------------------------------------------        
        self.modbus_client = ModBusBridgeClient(
            host="127.0.0.1",
            port=12345,
            parent=self
        )

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
        Розмітка контейнерів для карток приладів та налаштування елементів керування ПЛК.
        """
        self.barrel_container = self.ui.findChild(QWidget, "containerBarrel")
        self.wall_container = self.ui.findChild(QWidget, "containerWall")

        self.plc_ip_edit = self.ui.findChild(QLineEdit, "lineEdit")          # поле IP
        self.plc_port_spin = self.ui.findChild(QSpinBox, "spinBox")          # поле порта
        self.btn_connect_plc = self.ui.findChild(QPushButton, "btn_connect_plc")  # кнопка
        self.indicator_plc = self.ui.findChild(QLabel, "indicator_plc")      # индикатор PLC
        self.indicator_bridge = self.ui.findChild(QLabel, "indicator_bridge") # индикатор Bridge

        # --------------------------------------------------------------------
        # 1. ВАЛІДАЦІЯ IP-АДРЕСИ
        # --------------------------------------------------------------------
        # Встановлюємо регулярний вираз для перевірки IPv4-адреси.
        # Вираз перевіряє чотири октети, кожен від 0 до 255.
        # Дозволені значення: 0.0.0.0 ... 255.255.255.255
        #
        # Пояснення частин регулярного виразу:
        #   25[0-5]       -> 250-255
        #   2[0-4][0-9]   -> 200-249
        #   [01]?[0-9][0-9]? -> 0-199 (з можливим ведучим нулем)
        #   \.            -> крапка-роздільник
        #   {3}           -> рівно три повторення (для перших трьох октетів)
        #   $             -> кінець рядка (щоб не пропускати зайві символи)
        # --------------------------------------------------------------------
        ip_regex = QRegularExpression(
            r'^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
        )
        
        # Створюємо валідатор на основі регулярного виразу
        validator = QRegularExpressionValidator(ip_regex, self.plc_ip_edit)
        
        # Встановлюємо валідатор на поле введення IP
        self.plc_ip_edit.setValidator(validator)
        
        # Встановлюємо підказку (placeholder text) для поля IP
        self.plc_ip_edit.setPlaceholderText("192.168.1.50")

        # --------------------------------------------------------------------
        # 2. НАЛАШТУВАННЯ ПОЛЯ ПОРТУ
        # --------------------------------------------------------------------
        # Встановлюємо значення порту за замовчуванням (502 — стандартний порт ModBus TCP)
        self.plc_port_spin.setValue(502)

        # --------------------------------------------------------------------
        # 3. НАЛАШТУВАННЯ ІНДИКАТОРІВ (початковий стан — червоний, немає підключень)
        # --------------------------------------------------------------------
        self.update_plc_indicators(plc_connected=False, bridge_connected=False)

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


    def start_bridge(self, plc_ip: str, plc_port: int) -> bool:
        """
        Запускає ModBusBridgeService.exe через QProcess.
        
        Вхід:
            plc_ip - IP-адреса ПЛК (рядок)
            plc_port - порт ПЛК (int)
        
        Вихід:
            True - якщо процес успішно запущено
            False - якщо сталася помилка
        """
        # --------------------------------------------------------------------
        # 1. Якщо процес вже запущений — не створюємо новий
        # --------------------------------------------------------------------
        if self.bridge_process is not None:
            state = self.bridge_process.state()
            if state == QProcess.ProcessState.Running or state == QProcess.ProcessState.Starting:
                self.ui.textEdit.append("ModBusBridgeService вже запущений")
                return False
        
        # --------------------------------------------------------------------
        # 2. Перевіряємо наявність виконуваного файлу
        # --------------------------------------------------------------------
        executable = os.path.join("ModBusBridgeService_Runtime", "ModBusBridgeService.exe")
        if not os.path.exists(executable):
            self.ui.textEdit.append(f"Помилка: файл {executable} не знайдено")
            return False
        
        # --------------------------------------------------------------------
        # 3. Формуємо аргументи командного рядка
        # --------------------------------------------------------------------
        args = [str(plc_ip), str(plc_port)]
        
        self.ui.textEdit.append(f"Запуск {executable} з аргументами: {args}")
        
        # --------------------------------------------------------------------
        # 4. Створюємо та налаштовуємо QProcess
        # --------------------------------------------------------------------
        self.bridge_process = QProcess(self)
        self.bridge_process.setProgram(executable)
        self.bridge_process.setArguments(args)
        
        # --------------------------------------------------------------------
        # 5. Підключаємо сигнали
        # --------------------------------------------------------------------
        self.bridge_process.started.connect(self.on_bridge_started)
        self.bridge_process.finished.connect(self.on_bridge_finished)
        self.bridge_process.errorOccurred.connect(self.on_bridge_error)
        self.bridge_process.readyReadStandardOutput.connect(self.on_bridge_stdout)
        self.bridge_process.readyReadStandardError.connect(self.on_bridge_stderr)
        
        # --------------------------------------------------------------------
        # 6. Запускаємо процес
        # --------------------------------------------------------------------
        self.bridge_process.start()
        
        # --------------------------------------------------------------------
        # 7. Чекаємо, поки процес запуститься (неблокуюче очікування)
        # --------------------------------------------------------------------
        if not self.bridge_process.waitForStarted(3000):
            self.ui.textEdit.append("Помилка: не вдалося запустити ModBusBridgeService")
            self.bridge_process = None
            return False
        
        self.ui.textEdit.append("ModBusBridgeService успішно запущено")
        return True


    def stop_bridge(self):
        """
        Зупиняє ModBusBridgeService.exe.
        """
        if self.bridge_process is None:
            return
        
        state = self.bridge_process.state()
        if state == QProcess.ProcessState.NotRunning:
            self.ui.textEdit.append("ModBusBridgeService вже зупинено")
            self.bridge_process = None
            return
        
        self.ui.textEdit.append("Зупинка ModBusBridgeService...")
        
        # Відправляємо сигнал завершення
        self.bridge_process.terminate()
        
        # Чекаємо 3 секунди
        if not self.bridge_process.waitForFinished(3000):
            # Якщо не завершився — примусово завершуємо
            self.ui.textEdit.append("Примусове завершення ModBusBridgeService")
            self.bridge_process.kill()
            self.bridge_process.waitForFinished(1000)
        
        self.ui.textEdit.append("ModBusBridgeService зупинено")
        self.bridge_process = None


    def on_bridge_started(self):
        """
        Обробник сигналу started — процес C++ запущено.
        """
        self.ui.textEdit.append("[Bridge] Процес запущено")


    def on_bridge_finished(self, exit_code, exit_status):
        """
        Обробник сигналу finished — процес C++ завершився.
        """
        status_text = "нормально" if exit_status == QProcess.ExitStatus.NormalExit else "аварійно"
        self.ui.textEdit.append(f"[Bridge] Процес завершено з кодом {exit_code} ({status_text})")
        
        # Оновлюємо індикатори
        self.update_plc_indicators(plc_connected=False, bridge_connected=False)
        
        self.bridge_process = None


    def on_bridge_error(self, error):
        """
        Обробник сигналу errorOccurred — помилка процесу C++.
        """
        error_map = {
            QProcess.ProcessError.FailedToStart: "Не вдалося запустити процес",
            QProcess.ProcessError.Crashed: "Процес аварійно завершився",
            QProcess.ProcessError.Timedout: "Таймаут під час очікування",
            QProcess.ProcessError.WriteError: "Помилка запису в процес",
            QProcess.ProcessError.ReadError: "Помилка читання з процесу",
            QProcess.ProcessError.UnknownError: "Невідома помилка"
        }
        error_text = error_map.get(error, f"Помилка: {error}")
        self.ui.textEdit.append(f"[Bridge] {error_text}")
        self.update_plc_indicators(plc_connected=False, bridge_connected=False)
        self.bridge_process = None


    def on_bridge_stdout(self):
        """
        Обробник сигналу readyReadStandardOutput — вивід stdout від C++.
        """
        if self.bridge_process is None:
            return
        data = self.bridge_process.readAllStandardOutput()
        text = data.data().decode('utf-8', errors='replace').strip()
        if text:
            self.ui.textEdit.append(f"[Bridge stdout] {text}")


    def on_bridge_stderr(self):
        """
        Обробник сигналу readyReadStandardError — вивід stderr від C++.
        """
        if self.bridge_process is None:
            return
        data = self.bridge_process.readAllStandardError()
        text = data.data().decode('utf-8', errors='replace').strip()
        if text:
            self.ui.textEdit.append(f"[Bridge stderr] {text}")



    def update_plc_indicators(self, plc_connected: bool, bridge_connected: bool):
        """
        Оновлює кольорові індикатори стану підключення до ПЛК та Bridge.
        
        Вхід:
            plc_connected   - True, якщо C++ підключений до ПЛК
            bridge_connected - True, якщо Python підключений до C++ (локальний сокет)
        """
        # --------------------------------------------------------------------
        # Індикатор PLC (підключення C++ → ПЛК)
        # --------------------------------------------------------------------
        if plc_connected:
            self.indicator_plc.setStyleSheet(
                "background-color: #4CAF50; border-radius: 5px; min-width: 16px; min-height: 16px;"
            )
            self.indicator_plc.setToolTip("PLC підключено")
        else:
            self.indicator_plc.setStyleSheet(
                "background-color: #f44336; border-radius: 5px; min-width: 16px; min-height: 16px;"
            )
            self.indicator_plc.setToolTip("PLC не підключено")

        # --------------------------------------------------------------------
        # Індикатор Bridge (підключення Python → C++)
        # --------------------------------------------------------------------
        if bridge_connected:
            self.indicator_bridge.setStyleSheet(
                "background-color: #4CAF50; border-radius: 5px; min-width: 16px; min-height: 16px;"
            )
            self.indicator_bridge.setToolTip("З'єднання з Bridge встановлено")
        else:
            self.indicator_bridge.setStyleSheet(
                "background-color: #f44336; border-radius: 5px; min-width: 16px; min-height: 16px;"
            )
            self.indicator_bridge.setToolTip("З'єднання з Bridge відсутнє")



    def on_open_intervals(self):
        """
        Відкриває діалог налаштування інтервалів.

        Якщо оператор змінює тривалість спектрального циклу,
        історія динамічного алгоритму Tc скидається.

        Причина:
        K_F та K_Tc за алгоритмом обчислюються за T першого циклу
        і надалі є константними. Після зміни T стара історія
        математично більше не відповідає новому циклу.

        Після зміни інтервалу наступний завершений спектральний
        результат для групи A буде розглядатися як нова
        "перша година" Tc.
        """

        from dialogs.intervals_dialog import IntervalsDialog

        dialog = IntervalsDialog(self)

        if dialog.exec() == QDialog.Accepted:

            # ========================================================
            # 1. ЗБЕРІГАЄМО СТАРЕ ЗНАЧЕННЯ ЧАСУ СПЕКТРА
            # ========================================================

            old_spectrum_time = getattr(
                self,
                "spectrum_accumulation_time",
                3600
            )

            # ========================================================
            # 2. ОТРИМУЄМО НОВІ ЗНАЧЕННЯ
            # ========================================================

            new_spectrum_time = dialog.get_spectrum_time()

            self.spectrum_accumulation_time = new_spectrum_time
            self.db_write_interval = dialog.get_db_interval()
            self.zb_send_interval = dialog.get_zb_interval()
            self.cz_send_interval = dialog.get_cz_interval()

            self.cistern_save_interval = (
                dialog.get_cistern_save_interval()
            )

            self.wall_save_interval = (
                dialog.get_wall_save_interval()
            )

            # ========================================================
            # 3. ЯКЩО T ЗМІНИВСЯ — СКИДАЄМО ІСТОРІЮ Tc
            # ========================================================
            #
            # Сам поточний спектральний цикл тут НЕ скидаємо.
            #
            # За погодженою логікою новий spectrum_accumulation_time
            # застосовується до поточного циклу одразу.
            #
            # Але його результат уже стане новим першим циклом
            # для динамічної історії Tc.

            spectrum_time_changed = (
                new_spectrum_time != old_spectrum_time
            )

            if spectrum_time_changed:

                reset_count = 0

                for card in self.cards_by_sn.values():

                    if not isinstance(
                        card,
                        DeviceCardBarrel
                    ):
                        continue

                    card.clear_history()
                    reset_count += 1

                self.ui.textEdit.append(
                    "Змінено час накопичення спектру: "
                    "історію динамічного розрахунку Tc "
                    f"скинуто для {reset_count} цистерн."
                )

            # ========================================================
            # 4. ЗАСТОСОВУЄМО ІНТЕРВАЛИ ДО БД
            # ========================================================

            if hasattr(self, "db_manager"):
                self.db_manager.set_cistern_save_interval(
                    self.cistern_save_interval
                )

                self.db_manager.set_wall_save_interval(
                    self.wall_save_interval
                )

            # ========================================================
            # 5. ЛОГ
            # ========================================================

            self.ui.textEdit.append(
                f"Налаштування інтервалів збережено: "
                f"спектр={self.spectrum_accumulation_time}с, "
                f"ZB={self.zb_send_interval}с, "
                f"CZ={self.cz_send_interval}с, "
                f"БД={self.db_write_interval}хв, "
                f"збереження цистерн="
                f"{self.cistern_save_interval}с, "
                f"збереження приміщення="
                f"{self.wall_save_interval}с"
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

        # --------------------------------------------------------------------
        # Сигналы ModBusBridgeClient
        # --------------------------------------------------------------------
        if hasattr(self, 'modbus_client') and self.modbus_client is not None:
            self.modbus_client.connected.connect(self.on_bridge_connected)
            self.modbus_client.disconnected.connect(self.on_bridge_disconnected)
            self.modbus_client.dataReceived.connect(self.on_bridge_data_received)
            self.modbus_client.errorOccurred.connect(self.on_bridge_error_message)
            self.modbus_client.logMessage.connect(self.on_bridge_log_message)
        else:
            self.ui.textEdit.append("Увага: ModBusBridgeClient не створено")


        self.spectrum_cycle_finished.connect(self.device_manager.finish_spectrum_cycle, Qt.ConnectionType.QueuedConnection )





    def on_connect_plc_clicked(self):
        """
        Обробник натискання кнопки «Підключитися до ПЛК».
        Перевіряє IP, запускає C++ процес і підключається до Bridge.
        """
        ip = self.plc_ip_edit.text().strip()
        port = self.plc_port_spin.value()
        
        # --------------------------------------------------------------------
        # Перевірка IP за допомогою QHostAddress
        # --------------------------------------------------------------------
        if not ip:
            self.ui.textEdit.append("Помилка: IP-адреса не може бути порожньою")
            return
        
        host = QHostAddress(ip)
        if host.protocol() != QHostAddress.IPv4Protocol:
            self.ui.textEdit.append(f"Помилка: '{ip}' не є коректною IPv4-адресою")
            return
        
        self.ui.textEdit.append(f"Підключення до ПЛК {ip}:{port}")
        
        # --------------------------------------------------------------------
        # Запускаємо C++ процес
        # --------------------------------------------------------------------
        if not self.start_bridge(ip, port):
            return
        
        # --------------------------------------------------------------------
        # Підключаємося до Bridge через локальний сокет
        # --------------------------------------------------------------------
        self.ui.textEdit.append("[Bridge] Спроба підключення до Bridge...")
        
        # Робимо до 3 спроб з інтервалом 1 секунда
        max_attempts = 3
        attempt = 0
        connected = False
        
        while attempt < max_attempts:
            attempt += 1
            self.ui.textEdit.append(f"[Bridge] Спроба {attempt} з {max_attempts}...")
            
            # Викликаємо підключення
            if self.modbus_client.connect_to_bridge():
                connected = True
                break
            
            # Якщо не вдалося — чекаємо 1 секунду перед наступною спробою
            if attempt < max_attempts:
                import time
                time.sleep(1)
        
        if connected:
            self.ui.textEdit.append("[Bridge] Підключення до Bridge успішне")
            # Індикатор bridge оновиться через сигнал connected
        else:
            self.ui.textEdit.append(
                f"[Bridge] Не вдалося підключитися до Bridge після {max_attempts} спроб"
            )
            # Індикатор bridge залишиться червоним (disconnected)



    def on_bridge_connected(self):
        """
        Обробник сигналу connected — підключення до Bridge встановлено.
        """
        self.ui.textEdit.append("[Bridge] З'єднання з Bridge встановлено")
        # При подключении к Bridge считаем, что PLC также доступен (C++ уже подключился или подключится)
        self.update_plc_indicators(plc_connected=True, bridge_connected=True)

    def on_bridge_disconnected(self):
        """
        Обробник сигналу disconnected — з'єднання з Bridge втрачено.
        """
        self.ui.textEdit.append("[Bridge] З'єднання з Bridge втрачено")
        self.update_plc_indicators(plc_connected=False, bridge_connected=False)




    def on_bridge_data_received(self, data):
        """
        Обрабатывает JSON-сообщения, полученные от C++ ModBusBridgeService.

        Для сообщений type == "read" принимается состояние заполненности
        цистерн ZB1...ZB9:

            {
                "type": "read",
                "data": {
                    "zb": [
                        {"number": 1, "fullness": 0},
                        {"number": 2, "fullness": 1}
                    ]
                }
            }

        Основные задачи:

            1. Проверить структуру входящего сообщения.
            2. Проверить номер ZB и fullness.
            3. Обновить только действительно изменившиеся состояния.
            4. Атомарно сохранить новое состояние в cistern.json.
            5. Синхронизировать GUI.
            6. Передать снимок состояния в DeviceManager.

        Ошибка одной записи ZB не должна прерывать обработку остальных.
        """

        try:
            # ============================================================
            # 1. ПРОВЕРЯЕМ КОРНЕВОЙ ОБЪЕКТ
            # ============================================================

            if not isinstance(data, dict):

                self.ui.textEdit.append(
                    "[Bridge] Помилка: отримано повідомлення "
                    "некоректного формату."
                )

                return

            # ============================================================
            # 2. ОПРЕДЕЛЯЕМ ТИП СООБЩЕНИЯ
            # ============================================================

            msg_type = data.get(
                "type",
                "unknown"
            )

            # ============================================================
            # 3. ДЛЯ П.9 НАС ИНТЕРЕСУЕТ ТОЛЬКО READ
            # ============================================================

            if msg_type != "read":

                if self.bridge_debug_mode:

                    self.ui.textEdit.append(
                        (
                            "[Bridge] Отримано повідомлення "
                            f"типу '{msg_type}'"
                        )
                    )

                return

            # ============================================================
            # 4. ПРОВЕРЯЕМ DATA
            # ============================================================

            message_data = data.get(
                "data"
            )

            if not isinstance(
                message_data,
                dict
            ):

                self.ui.textEdit.append(
                    "[Bridge] Помилка: поле 'data' "
                    "має некоректний формат."
                )

                return

            # ============================================================
            # 5. ПОЛУЧАЕМ СПИСОК СОСТОЯНИЙ ZB
            # ============================================================

            zb_list = message_data.get(
                "zb"
            )

            if zb_list is None:

                # В сообщении read может не быть данных ZB.
                # Это не обязательно является ошибкой самого Bridge.
                return

            if not isinstance(
                zb_list,
                list
            ):

                self.ui.textEdit.append(
                    "[Bridge] Помилка: поле 'zb' "
                    "не є списком."
                )

                return

            if not zb_list:
                return

            # ============================================================
            # 6. СОБИРАЕМ КОРРЕКТНЫЕ ОБНОВЛЕНИЯ
            # ============================================================
            #
            # Сначала полностью проверяем входной список.
            # Только после этого меняем self.cistern_dict.

            validated_states = {}

            # Запоминаем номера, которые уже встретились.
            # Это защищает от неоднозначного сообщения:
            #
            #     ZB1 = 0
            #     ZB1 = 1

            duplicate_numbers = set()

            for zb in zb_list:

                # --------------------------------------------------------
                # Каждый элемент обязан быть объектом
                # --------------------------------------------------------

                if not isinstance(
                    zb,
                    dict
                ):

                    self.ui.textEdit.append(
                        (
                            "[Bridge] Помилка: некоректний "
                            f"елемент ZB: {zb}"
                        )
                    )

                    continue

                number = zb.get(
                    "number"
                )

                fullness = zb.get(
                    "fullness"
                )

                # --------------------------------------------------------
                # Проверяем наличие обязательных полей
                # --------------------------------------------------------

                if (
                    number is None
                    or fullness is None
                ):

                    self.ui.textEdit.append(
                        (
                            "[Bridge] Помилка: неповні дані "
                            f"для цистерни: {zb}"
                        )
                    )

                    continue

                # --------------------------------------------------------
                # Номер ZB должен быть именно целым числом
                # --------------------------------------------------------
                #
                # Используем type(...) is int специально:
                # bool в Python является подклассом int,
                # но True/False не должны считаться номерами цистерн.

                if type(number) is not int:

                    self.ui.textEdit.append(
                        (
                            "[Bridge] Помилка: некоректний "
                            f"номер цистерни '{number}'."
                        )
                    )

                    continue

                # --------------------------------------------------------
                # Допустимы только ZB1...ZB9
                # --------------------------------------------------------

                if number < 1 or number > 9:

                    self.ui.textEdit.append(
                        (
                            "[Bridge] Помилка: невірний "
                            f"номер цистерни {number}."
                        )
                    )

                    continue

                # --------------------------------------------------------
                # Fullness по протоколу должен быть 0 или 1
                # --------------------------------------------------------

                if (
                    type(fullness) is not int
                    or fullness not in (0, 1)
                ):

                    self.ui.textEdit.append(
                        (
                            "[Bridge] Помилка: невірне "
                            f"значення fullness={fullness} "
                            f"для ZB{number}."
                        )
                    )

                    continue

                # --------------------------------------------------------
                # Проверяем дубли одной ZB в одном сообщении
                # --------------------------------------------------------

                if number in validated_states:

                    duplicate_numbers.add(
                        number
                    )

                    continue

                validated_states[
                    number
                ] = bool(
                    fullness
                )

            # ============================================================
            # 7. ИСКЛЮЧАЕМ НЕОДНОЗНАЧНЫЕ ДУБЛИ
            # ============================================================

            for number in duplicate_numbers:

                validated_states.pop(
                    number,
                    None
                )

                self.ui.textEdit.append(
                    (
                        "[Bridge] Помилка: ZB"
                        f"{number} повторюється "
                        "в одному повідомленні. "
                        "Стан проігноровано."
                    )
                )

            # Если корректных данных нет — менять состояние нельзя.
            if not validated_states:
                return

            # ============================================================
            # 8. ОБНОВЛЯЕМ ТОЛЬКО ИЗМЕНИВШИЕСЯ ZB
            # ============================================================

            updated = False

            for number, new_fullness in validated_states.items():

                old_fullness = bool(
                    self.cistern_dict.get(
                        number,
                        False
                    )
                )

                if old_fullness == new_fullness:
                    continue

                self.cistern_dict[
                    number
                ] = new_fullness

                updated = True

            # ============================================================
            # 9. ЕСЛИ НИЧЕГО НЕ ИЗМЕНИЛОСЬ
            # ============================================================

            if not updated:
                return

            # ============================================================
            # 10. АТОМАРНО СОХРАНЯЕМ cistern.json
            # ============================================================
            #
            # Fullness является состоянием технологического процесса.
            #
            # После перезапуска приложения нельзя возвращаться
            # к старому значению только потому, что последнее изменение
            # существовало исключительно в оперативной памяти.
            #
            # Используем:
            #
            #     write -> flush -> fsync -> os.replace
            #
            # чтобы не получить частично записанный JSON при сбое.

            cistern_path = os.path.abspath(
                os.path.join(
                    "config",
                    "cistern.json"
                )
            )

            temp_path = (
                cistern_path
                + ".tmp"
            )

            try:
                export_data = {}

                for position in range(
                    1,
                    10
                ):

                    export_data[
                        str(position)
                    ] = {
                        "full": bool(
                            self.cistern_dict.get(
                                position,
                                False
                            )
                        ),

                        "isotopes": list(
                            self.cistern_isotopes.get(
                                position,
                                []
                            )
                        ),

                        "group": self.cistern_groups.get(
                            position,
                            (
                                "A"
                                if position in (1, 2)
                                else
                                "reserve"
                                if position == 3
                                else
                                "B"
                            )
                        )
                    }

                with open(
                    temp_path,
                    "w",
                    encoding="utf-8"
                ) as file:

                    json.dump(
                        export_data,
                        file,
                        ensure_ascii=False,
                        indent=4
                    )

                    file.flush()

                    os.fsync(
                        file.fileno()
                    )

                os.replace(
                    temp_path,
                    cistern_path
                )

            except OSError as e:

                self.ui.textEdit.append(
                    (
                        "[Bridge] Помилка збереження "
                        f"стану цистерн: {e}"
                    )
                )

                # Не откатываем self.cistern_dict.
                #
                # PLC сообщил актуальное физическое состояние,
                # поэтому оперативная работа должна продолжаться
                # с ним даже при ошибке сохранения файла.

                try:
                    if os.path.exists(
                        temp_path
                    ):
                        os.remove(
                            temp_path
                        )

                except OSError:
                    pass

            # ============================================================
            # 11. ОБНОВЛЯЕМ GUI
            # ============================================================

            self.sync_devices_with_cisterns()

            # ============================================================
            # 12. ПЕРЕДАЁМ СОСТОЯНИЕ В DeviceManager
            # ============================================================
            #
            # Передаём отдельный снимок словаря.
            # GUI-поток не должен изменять объект после отправки
            # queued-сигнала в поток DeviceManager.

            self.sync_cisterns_to_manager.emit(
                self.cistern_dict.copy()
            )

        # ================================================================
        # 13. ЗАЩИТА ОБРАБОТЧИКА BRIDGE
        # ================================================================

        except Exception as e:

            self.ui.textEdit.append(
                (
                    "[Bridge] Помилка при обробці "
                    f"даних: {e}"
                )
            )



    def on_bridge_error_message(self, message):
        """
        Обробник сигналу errorOccurred — помилка від Bridge.
        
        Вхід:
            message - str текст помилки
        """
        self.ui.textEdit.append(f"[Bridge ERROR] {message}")


    def on_bridge_log_message(self, message):
        """
        Обробник сигналу logMessage — діагностичне повідомлення від Bridge.
        
        Вхід:
            message - str текст повідомлення
        """
        self.ui.textEdit.append(f"[Bridge] {message}")



    def load_calibration_spectra(self):
        """
        Завантажує еталонні спектри з папки calibration/.

        Кожен calibration-файл повинен містити РІВНО 1024 числових
        значення в одному стовпці. Перші 1023 значення є спектральними
        даними, 1024-е значення зберігається як службове значення часу.

        Пошкоджений або неповний файл НЕ доповнюється нулями і НЕ
        обрізається. Такий файл не додається до calibration_spectra,
        щоб алгоритм не виконувався з тихо спотвореною калібровкою.
        """

        self.calibration_spectra = {}
        calib_dir = "calibration"

        if not os.path.isdir(calib_dir):
            self.ui.textEdit.append("Помилка: папка calibration/ не знайдена")
            return

        # Сортування робить порядок повідомлень відтворюваним.
        for filename in sorted(os.listdir(calib_dir)):
            if not filename.lower().endswith(".txt"):
                continue

            filepath = os.path.join(calib_dir, filename)

            try:
                data = np.loadtxt(filepath, dtype=float)

                # За вимогами файл повинен бути одним стовпцем із
                # рівно 1024 значень. Багатовимірну структуру також
                # вважаємо помилкою формату.
                if data.ndim != 1:
                    raise ValueError(
                        f"очікується один стовпець, отримано ndim={data.ndim}"
                    )

                if data.size != 1024:
                    raise ValueError(
                        f"очікується 1024 значення, отримано {data.size}"
                    )

                # NaN/inf не повинні потрапляти в спектральні формули.
                if not np.all(np.isfinite(data)):
                    raise ValueError("файл містить NaN або нескінченні значення")

                name = os.path.splitext(filename)[0]
                self.calibration_spectra[name] = data.copy()

                self.ui.textEdit.append(
                    f"Завантажено еталон: {name}, "
                    f"час набору: {data[1023]} сек"
                )

            except (OSError, ValueError, TypeError) as e:
                self.ui.textEdit.append(
                    f"Помилка завантаження калібрування {filename}: {e}"
                )



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
        Обрабатывает пакет, уже принятый и проверенный DeviceManager.

        Основные режимы:

            RadDose
            Temperature
            StartSpectre
            GetSpectre

        Метод отвечает за:

            - обновление GUI;
            - передачу актуального PAED обратно в DeviceManager;
            - накопление спектра;
            - определение окончания полного спектрального цикла;
            - запись текущих измерений в буферы БД;
            - передачу данных в ModBus Bridge.

        ВАЖНО:

            Для управляющей логики спектра используется только
            актуальный ВАЛИДНЫЙ PAED.

            Если очередной PAED невалиден, в DeviceManager
            передаётся None, чтобы старое значение PAED не могло
            ошибочно разрешить новый StartSpectre.

        Для настенных детекторов CZ дополнительно отслеживается
        актуальность температуры:

            temperature_valid = True
                последнее температурное измерение успешно;

            temperature_valid = False
                последнее температурное измерение завершилось ошибкой
                либо температура ещё ни разу не была получена.

        При ошибке температуры последнее успешно полученное
        числовое значение и его timestamp не уничтожаются.
        """

        # ============================================================
        # 1. ОСНОВНАЯ ИНФОРМАЦИЯ О ПАКЕТЕ
        # ============================================================

        sn = packet.serial_number
        mode = packet.mode
        buff = packet.buff

        # ============================================================
        # 2. ИЩЕМ GUI-КАРТОЧКУ ПРИБОРА
        # ============================================================

        card = self.cards_by_sn.get(sn)

        if card is None:

            self.ui.textEdit.append(
                (
                    "Помилка: не знайдено картку "
                    f"для приладу SN {sn}."
                )
            )

            return

        try:

            # ========================================================
            # RAD DOSE
            # ========================================================

            if mode == "RadDose":

                # ----------------------------------------------------
                # Разбираем пакет ПАЕД
                # ----------------------------------------------------

                data = self.device_manager._paed_data(buff)

                if not data:

                    # Если пакет по какой-либо причине не удалось
                    # разобрать, прежний PAED нельзя оставлять
                    # разрешающим значением для StartSpectre.

                    self.device_manager.update_device_paed.emit(
                        sn,
                        None
                    )

                    return

                dose = data["ped_value"]
                accuracy = data["accuracy"]

                low_failure = data.get(
                    "low_sens_failure",
                    True
                )

                high_failure = data.get(
                    "high_sens_failure",
                    True
                )

                result_valid = data.get(
                    "result_valid",
                    False
                )

                # ----------------------------------------------------
                # GUI
                # ----------------------------------------------------

                card.set_dose_value(
                    dose,
                    accuracy
                )

                card.set_detector_status(
                    low_failure,
                    high_failure,
                    result_valid
                )

                # ----------------------------------------------------
                # УПРАВЛЯЮЩИЙ PAED
                # ----------------------------------------------------

                self.device_manager.update_device_paed.emit(
                    sn,
                    dose if result_valid else None
                )

                # ----------------------------------------------------
                # ИЩЕМ DEVICE_ID
                # ----------------------------------------------------

                device_id = self.db_manager.get_device_id(sn)

                if device_id is None:

                    self.ui.textEdit.append(
                        (
                            "Помилка: прилад "
                            f"{sn} не знайдено в БД."
                        )
                    )

                    return

                # ----------------------------------------------------
                # ПОСЛЕДНЯЯ ИЗВЕСТНАЯ ТЕМПЕРАТУРА
                # ----------------------------------------------------

                temp_value = getattr(
                    card,
                    "last_temperature",
                    0.0
                )

                # ====================================================
                # CZ — ПРИБОР ПОМЕЩЕНИЯ
                # ====================================================

                if card.location_type == "room":

                    # ------------------------------------------------
                    # Для БД дополнительно передаём информацию
                    # о достоверности температуры.
                    # ------------------------------------------------

                    temperature_valid = getattr(
                        card,
                        "temperature_valid",
                        False
                    )

                    temperature_timestamp = getattr(
                        card,
                        "last_temperature_timestamp",
                        None
                    )

                    self.db_manager.buffer_wall_measurement(
                        device_id=device_id,
                        paed=dose,
                        temperature=temp_value,
                        low_status=(
                            1 if low_failure else 0
                        ),
                        high_status=(
                            1 if high_failure else 0
                        ),
                        valid=(
                            1 if result_valid else 0
                        ),
                        temperature_valid=temperature_valid,
                        temperature_timestamp=temperature_timestamp
                    )

                    cz_object = {
                        "number": card.posit_number,
                        "sn": (
                            int(sn)
                            if sn.isdigit()
                            else 0
                        ),
                        "temperature": temp_value,
                        "paed": dose,
                        "high_sensitivity": (
                            1 if high_failure else 0
                        ),
                        "low_sensitivity": (
                            1 if low_failure else 0
                        ),
                        "valid": (
                            1 if result_valid else 0
                        ),
                        "device_connection": 1
                    }

                    self._send_cz_data(
                        [cz_object]
                    )

                # ====================================================
                # ZB — ПРИБОР ЦИСТЕРНЫ
                # ====================================================

                elif card.location_type == "cistern":

                    fullness_status = (
                        "full"
                        if getattr(
                            card,
                            "is_full",
                            False
                        )
                        else "empty"
                    )

                    group = self.cistern_groups.get(
                        card.posit_number,
                        "A"
                    )

                    self.db_manager.buffer_cistern_measurement(
                        device_id=device_id,
                        paed=dose,
                        temperature=temp_value,
                        low_status=(
                            1 if low_failure else 0
                        ),
                        high_status=(
                            1 if high_failure else 0
                        ),
                        valid=(
                            1 if result_valid else 0
                        ),
                        fullness_status=fullness_status,
                        group=group,
                        activity_json="{}",
                        concentration_json="{}",
                        spectrum_active=card.spectrum_active
                    )

                    # ------------------------------------------------
                    # Формируем пустой набор изотопов для текущего
                    # обычного измерения PAED.
                    # ------------------------------------------------

                    if card.posit_number in (1, 2):

                        isotope_count = 2

                    elif card.posit_number == 3:

                        isotope_count = 5

                    else:

                        isotope_count = 3

                    isotopes = []

                    for i in range(
                        1,
                        isotope_count + 1
                    ):

                        isotopes.append(
                            {
                                "id": i,
                                "name": 0,
                                "activity": 0.0,
                                "concentration": 0.0
                            }
                        )

                    zb_object = {
                        "number": card.posit_number,
                        "sn": (
                            int(sn)
                            if sn.isdigit()
                            else 0
                        ),
                        "temperature": temp_value,
                        "paed": dose,
                        "high_sensitivity": (
                            1 if high_failure else 0
                        ),
                        "low_sensitivity": (
                            1 if low_failure else 0
                        ),
                        "valid": (
                            1 if result_valid else 0
                        ),
                        "device_connection": 1,
                        "ready_to_drain": 0,
                        "isotopes": isotopes
                    }

                    self._send_zb_data(
                        [zb_object]
                    )

            # ========================================================
            # TEMPERATURE
            # ========================================================

            elif mode == "Temperature":

                temperature = (
                    self.device_manager._temp_data(buff)
                )

                # ----------------------------------------------------
                # None означает:
                #
                # - некорректные данные;
                # - либо прибор сообщил об отказе термодатчика.
                #
                # Для CZ последнее известное значение НЕ уничтожаем.
                #
                # Но обязательно снимаем признак актуальности,
                # чтобы при следующем RadDose запись в БД содержала:
                #
                #     temperature_valid = 0
                #
                # timestamp последнего успешного измерения при этом
                # остаётся неизменным.
                # ----------------------------------------------------

                if temperature is None:

                    if card.location_type == "room":

                        card.temperature_valid = False

                    self.ui.textEdit.append(
                        (
                            "Помилка температури для "
                            f"SN {sn}: дані недійсні "
                            "або термодатчик повідомив "
                            "про відмову."
                        )
                    )

                    return

                # ----------------------------------------------------
                # Сначала преобразуем значение.
                #
                # Пока преобразование не прошло успешно, значение
                # нельзя считать новым корректным измерением.
                # ----------------------------------------------------

                try:

                    temperature_value = float(
                        temperature
                    )

                except (TypeError, ValueError):

                    # Для CZ не уничтожаем последнее известное
                    # значение температуры, но актуальность снимаем.

                    if card.location_type == "room":

                        card.temperature_valid = False

                    self.ui.textEdit.append(
                        (
                            "Помилка перетворення "
                            "температури для "
                            f"SN {sn}: {temperature}"
                        )
                    )

                    return

                # ----------------------------------------------------
                # Обновляем GUI только после успешного преобразования.
                # ----------------------------------------------------

                card.set_temp_value(
                    temperature
                )

                # ----------------------------------------------------
                # Сохраняем последнее реально полученное значение.
                # ----------------------------------------------------

                card.last_temperature = (
                    temperature_value
                )

                # ----------------------------------------------------
                # Для CZ фиксируем:
                #
                # - успешность текущего температурного измерения;
                # - реальное время его получения.
                #
                # Используем системное локальное время ПК в том же
                # строковом формате, который применяется в БД.
                # ----------------------------------------------------

                if card.location_type == "room":

                    card.temperature_valid = True

                    card.last_temperature_timestamp = (
                        time.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    )

            # ========================================================
            # START SPECTRE
            # ========================================================

            elif mode == "StartSpectre":

                # Сам факт попадания сюда означает, что
                # DeviceManager уже получил и проверил
                # успешный ответ StartSpectre.
                #
                # Именно в этот момент фиксируем начало полного
                # спектрального цикла по монотонным часам ПК.
                # Время отправки команды не используется, потому что
                # StartSpectre мог завершиться таймаутом или ошибкой.

                card.spectrum_start_monotonic = (
                    time.monotonic()
                )

                # Фактическое время завершённого цикла будет записано
                # только при получении первого успешного GetSpectre
                # после достижения заданного времени накопления.

                card.spectrum_elapsed_time = 0.0

                # Локальный флаг карточки синхронизируем с фактом
                # успешного запуска спектрального накопления.

                card.spectrum_active = True

                self.ui.textEdit.append(
                    (
                        "Початок збору спектру "
                        f"для SN {sn}."
                    )
                )

            # ========================================================
            # GET SPECTRE
            # ========================================================

            elif mode == "GetSpectre":

                # ----------------------------------------------------
                # После _parse_spectrum_data() buff должен быть dict.
                # ----------------------------------------------------

                if not isinstance(buff, dict):

                    self.ui.textEdit.append(
                        (
                            "Помилка: некоректні дані "
                            "GetSpectre для "
                            f"SN {sn}."
                        )
                    )

                    return

                channels = buff.get(
                    "channels"
                )

                paed_value = buff.get(
                    "paed_value"
                )

                accuracy = buff.get(
                    "accuracy",
                    0
                )

                test_byte = buff.get(
                    "test_byte",
                    0
                )

                result_valid = bool(
                    buff.get(
                        "valid",
                        False
                    )
                )

                # ----------------------------------------------------
                # ПРОВЕРКА СПЕКТРАЛЬНОГО МАССИВА
                # ----------------------------------------------------
                #
                # Текущая структура:
                #
                #     1023 канала
                #     +
                #     acquisition_time
                #
                # Итого 1024 элемента.
                # ----------------------------------------------------

                if (
                    not isinstance(
                        channels,
                        (list, tuple)
                    )
                    or len(channels) != 1024
                ):

                    self.ui.textEdit.append(
                        (
                            "Помилка: некоректна "
                            "структура спектру для "
                            f"SN {sn}."
                        )
                    )

                    return

                # ----------------------------------------------------
                # УПРАВЛЯЮЩИЙ PAED
                # ----------------------------------------------------

                self.device_manager.update_device_paed.emit(
                    sn,
                    (
                        paed_value
                        if result_valid
                        else None
                    )
                )

                # ----------------------------------------------------
                # Сохраняем PAED из спектрального ответа
                # ----------------------------------------------------

                card.last_paed_from_spectrum = (
                    paed_value
                )

                # ----------------------------------------------------
                # Обновляем отображение PAED
                # ----------------------------------------------------

                card.set_dose_value(
                    paed_value,
                    accuracy
                )

                # ----------------------------------------------------
                # Статусы детекторов
                # ----------------------------------------------------
                #
                # В существующей логике:
                #
                # True  -> соответствующий детектор исправен;
                # False -> отказ.
                #
                # Названия переменных исторически неудачны,
                # но здесь сохраняем существующую семантику.
                # ----------------------------------------------------

                high_failure = not bool(
                    test_byte & 0b00000001
                )

                low_failure = not bool(
                    test_byte & 0b00000010
                )

                card.set_detector_status(
                    low_failure,
                    high_failure,
                    result_valid
                )

                # ----------------------------------------------------
                # НАКОПЛЕНИЕ ОЧЕРЕДНОГО УЧАСТКА
                # ----------------------------------------------------
                #
                # add_spectrum_data():
                #
                #     S_total += S_i
                #     T_device_total += T_device_i
                #     spectrum_counter += 1
                #
                # После добавления текущего пакета метод проверяет
                # фактически прошедшее время ПК.
                # ----------------------------------------------------

                spectrum_ready = (
                    card.add_spectrum_data(
                        channels
                    )
                )

                # ----------------------------------------------------
                # СОХРАНЯЕМ ТЕКУЩЕЕ ИЗМЕРЕНИЕ В БУФЕР БД
                # ----------------------------------------------------

                device_id = (
                    self.db_manager.get_device_id(sn)
                )

                if (
                    device_id is not None
                    and card.location_type == "cistern"
                ):

                    temp_value = getattr(
                        card,
                        "last_temperature",
                        0.0
                    )

                    fullness_status = (
                        "full"
                        if getattr(
                            card,
                            "is_full",
                            False
                        )
                        else "empty"
                    )

                    group = self.cistern_groups.get(
                        card.posit_number,
                        "A"
                    )

                    self.db_manager.buffer_cistern_measurement(
                        device_id=device_id,
                        paed=paed_value,
                        temperature=temp_value,
                        low_status=(
                            1 if low_failure else 0
                        ),
                        high_status=(
                            1 if high_failure else 0
                        ),
                        valid=(
                            1 if result_valid else 0
                        ),
                        fullness_status=fullness_status,
                        group=group,
                        activity_json="{}",
                        concentration_json="{}",
                        spectrum_active=card.spectrum_active
                    )

                elif device_id is None:

                    self.ui.textEdit.append(
                        (
                            "Помилка: прилад "
                            f"{sn} не знайдено в БД."
                        )
                    )

                # ----------------------------------------------------
                # ПОЛНЫЙ СПЕКТРАЛЬНЫЙ ЦИКЛ ЗАВЕРШЁН
                # ----------------------------------------------------

                if spectrum_ready:

                    if card.spectrum_start_monotonic is None:

                        self.ui.textEdit.append(
                            (
                                "Помилка: неможливо визначити "
                                "час спектрального циклу для "
                                f"SN {sn}."
                            )
                        )

                        return

                    card.spectrum_elapsed_time = (
                        time.monotonic()
                        - card.spectrum_start_monotonic
                    )

                    if (
                        not math.isfinite(
                            card.spectrum_elapsed_time
                        )
                        or card.spectrum_elapsed_time <= 0.0
                    ):

                        self.ui.textEdit.append(
                            (
                                "Помилка: некоректний фактичний "
                                "час накопичення спектру для "
                                f"SN {sn}: "
                                f"{card.spectrum_elapsed_time}"
                            )
                        )

                        return

                    card.calculate_activity()

                    self.spectrum_cycle_finished.emit(
                        sn
                    )

            # ========================================================
            # НЕИЗВЕСТНЫЙ MODE
            # ========================================================

            else:

                self.ui.textEdit.append(
                    (
                        "Помилка: невідомий режим "
                        f"'{mode}' для SN {sn}."
                    )
                )

        except Exception as e:

            # ========================================================
            # ЗАЩИТА GUI-ПОТОКА
            # ========================================================
            #
            # Ошибка обработки одного пакета не должна приводить
            # к падению всего приложения.
            # ========================================================

            self.ui.textEdit.append(
                (
                    "Error parsing packet for "
                    f"{sn}: {e}\n"
                    "-------------------"
                )
            )
  


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
        Обрабатывает актуальный список найденных приборов
        и создаёт GUI-карточки ZB / CZ.

        Логика:

            1. Удаляем карточки предыдущего поиска.
            2. Разделяем приборы на цистерны и настенные.
            3. Сортируем их по физической позиции:
                ZB1 ... ZB9
                CZ1 ... CZ3
            4. Создаём новые карточки.
            5. Формируем cards_by_sn.
            6. Синхронизируем ZB с состоянием цистерн.
            7. Передаём состояние цистерн в DeviceManager.
            8. Устанавливаем корректное состояние кнопок.

        ВАЖНО:
            GUI должен отображать только результат
            ТЕКУЩЕГО поиска приборов.
        """

        # ============================================================
        # 1. ОЧИЩАЕМ РЕЗУЛЬТАТ ПРЕДЫДУЩЕГО ПОИСКА
        # ============================================================

        self.cards_by_sn.clear()
        self.clear_layout()

        # ============================================================
        # 2. ТЕКУЩИЙ ПОИСК НЕ ДАЛ НИ ОДНОГО ПРИБОРА
        # ============================================================

        if not devices:

            self.ui.textEdit.append(
                "Прилади не знайдено. "
                "Перевірте підключення та спробуйте ще раз."
            )

            # Поиск завершён — кнопку поиска снова разрешаем.
            self.butt_search_dev.setEnabled(True)

            # Запуск системы невозможен.
            if self.butt_system_start:
                self.butt_system_start.setEnabled(False)

            if self.butt_system_stop:
                self.butt_system_stop.setEnabled(False)

            return

        self.ui.textEdit.append(
            "Знайдено прилади:"
        )

        # ============================================================
        # 3. РАЗДЕЛЯЕМ ZB И CZ
        # ============================================================

        barrel_devices = [
            device
            for device in devices
            if device.get("location_type") == "cistern"
        ]

        wall_devices = [
            device
            for device in devices
            if device.get("location_type") == "room"
        ]

        # ============================================================
        # 4. СОРТИРУЕМ КАРТОЧКИ ПО ФИЗИЧЕСКОЙ ПОЗИЦИИ
        # ============================================================
        #
        # Порядок обнаружения приборов зависит от COM-порта
        # и адресов RS-485.
        #
        # Интерфейс оператора не должен от этого зависеть.
        #
        # Поэтому всегда получаем:
        #
        #     ZB1, ZB2, ... ZB9
        #
        # и:
        #
        #     CZ1, CZ2, CZ3

        barrel_devices.sort(
            key=lambda device: int(
                device.get("posit_number", 0)
            )
        )

        wall_devices.sort(
            key=lambda device: int(
                device.get("posit_number", 0)
            )
        )

        # ============================================================
        # 5. РАССЧИТЫВАЕМ СЕТКУ ДЛЯ ЦИСТЕРН
        # ============================================================

        if barrel_devices:

            columns = max(
                1,
                math.ceil(
                    math.sqrt(
                        len(barrel_devices)
                    )
                )
            )

        else:

            columns = 1

        barrel_index = 0

        # Считаем реально созданные карточки.
        created_cards = 0

        # ============================================================
        # 6. СОЗДАЁМ КАРТОЧКИ
        # ============================================================

        for device in (
            barrel_devices
            + wall_devices
        ):

            try:

                card = self.create_device_card(
                    device
                )

            except Exception as e:

                # Ошибка одной карточки не должна приводить
                # к падению всей процедуры поиска.
                self.ui.textEdit.append(
                    (
                        "Помилка створення картки "
                        f"SN {device.get('serial_number')}: {e}"
                    )
                )

                continue

            if card is None:
                continue

            # --------------------------------------------------------
            # Запоминаем основные параметры карточки
            # --------------------------------------------------------

            card.posit_number = (
                device.get(
                    "posit_number"
                )
            )

            card.serial_number = (
                device.get(
                    "serial_number"
                )
            )

            card.location_type = (
                device.get(
                    "location_type"
                )
            )

            # --------------------------------------------------------
            # Начальное состояние ZB
            # --------------------------------------------------------
            #
            # Это делаем здесь до общей синхронизации,
            # чтобы начальная загрузка существующего состояния
            # cistern.json не воспринималась как новое событие
            # "цистерна заполнилась".

            if isinstance(
                card,
                DeviceCardBarrel
            ):

                position = (
                    card.posit_number
                )

                full = bool(
                    self.cistern_dict.get(
                        int(position),
                        False
                    )
                )

                card.set_barrel_image(
                    full
                )

            # --------------------------------------------------------
            # Добавляем карточку в индекс по SN
            # --------------------------------------------------------

            self.cards_by_sn[
                card.serial_number
            ] = card

            # --------------------------------------------------------
            # Заполняем подписи
            # --------------------------------------------------------

            card.set_serial(
                card.serial_number
            )

            card.set_position(
                card.posit_number
            )

            card.setMinimumSize(
                0,
                0
            )

            card.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Expanding
            )

            # ========================================================
            # 7. РАЗМЕЩАЕМ КАРТОЧКУ В НУЖНОМ КОНТЕЙНЕРЕ
            # ========================================================

            if isinstance(
                card,
                DeviceCardBarrel
            ):

                row = (
                    barrel_index
                    // columns
                )

                col = (
                    barrel_index
                    % columns
                )

                self.barrel_grid.addWidget(
                    card,
                    row,
                    col
                )

                barrel_index += 1

            else:

                self.wall_layout.addWidget(
                    card
                )

            created_cards += 1

            # --------------------------------------------------------
            # Информация оператору
            # --------------------------------------------------------

            self.ui.textEdit.append(
                (
                    f"Порт: {device.get('port')}, "
                    f"Адреса: {device.get('address')}, "
                    f"SN: {device.get('serial_number')}"
                )
            )

        # ============================================================
        # 8. ДОБАВЛЯЕМ SPACER
        # ============================================================

        spacerB = QSpacerItem(
            1,
            1,
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Expanding
        )

        spacerW = QSpacerItem(
            1,
            1,
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Preferred
        )

        self.barrel_grid.addItem(
            spacerB
        )

        self.wall_layout.addItem(
            spacerW
        )

        # ============================================================
        # 9. НИ ОДНА КАРТОЧКА НЕ СОЗДАЛАСЬ
        # ============================================================

        if created_cards == 0:

            self.ui.textEdit.append(
                (
                    "Помилка: прилади знайдено, "
                    "але жодну GUI-картку створити не вдалося."
                )
            )

            self.butt_search_dev.setEnabled(
                True
            )

            if self.butt_system_start:
                self.butt_system_start.setEnabled(
                    False
                )

            if self.butt_system_stop:
                self.butt_system_stop.setEnabled(
                    False
                )

            return

        # ============================================================
        # 10. СИНХРОНИЗИРУЕМ СОСТОЯНИЕ ЦИСТЕРН
        # ============================================================

        self.sync_devices_with_cisterns()

        # ============================================================
        # 11. ПЕРЕДАЁМ НАЧАЛЬНОЕ СОСТОЯНИЕ ZB
        #     В DeviceManager
        # ============================================================

        self.sync_cisterns_to_manager.emit(
            self.cistern_dict.copy()
        )

        # ============================================================
        # 12. ПОИСК ЗАВЕРШЁН
        # ============================================================

        self.butt_search_dev.setEnabled(
            True
        )

        # Есть хотя бы одна корректная рабочая карточка —
        # разрешаем запуск опроса.
        if self.butt_system_start:

            self.butt_system_start.setEnabled(
                True
            )

        if self.butt_system_stop:

            self.butt_system_stop.setEnabled(
                False
            )



    

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
        Завантажує стан цистерн ZB1-ZB9 з JSON-файлу.

        Для актуальної конфігурації WROCLAW використовуються
        тільки 9 цистерн:

            ZB1, ZB2     -> група "A"
            ZB3          -> група "reserve"
            ZB4 ... ZB9  -> група "B"

        Для кожної цистерни зберігаються:
            full      - ознака заповненості;
            isotopes  - список раніше визначених ізотопів;
            group     - група алгоритму ідентифікації.

        Метод захищений від:
            - відсутності cistern.json;
            - пошкодженого JSON;
            - неправильного типу кореневого об'єкта;
            - неправильних номерів цистерн;
            - неправильного типу запису окремої цистерни;
            - неправильного типу поля full;
            - неправильного типу поля isotopes;
            - відсутніх записів ZB1-ZB9;
            - застарілих записів цистерн 10-20.

        Група цистерни визначається її фізичною позицією,
        а не значенням з JSON-файлу. Це виключає ситуацію,
        коли через пошкоджений або застарілий cistern.json
        для цистерни буде вибрано неправильний алгоритм.
        """

        # ============================================================
        # 1. СТВОРЮЄМО ЕТАЛОННУ СТРУКТУРУ ДЛЯ ZB1-ZB9
        # ============================================================

        # Словник заповненості цистерн.
        # За замовчуванням усі цистерни вважаються порожніми.
        self.cistern_dict = {
            i: False
            for i in range(1, 10)
        }

        # Словник раніше визначених ізотопів.
        # За замовчуванням список для кожної цистерни порожній.
        self.cistern_isotopes = {
            i: []
            for i in range(1, 10)
        }

        # Група алгоритму визначається жорстко за позицією цистерни.
        #
        # ZB1-ZB2 -> F-18 + Tc-99m
        # ZB3     -> резервний алгоритм усіх п'яти ізотопів
        # ZB4-ZB9 -> I-131 + Lu-177 + Y-90
        self.cistern_groups = {
            1: "A",
            2: "A",
            3: "reserve",
            4: "B",
            5: "B",
            6: "B",
            7: "B",
            8: "B",
            9: "B",
        }

        # Ознака того, що файл необхідно привести
        # до актуальної повної структури ZB1-ZB9.
        need_rewrite = False

        # ============================================================
        # 2. НАМАГАЄМОСЯ ПРОЧИТАТИ ІСНУЮЧИЙ ФАЙЛ
        # ============================================================

        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Кореневий JSON-об'єкт обов'язково повинен бути словником:
            #
            # {
            #     "1": {...},
            #     "2": {...}
            # }
            #
            # Якщо там список, число, рядок тощо —
            # файл структурно неправильний.
            if not isinstance(data, dict):
                raise ValueError(
                    "Кореневий об'єкт cistern.json повинен бути словником."
                )

            # ========================================================
            # 3. ЗАВАНТАЖУЄМО ТІЛЬКИ КОРЕКТНІ ЗАПИСИ ZB1-ZB9
            # ========================================================

            for key, value in data.items():

                # ----------------------------------------------------
                # Перевіряємо номер цистерни
                # ----------------------------------------------------

                try:
                    position = int(key)
                except (TypeError, ValueError):
                    print(
                        f"Некоректний номер цистерни у {json_file}: "
                        f"{key!r}. Запис пропущено."
                    )
                    need_rewrite = True
                    continue

                # В актуальній системі існують тільки ZB1-ZB9.
                if position < 1 or position > 9:
                    print(
                        f"Застарілий або некоректний запис ZB{position} "
                        f"у {json_file}. Запис пропущено."
                    )
                    need_rewrite = True
                    continue

                # ----------------------------------------------------
                # Перевіряємо структуру запису
                # ----------------------------------------------------

                if not isinstance(value, dict):
                    print(
                        f"Некоректні дані для ZB{position} "
                        f"у {json_file}. Використано значення за замовчуванням."
                    )
                    need_rewrite = True
                    continue

                # ----------------------------------------------------
                # Завантажуємо full
                # ----------------------------------------------------

                full_value = value.get("full", False)

                # Не використовуємо просто bool(full_value), тому що,
                # наприклад:
                #
                #     bool("false") == True
                #
                # що могло б помилково позначити цистерну як заповнену.
                if isinstance(full_value, bool):
                    self.cistern_dict[position] = full_value
                else:
                    print(
                        f"Некоректне поле 'full' для ZB{position} "
                        f"у {json_file}. Використано False."
                    )
                    self.cistern_dict[position] = False
                    need_rewrite = True

                # ----------------------------------------------------
                # Завантажуємо список ізотопів
                # ----------------------------------------------------

                isotopes_value = value.get("isotopes", [])

                if isinstance(isotopes_value, list):
                    # Зберігаємо тільки рядкові значення.
                    #
                    # Це захищає подальший код від випадкових
                    # чисел, словників або інших об'єктів у JSON.
                    valid_isotopes = [
                        isotope
                        for isotope in isotopes_value
                        if isinstance(isotope, str)
                    ]

                    self.cistern_isotopes[position] = valid_isotopes

                    # Якщо частина значень була відкинута,
                    # файл треба нормалізувати.
                    if len(valid_isotopes) != len(isotopes_value):
                        need_rewrite = True

                else:
                    print(
                        f"Некоректне поле 'isotopes' для ZB{position} "
                        f"у {json_file}. Використано порожній список."
                    )
                    self.cistern_isotopes[position] = []
                    need_rewrite = True

                # ----------------------------------------------------
                # Поле group з файлу навмисно НЕ використовуємо.
                # ----------------------------------------------------
                #
                # Група є характеристикою позиції цистерни,
                # а не змінним станом.
                #
                # Тому:
                #   ZB1-ZB2 -> A
                #   ZB3     -> reserve
                #   ZB4-ZB9 -> B
                #
                # завжди визначаються self.cistern_groups.

                expected_group = self.cistern_groups[position]

                if value.get("group") != expected_group:
                    need_rewrite = True

            # --------------------------------------------------------
            # Перевіряємо, чи присутні всі ZB1-ZB9
            # --------------------------------------------------------

            expected_positions = {
                str(i)
                for i in range(1, 10)
            }

            actual_positions = {
                str(key)
                for key in data.keys()
                if str(key).isdigit()
                and 1 <= int(key) <= 9
            }

            if actual_positions != expected_positions:
                need_rewrite = True

        # ============================================================
        # 4. ФАЙЛ ВІДСУТНІЙ
        # ============================================================

        except FileNotFoundError:
            print(
                f"Файл {json_file} відсутній. "
                f"Буде створено новий файл для ZB1-ZB9."
            )

            need_rewrite = True

        # ============================================================
        # 5. JSON СИНТАКСИЧНО ПОШКОДЖЕНИЙ
        # ============================================================

        except json.JSONDecodeError as error:
            print(
                f"Файл {json_file} містить пошкоджений JSON: {error}. "
                f"Буде створено коректну структуру ZB1-ZB9."
            )

            need_rewrite = True

        # ============================================================
        # 6. JSON МАЄ НЕПРАВИЛЬНУ СТРУКТУРУ
        # ============================================================

        except (TypeError, ValueError) as error:
            print(
                f"Некоректна структура файлу {json_file}: {error}. "
                f"Буде створено коректну структуру ZB1-ZB9."
            )

            need_rewrite = True

        # ============================================================
        # 7. ІНШІ ПОМИЛКИ ЧИТАННЯ ФАЙЛУ
        # ============================================================

        except OSError as error:
            # Помилка файлової системи не повинна валити запуск
            # всього застосунку.
            #
            # У пам'яті залишаються безпечні значення,
            # створені на початку методу.
            print(
                f"Не вдалося прочитати файл {json_file}: {error}. "
                f"Використовуються значення за замовчуванням."
            )

            # Тут не намагаємося одразу перезаписувати файл,
            # оскільки причина може бути у відсутності прав,
            # недоступному диску тощо.
            return

        # ============================================================
        # 8. НОРМАЛІЗУЄМО ФАЙЛ ПРИ НЕОБХІДНОСТІ
        # ============================================================

        if need_rewrite:

            export_data = {}

            for position in range(1, 10):
                export_data[str(position)] = {
                    "full": self.cistern_dict[position],
                    "isotopes": self.cistern_isotopes[position],
                    "group": self.cistern_groups[position],
                }

            try:
                # На випадок, якщо каталог config відсутній,
                # створюємо його перед записом.
                directory = os.path.dirname(json_file)

                if directory:
                    os.makedirs(directory, exist_ok=True)

                # ----------------------------------------------------
                # АТОМАРНИЙ ЗАПИС
                # ----------------------------------------------------
                #
                # Спочатку записуємо повний JSON у тимчасовий файл.
                # Тільки після успішного завершення запису
                # замінюємо основний cistern.json.
                #
                # Це зменшує ризик залишити напівзаписаний JSON,
                # наприклад, при аварійному завершенні програми
                # безпосередньо під час запису.

                temp_file = json_file + ".tmp"

                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(
                        export_data,
                        f,
                        ensure_ascii=False,
                        indent=4
                    )

                    # Гарантуємо передачу даних з буфера Python
                    # операційній системі перед заміною файлу.
                    f.flush()
                    os.fsync(f.fileno())

                # os.replace() замінює старий файл новим.
                # На одному файловому томі ця операція є атомарною.
                os.replace(temp_file, json_file)

                print(
                    f"Файл {json_file} приведено до актуальної "
                    f"структури ZB1-ZB9."
                )

            except OSError as error:
                # Навіть якщо файл не вдалося оновити,
                # програма продовжує працювати з коректною
                # структурою self.cistern_dict у пам'яті.
                print(
                    f"Не вдалося оновити файл {json_file}: {error}"
                )

                # Якщо тимчасовий файл залишився після помилки,
                # намагаємося його видалити.
                temp_file = json_file + ".tmp"

                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except OSError:
                    pass



    
    def sync_devices_with_cisterns(self):
        """
        Синхронизирует GUI-карточки цистерн ZB
        с текущим состоянием self.cistern_dict.

        ВАЖНО:

            1. Метод работает ТОЛЬКО с DeviceCardBarrel.
            Настенные приборы CZ не имеют состояния fullness.

            2. Никакие методы DeviceManager отсюда напрямую
            не вызываются — GUI и DeviceManager находятся
            в разных потоках.

            3. Ошибки синхронизации не скрываются.
            Они выводятся оператору в textEdit.

            4. При изменении состояния цистерны:
                empty -> full
                full  -> empty

            спектральные данные и история предыдущего
            цикла сбрасываются.
        """

        # ============================================================
        # 1. УБЕЖДАЕМСЯ, ЧТО ДАННЫЕ ЦИСТЕРН ЗАГРУЖЕНЫ
        # ============================================================

        if not self.cistern_dict:

            self.load_cistern_data(
                "config/cistern.json"
            )

        # ============================================================
        # 2. ПЕРЕБИРАЕМ GUI-КАРТОЧКИ
        # ============================================================

        for serial_number, card in self.cards_by_sn.items():

            # --------------------------------------------------------
            # CZ НЕ ИМЕЕТ СОСТОЯНИЯ ЗАПОЛНЕННОСТИ
            # --------------------------------------------------------
            #
            # Раньше код пытался вызвать:
            #
            #     card.set_barrel_image(...)
            #
            # также для DeviceCardWall.
            #
            # У настенной карточки такого метода нет,
            # поэтому каждый CZ создавал AttributeError,
            # который затем молча проглатывался.

            if not isinstance(
                card,
                DeviceCardBarrel
            ):
                continue

            try:

                # ====================================================
                # 3. ПОЛУЧАЕМ ПОЗИЦИЮ ZB
                # ====================================================

                posit = getattr(
                    card,
                    "posit_number",
                    None
                )

                if posit is None:

                    self.ui.textEdit.append(
                        (
                            "Помилка синхронізації цистерни: "
                            f"для SN {serial_number} "
                            "не визначено posit_number."
                        )
                    )

                    continue

                try:

                    posit = int(
                        posit
                    )

                except (
                    TypeError,
                    ValueError
                ):

                    self.ui.textEdit.append(
                        (
                            "Помилка синхронізації цистерни: "
                            f"некоректна позиція '{posit}' "
                            f"для SN {serial_number}."
                        )
                    )

                    continue

                # ====================================================
                # 4. ПРОВЕРЯЕМ ДИАПАЗОН ZB1-ZB9
                # ====================================================

                if posit < 1 or posit > 9:

                    self.ui.textEdit.append(
                        (
                            "Помилка синхронізації цистерни: "
                            f"позиція ZB{posit} "
                            f"для SN {serial_number} "
                            "поза допустимим діапазоном 1..9."
                        )
                    )

                    continue

                # ====================================================
                # 5. ПОЛУЧАЕМ СТАРОЕ И НОВОЕ СОСТОЯНИЕ
                # ====================================================

                old_full = bool(
                    getattr(
                        card,
                        "is_full",
                        False
                    )
                )

                new_full = bool(
                    self.cistern_dict.get(
                        posit,
                        False
                    )
                )

                # ====================================================
                # 6. ЕСЛИ СОСТОЯНИЕ НЕ ИЗМЕНИЛОСЬ
                # ====================================================
                #
                # Нет необходимости повторно менять картинку
                # и выполнять дополнительную работу.

                if old_full == new_full:

                    continue

                # ====================================================
                # 7. СОСТОЯНИЕ ЦИСТЕРНЫ ИЗМЕНИЛОСЬ
                # ====================================================

                card.set_barrel_image(
                    new_full
                )

                # ====================================================
                # 8. НАЧАЛСЯ НОВЫЙ ЦИКЛ ЦИСТЕРНЫ
                # ====================================================
                #
                # Как при заполнении, так и при опорожнении
                # накопленный спектр предыдущего цикла
                # больше нельзя использовать.

                if hasattr(
                    card,
                    "reset_spectrum"
                ):

                    card.reset_spectrum()

                if hasattr(
                    card,
                    "clear_history"
                ):

                    card.clear_history()

                # ====================================================
                # 9. СООБЩАЕМ ОПЕРАТОРУ
                # ====================================================

                if new_full:

                    self.ui.textEdit.append(
                        (
                            f"Цистерна №{posit} заповнена. "
                            "Спектр та історію скинуто."
                        )
                    )

                else:

                    self.ui.textEdit.append(
                        (
                            f"Цистерна №{posit} спорожнена. "
                            "Спектр та історію скинуто."
                        )
                    )

            # ========================================================
            # 10. НЕПРЕДВИДЕННАЯ ОШИБКА
            # ========================================================
            #
            # Для 24/7 приложения нельзя молча терять ошибку GUI.
            # При этом ошибка одной карточки не должна ломать
            # синхронизацию остальных ZB.

            except Exception as e:

                self.ui.textEdit.append(
                    (
                        "Помилка синхронізації "
                        f"ZB для SN {serial_number}: {e}"
                    )
                )

                continue



    
    def cleanup(self):
        """
        Коректне завершення роботи програми.
        Зупиняє всі таймери, процеси та закриває з'єднання.
        """
        # --------------------------------------------------------------------
        # 2. Закриваємо з'єднання з Bridge (ModBusBridgeClient)
        # --------------------------------------------------------------------
        if hasattr(self, 'modbus_client') and self.modbus_client is not None:
            self.ui.textEdit.append("[Bridge] Закриття з'єднання з Bridge...")
            self.modbus_client.shutdown()
            self.ui.textEdit.append("[Bridge] З'єднання з Bridge закрито")

        # --------------------------------------------------------------------
        # 3. Зупиняємо C++ процес (ModBusBridgeService)
        # --------------------------------------------------------------------
        self.stop_bridge()

        # --------------------------------------------------------------------
        # 4. Зупиняємо DeviceManager (коректно в його потоці)
        # --------------------------------------------------------------------
        if self.device_manager is not None:
            try:
                QMetaObject.invokeMethod(
                    self.device_manager,
                    "stop_all",
                    Qt.ConnectionType.QueuedConnection
                )
            except Exception as e:
                self.ui.textEdit.append(f"Помилка при зупинці DeviceManager: {e}")

        # --------------------------------------------------------------------
        # 5. Завершуємо потік DeviceManager
        # --------------------------------------------------------------------
        if self.device_manager_thread is not None and self.device_manager_thread.isRunning():
            self.device_manager_thread.quit()
            if not self.device_manager_thread.wait(2000):
                self.device_manager_thread.terminate()
                self.device_manager_thread.wait(1000)

        # --------------------------------------------------------------------
        # 6. Закриваємо з'єднання з БД та записуємо подію зупинки
        # --------------------------------------------------------------------
        if self.db_manager is not None:
            self.db_manager.save_system_event(None, "app_stop", "Програма зупинена")
            self.db_manager.close()

        self.ui.textEdit.append("Програма завершена")

    def is_bridge_connected(self) -> bool:
        """
        Перевіряє, чи встановлено з'єднання з Bridge (ModBusBridgeClient).
        
        Вихід:
            True - якщо з'єднання активне
            False - якщо з'єднання відсутнє або клієнт не створено
        """
        if hasattr(self, 'modbus_client') and self.modbus_client is not None:
            return self.modbus_client.is_connected()
        return False
        

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
        Активные и неактивные приборы для замены берутся из БД (is_active = 1, 0).
        """
        # Активные приборы (для замены) - берем из БД
        active_devices = self.db_manager.get_all_active_devices()
        
        # Неактивные приборы (для активации) - берем из БД
        inactive_devices = self.db_manager.get_inactive_devices()
        
        dialog = DeviceReplaceDialog(
            self.db_manager,
            active_devices,
            inactive_devices,
            self.ui,
            self  # передаем ссылку на App для отправки данных в Bridge
        )
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

        Формула консультанта:
            sum_k = sum(k_i)
            T1 = T - DEAD_TIME_COEFF * sum_k
            n_i = k_i / T1

        Повертає list[float] довжиною 1023 або None, якщо вхідні
        дані не дозволяють виконати коректний розрахунок.
        """

        # ------------------------------------------------------------
        # 1. ПЕРЕВІРКА ЧАСУ T
        # ------------------------------------------------------------
        try:
            real_time = float(T)
        except (TypeError, ValueError):
            return None

        if not math.isfinite(real_time) or real_time <= 0.0:
            return None

        # ------------------------------------------------------------
        # 2. ПЕРЕВІРКА 1023 КАНАЛІВ
        # ------------------------------------------------------------
        if not isinstance(spectrum, (list, tuple, np.ndarray)):
            return None

        if len(spectrum) != 1023:
            return None

        checked = []

        for value in spectrum:
            try:
                value_f = float(value)
            except (TypeError, ValueError):
                return None

            # Сирі накопичені імпульси повинні бути кінцевими та
            # не можуть бути від'ємними.
            if not math.isfinite(value_f) or value_f < 0.0:
                return None

            checked.append(value_f)

        # ------------------------------------------------------------
        # 3. КОРЕКЦІЯ НА МЕРТВИЙ ЧАС
        # ------------------------------------------------------------
        sum_k = math.fsum(checked)
        T1 = real_time - self.DEAD_TIME_COEFF * sum_k

        # Якщо T1 <= 0, формула фізично/математично непридатна.
        # Старий код мовчки підміняв T1 на T; тепер цього не робимо.
        if not math.isfinite(T1) or T1 <= 0.0:
            return None

        # ------------------------------------------------------------
        # 4. НОРМУВАННЯ ARR_1
        # ------------------------------------------------------------
        return [value / T1 for value in checked]



    def _subtract_background(self, arr1):
        """
        Віднімає підготовлений консультантом фоновий спектр.

        background.txt вже приведений до потрібного масштабу, тому
        додатково нормувати його тут НЕ потрібно.

        Повертає ARR_2 або None, якщо фон чи ARR_1 некоректні.
        Розрахунок без фону не продовжується.
        """

        # ------------------------------------------------------------
        # 1. ПЕРЕВІРКА ARR_1
        # ------------------------------------------------------------
        if not isinstance(arr1, (list, tuple, np.ndarray)):
            return None

        if len(arr1) != 1023:
            return None

        arr1_checked = []
        for value in arr1:
            try:
                value_f = float(value)
            except (TypeError, ValueError):
                return None

            if not math.isfinite(value_f):
                return None

            arr1_checked.append(value_f)

        # ------------------------------------------------------------
        # 2. ОТРИМУЄМО ОБОВ'ЯЗКОВИЙ ФОНОВИЙ СПЕКТР
        # ------------------------------------------------------------
        bg = self.calibration_spectra.get("background")

        # load_calibration_spectra вже перевіряє точну довжину 1024,
        # але тут залишаємо захист на випадок зміни даних у runtime.
        if bg is None or not isinstance(bg, (list, tuple, np.ndarray)):
            return None

        if len(bg) != 1024:
            return None

        background = []
        for value in bg[:1023]:
            try:
                value_f = float(value)
            except (TypeError, ValueError):
                return None

            if not math.isfinite(value_f):
                return None

            background.append(value_f)

        # ------------------------------------------------------------
        # 3. ФОРМУЄМО ARR_2
        # ------------------------------------------------------------
        # Від'ємні значення ARR_2 допустимі як результат віднімання
        # фону; штучно обрізати їх до нуля на цьому етапі не можна.
        return [
            arr1_checked[i] - background[i]
            for i in range(1023)
        ]


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
        Повертає базовий спектр довжиною 1023 канали.

        Для логічного імені "base_I" використовується файл
        calibration/I-131.txt. Сам файл уже підготовлений консультантом
        у потрібному масштабі та повторно не нормується.

        Якщо спектр відсутній або пошкоджений, повертається None.
        Нульове доповнення короткого масиву більше не виконується.
        """

        # ------------------------------------------------------------
        # 1. ВИЗНАЧАЄМО ФАКТИЧНЕ ІМ'Я
        # ------------------------------------------------------------
        spectrum_name = "I-131" if name == "base_I" else name

        # ------------------------------------------------------------
        # 2. ОТРИМУЄМО ЗАВАНТАЖЕНИЙ ЕТАЛОН
        # ------------------------------------------------------------
        spectrum = self.calibration_spectra.get(spectrum_name)

        if spectrum is None:
            return None

        if not isinstance(spectrum, (list, tuple, np.ndarray)):
            return None

        # Калібрувальний файл повинен мати рівно 1024 значення.
        if len(spectrum) != 1024:
            return None

        # ------------------------------------------------------------
        # 3. ПОВЕРТАЄМО ТІЛЬКИ 1023 СПЕКТРАЛЬНІ КАНАЛИ
        # ------------------------------------------------------------
        result = []

        for value in spectrum[:1023]:
            try:
                value_f = float(value)
            except (TypeError, ValueError):
                return None

            if not math.isfinite(value_f):
                return None

            result.append(value_f)

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
        Ідентифікація ізотопів для групи A (цистерни ZB1, ZB2).

        Алгоритм реалізований за первинним описом "F, Tc":

        ПЕРШИЙ ЦИКЛ
        ------------
        1. Для 18F результат розраховується одразу.
        2. Для 99mTc результат ще НЕ видається.
        3. Поточна площа Tc з ARR_2 запам'ятовується для другого циклу.
        4. K_F та K_Tc обчислюються за фактичним T першого циклу
           і фіксуються як константи для наступних циклів.

        ДРУГИЙ ЦИКЛ
        ------------
        1. 18F розраховується звичайно.
        2. 99mTc розраховується ОБОВ'ЯЗКОВО за формулою динаміки:
               S_Tc =
               (S_current - K_F * S_previous) /
               (K_Tc - K_F)
        3. Для другого циклу отриманий динамічний результат НЕ
           замінюється прямою площею.
        4. Після цього обчислюється відношення:
               ratio = S_Tc_dynamic / S_current
        5. Якщо ratio < 0.95, з третього циклу використовується
           прямий метод.
           Якщо ratio >= 0.95, з третього циклу продовжується
           динамічний метод.
           Значення рівно 0.95 за погодженим правилом відноситься
           до динамічного режиму.

        ТРЕТІЙ ЦИКЛ І ДАЛІ
        ------------------
        1. Якщо tc_use_direct == True:
               S_Tc = S_current
        2. Інакше:
               S_Tc =
               (S_current - K_F * S_previous) /
               (K_Tc - K_F)

        ВАЖЛИВО
        -------
        - K_F та K_Tc після першого циклу не перераховуються.
        - previous_Tc_arr2 після кожного завершеного циклу
          оновлюється поточною площею Tc з ARR_2.
        - Якщо історія пошкоджена або неповна, алгоритм безпечно
          починає нову "першу годину", а не використовує
          некоректні дані.
        - У першому циклі 99mTc повертається з available=False.
          Це означає: результат Tc ще не отриманий, а не "Tc немає".
        """

        # ============================================================
        # 0. БАЗОВА ПЕРЕВІРКА ВХІДНИХ ДАНИХ
        # ============================================================

        if len(arr1) != 1023 or len(arr2) != 1023:
            raise ValueError(
                "Група A: ARR_1 та ARR_2 повинні містити рівно 1023 канали."
            )

        try:
            real_time = float(real_time)
            volume = float(volume)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Група A: T та об'єм повинні бути числовими."
            ) from exc

        if not math.isfinite(real_time) or real_time <= 0.0:
            raise ValueError(
                f"Група A: некоректний час вимірювання T={real_time}."
            )

        if not math.isfinite(volume) or volume < 0.0:
            raise ValueError(
                f"Група A: некоректний об'єм цистерни={volume}."
            )

        # ============================================================
        # 1. РОЗРАХУНОК 18F
        # ============================================================

        isotope_F = "18F"
        window_F = self.GROUP_A_WINDOWS[isotope_F]
        coeff_F = self.GROUP_A_COEFFICIENTS[isotope_F]
        sigma_F = self.GROUP_A_SIGMA[isotope_F]

        # Площа з ARR_2 — після віднімання фону.
        sum_F_clean = self._calculate_window_sum(
            arr2,
            window_F[0],
            window_F[1]
        )

        # Площа з ARR_1 — для статистичних меж.
        sum_F_raw = self._calculate_window_sum(
            arr1,
            window_F[0],
            window_F[1]
        )

        limits_F = self._calculate_limits(
            sum_F_clean,
            sum_F_raw,
            real_time,
            sigma_F
        )

        # Питома активність 18F.
        conc_F = sum_F_clean * coeff_F

        # Загальна активність 18F.
        activity_F = conc_F * volume

        # Межі питомої активності.
        conc_F_upper = limits_F["upper"] * coeff_F
        conc_F_lower = limits_F["lower"] * coeff_F

        # Межі загальної активності.
        activity_F_upper = conc_F_upper * volume
        activity_F_lower = conc_F_lower * volume

        # Ідентифікація 18F за положенням верхньої/нижньої межі.
        if limits_F["upper"] > 0.0 and limits_F["lower"] > 0.0:
            detected_F = "Є"
        elif limits_F["upper"] > 0.0 and limits_F["lower"] <= 0.0:
            detected_F = "МОЖЕ БУТИ"
        else:
            detected_F = "НЕМАЄ"

        # ============================================================
        # 2. ПОТОЧНІ ПЛОЩІ 99mTc
        # ============================================================

        isotope_Tc = "99mTc"
        window_Tc = self.GROUP_A_WINDOWS[isotope_Tc]
        coeff_Tc = self.GROUP_A_COEFFICIENTS[isotope_Tc]
        sigma_Tc = self.GROUP_A_SIGMA[isotope_Tc]

        # Поточна площа Tc після віднімання фону.
        sum_Tc_clean_current = self._calculate_window_sum(
            arr2,
            window_Tc[0],
            window_Tc[1]
        )

        # Поточна площа Tc з ARR_1.
        # Вона використовується для статистичної похибки
        # саме поточного циклу.
        sum_Tc_raw_current = self._calculate_window_sum(
            arr1,
            window_Tc[0],
            window_Tc[1]
        )

        # ============================================================
        # 3. ПЕРЕВІРКА ІСТОРІЇ
        # ============================================================
        #
        # Історія повинна бути придатна для продовження динамічного
        # алгоритму. Якщо вона пошкоджена, не намагаємося вгадувати
        # дані — починаємо новий перший цикл.

        history_valid = False

        if isinstance(history, dict) and history:
            required_keys = {
                "cycle",
                "K_F",
                "K_Tc",
                "previous_Tc_arr2",
                "tc_use_direct"
            }

            if required_keys.issubset(history.keys()):
                try:
                    hist_cycle = int(history["cycle"])
                    hist_K_F = float(history["K_F"])
                    hist_K_Tc = float(history["K_Tc"])
                    hist_prev_Tc = float(history["previous_Tc_arr2"])

                    # tc_use_direct на першому циклі ще не визначений
                    # і тому може бути None.
                    hist_mode = history["tc_use_direct"]

                    history_valid = (
                        hist_cycle >= 1
                        and math.isfinite(hist_K_F)
                        and math.isfinite(hist_K_Tc)
                        and math.isfinite(hist_prev_Tc)
                        and hist_mode in (None, True, False)
                    )

                except (TypeError, ValueError):
                    history_valid = False

        # ============================================================
        # 4. ПЕРШИЙ ЦИКЛ
        # ============================================================

        if not history_valid:

            # Коефіцієнти розпаду розраховуються ОДИН РАЗ
            # за фактичним T першого циклу.
            K_F = self._calculate_decay_coefficient(
                real_time,
                self.GROUP_A_HALF_LIFE[isotope_F]
            )

            K_Tc = self._calculate_decay_coefficient(
                real_time,
                self.GROUP_A_HALF_LIFE[isotope_Tc]
            )

            if (
                not math.isfinite(K_F)
                or not math.isfinite(K_Tc)
            ):
                raise ValueError(
                    "Група A: не вдалося отримати коректні K_F/K_Tc."
                )

            # Знаменник знадобиться з другого циклу.
            denom = K_Tc - K_F

            if abs(denom) < 1e-12:
                raise ValueError(
                    "Група A: K_Tc - K_F занадто малий для "
                    "динамічного розрахунку Tc."
                )

            history_updated = {
                # Номер завершеного спектрального циклу.
                "cycle": 1,

                # Константні коефіцієнти, отримані за перший цикл.
                "K_F": K_F,
                "K_Tc": K_Tc,

                # Поточна ARR_2 зона Tc стає попередньою
                # для другого циклу.
                "previous_Tc_arr2": sum_Tc_clean_current,

                # Після першого циклу режим ще не визначений.
                # Рішення приймається лише після другого циклу.
                "tc_use_direct": None,

                # Саме відношення також з'явиться лише
                # після другого циклу.
                "tc_ratio": None,

                # Діагностично зберігаємо T першого циклу,
                # за яким були отримані K.
                "reference_time": real_time
            }

            # У першому циклі Tc ЩЕ НЕ РОЗРАХОВУЄТЬСЯ.
            #
            # available=False принципово відрізняє стан
            # "результату ще немає" від реального результату
            # "активність = 0".
            result = {
                "group": "A",
                "isotopes": ["18F", "99mTc"],

                "18F": {
                    "available": True,
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
                    "available": False,
                    "activity": None,
                    "concentration": None,
                    "activity_upper": None,
                    "activity_lower": None,
                    "conc_upper": None,
                    "conc_lower": None,
                    "detected": None,

                    # Поточні площі залишаємо для діагностики,
                    # але не трактуємо як результат Tc.
                    "sum_clean": sum_Tc_clean_current,
                    "sum_raw": sum_Tc_raw_current,

                    "limits": None,
                    "delay_cycles": 1
                },

                "real_time": real_time,
                "history_updated": history_updated
            }

            return result

        # ============================================================
        # 5. ДРУГИЙ ТА НАСТУПНІ ЦИКЛИ
        # ============================================================

        cycle = hist_cycle + 1
        K_F = hist_K_F
        K_Tc = hist_K_Tc
        prev_sum_Tc_arr2 = hist_prev_Tc

        denom = K_Tc - K_F

        if abs(denom) < 1e-12:
            raise ValueError(
                "Група A: K_Tc - K_F занадто малий для "
                "динамічного розрахунку Tc."
            )

        # ------------------------------------------------------------
        # 5.1. Другий цикл
        # ------------------------------------------------------------
        #
        # Другий цикл ЗАВЖДИ рахуємо за динамічною формулою.
        # Порогове відношення визначає тільки алгоритм
        # ТРЕТЬОГО та наступних циклів.

        if cycle == 2:

            sum_Tc_clean = (
                sum_Tc_clean_current
                - K_F * prev_sum_Tc_arr2
            ) / denom

            # Відношення п.11.
            #
            # Якщо поточна площа дорівнює нулю, математично
            # відношення визначити неможливо.
            #
            # У такому випадку безпечніше не перемикатися
            # у прямий режим автоматично; залишаємо dynamic.
            if abs(sum_Tc_clean_current) > 1e-12:
                tc_ratio = (
                    sum_Tc_clean
                    / sum_Tc_clean_current
                )
            else:
                tc_ratio = None

            if (
                tc_ratio is not None
                and math.isfinite(tc_ratio)
                and tc_ratio < self.GROUP_A_TC_THRESHOLD
            ):
                tc_use_direct = True
            else:
                # За погодженим правилом ratio == 0.95
                # належить до динамічного режиму.
                tc_use_direct = False

        # ------------------------------------------------------------
        # 5.2. Третій цикл і далі
        # ------------------------------------------------------------
        else:

            tc_use_direct = bool(hist_mode)
            tc_ratio = history.get("tc_ratio")

            if tc_use_direct:
                # Прямий метод: беремо поточну площу ARR_2.
                sum_Tc_clean = sum_Tc_clean_current

            else:
                # Динамічний метод.
                sum_Tc_clean = (
                    sum_Tc_clean_current
                    - K_F * prev_sum_Tc_arr2
                ) / denom

        # ============================================================
        # 6. МЕЖІ, АКТИВНІСТЬ ТА ІДЕНТИФІКАЦІЯ Tc
        # ============================================================
        #
        # Для статистичної складової використовується ARR_1
        # ПОТОЧНОГО циклу, як указано в первинному алгоритмі.

        limits_Tc = self._calculate_limits(
            sum_Tc_clean,
            sum_Tc_raw_current,
            real_time,
            sigma_Tc
        )

        conc_Tc = sum_Tc_clean * coeff_Tc
        activity_Tc = conc_Tc * volume

        conc_Tc_upper = limits_Tc["upper"] * coeff_Tc
        conc_Tc_lower = limits_Tc["lower"] * coeff_Tc

        activity_Tc_upper = conc_Tc_upper * volume
        activity_Tc_lower = conc_Tc_lower * volume

        if limits_Tc["upper"] > 0.0 and limits_Tc["lower"] > 0.0:
            detected_Tc = "Є"
        elif limits_Tc["upper"] > 0.0 and limits_Tc["lower"] <= 0.0:
            detected_Tc = "МОЖЕ БУТИ"
        else:
            detected_Tc = "НЕМАЄ"

        # ============================================================
        # 7. ОНОВЛЮЄМО ІСТОРІЮ
        # ============================================================
        #
        # Поточна ARR_2 зона Tc повинна стати попередньою
        # для наступного циклу — незалежно від того, який режим
        # (direct/dynamic) був використаний для результату.

        history_updated = {
            "cycle": cycle,
            "K_F": K_F,
            "K_Tc": K_Tc,
            "previous_Tc_arr2": sum_Tc_clean_current,
            "tc_use_direct": tc_use_direct,
            "tc_ratio": tc_ratio,
            "reference_time": history.get("reference_time", real_time)
        }

        # ============================================================
        # 8. ФОРМУЄМО РЕЗУЛЬТАТ
        # ============================================================

        result = {
            "group": "A",
            "isotopes": ["18F", "99mTc"],

            "18F": {
                "available": True,
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
                "available": True,
                "activity": activity_Tc,
                "concentration": conc_Tc,
                "activity_upper": activity_Tc_upper,
                "activity_lower": activity_Tc_lower,
                "conc_upper": conc_Tc_upper,
                "conc_lower": conc_Tc_lower,
                "detected": detected_Tc,
                "sum_clean": sum_Tc_clean,
                "sum_raw": sum_Tc_raw_current,
                "limits": limits_Tc,
                "delay_cycles": 1,

                # Діагностичні поля, корисні для перевірки
                # алгоритму на реальних даних.
                "tc_ratio": tc_ratio,
                "tc_use_direct": tc_use_direct
            },

            "real_time": real_time,
            "history_updated": history_updated
        }

        return result




    def _identify_group_B(self, arr1, arr2, real_time, volume):
        """
        Ідентифікація ізотопів для групи B (цистерни ZB4–ZB9).

        Ізотопи:
            - 90Y
            - 133I
            - 177Lu

        Алгоритм виконується строго в послідовності:

            1. 90Y по ARR_2.
            2. Масштабування базового спектра I-131 по зоні 90–150.
            3. Розрахунок 133I по масштабованому спектру ARR_3.
            4. Формування ARR_4 = ARR_2 - ARR_3.
            5. Розрахунок 177Lu по ARR_4.

        ВАЖЛИВО:

            - розрахунковий час T для алгоритму групи B фіксований
            і дорівнює 3600 секунд;

            - ARR_1 повинен бути вже підготовлений у identify_isotopes_alim()
            з використанням цього ж T = 3600 с;

            - базовий спектр I-131.txt є обов'язковим;

            - якщо базовий спектр відсутній або некоректний,
            розрахунок групи B не продовжується;

            - від'ємні значення ARR_2, ARR_3, ARR_4, площ та активностей
            допустимі та НЕ обрізаються до нуля;

            - для статистичних меж 133I під квадратним коренем
            використовується сума каналів 90–150 з ARR_1,
            що окремо підтверджено консультантом;

            - попередні спектральні цикли для групи B не використовуються.
        """

        # ============================================================
        # 0. БАЗОВА ПЕРЕВІРКА ВХІДНИХ ДАНИХ
        # ============================================================

        if len(arr1) != 1023 or len(arr2) != 1023:
            self.ui.textEdit.append(
                "Помилка групи B: ARR_1 та ARR_2 повинні містити "
                "рівно 1023 канали."
            )
            return None

        try:
            volume = float(volume)
        except (TypeError, ValueError):
            self.ui.textEdit.append(
                "Помилка групи B: некоректний об'єм цистерни."
            )
            return None

        if not math.isfinite(volume) or volume <= 0.0:
            self.ui.textEdit.append(
                f"Помилка групи B: некоректний об'єм цистерни: {volume}."
            )
            return None

        # ------------------------------------------------------------
        # Для алгоритму групи B консультант підтвердив:
        #
        #     T = 3600 секунд.
        #
        # Фактичний час ПК може відрізнятися на декілька секунд,
        # але у формулах алгоритму використовується саме 3600.
        # ------------------------------------------------------------

        calculation_time = 3600.0

        # ============================================================
        # 1. 90Y
        # ============================================================

        isotope_Y = "90Y"
        window_Y = self.GROUP_B_WINDOWS[isotope_Y]
        coeff_Y = self.GROUP_B_COEFFICIENTS[isotope_Y]
        sigma_Y = self.GROUP_B_SIGMA[isotope_Y]

        # Центральна площа 90Y береться з ARR_2.
        sum_Y_clean = self._calculate_window_sum(
            arr2,
            window_Y[0],
            window_Y[1]
        )

        # Для статистичної похибки використовується ARR_1.
        sum_Y_raw = self._calculate_window_sum(
            arr1,
            window_Y[0],
            window_Y[1]
        )

        limits_Y = self._calculate_limits(
            sum_Y_clean,
            sum_Y_raw,
            calculation_time,
            sigma_Y
        )

        # Питома активність.
        conc_Y = sum_Y_clean * coeff_Y

        # Загальна активність.
        activity_Y = conc_Y * volume

        # Межі питомої активності.
        conc_Y_upper = limits_Y["upper"] * coeff_Y
        conc_Y_lower = limits_Y["lower"] * coeff_Y

        # Межі загальної активності.
        activity_Y_upper = conc_Y_upper * volume
        activity_Y_lower = conc_Y_lower * volume

        # Правило ідентифікації однакове для всіх алгоритмів.
        if limits_Y["upper"] > 0.0 and limits_Y["lower"] > 0.0:
            detected_Y = "Є"

        elif limits_Y["upper"] > 0.0 and limits_Y["lower"] <= 0.0:
            detected_Y = "МОЖЕ БУТИ"

        else:
            detected_Y = "НЕМАЄ"

        # ============================================================
        # 2. 133I — БАЗОВИЙ СПЕКТР
        # ============================================================

        isotope_I = "133I"
        window_I = self.GROUP_B_WINDOWS[isotope_I]
        coeff_I = self.GROUP_B_COEFFICIENTS[isotope_I]
        sigma_I = self.GROUP_B_SIGMA[isotope_I]

        # Базовий спектр I-131 є ОБОВ'ЯЗКОВИМ.
        #
        # За відповіддю консультанта не допускається резервний
        # прямий розрахунок йоду без I-131.txt.
        base_spectrum = self._load_base_spectrum("base_I")

        if base_spectrum is None:
            self.ui.textEdit.append(
                "Помилка групи B: базовий спектр I-131.txt "
                "відсутній або пошкоджений. "
                "Розрахунок групи B скасовано."
            )
            return None

        if len(base_spectrum) != 1023:
            self.ui.textEdit.append(
                "Помилка групи B: базовий спектр I-131 "
                "повинен містити рівно 1023 спектральні канали."
            )
            return None

        # ============================================================
        # 3. КОЕФІЦІЄНТ МАСШТАБУВАННЯ ЙОДУ
        # ============================================================

        # Для групи B і чисельник, і знаменник коефіцієнта
        # масштабування беруться у вікні 90–150.
        sum_I_arr2 = self._calculate_window_sum(
            arr2,
            window_I[0],
            window_I[1]
        )

        sum_base_I = self._calculate_window_sum(
            base_spectrum,
            window_I[0],
            window_I[1]
        )

        # За словами консультанта базовий спектр незмінний,
        # тому його площа 90–150 у штатному стані не повинна
        # бути нульовою або від'ємною.
        #
        # Якщо це все-таки сталося, це означає пошкодження
        # калібрувальних даних. Підміняти алгоритм іншим
        # способом розрахунку заборонено.
        if (
            not math.isfinite(sum_base_I)
            or sum_base_I <= 0.0
        ):
            self.ui.textEdit.append(
                "Помилка групи B: некоректна площа базового "
                f"спектра I-131 у каналах 90–150: {sum_base_I}. "
                "Розрахунок скасовано."
            )
            return None

        # Чисельник може бути додатним, нульовим або від'ємним.
        #
        # Консультант прямо підтвердив, що його не потрібно
        # обмежувати нулем або брати по модулю.
        scale_I = sum_I_arr2 / sum_base_I

        if not math.isfinite(scale_I):
            self.ui.textEdit.append(
                "Помилка групи B: отримано некоректний коефіцієнт "
                f"масштабування I-131: {scale_I}."
            )
            return None

        # ============================================================
        # 4. ARR_3 — МАСШТАБОВАНИЙ БАЗОВИЙ СПЕКТР ЙОДУ
        # ============================================================

        arr3 = [
            value * scale_I
            for value in base_spectrum
        ]

        # Від'ємні значення ARR_3 допустимі.
        if any(not math.isfinite(value) for value in arr3):
            self.ui.textEdit.append(
                "Помилка групи B: ARR_3 містить некоректні "
                "числові значення."
            )
            return None

        # ============================================================
        # 5. ПЛОЩА ТА МЕЖІ 133I
        # ============================================================

        # Центральна площа 133I визначається вже по ARR_3.
        sum_I_clean = self._calculate_window_sum(
            arr3,
            window_I[0],
            window_I[1]
        )

        # ВАЖЛИВО:
        #
        # консультант окремо підтвердив, що під квадратним
        # коренем для статистичних границь йоду потрібно
        # використовувати суму 90–150 саме з ARR_1.
        sum_I_raw = self._calculate_window_sum(
            arr1,
            window_I[0],
            window_I[1]
        )

        limits_I = self._calculate_limits(
            sum_I_clean,
            sum_I_raw,
            calculation_time,
            sigma_I
        )

        conc_I = sum_I_clean * coeff_I
        activity_I = conc_I * volume

        conc_I_upper = limits_I["upper"] * coeff_I
        conc_I_lower = limits_I["lower"] * coeff_I

        activity_I_upper = conc_I_upper * volume
        activity_I_lower = conc_I_lower * volume

        if limits_I["upper"] > 0.0 and limits_I["lower"] > 0.0:
            detected_I = "Є"

        elif limits_I["upper"] > 0.0 and limits_I["lower"] <= 0.0:
            detected_I = "МОЖЕ БУТИ"

        else:
            detected_I = "НЕМАЄ"

        # ============================================================
        # 6. ARR_4 = ARR_2 - ARR_3
        # ============================================================

        # Ніякого fallback ARR_4 = ARR_2 більше немає.
        #
        # Якщо ARR_3 не вдалося отримати, метод уже завершився вище.
        arr4 = [
            arr2[i] - arr3[i]
            for i in range(1023)
        ]

        # Від'ємні значення ARR_4 дозволені консультантом.
        if any(not math.isfinite(value) for value in arr4):
            self.ui.textEdit.append(
                "Помилка групи B: ARR_4 містить некоректні "
                "числові значення."
            )
            return None

        # ============================================================
        # 7. 177Lu
        # ============================================================

        isotope_Lu = "177Lu"
        window_Lu = self.GROUP_B_WINDOWS[isotope_Lu]
        coeff_Lu = self.GROUP_B_COEFFICIENTS[isotope_Lu]
        sigma_Lu = self.GROUP_B_SIGMA[isotope_Lu]

        # Центральна площа Lu береться з ARR_4.
        sum_Lu_clean = self._calculate_window_sum(
            arr4,
            window_Lu[0],
            window_Lu[1]
        )

        # Для статистичної складової використовується ARR_1.
        sum_Lu_raw = self._calculate_window_sum(
            arr1,
            window_Lu[0],
            window_Lu[1]
        )

        limits_Lu = self._calculate_limits(
            sum_Lu_clean,
            sum_Lu_raw,
            calculation_time,
            sigma_Lu
        )

        conc_Lu = sum_Lu_clean * coeff_Lu
        activity_Lu = conc_Lu * volume

        conc_Lu_upper = limits_Lu["upper"] * coeff_Lu
        conc_Lu_lower = limits_Lu["lower"] * coeff_Lu

        activity_Lu_upper = conc_Lu_upper * volume
        activity_Lu_lower = conc_Lu_lower * volume

        if limits_Lu["upper"] > 0.0 and limits_Lu["lower"] > 0.0:
            detected_Lu = "Є"

        elif limits_Lu["upper"] > 0.0 and limits_Lu["lower"] <= 0.0:
            detected_Lu = "МОЖЕ БУТИ"

        else:
            detected_Lu = "НЕМАЄ"

        # ============================================================
        # 8. ФОРМУЄМО РЕЗУЛЬТАТ
        # ============================================================

        result = {
            "group": "B",

            # Порядок тут залишаємо сумісним з поточним GUI / Bridge.
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

            # Фактичний час ПК залишаємо як діагностичну інформацію.
            "real_time": real_time,

            # Додатково явно фіксуємо час, який використаний
            # у математичних формулах.
            "calculation_time": calculation_time,

            "components": {
                "iodine_scaled": arr3,
                "after_iodine_subtraction": arr4
            }
        }

        return result



    def _identify_group_reserve(
        self,
        arr1,
        arr2,
        real_time,
        volume,
        history,
        hour_valid=True,
        invalid_reason=None
    ):
        """
        Ідентифікація ізотопів для резервної цистерни ZB3.

        Ізотопи:

            - 90Y
            - 133I
            - 177Lu
            - 18F
            - 99mTc

        Алгоритм реалізовано відповідно до окремого алгоритму
        "F, Tc, I, Lu, Y" та відповідей консультанта.

        ================================================================
        ОСНОВНІ ПРАВИЛА
        ================================================================

        1. Розрахунковий час алгоритму:

                T = 3600 секунд

        незалежно від фактичного часу ПК.

        real_time передається сюди тільки як діагностичне значення.

        2. Послідовність обробки:

                ARR_1
                ↓
                ARR_2
                ↓
                90Y
                ↓
                масштабування I-131
                ↓
                ARR_3
                ↓
                133I
                ↓
                ARR_4 = ARR_2 - ARR_3
                ↓
                177Lu
                ↓
                18F
                ↓
                99mTc

        3. Для I-131:

        - масштабування базового спектра:
                115...150;

        - кінцева площа 133I:
                90...150;

        - статистична складова:
                ARR_1[90...150].

        4. Для 99mTc:

        - зона:
                12...64;

        - початкові межі:
                ± 1 sigma;

        - кожна година зберігається в історії;

        - починаючи з 7-ї години поточний цикл порівнюється
            з циклом рівно 6 годин тому:

                7 ↔ 1
                8 ↔ 2
                9 ↔ 3
                ...

        - ratio = стара_площа / поточна_площа;

        - ratio <= 2:
                алгоритм Tc + Lu;

        - ratio > 2:
                алгоритм Tc + F;

        - якщо ratio < 1.5:
                поточний результат СПОЧАТКУ розраховується
                за алгоритмом Tc + Lu,
                а екстраполяція починається тільки
                з НАСТУПНОЇ години;

        - після переходу до екстраполяції назад до
            шестигодинного алгоритму вже не повертаємося
            до спорожнення / нового заповнення цистерни;

        - екстраполяція:

                previous_upper * 0.890899
                previous_lower * 0.890899

            де upper/lower — межі ПИТОМОЇ активності Tc.

        5. Перші 6 годин остаточного результату Tc немає:

                available = False

        6. Якщо один часовий цикл неможливо коректно обробити,
        то за наявності попереднього остаточного результату Tc
        використовується екстраполяція.

        Якщо попереднього результату Tc ще немає,
        результат Tc залишається unavailable.

        7. Від'ємні значення ARR_2 / ARR_3 / ARR_4 та площ
        не обрізаються.
        """

        # ============================================================
        # 0. КОНСТАНТИ РЕЗЕРВНОГО АЛГОРИТМУ
        # ============================================================

        # За відповіддю консультанта всі часові формули
        # резервного алгоритму побудовані для одного
        # годинного циклу.
        calculation_time = 3600.0

        # Періоди напіврозпаду, які використовуються
        # саме у резервному алгоритмі.
        #
        # ВАЖЛИВО:
        # для Tc тут 360 хвилин, а НЕ 360.1 з групи A.
        tc_half_life_minutes = 360.0
        lu_half_life_minutes = 9570.0
        f_half_life_minutes = 110.0

        delay_hours = self.GROUP_RESERVE_TC_DELAY_HOURS
        extrapolation_coeff = (
            self.GROUP_RESERVE_TC_EXTRAPOLATION_COEFF
        )

        isotope_Tc = "99mTc"
        coeff_Tc = self.GROUP_RESERVE_COEFFICIENTS[
            isotope_Tc
        ]

        # ============================================================
        # 1. ПЕРЕВІРКА ОБ'ЄМУ
        # ============================================================

        try:
            volume = float(volume)

        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Reserve: об'єм цистерни повинен бути числовим."
            ) from exc

        if (
            not math.isfinite(volume)
            or volume <= 0.0
        ):
            raise ValueError(
                f"Reserve: некоректний об'єм цистерни: {volume}."
            )

        # ============================================================
        # 2. ФАКТИЧНИЙ ЧАС ПК — ТІЛЬКИ ДІАГНОСТИКА
        # ============================================================

        try:
            diagnostic_real_time = float(real_time)

        except (TypeError, ValueError):
            diagnostic_real_time = 0.0

        if not math.isfinite(diagnostic_real_time):
            diagnostic_real_time = 0.0

        # ============================================================
        # 3. ПІДГОТОВКА / ПЕРЕВІРКА ІСТОРІЇ Tc
        # ============================================================
        #
        # Старий формат history принципово відрізнявся від нового.
        #
        # Тому після оновлення програми стару або пошкоджену
        # структуру не намагаємося "вгадувати".
        #
        # Безпечніше почати шестигодинний алгоритм заново.

        history_valid = False

        if isinstance(history, dict):

            if history.get("algorithm") == "reserve":

                try:
                    hist_hour_index = int(
                        history.get("hour_index", 0)
                    )

                    hist_entries = history.get(
                        "tc_hours",
                        []
                    )

                    hist_extrapolation = bool(
                        history.get(
                            "extrapolation_started",
                            False
                        )
                    )

                    history_valid = (
                        hist_hour_index >= 0
                        and isinstance(hist_entries, list)
                    )

                except (TypeError, ValueError):
                    history_valid = False

        if not history_valid:

            history = {
                "algorithm": "reserve",

                # Номер поточного годинного циклу.
                "hour_index": 0,

                # Останні почасові початкові вимірювання Tc.
                #
                # Кожен запис містить:
                #
                #     hour
                #     timestamp
                #     valid
                #     sum_clean
                #     sum_raw
                #     upper
                #     lower
                #
                # upper/lower тут — ПОЧАТКОВІ межі площі Tc
                # з ARR_4 до шестигодинного розділення.
                "tc_hours": [],

                # Незворотний режим екстраполяції.
                "extrapolation_started": False,

                # Останні кінцеві межі ПИТОМОЇ активності Tc.
                #
                # Саме ці значення множаться на 0.890899.
                "last_result_conc_upper": None,
                "last_result_conc_lower": None,

                # До якої старої години відносився останній
                # виданий результат.
                "last_result_reference_hour": None,
                "last_result_reference_timestamp": None
            }

        # ============================================================
        # 4. НОВИЙ ГОДИННИЙ ЦИКЛ
        # ============================================================

        current_hour = (
            int(history.get("hour_index", 0))
            + 1
        )

        history["hour_index"] = current_hour

        # Час завершення саме цього спектрального циклу.
        #
        # Це не T алгоритму.
        current_timestamp = (
            QDateTime.currentDateTime().toString(
                Qt.DateFormat.ISODate
            )
        )

        # ============================================================
        # 5. ДОПОМІЖНІ ЛОКАЛЬНІ ФУНКЦІЇ
        # ============================================================

        def make_unavailable_isotope():
            """
            Формує результат ізотопу, який для поточного
            годинного циклу неможливо коректно розрахувати.
            """

            return {
                "available": False,
                "activity": None,
                "concentration": None,
                "activity_upper": None,
                "activity_lower": None,
                "conc_upper": None,
                "conc_lower": None,
                "detected": None,
                "sum_clean": None,
                "sum_raw": None,
                "limits": None
            }

        def tc_status(upper, lower):
            """
            Єдине погоджене правило ідентифікації ізотопу.
            """

            if upper > 0.0 and lower > 0.0:
                return "Є"

            if upper > 0.0 and lower <= 0.0:
                return "МОЖЕ БУТИ"

            return "НЕМАЄ"

        def get_reference_entry(reference_hour):
            """
            Повертає початковий запис Tc рівно шестигодинної
            давності.
            """

            for entry in history.get("tc_hours", []):

                if entry.get("hour") == reference_hour:
                    return entry

            return None

        def trim_history():
            """
            Для 24/7 роботи не дозволяємо списку tc_hours
            рости нескінченно.

            Для наступного циклу необхідні тільки останні
            сім годинних записів.
            """

            min_hour_to_keep = max(
                1,
                current_hour - delay_hours
            )

            history["tc_hours"] = [
                entry
                for entry in history.get("tc_hours", [])
                if entry.get("hour", 0) >= min_hour_to_keep
            ]

        def build_tc_unavailable(
            reason=None,
            reference_hour=None,
            reference_timestamp=None
        ):
            """
            Формує стан "остаточного результату Tc ще немає".
            """

            data = make_unavailable_isotope()

            data.update({
                "delay_hours": delay_hours,
                "reference_hour": reference_hour,
                "reference_timestamp": reference_timestamp,
                "extrapolated": False,
                "ratio": None,
                "reason": reason
            })

            return data

        def extrapolate_previous_tc(
            reference_hour,
            reference_timestamp,
            reason
        ):
            """
            Екстраполює ПОПЕРЕДНІ КІНЦЕВІ межі питомої
            активності Tc.

            Цей шлях використовується:

            1. після остаточного переходу в режим екстраполяції;
            2. як резервна обробка одного невдалого годинного циклу.

            ВАЖЛИВО:
            разова помилка години сама по собі НЕ переводить
            алгоритм назавжди в extrapolation_started.
            """

            try:
                previous_upper = float(
                    history.get(
                        "last_result_conc_upper"
                    )
                )

                previous_lower = float(
                    history.get(
                        "last_result_conc_lower"
                    )
                )

            except (TypeError, ValueError):

                return build_tc_unavailable(
                    reason=reason,
                    reference_hour=reference_hour,
                    reference_timestamp=reference_timestamp
                )

            if (
                not math.isfinite(previous_upper)
                or not math.isfinite(previous_lower)
            ):
                return build_tc_unavailable(
                    reason=reason,
                    reference_hour=reference_hour,
                    reference_timestamp=reference_timestamp
                )

            # --------------------------------------------------------
            # ЕКСТРАПОЛЯЦІЯ ПИТОМОЇ АКТИВНОСТІ
            # --------------------------------------------------------

            conc_upper = (
                previous_upper
                * extrapolation_coeff
            )

            conc_lower = (
                previous_lower
                * extrapolation_coeff
            )

            concentration = (
                conc_upper + conc_lower
            ) / 2.0

            # Загальна активність.
            activity = (
                concentration
                * volume
            )

            activity_upper = (
                conc_upper
                * volume
            )

            activity_lower = (
                conc_lower
                * volume
            )

            # Для сумісності result["limits"] з рештою
            # алгоритмів переводимо питомі межі назад
            # у еквівалентні межі площі.
            upper_area = (
                conc_upper / coeff_Tc
            )

            lower_area = (
                conc_lower / coeff_Tc
            )

            central_area = (
                concentration / coeff_Tc
            )

            detected = tc_status(
                conc_upper,
                conc_lower
            )

            # Цей результат стає основою для наступної
            # екстраполяції.
            history[
                "last_result_conc_upper"
            ] = conc_upper

            history[
                "last_result_conc_lower"
            ] = conc_lower

            history[
                "last_result_reference_hour"
            ] = reference_hour

            history[
                "last_result_reference_timestamp"
            ] = reference_timestamp

            return {
                "available": True,

                "activity": activity,
                "concentration": concentration,

                "activity_upper": activity_upper,
                "activity_lower": activity_lower,

                "conc_upper": conc_upper,
                "conc_lower": conc_lower,

                "detected": detected,

                "sum_clean": central_area,
                "sum_raw": None,

                "limits": {
                    "upper": upper_area,
                    "lower": lower_area
                },

                "delay_hours": delay_hours,
                "reference_hour": reference_hour,
                "reference_timestamp": reference_timestamp,

                "extrapolated": True,
                "ratio": None,
                "reason": reason
            }

        def make_invalid_hour_result(reason):
            """
            Обробляє повністю невдалий годинний цикл ZB3.

            Інші чотири ізотопи в такому циклі недоступні.

            Для Tc:
                - години 1...6: результату ще немає;
                - після 6-ї години за наявності попереднього
                результату виконуємо погоджену екстраполяцію.
            """

            # --------------------------------------------------------
            # Зберігаємо сам факт існування цієї години.
            # --------------------------------------------------------

            history["tc_hours"].append({
                "hour": current_hour,
                "timestamp": current_timestamp,
                "valid": False,
                "sum_clean": None,
                "sum_raw": None,
                "upper": None,
                "lower": None
            })

            reference_hour = (
                current_hour - delay_hours
            )

            reference_entry = (
                get_reference_entry(reference_hour)
                if reference_hour >= 1
                else None
            )

            reference_timestamp = (
                reference_entry.get("timestamp")
                if isinstance(reference_entry, dict)
                else None
            )

            # --------------------------------------------------------
            # Перші 6 годин — фінального Tc ще немає.
            # --------------------------------------------------------

            if current_hour <= delay_hours:

                tc_data = build_tc_unavailable(
                    reason=reason
                )

            else:

                # Після 6-ї години при помилці використовуємо
                # погоджену екстраполяцію попереднього
                # кінцевого результату.
                tc_data = extrapolate_previous_tc(
                    reference_hour,
                    reference_timestamp,
                    reason
                )

            trim_history()

            unavailable = make_unavailable_isotope()

            return {
                "group": "reserve",

                "isotopes": [
                    "18F",
                    "99mTc",
                    "133I",
                    "177Lu",
                    "90Y"
                ],

                "18F": dict(unavailable),

                "99mTc": tc_data,

                "133I": dict(unavailable),
                "177Lu": dict(unavailable),
                "90Y": dict(unavailable),

                "real_time": diagnostic_real_time,
                "calculation_time": calculation_time,

                # Поточний годинний спектр повністю
                # розрахувати не вдалося.
                "measurement_valid": False,

                "invalid_reason": reason,

                "history_updated": history
            }

        # ============================================================
        # 6. ЯКЩО ПОТОЧНА ГОДИНА ВЖЕ ПОЗНАЧЕНА ЯК НЕВАЛІДНА
        # ============================================================

        if not hour_valid:

            return make_invalid_hour_result(
                invalid_reason
                or
                "Некоректний годинний спектральний цикл."
            )

        # ============================================================
        # 7. ПЕРЕВІРКА ARR_1 / ARR_2
        # ============================================================

        if (
            not isinstance(
                arr1,
                (list, tuple, np.ndarray)
            )
            or
            not isinstance(
                arr2,
                (list, tuple, np.ndarray)
            )
        ):
            return make_invalid_hour_result(
                "ARR_1 або ARR_2 мають некоректний тип."
            )

        if (
            len(arr1) != 1023
            or
            len(arr2) != 1023
        ):
            return make_invalid_hour_result(
                "ARR_1 або ARR_2 мають некоректну довжину."
            )

        # ============================================================
        # 8. 90Y
        # ============================================================

        isotope_Y = "90Y"

        window_Y = self.GROUP_RESERVE_WINDOWS[
            isotope_Y
        ]

        coeff_Y = self.GROUP_RESERVE_COEFFICIENTS[
            isotope_Y
        ]

        sigma_Y = self.GROUP_RESERVE_SIGMA[
            isotope_Y
        ]

        # Центральна площа після віднімання фону.
        sum_Y_clean = self._calculate_window_sum(
            arr2,
            window_Y[0],
            window_Y[1]
        )

        # Статистична складова — з ARR_1.
        sum_Y_raw = self._calculate_window_sum(
            arr1,
            window_Y[0],
            window_Y[1]
        )

        limits_Y = self._calculate_limits(
            sum_Y_clean,
            sum_Y_raw,
            calculation_time,
            sigma_Y
        )

        conc_Y = (
            sum_Y_clean
            * coeff_Y
        )

        activity_Y = (
            conc_Y
            * volume
        )

        conc_Y_upper = (
            limits_Y["upper"]
            * coeff_Y
        )

        conc_Y_lower = (
            limits_Y["lower"]
            * coeff_Y
        )

        activity_Y_upper = (
            conc_Y_upper
            * volume
        )

        activity_Y_lower = (
            conc_Y_lower
            * volume
        )

        detected_Y = tc_status(
            limits_Y["upper"],
            limits_Y["lower"]
        )

        # ============================================================
        # 9. 133I — БАЗОВИЙ СПЕКТР
        # ============================================================

        isotope_I = "133I"

        # Кінцеве вікно активності I.
        window_I = self.GROUP_RESERVE_WINDOWS[
            isotope_I
        ]

        # Окреме вікно для масштабування базового I.
        base_window_I = (
            self.GROUP_RESERVE_BASE_I_WINDOW
        )

        coeff_I = self.GROUP_RESERVE_COEFFICIENTS[
            isotope_I
        ]

        sigma_I = self.GROUP_RESERVE_SIGMA[
            isotope_I
        ]

        # Базовий I-131 є обов'язковим.
        base_spectrum = self._load_base_spectrum(
            "base_I"
        )

        if base_spectrum is None:

            return make_invalid_hour_result(
                "Базовий спектр I-131.txt відсутній "
                "або пошкоджений."
            )

        if len(base_spectrum) != 1023:

            return make_invalid_hour_result(
                "Базовий спектр I-131 має некоректну "
                "довжину."
            )

        # ============================================================
        # 10. МАСШТАБУВАННЯ I — 115...150
        # ============================================================

        sum_I_arr2_base = (
            self._calculate_window_sum(
                arr2,
                base_window_I[0],
                base_window_I[1]
            )
        )

        sum_base_I = (
            self._calculate_window_sum(
                base_spectrum,
                base_window_I[0],
                base_window_I[1]
            )
        )

        # За інформацією консультанта базовий спектр
        # незмінний і ця площа у штатному стані
        # не повинна бути <= 0.
        #
        # Якщо це сталося, вважаємо поточний цикл
        # нерозрахованим, а НЕ змінюємо формулу.
        if (
            not math.isfinite(sum_base_I)
            or
            sum_base_I <= 0.0
        ):
            return make_invalid_hour_result(
                "Некоректна площа базового спектра "
                "I-131 у каналах 115-150."
            )

        # Поточна площа ARR_2 може бути навіть
        # нульовою або від'ємною.
        scale_I = (
            sum_I_arr2_base
            / sum_base_I
        )

        if not math.isfinite(scale_I):

            return make_invalid_hour_result(
                "Некоректний коефіцієнт "
                "масштабування I-131."
            )

        # ============================================================
        # 11. ARR_3
        # ============================================================

        arr3 = [
            value * scale_I
            for value in base_spectrum
        ]

        if any(
            not math.isfinite(value)
            for value in arr3
        ):
            return make_invalid_hour_result(
                "ARR_3 містить некоректні значення."
            )

        # ============================================================
        # 12. КІНЦЕВИЙ 133I — 90...150
        # ============================================================

        sum_I_clean = (
            self._calculate_window_sum(
                arr3,
                window_I[0],
                window_I[1]
            )
        )

        # За уточненням консультанта:
        #
        # під квадратним коренем для I
        # використовується ARR_1[90..150].
        sum_I_raw = (
            self._calculate_window_sum(
                arr1,
                window_I[0],
                window_I[1]
            )
        )

        limits_I = self._calculate_limits(
            sum_I_clean,
            sum_I_raw,
            calculation_time,
            sigma_I
        )

        conc_I = (
            sum_I_clean
            * coeff_I
        )

        activity_I = (
            conc_I
            * volume
        )

        conc_I_upper = (
            limits_I["upper"]
            * coeff_I
        )

        conc_I_lower = (
            limits_I["lower"]
            * coeff_I
        )

        activity_I_upper = (
            conc_I_upper
            * volume
        )

        activity_I_lower = (
            conc_I_lower
            * volume
        )

        detected_I = tc_status(
            limits_I["upper"],
            limits_I["lower"]
        )

        # ============================================================
        # 13. ARR_4 = ARR_2 - ARR_3
        # ============================================================

        arr4 = [
            arr2[i] - arr3[i]
            for i in range(1023)
        ]

        # Від'ємні значення ARR_4 ДОПУСТИМІ.
        #
        # Перевіряємо тільки NaN / inf.
        if any(
            not math.isfinite(value)
            for value in arr4
        ):
            return make_invalid_hour_result(
                "ARR_4 містить некоректні значення."
            )

        # ============================================================
        # 14. 177Lu
        # ============================================================

        isotope_Lu = "177Lu"

        window_Lu = self.GROUP_RESERVE_WINDOWS[
            isotope_Lu
        ]

        coeff_Lu = self.GROUP_RESERVE_COEFFICIENTS[
            isotope_Lu
        ]

        sigma_Lu = self.GROUP_RESERVE_SIGMA[
            isotope_Lu
        ]

        sum_Lu_clean = (
            self._calculate_window_sum(
                arr4,
                window_Lu[0],
                window_Lu[1]
            )
        )

        sum_Lu_raw = (
            self._calculate_window_sum(
                arr1,
                window_Lu[0],
                window_Lu[1]
            )
        )

        limits_Lu = self._calculate_limits(
            sum_Lu_clean,
            sum_Lu_raw,
            calculation_time,
            sigma_Lu
        )

        conc_Lu = (
            sum_Lu_clean
            * coeff_Lu
        )

        activity_Lu = (
            conc_Lu
            * volume
        )

        conc_Lu_upper = (
            limits_Lu["upper"]
            * coeff_Lu
        )

        conc_Lu_lower = (
            limits_Lu["lower"]
            * coeff_Lu
        )

        activity_Lu_upper = (
            conc_Lu_upper
            * volume
        )

        activity_Lu_lower = (
            conc_Lu_lower
            * volume
        )

        detected_Lu = tc_status(
            limits_Lu["upper"],
            limits_Lu["lower"]
        )

        # ============================================================
        # 15. 18F
        # ============================================================

        isotope_F = "18F"

        window_F = self.GROUP_RESERVE_WINDOWS[
            isotope_F
        ]

        coeff_F = self.GROUP_RESERVE_COEFFICIENTS[
            isotope_F
        ]

        sigma_F = self.GROUP_RESERVE_SIGMA[
            isotope_F
        ]

        sum_F_clean = (
            self._calculate_window_sum(
                arr4,
                window_F[0],
                window_F[1]
            )
        )

        sum_F_raw = (
            self._calculate_window_sum(
                arr1,
                window_F[0],
                window_F[1]
            )
        )

        limits_F = self._calculate_limits(
            sum_F_clean,
            sum_F_raw,
            calculation_time,
            sigma_F
        )

        conc_F = (
            sum_F_clean
            * coeff_F
        )

        activity_F = (
            conc_F
            * volume
        )

        conc_F_upper = (
            limits_F["upper"]
            * coeff_F
        )

        conc_F_lower = (
            limits_F["lower"]
            * coeff_F
        )

        activity_F_upper = (
            conc_F_upper
            * volume
        )

        activity_F_lower = (
            conc_F_lower
            * volume
        )

        detected_F = tc_status(
            limits_F["upper"],
            limits_F["lower"]
        )

        # ============================================================
        # 16. ПОТОЧНИЙ ПОЧАТКОВИЙ РОЗРАХУНОК 99mTc
        # ============================================================

        window_Tc = self.GROUP_RESERVE_WINDOWS[
            isotope_Tc
        ]

        sigma_Tc = self.GROUP_RESERVE_SIGMA[
            isotope_Tc
        ]

        # Поточна площа Tc після вилучення I.
        sum_Tc_clean_current = (
            self._calculate_window_sum(
                arr4,
                window_Tc[0],
                window_Tc[1]
            )
        )

        # Статистична складова Tc з ARR_1.
        sum_Tc_raw_current = (
            self._calculate_window_sum(
                arr1,
                window_Tc[0],
                window_Tc[1]
            )
        )

        current_limits_Tc = (
            self._calculate_limits(
                sum_Tc_clean_current,
                sum_Tc_raw_current,
                calculation_time,
                sigma_Tc
            )
        )

        # ============================================================
        # 17. ЗБЕРІГАЄМО ПОТОЧНУ ГОДИНУ Tc
        # ============================================================

        current_tc_entry = {
            "hour": current_hour,
            "timestamp": current_timestamp,
            "valid": True,

            "sum_clean": sum_Tc_clean_current,
            "sum_raw": sum_Tc_raw_current,

            "upper": current_limits_Tc["upper"],
            "lower": current_limits_Tc["lower"]
        }

        history["tc_hours"].append(
            current_tc_entry
        )

        # ============================================================
        # 18. ПЕРШІ ШІСТЬ ГОДИН
        # ============================================================
        #
        # Ми вже зберегли:
        #
        #     - площу;
        #     - upper;
        #     - lower;
        #     - timestamp.
        #
        # Але фінального результату Tc ще немає.

        if current_hour <= delay_hours:

            tc_data = build_tc_unavailable(
                reason=(
                    "Для розрахунку 99mTc необхідно "
                    "накопичити 6 годин історії."
                )
            )

            trim_history()

            result = {
                "group": "reserve",

                "isotopes": [
                    "18F",
                    "99mTc",
                    "133I",
                    "177Lu",
                    "90Y"
                ],

                "18F": {
                    "available": True,
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

                "99mTc": tc_data,

                "133I": {
                    "available": True,
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
                    "available": True,
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
                    "available": True,
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

                "real_time": diagnostic_real_time,
                "calculation_time": calculation_time,

                "measurement_valid": True,

                "components": {
                    "iodine_scaled": arr3,
                    "after_iodine_subtraction": arr4
                },

                "history_updated": history
            }

            return result

        # ============================================================
        # 19. ВИЗНАЧАЄМО ГОДИНУ 6 ГОДИН ТОМУ
        # ============================================================

        reference_hour = (
            current_hour
            - delay_hours
        )

        reference_entry = get_reference_entry(
            reference_hour
        )

        reference_timestamp = (
            reference_entry.get("timestamp")
            if isinstance(reference_entry, dict)
            else None
        )

        # ============================================================
        # 20. ЯКЩО МИ ВЖЕ У ПОСТІЙНІЙ ЕКСТРАПОЛЯЦІЇ
        # ============================================================
        #
        # Після ratio < 1.5 повернення до ratio / p17 / p18
        # більше немає до нового заповнення цистерни.

        if history.get(
            "extrapolation_started",
            False
        ):

            tc_data = extrapolate_previous_tc(
                reference_hour,
                reference_timestamp,
                "Постійний режим екстраполяції 99mTc."
            )

            trim_history()

        else:

            # ========================================================
            # 21. ПЕРЕВІРЯЄМО ШЕСТИГОДИННИЙ ОПОРНИЙ ЗАПИС
            # ========================================================

            reference_valid = (
                isinstance(reference_entry, dict)
                and reference_entry.get("valid") is True
            )

            if not reference_valid:

                # Немає коректного вимірювання рівно 6 годин тому.
                #
                # За погодженим правилом використовуємо
                # екстраполяцію попереднього кінцевого результату,
                # якщо він уже існує.
                tc_data = extrapolate_previous_tc(
                    reference_hour,
                    reference_timestamp,
                    (
                        "Відсутній коректний Tc-запис "
                        "рівно 6 годин тому."
                    )
                )

                trim_history()

            else:

                # ====================================================
                # 22. ОТРИМУЄМО СТАРІ ДАНІ Tc
                # ====================================================

                try:
                    old_sum = float(
                        reference_entry["sum_clean"]
                    )

                    old_upper = float(
                        reference_entry["upper"]
                    )

                    old_lower = float(
                        reference_entry["lower"]
                    )

                except (
                    KeyError,
                    TypeError,
                    ValueError
                ):

                    tc_data = extrapolate_previous_tc(
                        reference_hour,
                        reference_timestamp,
                        "Пошкоджений шестигодинний Tc-запис."
                    )

                    trim_history()

                else:

                    # ================================================
                    # 23. RATIO
                    # ================================================
                    #
                    # Порівнюємо площу шестигодинної давності
                    # з поточною:
                    #
                    #     ratio = OLD / CURRENT
                    #
                    # Для Tc з періодом близько 6 годин таке
                    # відношення природно знаходиться біля 2.

                    if (
                        not math.isfinite(
                            sum_Tc_clean_current
                        )
                        or
                        abs(
                            sum_Tc_clean_current
                        ) < 1e-12
                    ):

                        # Ділення на нуль або практично нуль
                        # неможливе.
                        #
                        # Алгоритм не підміняємо вигаданим ratio.
                        tc_data = extrapolate_previous_tc(
                            reference_hour,
                            reference_timestamp,
                            (
                                "Неможливо визначити ratio Tc: "
                                "поточна площа дорівнює нулю."
                            )
                        )

                        trim_history()

                    else:

                        ratio = (
                            old_sum
                            / sum_Tc_clean_current
                        )

                        if not math.isfinite(ratio):

                            tc_data = extrapolate_previous_tc(
                                reference_hour,
                                reference_timestamp,
                                "Отримано некоректний ratio Tc."
                            )

                            trim_history()

                        else:

                            # ========================================
                            # 24. КОЕФІЦІЄНТИ РОЗПАДУ ЗА 6 ГОДИН
                            # ========================================

                            six_hours_seconds = (
                                calculation_time
                                * delay_hours
                            )

                            K_Tc = (
                                self._calculate_decay_coefficient(
                                    six_hours_seconds,
                                    tc_half_life_minutes
                                )
                            )

                            K_Lu = (
                                self._calculate_decay_coefficient(
                                    six_hours_seconds,
                                    lu_half_life_minutes
                                )
                            )

                            K_F = (
                                self._calculate_decay_coefficient(
                                    six_hours_seconds,
                                    f_half_life_minutes
                                )
                            )

                            if (
                                not math.isfinite(K_Tc)
                                or
                                not math.isfinite(K_Lu)
                                or
                                not math.isfinite(K_F)
                            ):
                                tc_data = extrapolate_previous_tc(
                                    reference_hour,
                                    reference_timestamp,
                                    (
                                        "Некоректні коефіцієнти "
                                        "розпаду Tc/Lu/F."
                                    )
                                )

                                trim_history()

                            else:

                                # ====================================
                                # 25. ВИБІР p17 / p18
                                # ====================================
                                #
                                # ratio < 1.5:
                                #
                                #     ПОТОЧНИЙ результат все одно
                                #     рахуємо за p17 Tc+Lu;
                                #
                                #     тільки НАСТУПНІ години
                                #     переходять на екстраполяцію.
                                #
                                # ratio == 1.5:
                                #
                                #     звичайний режим.
                                #
                                # ratio <= 2:
                                #
                                #     p17 Tc+Lu.
                                #
                                # ratio > 2:
                                #
                                #     p18 Tc+F.

                                use_p17 = (
                                    ratio <= 2.0
                                )

                                start_extrapolation_after_this = (
                                    ratio < 1.5
                                )

                                if use_p17:

                                    denominator = (
                                        K_Tc - K_Lu
                                    )

                                    if abs(denominator) < 1e-12:

                                        tc_data = (
                                            extrapolate_previous_tc(
                                                reference_hour,
                                                reference_timestamp,
                                                (
                                                    "K_Tc - K_Lu "
                                                    "занадто малий."
                                                )
                                            )
                                        )

                                        trim_history()

                                    else:

                                        # ============================
                                        # p17 — Tc + Lu
                                        # ============================
                                        #
                                        # Перехресні upper/lower
                                        # підтверджені консультантом.
                                        #
                                        # ВАЖЛИВО:
                                        # old_upper / old_lower —
                                        # це СТАРІ МЕЖІ Tc,
                                        # а не межі Lu або Y.

                                        dynamic_upper = (
                                            current_limits_Tc["lower"]
                                            - K_Lu * old_upper
                                        ) / denominator

                                        dynamic_lower = (
                                            current_limits_Tc["upper"]
                                            - K_Lu * old_lower
                                        ) / denominator

                                        # Межі ПИТОМОЇ активності.
                                        conc_Tc_upper = (
                                            dynamic_upper
                                            * coeff_Tc
                                        )

                                        conc_Tc_lower = (
                                            dynamic_lower
                                            * coeff_Tc
                                        )

                                        # Центральна питома активність
                                        # за прямою вказівкою консультанта.
                                        conc_Tc = (
                                            conc_Tc_upper
                                            + conc_Tc_lower
                                        ) / 2.0

                                        activity_Tc = (
                                            conc_Tc
                                            * volume
                                        )

                                        activity_Tc_upper = (
                                            conc_Tc_upper
                                            * volume
                                        )

                                        activity_Tc_lower = (
                                            conc_Tc_lower
                                            * volume
                                        )

                                        detected_Tc = tc_status(
                                            conc_Tc_upper,
                                            conc_Tc_lower
                                        )

                                        history[
                                            "last_result_conc_upper"
                                        ] = conc_Tc_upper

                                        history[
                                            "last_result_conc_lower"
                                        ] = conc_Tc_lower

                                        history[
                                            "last_result_reference_hour"
                                        ] = reference_hour

                                        history[
                                            "last_result_reference_timestamp"
                                        ] = reference_timestamp

                                        # Перехід у постійну
                                        # екстраполяцію відбудеться
                                        # вже з НАСТУПНОЇ години.
                                        if (
                                            start_extrapolation_after_this
                                        ):
                                            history[
                                                "extrapolation_started"
                                            ] = True

                                        tc_data = {
                                            "available": True,

                                            "activity": activity_Tc,
                                            "concentration": conc_Tc,

                                            "activity_upper":
                                                activity_Tc_upper,

                                            "activity_lower":
                                                activity_Tc_lower,

                                            "conc_upper":
                                                conc_Tc_upper,

                                            "conc_lower":
                                                conc_Tc_lower,

                                            "detected":
                                                detected_Tc,

                                            # Центральний еквівалент
                                            # площі.
                                            "sum_clean": (
                                                dynamic_upper
                                                + dynamic_lower
                                            ) / 2.0,

                                            # Для діагностики
                                            # залишаємо стару raw-площу,
                                            # до якої відноситься результат.
                                            "sum_raw":
                                                reference_entry.get(
                                                    "sum_raw"
                                                ),

                                            "limits": {
                                                "upper":
                                                    dynamic_upper,
                                                "lower":
                                                    dynamic_lower
                                            },

                                            "delay_hours":
                                                delay_hours,

                                            "reference_hour":
                                                reference_hour,

                                            "reference_timestamp":
                                                reference_timestamp,

                                            "ratio": ratio,

                                            "algorithm":
                                                "Tc+Lu",

                                            "extrapolated": False,

                                            "extrapolation_starts_next":
                                                start_extrapolation_after_this
                                        }

                                        trim_history()

                                else:

                                    denominator = (
                                        K_Tc - K_F
                                    )

                                    if abs(denominator) < 1e-12:

                                        tc_data = (
                                            extrapolate_previous_tc(
                                                reference_hour,
                                                reference_timestamp,
                                                (
                                                    "K_Tc - K_F "
                                                    "занадто малий."
                                                )
                                            )
                                        )

                                        trim_history()

                                    else:

                                        # ============================
                                        # p18 — Tc + F
                                        # ============================
                                        #
                                        # Як і у p17,
                                        # old_upper / old_lower —
                                        # це СТАРІ МЕЖІ Tc.

                                        dynamic_upper = (
                                            current_limits_Tc["lower"]
                                            - K_F * old_upper
                                        ) / denominator

                                        dynamic_lower = (
                                            current_limits_Tc["upper"]
                                            - K_F * old_lower
                                        ) / denominator

                                        conc_Tc_upper = (
                                            dynamic_upper
                                            * coeff_Tc
                                        )

                                        conc_Tc_lower = (
                                            dynamic_lower
                                            * coeff_Tc
                                        )

                                        conc_Tc = (
                                            conc_Tc_upper
                                            + conc_Tc_lower
                                        ) / 2.0

                                        activity_Tc = (
                                            conc_Tc
                                            * volume
                                        )

                                        activity_Tc_upper = (
                                            conc_Tc_upper
                                            * volume
                                        )

                                        activity_Tc_lower = (
                                            conc_Tc_lower
                                            * volume
                                        )

                                        detected_Tc = tc_status(
                                            conc_Tc_upper,
                                            conc_Tc_lower
                                        )

                                        history[
                                            "last_result_conc_upper"
                                        ] = conc_Tc_upper

                                        history[
                                            "last_result_conc_lower"
                                        ] = conc_Tc_lower

                                        history[
                                            "last_result_reference_hour"
                                        ] = reference_hour

                                        history[
                                            "last_result_reference_timestamp"
                                        ] = reference_timestamp

                                        tc_data = {
                                            "available": True,

                                            "activity":
                                                activity_Tc,

                                            "concentration":
                                                conc_Tc,

                                            "activity_upper":
                                                activity_Tc_upper,

                                            "activity_lower":
                                                activity_Tc_lower,

                                            "conc_upper":
                                                conc_Tc_upper,

                                            "conc_lower":
                                                conc_Tc_lower,

                                            "detected":
                                                detected_Tc,

                                            "sum_clean": (
                                                dynamic_upper
                                                + dynamic_lower
                                            ) / 2.0,

                                            "sum_raw":
                                                reference_entry.get(
                                                    "sum_raw"
                                                ),

                                            "limits": {
                                                "upper":
                                                    dynamic_upper,
                                                "lower":
                                                    dynamic_lower
                                            },

                                            "delay_hours":
                                                delay_hours,

                                            "reference_hour":
                                                reference_hour,

                                            "reference_timestamp":
                                                reference_timestamp,

                                            "ratio":
                                                ratio,

                                            "algorithm":
                                                "Tc+F",

                                            "extrapolated":
                                                False,

                                            "extrapolation_starts_next":
                                                False
                                        }

                                        trim_history()

        # ============================================================
        # 26. ФОРМУЄМО ЗАГАЛЬНИЙ РЕЗУЛЬТАТ
        # ============================================================

        result = {
            "group": "reserve",

            # Порядок залишаємо стабільним для GUI / Bridge.
            "isotopes": [
                "18F",
                "99mTc",
                "133I",
                "177Lu",
                "90Y"
            ],

            "18F": {
                "available": True,

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

            "99mTc": tc_data,

            "133I": {
                "available": True,

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
                "available": True,

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
                "available": True,

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

            # Фактичне ПК-часове значення.
            "real_time": diagnostic_real_time,

            # Реальне математичне T алгоритму.
            "calculation_time": calculation_time,

            "measurement_valid": True,

            "components": {
                "iodine_scaled": arr3,
                "after_iodine_subtraction": arr4
            },

            "history_updated": history
        }

        return result





    def identify_isotopes_alim(
        self,
        spectrum,
        cistern_position,
        history=None
    ):
        """
        Головний вхід у алгоритм ідентифікації ALIM.

        Формат spectrum:

            1023 спектральні канали
            +
            фактичний час спектрального циклу ПК.

        ================================================================
        ЧАСОВА СЕМАНТИКА
        ================================================================

        actual_cycle_time:
            фактичний час циклу, виміряний ПК.

        calculation_time:
            час T, який використовується у математичному алгоритмі.

        За відповідями консультанта:

            група B:
                T = 3600 с

            reserve / ZB3:
                T = 3600 с

        Отже для цих алгоритмів:

            T1 = 3600 - DEAD_TIME_COEFF * sum(k)

        Фактичний час ПК залишається тільки діагностичною
        інформацією і не впливає на математичне T.

        Для групи A на цьому етапі залишаємо поточну поведінку.
        """

        # ============================================================
        # 1. БЕЗПЕЧНА ПОЧАТКОВА ІСТОРІЯ
        # ============================================================

        safe_history = (
            history
            if isinstance(history, dict)
            else {}
        )

        # ============================================================
        # 2. ПЕРЕВІРЯЄМО ФОРМАТ СПЕКТРУ
        # ============================================================

        if not isinstance(
            spectrum,
            (list, tuple, np.ndarray)
        ):
            self.ui.textEdit.append(
                "Помилка ALIM: спектр має некоректний тип."
            )
            return None, safe_history

        if len(spectrum) != 1024:
            self.ui.textEdit.append(
                f"Помилка ALIM: очікується 1024 значення "
                f"(1023 канали + T), отримано {len(spectrum)}."
            )
            return None, safe_history

        # ============================================================
        # 3. ФАКТИЧНИЙ ЧАС ЦИКЛУ ПК
        # ============================================================

        try:
            actual_cycle_time = float(
                spectrum[1023]
            )

        except (TypeError, ValueError):

            self.ui.textEdit.append(
                "Помилка ALIM: фактичний час накопичення "
                "не є числом."
            )

            return None, safe_history

        if (
            not math.isfinite(actual_cycle_time)
            or
            actual_cycle_time <= 0.0
        ):
            self.ui.textEdit.append(
                f"Помилка ALIM: некоректний фактичний "
                f"час циклу={actual_cycle_time}."
            )

            return None, safe_history

        # ============================================================
        # 4. ВИЗНАЧАЄМО ГРУПУ ДО НОРМУВАННЯ
        # ============================================================
        #
        # Це принципово важливо.
        #
        # Для B та reserve необхідно знати групу ДО створення ARR_1,
        # тому що для них T1 повинен розраховуватися від T=3600.

        if cistern_position not in self.cistern_groups:

            self.ui.textEdit.append(
                f"Помилка ALIM: невідомий номер цистерни "
                f"{cistern_position}."
            )

            return None, safe_history

        group = self.cistern_groups[
            cistern_position
        ]

        # ============================================================
        # 5. ОТРИМУЄМО ОБ'ЄМ ЦИСТЕРНИ
        # ============================================================

        volume = self._get_cistern_volume(
            cistern_position
        )

        try:
            volume = float(volume)

        except (TypeError, ValueError):

            self.ui.textEdit.append(
                f"Помилка ALIM: некоректний об'єм "
                f"цистерни {cistern_position}."
            )

            return None, safe_history

        if (
            not math.isfinite(volume)
            or
            volume <= 0.0
        ):
            self.ui.textEdit.append(
                f"Помилка ALIM: некоректний об'єм "
                f"цистерни {cistern_position}: {volume}."
            )

            return None, safe_history

        # ============================================================
        # 6. ВИЗНАЧАЄМО РОЗРАХУНКОВИЙ T
        # ============================================================

        if group in ("B", "reserve"):

            # --------------------------------------------------------
            # Для трьохізотопного алгоритму групи B
            # та п'ятиізотопного резервного алгоритму ZB3
            # консультант підтвердив:
            #
            #               T = 3600 секунд.
            # --------------------------------------------------------

            calculation_time = 3600.0

        else:

            # --------------------------------------------------------
            # Групу A зараз не змінюємо в рамках п.15.
            # --------------------------------------------------------

            calculation_time = actual_cycle_time

        # ============================================================
        # 7. ДОПОМІЖНА ОБРОБКА НЕВАЛІДНОЇ ГОДИНИ RESERVE
        # ============================================================
        #
        # У резервному алгоритмі важливо не просто пропустити
        # невдалий спектр.
        #
        # Якщо пропустити годину, послідовність:
        #
        #       7 ↔ 1
        #       8 ↔ 2
        #       9 ↔ 3
        #
        # буде порушена.
        #
        # Тому резервний алгоритм повинен знати, що фізично
        # годинний цикл відбувся, але результат спектру невалідний.

        def process_invalid_reserve_hour(reason):
            """
            Передає невалідну годину в алгоритм ZB3.

            Сам _identify_group_reserve() вирішує:

            - якщо кінцевого Tc ще немає -> available=False;
            - якщо попередній Tc вже є -> екстраполяція;
            - інші ізотопи поточного невалідного спектру
            залишаються unavailable.
            """

            if group != "reserve":
                return None, safe_history

            self.ui.textEdit.append(
                f"ZB3: поточний спектральний цикл "
                f"позначено як невалідний: {reason}"
            )

            result = self._identify_group_reserve(
                None,
                None,
                actual_cycle_time,
                volume,
                safe_history,
                hour_valid=False,
                invalid_reason=reason
            )

            if not result:
                return None, safe_history

            updated_history = result.pop(
                "history_updated",
                safe_history
            )

            return result, updated_history

        # ============================================================
        # 8. ПЕРЕВІРЯЄМО СИРІ 1023 КАНАЛИ
        # ============================================================

        raw_spectrum = []

        for index, value in enumerate(
            spectrum[:1023]
        ):

            try:
                value_f = float(value)

            except (TypeError, ValueError):

                reason = (
                    f"канал {index} не є числом"
                )

                if group == "reserve":
                    return process_invalid_reserve_hour(
                        reason
                    )

                self.ui.textEdit.append(
                    f"Помилка ALIM: {reason}."
                )

                return None, safe_history

            # --------------------------------------------------------
            # Сирі відліки детектора повинні бути:
            #
            #     - скінченними;
            #     - не від'ємними.
            #
            # Від'ємні значення дозволяються вже пізніше,
            # після віднімання фону в ARR_2 / ARR_4.
            # --------------------------------------------------------

            if (
                not math.isfinite(value_f)
                or
                value_f < 0.0
            ):

                reason = (
                    f"некоректне значення каналу "
                    f"{index}: {value_f}"
                )

                if group == "reserve":
                    return process_invalid_reserve_hour(
                        reason
                    )

                self.ui.textEdit.append(
                    f"Помилка ALIM: {reason}."
                )

                return None, safe_history

            raw_spectrum.append(
                value_f
            )

        # ============================================================
        # 9. ARR_1 — НОРМУВАННЯ З УРАХУВАННЯМ МЕРТВОГО ЧАСУ
        # ============================================================
        #
        # Для B / reserve:
        #
        #     calculation_time = 3600
        #
        # тому всередині _normalize_spectrum():
        #
        #     T1 = 3600 - DEAD_TIME_COEFF * sum(k)
        #
        # Для A поки використовується фактичний час.

        arr1 = self._normalize_spectrum(
            raw_spectrum,
            calculation_time
        )

        if arr1 is None:

            sum_k = math.fsum(
                raw_spectrum
            )

            corrected_time = (
                calculation_time
                - self.DEAD_TIME_COEFF * sum_k
            )

            reason = (
                "неможливо виконати нормування спектру "
                f"(T={calculation_time:.6f} с, "
                f"T1={corrected_time:.6f} с)"
            )

            if group == "reserve":

                return process_invalid_reserve_hour(
                    reason
                )

            self.ui.textEdit.append(
                f"Помилка ALIM: {reason}."
            )

            return None, safe_history

        # ============================================================
        # 10. ARR_2 — ВІДНІМАННЯ ФОНУ
        # ============================================================

        arr2 = self._subtract_background(
            arr1
        )

        if arr2 is None:

            reason = (
                "коректний background.txt недоступний; "
                "розрахунок без віднімання фону заборонено"
            )

            if group == "reserve":

                return process_invalid_reserve_hour(
                    reason
                )

            self.ui.textEdit.append(
                f"Помилка ALIM: {reason}."
            )

            return None, safe_history

        # ============================================================
        # 11. ВИКЛИКАЄМО АЛГОРИТМ ПОТРІБНОЇ ГРУПИ
        # ============================================================

        if group == "A":

            result = self._identify_group_A(
                arr1,
                arr2,
                calculation_time,
                volume,
                safe_history
            )

            if not result:
                return None, safe_history

            updated_history = result.pop(
                "history_updated",
                {}
            )

        elif group == "B":

            result = self._identify_group_B(
                arr1,
                arr2,

                # Фактичний час передається тільки
                # як діагностичне значення.
                actual_cycle_time,

                volume
            )

            if not result:
                return None, safe_history

            updated_history = {}

        elif group == "reserve":

            result = self._identify_group_reserve(
                arr1,
                arr2,

                # Усередині reserve T вже жорстко 3600.
                # actual_cycle_time потрібен для діагностики.
                actual_cycle_time,

                volume,
                safe_history,

                hour_valid=True
            )

            if not result:
                return None, safe_history

            updated_history = result.pop(
                "history_updated",
                safe_history
            )

        else:

            self.ui.textEdit.append(
                f"Помилка ALIM: невідома група "
                f"цистерни '{group}'."
            )

            return None, safe_history

        # ============================================================
        # 12. ДІАГНОСТИЧНА ІНФОРМАЦІЯ ПРО ЧАС
        # ============================================================

        if isinstance(result, dict):

            # Фактичний час ПК.
            result["real_time"] = (
                actual_cycle_time
            )

            # Час, використаний математичним алгоритмом.
            result["calculation_time"] = (
                calculation_time
            )

        # ============================================================
        # 13. ПОВЕРТАЄМО РЕЗУЛЬТАТ
        # ============================================================

        return result, updated_history  

    



    def _send_zb_data(self, zb_list):
        """
        Відправляє дані цистерн (ZB) до Bridge.
        
        Вхід:
            zb_list - список об'єктів ZB, кожен з яких містить поля:
                number, sn, temperature, paed, high_sensitivity, low_sensitivity,
                valid, device_connection, ready_to_drain, isotopes (масив)
        
        Якщо Bridge не підключений — виводить попередження в textEdit і не відправляє.
        """
        if not self.is_bridge_connected():
            self.ui.textEdit.append("[ZB] Bridge не підключений, дані не відправлені")
            return
        
        if not zb_list:
            return
        
        try:
            if not self.modbus_client.send_zb(zb_list):
                self.ui.textEdit.append("[ZB] Помилка при відправці даних")
        except Exception as e:
            self.ui.textEdit.append(f"[ZB] Виняток при відправці: {e}")

    def _send_cz_data(self, cz_list):
        """
        Відправляє дані настінних детекторів (CZ) до Bridge.
        
        Вхід:
            cz_list - список об'єктів CZ, кожен з яких містить поля:
                number, sn, temperature, paed, high_sensitivity, low_sensitivity,
                valid, device_connection
        
        Якщо Bridge не підключений — виводить попередження в textEdit і не відправляє.
        """
        if not self.is_bridge_connected():
            self.ui.textEdit.append("[CZ] Bridge не підключений, дані не відправлені")
            return
        
        if not cz_list:
            return
        
        try:
            if not self.modbus_client.send_cz(cz_list):
                self.ui.textEdit.append("[CZ] Помилка при відправці даних")
        except Exception as e:
            self.ui.textEdit.append(f"[CZ] Виняток при відправці: {e}")
























    def _calculate_ready_to_drain(
        self,
        posit_number,
        activity_upper_dict,
        concentration_upper_dict
    ):
        """
        Розрахунок готовності цистерни до зливу відповідно до
        прийнятої для проєкту інтерпретації вимог Закону / постанови 1320.

        ================================================================
        ПРИЙНЯТІ ПРАВИЛА
        ================================================================

        1. Для концентрації приймаємо:

                1 кг рідини == 1 літр

        Тому результати програми:

                Бк/л

        переводимо у нормативні:

                кБк/кг

        за формулою:

                C_kBq_kg = C_Bq_l / 1000

        2. Для перестраховки при ready_to_drain використовуємо
        НЕ центральні значення, а ВЕРХНІ статистичні межі:

                activity_upper
                conc_upper

        3. Якщо верхня статистична межа вийшла від'ємною,
        її нормативний внесок приймаємо рівним нулю:

                max(value, 0)

        4. Для суміші ізотопів обчислюємо:

                activity_ratio_sum =
                    Σ(A_upper_i / A0_i)

                concentration_ratio_sum =
                    Σ(C_upper_i / C0_i)

        5. Злив дозволяється тільки якщо ОБИДВІ умови виконані:

                concentration_ratio_sum <= 1

                activity_ratio_sum <= 1000

        6. Якщо хоча б одного необхідного результату немає,
        він має неправильний тип, NaN або inf:

                ready_to_drain = 0

        Тобто будь-яка невизначеність трактується безпечно.
        """

        # ============================================================
        # 1. ПЕРЕВІРКА ВХІДНИХ СЛОВНИКІВ
        # ============================================================

        if not isinstance(activity_upper_dict, dict):
            return 0

        if not isinstance(concentration_upper_dict, dict):
            return 0

        # ============================================================
        # 2. ВИЗНАЧАЄМО ГРУПУ ЦИСТЕРНИ
        # ============================================================

        group = self.cistern_groups.get(
            posit_number
        )

        if group not in (
            "A",
            "B",
            "reserve"
        ):
            return 0

        # ============================================================
        # 3. НОРМАТИВНІ ЗНАЧЕННЯ
        # ============================================================
        #
        # activity_limit:
        #     Бк
        #
        # concentration_limit:
        #     кБк/кг
        #
        # Для концентрації програма передає Бк/л,
        # тому перед порівнянням виконується / 1000.
        #
        # I-133:
        #     10 кБк/кг,
        # а НЕ 100 кБк/кг.

        limits = {
            "18F": {
                "activity": 1_000_000.0,
                "concentration": 10.0
            },

            "99mTc": {
                "activity": 10_000_000.0,
                "concentration": 100.0
            },

            "133I": {
                "activity": 1_000_000.0,
                "concentration": 10.0
            },

            "177Lu": {
                "activity": 10_000_000.0,
                "concentration": 1000.0
            },

            "90Y": {
                "activity": 100_000.0,
                "concentration": 1000.0
            }
        }

        # ============================================================
        # 4. ЯКІ ІЗОТОПИ ПОВИННІ БУТИ ДЛЯ КОЖНОЇ ГРУПИ
        # ============================================================

        if group == "A":

            required_isotopes = (
                "18F",
                "99mTc"
            )

        elif group == "B":

            required_isotopes = (
                "133I",
                "177Lu",
                "90Y"
            )

        else:

            # ZB3 — одна суміш усіх п'яти ізотопів.
            #
            # Не ділимо її штучно на групу A + групу B.
            required_isotopes = (
                "18F",
                "99mTc",
                "133I",
                "177Lu",
                "90Y"
            )

        # ============================================================
        # 5. РОЗРАХОВУЄМО НОРМОВАНІ СУМИ
        # ============================================================

        activity_ratio_sum = 0.0
        concentration_ratio_sum = 0.0

        for isotope in required_isotopes:

            # --------------------------------------------------------
            # Відсутність хоча б одного обов'язкового результату
            # означає, що рішення про злив приймати не можна.
            # --------------------------------------------------------

            if isotope not in activity_upper_dict:
                return 0

            if isotope not in concentration_upper_dict:
                return 0

            try:
                activity_upper = float(
                    activity_upper_dict[isotope]
                )

                concentration_upper_bq_l = float(
                    concentration_upper_dict[isotope]
                )

            except (TypeError, ValueError):
                return 0

            # --------------------------------------------------------
            # NaN / inf категорично не допускаємо.
            # --------------------------------------------------------

            if not math.isfinite(activity_upper):
                return 0

            if not math.isfinite(
                concentration_upper_bq_l
            ):
                return 0

            # --------------------------------------------------------
            # За погодженим правилом негативний статистичний
            # результат не повинен компенсувати позитивний внесок
            # іншого ізотопу.
            #
            # Тому:
            #
            #     negative -> 0
            # --------------------------------------------------------

            activity_upper = max(
                activity_upper,
                0.0
            )

            concentration_upper_bq_l = max(
                concentration_upper_bq_l,
                0.0
            )

            # --------------------------------------------------------
            # Переведення:
            #
            #     Бк/л -> кБк/кг
            #
            # при прийнятому:
            #
            #     1 кг == 1 л
            # --------------------------------------------------------

            concentration_upper_kbq_kg = (
                concentration_upper_bq_l
                / 1000.0
            )

            isotope_limits = limits[
                isotope
            ]

            activity_limit = float(
                isotope_limits["activity"]
            )

            concentration_limit = float(
                isotope_limits["concentration"]
            )

            # Додатковий захист від помилки констант.
            if (
                activity_limit <= 0.0
                or
                concentration_limit <= 0.0
            ):
                return 0

            activity_ratio_sum += (
                activity_upper
                / activity_limit
            )

            concentration_ratio_sum += (
                concentration_upper_kbq_kg
                / concentration_limit
            )

        # ============================================================
        # 6. ФІНАЛЬНА ПЕРЕВІРКА
        # ============================================================

        if (
            not math.isfinite(activity_ratio_sum)
            or
            not math.isfinite(
                concentration_ratio_sum
            )
        ):
            return 0

        # ============================================================
        # 7. READY_TO_DRAIN
        # ============================================================
        #
        # Для дозволу зливу обидві умови повинні
        # виконуватися одночасно.
        #
        # Межові значення допускаємо:
        #
        #     concentration_ratio_sum == 1
        #     activity_ratio_sum == 1000
        #
        # оскільки нормативне перевищення починається
        # саме ПОНАД відповідною межею.

        if (
            concentration_ratio_sum <= 1.0
            and
            activity_ratio_sum <= 1000.0
        ):
            return 1

        return 0


    def _send_ready_to_drain_update(self, posit_number, ready_to_drain):
        """
        Відправляє оновлення статусу ready_to_drain для цистерни в Bridge.
        """
        if not self.is_bridge_connected():
            return
        
        zb_object = {
            "number": posit_number,
            "ready_to_drain": ready_to_drain
        }
        
        try:
            if not self.modbus_client.send_zb([zb_object]):
                self.ui.textEdit.append(f"[ZB] Помилка при відправці ready_to_drain для ZB{posit_number}")
        except Exception as e:
            self.ui.textEdit.append(f"[ZB] Виняток при відправці ready_to_drain: {e}")


    def _send_replacement_to_bridge(self, zb_number: int, new_sn: int):
        """
        Отправляет информацию о замене прибора в Bridge.
        
        Вход:
            zb_number - номер цистерны (1..9)
            new_sn - новый серийный номер прибора
        """
        if not self.is_bridge_connected():
            self.ui.textEdit.append(
                f"[REPLACEMENT] Bridge не подключен, "
                f"данные о замене ZB{zb_number}->{new_sn} не отправлены"
            )
            return
        
        try:
            success = self.modbus_client.send_replacement(zb_number, new_sn)
            if not success:
                self.ui.textEdit.append(
                    f"[REPLACEMENT] Ошибка при отправке замены ZB{zb_number}->{new_sn}"
                )
        except Exception as e:
            self.ui.textEdit.append(
                f"[REPLACEMENT] Исключение при отправке замены ZB{zb_number}->{new_sn}: {e}"
            )

    
            

# def main():
#     """
#     Точка входу в програму.
#     Спочатку перевіряємо пароль, потім запускаємо основне вікно.
#     """
#     # Створюємо об'єкт програми Qt
#     app = QApplication(sys.argv)

#     # ------------------------------------------------------------
#     # 1. Показуємо діалог вводу пароля
#     # ------------------------------------------------------------
#     password_dialog = PasswordDialog()
#     result = password_dialog.exec()  # exec() повертає QDialog.Accepted або QDialog.Rejected

#     # Якщо користувач натиснув Cancel або ввів неправильний пароль — виходимо
#     if result != QDialog.Accepted:
#         sys.exit(0)  # завершуємо програму без помилок

#     # ------------------------------------------------------------
#     # 2. Пароль правильний — створюємо головне вікно
#     # ------------------------------------------------------------
#     window = App()
#     app.aboutToQuit.connect(window.cleanup)
#     sys.exit(app.exec())

def main():
    """
    Точка входу в програму.

    Перед запуском програми встановлюємо робочу директорію
    в каталог, де знаходиться app.py.

    Це необхідно, щоб усі відносні шляхи програми:
        _UI/
        config/
        calibration/
        data/
        ModBusBridgeService_Runtime/
    працювали однаково незалежно від того, звідки була
    запущена програма: IDE, ярлик Windows, автозапуск тощо.

    Після цього перевіряємо пароль і запускаємо основне вікно.
    """

    # ============================================================
    # 1. ВСТАНОВЛЮЄМО РОБОЧУ ДИРЕКТОРІЮ ПРОГРАМИ
    # ============================================================

    # Отримуємо абсолютний шлях до каталогу,
    # в якому знаходиться поточний файл app.py.
    application_dir = os.path.dirname(os.path.abspath(__file__))

    # Робимо цей каталог поточною робочою директорією.
    #
    # Після цього всі відносні шляхи, наприклад:
    #   config/config.txt
    #   data/clinic.db
    #   calibration/background.txt
    #   _UI/main_window_form.ui
    #
    # будуть шукатися саме відносно каталогу програми.
    os.chdir(application_dir)

    # ============================================================
    # 2. СТВОРЮЄМО QT APPLICATION
    # ============================================================

    app = QApplication(sys.argv)

    # ============================================================
    # 3. АВТОРИЗАЦІЯ
    # ============================================================

    password_dialog = PasswordDialog()

    # exec() повертає:
    #   QDialog.Accepted
    # або
    #   QDialog.Rejected
    result = password_dialog.exec()

    # Якщо користувач натиснув Cancel —
    # завершуємо програму штатно.
    if result != QDialog.Accepted:
        sys.exit(0)

    # ============================================================
    # 4. СТВОРЮЄМО ГОЛОВНЕ ВІКНО
    # ============================================================

    window = App()

    # Перед повним завершенням QApplication викликаємо cleanup(),
    # щоб коректно зупинити потоки, таймери, Bridge і БД.
    app.aboutToQuit.connect(window.cleanup)

    # ============================================================
    # 5. ЗАПУСКАЄМО ГОЛОВНИЙ ЦИКЛ QT
    # ============================================================

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
