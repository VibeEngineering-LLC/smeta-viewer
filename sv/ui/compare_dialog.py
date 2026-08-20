"""#SMETA-5: окно сравнения двух открытых смет.

Сравниваются документы, уже открытые во вкладках: выбор — двумя выпадающими
списками. Результат — таблица «что произошло / разница в деньгах / позиция»,
отсортированная так, что дорогие расхождения сверху.
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from sv.compare import compare, format_report
from sv.model import Smeta
from sv.ui import theme
from sv.ui.tree_model import fmt_money, fmt_qty


class CompareDialog(QtWidgets.QDialog):
    def __init__(self, smetas: list[Smeta], parent=None):
        super().__init__(parent)
        self._smetas = smetas
        self._res = None

        self.setWindowTitle("Сравнение смет")
        self.resize(1180, 760)
        self.setSizeGripEnabled(True)

        # Выбор документов
        layout = QtWidgets.QVBoxLayout(self)

        combo_layout = QtWidgets.QHBoxLayout()
        combo_layout.addWidget(QtWidgets.QLabel("Было:"))
        self._left = QtWidgets.QComboBox()
        combo_layout.addWidget(self._left)
        combo_layout.addWidget(QtWidgets.QLabel("Стало:"))
        self._right = QtWidgets.QComboBox()
        combo_layout.addWidget(self._right)
        self._btn = QtWidgets.QPushButton("Сравнить")
        self._btn.clicked.connect(self._run)
        combo_layout.addWidget(self._btn)
        self._btn_save = QtWidgets.QPushButton("Сохранить отчёт…")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._save)
        combo_layout.addWidget(self._btn_save)
        layout.addLayout(combo_layout)

        # Сводка
        self._summary = QtWidgets.QLabel()
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        # Таблица результатов
        self._table = QtWidgets.QTableWidget()
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(False)
        layout.addWidget(self._table)

        # Заполнение комбобоксов
        for smeta in smetas:
            self._left.addItem(smeta.title())
            self._right.addItem(smeta.title())

        if len(smetas) >= 2:
            self._right.setCurrentIndex(1)
        else:
            self._summary.setText("Нужно открыть хотя бы две сметы")
            self._btn.setEnabled(False)

    def _run(self):
        left_idx = self._left.currentIndex()
        right_idx = self._right.currentIndex()

        if left_idx == right_idx:
            self._summary.setText("Выбран один и тот же документ")
            return

        left = self._smetas[left_idx]
        right = self._smetas[right_idx]

        res = compare(left, right)

        # Сводка
        summary_text = (
            f"совпало: {res.unchanged_count} · "
            f"удалено: {len(res.removed())} · "
            f"добавлено: {len(res.added())} · "
            f"изменено: {len(res.changed())}\n"
            f"итог: {fmt_money(res.left_total)} ₽ → "
            f"{fmt_money(res.right_total)} ₽, разница {fmt_money(res.delta_total())} ₽"
        )
        self._summary.setText(summary_text)

        # Таблица
        self._table.clear()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["Что", "Разница, ₽", "Раздел", "Шифр", "Наименование", "Было", "Стало"]
        )
        self._table.setRowCount(len(res.changes))

        for i, ch in enumerate(res.changes):
            kind = ch.kind
            # kind — служебный код модели; в таблицу идёт русская подпись
            kind_ru = {"removed": "удалено", "added": "добавлено",
                       "changed": "изменено"}.get(kind, kind)
            item = QtWidgets.QTableWidgetItem(kind_ru)
            self._table.setItem(i, 0, item)

            # Разница, ₽
            diff_item = QtWidgets.QTableWidgetItem(fmt_money(ch.delta()))
            diff_item.setTextAlignment(QtCore.Qt.AlignRight)
            self._table.setItem(i, 1, diff_item)

            # Раздел
            # У Change нет методов доступа к полям позиции — берём саму позицию:
            # right для добавленных и изменённых, left для удалённых.
            pos = ch.right if ch.right is not None else ch.left
            section = pos.section if pos else ""
            item = QtWidgets.QTableWidgetItem(section)
            self._table.setItem(i, 2, item)

            # Шифр и наименование
            item = QtWidgets.QTableWidgetItem(pos.code if pos else "")
            self._table.setItem(i, 3, item)

            name = pos.name if pos else ""
            if kind == "changed":
                name += f" (изменено: {', '.join(ch.fields)})"
            item = QtWidgets.QTableWidgetItem(name)
            self._table.setItem(i, 4, item)

            # Было / Стало
            if kind == "changed":
                left_total = fmt_money(ch.left.total_current)
                right_total = fmt_money(ch.right.total_current)
                item = QtWidgets.QTableWidgetItem(left_total)
                self._table.setItem(i, 5, item)
                item = QtWidgets.QTableWidgetItem(right_total)
                self._table.setItem(i, 6, item)
            elif kind == "removed":
                item = QtWidgets.QTableWidgetItem(fmt_money(ch.left.total_current))
                self._table.setItem(i, 5, item)
            elif kind == "added":
                item = QtWidgets.QTableWidgetItem(fmt_money(ch.right.total_current))
                self._table.setItem(i, 6, item)

            # Цвет строки
            color = None
            if kind == "removed":
                color = theme.c("error")
            elif kind == "added":
                color = theme.c("ok")
            elif kind == "changed":
                color = theme.c("warn")

            if color:
                # QBrush требует QColor, а не строку "#rrggbb".
                brush = QtGui.QBrush(QtGui.QColor(color))
                for col in range(7):
                    item = self._table.item(i, col)
                    # У удалённой позиции пуста колонка «Стало», у добавленной —
                    # «Было»: там ячейки нет вовсе, и обращение к ней падало.
                    if item is not None:
                        item.setForeground(brush)

        # Настройка ширины колонок
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch)  # Наименование
        for i in range(7):
            if i != 4:
                header.setSectionResizeMode(i, QtWidgets.QHeaderView.ResizeToContents)

        self._res = res
        self._btn_save.setEnabled(True)

    def _save(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Сохранить отчёт", "", "Текстовый отчёт (*.txt)"
        )
        if not filename:
            return

        left_idx = self._left.currentIndex()
        right_idx = self._right.currentIndex()
        left_title = self._smetas[left_idx].title()
        right_title = self._smetas[right_idx].title()

        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(format_report(self._res, left_title, right_title))
            QtWidgets.QMessageBox.information(
                self, "Сохранено", f"Отчёт сохранён в {filename}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Ошибка", f"Не удалось сохранить файл:\n{str(e)}"
            )
