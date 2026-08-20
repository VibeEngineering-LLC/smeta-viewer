from __future__ import annotations
import os
import pytest
from sv.io.smetaru_xlsx import load
from sv.model import SmetaFormat

ENV_VAR = "SMETA_VIEWER_XLSX"


@pytest.fixture(scope="module")
def smeta():
    path = os.environ.get(ENV_VAR, "")
    if not path or not os.path.exists(path):
        pytest.skip(f"путь к смете не задан: переменная {ENV_VAR}")
    return load(path)


def test_positions_found(smeta):
    """Проверяет, что позиции загружены."""
    assert len(smeta.positions) > 0


def test_format_tag(smeta):
    """Проверяет, что формат сметы корректен."""
    assert smeta.fmt == SmetaFormat.SMETARU_XLSX


def test_sections_present(smeta):
    """Проверяет, что секции присутствуют."""
    assert smeta.section_count() > 0


def test_header_total_is_in_rubles(smeta):
    """Шапка печатается в ТЫСЯЧАХ, загрузчик обязан перевести в рубли.
    
    Признак потерянного перевода — итог меньше суммы позиций примерно в 1000 раз.
    """
    declared = smeta.totals.total_current
    if declared is None:
        pytest.skip("в шапке нет строки «Сметная стоимость»")
    actual = smeta.sum_positions_current()
    assert declared > actual / 10, "тысячи не переведены в рубли"


def test_sum_matches_declared_total(smeta):
    """Норма для формы — расхождение в копейки, шапка округлена до тысяч.
    
    Порог относительный, чтобы не зависеть от размера сметы.
    """
    declared = smeta.totals.total_current
    if declared is None:
        pytest.skip("в шапке нет строки «Сметная стоимость»")
    actual = smeta.sum_positions_current()
    diff = abs(actual - declared)
    assert diff <= max(1.0, declared * 0.0001), f"расхождение {diff}"


def test_money_fields_are_numeric(smeta):
    """Колонка G двузначна — в строке позиции это коэффициент-выражение
    вида ")*1,22", в строке итога базисная стоимость; при чтении её как текста в
    модель попадала строка и `sum_positions_base()` падал с TypeError.
    """
    for p in smeta.positions:
        if p.total_base is not None:
            assert isinstance(p.total_base, float)
        if p.total_current is not None:
            assert isinstance(p.total_current, float)


def test_sum_base_is_computable(smeta):
    """Проверяет, что сумма базисных стоимостей вычисляется."""
    v = smeta.sum_positions_base()
    assert isinstance(v, float)


def test_resources_parsed(smeta):
    """Проверяет, что ресурсы загружены."""
    assert any(not p.resources.is_empty() for p in smeta.positions)


def test_first_position_filled(smeta):
    """Проверяет, что первая позиция заполнена."""
    p = smeta.positions[0]
    assert p.name
    assert p.unit
    assert p.qty is not None
