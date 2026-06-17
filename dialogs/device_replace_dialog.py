# import os
# import json
# import hashlib
# from PySide6.QtWidgets import QDialog, QMessageBox
# from PySide6.QtUiTools import QUiLoader
# from PySide6.QtCore import QFile

# from devices.address_changer import AddressChanger
# from database.db_manager import DatabaseManager


# class DeviceReplaceDialog(QDialog):   

#     def __init__(self, db_manager, active_devices, inactive_devices, parent=None):
#         super().__init__(parent)
        
#         self.db_manager = db_manager
#         self.active_devices = active_devices      # для заміни
#         self.inactive_devices = inactive_devices  # для активації
#         self.new_device_info = None
#         self.address_changer = AddressChanger(db_manager)
        
#         # Завантажуємо UI
#         loader = QUiLoader()
#         ui_file = QFile("_UI/device_replace.ui")
#         ui_file.open(QFile.ReadOnly)
#         self.ui = loader.load(ui_file)
#         ui_file.close()
        
#         if self.ui is None:
#             raise RuntimeError("Не удалось загрузить _UI/device_replace.ui")
        
#         self.setLayout(self.ui.layout())
#         self.setWindowTitle(self.ui.windowTitle())
        
#         self.setup_connections()
#         self.load_active_devices()      # для заміни
#         self.load_inactive_devices()    # для активації
        
#         self.address_changer.status.connect(self.on_status)
#         self.address_changer.error.connect(self.on_error)
#         self.address_changer.found.connect(self.on_device_found)
    
#     def setup_connections(self):
#         self.ui.btn_find_new.clicked.connect(self.find_new_device)
#         self.ui.btn_replace.clicked.connect(self.replace_device)
#         self.ui.btn_cancel.clicked.connect(self.reject)
#         self.ui.combo_old_device.currentIndexChanged.connect(self.on_old_device_changed)
#         self.ui.btn_activate.clicked.connect(self.activate_device)
    
#     def load_missing_devices(self):
#         """Заполняет combo_old_device приборами, которые пропали"""
#         self.ui.combo_old_device.clear()
#         for dev in self.missing_devices:
#             self.ui.combo_old_device.addItem(
#                 f"{dev['serial_number']} ({dev['location_type']} №{dev['position_number']})",
#                 dev['serial_number']
#             )
#         if self.missing_devices:
#             self.on_old_device_changed(0)
    
#     # def on_old_device_changed(self, index):
#     #     """При выборе старого прибора показываем его расположение"""
#     #     if index < 0:
#     #         return
#     #     sn = self.ui.combo_old_device.currentData()
#     #     for dev in self.missing_devices:
#     #         if dev['serial_number'] == sn:
#     #             self.ui.label_old_location.setText(f"{dev['location_type']} №{dev['position_number']}")
#     #             break

#     def on_old_device_changed(self, index):
#         if index < 0:
#             return
#         sn = self.ui.combo_old_device.currentData()
#         for dev in self.active_devices:
#             if dev['serial_number'] == sn:
#                 self.ui.label_old_location.setText(f"{dev['location_type']} №{dev['position_number']}")
#                 break
        
#     def find_new_device(self):
#         """Поиск нового прибора на адресах 200-201"""
#         self.ui.btn_find_new.setEnabled(False)
#         self.ui.label_status.setText("Пошук нового приладу...")
#         self.ui.label_status.setStyleSheet("background-color: #fff3cd; color: #856404;")
        
#         # Запускаем поиск (синхронно, но с обработкой сигналов)
#         from PySide6.QtCore import QCoreApplication
#         QCoreApplication.processEvents()
        
#         port, sn, addr = self.address_changer.find_new_device()
        
#         if sn:
#             self.new_device_info = (port, sn, addr)
#             self.ui.edit_new_sn.setText(sn)
#             self.ui.btn_replace.setEnabled(True)
#             self.ui.label_status.setText("Новий прилад знайдено. Натисніть 'Виконати заміну'")
#             self.ui.label_status.setStyleSheet("background-color: #d4edda; color: #155724;")
#         else:
#             self.new_device_info = None
#             self.ui.btn_replace.setEnabled(False)
#             self.ui.label_status.setText("Новий прилад не знайдено. Перевірте підключення.")
#             self.ui.label_status.setStyleSheet("background-color: #f8d7da; color: #721c24;")
        
