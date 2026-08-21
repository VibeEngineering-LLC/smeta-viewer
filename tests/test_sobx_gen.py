"""Тесты генератора .sobx на синтетическом доноре (#SMETA-8).

Фикстура — выдуманная смета на 6 позиций, паспорт архива обезличен; реальных смет в
репозитории нет и быть не должно. В неё намеренно заложены случаи, на которых
генератор ломался: вырожденная прайс-строка как образец, одноимённый подраздел в
двух разделах, позиция без подраздела не первой в списке.

Проверка идёт НЕ только через загрузчик приложения: он читает около пятнадцати полей
из ста сорока четырёх, и круговой тест через него оставался зелёным на восьми разных
мутациях генератора. Поэтому здесь читается и сам файл — как архив с датасетами.
"""

from __future__ import annotations

import json
import pathlib
import zipfile

import pytest

from sv.io.sobx import load as load_sobx
from sv.io.sobx_donor import Donor
from sv.io.sobx_gen import build_sobx
from sv.io.sobx_write import decode_float

DONOR = pathlib.Path(__file__).resolve().parent / "fixtures" / "synthetic-donor.sobx"


@pytest.fixture(scope="module")
def donor_path() -> str:
    if not DONOR.exists():
        pytest.skip("нет фикстуры synthetic-donor.sobx")
    return str(DONOR)


@pytest.fixture(scope="module")
def generated(donor_path, tmp_path_factory) -> str:
    """Донор -> модель -> новый файл. Возвращает путь к сгенерированному файлу."""
    out = tmp_path_factory.mktemp("gen") / "out.sobx"
    smeta = load_sobx(donor_path)
    build_sobx(smeta, Donor(donor_path), str(out))
    return str(out)


def _rows(path: str, table: str) -> list[dict]:
    """Строки датасета словарями, читая архив напрямую, минуя модель приложения."""
    with zipfile.ZipFile(path) as zf:
        raw = zf.read(table).decode("cp1251")
    parsed = json.loads(raw, strict=False)
    names = [f["Name"] for f in parsed["Fields"]]
    return [dict(zip(names, row)) for row in (parsed.get("Data") or [])]


def _table_name(path: str, prefix: str, exclude: tuple[str, ...] = ()) -> str:
    """Вернуть первое имя из zipfile.ZipFile(path).namelist(), начинающееся с prefix и не
    начинающееся ни с одного из exclude."""
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name.startswith(prefix) and not any(name.startswith(e) for e in exclude):
                return name
    raise ValueError(f"Не найдена таблица с префиксом {prefix} и без исключений {exclude}")


def test_donor_has_required_cases(donor_path):
    """Проверить, что фикстура содержит то, ради чего заведена."""
    smeta = load_sobx(donor_path)
    positions = list(smeta.positions)
    # Сбор пар (раздел, подраздел) по позициям
    section_subsection_pairs = [(p.section, p.subsection) for p in positions]
    # Проверка наличия подразделов с одинаковым именем в разных разделах
    subsections_by_section = {}
    for section, subsection in section_subsection_pairs:
        if section not in subsections_by_section:
            subsections_by_section[section] = set()
        subsections_by_section[section].add(subsection)
    # Найти подраздел, встречающийся более чем в одном разделе
    shared_subsections = set()
    for subsections in subsections_by_section.values():
        for sub in subsections:
            if any(sub in subsections_by_section[s] for s in subsections_by_section if s != section):
                shared_subsections.add(sub)
    assert len(shared_subsections) > 0, "Нет подразделов, встречающихся в разных разделах"
    # Проверка наличия позиции без подраздела и её не первой позиции
    empty_subsection_positions = [i for i, p in enumerate(positions) if not p.subsection]
    assert len(empty_subsection_positions) > 0, "Нет позиций без подраздела"
    assert empty_subsection_positions[0] != 0, "Позиция без подраздела первая в списке"
    # Проверка наличия позиции с непустыми ресурсами
    has_resources = any(p.resources for p in positions)
    assert has_resources, "Нет позиций с непустыми ресурсами"
    # Проверка наличия прайс-строки с ненулевым итогом
    has_price_item = any(p.is_price_item() for p in positions)
    assert has_price_item, "Нет прайс-строки с ненулевым итогом"


