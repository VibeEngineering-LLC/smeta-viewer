"""#SMETA-1: точка входа просмотрщика смет. Запуск: py -3.14 -m sv [файл ...]"""
import sys

from PySide6 import QtWidgets

from sv.ui.main_window import MainWindow


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    for path in sys.argv[1:]:
        w.open_file(path)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