#         self.ui.btn_find_new.setEnabled(True)
    
#     def replace_device(self):
#         """
#             Выполняет замену прибора
#         """
#         # Получаем данные старого прибора
#         old_sn = self.ui.combo_old_device.currentData()
#         if not old_sn:
#             QMessageBox.warning(self, "Помилка", "Не вибрано старий прилад")
#             return
        
#         # Находим старый прибор в missing_devices
#         old_device = None
#         for dev in self.missing_devices:
#             if dev['serial_number'] == old_sn:
#                 old_device = dev
#                 break
        
#         if not old_device:
#             QMessageBox.warning(self, "Помилка", "Старий прилад не знайдено в конфігурації")
#             return
        
#         # Получаем данные нового прибора
#         if not self.new_device_info:
#             QMessageBox.warning(self, "Помилка", "Не знайдено новий прилад")
#             return
        
#         port, new_sn, old_addr = self.new_device_info

#         # Перевірка на однакові серійні номери
#         if old_sn == new_sn:
#             QMessageBox.warning(self, "Помилка", "Старий та новий прилади мають однаковий серійний номер. Заміна неможлива.")
#             self.ui.label_status.setText("Помилка: однакові SN")
#             self.ui.btn_replace.setEnabled(True)
#             return
        
#         # Получаем целевой адрес из config.txt (по старому SN)
#         target_address = self._get_address_from_config(old_sn)
#         if target_address is None:
#             QMessageBox.warning(self, "Помилка", f"Не вдалося знайти адресу для {old_sn} в config.txt")
#             return
        
#         # Меняем адрес нового прибора
#         self.ui.btn_replace.setEnabled(False)
#         self.ui.label_status.setText("Зміна адреси приладу...")
#         self.ui.label_status.setStyleSheet("background-color: #fff3cd; color: #856404;")
#         QMessageBox.information(self, "Увага", f"Буде змінено адресу приладу {new_sn} з {old_addr} на {target_address}")
        
#         success = self.address_changer.change_address(port, old_addr, target_address, new_sn)
        
#         if not success:
#             self.ui.label_status.setText("Помилка при зміні адреси. Спробуйте ще раз.")
#             self.ui.label_status.setStyleSheet("background-color: #f8d7da; color: #721c24;")
#             self.ui.btn_replace.setEnabled(True)
#             return
        
#         # Обновляем конфигурационные файлы и БД
#         try:
#             self._update_config_files(old_sn, new_sn, old_device)
#             self._update_database(old_sn, new_sn, old_device)
            
#             self.ui.label_status.setText("Заміна виконана. Необхідно перезапустити програму.")
#             self.ui.label_status.setStyleSheet("background-color: #d4edda; color: #155724;")
#             self.ui.btn_replace.setEnabled(False)
            
#             QMessageBox.information(self, "Успіх", 
#                 f"Заміна приладу виконана успішно.\n"
#                 f"Старий SN: {old_sn}\n"
#                 f"Новий SN: {new_sn}\n\n"
#                 f"Необхідно перезапустити програму.")
            
#         except Exception as e:
#             self.ui.label_status.setText(f"Помилка при оновленні конфігурації: {e}")
#             self.ui.label_status.setStyleSheet("background-color: #f8d7da; color: #721c24;")
#             self.ui.btn_replace.setEnabled(True)
    
#     def _get_address_from_config(self, serial_number):
#         """Читает address из config.txt по SN"""
#         config_path = "config/config.txt"
#         if not os.path.exists(config_path):
#             return None
        
#         with open(config_path, "r", encoding="utf-8") as f:
#             for line in f:
#                 line = line.strip()
#                 if not line or line.startswith("#"):
#                     continue
#                 parts = line.split(";")
#                 if len(parts) == 4 and parts[0] == serial_number:
#                     return int(parts[3])
#         return None
    
#     def _update_config_files(self, old_sn, new_sn, old_device):
#         """Обновляет config.txt, hash.txt, cistern.json"""
#         config_path = "config/config.txt"
        
#         # Читаем config
#         with open(config_path, "r", encoding="utf-8") as f:
#             lines = f.readlines()
        
