import os
import sys
import time
import PyQt5.QtWidgets
import PyQt5.QtCore
import PyQt5.QtGui

if getattr(sys, "frozen", False):
    _base = os.path.dirname(sys.executable)
else:
    _base = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
os.chdir(_base)
if _base not in sys.path:
    sys.path.insert(0, _base)


def _resource_path(relative_path):
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(_base, relative_path)


def _startup_error_path():
    if getattr(sys, "frozen", False):
        appdata = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CS2_Parser")
        try:
            os.makedirs(appdata, exist_ok=True)
            return os.path.join(appdata, "startup_error.txt")
        except Exception:
            pass
    return os.path.join(_base, "startup_error.txt")


def _show_startup_error(e):
    import traceback
    err_path = _startup_error_path()
    msg = str(e)
    try:
        with open(err_path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + " " + msg + "\n")
            traceback.print_exc(file=f)
    except Exception:
        pass
    try:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(
            None, "Ошибка запуска",
            "Не удалось запустить программу.\n\n" + msg + "\n\nПодробности: " + err_path,
        )
    except Exception:
        pass
    sys.exit(1)


def main():
    from PyQt5.QtWidgets import QSplashScreen, QApplication
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QPixmap

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    logo_path = _resource_path("assets/logo.png")
    if os.path.isfile(logo_path):
        pixmap = QPixmap(logo_path)
        if not pixmap.isNull():
            splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)
            splash.setMask(pixmap.mask() if not pixmap.mask().isNull() else pixmap.createHeuristicMask())
            splash.show()
            app.processEvents()

            def start_app():
                try:
                    splash.close()
                    import cs2_overlay
                    cs2_overlay.run_app_with_existing_qapp()
                except Exception as e:
                    _show_startup_error(e)

            QTimer.singleShot(1200, start_app)
            app.exec_()
            return

    try:
        import cs2_overlay
        cs2_overlay.main()
    except Exception as e:
        _show_startup_error(e)


if __name__ == "__main__":
    main()