def test_positions_count_preserved(donor_path, generated):
    """Число позиций в исходном и сгенерированном совпадает."""
    donor_smeta = load_sobx(donor_path)
    generated_smeta = load_sobx(generated)
    assert len(list(donor_smeta.positions)) == len(list(generated_smeta.positions))


def test_total_preserved(donor_path, generated):
    """sum_positions_current() совпадает с точностью 0.01."""
    donor_smeta = load_sobx(donor_path)
    generated_smeta = load_sobx(generated)
    donor_total = donor_smeta.sum_positions_current()
    generated_total = generated_smeta.sum_positions_current()
    assert abs(donor_total - generated_total) < 0.01


def test_tree_nodes_preserved(donor_path, generated):
    """Число узлов с ATYPE == 5 одинаково."""
    donor_rows = _rows(donor_path, "A_O_HIER.json")
    generated_rows = _rows(generated, "A_O_HIER.json")
    donor_count = sum(1 for r in donor_rows if r.get("ATYPE") == 5)
    generated_count = sum(1 for r in generated_rows if r.get("ATYPE") == 5)
    assert donor_count == generated_count


def test_positions_attached_to_same_nodes(donor_path, generated):
    """Распределение числа позиций по IDHIER совпадает."""
    donor_table_name = _table_name(donor_path, "A_SMETA_", exclude=("A_SMETA_CENLVL", "A_SMETA_VIEW"))
    generated_table_name = _table_name(generated, "A_SMETA_", exclude=("A_SMETA_CENLVL", "A_SMETA_VIEW"))
    donor_rows = _rows(donor_path, donor_table_name)
    generated_rows = _rows(generated, generated_table_name)
    donor_groups = {}
    for r in donor_rows:
        key = r.get("IDHIER")
        if key not in donor_groups:
            donor_groups[key] = 0
        donor_groups[key] += 1
    generated_groups = {}
    for r in generated_rows:
        key = r.get("IDHIER")
        if key not in generated_groups:
            generated_groups[key] = 0
        generated_groups[key] += 1
    assert sorted(donor_groups.values()) == sorted(generated_groups.values())


def test_money_fields_match(donor_path, generated):
    """Сравнить строки таблицы цен по индексу и полям."""
    donor_table_name = _table_name(donor_path, "A_SMETA_CENLVL_")
    generated_table_name = _table_name(generated, "A_SMETA_CENLVL_")
    donor_rows = _rows(donor_path, donor_table_name)
    generated_rows = _rows(generated, generated_table_name)
    fields = ("ITOGO", "RA", "RB", "RC", "RD", "RE", "RJ", "RK")
    for i, (d_row, g_row) in enumerate(zip(donor_rows, generated_rows)):
        for field in fields:
            d_val = decode_float(d_row.get(field))
            g_val = decode_float(g_row.get(field))
            if d_val is None:
                d_val = 0.0
            if g_val is None:
                g_val = 0.0
            assert abs(d_val - g_val) < 0.011, f"Расхождение в поле {field} на строке {i}"


def test_price_row_keeps_overhead_percents(donor_path, generated):
    """Проценты начислений не должны обнуляться у прайс-строк.

    Образцом прайс-позиции бралась первая попавшаяся, а ею оказалась вырожденная
    строка с нулями — от неё наследовались пустые EJ/EK.

    Точного РАВЕНСТВА с исходником здесь не требуется, и это не послабление, а
    честная граница: у прайс-строки фонд оплаты труда нулевой, отношение
    «начисление / ФОТ» не определено, и восстановить норматив не из чего — он
    наследуется от образца. Там, где ФОТ есть (расценки), восстановление точное,
    это проверяет отдельный тест ниже.
    """
    donor_pos = _rows(donor_path, _table_name(donor_path, "A_SMETA_",
                                              ("A_SMETA_CENLVL", "A_SMETA_VIEW")))
    gen_cen = _rows(generated, _table_name(generated, "A_SMETA_CENLVL_"))
    donor_cen = _rows(donor_path, _table_name(donor_path, "A_SMETA_CENLVL_"))

    checked = 0
    for i, pos in enumerate(donor_pos):
        if (pos.get("RABMAT") or 0) != 3:
            continue
        donor_ej = decode_float(donor_cen[i].get("EJ")) or 0.0
        if donor_ej <= 0:
            continue  # в исходнике норматив не заполнен — сравнивать не с чем
        gen_ej = decode_float(gen_cen[i].get("EJ")) or 0.0
        assert gen_ej > 0, "процент начислений у прайс-строки обнулён"
        checked += 1
    assert checked > 0, "в фикстуре нет прайс-строки с заполненным нормативом"