#         # Обновляем строку со старым SN
#         updated = False
#         for i, line in enumerate(lines):
#             if line.startswith(old_sn + ";"):
#                 parts = line.strip().split(";")
#                 if len(parts) == 4:
#                     new_line = f"{new_sn};{parts[1]};{parts[2]};{parts[3]}\n"
#                     lines[i] = new_line
#                     updated = True
#                     break
        
#         if not updated:
#             raise ValueError(f"SN {old_sn} не найден в config.txt")
        
#         # Записываем config
#         with open(config_path, "w", encoding="utf-8") as f:
#             f.writelines(lines)
        
#         # Обновляем hash.txt
#         with open(config_path, "rb") as f:
#             data = f.read()
#         sha256_hash = hashlib.sha256(data).hexdigest()
#         with open("config/hash.txt", "w", encoding="utf-8") as f:
#             f.write(sha256_hash)
        
#         # Обновляем cistern.json (если цистерна)
#         if old_device['location_type'] == 'cistern':
#             cistern_path = "config/cistern.json"
#             if os.path.exists(cistern_path):
#                 with open(cistern_path, "r", encoding="utf-8") as f:
#                     cistern_data = json.load(f)
#             else:
#                 cistern_data = {}
            
#             pos = str(old_device['position_number'])
#             if pos not in cistern_data:
#                 cistern_data[pos] = False
            
#             with open(cistern_path, "w", encoding="utf-8") as f:
#                 json.dump(cistern_data, f, ensure_ascii=False, indent=4)
    
#     def _update_database(self, old_sn, new_sn, old_device):
#         """Обновляет БД: старый прибор is_active=0, новый добавляется"""
#         # Деактивируем старый
#         conn = self.db_manager._get_connection()
#         cursor = conn.cursor()
#         cursor.execute("UPDATE devices SET is_active = 0 WHERE serial_number = ?", (old_sn,))
        
#         # Добавляем новый
#         cursor.execute("""
#             INSERT INTO devices (serial_number, device_type, location_type, position_number, is_active)
#             VALUES (?, ?, ?, ?, 1)
#         """, (new_sn, "БДБГ-09S-23", old_device['location_type'], old_device['position_number']))
        
#         conn.commit()
        
#         # Записываем событие
#         self.db_manager.save_system_event(None, "device_replaced", 
#             f"Заміна приладу: {old_sn} -> {new_sn}, позиція {old_device['position_number']}")
        
#         # Перезагружаем кэш активных приборов в db_manager
#         self.db_manager._load_devices_map()
    
#     def on_status(self, message):
#         self.ui.label_status.setText(message)
    
#     def on_error(self, message):
#         self.ui.label_status.setText(message)
#         self.ui.label_status.setStyleSheet("background-color: #f8d7da; color: #721c24;")
    
#     def on_device_found(self, port, sn, addr):
#         pass  # обработано в find_new_device

#     def load_active_devices(self):
#         """Заповнює combo_old_device активними приладами (для заміни)"""
#         self.ui.combo_old_device.clear()
#         for dev in self.active_devices:
#             self.ui.combo_old_device.addItem(
#                 f"{dev['serial_number']} ({dev['location_type']} №{dev['position_number']})",
#                 dev['serial_number']
#             )
#         if self.active_devices:
#             self.on_old_device_changed(0)

#     def load_inactive_devices(self):
#         """Заповнює combo_inactive_devices неактивними приладами (для активації)"""
#         self.ui.combo_inactive_device.clear()
#         for dev in self.inactive_devices:
#             self.ui.combo_inactive_device.addItem(
#                 f"{dev['serial_number']} ({dev['location_type']} №{dev['position_number']})",
#                 dev['serial_number']
#             )

#     # def activate_device(self):
#     #     """Активує вибраний неактивний прилад"""
#     #     sn = self.ui.combo_inactive_device.currentData()
#     #     if not sn:
#     #         QMessageBox.warning(self, "Помилка", "Не вибрано прилад для активації")
#     #         return
        
#     #     reply = QMessageBox.question(self, "Підтвердження", 
#     #                                 f"Активувати прилад {sn}?",
#     #                                 QMessageBox.Yes | QMessageBox.No)
#     #     if reply != QMessageBox.Yes:
#     #         return
        
#     #     conn = self.db_manager._get_connection()
#     #     cursor = conn.cursor()
#     #     cursor.execute("UPDATE devices SET is_active = 1 WHERE serial_number = ?", (sn,))
#     #     conn.commit()
        
