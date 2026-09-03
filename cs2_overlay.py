import sys, os, re, json, time, threading, traceback, subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QFrame, QScrollArea, QFileDialog, QMessageBox,
    QInputDialog, QMenu, QAction, QSizePolicy, QDialog, QLineEdit,
    QDialogButtonBox, QPlainTextEdit, QCheckBox, QStyle, QProgressDialog,
)
from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal, QThread, QPoint, QUrl, QAbstractNativeEventFilter
from PyQt5.QtGui import QPalette, QColor, QFont, QDesktopServices, QCursor, QKeySequence, QPixmap

from core_security import get_device_id, secure_api_call

APP_VERSION = 1.0

if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.normpath(os.path.dirname(sys.executable))
    _data_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CS2_Parser")
    try:
        os.makedirs(_data_dir, exist_ok=True)
    except Exception:
        pass  
    CONFIG_PATH = os.path.join(_data_dir, "config.json")
    STARTUP_ERROR_LOG = os.path.join(_data_dir, "startup_error.txt")
    PARSER_LOG = os.path.join(_data_dir, "parser.log")
else:
    SCRIPT_DIR = os.path.normpath(os.path.dirname(os.path.abspath(os.path.realpath(__file__))))
    CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
    STARTUP_ERROR_LOG = os.path.join(SCRIPT_DIR, "startup_error.txt")
    PARSER_LOG = os.path.join(SCRIPT_DIR, "parser.log")

_HOTKEY_CB = None
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
    WM_HOTKEY = 0x0312
    VK_F1, VK_F12 = 0x70, 0x7B
    VK_A, VK_Z = 0x41, 0x5A

    def _parse_hotkey(s):
        s = (s or "").strip()
        if not s: return None, None
        mod = 0
        key = None
        parts = [p.strip() for p in s.replace("+", " ").split()]
        for p in parts:
            low = p.lower()
            if low == "ctrl": mod |= MOD_CONTROL
            elif low == "alt": mod |= MOD_ALT
            elif low == "shift": mod |= MOD_SHIFT
            elif low == "win": mod |= MOD_WIN
            elif len(p) == 1 and p.isalpha(): key = ord(p.upper())
            elif len(p) == 1 and p.isdigit(): key = ord(p)
            elif p.upper().startswith("F") and len(p) <= 4:
                try:
                    n = int(p[1:])
                    if 1 <= n <= 12: key = VK_F1 + (n - 1)
                except ValueError: pass
        if key is None: return None, None
        return mod, key

    def _register_hotkey_win(hwnd, hotkey_id, mod, vk):
        return user32.RegisterHotKey(int(hwnd), hotkey_id, mod, vk) != 0

    def _unregister_hotkey_win(hwnd, hotkey_id):
        user32.UnregisterHotKey(int(hwnd), hotkey_id)

    HOTKEY_ID = 0x0000B00B 

    class _HotkeyNativeFilter(QAbstractNativeEventFilter):
        def nativeEventFilter(self, eventType, message):
            if eventType not in (b"windows_generic_MSG", b"windows_dispatcher_MSG") or not _HOTKEY_CB:
                return (False, 0)
            try:
                class MSG(ctypes.Structure):
                    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                                ("time", wintypes.DWORD), ("pt", wintypes.POINT)]
                try:
                    addr = int(message)
                except:
                    addr = message
                msg = ctypes.cast(addr, ctypes.POINTER(MSG)).contents
                if msg.message == WM_HOTKEY:
                    _HOTKEY_CB()
                    return (True, 0)
            except Exception:
                pass
            return (False, 0)
else:
    def _parse_hotkey(s): return None, None
    def _register_hotkey_win(h, i, m, v): return False
    def _unregister_hotkey_win(h, i): pass
    _HotkeyNativeFilter = None
    HOTKEY_ID = 0

def _parser_log(msg, **kwargs):
    try:
        parts = [time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()), msg]
        if kwargs:
            parts.append(" | " + " ".join(f"{k}={kwargs[k]!r}" for k in sorted(kwargs)))
        with open(PARSER_LOG, "a", encoding="utf-8") as f:
            f.write(" ".join(parts) + "\n")
    except Exception: pass

DEFAULTS = {
    "steamwebapi_key": "", "faceit_api_key": "", "steam_api_key": "",
    "min_value": 150, "gsi_port": 3000, "steam_path": "", "cs2_path": "",
    "license_server_url": "http://127.0.0.1:8000", "license_key": "",
    "bring_on_top_hotkey": "Ctrl+Y",
}

def load_cfg():
    out = dict(DEFAULTS)
    if not os.path.exists(CONFIG_PATH) and getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        try:
            embedded = os.path.join(sys._MEIPASS, "default_config.json")
            if os.path.isfile(embedded):
                with open(embedded, "r", encoding="utf-8") as f:
                    c = json.load(f)
                if isinstance(c, dict):
                    with open(CONFIG_PATH, "w", encoding="utf-8") as w:
                        json.dump(c, w, indent=2, ensure_ascii=False)
        except Exception:
            pass
    if not os.path.exists(CONFIG_PATH):
        return out
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            c = json.load(f)
        if isinstance(c, dict):
            for k in DEFAULTS:
                out[k] = c.get(k, DEFAULTS[k])
            for k in c:
                if k not in DEFAULTS:
                    out[k] = c[k]
        return out
    except Exception:
        return out

def _cfg_expires_ddmm(expires_at_str: str) -> str:
    s = (expires_at_str or "").strip()[:10]
    if len(s) < 10: return ""
    try:
        parts = s.split("-")
        if len(parts) == 3: return f"{int(parts[2]):02d}.{int(parts[1]):02d}"
    except: pass
    return ""

def save_cfg(c):
    if not c or not isinstance(c, dict): return
    try:
        to_save = dict(DEFAULTS)
        to_save.update(c)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(to_save, f, indent=2, ensure_ascii=False)
            f.flush()
    except Exception: pass

CFG = load_cfg()


def _need_first_run_wizard():
    if not getattr(sys, "frozen", False):
        return False
    key = (CFG.get("license_key") or "").strip()
    path = (CFG.get("cs2_path") or "").strip()
    return not key or not path


