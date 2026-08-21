from __future__ import annotations

import json
import zipfile

import pytest

from sv.io.sobx_write import (dataset_is_empty, dataset_json, decode_float,
                              encode_float, write_sobx)


@pytest.fixture
def fields() -> list[dict]:
    return [
        {"Name": "Keys", "Attributes": "[]", "DataType": "ftAutoInc", "Precision": 0, "Size": 0},
        {"Name": "ID", "Attributes": "[]", "DataType": "ftInteger", "Precision": 0, "Size": 0},
        {"Name": "TAB", "Attributes": "[]", "DataType": "ftString", "Precision": 0, "Size": 250},
        {"Name": "BA", "Attributes": "[]", "DataType": "ftFloat", "Precision": 0, "Size": 0}
    ]


def test_encode_float_reference_value():
    """Контрольное значение из карты формата."""
    assert encode_float(12.78) == "$40298F5C28F5C28F"


def test_encode_float_integer_stays_number():
    """Целое значение в ftFloat-поле пишется голым числом — это правильно,
    а не «недокодировано»."""
    assert encode_float(8) == 8
    assert encode_float(0) == 0
    assert isinstance(encode_float(8), int)


def test_decode_roundtrip():
    """Проверка обратного преобразования."""
    values = [12.78, 0.001, -5.5, 1234567.89]
    for v in values:
        assert abs(decode_float(encode_float(v)) - v) < 1e-9


def test_decode_float_bad_input_returns_none():
    """Некорректные входные данные возвращают None."""
    assert decode_float(None) is None
    assert decode_float("не число") is None
    assert decode_float("$ZZZZ") is None


def test_data_is_list_of_lists(fields):
    """Регрессия P-006 №1 — Data собран списком словарей вместо списка списков."""
    rows = [
        {"ID": 1, "TAB": "test1", "BA": 1.0},
        {"ID": 2, "TAB": "test2", "BA": 2.0}
    ]
    data = dataset_json(fields, rows)
    parsed = json.loads(data, strict=False)
    assert all(isinstance(r, list) for r in parsed["Data"])
    assert all(len(r) == len(fields) for r in parsed["Data"])


def test_float_cell_is_encoded_in_output(fields):
    """Регрессия P-006 №2 — проверяется вид готовой ячейки, а не наличие функции."""
    rows = [{"ID": 1, "TAB": "20-02-016-01", "BA": 12.78}]
    data = dataset_json(fields, rows)
    parsed = json.loads(data, strict=False)
    assert parsed["Data"][0][3] == "$40298F5C28F5C28F"


def test_type_comes_from_field_not_from_value(fields):
    """Тип берётся из описания поля, а не угадывается по типу python-значения."""
    rows = [{"ID": 7, "TAB": "прайс-лист", "BA": 8}]
    data = dataset_json(fields, rows)
    parsed = json.loads(data, strict=False)
    assert parsed["Data"][0][1] == 7
    assert isinstance(parsed["Data"][0][1], int)
    assert parsed["Data"][0][3] == 8
    assert isinstance(parsed["Data"][0][3], int)


def test_autoinc_keys_filled(fields):
    """Проверка заполнения ключей AutoInc."""
    rows = [
        {"ID": 1, "TAB": "test1", "BA": 1.0},
        {"ID": 2, "TAB": "test2", "BA": 2.0},
        {"ID": 3, "TAB": "test3", "BA": 3.0}
    ]
    data = dataset_json(fields, rows)
    parsed = json.loads(data, strict=False)
    assert [r[0] for r in parsed["Data"]] == [1, 2, 3]


def test_none_stays_null(fields):
    """Проверка сохранения None значений."""
    rows = [{"ID": None, "TAB": None, "BA": None}]
    data = dataset_json(fields, rows)
    parsed = json.loads(data, strict=False)
    assert parsed["Data"][0][1] is None
    assert parsed["Data"][0][2] is None
    assert parsed["Data"][0][3] is None


def test_dataset_is_empty(fields):
    """Проверка пустого датасета."""
    empty = dataset_json(fields, [])
    assert dataset_is_empty(empty)
    non_empty = dataset_json(fields, [{"ID": 1}])
    assert not dataset_is_empty(non_empty)


def test_write_sobx_encoding_and_order(tmp_path, fields):
    """Проверка кодировки и порядка файлов в .sobx."""
    datasets = {
        "ARCTYPE.json": dataset_json(fields, []),
        "B_NNAME.json": dataset_json(fields, [{"TAB": "Вентиляция"}]),
        "A_O_HIER.json": dataset_json(fields, [])
    }
    path = tmp_path / "out.sobx"
    write_sobx(str(path), datasets)
    with zipfile.ZipFile(path, 'r') as zf:
        assert zf.namelist()[0] == "ARCTYPE.json"
        assert zf.namelist()[1:] == sorted(zf.namelist()[1:])
        blob = zf.read("B_NNAME.json")
        assert b"\r\n" in blob
        assert "Вентиляция" in blob.decode("cp1251")
        with pytest.raises(UnicodeDecodeError):
            blob.decode("utf-8")


def test_write_sobx_deflate(tmp_path, fields):
    """Проверка сжатия ZIP-архива."""
    datasets = {
        "ARCTYPE.json": dataset_json(fields, []),
        "B_NNAME.json": dataset_json(fields, [{"TAB": "test"}]),
        "A_O_HIER.json": dataset_json(fields, [])
    }
    path = tmp_path / "out.sobx"
    write_sobx(str(path), datasets)
    with zipfile.ZipFile(path, 'r') as zf:
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_DEFLATED

def test_packed_value_survives_recoding(fields):
    """Регрессия: значение, уже упакованное в "$hex", не должно теряться.

    Генератор копирует датасеты донора строка в строку, поэтому упакованные
    значения проходят через кодировщик ПОВТОРНО. Прежняя версия пыталась
    привести "$4170..." к float, ловила ValueError и отдавала None — данные
    исчезали молча. Сверка поле-в-поле показала это на 200+ ячейках.
    """
    packed = "$40298F5C28F5C28F"
    parsed = json.loads(dataset_json(fields, [{"ID": 1, "TAB": "x", "BA": packed}]),
                        strict=False)
    assert parsed["Data"][0][3] == packed


def test_packed_value_roundtrip_is_stable(fields):
    """Двойное прохождение через сериализацию не меняет значение."""
    rows = [{"ID": 1, "TAB": "x", "BA": 12.78}]
    once = json.loads(dataset_json(fields, rows), strict=False)["Data"][0][3]
    twice = json.loads(dataset_json(fields, [{"ID": 1, "TAB": "x", "BA": once}]),
                       strict=False)["Data"][0][3]
    assert once == twice == "$40298F5C28F5C28F"
