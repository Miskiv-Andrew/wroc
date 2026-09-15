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
import json


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
        """
        Загружает в окно просмотра БД список всех приборов,
        включая ранее заменённые.

        Это необходимо для просмотра полной истории измерений
        за весь срок хранения БД.
        """

        # ------------------------------------------------------------
        # 1. ПОЛУЧАЕМ ВСЕ ПРИБОРЫ
        # ------------------------------------------------------------

        devices = self.db_manager.get_all_devices_for_history()

        cisterns = [
            d for d in devices
            if d["location_type"] == "cistern"
        ]

        rooms = [
            d for d in devices
            if d["location_type"] == "room"
        ]

        # ------------------------------------------------------------
        # 2. СОХРАНЯЕМ СЛОВАРЬ ПРИБОРОВ
        # ------------------------------------------------------------

        self.devices_dict = {}

        for device in cisterns + rooms:
            self.devices_dict[device["serial_number"]] = device

        # ------------------------------------------------------------
        # 3. ВКЛАДКА ПАЕД
        # ------------------------------------------------------------
        #
        # Сам список приборов будет формироваться методом
        # on_location_type_changed().
        # ------------------------------------------------------------

        self.ui.combo_device_paed.clear()
        self.ui.combo_device_paed.addItem(
            "-- Виберіть прилад --"
        )

        # ------------------------------------------------------------
        # 4. ВКЛАДКА АКТИВНОСТИ
        # ------------------------------------------------------------
        #
        # Активность относится только к детекторам цистерн.
        # ------------------------------------------------------------

        self.ui.combo_device_activity.clear()
        self.ui.combo_device_activity.addItem(
            "-- Виберіть цистерну --"
        )

        for device in cisterns:

            active_text = (
                ""
                if device["is_active"]
                else " [замінений]"
            )

            self.ui.combo_device_activity.addItem(
                (
                    f"Цистерна №{device['position_number']} "
                    f"(SN: {device['serial_number']})"
                    f"{active_text}"
                ),
                device["serial_number"]
            )

        # ------------------------------------------------------------
        # 5. ВКЛАДКА СИСТЕМНЫХ СОБЫТИЙ
        # ------------------------------------------------------------

        self.ui.combo_device_events.clear()
        self.ui.combo_device_events.addItem(
            "-- Всі прилади --"
        )

        for device in cisterns + rooms:

            active_text = (
                ""
                if device["is_active"]
                else " [замінений]"
            )

            location_name = (
                "Цистерна"
                if device["location_type"] == "cistern"
                else "Кімната"
            )

            self.ui.combo_device_events.addItem(
                (
                    f"{location_name} "
                    f"№{device['position_number']} "
                    f"(SN: {device['serial_number']})"
                    f"{active_text}"
                ),
                device["serial_number"]
            )



    def on_location_type_changed(self, index):
        """
        Обновляет список приборов при изменении типа расположения.

        При выборе "Всі" показываются все приборы.
        """

        self.ui.combo_device_paed.clear()
        self.ui.combo_device_paed.addItem(
            "-- Виберіть прилад --"
        )

        location_type = (
            self.ui.combo_location_type_paed.currentText()
        )

        devices = (
            self.db_manager.get_all_devices_for_history()
        )

        # ------------------------------------------------------------
        # 1. ФИЛЬТР ПО ТИПУ РАСПОЛОЖЕНИЯ
        # ------------------------------------------------------------

        if location_type == "Цистерна":

            filtered = [
                d for d in devices
                if d["location_type"] == "cistern"
            ]

            # Группа имеет смысл только для цистерн.
            self.ui.combo_group_paed.setEnabled(True)

        elif location_type == "Кімната":

            filtered = [
                d for d in devices
                if d["location_type"] == "room"
            ]

            # Для комнатных детекторов группы A/B/reserve
            # не используются.
            self.ui.combo_group_paed.setCurrentIndex(0)
            self.ui.combo_group_paed.setEnabled(False)

        else:
            # Выбрано "Всі".
            filtered = devices

            # При отображении одновременно цистерн и комнат
            # фильтр группы не применяется.
            self.ui.combo_group_paed.setCurrentIndex(0)
            self.ui.combo_group_paed.setEnabled(False)

        self.ui.combo_device_paed.setEnabled(True)

        # ------------------------------------------------------------
        # 2. ЗАПОЛНЯЕМ СПИСОК ПРИБОРОВ
        # ------------------------------------------------------------

        for device in filtered:

            active_text = (
                ""
                if device["is_active"]
                else " [замінений]"
            )

            location_name = (
                "Цистерна"
                if device["location_type"] == "cistern"
                else "Кімната"
            )

            self.ui.combo_device_paed.addItem(
                (
                    f"{location_name} "
                    f"№{device['position_number']} "
                    f"(SN: {device['serial_number']})"
                    f"{active_text}"
                ),
                device["serial_number"]
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
    
   
   
    def load_paed_data(self):
        """
        Загружает ПАЕД выбранного прибора из БД
        и отображает график и таблицу.
        """

        date_from, date_to = self.get_date_range("paed")

        # ------------------------------------------------------------
        # 1. ПРОВЕРЯЕМ КОРРЕКТНОСТЬ ПЕРИОДА
        # ------------------------------------------------------------

        if date_from > date_to:
            QMessageBox.warning(
                self,
                "Попередження",
                "Початкова дата не може бути пізніше кінцевої."
            )
            return

        # ------------------------------------------------------------
        # 2. ПОЛУЧАЕМ ВЫБРАННЫЙ ПРИБОР
        # ------------------------------------------------------------

        device_sn = self.ui.combo_device_paed.currentData()

        if not device_sn:
            QMessageBox.warning(
                self,
                "Попередження",
                "Виберіть прилад"
            )
            return

        device = self.devices_dict.get(device_sn)

        if device is None:
            QMessageBox.warning(
                self,
                "Помилка",
                "Не вдалося визначити тип вибраного приладу."
            )
            return

        # ------------------------------------------------------------
        # 3. ПОЛУЧАЕМ DEVICE_ID
        # ------------------------------------------------------------
        #
        # Используем специальный исторический метод, потому что
        # выбранный прибор может быть уже заменён и иметь is_active = 0.
        # ------------------------------------------------------------

        device_id = (
            self.db_manager.get_device_id_for_history(
                device_sn
            )
        )

        if device_id is None:
            QMessageBox.warning(
                self,
                "Помилка",
                "Прилад не знайдено в базі даних."
            )
            return

        # ------------------------------------------------------------
        # 4. ПОЛУЧАЕМ ФИЛЬТР ГРУППЫ
        # ------------------------------------------------------------

        group_filter = (
            self.ui.combo_group_paed.currentText()
        )

        conn = self.db_manager._get_connection()
        cursor = conn.cursor()

        date_from_str = date_from.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        date_to_str = date_to.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # ------------------------------------------------------------
        # 5. ЧИТАЕМ ДАННЫЕ
        # ------------------------------------------------------------

        try:

            if device["location_type"] == "cistern":

                if group_filter != "Всі":

                    query = """
                        SELECT
                            timestamp,
                            paed,
                            temperature,
                            low_status,
                            high_status,
                            valid
                        FROM measurements_cistern
                        WHERE device_id = ?
                          AND timestamp BETWEEN ? AND ?
                          AND "group" = ?
                        ORDER BY timestamp
                    """

                    cursor.execute(
                        query,
                        (
                            device_id,
                            date_from_str,
                            date_to_str,
                            group_filter
                        )
                    )

                else:

                    query = """
                        SELECT
                            timestamp,
                            paed,
                            temperature,
                            low_status,
                            high_status,
                            valid
                        FROM measurements_cistern
                        WHERE device_id = ?
                          AND timestamp BETWEEN ? AND ?
                        ORDER BY timestamp
                    """

                    cursor.execute(
                        query,
                        (
                            device_id,
                            date_from_str,
                            date_to_str
                        )
                    )

            else:

                query = """
                    SELECT
                        timestamp,
                        paed,
                        temperature,
                        low_status,
                        high_status,
                        valid
                    FROM measurements_wall
                    WHERE device_id = ?
                      AND timestamp BETWEEN ? AND ?
                    ORDER BY timestamp
                """

                cursor.execute(
                    query,
                    (
                        device_id,
                        date_from_str,
                        date_to_str
                    )
                )

            rows = cursor.fetchall()

        except Exception as e:

            QMessageBox.critical(
                self,
                "Помилка",
                f"Не вдалося прочитати дані ПАЕД:\n{e}"
            )
            return

        # ------------------------------------------------------------
        # 6. ЕСЛИ ДАННЫХ НЕТ
        # ------------------------------------------------------------

        if not rows:

            self.ax_paed.clear()

            self.ax_paed.text(
                0.5,
                0.5,
                "Немає даних за вибраний період",
                transform=self.ax_paed.transAxes,
                ha="center"
            )

            self.canvas_paed.draw()

            self.fill_paed_table([])

            return

        # ------------------------------------------------------------
        # 7. ГОТОВИМ ДАННЫЕ ДЛЯ ГРАФИКА
        # ------------------------------------------------------------

        timestamps = []
        paed_values = []

        for row in rows:

            try:

                timestamp = datetime.strptime(
                    row[0],
                    "%Y-%m-%d %H:%M:%S"
                )

                paed = float(row[1])

            except (TypeError, ValueError):
                # Одна повреждённая историческая запись
                # не должна ломать просмотр остальных данных.
                continue

            timestamps.append(timestamp)
            paed_values.append(paed)

        # ------------------------------------------------------------
        # 8. СТРОИМ ГРАФИК
        # ------------------------------------------------------------

        self.ax_paed.clear()

        if timestamps:

            self.ax_paed.plot(
                timestamps,
                paed_values,
                linewidth=1.5
            )

            self.ax_paed.set_xlabel("Час")

            self.ax_paed.set_ylabel(
                "ПАЕД, мкЗв/год"
            )

            self.ax_paed.set_title(
                f"ПАЕД - {device_sn}"
            )

            self.ax_paed.grid(True)

            self.figure_paed.autofmt_xdate()

        else:

            self.ax_paed.text(
                0.5,
                0.5,
                "Немає коректних даних для графіка",
                transform=self.ax_paed.transAxes,
                ha="center"
            )

        self.canvas_paed.draw()

        # ------------------------------------------------------------
        # 9. ЗАПОЛНЯЕМ ТАБЛИЦУ
        # ------------------------------------------------------------

        self.fill_paed_table(rows)



    def fill_paed_table(self, rows):
        """
        Заполняет таблицу ПАЕД.

        Семантика полей БД:
            low_status  = 1 -> отказ;
            high_status = 1 -> отказ;
            valid       = 1 -> результат валиден.
        """

        model = QStandardItemModel()

        model.setHorizontalHeaderLabels(
            [
                "Час",
                "ПАЕД, мкЗв/год",
                "Температура, °C",
                "Стан детекторів"
            ]
        )

        for row_idx, row in enumerate(rows):

            # --------------------------------------------------------
            # ВРЕМЯ
            # --------------------------------------------------------

            try:
                timestamp = datetime.strptime(
                    row[0],
                    "%Y-%m-%d %H:%M:%S"
                ).strftime(
                    "%d.%m.%Y %H:%M:%S"
                )
            except (TypeError, ValueError):
                timestamp = str(row[0] or "—")

            # --------------------------------------------------------
            # ПАЕД
            # --------------------------------------------------------

            try:
                paed = f"{float(row[1]):.2f}"
            except (TypeError, ValueError):
                paed = "—"

            # --------------------------------------------------------
            # ТЕМПЕРАТУРА
            # --------------------------------------------------------

            try:
                temp = f"{float(row[2]):.1f}"
            except (TypeError, ValueError):
                temp = "—"

            # --------------------------------------------------------
            # СОСТОЯНИЕ ДЕТЕКТОРОВ
            # --------------------------------------------------------
            #
            # В БД:
            #
            #     0 = отказа нет;
            #     1 = отказ.
            #
            # --------------------------------------------------------

            low_ok = (
                "Низькочутл: Відмова"
                if row[3] == 1
                else "Низькочутл: Норма"
            )

            high_ok = (
                "Високочутл: Відмова"
                if row[4] == 1
                else "Високочутл: Норма"
            )

            status = f"{low_ok}, {high_ok}"

            # Если вся запись отмечена как невалидная,
            # дополнительно показываем это оператору.
            if row[5] != 1:
                status += ", результат невалідний"

            model.setItem(
                row_idx,
                0,
                QStandardItem(timestamp)
            )

            model.setItem(
                row_idx,
                1,
                QStandardItem(paed)
            )

            model.setItem(
                row_idx,
                2,
                QStandardItem(temp)
            )

            model.setItem(
                row_idx,
                3,
                QStandardItem(status)
            )

        self.ui.tableView_paed.setModel(model)

        self.ui.tableView_paed.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )



    def load_activity_data(self):
        """
        Загружает исторические результаты активности цистерны,
        строит график суммарной активности и заполняет таблицу.
        """

        date_from, date_to = self.get_date_range(
            "activity"
        )

        # ------------------------------------------------------------
        # 1. ПРОВЕРЯЕМ ПЕРИОД
        # ------------------------------------------------------------

        if date_from > date_to:
            QMessageBox.warning(
                self,
                "Попередження",
                "Початкова дата не може бути пізніше кінцевої."
            )
            return

        # ------------------------------------------------------------
        # 2. ВЫБРАННАЯ ЦИСТЕРНА
        # ------------------------------------------------------------

        device_sn = (
            self.ui.combo_device_activity.currentData()
        )

        if not device_sn:
            QMessageBox.warning(
                self,
                "Попередження",
                "Виберіть цистерну"
            )
            return

        # ------------------------------------------------------------
        # 3. ПОЛУЧАЕМ ИСТОРИЧЕСКИЙ DEVICE_ID
        # ------------------------------------------------------------

        device_id = (
            self.db_manager.get_device_id_for_history(
                device_sn
            )
        )

        if device_id is None:
            QMessageBox.warning(
                self,
                "Помилка",
                "Прилад не знайдено в базі даних."
            )
            return

        group_filter = (
            self.ui.combo_group_activity.currentText()
        )

        conn = self.db_manager._get_connection()
        cursor = conn.cursor()

        date_from_str = date_from.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        date_to_str = date_to.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # ------------------------------------------------------------
        # 4. ЧИТАЕМ ДАННЫЕ
        # ------------------------------------------------------------

        try:

            if group_filter != "Всі":

                cursor.execute(
                    """
                    SELECT
                        timestamp,
                        paed,
                        activity,
                        concentration,
                        fullness_status
                    FROM measurements_cistern
                    WHERE device_id = ?
                      AND timestamp BETWEEN ? AND ?
                      AND "group" = ?
                    ORDER BY timestamp
                    """,
                    (
                        device_id,
                        date_from_str,
                        date_to_str,
                        group_filter
                    )
                )

            else:

                cursor.execute(
                    """
                    SELECT
                        timestamp,
                        paed,
                        activity,
                        concentration,
                        fullness_status
                    FROM measurements_cistern
                    WHERE device_id = ?
                      AND timestamp BETWEEN ? AND ?
                    ORDER BY timestamp
                    """,
                    (
                        device_id,
                        date_from_str,
                        date_to_str
                    )
                )

            rows = cursor.fetchall()

        except Exception as e:

            QMessageBox.critical(
                self,
                "Помилка",
                f"Не вдалося прочитати дані активності:\n{e}"
            )
            return

        # ------------------------------------------------------------
        # 5. ЕСЛИ ДАННЫХ НЕТ
        # ------------------------------------------------------------

        if not rows:

            self.ax_activity.clear()

            self.ax_activity.text(
                0.5,
                0.5,
                "Немає даних за вибраний період",
                transform=self.ax_activity.transAxes,
                ha="center"
            )

            self.canvas_activity.draw()

            self.fill_activity_table([])

            return

        # ------------------------------------------------------------
        # 6. ГОТОВИМ ДАННЫЕ ДЛЯ ГРАФИКА
        # ------------------------------------------------------------

        timestamps = []
        total_activities = []

        for row in rows:

            try:
                timestamp = datetime.strptime(
                    row[0],
                    "%Y-%m-%d %H:%M:%S"
                )
            except (TypeError, ValueError):
                continue

            total_activity = 0.0

            activity_json = row[2]

            if activity_json:

                try:

                    activity_dict = json.loads(
                        activity_json
                    )

                    if isinstance(activity_dict, dict):

                        for value in activity_dict.values():

                            try:
                                total_activity += float(value)
                            except (TypeError, ValueError):
                                continue

                except (
                    TypeError,
                    ValueError,
                    json.JSONDecodeError
                ):
                    # Повреждение JSON одной записи не должно
                    # ломать весь просмотр истории.
                    total_activity = 0.0

            timestamps.append(timestamp)
            total_activities.append(total_activity)

        # ------------------------------------------------------------
        # 7. СТРОИМ ГРАФИК
        # ------------------------------------------------------------

        self.ax_activity.clear()

        if timestamps:

            self.ax_activity.plot(
                timestamps,
                total_activities,
                linewidth=1.5
            )

            self.ax_activity.set_xlabel("Час")

            self.ax_activity.set_ylabel(
                "Активність, Бк"
            )

            self.ax_activity.set_title(
                f"Активність - {device_sn}"
            )

            self.ax_activity.grid(True)

            self.figure_activity.autofmt_xdate()

        else:

            self.ax_activity.text(
                0.5,
                0.5,
                "Немає коректних даних для графіка",
                transform=self.ax_activity.transAxes,
                ha="center"
            )

        self.canvas_activity.draw()

        # ------------------------------------------------------------
        # 8. ТАБЛИЦА
        # ------------------------------------------------------------

        self.fill_activity_table(rows)


    
    def fill_activity_table(self, rows):
        """
        Заполняет таблицу результатов спектрального анализа.

        Повреждение одной исторической записи не должно приводить
        к ошибке всего окна просмотра БД.
        """

        model = QStandardItemModel()

        model.setHorizontalHeaderLabels(
            [
                "Час",
                "ПАЕД, мкЗв/год",
                "Склад (активність, концентрація)",
                "Стан цистерни"
            ]
        )

        for row_idx, row in enumerate(rows):

            # --------------------------------------------------------
            # ВРЕМЯ
            # --------------------------------------------------------

            try:
                timestamp = datetime.strptime(
                    row[0],
                    "%Y-%m-%d %H:%M:%S"
                ).strftime(
                    "%d.%m.%Y %H:%M:%S"
                )
            except (TypeError, ValueError):
                timestamp = str(row[0] or "—")

            # --------------------------------------------------------
            # ПАЕД
            # --------------------------------------------------------

            try:
                paed = f"{float(row[1]):.2f}"
            except (TypeError, ValueError):
                paed = "—"

            # --------------------------------------------------------
            # СОСТОЯНИЕ ЦИСТЕРНЫ
            # --------------------------------------------------------

            if row[4] == "full":
                fullness = "Повна"

            elif row[4] == "empty":
                fullness = "Не повна"

            else:
                fullness = "—"

            # --------------------------------------------------------
            # ACTIVITY / CONCENTRATION
            # --------------------------------------------------------

            activity_json = row[2]
            concentration_json = row[3]

            composition_parts = []

            try:

                activity_dict = (
                    json.loads(activity_json)
                    if activity_json
                    else {}
                )

                concentration_dict = (
                    json.loads(concentration_json)
                    if concentration_json
                    else {}
                )

                if not isinstance(activity_dict, dict):
                    raise ValueError(
                        "activity не является словарём"
                    )

                if not isinstance(concentration_dict, dict):
                    concentration_dict = {}

                if activity_dict:

                    for isotope, activity in activity_dict.items():

                        concentration = (
                            concentration_dict.get(
                                isotope
                            )
                        )

                        try:
                            activity_text = (
                                f"{float(activity):.2f}"
                            )
                        except (TypeError, ValueError):
                            activity_text = "—"

                        try:
                            concentration_text = (
                                f"{float(concentration):.2f}"
                            )
                        except (TypeError, ValueError):
                            concentration_text = "—"

                        composition_parts.append(
                            (
                                f"{isotope}: "
                                f"{activity_text} Бк, "
                                f"{concentration_text} Бк/л"
                            )
                        )

                else:

                    composition_parts.append(
                        "немає даних"
                    )

            except (
                TypeError,
                ValueError,
                json.JSONDecodeError
            ):

                composition_parts.append(
                    "помилка даних"
                )

            composition_str = "; ".join(
                composition_parts
            )

            # --------------------------------------------------------
            # ЗАПОЛНЯЕМ СТРОКУ
            # --------------------------------------------------------

            model.setItem(
                row_idx,
                0,
                QStandardItem(timestamp)
            )

            model.setItem(
                row_idx,
                1,
                QStandardItem(paed)
            )

            model.setItem(
                row_idx,
                2,
                QStandardItem(composition_str)
            )

            model.setItem(
                row_idx,
                3,
                QStandardItem(fullness)
            )

        self.ui.tableView_activity.setModel(model)

        self.ui.tableView_activity.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )


    
    def load_events_data(self):
        """
        Загружает системные события за выбранный период.

        Поддерживает просмотр событий как активных,
        так и ранее заменённых приборов.
        """

        date_from, date_to = self.get_date_range(
            "events"
        )

        # ------------------------------------------------------------
        # 1. ПРОВЕРКА ПЕРИОДА
        # ------------------------------------------------------------

        if date_from > date_to:
            QMessageBox.warning(
                self,
                "Попередження",
                "Початкова дата не може бути пізніше кінцевої."
            )
            return

        # ------------------------------------------------------------
        # 2. ТИП СОБЫТИЯ
        # ------------------------------------------------------------

        event_type = (
            self.ui.combo_event_type.currentText()
        )

        if event_type == "Всі":
            event_type = None

        # ------------------------------------------------------------
        # 3. ПРИБОР
        # ------------------------------------------------------------

        device_sn = (
            self.ui.combo_device_events.currentData()
        )

        device_id = None

        if device_sn:

            device_id = (
                self.db_manager.get_device_id_for_history(
                    device_sn
                )
            )

            if device_id is None:
                QMessageBox.warning(
                    self,
                    "Помилка",
                    "Прилад не знайдено в базі даних."
                )
                return

        # ------------------------------------------------------------
        # 4. SQL
        # ------------------------------------------------------------
        #
        # Сразу соединяем system_events и devices через LEFT JOIN.
        #
        # Это исключает старую схему, при которой для каждой строки
        # события выполнялся ещё один отдельный SELECT.
        # ------------------------------------------------------------

        query = """
            SELECT
                system_events.timestamp,
                system_events.event_type,
                system_events.description,
                devices.serial_number
            FROM system_events
            LEFT JOIN devices
                ON devices.id = system_events.device_id
            WHERE system_events.timestamp BETWEEN ? AND ?
        """

        params = [
            date_from.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            date_to.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        ]

        if event_type:

            query += """
                AND system_events.event_type = ?
            """

            params.append(event_type)

        if device_id is not None:

            query += """
                AND system_events.device_id = ?
            """

            params.append(device_id)

        query += """
            ORDER BY system_events.timestamp DESC
        """

        # ------------------------------------------------------------
        # 5. ЧИТАЕМ СОБЫТИЯ
        # ------------------------------------------------------------

        try:

            conn = self.db_manager._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                query,
                params
            )

            rows = cursor.fetchall()

        except Exception as e:

            QMessageBox.critical(
                self,
                "Помилка",
                f"Не вдалося прочитати системні події:\n{e}"
            )
            return

        # ------------------------------------------------------------
        # 6. СОЗДАЕМ МОДЕЛЬ ТАБЛИЦЫ
        # ------------------------------------------------------------

        model = QStandardItemModel()

        model.setHorizontalHeaderLabels(
            [
                "Час",
                "Тип події",
                "Прилад",
                "Опис"
            ]
        )

        # ------------------------------------------------------------
        # 7. ЗАПОЛНЯЕМ ТАБЛИЦУ
        # ------------------------------------------------------------

        for row_idx, row in enumerate(rows):

            try:
                timestamp = datetime.strptime(
                    row[0],
                    "%Y-%m-%d %H:%M:%S"
                ).strftime(
                    "%d.%m.%Y %H:%M:%S"
                )
            except (TypeError, ValueError):
                timestamp = str(row[0] or "—")

            event_type_text = (
                str(row[1])
                if row[1] is not None
                else "—"
            )

            description = (
                str(row[2])
                if row[2] is not None
                else ""
            )

            device_sn_text = (
                str(row[3])
                if row[3] is not None
                else "—"
            )

            model.setItem(
                row_idx,
                0,
                QStandardItem(timestamp)
            )

            model.setItem(
                row_idx,
                1,
                QStandardItem(event_type_text)
            )

            model.setItem(
                row_idx,
                2,
                QStandardItem(device_sn_text)
            )

            model.setItem(
                row_idx,
                3,
                QStandardItem(description)
            )

        self.ui.tableView_events.setModel(model)

        self.ui.tableView_events.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )



    def reset_filters(self, tab):
        """
        Сбрасывает фильтры только выбранной вкладки.

        ВАЖНО:
        Сброс одной вкладки не должен изменять период
        или фильтры других вкладок.
        """

        # ------------------------------------------------------------
        # ОБЩИЙ ПЕРИОД ПО УМОЛЧАНИЮ
        # ------------------------------------------------------------

        now = QDateTime.currentDateTime()
        week_ago = now.addDays(-7)

        # ------------------------------------------------------------
        # ВКЛАДКА ПАЕД
        # ------------------------------------------------------------

        if tab == "paed":

            # Возвращаем период только этой вкладки
            # к последним 7 дням.
            self.ui.dateFrom_paed.setDateTime(
                week_ago
            )

            self.ui.dateTo_paed.setDateTime(
                now
            )

            # Возвращаем тип расположения к "Всі".
            #
            # Изменение индекса автоматически вызовет
            # on_location_type_changed(), который сформирует
            # правильный список всех приборов.
            self.ui.combo_location_type_paed.setCurrentIndex(0)

            # Группа при режиме "Всі" не используется.
            self.ui.combo_group_paed.setCurrentIndex(0)
            self.ui.combo_group_paed.setEnabled(False)

            # После вызова on_location_type_changed()
            # список приборов уже заполнен.
            # Возвращаем выбор на служебную первую строку.
            self.ui.combo_device_paed.setCurrentIndex(0)

            # В новой логике список приборов при "Всі"
            # должен оставаться доступным.
            self.ui.combo_device_paed.setEnabled(True)

        # ------------------------------------------------------------
        # ВКЛАДКА АКТИВНОСТИ
        # ------------------------------------------------------------

        elif tab == "activity":

            self.ui.dateFrom_activity.setDateTime(
                week_ago
            )

            self.ui.dateTo_activity.setDateTime(
                now
            )

            self.ui.combo_device_activity.setCurrentIndex(0)
            self.ui.combo_group_activity.setCurrentIndex(0)

        # ------------------------------------------------------------
        # ВКЛАДКА СИСТЕМНЫХ СОБЫТИЙ
        # ------------------------------------------------------------

        elif tab == "events":

            self.ui.dateFrom_events.setDateTime(
                week_ago
            )

            self.ui.dateTo_events.setDateTime(
                now
            )

            self.ui.combo_event_type.setCurrentIndex(0)
            self.ui.combo_device_events.setCurrentIndex(0)


    
    def set_all_period(self, tab):
        """
        Устанавливает период просмотра за весь нормативный
        срок хранения данных — последние 5 лет.
        """

        now = QDateTime.currentDateTime()

        # Данные в БД хранятся 5 лет.
        five_years_ago = now.addYears(-5)

        if tab == "paed":

            self.ui.dateFrom_paed.setDateTime(
                five_years_ago
            )

            self.ui.dateTo_paed.setDateTime(
                now
            )

        elif tab == "activity":

            self.ui.dateFrom_activity.setDateTime(
                five_years_ago
            )

            self.ui.dateTo_activity.setDateTime(
                now
            )

        elif tab == "events":

            self.ui.dateFrom_events.setDateTime(
                five_years_ago
            )

            self.ui.dateTo_events.setDateTime(
                now
            )


    
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