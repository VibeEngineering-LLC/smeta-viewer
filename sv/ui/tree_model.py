"""#SMETA-1: модель дерева сметы для QTreeView.

Иерархия: Раздел → Подраздел → Позиция → ресурсные строки. На реальных сметах сотни позиций и тысячи ресурсных строк, поэтому дерево строится на QAbstractItemModel с узлами
_Node, а не на QTreeWidgetItem: виджет-элементы на таком объёме заметно тормозят.

Деньги форматируются с неразрывным пробелом между разрядами и двумя знаками; в
колонках чисел — выравнивание вправо, чтобы разряды читались столбиком.
"""
from __future__ import annotations

from PySide6 import QtCore, QtGui

from sv.model import Position, Smeta
from sv.ui import theme

COLUMNS = ["№", "Шифр", "Наименование", "Ед.изм.", "Кол-во",
           "Цена базисная", "Стоимость базисная", "Стоимость текущая", "Трудозатраты"]
COL_NUM, COL_CODE, COL_NAME, COL_UNIT, COL_QTY, COL_PRICE, COL_BASE, COL_CURRENT, COL_LABOR = range(9)
NUMERIC_COLUMNS = {COL_QTY, COL_PRICE, COL_BASE, COL_CURRENT, COL_LABOR}

KIND_SECTION = "section"
KIND_SUBSECTION = "subsection"
KIND_POSITION = "position"
KIND_RESOURCE = "resource"


def fmt_money(v: float | None) -> str:
    """Форматирует денежное значение."""
    if v is None or v == "":
        return ""
    s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return s


def fmt_qty(v: float | None) -> str:
    """Форматирует количественное значение."""
    if v is None:
        return ""
    if float(v).is_integer():
        return f"{int(v)}"
    return f"{v:g}".replace(".", ",")


class _Node:
    __slots__ = ("kind", "text", "payload", "parent", "children", "row")

    def __init__(self, kind: str, text: str, payload=None):
        self.kind = kind
        self.text = text
        self.payload = payload
        self.parent = None
        self.children = []
        self.row = -1

    def add(self, child):
        """Добавляет дочерний узел."""
        child.parent = self
        child.row = len(self.children)
        self.children.append(child)
        return child



def _subtree_sum(node, attr: str) -> float:
    """Сумма поля позиций по ВСЕМУ поддереву узла.

    У раздела прямые дети — подразделы, а не позиции: суммирование только по
    node.children давало разделу нулевой итог при непустых подразделах.
    None считается нулём (позиция без итоговой строки).
    """
    total = 0.0
    stack = list(node.children)
    while stack:
        n = stack.pop()
        if n.kind == KIND_POSITION and n.payload is not None:
            total += getattr(n.payload, attr) or 0.0
        else:
            stack.extend(n.children)
    return total