#     #     self.db_manager.save_system_event(None, "device_activated", f"Прилад {sn} активовано")
        
#     #     QMessageBox.information(self, "Успіх", f"Прилад {sn} активовано. Необхідно перезапустити програму.")
#     #     self.ui.label_status.setText("Прилад активовано. Перезапустіть програму.")

#     def activate_device(self):
#         """Активує вибраний неактивний прилад"""
#         sn = self.ui.combo_inactive_device.currentData()
#         if not sn:
#             QMessageBox.warning(self, "Помилка", "Не вибрано прилад для активації")
#             return
        
#         reply = QMessageBox.question(self, "Підтвердження", 
#                                     f"Активувати прилад {sn}?",
#                                     QMessageBox.Yes | QMessageBox.No)
#         if reply != QMessageBox.Yes:
#             return
        
#         self.db_manager.activate_device(sn)
#         self.db_manager.reload_devices_map()
        
#         self.db_manager.save_system_event(None, "device_activated", f"Прилад {sn} активовано")
        
#         QMessageBox.information(self, "Успіх", f"Прилад {sn} активовано. Необхідно перезапустити програму.")
#         self.ui.label_status.setText("Прилад активовано. Перезапустіть програму.")

###########################################################################################################################################################



import os
import json
import hashlib
from PySide6.QtWidgets import QDialog, QMessageBox
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile

from devices.address_changer import AddressChanger
from database.db_manager import DatabaseManager


