"""#SMETA-8: сериализация датасетов Delphi и упаковка архива .sobx.

Формат описан в карте Сметчика (references/FORMAT-sobx.md, 2026-08-20): ZIP с
дампами датасетов, cp1251, CRLF, дробные ftFloat строкой "$<16 hex>" — IEEE-754
double big-endian, целые в том же поле — голым числом.

КОНСТРУКЦИЯ ПРОТИВ ДВУХ ИЗВЕСТНЫХ ГРАБЕЛЬ (инцидент P-006 контура «Сметчик»,
оба раза код компилировался, печатал «ОК» и давал мусор):

  1. «Data собран списком словарей вместо списка списков». Здесь строку НЕЛЬЗЯ
     передать списком: dataset_json принимает только словари и раскладывает их
     по Fields сам. Забыть шаг конвертации нечем — его нет в вызывающем коде.
  2. «Кодировщик ftFloat написан, но не вызван». Здесь кодирование — единственный
     путь значения к выходу: _encode_value вызывается для каждой ячейки, а тип
     берётся из описания поля, а не угадывается по типу python-значения.

Проверять формат нужно на готовой строке: дробное значение обязано выглядеть как
"$40298F5C28F5C28F" (= 12.78), а не как 12.78.
"""
from __future__ import annotations

import json
import struct
import zipfile


FLOAT_TYPES = {"ftFloat", "ftCurrency", "ftBCD", "ftFMTBcd"}
INT_TYPES = {"ftInteger", "ftSmallint", "ftWord", "ftLargeint", "ftAutoInc"}
EMPTY_DATE = "30.12.1899"


def encode_float(value) -> str | int:
    """Дробное — строкой "$<16 hex>" (IEEE-754 double big-endian); целое — числом.

    Значение, УЖЕ упакованное в "$hex", возвращается как есть. Это не мелочь:
    генератор копирует датасеты донора строка в строку, и такие значения проходят
    через кодировщик повторно. Прежняя версия пыталась сделать float("$4170…"),
    ловила ValueError и отдавала None — данные исчезали молча, без исключения,
    ровно тем способом, против которого написан этот модуль.
    """
    if isinstance(value, str):
        if value.startswith("$"):
            return value
        value = value.replace(",", ".")
    if float(value).is_integer():
        return int(value)
    return "$" + struct.pack(">d", float(value)).hex().upper()


def decode_float(value) -> float | None:
    """Обратная операция, нужна тестам и круговой проверке."""
    try:
        if isinstance(value, str) and value.startswith("$"):
            return struct.unpack(">d", bytes.fromhex(value[1:]))[0]
        else:
            return float(value)
    except (TypeError, ValueError, struct.error):
        # TypeError ловится наравне с остальными: float(None) — самый частый вход
        # при чтении ячейки, которой в строке не оказалось.
        return None


def _encode_value(value, datatype: str):
    """Одна ячейка. Тип берётся ИЗ ОПИСАНИЯ ПОЛЯ, а не из типа python-значения."""
    if value is None:
        return None
    if datatype in FLOAT_TYPES:
        try:
            return encode_float(value)
        except (TypeError, ValueError):
            return None
    elif datatype in INT_TYPES:
        # Целочисленное поле тоже может прийти уже готовым значением из донора;
        # нечисловой текст в нём — сигнал дефекта, а не повод молча обнулить.
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    else:
        # строки, даты, memo
        if isinstance(value, str):
            return value
        return str(value)


def dataset_json(fields: list[dict], rows: list[dict], indexes: list[dict] | None = None) -> str:
    """Собрать JSON датасета. rows — список СЛОВАРЕЙ {имя поля: значение}.

    Список значений на вход НЕ принимается сознательно: раскладка по порядку
    Fields — та самая операция, которую легко потерять молча, поэтому она
    выполняется здесь и всегда.

    Поле ftAutoInc (в этом формате всегда первое, "Keys") заполняется само
    порядковым номером записи с 1, если вызывающий не задал значение явно.
    """
    names = [f["Name"] for f in fields]
    types = [f.get("DataType", "ftString") for f in fields]

    data = []
    for idx, row in enumerate(rows, 1):
        values = []
        for name, dtype in zip(names, types):
            if dtype == "ftAutoInc" and row.get(name) is None:
                values.append(idx)
            else:
                values.append(_encode_value(row.get(name), dtype))
        data.append(values)

    # Сериализуются сами списки, а не обёртки с последующей обрезкой префикса:
    # срезы вида fields_json[10:-1] завязаны на длину строки «{"Fields": » и
    # ломаются от любой правки формата, причём молча — JSON остаётся валидным.
    fields_json = json.dumps(fields, ensure_ascii=False)
    indexes_json = json.dumps(indexes or [], ensure_ascii=False)
    data_body = ",\n".join(json.dumps(r, ensure_ascii=False) for r in data)
    return ('{\n"Fields": ' + fields_json
            + ',\n\n"Indexes": ' + indexes_json
            + ',\n\n"Data": [\n' + data_body + '\n]\n}')


def write_sobx(path: str, datasets: dict[str, str]) -> None:
    """Упаковать датасеты в .sobx. Ключ словаря — имя файла в архиве («A_O_HIER.json»),
    значение — готовый JSON-текст.

    ARCTYPE.json пишется первой записью, остальные — по алфавиту: так устроен
    эталон, и воспроизвести порядок дешевле, чем проверять, важен ли он.
    Кодировка cp1251, переводы строк CRLF — как в оригинале; пустые датасеты
    (без записей) в архив не попадают вовсе, это наблюдаемое свойство формата.
    """
    # Определяем порядок файлов
    names = list(datasets.keys())
    if "ARCTYPE.json" in names:
        names.remove("ARCTYPE.json")
        names = ["ARCTYPE.json"] + sorted(names)
    else:
        names = sorted(names)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            text = datasets[name]
            # Нормализуем переводы строк
            text = text.replace("\r\n", "\n")
            text = text.replace("\n", "\r\n")
            blob = text.encode("cp1251", errors="replace")
            zf.writestr(name, blob)


def dataset_is_empty(dataset_text: str) -> bool:
    """Вернуть True, если в тексте датасета секция `Data` пуста."""
    return '"Data": [\n\n]' in dataset_text or '"Data": []' in dataset_text
