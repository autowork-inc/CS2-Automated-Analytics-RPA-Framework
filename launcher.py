import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(SCRIPT_DIR, "requirements.txt")


def main():
    os.chdir(SCRIPT_DIR)
    if not os.path.isfile(REQUIREMENTS):
        print("Файл requirements.txt не найден.")
        input("Нажмите Enter для выхода...")
        sys.exit(1)

    print("Проверка зависимостей...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS, "-q", "--disable-pip-version-check"],
            check=True,
            capture_output=False,
        )
    except subprocess.CalledProcessError as e:
        print("Ошибка установки зависимостей. Убедитесь, что Python и pip установлены.")
        input("Нажмите Enter для выхода...")
        sys.exit(e.returncode)
    except FileNotFoundError:
        print("Python не найден. Установите Python 3.8+ с https://www.python.org/")
        input("Нажмите Enter для выхода...")
        sys.exit(1)

    print("Запуск CS2 Inventory Parser...")
    sys.path.insert(0, SCRIPT_DIR)
    import cs2_overlay
    cs2_overlay.main()


if __name__ == "__main__":
    main()
