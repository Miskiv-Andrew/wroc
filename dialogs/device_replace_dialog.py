


import os
import json
import hashlib
from PySide6.QtWidgets import QDialog, QMessageBox, QLabel, QGroupBox
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile

from devices.address_changer import AddressChanger
from database.db_manager import DatabaseManager, write_config_and_hash, atomic_write_bytes
from translations import TRANSLATIONS

class DeviceReplaceDialog(QDialog):

    def __init__(self, db_manager, active_devices, inactive_devices, parent=None, app=None):
        super().__init__(parent)
        
        self.db_manager = db_manager
        self.active_devices = active_devices      # для замены
        self.inactive_devices = inactive_devices  # для активации
        self.app = app                            # ссылка на App для отправки в Bridge
        self.new_device_info = None               # (port, serial_number, address)
        self.address_changer = AddressChanger(db_manager, self.tr)

        
        # Загружаем UI
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
        self.load_active_devices()      # для замены
        self.load_inactive_devices()    # для активации
        
        self.address_changer.status.connect(self.on_status)
        self.address_changer.error.connect(self.on_error)
        self.address_changer.found.connect(self.on_device_found)

        self.retranslate_ui()

    def tr(self, key):
        if self.app is not None:
            return self.app.tr(key)
        return TRANSLATIONS["uk"].get(key, key)

    def retranslate_ui(self):
        self.setWindowTitle(self.tr("replace_window_title"))
        self.ui.setWindowTitle(self.tr("replace_window_title"))

        labels = {
            "label_title": "replace_heading",
            "label_old_sn": "replace_old_device",
            "label_old_info": "location",
            "label_new_sn": "new_sn",
            "label_inactive_device": "inactive_device",
        }
        for widget_name, translation_key in labels.items():
            label = self.findChild(QLabel, widget_name)
            if label is None:
                raise RuntimeError(f"Missing QLabel: {widget_name}")
            label.setText(self.tr(translation_key))

        groups = {
            "groupBox_old_device": "replace_group",
            "groupBox_new_device": "replace_new_device",
            "groupBox_activate_device": "activate_group",
        }
        for widget_name, translation_key in groups.items():
            group = self.findChild(QGroupBox, widget_name)
            if group is None:
                raise RuntimeError(f"Missing QGroupBox: {widget_name}")
            group.setTitle(self.tr(translation_key))

        self.ui.btn_find_new.setText(self.tr("find_new_device"))
        self.ui.btn_activate.setText(self.tr("activate_device"))
        self.ui.btn_replace.setText(self.tr("execute_replacement"))
        self.ui.btn_cancel.setText(self.tr("cancel"))
    
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
        self.ui.label_status.setText(self.tr("replace_searching"))
        self.ui.label_status.setStyleSheet("background-color: #fff3cd; color: #856404;")
        
        # Запускаємо пошук (синхронно, але з обробкою сигналів)
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        
        port, sn, addr = self.address_changer.find_new_device()
        
        if sn:
            self.new_device_info = (port, sn, addr)
            self.ui.edit_new_sn.setText(sn)
            self.ui.btn_replace.setEnabled(True)
            self.ui.label_status.setText(self.tr("replace_searching_found"))
            self.ui.label_status.setStyleSheet("background-color: #d4edda; color: #155724;")
        else:
            self.new_device_info = None
            self.ui.btn_replace.setEnabled(False)
            self.ui.label_status.setText(self.tr("replace_searching_not_found"))
            self.ui.label_status.setStyleSheet("background-color: #f8d7da; color: #721c24;")
        
        self.ui.btn_find_new.setEnabled(True)

  

    def replace_device(self):
        """
        Выполняет замену неисправного прибора.

        Процедура используется как для детекторов цистерн ZB,
        так и для настенных детекторов CZ.

        ВАЖНО:
        Специальная команда replacement в Bridge предназначена
        только для детекторов цистерн ZB.

        Для настенных детекторов CZ новый серийный номер
        передаётся в Bridge обычным CZ-пакетом после перезапуска
        программы и возобновления работы системы.
        """

        # ============================================================
        # 1. ПОЛУЧАЕМ СТАРЫЙ ПРИБОР
        # ============================================================

        old_sn = self.ui.combo_old_device.currentData()

        if not old_sn:
            QMessageBox.warning(
                self,
                self.tr("error"),
                self.tr("replace_old_not_chosen")
            )
            return

        # ============================================================
        # 2. НАХОДИМ ДАННЫЕ СТАРОГО ПРИБОРА
        # ============================================================

        old_device = None

        for dev in self.active_devices:
            if dev["serial_number"] == old_sn:
                old_device = dev
                break

        if not old_device:
            QMessageBox.warning(
                self,
                self.tr("error"),
                self.tr("replace_old_not_found")
            )
            return

        # ============================================================
        # 3. ПРОВЕРЯЕМ НОВЫЙ ПРИБОР
        # ============================================================

        if not self.new_device_info:
            QMessageBox.warning(
                self,
                self.tr("error"),
                self.tr("replace_not_found")
            )
            return

        port, new_sn, old_addr = self.new_device_info

        # ------------------------------------------------------------
        # Новый и заменяемый приборы не могут иметь одинаковый SN.
        # ------------------------------------------------------------

        if old_sn == new_sn:
            QMessageBox.warning(
                self,
                self.tr("error"),
                (
                    self.tr("replace_identical_sn")
                )
            )

            self.ui.label_status.setText(
                self.tr("replace_identical_error")
            )

            self.ui.btn_replace.setEnabled(True)

            return

        # ============================================================
        # 4. ПОЛУЧАЕМ РАБОЧИЙ АДРЕС СТАРОГО ПРИБОРА
        # ============================================================

        target_address = self._get_address_from_config(
            old_sn
        )

        if target_address is None:
            QMessageBox.warning(
                self,
                self.tr("error"),
                (
                    # f"Не удалось найти адрес для "
                    # f"{old_sn} в config.txt"
                    f"{self.tr("replace_not_found_config_1")} {old_sn} {self.tr("replace_not_found_config_2")}"
                )
            )
            return

        # ============================================================
        # 5. ИЗМЕНЯЕМ АДРЕС НОВОГО ПРИБОРА
        # ============================================================

        self.ui.btn_replace.setEnabled(False)

        self.ui.label_status.setText(
            self.tr("replace_changing")
        )

        self.ui.label_status.setStyleSheet(
            "background-color: #fff3cd; color: #856404;"
        )

        QMessageBox.information(
            self,
            self.tr("warning"),
            (
                f"{self.tr("replace_pending")} {new_sn} ,"
                f"{old_addr} - {target_address}"
            )
        )

        success = self.address_changer.change_address(
            port,
            old_addr,
            target_address,
            new_sn
        )

        if not success:
            self.ui.label_status.setText(
                self.tr("replace_error")
            )

            self.ui.label_status.setStyleSheet(
                "background-color: #f8d7da; color: #721c24;"
            )

            self.ui.btn_replace.setEnabled(True)

            return

        # ============================================================
        # 6. ОБНОВЛЯЕМ КОНФИГУРАЦИЮ И БД
        # ============================================================

        try:

            self._update_config_files(
                old_sn,
                new_sn,
                old_device
            )

            self._update_database(
                old_sn,
                new_sn,
                old_device
            )

            # ========================================================
            # 7. УВЕДОМЛЯЕМ BRIDGE О ЗАМЕНЕ
            # ========================================================
            #
            # Специальная команда replacement существует ТОЛЬКО
            # для детекторов цистерн ZB.
            #
            # Для настенного CZ вызывать её нельзя:
            #
            #     position_number CZ1
            #
            # иначе был бы интерпретирован Bridge как номер ZB1.
            #
            # Новый SN настенного детектора после перезапуска
            # передаётся обычным CZ-пакетом.
            # ========================================================

            if (
                self.app is not None
                and old_device["location_type"] == "cistern"
            ):
                self.app._send_replacement_to_bridge(
                    old_device["position_number"],
                    int(new_sn)
                )

            # ========================================================
            # 8. ЗАМЕНА ЗАВЕРШЕНА
            # ========================================================

            self.ui.label_status.setText(
                self.tr("replace_success")
            )

            self.ui.label_status.setStyleSheet(
                "background-color: #d4edda; color: #155724;"
            )

            # Повторная замена в этом экземпляре диалога запрещается.
            self.ui.btn_replace.setEnabled(False)

            QMessageBox.information(
                self,
                self.tr("replace_success_title"),
                (
                    # f"Замена прибора выполнена успешно.\n"
                    # f"Старый SN: {old_sn}\n"
                    # f"Новый SN: {new_sn}\n\n"
                    # f"Необходимо перезапустить программу."
                    f"{self.tr("replace_success_1")}\n"
                    f"{self.tr("replace_success_2")} {old_sn}\n"
                    f"{self.tr("replace_success_3")} {new_sn}\n\n"
                    f"{self.tr("replace_success_4")}"
                )
            )

        except Exception as e:

            self.ui.label_status.setText(
                #f"Ошибка при обновлении конфигурации: {e}"
                f"{self.tr("replace_error_config")} {e}"
            )

            self.ui.label_status.setStyleSheet(
                "background-color: #f8d7da; color: #721c24;"
            )

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
        """
        Оновлює конфігураційні файли при заміні приладу:
            - config.txt (заміна SN)
            - hash.txt (перерахунок SHA-256)
            - cistern.json (якщо цистерна — оновлює структуру з full, isotopes, group)
        """
        config_path = "config/config.txt"
        
        # Читаємо config.txt
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        # Замінюємо старий SN на новий у відповідному рядку
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
        
        # Записуємо оновлений config.txt
        # with open(config_path, "w", encoding="utf-8") as f:
        #     f.writelines(lines)
        
        # # Перераховуємо hash.txt
        # with open(config_path, "rb") as f:
        #     data = f.read()
        # sha256_hash = hashlib.sha256(data).hexdigest()
        # with open("config/hash.txt", "w", encoding="utf-8") as f:
        #     f.write(sha256_hash)
        
        # Записуємо config.txt і hash.txt атомарно
        config_bytes = "".join(lines).encode("utf-8")
        write_config_and_hash(config_bytes)
        
        # ------------------------------------------------------------
        # Якщо замінюється цистерна — оновлюємо cistern.json
        # ------------------------------------------------------------
        if old_device['location_type'] == 'cistern':
            cistern_path = "config/cistern.json"
            
            # Завантажуємо поточний вміст cistern.json (якщо файл існує)
            if os.path.exists(cistern_path):
                with open(cistern_path, "r", encoding="utf-8") as f:
                    cistern_data = json.load(f)
            else:
                cistern_data = {}
            
            pos = str(old_device['position_number'])
            
            # Якщо позиція вже існує — залишаємо її значення (full, isotopes, group)
            # Якщо позиція відсутня — створюємо дефолтну структуру
            if pos not in cistern_data:
                cistern_data[pos] = {
                    "full": False,
                    "isotopes": [],
                    "group": "A"
                }
            # Якщо позиція є, але запис зберігає старий формат (просто boolean),
            # конвертуємо його в нову структуру
            elif isinstance(cistern_data[pos], bool):
                old_full = cistern_data[pos]
                cistern_data[pos] = {
                    "full": old_full,
                    "isotopes": [],
                    "group": "A"
                }
            # Якщо запис вже є словником — нічого не змінюємо
            
            # Записуємо оновлений cistern.json
            # with open(cistern_path, "w", encoding="utf-8") as f:
            #     json.dump(cistern_data, f, ensure_ascii=False, indent=4)  
            atomic_write_bytes(
                cistern_path,
                json.dumps(cistern_data, ensure_ascii=False, indent=4).encode("utf-8")
            )



    def _update_database(self, old_sn, new_sn, old_device):
        """
        Обновляет БД при замене прибора.

        Последовательность:

            1. старый прибор становится неактивным;

            2. новый прибор:
                - если уже существует в БД, повторно активируется
                И привязывается к позиции заменяемого прибора;
                - если раньше в БД не существовал, создаётся;

            3. изменения фиксируются в БД;

            4. перечитывается кеш активных приборов;

            5. событие device_replaced связывается
            с новым прибором.

        ВАЖНО:

        Старые записи измерений не изменяются.
        Старый прибор остаётся в таблице devices с is_active = 0.

        Если новый прибор ранее уже использовался в системе,
        его старая позиция не должна сохраняться: теперь он физически
        установлен вместо old_device и поэтому должен получить
        location_type и position_number заменяемого прибора.
        """

        # ============================================================
        # 1. ПОЛУЧАЕМ СОЕДИНЕНИЕ С БД
        # ============================================================

        conn = self.db_manager._get_connection()
        cursor = conn.cursor()

        try:

            # ========================================================
            # 2. ДЕАКТИВИРУЕМ СТАРЫЙ ПРИБОР
            # ========================================================

            cursor.execute(
                """
                UPDATE devices
                SET is_active = 0
                WHERE serial_number = ?
                """,
                (old_sn,)
            )

            # ========================================================
            # 3. ПРОВЕРЯЕМ, СУЩЕСТВУЕТ ЛИ НОВЫЙ SN В БД
            # ========================================================

            if self.db_manager.device_exists(new_sn):

                # ----------------------------------------------------
                # Прибор уже известен системе.
                #
                # Например:
                #   - ранее использовался на другой позиции;
                #   - был снят;
                #   - был отремонтирован;
                #   - теперь устанавливается вместо неисправного.
                #
                # Поэтому недостаточно только is_active = 1.
                #
                # Его логическое расположение в БД обязательно
                # должно соответствовать позиции прибора,
                # который сейчас заменяется.
                # ----------------------------------------------------

                cursor.execute(
                    """
                    UPDATE devices
                    SET
                        device_type = ?,
                        location_type = ?,
                        position_number = ?,
                        is_active = 1
                    WHERE serial_number = ?
                    """,
                    (
                        "БДБГ-09S-23",
                        old_device["location_type"],
                        old_device["position_number"],
                        new_sn
                    )
                )

            else:

                # ----------------------------------------------------
                # Новый SN раньше в системе не встречался.
                # Создаём новую запись сразу на позиции
                # заменяемого прибора.
                # ----------------------------------------------------

                cursor.execute(
                    """
                    INSERT INTO devices
                    (
                        serial_number,
                        device_type,
                        location_type,
                        position_number,
                        is_active
                    )
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (
                        new_sn,
                        "БДБГ-09S-23",
                        old_device["location_type"],
                        old_device["position_number"]
                    )
                )

            # ========================================================
            # 4. ФИКСИРУЕМ ИЗМЕНЕНИЯ ПРИБОРОВ
            # ========================================================

            conn.commit()

        except Exception:

            # ========================================================
            # 5. ПРИ ОШИБКЕ ОТКАТЫВАЕМ ИЗМЕНЕНИЯ БД
            # ========================================================

            try:
                conn.rollback()
            except Exception:
                pass

            raise

        # ============================================================
        # 6. ОБНОВЛЯЕМ КЕШ АКТИВНЫХ ПРИБОРОВ
        # ============================================================

        self.db_manager._load_devices_map()

        # ============================================================
        # 7. ПОЛУЧАЕМ ID НОВОГО ПРИБОРА
        # ============================================================

        new_device_id = self.db_manager.get_device_id(
            new_sn
        )

        # ============================================================
        # 8. СОХРАНЯЕМ СОБЫТИЕ ЗАМЕНЫ
        # ============================================================
        #
        # Событие относится к новому установленному прибору.
        #
        # Старый и новый SN дополнительно сохраняются
        # в текстовом описании события.
        # ============================================================

        self.db_manager.save_system_event(
            new_device_id,
            "device_replaced",
            (
                f"{self.tr("replace_title")} "
                f"{old_sn} -> {new_sn}, "
                f"{self.tr("position")} {old_device['position_number']}"
            )
        )


    
    def on_status(self, message):
        self.ui.label_status.setText(message)
        self.ui.label_status.setStyleSheet("")
    
    def on_error(self, message):
        self.ui.label_status.setText(message)
        self.ui.label_status.setStyleSheet("background-color: #f8d7da; color: #721c24;")
    
    def on_device_found(self, port, sn, addr):
        pass  # оброблено в find_new_device

    # def activate_device(self):
    #     """Активує вибраний неактивний прилад"""
    #     sn = self.ui.combo_inactive_device.currentData()
    #     if not sn:
    #         QMessageBox.warning(self, self.tr("error"), self.tr("activate_choose"))
    #         return
        
    #     # reply = QMessageBox.question(self, self.tr("confirmation"), 
    #     #                             f"{self.tr("activate_device")} {sn}?",
    #     #                             QMessageBox.Yes | QMessageBox.No)
    #     msg_box = QMessageBox(self)
    #     msg_box.setWindowTitle(self.tr("confirmation"))
    #     msg_box.setText(f"{self.tr('activate_device')} {sn}?")
    #     msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

    #     msg_box.button(QMessageBox.Yes).setText(self.tr("yes"))
    #     msg_box.button(QMessageBox.No).setText(self.tr("no"))

    #     reply = msg_box.exec()
        
    #     if reply != QMessageBox.Yes:
    #         return
        
    #     self.db_manager.activate_device(sn)
    #     self.db_manager.reload_devices_map()
        
    #     self.db_manager.save_system_event(None, "device_activated", f"{self.tr("device_paed")} {sn} {self.tr("activated")}")
        
    #     QMessageBox.information(self, self.tr("replace_success_title"), f"{self.tr("device_paed")} {sn} {self.tr("activated")}. {self.tr("need_reboot")}")
    #     self.ui.label_status.setText(self.tr("activate_success"))
    
    def activate_device(self):
        sn = self.ui.combo_inactive_device.currentData()
        if not sn:
            QMessageBox.warning(self, self.tr("error"), self.tr("activate_choose"))
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.tr("confirmation"))
        msg_box.setText(f"{self.tr('activate_device')} {sn}?")
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

        msg_box.button(QMessageBox.Yes).setText(self.tr("yes"))
        msg_box.button(QMessageBox.No).setText(self.tr("no"))

        reply = msg_box.exec()
        
        if reply != QMessageBox.Yes:
            return

        try:
            # This manager method should update config.txt, hash.txt,
            # and the database, then refresh its active-device map.
            self.db_manager.activate_device(sn)

            self.db_manager.save_system_event(
                None,
                "device_activated",
                f"{self.tr('device_paed')} {sn} {self.tr('activated')}"
            )
        except Exception as e:
            QMessageBox.warning(self, self.tr("error"), str(e))
            return

        QMessageBox.information(
            self,
            self.tr("replace_success_title"),
            f"{self.tr('device_paed')} {sn} {self.tr('activated')}. "
            f"{self.tr('need_reboot')}"
        )
        self.ui.label_status.setText(self.tr("activate_success"))