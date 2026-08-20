"""#SMETA-1: загрузчик .sobx — экспорт объекта из Смета.РУ (ZIP с дампами таблиц БД).

Структура и связи проверены на реальном файле: итог по полю ITOGO совпадает
с итогом той же сметы, выгруженной в .xlsx.

Особенности формата, подтверждённые на файле:
  * JSON внутри архива — cp1251 БЕЗ BOM; utf-8 падает;
  * парсить нестрого (strict=False): внутри строк встречаются управляющие символы;
  * дробные числа хранятся строкой "$40298F5C28F5C28F" — это IEEE-754 double
    big-endian в hex; целые лежат обычными числами, декодер обязан уметь оба.

ПЕРСОНАЛЬНЫЕ ДАННЫЕ: таблица A_O_PARAMS_R_PR содержит ФИО исполнителя, проверяющего
и утверждающего. Загрузчик берёт оттуда ТОЛЬКО FULLNAME (название раздела) и не
читает поля *_FIO / *_DOLGN.
"""
from __future__ import annotations

import json
import struct
import zipfile

from sv.model import Position, Resources, Smeta, SmetaFormat, Totals


def _num(v) -> float | None:
    """Преобразовать значение в число, если возможно."""
    if isinstance(v, str) and v.startswith("$"):
        try:
            return struct.unpack(">d", bytes.fromhex(v[1:]))[0]
        except (ValueError, struct.error):
            return None
    elif isinstance(v, (int, float)):
        return float(v)
    return None


def _txt(v) -> str:
    """Преобразовать значение в строку, убрав пробелы."""
    return "" if v is None else str(v).strip()


def _table(z: zipfile.ZipFile, name: str) -> dict | None:
    """Читает таблицу из ZIP-архива и парсит JSON."""
    try:
        with z.open(name) as f:
            data = f.read().decode("cp1251")
        return json.loads(data, strict=False)
    except Exception:
        return None


def _rows(t: dict) -> list[dict]:
    """Преобразует дамп таблицы в список словарей."""
    fields = t["Fields"]
    data = t["Data"]
    result = []
    for row in data:
        row_dict = {}
        for i, field in enumerate(fields):
            key = field.get("Name", field) if isinstance(field, dict) else field
            value = row[i] if i < len(row) else None
            row_dict[key] = value
        result.append(row_dict)
    return result


def _find(names: list[str], prefix: str) -> str | None:
    """Находит имя таблицы по префиксу."""
    for name in names:
        if name.startswith(prefix):
            return name
    return None