def run_first_run_wizard_if_needed():
    if not _need_first_run_wizard():
        return
    if not (CFG.get("license_key") or "").strip():
        dlg = ActivationDialog()
        dlg.exec_()
        if not (CFG.get("license_key") or "").strip():
            return

    if not (CFG.get("cs2_path") or "").strip():
        parent = QApplication.activeWindow()
        info_dlg = QDialog(parent)
        info_dlg.setStyleSheet(
            "QDialog{background:#1a1a2e; color:white;} "
            "QLabel{color:white;} "
            "QPushButton{background:#6366f1; color:white; padding:8px; border-radius:6px; font-weight:bold;}"
        )
        info_dlg.setWindowTitle("Папка с игрой CS2")
        info_dlg.setWindowFlags(info_dlg.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        layout = QVBoxLayout(info_dlg)
        text = QLabel("Для корректной работы софта укажите папку с игрой CS2 (где лежит cs2.exe)")
        text.setWordWrap(True)
        layout.addWidget(text)
        btn_row = QHBoxLayout()
        open_btn = QPushButton("Открыть проводник")
        btn_row.addWidget(open_btn)
        skip_btn = QPushButton("Позже")
        btn_row.addWidget(skip_btn)
        layout.addLayout(btn_row)

        chosen_folder = {"path": None}

        def _on_open():
            folder = QFileDialog.getExistingDirectory(
                info_dlg,
                "Укажите папку с игрой CS2 (папка, где лежит cs2.exe)",
                CFG.get("cs2_path", "") or "",
                QFileDialog.ShowDirsOnly,
            )
            if folder and os.path.isdir(folder):
                chosen_folder["path"] = os.path.normpath(folder)
                info_dlg.accept()

        def _on_skip():
            info_dlg.reject()

        open_btn.clicked.connect(_on_open)
        skip_btn.clicked.connect(_on_skip)

        info_dlg.exec_()

        if chosen_folder["path"]:
            CFG["cs2_path"] = chosen_folder["path"]
            save_cfg(CFG)


TELEGRAM_FALLBACK_CHANNEL_URL = "https://t.me/username"

def _fetch_backend_url_from_telegram() -> str | None:
    try:
        r = requests.get(TELEGRAM_FALLBACK_CHANNEL_URL, timeout=8)
        if r.status_code != 200 or not r.text: return None
        
        idx = r.text.find("BACKEND_URL=")
        if idx < 0: return None
        
        snippet = r.text[idx:idx+150]
        
        match = re.search(r'(https?://[0-9a-zA-Z.:\-]+)', snippet)
        if match:
            return match.group(1).rstrip("/")
        return None
    except Exception: return None

def call_backend(relative_path: str, method: str = "GET", json=None, params=None, timeout=15, retry_after_fallback: bool = True):
    url_base = (CFG.get("license_server_url") or "").strip().rstrip("/")
    
    if not url_base and retry_after_fallback:
        fetched_url = _fetch_backend_url_from_telegram()
        if fetched_url:
            url_base = fetched_url
            CFG["license_server_url"] = url_base
            save_cfg(CFG) 
            
    if not url_base: 
        raise requests.RequestException("URL сервера не найден даже в резервном канале")
        
    full_url = f"{url_base}/{relative_path.lstrip('/')}"
    
    try:
        return secure_api_call(full_url, method=method, json_data=json, params=params, timeout=timeout)
    except (requests.ConnectionError, requests.Timeout, requests.RequestException):
        if not retry_after_fallback: raise
        new_url = _fetch_backend_url_from_telegram()
        if not new_url or new_url == url_base: raise
        
        CFG["license_server_url"] = new_url
        save_cfg(CFG)
        
        full_url_retry = f"{new_url}/{relative_path.lstrip('/')}"
        return secure_api_call(full_url_retry, method=method, json_data=json, params=params, timeout=timeout)
def check_parsed_remote(steam_id: str) -> bool:
    if not (CFG.get("license_server_url") or "").strip(): return False
    try:
        r = call_backend("check_parsed", method="GET", params={"steam_id": steam_id}, timeout=5)
        if r.status_code == 200: return r.json().get("parsed", False)
    except Exception: pass
    return False

_CHECK_PARSED_CACHE: dict[str, tuple[bool, float | None, str | None]] = {}


def check_parsed_remote_full(steam_id: str) -> tuple[bool, float | None, str | None]:
    sid = str(steam_id or "").strip()
    if not sid:
        return False, None, None
    cached = _CHECK_PARSED_CACHE.get(sid)
    if cached is not None:
        return cached
    if not (CFG.get("license_server_url") or "").strip():
        return False, None, None
    try:
        r = call_backend("check_parsed", method="GET", params={"steam_id": sid}, timeout=5)
        if r.status_code != 200:
            return False, None, None
        data = r.json() or {}
        if not data.get("parsed"):
            res = (False, None, None)
        else:
            res = (True, data.get("last_value"), data.get("name") or None)
        _CHECK_PARSED_CACHE[sid] = res
        return res
    except Exception:
        return False, None, None

def check_parsed_batch_remote(steam_ids: list[str]) -> dict:
    if not (CFG.get("license_server_url") or "").strip() or not steam_ids:
        return {}
    ids = [str(s).strip() for s in steam_ids if s and str(s).strip()]
    if not ids:
        return {}
    key = (CFG.get("license_key") or "").strip()
    payload = {"steam_ids": ids}
    if key:
        payload["key"] = key
        payload["device_id"] = get_device_id()
    try:
        r = call_backend("check_parsed_batch", method="POST", json=payload, timeout=10)
        if r.status_code != 200:
            return {}
        return r.json() if r.text else {}
    except Exception:
        return {}


def report_parsed_remote(steam_id: str, last_value: float | None, name: str | None, country_code: str | None) -> None:
    key = (CFG.get("license_key") or "").strip()
    if not key or not (CFG.get("license_server_url") or "").strip(): return
    try:
        call_backend("report_parsed", method="POST", json={"key": key, "device_id": get_device_id(), "steam_id": steam_id, "last_value": last_value, "name": name, "country_code": country_code}, timeout=5)
    except Exception: pass

def report_parsed_batch_remote(players_list: list):
    key = (CFG.get("license_key") or "").strip()
    if not key or not (CFG.get("license_server_url") or "").strip() or not players_list: return
    try:
        call_backend("report_parsed_batch", method="POST", json={"key": key, "device_id": get_device_id(), "players": players_list}, timeout=10)
    except Exception: pass

def validate_license(key: str, device_id: str) -> tuple[bool, str]:
    url = (CFG.get("license_server_url") or "").strip().rstrip("/")
    if not url: return False, "Не задан URL сервера лицензий"
    key = key.strip()
    if not key: return False, "Введите ключ"
    try:
        r = call_backend("validate", method="POST", json={"key": key, "device_id": device_id}, timeout=15)
        if r.status_code == 200:
            data = r.json() if r.text else {}
            exp = (data.get("expires_at") or "").strip()
            if exp:
                CFG["expires_at"] = exp
                save_cfg(CFG)
            return True, ""
        msg = (r.json() if r.text else {}).get("detail", str(r.status_code))
        if r.status_code == 403 and "already_used" in str(msg).lower(): return False, "Ключ используется на другом ПК."
        if r.status_code == 403 and "expired" in str(msg).lower(): return False, "Подписка истекла."
        return False, msg or "Ошибка лицензии"
    except Exception as e:
        return False, f"Нет связи с сервером: {e}"

class ActivationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("Активация")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        self.key_edit = QLineEdit()
        self.key_edit.setText((CFG.get("license_key") or "").strip())
        self.key_edit.setMinimumHeight(36)
        layout.addWidget(self.key_edit)
        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color:#ff6666;")
        layout.addWidget(self.error_lbl)
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("Активировать")
        ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)
        self.setStyleSheet("QDialog{background:#1a1a2e;} QLabel{color:#e0e0e0;} QLineEdit{background:#16213e;color:#fff;border:1px solid #0f3460;padding:6px;} QPushButton{background:#e94560;color:white;border-radius:6px;padding:8px;}")

    def _on_ok(self):
        key = self.key_edit.text().strip()
        ok, err = validate_license(key, get_device_id())
        if ok:
            CFG["license_key"] = key
            save_cfg(CFG)
            self.accept()
        else:
            self.error_lbl.setText(err or "Неверный ключ")

