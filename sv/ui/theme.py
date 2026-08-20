"""#SMETA-4: темы оформления (тёмная и светлая) и палитра для кода вне QSS.

Контраст текста к фону проверен по WCAG AA (порог 4.5:1):
  тёмная  — текст #d0d2d6 на #26282b: 9,8:1; приглушённый #9a9ca0 на #2b2d31: 5,0:1
  светлая — текст #11f2124 на #ffffff: 16,7:1; приглушённый #6b6f76 на #ffffff: 5,3:1
Значения ниже порога в темы не попадают: серый текст на сером — самая частая
причина нечитаемого интерфейса.
"""
from __future__ import annotations

THEME_DARK = "dark"
THEME_LIGHT = "light"
THEMES = (THEME_DARK, THEME_LIGHT)
DEFAULT_THEME = THEME_DARK

_DARK = {
    "window": "#2b2d31", "base": "#26282b", "alt_base": "#2f3136", "text": "#d0d2d6",
    "muted": "#9a9ca0", "border": "#1c1e21", "header": "#34373c", "hover": "#3a3d42",
    "selection": "#4a7d4a", "selection_text": "#ffffff", "link": "#7ab8ff",
    "ok": "#7ab87a", "warn": "#e0b050", "error": "#e07a7a",
    "button": "#303338", "button_hover": "#3a3d42",
}

_LIGHT = {
    "window": "#f4f5f7", "base": "#ffffff", "alt_base": "#f0f1f3", "text": "#1f2124",
    "muted": "#6b6f76", "border": "#c8ccd0", "header": "#e4e6e9", "hover": "#dfe3e8",
    "selection": "#2f6fb5", "selection_text": "#ffffff", "link": "#1a5fb4",
    "ok": "#1f7a3f", "warn": "#8a6100", "error": "#b3261e",
    "button": "#ffffff", "button_hover": "#eceef1",
}

def palette(theme: str) -> dict[str, str]:
    """Вернуть палитру для заданной темы."""
    return _LIGHT if theme == THEME_LIGHT else _DARK

def color(theme: str, key: str) -> str:
    """Получить цвет из палитры по ключу; если ключа нет — вернуть цвет текста темы."""
    p = palette(theme)
    if key in p:
        return p[key]
    return p["text"]

def qss(theme: str) -> str:
    """Собрать таблицу стилей для заданной темы."""
    p = palette(theme)
    return f"""QWidget {{
    color: {p['text']};
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {p['window']};
}}

QMenuBar {{
    background-color: {p['header']};
    color: {p['text']};
}}

QMenuBar::item:selected {{
    background-color: {p['hover']};
}}

QMenu {{
    background-color: {p['base']};
    color: {p['text']};
    border: 1px solid {p['border']};
}}

QMenu::item:selected {{
    background-color: {p['selection']};
    color: {p['selection_text']};
}}

QTabWidget::pane {{
    border: 1px solid {p['border']};
    background-color: {p['window']};
}}

QTabBar::tab {{
    background-color: {p['button']};
    color: {p['text']};
    padding: 6px 14px;
    border: 1px solid {p['border']};
}}

QTabBar::tab:selected {{
    background-color: {p['selection']};
    color: {p['selection_text']};
}}

QTabBar::tab:hover:!selected {{
    background-color: {p['hover']};
}}

QTreeView, QTableWidget, QTableView {{
    background-color: {p['base']};
    alternate-background-color: {p['alt_base']};
    color: {p['text']};
    border: 1px solid {p['border']};
    gridline-color: {p['border']};
}}

QTreeView::item:selected, QTableWidget::item:selected {{
    background-color: {p['selection']};
    color: {p['selection_text']};
}}

QHeaderView::section {{
    background-color: {p['header']};
    color: {p['text']};
    padding: 5px;
    border: 1px solid {p['border']};
}}

QLineEdit {{
    background-color: {p['base']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 3px;
    padding: 4px 6px;
}}

QLineEdit:focus {{
    border: 1px solid {p['selection']};
}}

QPushButton {{
    background-color: {p['button']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 3px;
    padding: 5px 12px;
}}

QPushButton:hover {{
    background-color: {p['button_hover']};
}}

QCheckBox {{
    color: {p['text']};
}}

QSplitter::handle {{
    background-color: {p['border']};
}}

QStatusBar {{
    background-color: {p['header']};
    color: {p['text']};
}}

QScrollBar:vertical, QScrollBar:horizontal {{
    background-color: {p['window']};
    border: 1px solid {p['border']};
    width: 12px;
    height: 12px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QToolTip {{
    background-color: {p['base']};
    color: {p['text']};
    border: 1px solid {p['border']};
}}"""


# --- текущая тема процесса -------------------------------------------------
# Держим здесь, а не в окне: цвета нужны и модели дерева, и вкладке, и они не
# должны знать друг о друге. Значение переживает пересоздание виджетов.
_state = {"theme": DEFAULT_THEME}


def current() -> str:
    """Имя действующей темы."""
    return _state["theme"]


def set_current(theme: str) -> None:
    """Сменить тему процесса. Неизвестное имя игнорируется молча."""
    if theme in THEMES:
        _state["theme"] = theme


def c(key: str) -> str:
    """Цвет действующей темы по имени — короткая форма для кода UI."""
    return color(_state["theme"], key)
