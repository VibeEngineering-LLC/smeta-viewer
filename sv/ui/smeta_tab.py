"""#SMETA-1: вкладка одного сметного документа.

Слева — навигация по разделам, в центре — дерево «Раздел → Подраздел → Позиция →
ресурсные строки», снизу — итоги и контроль расхождения.

Контроль расхождения: сумма позиций сверяется с итогом,
записанным в документе. Для формы Смета.РУ норма — копейки (округление шапки до
тысяч — расхождение в копейки на миллионы). Молча рисовать таблицу при большом
расхождении нельзя — это деньги.
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from sv.model import Smeta, SmetaFormat
from sv.ui import theme
from sv.ui.tree_model import (COL_CODE, COL_CURRENT, COL_NAME, COLUMNS,
                              KIND_POSITION, KIND_RESOURCE,
                              SmetaTreeModel, fmt_money)


class SmetaTab(QtWidgets.QWidget):
    selectionSummary = QtCore.Signal(str)

    def __init__(self, smeta: Smeta, parent=None):
        super().__init__(parent)
        self.smeta = smeta

        # 1. Верхняя строка
        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText("Поиск по шифру и наименованию")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)

        self._search_info = QtWidgets.QLabel()

        self._only_fer = QtWidgets.QCheckBox("только расценки")
        self._only_fer.stateChanged.connect(self._apply_filters)

        self._hide_res = QtWidgets.QCheckBox("без ресурсных строк")
        self._hide_res.stateChanged.connect(self._apply_filters)

        top_layout = QtWidgets.QHBoxLayout()
        top_layout.addWidget(self._search)
        top_layout.addWidget(self._search_info)
        top_layout.addWidget(self._only_fer)
        top_layout.addWidget(self._hide_res)
        top_layout.addStretch()

        # 2. Плашка контроля
        self._check_label = QtWidgets.QLabel()
        self._check_label.setWordWrap(True)
        self._check_label.setContentsMargins(4, 4, 4, 4)

        # 3. Центральная часть
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # Слева навигация
        self._nav = QtWidgets.QTreeWidget()
        self._nav.setHeaderHidden(True)
        self._nav.setMinimumWidth(180)
        self._nav.itemClicked.connect(self._on_nav_clicked)

        sections = list(smeta.sections())
        for section in sections:
            sec_item = QtWidgets.QTreeWidgetItem([section.name])
            sec_item.setData(0, QtCore.Qt.UserRole, (section.name, ""))
            self._nav.addTopLevelItem(sec_item)
            for subsection in section.subsections:
                sub_item = QtWidgets.QTreeWidgetItem([subsection])
                sub_item.setData(0, QtCore.Qt.UserRole, (section.name, subsection))
                sec_item.addChild(sub_item)

        # Справа дерево позиций
        self._view = QtWidgets.QTreeView()
        self._model = SmetaTreeModel(smeta)
        self._view.setModel(self._model)
        self._view.setAlternatingRowColors(True)
        self._view.setUniformRowHeights(True)
        self._view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        header = self._view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, QtWidgets.QHeaderView.Stretch)
        for i in range(len(COLUMNS)):
            if i != COL_NAME:
                header.setSectionResizeMode(i, QtWidgets.QHeaderView.ResizeToContents)

        self._view.selectionModel().selectionChanged.connect(self._on_selection)

        splitter.addWidget(self._nav)
        splitter.addWidget(self._view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # 4. Панель итогов
        self._totals = QtWidgets.QTableWidget()
        self._totals.verticalHeader().setVisible(False)
        self._totals.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._totals.horizontalHeader().setStretchLastSection(True)
        self._totals.setMaximumHeight(190)

        totals_data = smeta.totals.rows()
        rows = len(totals_data) + 1
        self._totals.setRowCount(rows)
        self._totals.setColumnCount(3)
        self._totals.setHorizontalHeaderLabels(["Показатель", "В базисных ценах", "В текущих ценах"])

        # Добавляем строку суммы позиций
        base_sum, current_sum = smeta.sum_positions_base(), smeta.sum_positions_current()
        self._totals.setItem(0, 0, QtWidgets.QTableWidgetItem("Сумма позиций"))
        self._totals.setItem(0, 1, QtWidgets.QTableWidgetItem(fmt_money(base_sum)))
        self._totals.setItem(0, 2, QtWidgets.QTableWidgetItem(fmt_money(current_sum)))

        # Totals.rows() отдаёт КОРТЕЖИ (подпись, базис, текущая), а не объекты с полями.
        for i, (label, base, current) in enumerate(totals_data):
            self._totals.setItem(i + 1, 0, QtWidgets.QTableWidgetItem(label))
            self._totals.setItem(i + 1, 1, QtWidgets.QTableWidgetItem(fmt_money(base)))
            self._totals.setItem(i + 1, 2, QtWidgets.QTableWidgetItem(fmt_money(current)))

        # Выравнивание числовых колонок
        for i in range(1, rows):
            for j in range(1, 3):
                item = self._totals.item(i, j)
                if item:
                    item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        # 5. Укладка
        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(top_layout)
        # Плашка контроля не должна растягиваться: без явного stretch она забирала
        # свободное место и между ней и таблицей зияла пустота в пол-экрана.
        self._check_label.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                                        QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self._check_label, 0)
        layout.addWidget(splitter, 1)      # всё свободное место — таблице
        layout.addWidget(self._totals, 0)
        self.setLayout(layout)

        self._update_check()

    def _update_check(self):
        s = self.smeta
        declared = s.totals.total_current
        actual = s.sum_positions_current()
        if s.fmt == SmetaFormat.LSR_XLSX and declared is not None:
            # #SMETA-6: у входящей ЛСР итог шапки уже включает лимитированные
            # затраты и НДС, а сумма позиций — нет. Расхождение 15-25% здесь
            # НОРМА, а не ошибка; применять к нему тот же порог, что и для
            # Смета.РУ (копейки), значило бы красить документ красным каждый
            # раз без исключения — постоянная ложная тревога хуже отсутствия
            # проверки.
            text = (f"Сумма позиций: {fmt_money(actual)} ₽. "
                    f"Итог шапки: {fmt_money(declared)} ₽ (включает лимитированные "
                    f"затраты и НДС — сравнение с суммой позиций не показательно).")
            color = theme.c("warn")
        elif declared is None:
            # Формат не хранит итог документа (.sobx, .arp) либо строка итога не
            # найдена. Показываем посчитанную сумму и прямо говорим, что сверять
            # не с чем — молчаливая зелёная «норма» здесь была бы обманом.
            text = (f"Сумма позиций: {fmt_money(actual)} ₽. "
                    f"Итог документа в файле не хранится — сверить не с чем.")
            color = theme.c("warn")
        else:
            diff = abs(actual - declared)
            pct = diff / declared * 100 if declared else 0
            if diff <= 1.0 or pct < 0.01:
                text = f"Сверка: сумма позиций {fmt_money(actual)} ₽, итог документа {fmt_money(declared)} ₽ — расхождение {fmt_money(diff)} ₽ (округление, норма)"
                color = theme.c("ok")
            else:
                text = f"ВНИМАНИЕ: расхождение {fmt_money(diff)} ₽ ({pct:.2f} %) между суммой позиций и итогом документа"
                color = theme.c("error")

        if s.warnings:
            text += " · " + " · ".join(s.warnings)

        self._check_label.setStyleSheet(f"color: {color}; padding: 4px;")
        self._check_label.setText(text)

    def _on_search(self, text):
        if not text:
            self._search_info.setText("")
            return

        positions = self._model.positions()
        n = 0
        for pos in positions:
            if (text.casefold() in pos.code.casefold() or
                text.casefold() in pos.name.casefold()):
                n += 1

        self._search_info.setText(f"совпадений: {n}")

        idx = self._model.index_of_first_match(text)
        if idx.isValid():
            self._view.setCurrentIndex(idx)
            self._view.scrollTo(idx, QtWidgets.QAbstractItemView.PositionAtCenter)
            parent = idx.parent()
            while parent.isValid():
                self._view.expand(parent)
                parent = parent.parent()

    def _apply_filters(self):
        """Фильтры показа: прячем строки, а не перестраиваем модель.

        Прежняя версия вызывала несуществующие методы (row_of_position у модели,
        is_resource_row у позиции), падала прямо в Qt-слоте и потому просто
        ничего не делала; снятие галки тоже ничего не возвращало, потому что
        setRowHidden(..., False) не вызывался нигде. Обходим дерево целиком:
        позиции лежат на 2-3 уровне, индекс от корня для них не годится.
        """
        only_fer = self._only_fer.isChecked()
        hide_res = self._hide_res.isChecked()
        m = self._model

        def walk(parent):
            for r in range(m.rowCount(parent)):
                idx = m.index(r, 0, parent)
                node = m.node_at(idx)
                hidden = False
                if node is not None:
                    if hide_res and node.kind == KIND_RESOURCE:
                        hidden = True
                    elif (only_fer and node.kind == KIND_POSITION
                          and node.payload is not None and node.payload.is_price_item()):
                        hidden = True
                self._view.setRowHidden(r, parent, hidden)
                if not hidden:
                    walk(idx)

        walk(QtCore.QModelIndex())

    def _on_nav_clicked(self, item, column):
        sec, sub = item.data(0, QtCore.Qt.UserRole)
        idx = self._model.index_of_section(sec, sub)
        if idx.isValid():
            self._view.setCurrentIndex(idx)
            self._view.scrollTo(idx, QtWidgets.QAbstractItemView.PositionAtTop)
            self._view.expand(idx)

    def _on_selection(self):
        """#SMETA-3: сумма по выделенным позициям.

        Прежняя версия считала по НОМЕРАМ строк диапазона и передавала int туда,
        где нужен QModelIndex: position_at(row) падал с AttributeError в слоте,
        и статусбар всегда оставался пустым. Идём по selectedRows() —
        это индексы, уникальные по строкам, из любых веток дерева.
        """
        total = 0.0
        seen = set()
        for idx in self._view.selectionModel().selectedRows():
            pos = self._model.position_at(idx)
            if pos is None or id(pos) in seen:
                continue
            seen.add(id(pos))
            total += pos.total_current or 0.0
        n = len(seen)
        if n > 0:
            text = f"выделено позиций: {n}, сумма: {fmt_money(total)} ₽"
        else:
            text = ""
        self.selectionSummary.emit(text)

    def expand_all(self):
        self._view.expandAll()
        self._view.resizeColumnToContents(COL_CODE)

    def collapse_all(self):
        self._view.collapseAll()