class SmetaTreeModel(QtCore.QAbstractItemModel):
    def __init__(self, smeta: Smeta | None = None, parent=None):
        super().__init__(parent)
        self._smeta = smeta
        self._root = _Node(KIND_SECTION, "root")
        if smeta is not None:
            self._build()

    def set_smeta(self, smeta):
        """Устанавливает смету и перестраивает модель."""
        self.beginResetModel()
        self._smeta = smeta
        self._root = _Node(KIND_SECTION, "root")
        if smeta is not None:
            self._build()
        self.endResetModel()

    def _build(self):
        """Строит дерево из сметы."""
        sections = list(self._smeta.sections())
        for section in sections:
            node_section = _Node(KIND_SECTION, section.name)
            self._root.add(node_section)

            subsections = {}
            positions = []
            for position in section.positions:
                if position.subsection:
                    if position.subsection not in subsections:
                        subsections[position.subsection] = _Node(KIND_SUBSECTION, position.subsection)
                        node_section.add(subsections[position.subsection])
                    target = subsections[position.subsection]
                else:
                    target = node_section
                node_position = _Node(KIND_POSITION, "", payload=position)
                target.add(node_position)
                positions.append(node_position)

            for pos_node in positions:
                position = pos_node.payload
                for row in position.resources.rows():
                    label, base, current = row
                    node_resource = _Node(KIND_RESOURCE, label, (label, base, current))
                    pos_node.add(node_resource)
                if position.note:
                    node_note = _Node(KIND_RESOURCE, "", (position.note, None, None))
                    pos_node.add(node_note)

    def index(self, row: int, column: int, parent=QtCore.QModelIndex()) -> QtCore.QModelIndex:
        """Возвращает индекс узла по строке и колонке."""
        if not self.hasIndex(row, column, parent):
            return QtCore.QModelIndex()
        node = parent.internalPointer() if parent.isValid() else self._root
        child = node.children[row]
        return self.createIndex(row, column, child)

    def parent(self, index: QtCore.QModelIndex) -> QtCore.QModelIndex:
        """Возвращает индекс родителя."""
        if not index.isValid():
            return QtCore.QModelIndex()
        node = index.internalPointer()
        if node.parent is self._root:
            return QtCore.QModelIndex()
        return self.createIndex(node.parent.row, 0, node.parent)

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        """Возвращает количество строк."""
        node = parent.internalPointer() if parent.isValid() else self._root
        return len(node.children)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        """Возвращает количество колонок."""
        return len(COLUMNS)

    def headerData(self, section: int, orientation: QtCore.Qt.Orientation, role: int = QtCore.Qt.DisplayRole):
        """Возвращает заголовки."""
        if orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole):
        """Возвращает данные для отображения."""
        if not index.isValid():
            return None
        node = index.internalPointer()
        col = index.column()

        if role == QtCore.Qt.DisplayRole:
            if node.kind in (KIND_SECTION, KIND_SUBSECTION):
                if col == COL_NAME:
                    return node.text
                elif col == COL_CURRENT:
                    return fmt_money(_subtree_sum(node, "total_current"))
                elif col == COL_BASE:
                    return fmt_money(_subtree_sum(node, "total_base"))
                else:
                    return ""
            elif node.kind == KIND_POSITION:
                p = node.payload
                if col == COL_NUM:
                    return p.num
                elif col == COL_CODE:
                    return p.code
                elif col == COL_NAME:
                    return p.name
                elif col == COL_UNIT:
                    return p.unit
                elif col == COL_QTY:
                    return fmt_qty(p.qty)
                elif col == COL_PRICE:
                    return fmt_money(p.price_base)
                elif col == COL_BASE:
                    return fmt_money(p.total_base)
                elif col == COL_CURRENT:
                    return fmt_money(p.total_current)
                elif col == COL_LABOR:
                    return fmt_qty(p.labor)
            elif node.kind == KIND_RESOURCE:
                label, base, current = node.payload
                if col == COL_NAME:
                    return label
                elif col == COL_BASE:
                    return fmt_money(base)
                elif col == COL_CURRENT:
                    return fmt_money(current)
                else:
                    return ""
        elif role == QtCore.Qt.TextAlignmentRole:
            if col in NUMERIC_COLUMNS:
                return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            else:
                return int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        elif role == QtCore.Qt.FontRole:
            if node.kind in (KIND_SECTION, KIND_SUBSECTION):
                font = QtGui.QFont()
                font.setBold(True)
                return font
            return None
        elif role == QtCore.Qt.ForegroundRole:
            if node.kind == KIND_RESOURCE:
                return QtGui.QColor(theme.c("muted"))
            return None
        elif role == QtCore.Qt.UserRole:
            return node
        return None

    def node_at(self, index) -> _Node | None:
        """Возвращает узел по индексу."""
        if not index.isValid():
            return None
        return index.internalPointer()

    def position_at(self, index) -> Position | None:
        """Возвращает позицию по индексу, если это позиция."""
        node = self.node_at(index)
        if node and node.kind == KIND_POSITION:
            return node.payload
        return None

    def positions(self) -> list[Position]:
        """Возвращает список всех позиций в порядке дерева."""
        result = []
        def traverse(node):
            if node.kind == KIND_POSITION:
                result.append(node.payload)
            for child in node.children:
                traverse(child)
        traverse(self._root)
        return result

    def index_of_section(self, section: str, subsection: str = "") -> QtCore.QModelIndex:
        """Индекс узла раздела, либо подраздела внутри него, по названию.

        #SMETA-3: навигация слева вызывала этот метод, а его в модели не было —
        клик молча падал в Qt-слоте, и панель выглядела нерабочей.
        """
        for i, sec in enumerate(self._root.children):
            if sec.text != section:
                continue
            sec_idx = self.createIndex(i, 0, sec)
            if not subsection:
                return sec_idx
            for j, sub in enumerate(sec.children):
                if sub.kind == KIND_SUBSECTION and sub.text == subsection:
                    return self.createIndex(j, 0, sub)
            return sec_idx
        return QtCore.QModelIndex()

    def index_of_first_match(self, text: str) -> QtCore.QModelIndex:
        """Возвращает индекс первой позиции, содержащей текст."""
        def search(node):
            if node.kind == KIND_POSITION:
                p = node.payload
                if (text.casefold() in p.code.casefold() or
                        text.casefold() in p.name.casefold()):
                    return self.createIndex(node.row, 0, node)
            for child in node.children:
                found = search(child)
                if found.isValid():
                    return found
            return QtCore.QModelIndex()
        return search(self._root)