class DeviceReplaceDialog(QDialog):

    def __init__(self, db_manager, active_devices, inactive_devices, parent=None):
        super().__init__(parent)
        
        self.db_manager = db_manager
        self.active_devices = active_devices      # для заміни
        self.inactive_devices = inactive_devices  # для активації
        self.new_device_info = None               # (port, serial_number, address)
        self.address_changer = AddressChanger(db_manager)
        
        # Завантажуємо UI
        loader = QUiLoader()
        ui_file = QFile("_UI/device_replace.ui")
        ui_file.open(QFile.ReadOnly)
        self.ui = loader.load(ui_file)
        ui_file.close()
        
        if self.ui is None:
            raise RuntimeError("Не удалось загрузить _UI/device_replace.ui")
        
        self.setLayout(self.ui.layout())
        self.setWindowTitle(self.ui.windowTitle())
        
        self.setup_connections()
        self.load_active_devices()      # для заміни
        self.load_inactive_devices()    # для активації
        
        self.address_changer.status.connect(self.on_status)
        self.address_changer.error.connect(self.on_error)
        self.address_changer.found.connect(self.on_device_found)
    
    def setup_connections(self):
        self.ui.btn_find_new.clicked.connect(self.find_new_device)
        self.ui.btn_replace.clicked.connect(self.replace_device)
        self.ui.btn_cancel.clicked.connect(self.reject)
        self.ui.combo_old_device.currentIndexChanged.connect(self.on_old_device_changed)
        self.ui.btn_activate.clicked.connect(self.activate_device)
    
    def load_active_devices(self):
        """Заповнює combo_old_device активними приладами (для заміни)"""
        self.ui.combo_old_device.clear()
        for dev in self.active_devices:
            self.ui.combo_old_device.addItem(
                f"{dev['serial_number']} ({dev['location_type']} №{dev['position_number']})",
                dev['serial_number']
            )
        if self.active_devices:
            self.on_old_device_changed(0)
    
    def load_inactive_devices(self):
        """Заповнює combo_inactive_devices неактивними приладами (для активації)"""
        self.ui.combo_inactive_device.clear()
        for dev in self.inactive_devices:
            self.ui.combo_inactive_device.addItem(
                f"{dev['serial_number']} ({dev['location_type']} №{dev['position_number']})",
                dev['serial_number']
            )
    
    def on_old_device_changed(self, index):
        """При виборі старого приладу показуємо його розташування"""
        if index < 0:
            return
        sn = self.ui.combo_old_device.currentData()
        for dev in self.active_devices:
            if dev['serial_number'] == sn:
                self.ui.label_old_location.setText(f"{dev['location_type']} №{dev['position_number']}")
                break
    
    def find_new_device(self):
        """Пошук нового приладу на адресах 200-201"""
        self.ui.btn_find_new.setEnabled(False)
        self.ui.label_status.setText("Пошук нового приладу...")
        self.ui.label_status.setStyleSheet("background-color: #fff3cd; color: #856404;")
        
        # Запускаємо пошук (синхронно, але з обробкою сигналів)
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        
        port, sn, addr = self.address_changer.find_new_device()
        
        if sn:
            self.new_device_info = (port, sn, addr)
            self.ui.edit_new_sn.setText(sn)
            self.ui.btn_replace.setEnabled(True)
            self.ui.label_status.setText("Новий прилад знайдено. Натисніть 'Виконати заміну'")
            self.ui.label_status.setStyleSheet("background-color: #d4edda; color: #155724;")
        else:
            self.new_device_info = None
            self.ui.btn_replace.setEnabled(False)
            self.ui.label_status.setText("Новий прилад не знайдено. Перевірте підключення.")
            self.ui.label_status.setStyleSheet("background-color: #f8d7da; color: #721c24;")
        
        self.ui.btn_find_new.setEnabled(True)
    
    # def replace_device(self):
    #     """
    #         Виконує заміну приладу
    #     """
    #     # Отримуємо дані старого приладу
    #     old_sn = self.ui.combo_old_device.currentData()
    #     if not old_sn:
    #         QMessageBox.warning(self, "Помилка", "Не вибрано старий прилад")
    #         return
        
    #     # Знаходимо старий прилад в active_devices
    #     old_device = None
    #     for dev in self.active_devices:
    #         if dev['serial_number'] == old_sn:
    #             old_device = dev
    #             break
        
    #     if not old_device:
    #         QMessageBox.warning(self, "Помилка", "Старий прилад не знайдено в конфігурації")
    #         return
        
    #     # Отримуємо дані нового приладу
    #     if not self.new_device_info:
    #         QMessageBox.warning(self, "Помилка", "Не знайдено новий прилад")
    #         return
        
    #     port, new_sn, old_addr = self.new_device_info

    #     # Перевірка на однакові серійні номери
    #     if old_sn == new_sn:
    #         QMessageBox.warning(self, "Помилка", "Старий та новий прилади мають однаковий серійний номер. Заміна неможлива.")
    #         self.ui.label_status.setText("Помилка: однакові SN")
    #         self.ui.btn_replace.setEnabled(True)
    #         return
        
    #     # Отримуємо цільову адресу з config.txt (по старому SN)
    #     target_address = self._get_address_from_config(old_sn)
    #     if target_address is None:
    #         QMessageBox.warning(self, "Помилка", f"Не вдалося знайти адресу для {old_sn} в config.txt")
    #         return
        
    #     # Змінюємо адресу нового приладу
    #     self.ui.btn_replace.setEnabled(False)
    #     self.ui.label_status.setText("Зміна адреси приладу...")
    #     self.ui.label_status.setStyleSheet("background-color: #fff3cd; color: #856404;")
    #     QMessageBox.information(self, "Увага", f"Буде змінено адресу приладу {new_sn} з {old_addr} на {target_address}")
        
    #     success = self.address_changer.change_address(port, old_addr, target_address, new_sn)
        
    #     if not success:
    #         self.ui.label_status.setText("Помилка при зміні адреси. Спробуйте ще раз.")
    #         self.ui.label_status.setStyleSheet("background-color: #f8d7da; color: #721c24;")
    #         self.ui.btn_replace.setEnabled(True)
    #         return
        
    #     # Оновлюємо конфігураційні файли та БД
    #     try:
    #         self._update_config_files(old_sn, new_sn, old_device)
    #         self._update_database(old_sn, new_sn, old_device)
            
    #         self.ui.label_status.setText("Заміна виконана. Необхідно перезапустити програму.")
    #         self.ui.label_status.setStyleSheet("background-color: #d4edda; color: #155724;")
    #         self.ui.btn_replace.setEnabled(False)
            
    #         QMessageBox.information(self, "Успіх", 
    #             f"Заміна приладу виконана успішно.\n"
    #             f"Старий SN: {old_sn}\n"
    #             f"Новий SN: {new_sn}\n\n"
    #             f"Необхідно перезапустити програму.")
            
    #     except Exception as e:
    #         self.ui.label_status.setText(f"Помилка при оновленні конфігурації: {e}")
    #         self.ui.label_status.setStyleSheet("background-color: #f8d7da; color: #721c24;")
    #         self.ui.btn_replace.setEnabled(True)

    def replace_device(self):
        # Отримуємо дані старого приладу
        old_sn = self.ui.combo_old_device.currentData()
        if not old_sn:
            QMessageBox.warning(self, "Помилка", "Не вибрано старий прилад")
            return
        
        # Знаходимо старий прилад в active_devices
        old_device = None
        for dev in self.active_devices:
            if dev['serial_number'] == old_sn:
                old_device = dev
                break
        
        if not old_device:
            QMessageBox.warning(self, "Помилка", "Старий прилад не знайдено в конфігурації")
            return
        
        # Отримуємо дані нового приладу
        if not self.new_device_info:
            QMessageBox.warning(self, "Помилка", "Не знайдено новий прилад")
            return
        
        port, new_sn, old_addr = self.new_device_info

        # Перевірка на однакові серійні номери
        if old_sn == new_sn:
            QMessageBox.warning(self, "Помилка", "Старий та новий прилади мають однаковий серійний номер. Заміна неможлива.")
            self.ui.label_status.setText("Помилка: однакові SN")
            self.ui.btn_replace.setEnabled(True)
            return
        
        # Отримуємо цільову адресу з config.txt (по старому SN)
        target_address = self._get_address_from_config(old_sn)
        if target_address is None:
            QMessageBox.warning(self, "Помилка", f"Не вдалося знайти адресу для {old_sn} в config.txt")
            return
        
        # Змінюємо адресу нового приладу
        self.ui.btn_replace.setEnabled(False)
        self.ui.label_status.setText("Зміна адреси приладу...")
        self.ui.label_status.setStyleSheet("background-color: #fff3cd; color: #856404;")
        
        QMessageBox.information(self, "Увага", f"Буде змінено адресу приладу {new_sn} з {old_addr} на {target_address}")
        
        success = self.address_changer.change_address(port, old_addr, target_address, new_sn)
        
        if not success:
            self.ui.label_status.setText("Помилка при зміні адреси. Спробуйте ще раз.")
            self.ui.label_status.setStyleSheet("background-color: #f8d7da; color: #721c24;")
            self.ui.btn_replace.setEnabled(True)
            return
        
        # Оновлюємо конфігураційні файли та БД
        try:
            self._update_config_files(old_sn, new_sn, old_device)
            self._update_database(old_sn, new_sn, old_device)
            
            self.ui.label_status.setText("Заміна виконана. Необхідно перезапустити програму.")
            self.ui.label_status.setStyleSheet("background-color: #d4edda; color: #155724;")
            self.ui.btn_replace.setEnabled(False)
            
            QMessageBox.information(self, "Успіх", 
                f"Заміна приладу виконана успішно.\n"
                f"Старий SN: {old_sn}\n"
                f"Новий SN: {new_sn}\n\n"
                f"Необхідно перезапустити програму.")
            
        except Exception as e:
            self.ui.label_status.setText(f"Помилка при оновленні конфігурації: {e}")
            self.ui.label_status.setStyleSheet("background-color: #f8d7da; color: #721c24;")
            self.ui.btn_replace.setEnabled(True)


    
    def _get_address_from_config(self, serial_number):
        """Читає address з config.txt по SN"""
        config_path = "config/config.txt"
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(";")
                if len(parts) == 4 and parts[0] == serial_number:
                    return int(parts[3])
        return None
    
    def _update_config_files(self, old_sn, new_sn, old_device):
        """Оновлює config.txt, hash.txt, cistern.json"""
        config_path = "config/config.txt"
        
        # Читаємо config
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        # Оновлюємо рядок зі старим SN
        updated = False
        for i, line in enumerate(lines):
            if line.startswith(old_sn + ";"):
                parts = line.strip().split(";")
                if len(parts) == 4:
                    new_line = f"{new_sn};{parts[1]};{parts[2]};{parts[3]}\n"
                    lines[i] = new_line
                    updated = True
                    break
        
        if not updated:
            raise ValueError(f"SN {old_sn} не знайдено в config.txt")
        
        # Записуємо config
        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        
        # Оновлюємо hash.txt
        with open(config_path, "rb") as f:
            data = f.read()
        sha256_hash = hashlib.sha256(data).hexdigest()
        with open("config/hash.txt", "w", encoding="utf-8") as f:
            f.write(sha256_hash)
        
        # Оновлюємо cistern.json (якщо цистерна)
        if old_device['location_type'] == 'cistern':
            cistern_path = "config/cistern.json"
            if os.path.exists(cistern_path):
                with open(cistern_path, "r", encoding="utf-8") as f:
                    cistern_data = json.load(f)
            else:
                cistern_data = {}
            
            pos = str(old_device['position_number'])
            if pos not in cistern_data:
                cistern_data[pos] = False
            
            with open(cistern_path, "w", encoding="utf-8") as f:
                json.dump(cistern_data, f, ensure_ascii=False, indent=4)
    
    # def _update_database(self, old_sn, new_sn, old_device):
    #     """Оновлює БД: старий прилад is_active=0, новий додається"""
    #     # Деактивуємо старий
    #     conn = self.db_manager._get_connection()
    #     cursor = conn.cursor()
    #     cursor.execute("UPDATE devices SET is_active = 0 WHERE serial_number = ?", (old_sn,))
        
    #     # Додаємо новий
    #     cursor.execute("""
    #         INSERT INTO devices (serial_number, device_type, location_type, position_number, is_active)
    #         VALUES (?, ?, ?, ?, 1)
    #     """, (new_sn, "БДБГ-09S-23", old_device['location_type'], old_device['position_number']))
        
    #     conn.commit()
        
    #     # Записуємо подію
    #     self.db_manager.save_system_event(None, "device_replaced", 
    #         f"Заміна приладу: {old_sn} -> {new_sn}, позиція {old_device['position_number']}")
        
    #     # Перезавантажуємо кеш активних приладів в db_manager
    #     self.db_manager._load_devices_map()

    def _update_database(self, old_sn, new_sn, old_device):
        """
        Обновляет БД:
        - Если SN нового прибора уже существует в БД → UPDATE is_active = 1
        - Если SN нового прибора отсутствует → INSERT новой записи
        - Старый прибор → is_active = 0
        """
        conn = self.db_manager._get_connection()
        cursor = conn.cursor()
        
        # Деактивируем старый прибор
        cursor.execute("UPDATE devices SET is_active = 0 WHERE serial_number = ?", (old_sn,))
        
        # Проверяем, существует ли новый SN в БД
        if self.db_manager.device_exists(new_sn):
            # Прибор уже есть в БД (вернулся из ремонта) → активируем
            cursor.execute("UPDATE devices SET is_active = 1 WHERE serial_number = ?", (new_sn,))
        else:
            # Нового прибора нет в БД → добавляем
            cursor.execute("""
                INSERT INTO devices (serial_number, device_type, location_type, position_number, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (new_sn, "БДБГ-09S-23", old_device['location_type'], old_device['position_number']))
        
        conn.commit()
        
        # Записываем событие замены
        self.db_manager.save_system_event(None, "device_replaced", 
            f"Заміна приладу: {old_sn} -> {new_sn}, позиція {old_device['position_number']}")
        
        # Перезагружаем кеш активных приборов
        self.db_manager._load_devices_map()
    
    def on_status(self, message):
        self.ui.label_status.setText(message)
        self.ui.label_status.setStyleSheet("")
    
    def on_error(self, message):
        self.ui.label_status.setText(message)
        self.ui.label_status.setStyleSheet("background-color: #f8d7da; color: #721c24;")
    
    def on_device_found(self, port, sn, addr):
        pass  # оброблено в find_new_device

    def activate_device(self):
        """Активує вибраний неактивний прилад"""
        sn = self.ui.combo_inactive_device.currentData()
        if not sn:
            QMessageBox.warning(self, "Помилка", "Не вибрано прилад для активації")
            return
        
        reply = QMessageBox.question(self, "Підтвердження", 
                                    f"Активувати прилад {sn}?",
                                    QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        
        self.db_manager.activate_device(sn)
        self.db_manager.reload_devices_map()
        
        self.db_manager.save_system_event(None, "device_activated", f"Прилад {sn} активовано")
        
        QMessageBox.information(self, "Успіх", f"Прилад {sn} активовано. Необхідно перезапустити програму.")
        self.ui.label_status.setText("Прилад активовано. Перезапустіть програму.")