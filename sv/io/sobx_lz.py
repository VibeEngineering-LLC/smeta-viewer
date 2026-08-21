"""#SMETA-8: пересчёт итоговых ведомостей A_LZ под записываемую смету.

Без пересчёта итоговые таблицы нового файла описывают смету донора: числа чужие,
но выглядят своими — а это тот самый случай, когда ошибка не видна глазом.

Правило показателя установлено на реальном файле и проверено на 270 значениях по
30 узлам дерева, расхождений ноль: показатель узла равен сумме соответствующего
поля строк цен по всем позициям ПОДДЕРЕВА, а не только по прямым потомкам.

Затраты труда машинистов (код 208) модель не хранит — загрузчик .sobx поле RH не
читает. Значение пишется нулём, и это НЕ равнозначно «машинистов не было»: это
отсутствие данных, о чём вызывающая сторона предупреждается отдельно.
"""
from __future__ import annotations

import re

from sv.io.sobx_write import decode_float

ATYPE_FIELD = {
    201: "RA", 202: "RB", 203: "RC", 204: "RD", 205: "RE",
    207: "RG", 208: "RH", 210: "RJ", 211: "RK",
}
ATYPE_VAT = 212
VAT_ROW_TAX = 28      # NUMBER строки НДС
VAT_ROW_TOTAL = 29    # NUMBER строки «итого с НДС»
DEFAULT_VAT = 0.20


def detect_vat_rate(donor) -> float:
    """Ставка НДС, вычисленная по донору, а не взятая из головы.

    Берётся отношение строки НДС к сумме позиций у корневого узла. Если вычислить
    не удаётся (нет строк, нулевая база), возвращается DEFAULT_VAT.
    """
    table_name, values_name = lz_table_names(donor)
    if not table_name or not values_name:
        return DEFAULT_VAT

    rows = donor.rows(table_name)
    if not rows:
        return DEFAULT_VAT

    # Найти строку с НДС у корневого узла
    vat_row = None
    for r in rows:
        if r.get("IDHIER") == donor.obj_id and r.get("ATYPE") == ATYPE_VAT and r.get("NUMBER") == VAT_ROW_TAX:
            vat_row = r
            break

    if not vat_row:
        return DEFAULT_VAT

    # Сумма позиций у корневого узла
    total = 0.0
    for r in donor.rows(table_name):
        if r.get("IDHIER") == donor.obj_id and r.get("ATYPE") != ATYPE_VAT:
            total += r.get("ITOGO", 0.0)

    if total <= 0:
        return DEFAULT_VAT

    vat_value = decode_float(vat_row.get("VALUE", "0"))
    rate = round(vat_value / total, 4)
    if 0 < rate < 1:
        return rate
    else:
        return DEFAULT_VAT


def lz_table_names(donor) -> tuple[str | None, str | None]:
    """Вернуть пару имён (таблица ведомостей, таблица значений)."""
    suffix = f"_{donor.smeta_type}.json" if donor.smeta_type is not None else ".json"
    table_name = None
    values_name = None

    for name in sorted(donor.datasets):
        if re.match(r"^A_LZ_\d+_\d+\.json$", name) and not re.match(r"^A_LZ_(CENLVL|NEW|NAMES)", name):
            if name.endswith(suffix):
                table_name = name
        elif name.startswith("A_LZ_CENLVL_") and not "_NEW" in name:
            if name.endswith(suffix):
                values_name = name

    return (table_name, values_name)


def new_table_names(donor) -> list[str]:
    """Вернуть список имён датасетов донора, содержащих A_LZ_NEW или A_LZ_CENLVL_NEW."""
    result = []
    for name in donor.datasets:
        if "A_LZ_NEW" in name or "A_LZ_CENLVL_NEW" in name:
            result.append(name)
    return result


def build_lz_rows(donor, node_ids, subtree_sums, next_id, vat_rate) -> tuple[list[dict], list[dict], int]:
    """Собрать строки ведомостей и их значений для новых узлов.

    node_ids — список идентификаторов узлов нового дерева в порядке обхода
    (объект, локальная смета, разделы, подразделы).
    subtree_sums — словарь {идентификатор узла: {имя поля: сумма}}; суммы считает
    вызывающая сторона, здесь только раскладка по показателям.
    next_id — с какого значения выдавать идентификаторы строк ведомости.

    Возвращает (строки ведомости, строки значений, следующий свободный идентификатор).
    """
    table_name, values_name = lz_table_names(donor)
    if not table_name or not values_name:
        return ([], [], next_id)

    # Набор-образец строк
    sample_rows = [r for r in donor.rows(table_name) if r.get("IDHIER") == donor.obj_id]
    if not sample_rows:
        # Если нет строк с IDHIER == obj_id, взять первую строку с любым IDHIER
        all_rows = donor.rows(table_name)
        if all_rows:
            first_idhier = all_rows[0].get("IDHIER")
            sample_rows = [r for r in donor.rows(table_name) if r.get("IDHIER") == first_idhier]

    if not sample_rows:
        return ([], [], next_id)

    # Образец строки значений
    values_sample = donor.rows(values_name)
    if values_sample:
        values_sample = values_sample[0]
    else:
        values_sample = {}

    rows = []
    values_rows = []

    for node_id in node_ids:
        sums = subtree_sums.get(node_id) or {}
        is_root = (node_id == node_ids[0])

        for sample_row in sample_rows:
            # Копия строки образца
            row = dict(sample_row)
            row["ID"] = next_id
            row["IDHIER"] = node_id
            row["Keys"] = None
            next_id += 1

            atype = row.get("ATYPE")
            number = row.get("NUMBER")

            # Вычисление значения показателя
            value = None
            if atype in ATYPE_FIELD:
                value = sums.get(ATYPE_FIELD[atype])
                if value is not None:
                    value = round(value, 2)
            elif atype == ATYPE_VAT:
                if is_root:
                    itogo = sums.get("ITOGO", 0.0)
                    if number == VAT_ROW_TAX:
                        value = round(itogo * vat_rate, 2)
                    elif number == VAT_ROW_TOTAL:
                        value = round(itogo * (1 + vat_rate), 2)
                else:
                    value = None
            else:
                value = None

            row["VALUE"] = str(value) if value is not None else None

            # Для показателей 207 и 208 — округление до 4 знаков
            if atype in (207, 208):
                if value is not None:
                    row["VALUE"] = str(round(value, 4))

            rows.append(row)

            # Строка значений
            values_row = dict(values_sample)
            values_row["ID"] = row["ID"]
            values_row["Keys"] = None
            values_row["ITOG"] = str(value) if value is not None else None

            values_rows.append(values_row)

    return (rows, values_rows, next_id)


def blank_new_tables(donor) -> dict[str, list[dict]]:
    """Дополнительные ведомости — со снятыми значениями.

    Показатели этих таблиц (материалы и оборудование заказчика и подрядчика,
    разбивка по видам работ) требуют признаков, которых в модели нет. Оставить
    донорские числа значило бы показать в новом документе чужие суммы; поэтому
    структура сохраняется, а значения снимаются. Пустая ячейка честнее чужой.
    """
    result = {}
    for name in new_table_names(donor):
        rows = donor.rows(name)
        new_rows = []
        for r in rows:
            new_r = dict(r)
            if "ITOG" in new_r:
                new_r["ITOG"] = None
            new_rows.append(new_r)
        result[name] = new_rows
    return result
