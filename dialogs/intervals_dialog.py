# dialogs/intervals_dialog.py

import os
from PySide6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QLabel, QSpinBox, QGridLayout
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile


class IntervalsDialog(QDialog):
    """
    Діалог для налаштування інтервалів:
    - час накопичення спектру
    - інтервал відправки ZB
    - інтервал відправки CZ
    - інтервал запису в БД
    - інтервал збереження даних цистерн (неактивні режими)
    - інтервал збереження даних настінних детекторів
    """

    def __init__(self, parent=None):
        # QDialog очікує QWidget як parent
        if parent is not None and hasattr(parent, 'ui'):
            real_parent = parent.ui
        else:
            real_parent = parent
        
        super().__init__(real_parent)

        # Завантажуємо UI
        loader = QUiLoader()
        ui_file = QFile("_UI/intervals_dialog.ui")
        ui_file.open(QFile.ReadOnly)
        self.ui = loader.load(ui_file)
        ui_file.close()

        if self.ui is None:
            raise RuntimeError("Не удалось загрузить _UI/intervals_dialog.ui")

        # Робимо цей QWidget центральним у діалозі
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.ui)

        self.setWindowTitle("Налаштування інтервалів")
        self.setModal(True)

        # --------------------------------------------------------------------
        # Отримуємо посилання на елементи
        # --------------------------------------------------------------------
        self.spin_spectrum_time = self.ui.findChild(QSpinBox, "spin_spectrum_time")
        self.spin_db_interval = self.ui.findChild(QSpinBox, "spin_db_interval")
        self.spin_zb_interval = self.ui.findChild(QSpinBox, "spin_zb_interval")
        self.spin_cz_interval = self.ui.findChild(QSpinBox, "spin_cz_interval")
        self.spin_cistern_save_interval = self.ui.findChild(QSpinBox, "spin_cistern_save_interval")
        self.spin_wall_save_interval = self.ui.findChild(QSpinBox, "spin_wall_save_interval")

        self.btn_save = self.ui.findChild(QPushButton, "btn_save")
        self.btn_cancel = self.ui.findChild(QPushButton, "btn_cancel")

        # --------------------------------------------------------------------
        # Встановлюємо значення за замовчуванням (якщо є батьківські налаштування)
        # --------------------------------------------------------------------
        if parent is not None:
            if hasattr(parent, 'spectrum_accumulation_time'):
                self.spin_spectrum_time.setValue(parent.spectrum_accumulation_time)
            if hasattr(parent, 'db_write_interval'):
                self.spin_db_interval.setValue(parent.db_write_interval)
            if hasattr(parent, 'zb_send_interval'):
                self.spin_zb_interval.setValue(parent.zb_send_interval)
            if hasattr(parent, 'cz_send_interval'):
                self.spin_cz_interval.setValue(parent.cz_send_interval)
            if hasattr(parent, 'cistern_save_interval'):
                self.spin_cistern_save_interval.setValue(parent.cistern_save_interval)
            if hasattr(parent, 'wall_save_interval'):
                self.spin_wall_save_interval.setValue(parent.wall_save_interval)

        # --------------------------------------------------------------------
        # Підключаємо сигнали
        # --------------------------------------------------------------------
        self.btn_save.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

    # ------------------------------------------------------------------------
    # Методи для отримання значень
    # ------------------------------------------------------------------------
    def get_spectrum_time(self):
        return self.spin_spectrum_time.value()

    def get_db_interval(self):
        return self.spin_db_interval.value()

    def get_zb_interval(self):
        return self.spin_zb_interval.value()

    def get_cz_interval(self):
        return self.spin_cz_interval.value()

    def get_cistern_save_interval(self):
        return self.spin_cistern_save_interval.value()

    def get_wall_save_interval(self):
        return self.spin_wall_save_interval.value()