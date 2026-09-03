import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
ROOT_ENV = os.path.join(SCRIPT_DIR, ".env")

ENV_KEYS = [
    "PARSER_ADMIN_SECRET",
    "PARSER_MOD_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "BACKEND_URL",
    "ADMIN_TELEGRAM_ID",
    "DOWNLOAD_URL",
    "PAYMENT_LINK",
    "STEAMWEBAPI_KEYS",
]


def _parse_env(path):
    out = {}
    if not os.path.isfile(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


def _write_env(path, data):
    if not data:
        return False
    try:
        lines = [f"{k}={v}" for k, v in data.items() if v is not None and str(v).strip() != ""]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except Exception:
        return False


def check_python():
    if sys.version_info < (3, 8):
        print("Требуется Python 3.8 или новее. Сейчас:", sys.version)
        return False
    return True


def ensure_config():
    cfg = _parse_env(ROOT_ENV)
    for k in ENV_KEYS:
        if k not in cfg:
            cfg[k] = ""
    if not cfg.get("BACKEND_URL"):
        cfg["BACKEND_URL"] = "http://127.0.0.1:8000"

    if (cfg.get("PARSER_ADMIN_SECRET") or "").strip():
        return cfg

    print("Файл .env не найден или пароль админа пуст. Заполним настройки сейчас.\n")
    try:
        cfg["PARSER_ADMIN_SECRET"] = input("Пароль админа (PARSER_ADMIN_SECRET): ").strip()
        cfg["PARSER_MOD_SECRET"] = (input("Пароль модератора (PARSER_MOD_SECRET, Enter = пусто): ").strip() or "").strip()
        cfg["TELEGRAM_BOT_TOKEN"] = input("Токен Telegram-бота (от @BotFather): ").strip()
        cfg["ADMIN_TELEGRAM_ID"] = input("Ваш Telegram ID (число): ").strip() or "7293801956"
        cfg["DOWNLOAD_URL"] = input("Ссылка на скачивание софта (можно позже): ").strip()
        cfg["PAYMENT_LINK"] = input("Ссылка «Оплатить подписку» (например https://t.me/ник): ").strip() or "https://t.me/wellstreet"
        cfg["BACKEND_URL"] = (input("URL backend (Enter = http://127.0.0.1:8000): ").strip() or "http://127.0.0.1:8000").rstrip("/")
        cfg["STEAMWEBAPI_KEYS"] = input("Ключи Steam Web API через запятую (можно позже): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nПрервано.")
        return None

    if not (cfg.get("PARSER_ADMIN_SECRET") or "").strip():
        print("Пароль админа обязателен. Создайте .env в корне и заполните PARSER_ADMIN_SECRET.")
        return None

    if _write_env(ROOT_ENV, cfg):
        print("Сохранено в .env (один файл для backend и бота)")
    else:
        print("Не удалось сохранить .env")
        return None
    return cfg


def install_deps():
    req_path = os.path.join(SCRIPT_DIR, "requirements_server.txt")
    if not os.path.isfile(req_path):
        print("Файл requirements_server.txt не найден.")
        return False
    print("Установка серверных зависимостей...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", req_path, "-q", "--disable-pip-version-check"],
            check=True,
            cwd=SCRIPT_DIR,
        )
        print("Зависимости установлены.")
        return True
    except subprocess.CalledProcessError as e:
        print("Ошибка установки:", e)
        return False


def run_backend():
    backend_dir = os.path.join(SCRIPT_DIR, "backend")
    cmd = [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
    if sys.platform == "win32":
        subprocess.Popen(
            cmd,
            cwd=backend_dir,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(cmd, cwd=backend_dir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Backend запущен в отдельном окне (порт 8000).")


def run_bot():
    bot_dir = os.path.join(SCRIPT_DIR, "bot")
    cmd = [sys.executable, "bot.py"]
    if sys.platform == "win32":
        subprocess.Popen(
            cmd,
            cwd=bot_dir,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(cmd, cwd=bot_dir, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Бот запущен в отдельном окне.")


def main():
    os.chdir(SCRIPT_DIR)
    print("=== Настройка сервера CS2 Parser ===\n")

    if not check_python():
        input("Нажмите Enter для выхода...")
        sys.exit(1)

    cfg = ensure_config()
    if not cfg:
        input("Нажмите Enter для выхода...")
        sys.exit(1)

    if not install_deps():
        input("Нажмите Enter для выхода...")
        sys.exit(1)

    print("\nНастройка завершена. Backend и бот читают один файл .env в корне проекта.")
    try:
        q = input("Запустить backend и бота сейчас? (y/n): ").strip().lower()
        if q in ("y", "yes", "д", "да"):
            run_backend()
            import time
            time.sleep(2)
            run_bot()
            print("Готово. Оба окна можно закрыть для остановки.")
    except (EOFError, KeyboardInterrupt):
        pass

    input("\nНажмите Enter для выхода...")


if __name__ == "__main__":
    main()