def load(path: str) -> Smeta:
    """Загружает смету из .sobx файла."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()

        # Найти таблицы
        # Имена таблиц несут числовой суффикс объекта, поэтому ищем
        # по префиксу, но СНАЧАЛА отбрасываем однокоренные A_SMETA_CENLVL_* и
        # A_SMETA_VIEW_*: иначе _find мог вернуть их и позиции не читались вовсе.
        pos_candidates = [n for n in names
                          if n.startswith("A_SMETA_")
                          and not n.startswith("A_SMETA_CENLVL")
                          and not n.startswith("A_SMETA_VIEW")]
        pos_table_name = pos_candidates[0] if pos_candidates else None

        cenlvl_table_name = _find(names, "A_SMETA_CENLVL_")
        nname_table = _table(z, "B_NNAME.json")
        edizm_table = _table(z, "B_EDIZM.json")
        params_pr_table = _table(z, "A_O_PARAMS_R_PR.json")
        hier_table = _table(z, "A_O_HIER.json")
        params_ls_table = _table(z, "A_O_PARAMS_LS.json")

        # Построить справочники
        names_by_id = {}
        if nname_table:
            for row in _rows(nname_table):
                names_by_id[row.get("ID")] = _txt(row.get("NAME"))

        units_by_id = {}
        if edizm_table:
            for row in _rows(edizm_table):
                units_by_id[row.get("ID")] = _txt(row.get("NAME"))

        sections_by_id = {}
        if params_pr_table:
            for row in _rows(params_pr_table):
                sections_by_id[_txt(row.get("ID"))] = _txt(row.get("FULLNAME"))

        parent_of = {}
        if hier_table:
            for row in _rows(hier_table):
                parent_of[_txt(row.get("NUMBER"))] = _txt(row.get("PARENT"))

        # Цены
        price_by_id = {}
        price_table_lost = cenlvl_table_name is None
        if cenlvl_table_name:
            cenlvl_table = _table(z, cenlvl_table_name)
            if cenlvl_table is None:
                # Архив валиден, но таблица цен не разобралась. Без этого признака
                # смета молча показывалась как смета на 0 рублей.
                price_table_lost = True
            if cenlvl_table:
                for row in _rows(cenlvl_table):
                    # Кладём ВСЮ строку цен: из неё берутся ITOGO и составляющие
                    # BA..BG / CA..CG. Поля "CENA" в этой таблице нет.
                    price_by_id[row.get("ID")] = row

        # Позиции
        positions = []
        total_current_sum = 0.0
        warnings = []

        if pos_table_name:
            pos_table = _table(z, pos_table_name)
            if pos_table:
                for i, row in enumerate(_rows(pos_table), 1):
                    code = _txt(row.get("TAB")) or _txt(row.get("ALTTAB"))
                    name_id = row.get("NAME_ID")
                    name = names_by_id.get(name_id, "")
                    unit_id = row.get("ID_EDIZM")
                    unit = units_by_id.get(unit_id, "")
                    qty = _num(row.get("KOLL"))
                    num = str(i)

                    # Определить раздел и подраздел
                    hier_id = row.get("IDHIER")
                    section = ""
                    subsection = ""
                    steps = 0
                    current_id = _txt(hier_id)      # ключи иерархии приводим к строке:
                    hierarchy_names = []           # IDHIER — число, а parent_of строится
                    while current_id and steps < 20:   # по строковым ключам, иначе связь рвётся
                        # ВНИМАНИЕ: переменную наименования позиции здесь трогать нельзя —
                        # имя узла держим в отдельной sec_name, иначе имя позиции
                        # затиралось названием раздела.
                        sec_name = sections_by_id.get(current_id)
                        if sec_name:
                            hierarchy_names.append(sec_name)
                        parent_id = parent_of.get(current_id)
                        if not parent_id or parent_id == current_id:
                            break
                        current_id = parent_id
                        steps += 1

                    # Цепочка идёт СНИЗУ ВВЕРХ: [подраздел, раздел, объект…].
                    if len(hierarchy_names) >= 2:
                        subsection, section = hierarchy_names[0], hierarchy_names[1]
                    elif hierarchy_names:
                        section = hierarchy_names[0]

                    # Цены
                    # Денежные поля лежат в ОТДЕЛЬНОЙ таблице A_SMETA_CENLVL_*,
                    # связь один к одному по полю ID.
                    # В самой строке позиции их нет — чтение row.get("ITOGO")
                    # давало None и обнуляло весь итог сметы.
                    pr = price_by_id.get(row.get("ID")) or {}
                    total_current = _num(pr.get("ITOGO"))
                    price_base = _num(pr.get("BA"))
                    # РАСКЛАДКА ЦЕН (сверена дампом с той же сметой в .xlsx):
                    #   B* — базисные цены НА ЕДИНИЦУ;
                    #   C* — их копия, а НЕ текущие цены (значения совпадают с B*);
                    #   R* — суммы В ТЕКУЩИХ ЦЕНАХ НА ВЕСЬ ОБЪЁМ — это и нужно.
                    # Чтение C* как «текущих» давало зарплату 7,44 вместо 3 989,03.
                    q = qty or 0.0
                    _on_qty = lambda v: None if v is None else v * q

                    zarplata_base = _on_qty(_num(pr.get("BE")))
                    zarplata_current = _num(pr.get("RE"))
                    ekspl_mashin_base = _on_qty(_num(pr.get("BC")))
                    ekspl_mashin_current = _num(pr.get("RC"))
                    zp_mashinistov_base = _on_qty(_num(pr.get("BD")))
                    zp_mashinistov_current = _num(pr.get("RD"))
                    materialy_base = _on_qty(_num(pr.get("BB")))
                    materialy_current = _num(pr.get("RB"))
                    zatraty_truda_qty = _num(pr.get("BG"))   # норма времени НА ЕДИНИЦУ, не на объём

                    total_current_sum += total_current if total_current is not None else 0.0

                    resources = Resources(
                        zarplata_base=zarplata_base,
                        zarplata_current=zarplata_current,
                        ekspl_mashin_base=ekspl_mashin_base,
                        ekspl_mashin_current=ekspl_mashin_current,
                        zp_mashinistov_base=zp_mashinistov_base,
                        zp_mashinistov_current=zp_mashinistov_current,
                        materialy_base=materialy_base,
                        materialy_current=materialy_current,
                        zatraty_truda_qty=zatraty_truda_qty,
                        zatraty_truda_value=_num(pr.get("RG")),
                        nr_current=_num(pr.get("RJ")),
                        sp_current=_num(pr.get("RK"))
                    )

                    pos = Position(
                        code=code,
                        name=name,
                        unit=unit,
                        qty=qty,
                        num=num,
                        price_base=price_base,
                        section=section,
                        subsection=subsection,
                        total_current=total_current,
                        resources=resources,
                        source_row=i
                    )
                    positions.append(pos)
        else:
            warnings.append("в архиве не найдена таблица позиций A_SMETA_*")

        # Имя сметы
        smeta_num = ""
        if params_ls_table:
            for row in _rows(params_ls_table):
                smeta_num = _txt(row.get("FULLNAME")) or _txt(row.get("SHIFR"))
                if smeta_num:
                    break

        # Итог документа в .sobx НЕ хранится: подставлять сюда сумму позиций нельзя —
        # тогда сверка сравнивает величину саму с собой и всегда показывает «норма».
        totals = Totals()
        if price_table_lost:
            warnings.append("НЕ ПРОЧИТАНА таблица цен: стоимости позиций отсутствуют")
        warnings.append("итог документа в .sobx не хранится — сверка с суммой позиций невозможна")
        warnings.append("базисные итоги позиций в .sobx не хранятся отдельным полем — колонка «Стоимость базисная» пуста")

        return Smeta(
            path=path,
            fmt=SmetaFormat.SOBX,
            smeta_num=smeta_num,
            positions=positions,
            totals=totals,
            warnings=warnings
        )
