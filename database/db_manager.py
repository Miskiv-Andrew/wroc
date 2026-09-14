# database/db_manager.py

import sqlite3
import os
import json
import hashlib
from   PySide6.QtCore import QTimer
from   datetime import datetime, timedelta


class DatabaseManager:

    def __init__(self, db_path="data/clinic.db"):
        """
        Инициализация менеджера базы данных.
        db_path: путь к файлу базы данных SQLite
        """
        # Создаём директорию для БД, если её нет
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self.db_path = db_path
        self.connection = None
        self.devices_map = {}  # {serial_number: device_id} только для активных приборов
        
        # Буфер для настенных детекторов: {device_id: (timestamp, paed, temperature, low_status, high_status, valid)}
        self.wall_buffer = {}
        
        # ------------------------------------------------------------
        # НОВЫЕ АТРИБУТЫ ДЛЯ ИНТЕРВАЛОВ СОХРАНЕНИЯ
        # ------------------------------------------------------------
        self.cistern_save_interval = 3600   # секунды (по умолчанию 1 час)
        self.wall_save_interval = 1800      # секунды (по умолчанию 30 минут)
        
        # ------------------------------------------------------------
        # ТАЙМЕРЫ ДЛЯ ПЕРИОДИЧЕСКОГО СБРОСА БУФЕРОВ
        # ------------------------------------------------------------
        # Таймер для настенных детекторов (заменяет старый flush_timer)
        self.wall_timer = QTimer()
        self.wall_timer.timeout.connect(self._flush_wall_buffer)
        self.wall_timer.start(self.wall_save_interval * 1000)  # переводим в мс
        
        # Таймер для цистерн (только для неактивных режимов)
        self.cistern_timer = QTimer()
        self.cistern_timer.timeout.connect(self.flush_inactive_cistern_buffer)
        self.cistern_timer.start(self.cistern_save_interval * 1000)
        
        # ------------------------------------------------------------
        # Создаём таблицы, если их нет
        # ------------------------------------------------------------
        self._create_tables_if_not_exist()

        # Заполняем devices из config.txt
        self._init_devices_from_config()
        
        # Загружаем словарь активных приборов
        self._load_devices_map()
        
        # Очищаем старые записи при старте
        self.cleanup_old_records()
        
        # Запускаем таймер для ежедневной очистки (24 часа)
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self.cleanup_old_records)
        self.cleanup_timer.start(24 * 60 * 60 * 1000)  # 24 часа
        
        # Явно создаём соединение при старте
        self._get_connection()

        # Буфер для цистерн: хранит последнее измерение для каждой цистерны.
        # Ключ — device_id, значение — кортеж:
        # (timestamp, paed, temperature, activity_json, concentration_json,
        #  low_status, high_status, valid, fullness_status, group, spectrum_active)
        self.cistern_buffer = {}


    
    def _get_connection(self):
        """Возвращает соединение с БД. Создаёт новое, если нет активного."""
        if self.connection is None:
            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row
        return self.connection
    
    def _execute_query(self, query, params=()):
        """Выполняет SQL-запрос и возвращает курсор."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor
    
    def _fetch_all(self, query, params=()):
        """Выполняет SELECT и возвращает все строки."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()



    
    
    def _create_tables_if_not_exist(self):
        """
        Создаёт таблицы базы данных, если они ещё не существуют.

        Для таблицы measurements_cistern дополнительно выполняется
        безопасная миграция уже существующей базы данных.

        ВАЖНО:
        -------
        Старые поля:

            activity
            concentration

        НЕ изменяются по структуре.

        Они по-прежнему содержат JSON вида:

            {
                "18F": 123.4,
                "99mTc": 456.7
            }

        Добавляются новые поля:

            activity_upper
                JSON с верхними статистическими границами активности.

            concentration_upper
                JSON с верхними статистическими границами концентрации.

            result_meta
                JSON со служебной информацией результата.
                В частности, для резервного алгоритма ZB3 здесь
                будет храниться информация о задержанном результате Tc.

            ready_to_drain
                0 / 1 для завершённого спектрального результата.
                NULL для обычной записи PAED, где решение о сливе
                не рассчитывалось.

            measurement_valid
                0 / 1 для завершённого спектрального результата.
                NULL для обычной записи PAED.

        Миграция построена так, чтобы существующий clinic.db
        не удалялся и его старые записи не изменялись.
        """

        # ============================================================
        # 1. ТАБЛИЦА ПРИБОРОВ
        # ============================================================

        self._execute_query("""
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                serial_number TEXT UNIQUE NOT NULL,
                device_type TEXT NOT NULL,
                location_type TEXT NOT NULL,
                position_number INTEGER NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        """)

        # ============================================================
        # 2. ТАБЛИЦА НАСТЕННЫХ ДЕТЕКТОРОВ
        # ============================================================
        #
        # В рамках п.17 её структуру не меняем.

        self._execute_query("""
            CREATE TABLE IF NOT EXISTS measurements_wall (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL,
                timestamp DATETIME NOT NULL,
                paed REAL NOT NULL,
                temperature REAL NOT NULL,
                low_status INTEGER NOT NULL,
                high_status INTEGER NOT NULL,
                valid INTEGER NOT NULL,

                FOREIGN KEY (device_id)
                    REFERENCES devices(id)
                    ON DELETE CASCADE
            )
        """)

        # ============================================================
        # 3. ТАБЛИЦА ИЗМЕРЕНИЙ ЦИСТЕРН
        # ============================================================
        #
        # Для НОВОЙ базы сразу создаём полную актуальную структуру.
        #
        # Если таблица уже существует в старом clinic.db,
        # CREATE TABLE IF NOT EXISTS её не изменит.
        #
        # Поэтому ниже отдельно выполняется миграция отсутствующих
        # столбцов через ALTER TABLE.

        self._execute_query("""
            CREATE TABLE IF NOT EXISTS measurements_cistern (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                device_id INTEGER NOT NULL,

                timestamp DATETIME NOT NULL,

                paed REAL NOT NULL,

                temperature REAL NOT NULL,

                activity TEXT,

                concentration TEXT,

                activity_upper TEXT,

                concentration_upper TEXT,

                result_meta TEXT,

                low_status INTEGER NOT NULL,

                high_status INTEGER NOT NULL,

                valid INTEGER NOT NULL,

                measurement_valid INTEGER,

                fullness_status TEXT NOT NULL,

                "group" TEXT,

                ready_to_drain INTEGER,

                FOREIGN KEY (device_id)
                    REFERENCES devices(id)
                    ON DELETE CASCADE
            )
        """)

        # ============================================================
        # 4. МИГРАЦИЯ СУЩЕСТВУЮЩЕЙ measurements_cistern
        # ============================================================
        #
        # PRAGMA table_info() возвращает структуру уже существующей
        # таблицы.
        #
        # Получаем множество имён её колонок.
        #
        # После этого добавляем только те поля, которых действительно
        # нет.
        #
        # Такой подход позволяет запускать приложение сколько угодно
        # раз:
        #
        #     первая загрузка старой БД -> поля будут добавлены;
        #     последующие загрузки      -> ничего повторно не добавляется.

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "PRAGMA table_info(measurements_cistern)"
        )

        table_info = cursor.fetchall()

        existing_columns = {
            row["name"]
            for row in table_info
        }

        # ------------------------------------------------------------
        # Описание новых полей.
        #
        # Здесь намеренно НЕ устанавливаем DEFAULT 0.
        #
        # Для старых записей и обычных PAED-записей значение NULL
        # имеет важный смысл:
        #
        #     параметр не рассчитывался.
        #
        # Это принципиально отличается от:
        #
        #     0 = параметр рассчитан и имеет отрицательный результат.
        # ------------------------------------------------------------

        required_columns = {
            "activity_upper": "TEXT",
            "concentration_upper": "TEXT",
            "result_meta": "TEXT",
            "ready_to_drain": "INTEGER",
            "measurement_valid": "INTEGER",
        }

        try:

            for column_name, column_type in required_columns.items():

                if column_name in existing_columns:
                    continue

                # ----------------------------------------------------
                # Имена столбцов здесь НЕ поступают от пользователя.
                #
                # Они заданы непосредственно в исходном коде выше,
                # поэтому безопасно использовать их в SQL-структуре.
                # ----------------------------------------------------

                cursor.execute(
                    f"""
                    ALTER TABLE measurements_cistern
                    ADD COLUMN "{column_name}" {column_type}
                    """
                )

            # --------------------------------------------------------
            # Миграция всех отсутствующих колонок завершилась успешно.
            # Только теперь фиксируем изменения.
            # --------------------------------------------------------

            conn.commit()

        except Exception:

            # --------------------------------------------------------
            # Если миграция не завершилась полностью, пытаемся
            # откатить текущую транзакцию.
            #
            # Исключение НЕ скрываем.
            #
            # Инициализация программы должна явно сообщить об ошибке БД,
            # а не продолжить работу с неизвестной структурой таблицы.
            # --------------------------------------------------------

            try:
                conn.rollback()
            except Exception:
                pass

            raise

        # ============================================================
        # 5. ТАБЛИЦА СИСТЕМНЫХ СОБЫТИЙ
        # ============================================================

        self._execute_query("""
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                device_id INTEGER,

                timestamp DATETIME NOT NULL,

                event_type TEXT NOT NULL,

                description TEXT,

                FOREIGN KEY (device_id)
                    REFERENCES devices(id)
                    ON DELETE SET NULL
            )
        """)

        # ============================================================
        # 6. ИНДЕКСЫ
        # ============================================================

        self._execute_query("""
            CREATE INDEX IF NOT EXISTS
            idx_wall_timestamp
            ON measurements_wall(timestamp)
        """)

        self._execute_query("""
            CREATE INDEX IF NOT EXISTS
            idx_cistern_timestamp
            ON measurements_cistern(timestamp)
        """)

        self._execute_query("""
            CREATE INDEX IF NOT EXISTS
            idx_events_timestamp
            ON system_events(timestamp)
        """)

        self._execute_query("""
            CREATE INDEX IF NOT EXISTS
            idx_events_device
            ON system_events(device_id)
        """)

        self._execute_query("""
            CREATE INDEX IF NOT EXISTS
            idx_wall_device
            ON measurements_wall(device_id)
        """)

        self._execute_query("""
            CREATE INDEX IF NOT EXISTS
            idx_cistern_device
            ON measurements_cistern(device_id)
        """)


    
    def _load_devices_map(self):
        """Загружает словарь активных приборов {serial_number: device_id}"""
        self.devices_map = {}
        rows = self._fetch_all("SELECT id, serial_number FROM devices WHERE is_active = 1")
        for row in rows:
            self.devices_map[row["serial_number"]] = row["id"]
    
    def get_device_id(self, serial_number):
        """
        Возвращает device_id для активного прибора по серийному номеру.
        Если прибор не найден или неактивен — возвращает None.
        """
        return self.devices_map.get(serial_number)
    
    def get_all_active_devices(self):
        """
        Возвращает список всех активных приборов с их данными.
        """
        rows = self._fetch_all("""
            SELECT id, serial_number, device_type, location_type, position_number, is_active
            FROM devices WHERE is_active = 1
        """)
        return [dict(row) for row in rows]


    
    
    def cleanup_old_records(self):
        """
        Удаляет записи, возраст которых превышает 5 КАЛЕНДАРНЫХ лет.

        Это важно для требования хранения данных не менее 5 лет.

        Старый вариант:

            datetime.now() - timedelta(days=5 * 365)

        не является точным календарным интервалом в 5 лет,
        потому что между датами могут встречаться високосные годы.

        Новый вариант вычисляет дату, соответствующую той же
        календарной дате ровно 5 лет назад.

        Отдельно обрабатывается случай 29 февраля.
        """

        # ------------------------------------------------------------
        # Текущая дата и время.
        # ------------------------------------------------------------

        now = datetime.now()

        try:

            # --------------------------------------------------------
            # Обычный случай:
            #
            # 14.09.2026 -> 14.09.2021
            #
            # Время сохраняется тем же.
            # --------------------------------------------------------

            five_years_ago_dt = now.replace(
                year=now.year - 5
            )

        except ValueError:

            # --------------------------------------------------------
            # Единственный ожидаемый случай ValueError здесь —
            # 29 февраля.
            #
            # Например:
            #
            # 29.02.2032
            #
            # даты 29.02.2027 не существует.
            #
            # Для требования "хранить не менее 5 лет" выбираем
            # консервативный вариант и используем 28 февраля.
            #
            # Это не приведёт к преждевременному удалению записей.
            # --------------------------------------------------------

            five_years_ago_dt = now.replace(
                year=now.year - 5,
                month=2,
                day=28
            )

        # ------------------------------------------------------------
        # Формат timestamp соответствует формату, используемому
        # при записи данных в эту БД.
        # ------------------------------------------------------------

        five_years_ago = five_years_ago_dt.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # ------------------------------------------------------------
        # Удаляем только записи, которые СТРОГО старше пяти лет.
        #
        # Запись с timestamp, равным граничной дате, сохраняется.
        # ------------------------------------------------------------

        conn = self._get_connection()
        cursor = conn.cursor()

        try:

            cursor.execute(
                """
                DELETE FROM measurements_wall
                WHERE timestamp < ?
                """,
                (five_years_ago,)
            )

            cursor.execute(
                """
                DELETE FROM measurements_cistern
                WHERE timestamp < ?
                """,
                (five_years_ago,)
            )

            cursor.execute(
                """
                DELETE FROM system_events
                WHERE timestamp < ?
                """,
                (five_years_ago,)
            )

            # --------------------------------------------------------
            # Все три удаления фиксируем одной транзакцией.
            # --------------------------------------------------------

            conn.commit()

        except Exception:

            # --------------------------------------------------------
            # При ошибке не допускаем частичного удаления таблиц.
            # --------------------------------------------------------

            try:
                conn.rollback()
            except Exception:
                pass

            raise



        
    def buffer_wall_measurement(self, device_id, paed, temperature, low_status, high_status, valid):
        """
        Сохраняет измерение настенного детектора в буфер.
        В буфере хранится только последнее измерение для каждого device_id.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.wall_buffer[device_id] = (timestamp, paed, temperature, low_status, high_status, valid)
    
    def _flush_wall_buffer(self):
        """
        Записывает все буферизованные измерения настенных детекторов в БД.
        """
        if not self.wall_buffer:
            return
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        for device_id, (timestamp, paed, temperature, low_status, high_status, valid) in self.wall_buffer.items():
            cursor.execute("""
                INSERT INTO measurements_wall (device_id, timestamp, paed, temperature, low_status, high_status, valid)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (device_id, timestamp, paed, temperature, low_status, high_status, valid))
        
        conn.commit()
        self.wall_buffer.clear()

        
    
    def save_cistern_measurement(
        self,
        device_id,
        paed,
        temperature,
        activity_json,
        concentration_json,
        low_status,
        high_status,
        valid,
        fullness_status,
        group=None,
        activity_upper_json=None,
        concentration_upper_json=None,
        result_meta_json=None,
        ready_to_drain=None,
        measurement_valid=None
    ):
        """
        Непосредственно сохраняет завершённый результат измерения
        цистерны в таблицу measurements_cistern.

        Этот метод используется прежде всего для записи результата
        завершённого спектрального цикла.

        Параметры:
        ----------
        device_id
            ID прибора в таблице devices.

        paed
            Последнее актуальное значение ПАЕД.

        temperature
            Последняя актуальная температура.

        activity_json
            JSON с центральными значениями активности:
                {
                    "18F": 123.4,
                    "99mTc": 456.7
                }

        concentration_json
            JSON с центральными значениями концентрации.

        low_status
            Состояние низкочувствительного канала прибора.

        high_status
            Состояние высокочувствительного канала прибора.

        valid
            Валидность текущих приборных данных.

            ВАЖНО:
            Это НЕ то же самое, что measurement_valid.

        fullness_status
            Текущее состояние цистерны:
                "full"
                "empty"

        group
            Группа алгоритма:
                "A"
                "B"
                "reserve"

        activity_upper_json
            JSON с верхними статистическими границами активности.

            Для обычной строки PAED может быть None.

        concentration_upper_json
            JSON с верхними статистическими границами концентрации.

            Для обычной строки PAED может быть None.

        result_meta_json
            JSON со служебной информацией результата.

            В частности, для ZB3 здесь может храниться информация
            о задержанном результате 99mTc.

        ready_to_drain
            0 / 1, если решение о возможности слива было рассчитано.

            None означает:
                решение в данной записи не рассчитывалось.

        measurement_valid
            0 / 1 — валидность именно законченного спектрального
            результата.

            None означает:
                спектральный результат в данной записи отсутствует.

        ВАЖНАЯ ЛОГИКА БУФЕРА:
        ----------------------
        После УСПЕШНОЙ записи полного спектрального результата
        удаляется обычная буферная PAED-запись этой же цистерны.

        Это предотвращает появление двух почти одновременных строк:

            1. полноценный спектральный результат;
            2. старая буферная строка той же цистерны без активности.

        Буферы других цистерн при этом не затрагиваются.
        """

        # ------------------------------------------------------------
        # Формируем время фактического сохранения результата.
        # ------------------------------------------------------------

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ------------------------------------------------------------
        # Записываем полный результат.
        #
        # Новые nullable-поля могут содержать None.
        # sqlite3 автоматически преобразует Python None в SQL NULL.
        # ------------------------------------------------------------

        self._execute_query(
            """
            INSERT INTO measurements_cistern (
                device_id,
                timestamp,
                paed,
                temperature,
                activity,
                concentration,
                activity_upper,
                concentration_upper,
                result_meta,
                low_status,
                high_status,
                valid,
                measurement_valid,
                fullness_status,
                "group",
                ready_to_drain
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                device_id,
                timestamp,
                paed,
                temperature,
                activity_json,
                concentration_json,
                activity_upper_json,
                concentration_upper_json,
                result_meta_json,
                low_status,
                high_status,
                valid,
                measurement_valid,
                fullness_status,
                group,
                ready_to_drain
            )
        )

        # ------------------------------------------------------------
        # До этой точки мы дошли только если INSERT + commit внутри
        # _execute_query() завершились успешно.
        #
        # Теперь старую буферную запись этой же цистерны можно удалить.
        #
        # Если INSERT вызовет исключение, выполнение сюда не дойдёт,
        # поэтому буферная запись останется и данные не будут
        # дополнительно потеряны.
        # ------------------------------------------------------------

        if hasattr(self, "cistern_buffer") and self.cistern_buffer is not None:
            self.cistern_buffer.pop(device_id, None)



    
    def save_system_event(self, device_id, event_type, description):
        """
        Сохраняет системное событие в БД.
        device_id может быть None (событие не связано с конкретным прибором).
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._execute_query("""
            INSERT INTO system_events (device_id, timestamp, event_type, description)
            VALUES (?, ?, ?, ?)
        """, (device_id, timestamp, event_type, description))
    
    def replace_device(self, old_serial_number, new_serial_number, device_type, location_type, position_number):
        """
        Замена прибора.
        - Старый прибор становится неактивным (is_active = 0)
        - Новый прибор добавляется с is_active = 1
        - Обновляются файлы config.txt, hash.txt, cistern.json
        - Записывается событие замены
        """
        # Проверяем существование старого прибора
        old_device = self._fetch_all("SELECT id FROM devices WHERE serial_number = ?", (old_serial_number,))
        if not old_device:
            raise ValueError(f"Старый прибор с SN {old_serial_number} не найден в БД")
        
        # Проверяем, не существует ли уже новый прибор
        new_exists = self._fetch_all("SELECT id FROM devices WHERE serial_number = ?", (new_serial_number,))
        if new_exists:
            raise ValueError(f"Прибор с SN {new_serial_number} уже существует в БД")
        
        # Деактивируем старый прибор
        self._execute_query("UPDATE devices SET is_active = 0 WHERE serial_number = ?", (old_serial_number,))
        
        # Добавляем новый прибор
        self._execute_query("""
            INSERT INTO devices (serial_number, device_type, location_type, position_number, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (new_serial_number, device_type, location_type, position_number))
        
        # Обновляем config.txt
        self._update_config_file(old_serial_number, new_serial_number, location_type, position_number)
        
        # Обновляем cistern.json (если цистерна)
        if location_type == "cistern":
            self._update_cistern_json(position_number)
        
        # Записываем событие замены
        self.save_system_event(None, "device_replaced", 
                               f"Заміна приладу: SN {old_serial_number} -> SN {new_serial_number}, позиція {position_number}")
        
        # Перезагружаем словарь активных приборов
        self._load_devices_map()
        
        return True
    
    def _update_config_file(self, old_sn, new_sn, location_type, position_number):
        """
        Обновляет config.txt: заменяет старый серийный номер на новый.
        """
        config_path = "config/config.txt"
        
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Файл {config_path} не знайдено")
        
        # Читаем текущий config
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        # Обновляем строку с нужным SN
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(old_sn + ";"):
                parts = line.strip().split(";")
                # Формат: serial_number;location_type;position_number;address
                if len(parts) == 4:
                    new_line = f"{new_sn};{parts[1]};{parts[2]};{parts[3]}\n"
                    lines[i] = new_line
                    updated = True
                    break
        
        if not updated:
            raise ValueError(f"Старый SN {old_sn} не найден в config.txt")
        
        # Записываем обновлённый config
        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        
        # Обновляем hash.txt
        with open(config_path, "rb") as f:
            data = f.read()
        sha256_hash = hashlib.sha256(data).hexdigest()
        
        with open("config/hash.txt", "w", encoding="utf-8") as f:
            f.write(sha256_hash)
    
    def _update_cistern_json(self, position_number):
        """
        Обновляет cistern.json: при замене прибора цистерны копирует состояние заполненности
        (оставляет существующее значение для данной позиции).
        """
        cistern_path = "config/cistern.json"
        
        if not os.path.exists(cistern_path):
            # Если файла нет, создаём с пустым состоянием
            cistern_data = {str(position_number): False}
        else:
            with open(cistern_path, "r", encoding="utf-8") as f:
                cistern_data = json.load(f)
            
            # Если позиция существует, оставляем её значение, иначе добавляем False
            if str(position_number) not in cistern_data:
                cistern_data[str(position_number)] = False
        
        # Записываем обновлённый cistern.json
        with open(cistern_path, "w", encoding="utf-8") as f:
            json.dump(cistern_data, f, ensure_ascii=False, indent=4)

    def _init_devices_from_config(self):
        """
        Заполняет таблицу devices из config.txt при первом запуске.
        Добавляет только те приборы, которых ещё нет в БД (по serial_number).
        """
        config_path = "config/config.txt"
        
        if not os.path.exists(config_path):
            # Нет конфигурации - пропускаем (будет создана позже через debug_mode)
            return
        
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            parts = line.split(";")
            if len(parts) != 4:
                continue
            
            serial_number = parts[0]
            location_type = parts[1]
            position_number = int(parts[2])
            # address = parts[3]  # не используется для БД
            
            # Проверяем, существует ли уже прибор в БД
            existing = self._fetch_all("SELECT id FROM devices WHERE serial_number = ?", (serial_number,))
            if existing:
                continue  # уже есть, пропускаем
            
            # Добавляем новый прибор
            device_type = "БДБГ-09S-23"
            self._execute_query("""
                INSERT INTO devices (serial_number, device_type, location_type, position_number, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (serial_number, device_type, location_type, position_number))


    def buffer_cistern_measurement(
        self,
        device_id,
        paed,
        temperature,
        low_status,
        high_status,
        valid,
        fullness_status,
        group=None,
        activity_json="{}",
        concentration_json="{}",
        spectrum_active=False
    ):
        """
        Сохраняет последнее текущее измерение цистерны во внутреннем буфере.

        Для каждого device_id хранится только последнее состояние.

        ВАЖНО:
        -------
        Этот буфер предназначен прежде всего для периодического
        сохранения обычных данных мониторинга:

            - ПАЕД
            - температура
            - статусы детектора
            - состояние заполненности
            - группа цистерны

        Полный завершённый спектральный результат сохраняется отдельно
        через save_cistern_measurement().

        Параметры activity_json и concentration_json пока оставлены
        в сигнатуре для совместимости с уже существующими вызовами
        из app.py.

        Однако в обычной буферной записи они не используются как
        источник завершённого спектрального результата.

        Внутреннее представление буфера теперь dict, а не tuple.
        Это исключает зависимость кода от жёстких числовых индексов.
        """

        # ------------------------------------------------------------
        # Фиксируем время последнего полученного состояния цистерны.
        # ------------------------------------------------------------

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ------------------------------------------------------------
        # Для каждого device_id сохраняем только самое последнее
        # состояние.
        #
        # Предыдущая запись этого device_id заменяется новой.
        # Такое поведение соответствует текущей архитектуре буфера:
        # периодически в БД сохраняется последний актуальный срез,
        # а не каждый входящий пакет.
        # ------------------------------------------------------------

        self.cistern_buffer[device_id] = {
            "timestamp": timestamp,
            "paed": paed,
            "temperature": temperature,
            "low_status": low_status,
            "high_status": high_status,
            "valid": valid,
            "fullness_status": fullness_status,
            "group": group,
            "spectrum_active": bool(spectrum_active),
        }
        

    def flush_cistern_buffer(self):
        """
        Сохраняет все текущие буферизованные измерения цистерн в БД.

        Этот метод используется для сохранения обычных мониторинговых
        срезов цистерн:

            - ПАЕД;
            - температуры;
            - аппаратных статусов;
            - валидности приборных данных;
            - состояния заполненности;
            - группы цистерны.

        ВАЖНО:
        -------
        Буферная запись НЕ является завершённым спектральным
        результатом.

        Поэтому для неё:

            activity              = NULL
            concentration         = NULL
            activity_upper        = NULL
            concentration_upper   = NULL
            result_meta           = NULL
            measurement_valid     = NULL
            ready_to_drain        = NULL

        Это позволяет однозначно отличить обычный мониторинговый
        срез от результата законченного спектрального анализа.

        При ошибке записи или commit() данные НЕ удаляются из
        cistern_buffer.
        """

        # ------------------------------------------------------------
        # Если сохранять нечего — сразу выходим.
        # ------------------------------------------------------------

        if not self.cistern_buffer:
            return

        conn = self._get_connection()
        cursor = conn.cursor()

        # ------------------------------------------------------------
        # Фиксируем список записей, которые существовали в буфере
        # именно на момент начала операции.
        #
        # Работаем с копией items(), чтобы дальнейшее удаление
        # элементов не изменяло словарь во время обхода.
        # ------------------------------------------------------------

        records_to_flush = list(self.cistern_buffer.items())

        try:

            for device_id, record in records_to_flush:

                cursor.execute(
                    """
                    INSERT INTO measurements_cistern (
                        device_id,
                        timestamp,
                        paed,
                        temperature,
                        activity,
                        concentration,
                        activity_upper,
                        concentration_upper,
                        result_meta,
                        low_status,
                        high_status,
                        valid,
                        measurement_valid,
                        fullness_status,
                        "group",
                        ready_to_drain
                    )
                    VALUES (
                        ?, ?, ?, ?,
                        NULL, NULL, NULL, NULL, NULL,
                        ?, ?, ?,
                        NULL,
                        ?, ?,
                        NULL
                    )
                    """,
                    (
                        device_id,
                        record["timestamp"],
                        record["paed"],
                        record["temperature"],
                        record["low_status"],
                        record["high_status"],
                        record["valid"],
                        record["fullness_status"],
                        record["group"],
                    )
                )

            # --------------------------------------------------------
            # Все INSERT выполнены.
            # Фиксируем их одной транзакцией.
            # --------------------------------------------------------

            conn.commit()

        except Exception:

            # --------------------------------------------------------
            # При любой ошибке пытаемся откатить транзакцию.
            #
            # Главное: cistern_buffer ниже НЕ очищается.
            # Следовательно, данные остаются в памяти и могут быть
            # повторно сохранены позднее.
            # --------------------------------------------------------

            try:
                conn.rollback()
            except Exception:
                pass

            # Ошибку не скрываем.
            raise

        # ------------------------------------------------------------
        # Только после успешного commit() удаляем сохранённые записи.
        #
        # Используем pop(device_id, None), а не clear().
        #
        # Это принципиально безопаснее: если между созданием
        # records_to_flush и этим местом для какого-либо device_id
        # появилась более новая запись, её нельзя случайно удалить.
        #
        # Поэтому дополнительно проверяем, что объект record в
        # буфере всё ещё является именно той записью, которую мы
        # только что сохранили.
        # ------------------------------------------------------------

        for device_id, saved_record in records_to_flush:

            current_record = self.cistern_buffer.get(device_id)

            if current_record is saved_record:
                self.cistern_buffer.pop(device_id, None)



    def flush_inactive_cistern_buffer(self):
        """
        Сохраняет в БД только те буферизованные записи цистерн,
        для которых в данный момент НЕ выполняется накопление спектра.

        Используется периодическим таймером cistern_timer.

        Для обычной мониторинговой записи сохраняются:

            - ПАЕД;
            - температура;
            - аппаратные статусы;
            - валидность приборных данных;
            - состояние заполненности;
            - группа цистерны.

        Спектральные поля для таких записей остаются NULL:

            activity
            concentration
            activity_upper
            concentration_upper
            result_meta
            measurement_valid
            ready_to_drain

        ВАЖНО:
        -------
        При ошибке записи или commit() данные не удаляются
        из cistern_buffer.

        После успешного commit() удаляются только те записи,
        которые действительно были сохранены и не успели быть
        заменены более свежими данными.
        """

        # ------------------------------------------------------------
        # Если буфер пуст — сохранять нечего.
        # ------------------------------------------------------------

        if not self.cistern_buffer:
            return

        # ------------------------------------------------------------
        # Выбираем только те записи, для которых накопление спектра
        # сейчас не активно.
        #
        # Работаем с отдельным списком, чтобы не изменять словарь
        # во время обхода.
        # ------------------------------------------------------------

        records_to_flush = []

        for device_id, record in self.cistern_buffer.items():

            if not record.get("spectrum_active", False):
                records_to_flush.append(
                    (device_id, record)
                )

        # ------------------------------------------------------------
        # Если все цистерны сейчас находятся в режиме накопления,
        # ничего не записываем.
        # ------------------------------------------------------------

        if not records_to_flush:
            return

        conn = self._get_connection()
        cursor = conn.cursor()

        try:

            # --------------------------------------------------------
            # Сохраняем выбранные записи одной транзакцией.
            # --------------------------------------------------------

            for device_id, record in records_to_flush:

                cursor.execute(
                    """
                    INSERT INTO measurements_cistern (
                        device_id,
                        timestamp,
                        paed,
                        temperature,
                        activity,
                        concentration,
                        activity_upper,
                        concentration_upper,
                        result_meta,
                        low_status,
                        high_status,
                        valid,
                        measurement_valid,
                        fullness_status,
                        "group",
                        ready_to_drain
                    )
                    VALUES (
                        ?, ?, ?, ?,
                        NULL, NULL, NULL, NULL, NULL,
                        ?, ?, ?,
                        NULL,
                        ?, ?,
                        NULL
                    )
                    """,
                    (
                        device_id,
                        record["timestamp"],
                        record["paed"],
                        record["temperature"],
                        record["low_status"],
                        record["high_status"],
                        record["valid"],
                        record["fullness_status"],
                        record["group"],
                    )
                )

            # --------------------------------------------------------
            # Все INSERT выполнены успешно — фиксируем транзакцию.
            # --------------------------------------------------------

            conn.commit()

        except Exception:

            # --------------------------------------------------------
            # При ошибке откатываем текущую транзакцию.
            #
            # Буфер при этом остаётся нетронутым.
            # --------------------------------------------------------

            try:
                conn.rollback()
            except Exception:
                pass

            raise

        # ------------------------------------------------------------
        # После успешного commit() удаляем только те записи,
        # которые были фактически сохранены.
        #
        # Если между началом операции и этим местом для device_id
        # пришла более новая запись, её удалять нельзя.
        # ------------------------------------------------------------

        for device_id, saved_record in records_to_flush:

            current_record = self.cistern_buffer.get(device_id)

            if current_record is saved_record:
                self.cistern_buffer.pop(device_id, None)




    def set_cistern_save_interval(self, seconds):
        """
        Встановлює інтервал збереження даних для неактивних цистерн.
        
        Вхід:
            seconds - int, інтервал у секундах
        """
        if seconds < 1:
            return
        self.cistern_save_interval = seconds
        if hasattr(self, 'cistern_timer') and self.cistern_timer is not None:
            self.cistern_timer.stop()
            self.cistern_timer.start(seconds * 1000)

    def set_wall_save_interval(self, seconds):
        """
        Встановлює інтервал збереження даних для настінних детекторів.
        
        Вхід:
            seconds - int, інтервал у секундах
        """
        if seconds < 1:
            return
        self.wall_save_interval = seconds
        if hasattr(self, 'wall_timer') and self.wall_timer is not None:
            self.wall_timer.stop()
            self.wall_timer.start(seconds * 1000)


    def get_device_active_status(self, serial_number: str) -> bool:
        """
            Повертає is_active для приладу за SN (безпечний для використання в різних потоках)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM devices WHERE serial_number = ?", (serial_number,))
        row = cursor.fetchone()
        conn.close()
        return bool(row[0]) if row else True 

    def get_inactive_devices(self):
        """
        Возвращает список неактивных приборов из БД.
        Используется для заполнения списка активации в диалоге замены.
        """
        rows = self._fetch_all("SELECT serial_number, location_type, position_number FROM devices WHERE is_active = 0")
        return [dict(row) for row in rows]
        

    def activate_device(self, serial_number: str):
        """
            Активує прилад (безпечний для різних потоків)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE devices SET is_active = 1 WHERE serial_number = ?", (serial_number,))
        conn.commit()
        conn.close()   

    def reload_devices_map(self):
        """
            Перезавантажує кеш активних приладів (потокобезпечний)
        """
        # Створюємо тимчасове з'єднання в поточному потоці
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, serial_number FROM devices WHERE is_active = 1")
        rows = cursor.fetchall()
        conn.close()
        
        # Оновлюємо кеш
        self.devices_map = {}
        for row in rows:
            self.devices_map[row[1]] = row[0]

    def device_exists(self, serial_number: str) -> bool:
        """
        Проверяет, существует ли прибор с данным серийным номером в БД.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM devices WHERE serial_number = ?", (serial_number,))
        row = cursor.fetchone()
        return row is not None

    

    
    def close(self):
        """
        Корректно завершает работу DatabaseManager.

        Перед закрытием соединения:

            1. останавливаются таймеры DatabaseManager;
            2. сохраняется буфер настенных детекторов;
            3. сохраняется буфер цистерн;
            4. только после этого закрывается SQLite-соединение.

        ВАЖНО:
        -------
        flush-методы построены так, что при ошибке записи данные
        не удаляются из соответствующего буфера.

        Исключения при сохранении не скрываются: вызывающий код
        должен знать, что штатное сохранение данных перед закрытием
        БД выполнить не удалось.
        """

        # ------------------------------------------------------------
        # Сначала останавливаем таймеры.
        #
        # После начала процедуры закрытия никакой таймер
        # DatabaseManager не должен инициировать новую операцию
        # сохранения или очистки БД.
        # ------------------------------------------------------------

        if hasattr(self, "wall_timer") and self.wall_timer is not None:
            self.wall_timer.stop()

        if hasattr(self, "cistern_timer") and self.cistern_timer is not None:
            self.cistern_timer.stop()

        if hasattr(self, "cleanup_timer") and self.cleanup_timer is not None:
            self.cleanup_timer.stop()

        flush_error = None

        # ------------------------------------------------------------
        # Сохраняем буфер настенных детекторов.
        #
        # Ошибку запоминаем, но всё равно пытаемся сохранить
        # cistern_buffer. Ошибка одной группы данных не должна
        # автоматически лишать нас возможности сохранить другую.
        # ------------------------------------------------------------

        try:
            self._flush_wall_buffer()

        except Exception as exc:
            flush_error = exc

        # ------------------------------------------------------------
        # Сохраняем ВСЕ оставшиеся данные цистерн.
        #
        # Здесь используется flush_cistern_buffer(), а не
        # flush_inactive_cistern_buffer(), потому что при закрытии
        # приложения необходимо попытаться сохранить последнее
        # состояние даже той цистерны, которая находилась в режиме
        # накопления спектра.
        # ------------------------------------------------------------

        try:
            self.flush_cistern_buffer()

        except Exception as exc:

            # Если ошибка wall_buffer уже была, сохраняем её как
            # первоначальную причину.
            #
            # Если ошибки раньше не было — запоминаем ошибку
            # cistern_buffer.
            if flush_error is None:
                flush_error = exc

        # ------------------------------------------------------------
        # После попыток сохранения закрываем соединение.
        #
        # Даже если flush завершился ошибкой, оставлять открытое
        # SQLite-соединение при завершении программы нельзя.
        # ------------------------------------------------------------

        try:

            if self.connection is not None:
                self.connection.close()
                self.connection = None

        except Exception as exc:

            if flush_error is None:
                flush_error = exc

        # ------------------------------------------------------------
        # Если на каком-либо этапе возникла ошибка — сообщаем о ней
        # вызывающему коду.
        #
        # При нормальном завершении метод просто заканчивает работу.
        # ------------------------------------------------------------

        if flush_error is not None:
            raise flush_error