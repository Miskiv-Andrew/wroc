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
        
        # Таймер для сброса буфера раз в 30 минут
        self.flush_timer = QTimer()
        self.flush_timer.timeout.connect(self._flush_wall_buffer)
        self.flush_timer.start(30 * 60 * 1000)  # 30 минут
        
        # Создаём таблицы, если их нет
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
        """Создаёт таблицы и индексы, если они не существуют."""
        
        # Таблица устройств
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
        
        # Таблица измерений настенных детекторов
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
                FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
            )
        """)
        
        # Таблица измерений цистерн
        self._execute_query("""
            CREATE TABLE IF NOT EXISTS measurements_cistern (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL,
                timestamp DATETIME NOT NULL,
                paed REAL NOT NULL,
                temperature REAL NOT NULL,
                activity REAL NOT NULL,
                low_status INTEGER NOT NULL,
                high_status INTEGER NOT NULL,
                valid INTEGER NOT NULL,
                fullness_status TEXT NOT NULL,
                ready_to_drain INTEGER NOT NULL,
                FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
            )
        """)
        
        # Таблица системных событий
        self._execute_query("""
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER,
                timestamp DATETIME NOT NULL,
                event_type TEXT NOT NULL,
                description TEXT,
                FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE SET NULL
            )
        """)
        
        # Индексы
        self._execute_query("CREATE INDEX IF NOT EXISTS idx_wall_timestamp ON measurements_wall(timestamp)")
        self._execute_query("CREATE INDEX IF NOT EXISTS idx_cistern_timestamp ON measurements_cistern(timestamp)")
        self._execute_query("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON system_events(timestamp)")
        self._execute_query("CREATE INDEX IF NOT EXISTS idx_events_device ON system_events(device_id)")
        self._execute_query("CREATE INDEX IF NOT EXISTS idx_wall_device ON measurements_wall(device_id)")
        self._execute_query("CREATE INDEX IF NOT EXISTS idx_cistern_device ON measurements_cistern(device_id)")
    
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
        Удаляет записи старше 3 лет из всех таблиц.
        """
        three_years_ago = (datetime.now() - timedelta(days=3*365)).strftime("%Y-%m-%d %H:%M:%S")
        
        self._execute_query("DELETE FROM measurements_wall WHERE timestamp < ?", (three_years_ago,))
        self._execute_query("DELETE FROM measurements_cistern WHERE timestamp < ?", (three_years_ago,))
        self._execute_query("DELETE FROM system_events WHERE timestamp < ?", (three_years_ago,))
    
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
    
    def save_cistern_measurement(self, device_id, paed, temperature, activity, low_status, high_status, valid, fullness_status, ready_to_drain):
        """
        Немедленно сохраняет измерение цистерны в БД (без буферизации).
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._execute_query("""
            INSERT INTO measurements_cistern 
            (device_id, timestamp, paed, temperature, activity, low_status, high_status, valid, fullness_status, ready_to_drain)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (device_id, timestamp, paed, temperature, activity, low_status, high_status, valid, fullness_status, ready_to_drain))
    
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
            Повертає список неактивних приладів
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT serial_number, location_type, position_number FROM devices WHERE is_active = 0")
        rows = cursor.fetchall()
        conn.close()
        return [{"serial_number": row[0], "location_type": row[1], "position_number": row[2]} for row in rows]
    

    def activate_device(self, serial_number: str):
        """
            Активує прилад (безпечний для різних потоків)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE devices SET is_active = 1 WHERE serial_number = ?", (serial_number,))
        conn.commit()
        conn.close()

    # def reload_devices_map(self):
    #     """Перезавантажує кеш активних приладів"""
    #     self._load_devices_map()

    def reload_devices_map(self):
        """Перезавантажує кеш активних приладів (потокобезпечний)"""
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

    
    def close(self):
        """
        Закрывает соединение с БД и сбрасывает буфер.
        """
        self._flush_wall_buffer()
        if self.connection:
            self.connection.close()
            self.connection = None