def find_cs2_from_steam(steam_root):
    if not steam_root or not os.path.isdir(steam_root): return ""
    sp = os.path.normpath(steam_root)
    cs2 = os.path.join(sp, "steamapps", "common", "Counter-Strike Global Offensive")
    if os.path.isdir(cs2): return cs2
    vdf = os.path.join(sp, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(vdf):
        try:
            with open(vdf, "r", encoding="utf-8") as f:
                for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                    cs2 = os.path.join(m.group(1), "steamapps", "common", "Counter-Strike Global Offensive")
                    if os.path.isdir(cs2): return cs2
        except Exception: pass
    return ""

def _is_cs2_folder(path):
    return path and os.path.isdir(os.path.join(path, "game", "csgo"))

GSI_CFG_NAME = "gamestate_integration_overlay.cfg"
GSI_CFG_BODY = '''"CS2_Overlay_Parser"
{{
    "uri"           "http://127.0.0.1:{port}"
    "timeout"       "5.0"
    "buffer"        "0.1"
    "throttle"      "0.5"
    "heartbeat"     "2.0"
    "data"
    {{
        "provider"              "1"
        "map"                   "1"
        "round"                 "1"
        "player_id"             "1"
        "allplayers_id"         "1"
        "allplayers_state"      "1"
        "allplayers_match_stats" "1"
    }}
}}'''

def ensure_gsi(cs2_path, port):
    cfg_dir = os.path.join(cs2_path, "game", "csgo", "cfg")
    if not os.path.isdir(cfg_dir): return False, f"Нет папки: {cfg_dir}"
    dst = os.path.join(cfg_dir, GSI_CFG_NAME)
    try:
        if os.path.isfile(dst): os.remove(dst)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(GSI_CFG_BODY.format(port=port))
        return True, "GSI установлен."
    except Exception as e:
        return False, str(e)

class _GsiHandler(BaseHTTPRequestHandler):
    callback = None
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        try:
            if _GsiHandler.callback: _GsiHandler.callback(json.loads(raw))
        except Exception: pass
        self.send_response(200)
        self.end_headers()
    def log_message(self, *_a): pass

class GsiServer:
    def __init__(self, port):
        self.port = port
        self.players = {}
        self._provider_steamid = ""
        self._srv = None

    def start(self):
        _GsiHandler.callback = self._on_data
        self._srv = HTTPServer(("127.0.0.1", self.port), _GsiHandler)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def _on_data(self, data):
        prov = data.get("provider") if isinstance(data.get("provider"), dict) else {}
        self._provider_steamid = str(prov.get("steamid") or "").strip()
        ap = data.get("allplayers")
        if ap and isinstance(ap, dict):
            new = {}
            for sid, info in ap.items():
                if _is_bot(sid, info.get("name", "")): continue
                new[sid] = {"name": info.get("name", "?"), "team": info.get("team", "")}
            self.players = new

    def get_my_steam_id(self): return self._provider_steamid
    def get_players(self): return dict(self.players)

def _is_bot(steam_id, name=""):
    s = str(steam_id).strip()
    if s in ("0", "BOT", "", "76561197960265728") or not re.match(r"^765\d{14}$", s): return True
    if str(name).strip().lower().startswith("bot "): return True
    return False

def _parse_status_text(text):
    players = {}
    for line in text.splitlines():
        line = line.strip()
        for regex in (r'#\s+\d+\s+\d+\s+"(.+?)"\s+(\d{17})', r'#.*?"(.+?)".*?(\d{17})'):
            m = re.match(regex, line)
            if m:
                name, sid = m.group(1), m.group(2)
                if not _is_bot(sid, name): players[sid] = {"name": name, "team": ""}
                break
    return players

def read_console_log(cs2_path):
    p = os.path.join(cs2_path, "game", "csgo", "console.log")
    if not os.path.isfile(p):
        return {}, ""
    try:
        size = os.path.getsize(p)
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            if size > 524288:
                f.seek(size - 524288)
            text = f.read()
            blocks = list(re.finditer(r'(?m)^hostname[\s:]+', text))
            if blocks:
                last_block = text[blocks[-1].start():]
                server_ident = last_block.splitlines()[0].strip() if last_block else ""
                return _parse_status_text(last_block), server_ident
            return {}, ""
    except Exception:
        return {}, ""

def fetch_inventory_batch_via_backend(steam_ids: list) -> dict:
    key = (CFG.get("license_key") or "").strip()
    steam_ids = [str(s).strip() for s in steam_ids if s and str(s).strip()]
    _parser_log("Batch request", n_steam_ids=len(steam_ids), has_key=bool(key))
    if not key or not steam_ids:
        _parser_log("Batch skip: no key or no steam_ids")
        return {"__ERROR__": "Нет ключа или нет игроков"}
    try:
        r = call_backend(
            "api/inventory/batch",
            method="POST",
            json={"key": key, "device_id": get_device_id(), "steam_ids": steam_ids},
            timeout=30,
        )
    except Exception as e:
        _parser_log("Batch inventory request failed", error=repr(e))
        return {"__ERROR__": f"Нет связи с сервером: {e}"}
    if r.status_code != 200:
        detail = None
        try:
            detail = (r.json() if r.text else {}).get("detail")
        except Exception:
            detail = None
        msg = detail or f"HTTP {r.status_code}"
        _parser_log("Batch inventory non-200", status=r.status_code, detail=msg)
        return {"__ERROR__": msg}
    try:
        data = r.json() if r.text else {}
    except Exception:
        return {"__ERROR__": "invalid response"}
    out = {}
    for sid in steam_ids:
        entry = data.get(sid)
        if isinstance(entry, dict):
            out[sid] = (entry.get("value"), entry.get("items") or [])
        else:
            out[sid] = (None, [])
    return out


def fetch_inventory_single_via_backend(steam_id: str) -> tuple:
    key = (CFG.get("license_key") or "").strip()
    sid = str(steam_id or "").strip()
    if not key or not sid or not (CFG.get("license_server_url") or "").strip():
        return None, []
    try:
        r = call_backend(
            "api/inventory/single",
            method="POST",
            json={"key": key, "device_id": get_device_id(), "steam_id": sid},
            timeout=25,
        )
    except Exception:
        return None, []
    if r.status_code != 200:
        return None, []
    try:
        data = r.json() if r.text else {}
        entry = data.get(sid)
        if isinstance(entry, dict):
            return entry.get("value"), entry.get("items") or []
    except Exception:
        pass
    return None, []


def fetch_faceit(steam_id):
    result = {"found": False, "nickname": "", "country": "", "url": "", "elo": 0, "level": 0, "matches": 0, "player_id": ""}
    headers = {"Authorization": f"Bearer {CFG['faceit_api_key']}"} if CFG.get("faceit_api_key") else {}
    for game in ("cs2", "csgo"):
        try:
            r = requests.get(f"https://open.faceit.com/data/v4/players", params={"game": game, "game_player_id": steam_id}, headers=headers, timeout=5)
            if r.status_code == 200:
                d = r.json()
                pid = d.get("player_id", "")
                result.update({"found": True, "nickname": d.get("nickname", ""), "country": (d.get("country") or "").upper(), "url": (d.get("faceit_url") or "").replace("{lang}", "en"), "player_id": pid})
                cs = d.get("games", {}).get(game, {})
                result["elo"] = cs.get("faceit_elo", 0)
                result["level"] = cs.get("skill_level", 0)
                if pid and headers:
                    sr = requests.get(f"https://open.faceit.com/data/v4/players/{pid}/stats/{game}", headers=headers, timeout=5)
                    if sr.status_code == 200: result["matches"] = int(sr.json().get("lifetime", {}).get("Matches", 0))
                return result
        except Exception: pass
    return result

class WorkerSignals(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(list)

class Worker(QThread):
    def __init__(self, players):
        super().__init__()
        self.players = players
        self.sig = WorkerSignals()
        self._cancel = threading.Event()
        self._last_error: str | None = None

    def cancel(self): self._cancel.set()

    def run(self):
        self._cancel.clear()
        self._last_error = None
        if not self.players:
            self.sig.finished.emit([])
            return
        steam_ids = list(self.players.keys())
        _parser_log("Worker batch start", n_ids=len(steam_ids))
        inv_by_id = {}
        if not self._cancel.is_set():
            inv_by_id = fetch_inventory_batch_via_backend(steam_ids)
            if isinstance(inv_by_id, dict) and "__ERROR__" in inv_by_id:
                err_msg = inv_by_id.get("__ERROR__") or "Ошибка инвентаря"
                self._last_error = err_msg
                _parser_log("Worker batch error", error=err_msg)
                self.sig.finished.emit([])
                return
            _parser_log("Worker batch ok")

        results = []
        for done, (steam_id, info) in enumerate(self.players.items(), 1):
            if self._cancel.is_set(): break
            inv_val, top_items = inv_by_id.get(steam_id, (None, []))
            results.append({
                "steam_id": steam_id,
                "name": info.get("name") or steam_id,
                "team": info.get("team", ""),
                "inv_value": inv_val,
                "top_items": top_items,
                "faceit": {}, "country": ""
            })
            self.sig.progress.emit(f"Готово: {info.get('name', '?')}")
        results.sort(key=lambda x: (x.get("inv_value") is None, -(x.get("inv_value") or 0)))
        self.sig.finished.emit(results)

BTN_STYLE = """
QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #6366f1, stop:1 #4f46e5); border: none; border-radius: 10px; padding: 10px 16px; color: #fff; font-size: 13px; font-weight: bold; }
QPushButton:hover { background: #818cf8; } QPushButton:pressed { background: #4338ca; } QPushButton:disabled { background: #475569; color: #94a3b8; }
"""
FOLDER_BTN_STYLE_OK = """
QPushButton { background: #16a34a; border: none; border-radius: 10px; padding: 10px 16px; color: #fff; font-size: 13px; font-weight: bold; }
QPushButton:hover { background: #15803d; }
"""
ICON_BTN_STYLE = """
QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #6366f1, stop:1 #4f46e5); border: none; border-radius: 16px; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; padding: 0; color: #fff; font-size: 18px; font-weight: bold; }
QPushButton:hover { background: #818cf8; } QPushButton:pressed { background: #4338ca; }
"""
ICON_STOP_BTN_STYLE = """
QPushButton { background: #dc2626; border: none; border-radius: 16px; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; padding: 0; color: #fff; font-size: 14px; font-weight: bold; }
QPushButton:hover { background: #ef4444; } QPushButton:pressed { background: #b91c1c; } QPushButton:disabled { background: #374151; color: #9ca3af; }
"""
PANEL_BG = "background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1e1b4b, stop:1 #0f0f23); border: 1px solid rgba(99, 102, 241, 0.3); border-radius: 14px;"

class DetailLoaderThread(QThread):
    done = pyqtSignal(list, object, dict)
    def __init__(self, steam_id):
        super().__init__()
        self.steam_id = steam_id
    def run(self):
        faceit = fetch_faceit(self.steam_id)
        self.done.emit([], None, faceit or {})

class DetailDialog(QDialog):
    def __init__(self, r: dict, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        # Делаем диалог модальным, чтобы он всегда был поверх радара игроков
        self.setWindowModality(Qt.ApplicationModal)
        self.r = r if isinstance(r, dict) else {}
        self.setWindowTitle(f"Подробнее — {self.r.get('name') or '?'}")
        self.setMinimumSize(380, 280)
        self.content = QPlainTextEdit(self)
        self.content.setReadOnly(True)
        self.content.setStyleSheet("background:rgba(25,25,45,255);color:#ddd;border-radius:6px;")
        QVBoxLayout(self).addWidget(self.content)
        self.content.appendPlainText(f"Steam ID: {self.r.get('steam_id') or '?'}")
        val = self.r.get("inv_value")
        self.content.appendPlainText(f"Инвентарь: ${float(val):.2f}" if val is not None else "Инвентарь: Ошибка / Не загружен")
        self.content.appendPlainText("\nЗагрузка Faceit...")
        self._l = DetailLoaderThread(str(self.r.get("steam_id") or ""))
        self._l.done.connect(self._on_loaded)
        self._l.start()
        self.setStyleSheet("background:rgba(28,28,48,255);color:#eee;")
    def _on_loaded(self, m, c, fc):
        txt = self.content.toPlainText().replace("\nЗагрузка Faceit...", "")
        self.content.setPlainText(txt)
        if fc.get("found"):
            self.content.appendPlainText(f"\nFaceit: {fc.get('nickname', '?')}\n  Уровень: {fc.get('level')}\n  ELO: {fc.get('elo')}\n  Страна: {fc.get('country')}")
        else:
            self.content.appendPlainText("\nFaceit не найден.")

class ResultsPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._drag_pos = None
        self.on_detail = None
        self.on_restore_clicked = None
        self.on_clear_clicked = None
        self.setWindowFlags((Qt.FramelessWindowHint | Qt.Window | Qt.WindowStaysOnTopHint) & ~Qt.WindowContextHelpButtonHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(380)
        self.setMinimumHeight(260)
        self.setFocusPolicy(Qt.StrongFocus)
        self._build_ui()
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.LeftButton: self.move(e.globalPos() - self._drag_pos)
    def mouseReleaseEvent(self, _e): self._drag_pos = None

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.box = QWidget()
        self.box.setStyleSheet(f"#box {{{PANEL_BG}}}")
        self.box.setObjectName("box")
        bl = QVBoxLayout(self.box)
        hdr = QHBoxLayout()
        t = QLabel("РАДАР ИГРОКОВ")
        t.setStyleSheet("color:#a5b4fc;font-size:16px;font-weight:bold;")
        hdr.addWidget(t)
        hdr.addStretch()
        clear_btn = QPushButton("🗑 Очистить")
        clear_btn.setStyleSheet("QPushButton{background:#475569;border-radius:10px;color:white;font:bold 12px;padding:6px;} QPushButton:hover{background:#64748b;}")
        clear_btn.clicked.connect(lambda: self.on_clear_clicked() if getattr(self, 'on_clear_clicked', None) else None)
        
        restore_btn = QPushButton("↩ Вернуть")
        restore_btn.setStyleSheet("QPushButton{background:#475569;border-radius:10px;color:white;font:bold 12px;padding:6px;} QPushButton:hover{background:#64748b;}")
        restore_btn.clicked.connect(lambda: self.on_restore_clicked() if getattr(self, 'on_restore_clicked', None) else None)
        
        hdr.insertWidget(2, restore_btn)
        hdr.insertWidget(3, clear_btn)
        cb = QPushButton("✕")
        cb.setFixedSize(28, 28)
        cb.setStyleSheet("QPushButton{background:#dc2626;border-radius:14px;color:white;font:bold 13px;} QPushButton:hover{background:#ef4444;}")
        cb.clicked.connect(self.hide)
        hdr.addWidget(cb)
        bl.addLayout(hdr)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("border:none;background:transparent;")
        self.sw = QWidget()
        self.sl = QVBoxLayout(self.sw)
        self.sl.addStretch()
        self.scroll.setWidget(self.sw)
        bl.addWidget(self.scroll)
        root.addWidget(self.box)
        self._current_results = []

    def get_results_without_value(self): return [r for r in self._current_results if r.get("inv_value") is None]

    def add_results(self, new_rows):
        for r in new_rows:
            self._current_results.append(r)
            self.sl.insertWidget(self.sl.count() - 1, self._card(r))

    def update_result_inplace(self, steam_id, val, items):
        for r in self._current_results:
            if str(r.get("steam_id")) == str(steam_id): r["inv_value"], r["top_items"] = val, items or []
    def set_results(self, results):
        while self.sl.count() > 1:
            i = self.sl.takeAt(0)
            if i.widget(): i.widget().deleteLater()
        self._current_results = list(results) if results else []
        for r in self._current_results:
            self.sl.insertWidget(self.sl.count() - 1, self._card(r))
        try:
            self.sw.updateGeometry()
            QApplication.processEvents()
        except Exception:
            pass
        self.show()

    def _card(self, r):
        c = QFrame()
        c.setStyleSheet("QFrame{background:rgba(30,27,75,0.95);border-radius:10px;border:1px solid rgba(99,102,241,0.25);}")
        vl = QVBoxLayout(c)
        l1 = QHBoxLayout()
        t = r.get("team", "")
        if t: l1.addWidget(QLabel(f"[{t}]", styleSheet=f"color:{'#5c94fc' if t=='CT' else '#e8c252'};font-weight:bold;"))
        name_lbl = QLabel(str(r.get("name") or "?"))
        name_lbl.setStyleSheet("color:white;font-weight:bold;")
        name_lbl.setWordWrap(True)
        name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        l1.addWidget(name_lbl)
        v = r.get("inv_value")
        if v is not None:
            l1.addWidget(QLabel(f"— ${float(v):.2f}", styleSheet="color:#4cff4c;font-weight:bold;"))
        else:
            l1.addWidget(QLabel("— (не проверен)", styleSheet="color:#94a3b8;"))
        l1.addStretch()
        vl.addLayout(l1)
        
        in_db = r.get("in_db_before_check", False)
        has_date = r.get("updated_at") is not None
        show_status = in_db or has_date
        
        if show_status:
            parsed_row = QHBoxLayout()
            try:
                icon = QApplication.style().standardIcon(QStyle.SP_DialogApplyButton)
                icon_lbl = QLabel()
                icon_lbl.setPixmap(icon.pixmap(14, 14))
                parsed_row.addWidget(icon_lbl)
            except Exception:
                pass
            if in_db and r.get("parsed_by_you"):
                status_text = "Ранее спаршен вами"
            elif in_db:
                status_text = "Ранее в базе"
            else:
                status_text = "Спаршен вами"
            parsed_row.addWidget(QLabel(status_text, styleSheet="color:#94a3b8;font-size:10px;"))
            parsed_row.addStretch()
            vl.addLayout(parsed_row)
            
            # Умная обработка даты (без года, с "Сегодня")
            up = str(r.get("updated_at") or "").strip()
            if len(up) >= 16:  # Формат YYYY-MM-DDTHH:MM:SS
                import time
                yr, mo, dy = up[0:4], up[5:7], up[8:10]
                hr, mn = up[11:13], up[14:16]
                if yr == time.strftime("%Y") and mo == time.strftime("%m") and dy == time.strftime("%d"):
                    date_str = f"Сегодня в {hr}:{mn}"
                else:
                    date_str = f"{dy}.{mo} в {hr}:{mn}"
                vl.addWidget(QLabel(f"Обновлено: {date_str}", styleSheet="color:#64748b;font-size:10px;"))

        b_row = QHBoxLayout()
        bd = QPushButton("Открыть в браузере")
        bd.setStyleSheet("""
            QPushButton { background: rgba(99,102,241,0.4); border-radius: 6px; padding: 6px; color: white; font-weight: bold; }
            QPushButton:hover { background: rgba(99,102,241,0.8); }
            QPushButton:pressed { background: rgba(79,70,229,1); }
        """)
        bd.clicked.connect(lambda _, sid=str(r.get("steam_id") or ""): QDesktopServices.openUrl(QUrl(f"https://steamcommunity.com/profiles/{sid}")))
        b_row.addWidget(bd)
        
        if getattr(self, "on_refresh_player", None) and r.get("steam_id"):
            refresh_btn = QPushButton("Обновить информацию")
            refresh_btn.setEnabled(True)
            try:
                refresh_btn.setIcon(QApplication.style().standardIcon(QStyle.SP_BrowserReload))
            except Exception:
                pass
            refresh_btn.setStyleSheet("""
                QPushButton { background: rgba(34,197,94,0.4); border-radius: 6px; padding: 6px; color: white; font-weight: bold; }
                QPushButton:hover { background: rgba(34,197,94,0.8); }
                QPushButton:pressed { background: rgba(22,163,74,1); }
            """)
            refresh_btn.clicked.connect(lambda _, sid=str(r.get("steam_id") or ""): self.on_refresh_player(sid) if self.on_refresh_player else None)
            b_row.addWidget(refresh_btn)
            
        vl.addLayout(b_row)
        return c

def _format_qt_hotkey(key, mods):
    m = []
    if mods & Qt.ControlModifier: m.append("Ctrl")
    if mods & Qt.AltModifier: m.append("Alt")
    if mods & Qt.ShiftModifier: m.append("Shift")
    ks = None
    if Qt.Key_F1 <= key <= Qt.Key_F12: ks = "F" + str(1 + key - Qt.Key_F1)
    elif Qt.Key_A <= key <= Qt.Key_Z: ks = chr(ord("A") + key - Qt.Key_A)
    elif Qt.Key_0 <= key <= Qt.Key_9: ks = str(key - Qt.Key_0)
    return "+".join(m + [ks]) if ks else None

class HotkeyDialog(QDialog):
    def __init__(self, parent=None, cur=""):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("Хоткей")
        self._combo = (cur or "Ctrl+Y").strip()
        self._listening = False
        l = QVBoxLayout(self)
        self.hint_lbl = QLabel("Нажмите «Задать комбинацию», затем нужные клавиши.", styleSheet="color:#cbd5f5;font-size:11px;")
        l.addWidget(self.hint_lbl)
        self.lbl = QLabel(self._combo, styleSheet="font-size:16px;font-weight:bold;color:#a5b4fc;padding:8px;")
        l.addWidget(self.lbl)
        hl = QHBoxLayout()
        self.b_listen = QPushButton("Назначить", styleSheet=BTN_STYLE)
        self.b_listen.clicked.connect(self._start)
        self.b_save = QPushButton("Сохранить", styleSheet=BTN_STYLE)
        self.b_save.clicked.connect(self._save)
        hl.addWidget(self.b_listen)
        hl.addWidget(self.b_save)
        l.addLayout(hl)
        self.setStyleSheet("QDialog{background:#1a1a2e;}")
    def _start(self):
        self._listening = True
        self.lbl.setText("Нажмите клавиши...")
    def keyPressEvent(self, e):
        e.accept()
        if not self._listening or e.key() in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return
            
        vk = e.nativeVirtualKey()
        key_str = None
        
        if 65 <= vk <= 90:
            key_str = chr(vk)
        elif Qt.Key_F1 <= e.key() <= Qt.Key_F12:
            key_str = "F" + str(1 + e.key() - Qt.Key_F1)
        elif Qt.Key_0 <= e.key() <= Qt.Key_9:
            key_str = str(e.key() - Qt.Key_0)
        else:
            seq = QKeySequence(int(e.key()))
            key_str = seq.toString().strip().upper()
            ru_to_en = dict(zip("ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮЁ", "QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>~"))
            if key_str in ru_to_en:
                key_str = ru_to_en[key_str]

        if not key_str:
            return

        mods = []
        if e.modifiers() & Qt.ControlModifier: mods.append("Ctrl")
        if e.modifiers() & Qt.AltModifier: mods.append("Alt")
        if e.modifiers() & Qt.ShiftModifier: mods.append("Shift")
        
        s = "+".join(mods + [key_str])
        
        if s:
            self._combo = s
            self.lbl.setText(s)
            self._listening = False
    def _save(self):
        CFG["bring_on_top_hotkey"] = self._combo
        save_cfg(CFG)
        self.accept()

class SettingsDialog(QDialog):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowTitle(f"Настройки (Ver. {APP_VERSION})")
        self.setMinimumWidth(300)
        l = QVBoxLayout(self)
        cs2_ok = bool((CFG.get("cs2_path") or "").strip())
        cs2_text = "Папка CS2: Выбрана" if cs2_ok else "Папка CS2: Не указана"
        cs2_style = FOLDER_BTN_STYLE_OK if cs2_ok else BTN_STYLE
        l.addWidget(QPushButton(cs2_text, clicked=app.pick_steam_path, styleSheet=cs2_style))
        def _set_hotkey():
            if HotkeyDialog(self, CFG.get("bring_on_top_hotkey")).exec_() == QDialog.Accepted:
                app._register_bring_on_top_hotkey() # Применяем на лету
                
        l.addWidget(QPushButton("Горячая клавиша", clicked=_set_hotkey, styleSheet=BTN_STYLE))
        e = CFG.get("expires_at", "")[:10]
        self._license_btn = QPushButton(f"Лицензия (до {_cfg_expires_ddmm(e)})" if e else "Лицензия", styleSheet=BTN_STYLE)
        self._license_btn.clicked.connect(lambda: self._open_activation_and_refresh_license(app))
        l.addWidget(self._license_btn)
        min_val = int(CFG.get("min_value") or 150)
        min_btn = QPushButton(f"Минимальный порог отображения: {min_val}$", styleSheet=BTN_STYLE)
        min_btn.clicked.connect(lambda: self._set_min_value(app))
        l.addWidget(min_btn)
        l.addWidget(QPushButton("Закрыть", clicked=self.accept, styleSheet="background:#dc2626;color:white;border-radius:10px;padding:10px;font-weight:bold;"))
        self.setStyleSheet("QDialog{background:#1a1a2e;}")

    def _open_activation_and_refresh_license(self, app):
        ActivationDialog(self).exec_()
        e = CFG.get("expires_at", "")[:10]
        self._license_btn.setText(f"Лицензия (до {_cfg_expires_ddmm(e)})" if e else "Лицензия")

    def _set_min_value(self, app):
        cur = int(CFG.get("min_value") or 150)
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Порог отображения")
        dlg.setLabelText("Минимальная сумма инвентаря ($):")
        dlg.setIntValue(cur)
        dlg.setIntRange(0, 100000)
        dlg.setStyleSheet("QInputDialog { background: #1a1a2e; color: white; } QLabel { color: white; } QLineEdit, QSpinBox { background: #16213e; color: white; border: 1px solid #0f3460; padding: 4px; } QPushButton { background: #6366f1; color: white; padding: 6px; border-radius: 4px; font-weight: bold;}")
        if dlg.exec_() == QDialog.Accepted:
            val = dlg.intValue()
            CFG["min_value"] = val
            save_cfg(CFG)
            msg = QMessageBox(self)
            msg.setWindowTitle("Готово")
            msg.setText(f"Порог установлен: {val}$")
            msg.setStyleSheet("QMessageBox, QLabel { color: #ffffff; background-color: #1a1a2e; } QPushButton { color: #fff; background: #6366f1; min-width: 80px; }")
            msg.exec_()

class ControlPanel(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._drag_pos = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._build_ui()
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.LeftButton: self.move(e.globalPos() - self._drag_pos)
    def mouseReleaseEvent(self, _e): self._drag_pos = None
    def keyPressEvent(self, e): e.accept()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        box = QWidget(objectName="box", styleSheet=f"#box{{{PANEL_BG}}}")
        vl = QVBoxLayout(box)
        logo_dir = getattr(sys, "_MEIPASS", SCRIPT_DIR)
        logo_path = os.path.join(logo_dir, "assets", "logo.png")
        if not os.path.isfile(logo_path):
            logo_path = os.path.join(SCRIPT_DIR, "assets", "logo.png")
        if os.path.isfile(logo_path):
            try:
                pix = QPixmap(logo_path)
                if not pix.isNull():
                    pix = pix.scaledToWidth(200, Qt.SmoothTransformation)
                    logo_lbl = QLabel()
                    logo_lbl.setPixmap(pix)
                    logo_lbl.setAlignment(Qt.AlignCenter)
                    vl.addWidget(logo_lbl)
            except Exception:
                pass
        hl = QHBoxLayout()
        self.btn_check = QPushButton("Проверка", styleSheet=BTN_STYLE, clicked=self.app.start_check)
        self.btn_list = QPushButton("Список", styleSheet=BTN_STYLE, clicked=self.app.show_players_list)
        self.btn_set = QPushButton("⚙", styleSheet=ICON_BTN_STYLE, clicked=lambda: SettingsDialog(self, self.app).exec_())
        self.btn_x = QPushButton("✕", styleSheet="background:#dc2626;border-radius:16px;color:white;font-weight:bold;min-width:32px;max-width:32px;min-height:32px;max-height:32px;", clicked=QApplication.quit)
        for w in (self.btn_check, self.btn_list, self.btn_set, self.btn_x): hl.addWidget(w)
        vl.addLayout(hl)
        self.lbl_st = QLabel("", alignment=Qt.AlignCenter, styleSheet="color:#94a3b8;font-size:11px;")
        self.lbl_st.setTextInteractionFlags(Qt.NoTextInteraction)
        self.lbl_gsi = QLabel("Перейдите в наблюдатели чтобы начать проверку", alignment=Qt.AlignCenter, styleSheet="color:#64748b;font-size:11px;")
        vl.addWidget(self.lbl_st)
        vl.addWidget(self.lbl_gsi)
        root.addWidget(box)
        self.setFixedWidth(420)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_status(self, t, c="#94a3b8"): self.lbl_st.setText(t); self.lbl_st.setStyleSheet(f"color:{c};font-size:11px;")
    def set_gsi(self, total, checked=None):
        if total > 0 and checked is not None:
            self.lbl_gsi.setText(f"🟢 Проверено: {checked} / {total}")
            self.lbl_gsi.setStyleSheet("color:#22c55e;font-size:12px;font-weight:bold;")
        elif total > 1:
            self.lbl_gsi.setText(f"🟢 Игроков: {total}.")
            self.lbl_gsi.setStyleSheet("color:#22c55e;font-size:12px;font-weight:bold;")
        else:
            self.lbl_gsi.setText("Перейдите в наблюдатели чтобы начать проверку")
            self.lbl_gsi.setStyleSheet("color:#64748b;font-size:10px;")

class App:
    def __init__(self):
        self.worker, self.gsi = None, None
        self.results_panel = ResultsPanel()
        self.results_panel.on_detail = lambda r: DetailDialog(r, self.results_panel).exec_()
        self.results_panel.on_refresh_player = self.refresh_player_inventory
        self.results_panel.on_clear_clicked = self.clear_radar
        self.results_panel.on_restore_clicked = self.restore_radar
        self.ctrl = ControlPanel(self)
        self.cs2_path = CFG.get("cs2_path", "")
        self._hotkey_filter = None
        self._last_server_ident = ""
        self._in_db_results: list = []
        self._players: dict[str, dict] = {}
        self._init_gsi()
        QTimer.singleShot(0, self._start)
        self.t = QTimer(); self.t.timeout.connect(self._poll); self.t.start(2000)
    
    def _init_gsi(self):
        if self.cs2_path: ensure_gsi(self.cs2_path, CFG.get("gsi_port", 3000))
        self.gsi = GsiServer(CFG.get("gsi_port", 3000))
        self.gsi.start()

    def clear_radar(self):
        for sid in self._players:
            self._players[sid]["in_list"] = False
        self.results_panel.set_results([])
        self.ctrl.set_status("Список очищен", "#94a3b8")

    def restore_radar(self):
        min_val = float(CFG.get("min_value") or 150)
        for sid, info in self._players.items():
            if info.get("checked") and info.get("inv_value") is not None:
                info["in_list"] = float(info["inv_value"]) >= min_val
        self.show_players_list()
        self.ctrl.set_status("Список восстановлен", "#94a3b8")

    def _collect_players(self, count_new: bool = True) -> set[str]:
        p: dict[str, dict] = {}
        if self.gsi:
            p.update(self.gsi.get_players())
        my = self.gsi.get_my_steam_id() if self.gsi else ""
        if my in p:
            del p[my]
        if self.cs2_path:
            pc, srv_id = read_console_log(self.cs2_path)
            if srv_id and srv_id != getattr(self, "_last_server_ident", ""):
                self._players.clear()
                self._last_server_ident = srv_id
                if hasattr(self, "results_panel"):
                    self.results_panel.set_results([])
            if my in pc:
                del pc[my]
            p.update(pc)

        current_ids: set[str] = set()
        for sid, info in p.items():
            sid_str = str(sid)
            current_ids.add(sid_str)
            existed = sid_str in self._players
            if not existed:
                self._players[sid_str] = {
                    "steam_id": sid_str,
                    "name": info.get("name") or sid_str,
                    "team": info.get("team", ""),
                    "inv_value": None,
                    "checked": False,
                    "in_list": False,
                }
            else:
                self._players[sid_str]["name"] = info.get("name") or self._players[sid_str]["name"]
                self._players[sid_str]["team"] = info.get("team", self._players[sid_str]["team"])
        return current_ids

    def _poll(self):
        try:
            current_ids = self._collect_players(count_new=True)
        except Exception:
            current_ids = set()

        if self.gsi:
            try:
                total = len(current_ids)
                checked = sum(1 for sid in current_ids if self._players.get(sid, {}).get("checked"))
                self.ctrl.set_gsi(total, checked)
            except Exception:
                pass

        has_unchecked = any(not info.get("checked") for info in self._players.values())
        is_working = self.worker is not None and self.worker.isRunning()
        is_cooldown = getattr(self, "_cooldown_left", 0) > 0
        self.ctrl.btn_check.setEnabled(has_unchecked and not is_working and not is_cooldown)

    def _check_for_updates(self):
        if not getattr(sys, "frozen", False):
            return
        url_base = (CFG.get("license_server_url") or "").strip().rstrip("/")
        if not url_base:
            return
        try:
            r = requests.get(f"{url_base}/api/version", timeout=10)
            if r.status_code != 200:
                return
            data = r.json() or {}
            try:
                server_ver = float(data.get("version", 0))
            except (TypeError, ValueError):
                return
            if server_ver <= APP_VERSION:
                return
        except Exception:
            return
        update_url = (data.get("update_url") or "").strip() or f"{url_base}/download/update"
        data_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CS2_Parser")
        try:
            os.makedirs(data_dir, exist_ok=True)
        except Exception:
            return
        self.ctrl.set_status("Скачивание обновления...", "#ffd700")
        QApplication.processEvents()
        dest_exe = os.path.join(data_dir, "update_new.exe")
        from PyQt5.QtWidgets import QProgressDialog
        total_size = 50 * 1024 * 1024  # примерный размер по умолчанию
        try:
            head_r = requests.head(update_url, timeout=5)
            if head_r.status_code == 200 and 'content-length' in head_r.headers:
                total_size = int(head_r.headers['content-length'])
        except Exception:
            pass

        progress = QProgressDialog("Обновление софта...", "Отмена", 0, total_size, self.ctrl)
        progress.setWindowTitle("Обновление в процессе")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setStyleSheet("""
            QProgressDialog { background: #1a1a2e; border: 1px solid #4f46e5; }
            QLabel { color: #e0e0e0; font-weight: bold; }
            QProgressBar { 
                border: 1px solid #4f46e5; 
                border_radius: 5px; 
                text-align: center; 
                color: white; 
                background: #16213e;
            }
            QProgressBar::chunk { background-color: #6366f1; }
            QPushButton { background: #475569; color: white; border-radius: 5px; padding: 5px; }
        """)
        progress.show()

        downloaded = 0
        try:
            rr = requests.get(update_url, timeout=120, stream=True)
            rr.raise_for_status()
            with open(dest_exe, "wb") as f:
                for chunk in rr.iter_content(chunk_size=1048576):
                    if progress.wasCanceled():
                        return
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress.setValue(downloaded)
                        QApplication.processEvents()
        except Exception:
            return
        bat_path = os.path.join(data_dir, "updater.bat")
        bat_content = "@echo off\r\ntimeout /t 2 /nobreak >nul\r\nmove /y \"update_new.exe\" \"CS2_Parser.exe\"\r\nstart \"\" \"CS2_Parser.exe\"\r\ndel \"%~f0\"\r\n"
        try:
            with open(bat_path, "wb") as f:
                f.write(bat_content.encode("utf-8"))
        except Exception:
            return
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            subprocess.Popen(
                ["cmd.exe", "/c", bat_path],
                cwd=data_dir,
                creationflags=flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
        sys.exit(0)

    def _start(self):
        self._check_for_updates()
        self.ctrl.show()
        if not CFG.get("license_key"): ActivationDialog(self.ctrl).exec_()
        self._register_bring_on_top_hotkey()

    def _on_bring_on_top(self):
        self.ctrl.raise_()
        self.ctrl.activateWindow()
        if self.results_panel.isVisible():
            self.results_panel.raise_()
            self.results_panel.activateWindow()

    def _register_bring_on_top_hotkey(self):
        global _HOTKEY_CB
        if sys.platform != "win32" or _HotkeyNativeFilter is None:
            return
        qapp = QApplication.instance()
        if not qapp:
            return
        _HOTKEY_CB = self._on_bring_on_top
        
        if not self._hotkey_filter:
            self._hotkey_filter = _HotkeyNativeFilter()
            qapp.installNativeEventFilter(self._hotkey_filter)
            
        try:
            _unregister_hotkey_win(self.ctrl.winId(), HOTKEY_ID)
        except Exception:
            pass

        mod, vk = _parse_hotkey(CFG.get("bring_on_top_hotkey") or "Ctrl+Y")
        if mod is not None and vk is not None:
            try:
                _register_hotkey_win(self.ctrl.winId(), HOTKEY_ID, mod, vk)
            except Exception:
                pass

    def show_players_list(self):
        self._collect_players(count_new=False)

        if not self._players:
            self.ctrl.set_status("Игроки не найдены. Введите status в консоли и нажмите «Проверка».", "#ff8800")
            return

        min_val = float(CFG.get("min_value") or 150)
        fat_players = []
        for sid, info in self._players.items():
            v = info.get("inv_value")
            if v is not None and float(v or 0) >= min_val and info.get("in_list", False):
                fat_players.append({
                    "steam_id": sid,
                    "name": info.get("name") or sid,
                    "team": info.get("team", ""),
                    "inv_value": v,
                    "in_db_before_check": info.get("in_db_before_check", False),
                    "parsed_by_you": info.get("parsed_by_you", False),
                    "updated_at": info.get("updated_at"),
                })

        if not fat_players:
            self.ctrl.set_status("Пока нет игроков с инвентарём выше порога. Нажмите «Проверка».", "#94a3b8")
        else:
            self.results_panel.set_results(fat_players)

        pos = self.ctrl.pos()
        self.results_panel.move(pos.x() + 340, pos.y())
        self.results_panel.show()
        self.ctrl.set_status(f"Список открыт. Игроков: {len(self.results_panel._current_results)}", "#94a3b8")

    def refresh_player_inventory(self, steam_id: str):
        sid = str(steam_id or "").strip()
        if not sid:
            return
            
        info = self._players.get(sid, {})
        name = str(info.get("name") or sid)
        
        self.ctrl.set_status(f"Обновляю: {name}...", "#ffd700")
        val, items = fetch_inventory_single_via_backend(sid)
        
        if info is not None:
            info["inv_value"] = val
            import time
            info["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            info["parsed_by_you"] = True
            info["in_db_before_check"] = True
            self._players[sid] = info
            
        self.results_panel.update_result_inplace(sid, val, items)
        
        if val is not None and info:
            try:
                report_parsed_remote(sid, float(val), str(info.get("name") or "") or None, None)
            except Exception:
                pass
        
        self.show_players_list()
        
        # Информативный ответ
        if val is not None:
            self.ctrl.set_status(f"Обновлен: {name} (${float(val):.2f})", "#4cff4c")
        else:
            self.ctrl.set_status(f"Не удалось обновить: {name}", "#ff6666")

    def start_check(self):
        if self.worker and self.worker.isRunning(): return
        current_ids = self._collect_players(count_new=False)
        if not current_ids:
            self.ctrl.set_status("Игроки не найдены. Введите status в консоли и попробуйте ещё раз.", "#ff8800")
            return
        to_check_ids = [sid for sid in current_ids if not self._players.get(sid, {}).get("checked")]
        if not to_check_ids:
            self.ctrl.set_status("Новых игроков для проверки нет.", "#94a3b8")
            return

        self._added_count = 0
        self._in_db_results = []
        if hasattr(self.results_panel, "_added_lbl") and self.results_panel._added_lbl:
            self.results_panel._added_lbl.setText("")

        self.ctrl.set_status("Связь с базой...", "#ffd700")
        QApplication.processEvents()
        batch = check_parsed_batch_remote(to_check_ids)
        in_db_ids = [sid for sid in to_check_ids if batch.get(sid, {}).get("parsed")]
        not_in_db_ids = [sid for sid in to_check_ids if sid not in in_db_ids]

        for sid in in_db_ids:
            data = batch.get(sid, {})
            info = self._players.get(sid) or {
                "steam_id": sid,
                "name": sid,
                "team": "",
                "inv_value": None,
                "checked": False,
                "in_list": False,
            }
            info["name"] = data.get("name") or info.get("name") or sid
            info["team"] = info.get("team", "")
            info["inv_value"] = data.get("last_value")
            info["checked"] = True
            info["updated_at"] = data.get("last_seen")
            info["in_db_before_check"] = True
            info["parsed_by_you"] = data.get("parsed_by_you", False)
            self._players[sid] = info

        in_db_results = []
        for sid in in_db_ids:
            info = self._players[sid]
            in_db_results.append({
                "steam_id": sid,
                "name": info.get("name") or sid,
                "team": info.get("team", ""),
                "inv_value": info.get("inv_value"),
                "top_items": [],
                "faceit": {},
                "country": "",
                "already_parsed": True,
                "in_db_before_check": True,
                "parsed_by_you": info.get("parsed_by_you", False),
                "updated_at": info.get("updated_at"),
            })
        self._in_db_results = in_db_results

        if not not_in_db_ids:
            self.ctrl.btn_check.setEnabled(True)
            self._apply_check_results(in_db_results)
            return

        self.ctrl.set_status(f"Парсим {len(not_in_db_ids)} чел...", "#ffd700")
        self.ctrl.btn_check.setEnabled(False)
        players_dict = {
            sid: {
                "name": self._players[sid].get("name") or sid,
                "team": self._players[sid].get("team", ""),
            }
            for sid in not_in_db_ids
        }
        self.worker = Worker(players_dict)
        self.worker.sig.finished.connect(self._on_done)
        self.worker.start()

    def _on_done(self, res):
        err = getattr(self.worker, "_last_error", None) if self.worker else None
        if err:
            self._cooldown_left = 20
            self.ctrl.btn_check.setEnabled(False)
            if hasattr(self, "_cooldown_timer"):
                self._cooldown_timer.stop()
                self._cooldown_timer.deleteLater()
            self._cooldown_timer = QTimer(self.ctrl)
            def _tick():
                self._cooldown_left -= 1
                if self._cooldown_left <= 0:
                    self.ctrl.set_status("Готово", "#94a3b8")
                    self._cooldown_timer.stop()
                else:
                    self.ctrl.set_status(f"Подождите и попробуйте через: {self._cooldown_left} сек.", "#ff8800")
            self._cooldown_timer.timeout.connect(_tick)
            self._cooldown_timer.start(1000)
            _tick()
            if self.worker:
                self.worker._last_error = None
            return

        merged = (self._in_db_results or []) + (res or [])
        self.ctrl.btn_check.setEnabled(True)
        self._apply_check_results(merged)

    def _apply_check_results(self, res):
        min_val = float(CFG.get("min_value") or 150)
        to_report = []

        for r in res:
            sid = str(r.get("steam_id") or "")
            if not sid:
                continue
            
            if not r.get("already_parsed") and r.get("inv_value") is not None:
                to_report.append({
                    "steam_id": sid,
                    "last_value": float(r["inv_value"]),
                    "name": str(r.get("name") or "") or None
                })
                
            info = self._players.get(sid) or {
                "steam_id": sid,
                "name": sid,
                "team": "",
                "inv_value": None,
                "checked": False,
                "in_list": False,
            }
            info["name"] = r.get("name") or info.get("name") or sid
            info["team"] = r.get("team", info.get("team", ""))
            info["inv_value"] = r.get("inv_value")
            info["checked"] = True
            if r.get("updated_at") is not None:
                info["updated_at"] = r.get("updated_at")
            info["in_db_before_check"] = r.get("in_db_before_check", False)
            if r.get("parsed_by_you") is not None:
                info["parsed_by_you"] = r.get("parsed_by_you")
            v = info["inv_value"]
            info["in_list"] = v is not None and float(v or 0) >= min_val
            self._players[sid] = info

        fat_players = []
        for sid, info in self._players.items():
            v = info.get("inv_value")
            if info.get("in_list") and v is not None and float(v or 0) >= min_val:
                fat_players.append({
                    "steam_id": sid,
                    "name": info.get("name") or sid,
                    "team": info.get("team", ""),
                    "inv_value": v,
                    "in_db_before_check": info.get("in_db_before_check", False),
                    "parsed_by_you": info.get("parsed_by_you", False),
                    "updated_at": info.get("updated_at"),
                })
        if fat_players:
            self.results_panel.set_results(fat_players)
        count = len(fat_players)
        if count >= 1:
            self.ctrl.set_status(f"Проверка завершена, проверено: {len(res)}", "#4cff4c")
            pos = self.ctrl.pos()
            self.results_panel.move(pos.x() + 340, pos.y())
            self.results_panel.show()
        else:
            self.ctrl.set_status("Inventories below threshold", "#4cff4c")

        if to_report:
            threading.Thread(target=report_parsed_batch_remote, args=(to_report,), daemon=True).start()

    def pick_steam_path(self):
        d = QFileDialog.getExistingDirectory()
        if d:
            CFG["cs2_path"] = d
            save_cfg(CFG)
            self._init_gsi()
    def set_faceit_key(self):
        k, ok = QInputDialog.getText(self.ctrl, "Faceit API", "Ключ:", text=CFG.get("faceit_api_key", ""))
        if ok: CFG["faceit_api_key"] = k; save_cfg(CFG)
    def show_license_dialog(self): ActivationDialog().exec_()

def run_app_with_existing_qapp():
    run_first_run_wizard_if_needed()
    App()


def main():
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    run_first_run_wizard_if_needed()
    App()
    sys.exit(qapp.exec_())


if __name__ == "__main__":
    main()