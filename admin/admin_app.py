import os
import sys
import json
import requests

ADMIN_DIR = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
CLIENT_CONFIG_PATH = os.path.join(ADMIN_DIR, "admin_client_config.json")


def load_client_config():
    out = {"BACKEND_URL": "", "SECRET": ""}
    if not os.path.isfile(CLIENT_CONFIG_PATH):
        return out
    try:
        with open(CLIENT_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        out["BACKEND_URL"] = (data.get("BACKEND_URL") or "").strip().rstrip("/")
        out["SECRET"] = (data.get("SECRET") or "").strip()
    except Exception:
        pass
    return out


def save_client_config(cfg):
    if not cfg or not isinstance(cfg, dict):
        return False
    try:
        data = {
            "BACKEND_URL": (cfg.get("BACKEND_URL") or "").strip().rstrip("/"),
            "SECRET": (cfg.get("SECRET") or "").strip(),
        }
        with open(CLIENT_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def api_get(path, params=None):
    base = (load_client_config().get("BACKEND_URL") or "").rstrip("/")
    if not base:
        return 0, {"error": "BACKEND_URL не задан"}
    p = dict(params or {})
    p["admin_secret"] = load_client_config().get("SECRET") or ""
    try:
        r = requests.get(base + path, params=p, timeout=10)
        return r.status_code, r.json() if r.text else {}
    except Exception as e:
        return 0, {"error": str(e)}


def api_post(path, params=None, json_body=None):
    base = (load_client_config().get("BACKEND_URL") or "").rstrip("/")
    if not base:
        return 0, {"error": "BACKEND_URL не задан"}
    p = dict(params or {})
    p["admin_secret"] = load_client_config().get("SECRET") or ""
    try:
        r = requests.post(base + path, params=p, json=json_body, timeout=10)
        return r.status_code, r.json() if r.text else {}
    except Exception as e:
        return 0, {"error": str(e)}


from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QLineEdit, QTabWidget, QMessageBox, QDialog, QGroupBox, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QInputDialog,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

STYLE_MAIN = """
QWidget { background: #1a1a2e; color: #e0e0e0; }
QLabel { color: #e0e0e0; }
QLineEdit, QTextEdit {
    background: #16213e; color: #fff; border: 1px solid #0f3460;
    border-radius: 6px; padding: 6px; selection-background-color: #6366f1;
}
QPushButton {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #6366f1, stop:1 #4f46e5);
    color: white; border: none; border-radius: 8px; padding: 8px 16px;
}
QPushButton:hover { background: #818cf8; }
QPushButton:pressed { background: #4338ca; }
QPushButton:disabled { background: #475569; color: #94a3b8; }
QTabWidget::pane { border: 1px solid #334155; border-radius: 8px; background: #0f0f23; }
QTabBar::tab { background: #1e1b4b; color: #a5b4fc; padding: 8px 16px; margin-right: 2px; }
QTabBar::tab:selected { background: #6366f1; color: white; }
QGroupBox { font-weight: bold; color: #a5b4fc; border: 1px solid #334155; border-radius: 8px; margin-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }
QTableWidget { background: #16213e; gridline-color: #334155; }
QHeaderView::section { background: #1e1b4b; color: #a5b4fc; padding: 6px; }
"""


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Вход — CS2 Parser Admin")
        self.setMinimumWidth(400)
        self.setStyleSheet(STYLE_MAIN)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("URL сервера (backend):"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://your-server.com или http://127.0.0.1:8000")
        cfg = load_client_config()
        if cfg.get("BACKEND_URL"):
            self.url_edit.setText(cfg["BACKEND_URL"])
        layout.addWidget(self.url_edit)
        layout.addWidget(QLabel("Пароль (Admin или Moderator):"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Пароль")
        layout.addWidget(self.password_edit)
        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #f87171; font-size: 11px;")
        layout.addWidget(self.error_lbl)
        btn = QPushButton("Войти")
        btn.clicked.connect(self._on_ok)
        layout.addWidget(btn)

    def _on_ok(self):
        url = self.url_edit.text().strip().rstrip("/")
        pwd = self.password_edit.text().strip()
        if not url:
            self.error_lbl.setText("Введите URL сервера.")
            return
        if not pwd:
            self.error_lbl.setText("Введите пароль.")
            return
        try:
            r = requests.get(f"{url}/admin/keys", params={"admin_secret": pwd}, timeout=10)
            if r.status_code != 200:
                self.error_lbl.setText("Неверный пароль или нет доступа.")
                return
        except Exception as e:
            self.error_lbl.setText("Ошибка соединения: " + str(e))
            return
        if save_client_config({"BACKEND_URL": url, "SECRET": pwd}):
            self.done(QDialog.Accepted)
        else:
            self.error_lbl.setText("Не удалось сохранить настройки входа.")


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(STYLE_MAIN)
        layout = QVBoxLayout(self)
        self.no_rights_lbl = QLabel("")
        self.no_rights_lbl.setStyleSheet("color: #f87171;")
        self.no_rights_lbl.setWordWrap(True)
        layout.addWidget(self.no_rights_lbl)
        g = QGroupBox("Настройки сервера")
        fl = QFormLayout(g)
        self.telegram_token_edit = QLineEdit()
        self.telegram_token_edit.setPlaceholderText("Токен от @BotFather")
        fl.addRow("Токен Telegram-бота:", self.telegram_token_edit)
        self.download_url_edit = QLineEdit()
        self.download_url_edit.setPlaceholderText("Ссылка на скачивание софта")
        fl.addRow("DOWNLOAD_URL:", self.download_url_edit)
        self.payment_link_edit = QLineEdit()
        self.payment_link_edit.setPlaceholderText("Ссылка «Оплатить подписку»")
        fl.addRow("PAYMENT_LINK:", self.payment_link_edit)
        layout.addWidget(g)
        self.save_btn = QPushButton("Сохранить настройки")
        self.save_btn.clicked.connect(self._save)
        layout.addWidget(self.save_btn)
        layout.addStretch()

    def load(self):
        self.no_rights_lbl.setText("")
        code, data = api_get("/admin/config")
        if code == 403 or (code == 200 and data.get("detail") == "forbidden"):
            self.no_rights_lbl.setText("Недостаточно прав для изменения настроек сервера.")
            self.telegram_token_edit.setEnabled(False)
            self.download_url_edit.setEnabled(False)
            self.payment_link_edit.setEnabled(False)
            self.save_btn.setEnabled(False)
            return
        if code != 200:
            self.no_rights_lbl.setText("Ошибка загрузки: " + str(data.get("detail", data.get("error", code))))
            return
        self.telegram_token_edit.setEnabled(True)
        self.download_url_edit.setEnabled(True)
        self.payment_link_edit.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.telegram_token_edit.setText(data.get("TELEGRAM_BOT_TOKEN") or "")
        self.download_url_edit.setText(data.get("DOWNLOAD_URL") or "")
        self.payment_link_edit.setText(data.get("PAYMENT_LINK") or "")

    def _save(self):
        code, data = api_post("/admin/config/update", json_body={
            "TELEGRAM_BOT_TOKEN": self.telegram_token_edit.text().strip(),
            "DOWNLOAD_URL": self.download_url_edit.text().strip(),
            "PAYMENT_LINK": self.payment_link_edit.text().strip(),
        })
        if code == 200:
            QMessageBox.information(self, "Сохранено", "Настройки сервера сохранены. Перезапустите бота для применения.")
        else:
            QMessageBox.warning(self, "Ошибка", str(data.get("detail", data.get("error", code))))


class KeysTab(QWidget):
    def __init__(self, secret_getter, parent=None):
        super().__init__(parent)
        self._get_secret = secret_getter
        self.setStyleSheet(STYLE_MAIN)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        create_btn = QPushButton("Создать ключ")
        create_btn.clicked.connect(self._create_key)
        row.addWidget(create_btn)
        self.new_key_lbl = QLabel("")
        self.new_key_lbl.setWordWrap(True)
        self.new_key_lbl.setStyleSheet("color: #4ade80;")
        row.addWidget(self.new_key_lbl, 1)
        layout.addLayout(row)
        list_btn = QPushButton("Обновить список ключей")
        list_btn.clicked.connect(self._list_keys)
        layout.addWidget(list_btn)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Ключ", "Привязан", "До", "Telegram ID"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.table)
        act_row = QHBoxLayout()
        act_row.addWidget(QLabel("Выбранный ключ:"))
        copy_btn = QPushButton("Копировать")
        copy_btn.clicked.connect(self._copy_selected)
        act_row.addWidget(copy_btn)
        revoke_btn = QPushButton("Отозвать")
        revoke_btn.clicked.connect(self._revoke_selected)
        revoke_btn.setStyleSheet("QPushButton { background: #dc2626; } QPushButton:hover { background: #ef4444; }")
        act_row.addWidget(revoke_btn)
        grant_btn = QPushButton("Выдать пользователю")
        grant_btn.clicked.connect(self._grant_selected)
        act_row.addWidget(grant_btn)
        reset_btn = QPushButton("Сбросить привязку по железу")
        reset_btn.clicked.connect(self._reset_device_binding)
        act_row.addWidget(reset_btn)
        act_row.addStretch()
        layout.addLayout(act_row)
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(self.status_lbl)

    def _secret(self):
        return (self._get_secret() or "").strip()

    def _selected_key(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        return item.data(Qt.UserRole) or item.text().strip() or None

    def _create_key(self):
        if not self._secret():
            self.status_lbl.setText("Сначала войдите (URL и пароль).")
            return
        code, data = api_post("/admin/keys/create")
        if code == 200 and data.get("key"):
            key = data["key"]
            self.new_key_lbl.setText("Новый ключ: " + key)
            QApplication.clipboard().setText(key)
            self.status_lbl.setText("Ключ скопирован в буфер обмена.")
            self._list_keys()
        else:
            self.status_lbl.setText("Ошибка: " + str(data.get("detail", data.get("error", code))))

    def _list_keys(self):
        if not self._secret():
            self.status_lbl.setText("Сначала войдите.")
            return
        code, data = api_get("/admin/keys")
        if code != 200:
            self.status_lbl.setText("Ошибка: " + str(data.get("detail", data.get("error", code))))
            return
        keys = data.get("keys") or []
        self.table.setRowCount(len(keys))
        for i, k in enumerate(keys):
            key = (k.get("key") or "").strip()
            item0 = QTableWidgetItem(key)
            item0.setData(Qt.UserRole, key)
            self.table.setItem(i, 0, item0)
            self.table.setItem(i, 1, QTableWidgetItem("Да" if k.get("device_id") else "Нет"))
            exp = (k.get("expires_at") or "")[:10] or "—"
            self.table.setItem(i, 2, QTableWidgetItem(exp))
            self.table.setItem(i, 3, QTableWidgetItem(str(k.get("telegram_id") or "—")))
            self.table.setRowHeight(i, 28)
        self.status_lbl.setText("Ключей: " + str(len(keys)))

    def _copy_selected(self):
        key = self._selected_key()
        if not key:
            self.status_lbl.setText("Выберите строку в таблице.")
            return
        QApplication.clipboard().setText(key)
        self.status_lbl.setText("Ключ скопирован в буфер.")

    def _revoke_selected(self):
        key = self._selected_key()
        if not key:
            self.status_lbl.setText("Выберите ключ в таблице.")
            return
        if not self._secret():
            self.status_lbl.setText("Сначала войдите.")
            return
        code, data = api_post("/admin/keys/revoke", params={"key": key})
        if code == 200:
            self.status_lbl.setText("Ключ отозван.")
            self._list_keys()
        elif code == 404:
            self.status_lbl.setText("Ключ не найден.")
        else:
            self.status_lbl.setText("Ошибка: " + str(data.get("detail", data.get("error", code))))

    def _reset_device_binding(self):
        key = self._selected_key()
        if not key:
            self.status_lbl.setText("Выберите ключ в таблице.")
            return
        if not self._secret():
            self.status_lbl.setText("Сначала войдите.")
            return
        code, data = api_post("/admin/keys/reset_device", params={"key": key})
        if code == 200:
            self.status_lbl.setText("Привязка по железу сброшена.")
            self._list_keys()
        elif code == 404:
            self.status_lbl.setText("Ключ не найден.")
        else:
            self.status_lbl.setText("Ошибка: " + str(data.get("detail", data.get("error", code))))

    def _grant_selected(self):
        key = self._selected_key()
        if not key:
            self.status_lbl.setText("Выберите ключ в таблице.")
            return
        if not self._secret():
            self.status_lbl.setText("Сначала войдите.")
            return
        tid, ok = QInputDialog.getText(self, "Выдать ключ", "Telegram ID пользователя:", text="")
        if not ok or not (tid or "").strip():
            return
        try:
            telegram_id = int(tid.strip())
        except ValueError:
            self.status_lbl.setText("Введите числовой Telegram ID.")
            return

        self.status_lbl.setText("Отправка запроса на сервер (может занять до минуты)...")
        QApplication.processEvents()

        code, data = api_post("/admin/keys/grant_and_notify", params={"key": key, "telegram_id": telegram_id})

        if code == 200:
            if data.get("notified"):
                msg = "Успех! Ключ " + ("и файл софта " if data.get("sent_file") else "без файла ") + "отправлены пользователю."
                self.status_lbl.setText(msg)
            else:
                self.status_lbl.setText(f"Ключ привязан, но ТГ-уведомление не ушло: {data.get('detail')}")
        else:
            self.status_lbl.setText("Ошибка сервера: " + str(data.get("detail", data.get("error", code))))

        self._list_keys()


class SteamWebApiTab(QWidget):
    def __init__(self, secret_getter, parent=None):
        super().__init__(parent)
        self._get_secret = secret_getter
        self.setStyleSheet(STYLE_MAIN)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Пул ключей Steam Web API. Новые ключи добавляйте сюда."))
        add_row = QHBoxLayout()
        self.add_key_edit = QLineEdit()
        self.add_key_edit.setPlaceholderText("Вставьте ключ Steam Web API")
        add_row.addWidget(self.add_key_edit)
        add_btn = QPushButton("Добавить ключ в пул")
        add_btn.clicked.connect(self._add_key)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)
        stats_btn = QPushButton("Аналитика нагрузки API")
        stats_btn.clicked.connect(self._show_api_stats)
        layout.addWidget(stats_btn)
        refresh_btn = QPushButton("Обновить список")
        refresh_btn.clicked.connect(self._refresh_list)
        layout.addWidget(refresh_btn)
        self.pool_table = QTableWidget(0, 4)
        self.pool_table.setHorizontalHeaderLabels(["Ключ", "Активен", "Использований", "Последнее использование"])
        self.pool_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.pool_table)
        act_row = QHBoxLayout()
        act_row.addWidget(QLabel("С выбранным ключом:"))
        enable_btn = QPushButton("Включить")
        enable_btn.clicked.connect(lambda: self._set_active(True))
        act_row.addWidget(enable_btn)
        disable_btn = QPushButton("Выключить")
        disable_btn.clicked.connect(lambda: self._set_active(False))
        act_row.addWidget(disable_btn)
        del_btn = QPushButton("Удалить из пула")
        del_btn.clicked.connect(self._remove_key)
        act_row.addWidget(del_btn)
        act_row.addStretch()
        layout.addLayout(act_row)
        self.pool_status = QLabel("")
        self.pool_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(self.pool_status)

    def _secret(self):
        return (self._get_secret() or "").strip()

    def _selected_api_key(self):
        row = self.pool_table.currentRow()
        if row < 0:
            return None
        item = self.pool_table.item(row, 0)
        return (item.text() or "").strip() if item else None

    def _show_api_stats(self):
        if not self._secret():
            self.pool_status.setText("Сначала войдите.")
            return
        code, data = api_get("/admin/api_stats")
        if code != 200:
            QMessageBox.warning(self, "Аналитика", str(data.get("detail", data.get("error", code))))
            return
        total = data.get("total_requests", 0)
        peak_hour = data.get("peak_hour") or "—"
        peak_count = data.get("peak_count", 0)
        msg = f"За последние 24 часа:\n\nВсего запросов к Steam Web API: {total}\nПиковый час: {peak_hour}\nЗапросов в пик: {peak_count}"
        QMessageBox.information(self, "Аналитика нагрузки API", msg)

    def _add_key(self):
        key = self.add_key_edit.text().strip()
        if not key:
            self.pool_status.setText("Введите ключ.")
            return
        if not self._secret():
            self.pool_status.setText("Сначала войдите.")
            return
        code, data = api_post("/admin/steamwebapi_pool/add", params={"api_key": key})
        if code == 200:
            self.pool_status.setText("Ключ добавлен в пул.")
            self.add_key_edit.clear()
            self._refresh_list()
        else:
            self.pool_status.setText("Ошибка: " + str(data.get("detail", data.get("error", code))))

    def _remove_key(self):
        key = self._selected_api_key()
        if not key:
            self.pool_status.setText("Выберите ключ в таблице.")
            return
        if not self._secret():
            self.pool_status.setText("Сначала войдите.")
            return
        code, data = api_post("/admin/steamwebapi_pool/remove", params={"api_key": key})
        if code == 200:
            self.pool_status.setText("Ключ удалён из пула.")
            self._refresh_list()
        else:
            self.pool_status.setText("Ошибка: " + str(data.get("detail", data.get("error", code))))

    def _set_active(self, active: bool):
        key = self._selected_api_key()
        if not key:
            self.pool_status.setText("Выберите ключ в таблице.")
            return
        if not self._secret():
            self.pool_status.setText("Сначала войдите.")
            return
        code, data = api_post("/admin/steamwebapi_pool/set_active", params={"api_key": key, "active": active})
        if code == 200:
            self.pool_status.setText("Статус ключа обновлён.")
            self._refresh_list()
        else:
            self.pool_status.setText("Ошибка: " + str(data.get("detail", data.get("error", code))))

    def _refresh_list(self):
        if not self._secret():
            self.pool_status.setText("Сначала войдите.")
            return
        code, data = api_get("/admin/steamwebapi_pool")
        if code != 200:
            self.pool_status.setText("Ошибка: " + str(data.get("detail", data.get("error", code))))
            return
        keys = data.get("keys") or []
        self.pool_table.setRowCount(len(keys))
        for i, k in enumerate(keys):
            full_key = (k.get("api_key") or "").strip()
            if not full_key:
                full_key = k.get("api_key_masked") or "***"
            self.pool_table.setItem(i, 0, QTableWidgetItem(full_key))
            self.pool_table.setItem(i, 1, QTableWidgetItem("Да" if k.get("is_active") else "Нет"))
            self.pool_table.setItem(i, 2, QTableWidgetItem(str(k.get("usage_count") or 0)))
            self.pool_table.setItem(i, 3, QTableWidgetItem((k.get("last_used_at") or "—")[:19]))
        self.pool_status.setText("В пуле ключей: " + str(len(keys)))


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CS2 Parser — Админ-пульт")
        self.setMinimumSize(640, 520)
        self.setStyleSheet(STYLE_MAIN)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.settings_tab = SettingsTab()
        self.tabs.addTab(self.settings_tab, "Настройки")
        self.keys_tab = KeysTab(self._get_secret)
        self.tabs.addTab(self.keys_tab, "Лицензии")
        self.steamwebapi_tab = SteamWebApiTab(self._get_secret)
        self.tabs.addTab(self.steamwebapi_tab, "Steam Web API")
        layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _get_secret(self):
        return load_client_config().get("SECRET") or ""

    def _on_tab_changed(self, index):
        if self.tabs.widget(index) == self.settings_tab:
            self.settings_tab.load()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    login = LoginDialog()
    if login.exec_() != QDialog.Accepted:
        sys.exit(0)
    w = MainWindow()
    w.settings_tab.load()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