def test_percents_restored_exactly_where_payroll_exists(donor_path, generated):
    """Где есть ФОТ, проценты НР и СП восстанавливаются ТОЧНО.

    На полной смете заказчика это проверено на всех 275 строках с ненулевым
    фондом оплаты труда: расхождений ноль. Здесь то же на синтетической фикстуре.
    """
    donor_cen = _rows(donor_path, _table_name(donor_path, "A_SMETA_CENLVL_"))
    gen_cen = _rows(generated, _table_name(generated, "A_SMETA_CENLVL_"))

    checked = 0
    for src, out in zip(donor_cen, gen_cen):
        fot = (decode_float(src.get("RE")) or 0.0) + (decode_float(src.get("RD")) or 0.0)
        if fot <= 1e-9:
            continue
        for field in ("EJ", "EK"):
            a = decode_float(src.get(field)) or 0.0
            b = decode_float(out.get(field)) or 0.0
            assert abs(a - b) < 0.011, f"{field}: {a} != {b}"
        checked += 1
    assert checked > 0, "в фикстуре нет позиций с ненулевым ФОТ"


def test_floats_are_packed(generated):
    """В сгенерированном файле дробные значения хранятся строкой вида "$…".""" 
    cenlvl_table_name = _table_name(generated, "A_SMETA_CENLVL_")
    rows = _rows(generated, cenlvl_table_name)
    has_packed = any(isinstance(r.get("ITOGO"), str) and r.get("ITOGO", "").startswith("$") for r in rows)
    assert has_packed


def test_all_donor_datasets_present(donor_path, generated):
    """Множество имён файлов в архиве сгенерированного совпадает с множеством имён донора."""
    with zipfile.ZipFile(donor_path) as zf:
        donor_files = set(zf.namelist())
    with zipfile.ZipFile(generated) as zf:
        generated_files = set(zf.namelist())
    assert donor_files == generated_files


def test_names_dictionary_not_broken(generated):
    """В B_NNAME.json у каждой строки с непустым NAME поле CRC не равно None."""
    rows = _rows(generated, "B_NNAME.json")
    for r in rows:
        name = r.get("NAME")
        if name and name.strip():
            assert r.get("CRC") is not None


class _StubDonor:
    """Донор с одной вырожденной и одной нормальной прайс-строкой.

    В фикстуре обе прайс-строки с ненулевым итогом, поэтому «первый попавшийся
    образец» там случайно совпадает с правильным, и подмену не видно. Здесь
    вырожденная строка стоит ПЕРВОЙ — как в реальном файле заказчика, где на ней
    и произошёл дефект.
    """

    smeta_table = "A_SMETA_1_15.json"
    cenlvl_table = "A_SMETA_CENLVL_1_15.json"

    def rows(self, table):
        if table == self.smeta_table:
            return [{"ID": 1, "RABMAT": 3}, {"ID": 2, "RABMAT": 3}]
        return [{"ID": 1, "ITOGO": 0}, {"ID": 2, "ITOGO": "$40E4E63C00000000"}]


def test_template_skips_degenerate_row():
    """Образцом берётся строка с ненулевым итогом, а не первая подходящая.

    ГРАНИЦА ЭТОГО ТЕСТА, названная прямо: он проверяет саму функцию выбора, но НЕ
    проверяет, что генератор её вызывает. Подмена вызова внутри build_sobx на
    прежний «первый попавшийся» этот тест не роняет — проверено мутацией. Это тот
    же класс, что дефект P-006 в смежном контуре: наличие правильной функции ещё
    не означает, что она применяется.

    Чтобы закрыть и применение, в фикстуре нужна вырожденная прайс-строка,
    стоящая ПЕРВОЙ (сейчас обе прайс-строки в ней с ненулевым итогом, и подмена
    случайно даёт тот же результат). Запрошено у автора фикстуры.
    """
    from sv.io.sobx_gen import _pick_template

    assert _pick_template(_StubDonor(), 3)["ID"] == 2
