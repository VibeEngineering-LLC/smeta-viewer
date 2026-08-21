"""Тесты модели сметы (#SMETA-8, регрессия P-011)."""
from __future__ import annotations

from sv.model import Position, Smeta


def _smeta_with_repeated_subsection() -> Smeta:
    """Подраздел с одним именем в ДВУХ разделах — реальный случай эталона."""
    return Smeta(positions=[
        Position(name="a", section="Холодоснабжение", subsection="Узел П6"),
        Position(name="b", section="Теплоснабжение", subsection="Узел П6"),
        Position(name="c", section="Теплоснабжение", subsection="Узел П7"),
    ])


def test_repeated_subsection_kept_in_both_sections():
    """Одноимённый подраздел обязан попасть в ОБА раздела.

    Глобальное множество имён теряло его во втором разделе: подраздел исчезал
    из навигации, а в генераторе .sobx его позиции сваливались в раздел.
    """
    by_name = {s.name: s for s in _smeta_with_repeated_subsection().sections()}
    assert by_name["Холодоснабжение"].subsections == ["Узел П6"]
    assert by_name["Теплоснабжение"].subsections == ["Узел П6", "Узел П7"]


def test_subsection_not_duplicated_within_section():
    """Повтор внутри ОДНОГО раздела в список дважды не попадает."""
    s = Smeta(positions=[
        Position(name="a", section="Р", subsection="П"),
        Position(name="b", section="Р", subsection="П"),
    ])
    assert s.sections()[0].subsections == ["П"]
