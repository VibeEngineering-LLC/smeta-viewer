from __future__ import annotations
import sys
import pathlib
import pytest
import os

# Добавляем scripts в path для импорта build_lsr_fixture
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from build_lsr_fixture import build

from sv.io.lsr_xlsx import load, looks_like_lsr
from sv.model import SmetaFormat

@pytest.fixture
def fixture_path(tmp_path):
    path = tmp_path / "lsr_fixture.xlsx"
    build(str(path))
    return str(path)

def test_detects_as_lsr(fixture_path):
    """Проверяет, что файл распознается как ЛСР."""
    assert looks_like_lsr(fixture_path) is True

def test_format_tag(fixture_path):
    """Проверяет, что формат файла установлен корректно."""
    s = load(fixture_path)
    assert s.fmt == SmetaFormat.LSR_XLSX

def test_position_count(fixture_path):
    """Проверяет, что количество позиций в файле равно двум."""
    assert len(load(fixture_path).positions) == 2

def test_first_position_fields(fixture_path):
    """Проверяет поля первой позиции: код, количество и итоговая сумма."""
    p = load(fixture_path).positions[0]
    assert p.code == "ФЕР08-01-001-01"
    assert p.qty == 10
    assert round(p.total_current, 2) == 1500.0

def test_second_position_no_resource_leak(fixture_path):
    """Проверяет, что ресурсы первой позиции не «утекли» во вторую."""
    p = load(fixture_path).positions[1]
    assert p.resources.is_empty()

def test_resources_of_first_position(fixture_path):
    """Проверяет корректность ресурсов в первой позиции."""
    rows = load(fixture_path).positions[0].resources.rows()
    d = {label: (base, current) for label, base, current in rows}
    assert abs(d["Зарплата"][1] - 200.0) < 0.01
    assert abs(d["Накладные расходы"][1] - 250.0) < 0.01
    assert abs(d["Сметная прибыль"][1] - 150.0) < 0.01

def test_header_totals_converted_to_rubles(fixture_path):
    """Проверяет корректный перевод итогов из тысяч рублей в рубли."""
    t = load(fixture_path).totals
    assert abs(t.total_current - 1234500.0) < 1.0

def test_warns_about_vat_discrepancy(fixture_path):
    """Проверяет наличие предупреждения о несоответствии НДС."""
    s = load(fixture_path)
    assert any("НДС" in w for w in s.warnings)

def test_negative_detection_on_other_format():
    """Проверяет, что другой формат не распознается как ЛСР."""
    path = os.environ.get("SMETA_VIEWER_XLSX")
    if not path:
        pytest.skip("SMETA_VIEWER_XLSX не задана — эталон формы Смета.РУ недоступен")
    assert looks_like_lsr(path) is False
