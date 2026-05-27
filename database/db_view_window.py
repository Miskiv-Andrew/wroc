import os
import csv
from datetime import datetime

from PySide6.QtWidgets import QMainWindow, QFileDialog, QMessageBox, QHeaderView
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, QDateTime, Qt
from PySide6.QtGui import QStandardItemModel, QStandardItem

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from database.db_manager import DatabaseManager


class DBViewWindow(QMainWindow):
    def __init__(self, db_manager: DatabaseManager, parent=None):
        super().__init__(parent)
        
        self.db_manager = db_manager
        self.current_tab = "paed"  # paed, activity, events
        
        # Загружаем UI
        loader = QUiLoader()
        ui_file = QFile("_UI/db_view.ui")
        ui_file.open(QFile.ReadOnly)
        self.ui = loader.load(ui_file)
        ui_file.close()
        
        if self.ui is None:
            raise RuntimeError("Не удалось загрузить UI/db_view.ui")
        
        self.setCentralWidget(self.ui.centralWidget())
        self.setWindowTitle("База даних - перегляд даних")
        self.resize(1200, 800)
        
        # Инициализация графиков
        self.init_plots()
        
        # Подключаем сигналы
        self.setup_connections()
        
        # Загружаем списки приборов
        self.load_devices_lists()
        
        # Устанавливаем начальные даты (последние 7 дней)
        self.set_default_dates()
    
    def init_plots(self):
        """Инициализирует виджеты графиков для вкладок ПАЕД и Активность"""
        # Вкладка ПАЕД
        self.figure_paed = Figure(figsize=(8, 4))
        self.canvas_paed = FigureCanvas(self.figure_paed)
        self.ax_paed = self.figure_paed.add_subplot(111)
        
        # Заменяем placeholder на реальный график
        plot_container = self.ui.frame_plot_paed
        if plot_container:
            # Очищаем контейнер
            for child in plot_container.children():
                if isinstance(child, FigureCanvas):
                    child.deleteLater()
            # Добавляем canvas
            layout = plot_container.layout()
            if layout:
                layout.addWidget(self.canvas_paed)
        
        # Вкладка Активность
        self.figure_activity = Figure(figsize=(8, 4))
        self.canvas_activity = FigureCanvas(self.figure_activity)
        self.ax_activity = self.figure_activity.add_subplot(111)
        
        plot_container_activity = self.ui.frame_plot_activity
        if plot_container_activity:
            for child in plot_container_activity.children():
                if isinstance(child, FigureCanvas):
                    child.deleteLater()
            layout = plot_container_activity.layout()
            if layout:
                layout.addWidget(self.canvas_activity)
    
    def setup_connections(self):
        # Вкладка ПАЕД
        self.ui.btn_apply_paed.clicked.connect(lambda: self.load_paed_data())
        self.ui.btn_reset_filters_paed.clicked.connect(lambda: self.reset_filters("paed"))
        self.ui.btn_all_period_paed.clicked.connect(lambda: self.set_all_period("paed"))
        self.ui.btn_export_csv_paed.clicked.connect(lambda: self.export_csv("paed"))
        self.ui.btn_export_png_paed.clicked.connect(lambda: self.export_png("paed"))
        self.ui.combo_location_type_paed.currentIndexChanged.connect(self.on_location_type_changed)
        
        # Вкладка Активность
        self.ui.btn_apply_activity.clicked.connect(lambda: self.load_activity_data())
        self.ui.btn_reset_filters_activity.clicked.connect(lambda: self.reset_filters("activity"))
        self.ui.btn_all_period_activity.clicked.connect(lambda: self.set_all_period("activity"))
        self.ui.btn_export_csv_activity.clicked.connect(lambda: self.export_csv("activity"))
        self.ui.btn_export_png_activity.clicked.connect(lambda: self.export_png("activity"))
        
        # Вкладка Системные события
        self.ui.btn_apply_events.clicked.connect(lambda: self.load_events_data())
        self.ui.btn_reset_filters_events.clicked.connect(lambda: self.reset_filters("events"))
        self.ui.btn_all_period_events.clicked.connect(lambda: self.set_all_period("events"))
        self.ui.btn_export_csv_events.clicked.connect(lambda: self.export_csv("events"))
        
        # Переключение вкладок
        self.ui.tabWidget.currentChanged.connect(self.on_tab_changed)
    
    def on_tab_changed(self, index):
        """При переключении вкладки загружаем данные"""
        if index == 0:
            self.current_tab = "paed"
            self.load_paed_data()
        elif index == 1:
            self.current_tab = "activity"
            self.load_activity_data()
        elif index == 2:
            self.current_tab = "events"
            self.load_events_data()
    
    def load_devices_lists(self):
        """Загружает списки приборов из БД"""
        devices = self.db_manager.get_all_active_devices()
        
        # Сортируем по типу расположения
        cisterns = [d for d in devices if d["location_type"] == "cistern"]
        rooms = [d for d in devices if d["location_type"] == "room"]
        
        # Вкладка ПАЕД - словарь для быстрого доступа
        self.devices_dict = {}
        for d in cisterns + rooms:
            self.devices_dict[d["serial_number"]] = d
        
        # Вкладка Активность (только цистерны)
        self.ui.combo_device_activity.clear()
        self.ui.combo_device_activity.addItem("-- Виберіть цистерну --")
        for d in cisterns:
            self.ui.combo_device_activity.addItem(
                f"Цистерна №{d['position_number']} (SN: {d['serial_number']})",
                d["serial_number"]
            )
        
        # Вкладка События
        self.ui.combo_device_events.clear()
        self.ui.combo_device_events.addItem("-- Всі прилади --")
        for d in cisterns + rooms:
            self.ui.combo_device_events.addItem(
                f"{d['location_type']} №{d['position_number']} (SN: {d['serial_number']})",
                d["serial_number"]
            )
    
    def on_location_type_changed(self, index):
        """Обновляет список приборов при смене типа расположения"""
        self.ui.combo_device_paed.clear()
        self.ui.combo_device_paed.addItem("-- Виберіть прилад --")
        
        location_type = self.ui.combo_location_type_paed.currentText()
        devices = self.db_manager.get_all_active_devices()
        
        if location_type == "Цистерна":
            filtered = [d for d in devices if d["location_type"] == "cistern"]
            self.ui.combo_device_paed.setEnabled(True)
        elif location_type == "Кімната":
            filtered = [d for d in devices if d["location_type"] == "room"]
            self.ui.combo_device_paed.setEnabled(True)
        else:
            filtered = []
            self.ui.combo_device_paed.setEnabled(False)
        
        for d in filtered:
            self.ui.combo_device_paed.addItem(
                f"{d['location_type']} №{d['position_number']} (SN: {d['serial_number']})",
                d["serial_number"]
            )
    
    def get_date_range(self, tab):
        """Возвращает (date_from, date_to) для указанной вкладки"""
        if tab == "paed":
            date_from = self.ui.dateFrom_paed.dateTime().toPython()
            date_to = self.ui.dateTo_paed.dateTime().toPython()
        elif tab == "activity":
            date_from = self.ui.dateFrom_activity.dateTime().toPython()
            date_to = self.ui.dateTo_activity.dateTime().toPython()
        else:  # events
            date_from = self.ui.dateFrom_events.dateTime().toPython()
            date_to = self.ui.dateTo_events.dateTime().toPython()
        return date_from, date_to
    
    
    # def load_paed_data(self):
    #     """Загружает данные ПАЕД из БД и строит график/таблицу"""
    #     date_from, date_to = self.get_date_range("paed")
        
    #     # Получаем выбранный прибор
    #     device_sn = self.ui.combo_device_paed.currentData()
    #     if not device_sn:
    #         QMessageBox.warning(self, "Попередження", "Виберіть прилад")
    #         return
        
    #     device_id = self.db_manager.get_device_id(device_sn)
    #     if not device_id:
    #         return
        
    #     # Определяем тип расположения
    #     location_type = self.ui.combo_location_type_paed.currentText()
        
    #     # Загружаем данные в зависимости от типа
    #     if location_type in ("Цистерна", "Всі"):
    #         # Измерения цистерн
    #         conn = self.db_manager._get_connection()
    #         cursor = conn.cursor()
    #         cursor.execute("""
    #             SELECT timestamp, paed, temperature, low_status, high_status, valid
    #             FROM measurements_cistern
    #             WHERE device_id = ? AND timestamp BETWEEN ? AND ?
    #             ORDER BY timestamp
    #         """, (device_id, date_from, date_to))
    #         rows = cursor.fetchall()
    #     else:
    #         # Измерения настенных
    #         conn = self.db_manager._get_connection()
    #         cursor = conn.cursor()
    #         cursor.execute("""
    #             SELECT timestamp, paed, temperature, low_status, high_status, valid
    #             FROM measurements_wall
    #             WHERE device_id = ? AND timestamp BETWEEN ? AND ?
    #             ORDER BY timestamp
    #         """, (device_id, date_from, date_to))
    #         rows = cursor.fetchall()
        
    #     if not rows:
    #         self.ax_paed.clear()
    #         self.ax_paed.text(0.5, 0.5, "Немає даних за вибраний період", transform=self.ax_paed.transAxes, ha='center')
    #         self.canvas_paed.draw()
    #         self.fill_paed_table([])
    #         return
        
    #     # Строим график
    #     self.ax_paed.clear()
    #     timestamps = [row[0] for row in rows]
    #     paed_values = [row[1] for row in rows]
        
    #     self.ax_paed.plot(timestamps, paed_values, 'b-', linewidth=1.5)
    #     self.ax_paed.set_xlabel("Час")
    #     self.ax_paed.set_ylabel("ПАЕД, мкЗв/год")
    #     self.ax_paed.set_title(f"ПАЕД - {device_sn}")
    #     self.ax_paed.grid(True, alpha=0.3)
    #     self.figure_paed.autofmt_xdate()
    #     self.canvas_paed.draw()
        
    #     # Заполняем таблицу
    #     self.fill_paed_table(rows)

    def load_paed_data(self):
        """
            Загружает данные ПАЕД из БД и строит график/таблицу
        """
        date_from, date_to = self.get_date_range("paed")
        
        device_sn = self.ui.combo_device_paed.currentData()
        if not device_sn:
            QMessageBox.warning(self, "Попередження", "Виберіть прилад")
            return
        
        device_id = self.db_manager.get_device_id(device_sn)
        if not device_id:
            return
        
        location_type = self.ui.combo_location_type_paed.currentText()
        
        if location_type in ("Цистерна", "Всі"):
            conn = self.db_manager._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, paed, temperature, low_status, high_status, valid
                FROM measurements_cistern
                WHERE device_id = ? AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp
            """, (device_id, date_from, date_to))
            rows = cursor.fetchall()
        else:
            conn = self.db_manager._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, paed, temperature, low_status, high_status, valid
                FROM measurements_wall
                WHERE device_id = ? AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp
            """, (device_id, date_from, date_to))
            rows = cursor.fetchall()
        
        if not rows:
            self.ax_paed.clear()
            self.ax_paed.text(0.5, 0.5, "Немає даних за вибраний період", transform=self.ax_paed.transAxes, ha='center')
            self.canvas_paed.draw()
            self.fill_paed_table([])
            return
        
        # Строим график - конвертируем строки в datetime
        self.ax_paed.clear()
        timestamps = [datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S") for row in rows]
        paed_values = [row[1] for row in rows]
        
        self.ax_paed.plot(timestamps, paed_values, 'b-', linewidth=1.5)
        self.ax_paed.set_xlabel("Час")
        self.ax_paed.set_ylabel("ПАЕД, мкЗв/год")
        self.ax_paed.set_title(f"ПАЕД - {device_sn}")
        self.ax_paed.grid(True, alpha=0.3)
        self.figure_paed.autofmt_xdate()
        self.canvas_paed.draw()
        
        self.fill_paed_table(rows)



    
    # def fill_paed_table(self, rows):
    #     """Заполняет таблицу ПАЕД"""
    #     model = QStandardItemModel()
    #     model.setHorizontalHeaderLabels(["Час", "ПАЕД, мкЗв/год", "Температура, °C", "Стан детекторів"])
        
    #     for row_idx, row in enumerate(rows):
    #         timestamp = row[0].strftime("%d.%m.%Y %H:%M:%S")
    #         paed = f"{row[1]:.2f}"
    #         temp = f"{row[2]:.1f}"
    #         low_ok = "Низькочутл: Норма" if row[3] == 0 else "Низькочутл: Відмова"
    #         high_ok = "Високочутл: Норма" if row[4] == 0 else "Високочутл: Відмова"
    #         status = f"{low_ok}, {high_ok}"
            
    #         model.setItem(row_idx, 0, QStandardItem(timestamp))
    #         model.setItem(row_idx, 1, QStandardItem(paed))
    #         model.setItem(row_idx, 2, QStandardItem(temp))
    #         model.setItem(row_idx, 3, QStandardItem(status))
        
    #     self.ui.tableView_paed.setModel(model)
    #     self.ui.tableView_paed.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def fill_paed_table(self, rows):
        """
            Заполняет таблицу ПАЕД
        """
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(["Час", "ПАЕД, мкЗв/год", "Температура, °C", "Стан детекторів"])
        
        for row_idx, row in enumerate(rows):
            timestamp = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S")
            paed = f"{row[1]:.2f}"
            temp = f"{row[2]:.1f}"
            low_ok = "Низькочутл: Норма" if row[3] == 0 else "Низькочутл: Відмова"
            high_ok = "Високочутл: Норма" if row[4] == 0 else "Високочутл: Відмова"
            status = f"{low_ok}, {high_ok}"
            
            model.setItem(row_idx, 0, QStandardItem(timestamp))
            model.setItem(row_idx, 1, QStandardItem(paed))
            model.setItem(row_idx, 2, QStandardItem(temp))
            model.setItem(row_idx, 3, QStandardItem(status))
        
        self.ui.tableView_paed.setModel(model)
        self.ui.tableView_paed.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        
    def load_activity_data(self):
        """Загружает данные активности из БД"""
        date_from, date_to = self.get_date_range("activity")
        
        device_sn = self.ui.combo_device_activity.currentData()
        if not device_sn:
            QMessageBox.warning(self, "Попередження", "Виберіть цистерну")
            return
        
        device_id = self.db_manager.get_device_id(device_sn)
        if not device_id:
            return
        
        conn = self.db_manager._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, paed, activity, fullness_status
            FROM measurements_cistern
            WHERE device_id = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp
        """, (device_id, date_from, date_to))
        rows = cursor.fetchall()
        
        if not rows:
            self.ax_activity.clear()
            self.ax_activity.text(0.5, 0.5, "Немає даних за вибраний період", transform=self.ax_activity.transAxes, ha='center')
            self.canvas_activity.draw()
            self.fill_activity_table([])
            return
        
        # Строим график - конвертируем строки в datetime
        self.ax_activity.clear()
        timestamps = [datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S") for row in rows]
        activity_values = [row[2] if row[2] else 0 for row in rows]
        
        self.ax_activity.plot(timestamps, activity_values, 'g-', linewidth=1.5)
        self.ax_activity.set_xlabel("Час")
        self.ax_activity.set_ylabel("Активність, кБк")
        self.ax_activity.set_title(f"Активність - {device_sn}")
        self.ax_activity.grid(True, alpha=0.3)
        self.figure_activity.autofmt_xdate()
        self.canvas_activity.draw()
        
        self.fill_activity_table(rows)
    
    def fill_activity_table(self, rows):
        """Заполняет таблицу активности"""
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(["Час", "ПАЕД, мкЗв/год", "Активність, кБк", "Стан цистерни"])
        
        for row_idx, row in enumerate(rows):
            timestamp = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S")
            paed = f"{row[1]:.2f}"
            activity = f"{row[2]:.2f}" if row[2] else "—"
            fullness = "Повна" if row[3] == "full" else "Не повна"
            
            model.setItem(row_idx, 0, QStandardItem(timestamp))
            model.setItem(row_idx, 1, QStandardItem(paed))
            model.setItem(row_idx, 2, QStandardItem(activity))
            model.setItem(row_idx, 3, QStandardItem(fullness))
        
        self.ui.tableView_activity.setModel(model)
        self.ui.tableView_activity.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    
    def load_events_data(self):
        """Загружает системные события"""
        date_from, date_to = self.get_date_range("events")
        
        event_type = self.ui.combo_event_type.currentText()
        if event_type == "Всі":
            event_type = None
        
        device_sn = self.ui.combo_device_events.currentData()
        device_id = self.db_manager.get_device_id(device_sn) if device_sn else None
        
        query = """
            SELECT timestamp, event_type, description, device_id
            FROM system_events
            WHERE timestamp BETWEEN ? AND ?
        """
        params = [date_from, date_to]
        
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        
        if device_id:
            query += " AND device_id = ?"
            params.append(device_id)
        
        query += " ORDER BY timestamp DESC"
        
        conn = self.db_manager._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(["Час", "Тип події", "Прилад", "Опис"])
        
        for row_idx, row in enumerate(rows):
            timestamp = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M:%S")
            event_type = row[1]
            description = row[2] if row[2] else ""
            
            dev_id = row[3]
            if dev_id:
                cursor2 = conn.cursor()
                cursor2.execute("SELECT serial_number FROM devices WHERE id = ?", (dev_id,))
                sn_row = cursor2.fetchone()
                device_sn_str = sn_row[0] if sn_row else f"ID:{dev_id}"
            else:
                device_sn_str = "—"
            
            model.setItem(row_idx, 0, QStandardItem(timestamp))
            model.setItem(row_idx, 1, QStandardItem(event_type))
            model.setItem(row_idx, 2, QStandardItem(device_sn_str))
            model.setItem(row_idx, 3, QStandardItem(description))
        
        self.ui.tableView_events.setModel(model)
        self.ui.tableView_events.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        
    def reset_filters(self, tab):
        """Сброс фильтров к значениям по умолчанию"""
        self.set_default_dates()
        
        if tab == "paed":
            self.ui.combo_location_type_paed.setCurrentIndex(0)
            self.ui.combo_device_paed.setEnabled(False)
            self.ui.combo_device_paed.clear()
            self.ui.combo_device_paed.addItem("-- Виберіть прилад --")
        elif tab == "activity":
            self.ui.combo_device_activity.setCurrentIndex(0)
        elif tab == "events":
            self.ui.combo_event_type.setCurrentIndex(0)
            self.ui.combo_device_events.setCurrentIndex(0)
    
    def set_all_period(self, tab):
        """Устанавливает период за всё время (3 года назад)"""
        now = QDateTime.currentDateTime()
        three_years_ago = now.addYears(-3)
        
        if tab == "paed":
            self.ui.dateFrom_paed.setDateTime(three_years_ago)
            self.ui.dateTo_paed.setDateTime(now)
        elif tab == "activity":
            self.ui.dateFrom_activity.setDateTime(three_years_ago)
            self.ui.dateTo_activity.setDateTime(now)
        elif tab == "events":
            self.ui.dateFrom_events.setDateTime(three_years_ago)
            self.ui.dateTo_events.setDateTime(now)
    
    def set_default_dates(self):
        """Устанавливает даты по умолчанию (последние 7 дней)"""
        now = QDateTime.currentDateTime()
        week_ago = now.addDays(-7)
        
        self.ui.dateFrom_paed.setDateTime(week_ago)
        self.ui.dateTo_paed.setDateTime(now)
        self.ui.dateFrom_activity.setDateTime(week_ago)
        self.ui.dateTo_activity.setDateTime(now)
        self.ui.dateFrom_events.setDateTime(week_ago)
        self.ui.dateTo_events.setDateTime(now)
    
    def export_csv(self, tab):
        """Экспорт таблицы в CSV"""
        file_path, _ = QFileDialog.getSaveFileName(self, "Зберегти CSV", "", "CSV Files (*.csv)")
        if not file_path:
            return
        
        # Получаем модель таблицы
        if tab == "paed":
            model = self.ui.tableView_paed.model()
        elif tab == "activity":
            model = self.ui.tableView_activity.model()
        else:
            model = self.ui.tableView_events.model()
        
        if not model:
            QMessageBox.warning(self, "Помилка", "Немає даних для експорту")
            return
        
        try:
            with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                # Заголовки
                headers = [model.headerData(i, Qt.Horizontal) for i in range(model.columnCount())]
                writer.writerow(headers)
                # Данные
                for row in range(model.rowCount()):
                    row_data = []
                    for col in range(model.columnCount()):
                        idx = model.index(row, col)
                        row_data.append(model.data(idx))
                    writer.writerow(row_data)
            
            QMessageBox.information(self, "Успіх", f"Дані збережено у {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Помилка", f"Не вдалося зберегти CSV: {e}")
    
    def export_png(self, tab):
        """Экспорт графика в PNG"""
        file_path, _ = QFileDialog.getSaveFileName(self, "Зберегти графік", "", "PNG Files (*.png)")
        if not file_path:
            return
        
        try:
            if tab == "paed":
                self.figure_paed.savefig(file_path, dpi=150, bbox_inches='tight')
            else:
                self.figure_activity.savefig(file_path, dpi=150, bbox_inches='tight')
            QMessageBox.information(self, "Успіх", f"Графік збережено у {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Помилка", f"Не вдалося зберегти графік: {e}")