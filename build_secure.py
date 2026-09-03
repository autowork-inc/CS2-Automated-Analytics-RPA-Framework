import os
import re
import sys
import json
import shutil
import subprocess
import zipfile

def get_app_version():
    try:
        with open(os.path.join(SCRIPT_DIR, "cs2_overlay.py"), "r", encoding="utf-8") as f:
            content = f.read()
            match = re.search(r"APP_VERSION\s*=\s*([\d\.]+)", content)
            if match:
                return match.group(1)
    except Exception:
        pass
    return "unknown"

SCRIPT_DIR = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
DIST_EXE = os.path.join(SCRIPT_DIR, "dist", "CS2_Parser.exe")
RELEASE_DIR = os.path.join(SCRIPT_DIR, "release")
VERSION = get_app_version()
ZIP_NAME = f"cs2_parser_v{VERSION}.zip"
ZIP_PATH = os.path.join(RELEASE_DIR, ZIP_NAME)
ROOT_ENV = os.path.join(SCRIPT_DIR, ".env")
os.chdir(SCRIPT_DIR)



def clean_old_builds():
    print("🧹 [1/4] Очистка старых файлов сборки...")
    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            shutil.rmtree(folder, ignore_errors=True)
    if os.path.exists("CS2_Parser.spec"):
        os.remove("CS2_Parser.spec")

def obfuscate_code():
    print("🛡️ [2/4] Preparing core environment...")
    files_to_protect = ["launcher_exe.py", "core_security.py"]
    files_str = " ".join(files_to_protect)
    print("   📂 Копирование UI-скриптов...")
    shutil.copy2("cs2_overlay.py", os.path.join("cs2_overlay.py"))

def write_embedded_config():
    
    path = os.path.join(SCRIPT_DIR, "default_config.json")
    config = {
        "steamwebapi_key": "",
        "faceit_api_key": "",
        "steam_api_key": "",
        "min_value": 150,
        "gsi_port": 3000,
        "steam_path": "",
        "cs2_path": "",
        "license_server_url": get_license_server_url(),
        "license_key": "",
        "bring_on_top_hotkey": "Ctrl+Y",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    return path


HIDDEN_IMPORTS = [
    "PyQt5",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "PyQt5.sip",
    "cs2_overlay",   
    "requests",
]


def build_exe():
    print("📦 [3/4] Сборка .exe (PyInstaller)...")
    embedded_config_path = write_embedded_config()
    try:
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--onefile",
            "--windowed",
            "--clean",
            "--name", "CS2_Parser",
            "--paths",
            "--add-data", f"{embedded_config_path};.",
            "--add-data", os.path.join(SCRIPT_DIR, "assets", "logo.png") + ";assets",
        ]
        for mod in HIDDEN_IMPORTS:
            cmd.extend(["--hidden-import", mod])
        icon_path = os.path.abspath(os.path.join(SCRIPT_DIR, "assets", "favicon.ico"))
        if os.path.isfile(icon_path):
            cmd.extend(["--icon", icon_path])
            print("   🖼 Иконка: assets\\favicon.ico")
        else:
            print("   ⚠ Иконка не найдена: " + icon_path)
        if os.path.isfile(os.path.join(SCRIPT_DIR, "upx.exe")):
            print("   ✅ Найден upx.exe! Включаем сжатие...")
            cmd.extend(["--upx-dir", SCRIPT_DIR])
        else:
            print("   ⚠️ upx.exe не найден. Для сжатия закиньте upx.exe в корень проекта.")
        cmd.append(os.path.join("launcher_exe.py"))
        subprocess.run(cmd, check=True)
    finally:
        if os.path.isfile(embedded_config_path):
            os.remove(embedded_config_path)


def get_license_server_url():
   
    if os.path.isfile(ROOT_ENV):
        try:
            with open(ROOT_ENV, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("BACKEND_URL=") and "=" in line:
                        url = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if url:
                            return url.rstrip("/")
        except Exception:
            pass
    return "http://127.0.0.1:8000"


def create_release_zip():
    
    if not os.path.isfile(DIST_EXE):
        print("   ⚠ Пропуск архива: dist\\CS2_Parser.exe не найден.")
        return
    print("   📦 Создание релиз-архива...")
    os.makedirs(RELEASE_DIR, exist_ok=True)
    if os.path.isfile(ZIP_PATH):
        os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(DIST_EXE, "CS2_Parser.exe")
    print(f"   ✅ Архив: release\\{ZIP_NAME}")


def clean_all_except_release_zip():
    
    for folder in ["build", "dist"]:
        if os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
    if os.path.isfile(os.path.join(SCRIPT_DIR, "CS2_Parser.spec")):
        os.remove(os.path.join(SCRIPT_DIR, "CS2_Parser.spec"))
    if os.path.isdir(RELEASE_DIR):
        for name in os.listdir(RELEASE_DIR):
            if name != ZIP_NAME:
                path = os.path.join(RELEASE_DIR, name)
                if os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
    print("   🧹 Всё лишнее удалено. В release только архив.")


def finish():
    print("✅ [4/4] Готово!")
    if os.path.isfile(ZIP_PATH):
        zip_mb = os.path.getsize(ZIP_PATH) / (1024 * 1024)
        print(f"   📦 release\\{ZIP_NAME} ({zip_mb:.2f} МБ)")
        if zip_mb > 50:
            print("   ⚠ Размер > 50 МБ — бот не отправит архивом в чат, используйте ссылку.")

if __name__ == "__main__":
    try:
        clean_old_builds()
        obfuscate_code()
        build_exe()
        create_release_zip()
        clean_all_except_release_zip()
        finish()
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка во время сборки! Код ошибки: {e.returncode}")
        input("Нажмите Enter для выхода...")