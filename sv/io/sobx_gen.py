"""#SMETA-8: генератор .sobx — сборка файла объекта Смета.РУ из модели по донору.

ФОРМУЛЫ ДЕНЕГ восстановлены на доноре и проверены на ВСЕХ его строках (расхождение
ноль, не «в пределах копейки»):

    RB = BB*KOLL*MB     RC = BC*KOLL*MC     RD = BD*KOLL*ME     RE = BE*KOLL*MD
    RA = RB + RC + RE                       ФОТ = RE + RD
    RJ = ФОТ*EJ/100     RK = ФОТ*EK/100     ITOGO = RA + RJ + RK

То есть накладные и сметная прибыль начисляются на ФОТ (основная зарплата ПЛЮС
зарплата машинистов), а не на одну основную: начисление на RE занижало бы их на
полтора процента, а в итогах сметы это уже не копейки.

ЧЕСТНАЯ ГРАНИЦА: индексы пересчёта (M*, D*) и проценты НР/СП (EJ, EK) в модели не
хранятся — они ВОССТАНАВЛИВАЮТСЯ делением текущей суммы на базисную. Там, где
базисной суммы нет (ноль), индекс берётся из строки-шаблона донора, и это значение
унаследованное, а не вычисленное по данным сметы.
"""
from __future__ import annotations

from sv.io.sobx_donor import Donor, name_crc
from sv.io.sobx_write import dataset_json, write_sobx
from sv.model import Smeta


def _num(v) -> float:
    """Преобразовать значение в число."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _ratio(current: float, base_total: float, fallback) -> float:
    """Индекс пересчёта = текущая сумма / базисная сумма. При нулевом
    знаменателе индекс не определён — возвращается fallback (значение из шаблона)."""
    if abs(base_total) < 1e-9:
        return fallback
    return _clean(current / base_total)



def _clean(value: float) -> float:
    """Убрать шум округления из восстановленного коэффициента.

    Суммы в файле хранятся с точностью до копейки, поэтому деление даёт мусор в
    младших разрядах: индекс 67,02 выходит как 67,0000012, процент 121 — как
    121,0000009. Значение притягивается к виду с двумя знаками ТОЛЬКО если оно
    отстоит от него меньше чем на 0,0005 — то есть если разница объясняется
    округлением сумм. Настоящий коэффициент с тремя-четырьмя знаками (67,0234)
    под это условие не попадает и сохраняется как есть: огрублять реальные данные
    ради красивого вида файла нельзя.
    """
    two = round(value, 2)
    if abs(value - two) < 0.0005:
        return two
    return round(value, 4)


def _per_unit(value_on_qty, qty: float) -> float:
    """Базисные составляющие ресурсов в модели лежат НА ВЕСЬ ОБЪЁМ (загрузчик
    `.sobx` умножает их на количество при чтении), а в файле хранятся НА ЕДИНИЦУ — здесь
    выполняется обратное деление."""
    if abs(qty) < 1e-12:
        return _num(value_on_qty)
    return _num(value_on_qty) / qty



def _pick_template(donor, rabmat: int):
    """Строка-образец нужного вида с НЕНУЛЕВЫМ итогом.

    Вырожденная строка (нулевая позиция, пустые начисления) как образец опаснее
    отсутствия образца: наследуемые из неё поля выглядят заполненными, а по смыслу
    пусты. Если ненулевой строки нет — берётся любая подходящая.
    """
    cen = {r.get("ID"): r for r in donor.rows(donor.cenlvl_table)}
    fallback = None
    for row in donor.rows(donor.smeta_table):
        if (row.get("RABMAT") or 0) != rabmat:
            continue
        if fallback is None:
            fallback = row
        c = cen.get(row.get("ID")) or {}
        itogo = c.get("ITOGO")
        if itogo not in (None, "", 0):
            return row
    return fallback


def build_sobx(smeta: Smeta, donor: Donor, out_path: str) -> dict:
    """Собрать .sobx из модели по донору. Возвращает статистику сборки."""
    warnings: list[str] = []

    # Шаг 1. Идентификаторы
    obj_id = donor.obj_id
    smeta_type = donor.smeta_type
    node_step = 58          # шаг идентификаторов узлов дерева, взят из донора
    pos_step = 18           # шаг идентификаторов позиций
    ls_id = obj_id + node_step
    next_node = ls_id + node_step
    next_pos = obj_id + 1752

    # Шаг 2. Дерево: A_O_HIER.json и A_O_PARAMS_R_PR.json
    t_root = donor.template("A_O_HIER.json", ISROOT=1)
    t_ls = donor.template("A_O_HIER.json", ATYPE=3) or t_root
    t_sec = donor.template("A_O_HIER.json", ATYPE=4) or t_root
    t_sub = donor.template("A_O_HIER.json", ATYPE=5) or t_root

    # Шаблоны параметров узла — искать перебором
    param_rows = []
    p_sec = None
    p_sub = None
    for row in donor.rows("A_O_PARAMS_R_PR.json"):
        shifr = str(row.get("SHIFR", "")).casefold()
        if "подраздел" in shifr:
            p_sub = row
        elif "раздел" in shifr:
            p_sec = row
    if not p_sec:
        p_sec = donor.rows("A_O_PARAMS_R_PR.json")[0]
    if not p_sub:
        p_sub = donor.rows("A_O_PARAMS_R_PR.json")[0]

    hier_rows = []
    node_by_key = {}

    # Корень
    root_row = dict(t_root)
    root_row.update({
        "Keys": None,
        "NUMBER": obj_id,
        "ATYPE": 1,
        "ISROOT": 1,
        "SORTING": 0,
        "COUNTCHILDREN": 1
    })
    hier_rows.append(root_row)

    # Узел ЛС
    ls_row = dict(t_ls)
    ls_row.update({
        "Keys": None,
        "NUMBER": ls_id,
        "PARENT": obj_id,
        "ATYPE": 3,
        "SORTING": 1,
        "ISROOT": None,
        "COUNTCHILDREN": len(smeta.sections())
    })
    hier_rows.append(ls_row)

    # Секции
    for num_sec, section in enumerate(smeta.sections(), 1):
        sec_id = next_node
        next_node += node_step

        sec_row = dict(t_sec)
        sec_row.update({
            "Keys": None,
            "NUMBER": sec_id,
            "PARENT": ls_id,
            "ATYPE": 4,
            "ISROOT": None,
            "SORTING": num_sec,
            "COUNTCHILDREN": len(section.subsections)
        })
        hier_rows.append(sec_row)

        param_row = dict(p_sec)
        param_row.update({
            "Keys": None,
            "ID": sec_id,
            "FULLNAME": section.name
        })
        param_rows.append(param_row)

        node_by_key[(section.name, "")] = sec_id

        # Подразделы
        for num_sub, subsection in enumerate(section.subsections, 1):
            sub_id = next_node
            next_node += node_step

            sub_row = dict(t_sub)
            sub_row.update({
                "Keys": None,
                "NUMBER": sub_id,
                "PARENT": sec_id,
                "ATYPE": 5,
                "ISROOT": None,
                "SORTING": num_sub,
                "COUNTCHILDREN": 0
            })
            hier_rows.append(sub_row)

            param_row = dict(p_sub)
            param_row.update({
                "Keys": None,
                "ID": sub_id,
                "FULLNAME": subsection
            })
            param_rows.append(param_row)

            node_by_key[(section.name, subsection)] = sub_id

    # Шаг 3. Справочники
    names_index = donor.names_index()
    nname_rows = donor.rows("B_NNAME.json")
    next_name_id = donor.max_id("B_NNAME.json") + 1
    units_index = donor.units_index()

    empty_name_id = 0
    for row in nname_rows:
        if not row.get("NAME"):
            empty_name_id = row["ID"]
            break

    default_unit_id = 0
    for row in donor.rows("B_EDIZM.json"):
        if row.get("ID"):
            default_unit_id = row["ID"]
            break

    reported_warnings = set()

    def name_id(text):
        nonlocal next_name_id
        if not text:
            return empty_name_id
        if text in names_index:
            return names_index[text]
        new_id = next_name_id
        next_name_id += 1
        names_index[text] = new_id
        nname_rows.append({
            "Keys": None,
            "ID": new_id,
            "NAME": text,
            "IDTITLE": None,
            "CRC": name_crc(text)
        })
        return new_id

    def unit_id(text):
        key = str(text or "").strip().casefold()
        if key in units_index:
            return units_index[key]
        warning_msg = f"единица измерения не найдена в справочнике донора: {text}"
        if warning_msg not in reported_warnings:
            warnings.append(warning_msg)
            reported_warnings.add(warning_msg)
        return default_unit_id

    # Шаг 4. Позиции
    # Шаблон выбирается не «первый попавшийся с нужным RABMAT», а ТИПИЧНЫЙ — с
    # ненулевым итогом. В доноре первой прайс-строкой оказалась вырожденная позиция
    # с нулями, и наследование от неё давало новым строкам пустые проценты НР и СП:
    # дефект тихий, суммы при этом сходились до копейки.
    tpl_pos_rasc = _pick_template(donor, 0)
    tpl_pos_price = _pick_template(donor, 3)
    cen_by_id = {r["ID"]: r for r in donor.rows(donor.cenlvl_table)}
    tpl_cen_rasc = cen_by_id.get(tpl_pos_rasc["ID"]) if tpl_pos_rasc else None
    tpl_cen_price = cen_by_id.get(tpl_pos_price["ID"]) if tpl_pos_price else None

    pos_rows = []
    cen_rows = []
    num_rows = []
    total_sum = 0.0

    # NUMBER1 — номер позиции ВНУТРИ своего узла дерева, а не сквозной по смете.
    # Проверено на доноре: в каждом подразделе нумерация начинается с 1. Расхождения
    # в самом доноре (220 строк) — исторические дыры от удалённых позиций, замысел
    # формата они не меняют; новый файл нумеруется подряд.
    num_in_node: dict[int, int] = {}
    for p in smeta.positions:
        is_price = p.is_price_item()
        tpl_pos = tpl_pos_price if is_price else tpl_pos_rasc
        tpl_cen = tpl_cen_price if is_price else tpl_cen_rasc
        if not tpl_pos:
            tpl_pos = tpl_pos_rasc or tpl_pos_price
        if not tpl_cen:
            tpl_cen = tpl_cen_rasc or tpl_cen_price

        pid = next_pos
        next_pos += pos_step

        hier_id = node_by_key.get((p.section, p.subsection)) or node_by_key.get((p.section, "")) or ls_id

        num1 = num_in_node.get(hier_id, 0) + 1
        num_in_node[hier_id] = num1

        q = _num(p.qty)

        # Базисные НА ЕДИНИЦУ
        ba = _num(p.price_base)
        bb = _per_unit(p.resources.materialy_base, q)
        bc = _per_unit(p.resources.ekspl_mashin_base, q)
        bd = _per_unit(p.resources.zp_mashinistov_base, q)
        be = _per_unit(p.resources.zarplata_base, q)
        bg = _num(p.resources.zatraty_truda_qty)

        # Строка позиции
        pos_row = dict(tpl_pos)
        pos_row.update({
            "Keys": None,
            "ID": pid,
            "IDHIER": hier_id,
            "SMETATYPE": smeta_type,
            "NUMBER1": num1,
            "NOMERROD1": pid,
            "TAB": p.code,
            "ALTTAB": (None if is_price else p.code),
            "NAME_ID": name_id(p.name),
            "ID_EDIZM": unit_id(p.unit),
            "KOLL": q,
            "KOLL_B": q,
            "BA": ba,
            "BB": bb,
            "BC": bc,
            "BD": bd,
            "BE": be,
            "BG": bg
        })
        pos_rows.append(pos_row)

        # Текущие суммы НА ВЕСЬ ОБЪЁМ — из модели
        rb = _num(p.resources.materialy_current)
        rc = _num(p.resources.ekspl_mashin_current)
        rd = _num(p.resources.zp_mashinistov_current)
        re_ = _num(p.resources.zarplata_current)
        rg = _num(p.resources.zatraty_truda_value)
        rj = _num(p.resources.nr_current)
        rk = _num(p.resources.sp_current)
        ra = rb + rc + re_

        total = _num(p.total_current)
        if abs(total) < 1e-9 and abs(ra + rj + rk) > 1e-9:
            total = ra + rj + rk
        total_sum += total

        # Строка цен
        cen_row = dict(tpl_cen)
        cen_row.update({
            "Keys": None,
            "ID": pid,
            "BA": ba, "BB": bb, "BC": bc, "BD": bd, "BE": be, "BG": bg,
            "CA": ba, "CB": bb, "CC": bc, "CD": bd, "CE": be, "CG": bg,
            "EA": ba, "EB": bb, "EC": bc, "ED": bd, "EE": be, "EG": bg,
            "RA": ra, "RB": rb, "RC": rc, "RD": rd, "RE": re_, "RG": rg, "RJ": rj, "RK": rk, "ITOGO": total
        })

        # Индексы восстановлением (fallback — значение из tpl_cen)
        mb = _ratio(rb, bb * q, tpl_cen.get("MB"))
        mc = _ratio(rc, bc * q, tpl_cen.get("MC"))
        me = _ratio(rd, bd * q, tpl_cen.get("ME"))
        md = _ratio(re_, be * q, tpl_cen.get("MD"))

        cen_row.update({
            "MB": mb, "MC": mc, "ME": me, "MD": md,
            "DB": mb, "DC": mc, "DE": me, "DD": md
        })

        # Проценты начислений
        fot = re_ + rd
        if fot > 1e-9:
            ej = _clean(rj / fot * 100.0)
            ek = _clean(rk / fot * 100.0)
        else:
            ej = tpl_cen.get("EJ")
            ek = tpl_cen.get("EK")

        cen_row.update({
            "EJ": ej, "EK": ek,
            "PA": ej, "PB": ek
        })
        cen_rows.append(cen_row)

        num_rows.append({
            "Keys": None,
            "ID": pid,
            "NUMBER1": num1,
            "NUMBER2": 0,
            "NUMBER3": 0
        })

    # Шаг 5. Сборка архива
    datasets = {}
    for name in donor.datasets:
        datasets[name] = dataset_json(donor.fields(name), donor.rows(name), donor.indexes(name))

    # Пересобранные датасеты обязаны пройти ТУ ЖЕ сериализацию, что и скопированные:
    # положить сюда список строк вместо готового JSON — это и есть грабля «потерянный
    # шаг конвертации». Здесь она не молчит: write_sobx принимает только строки.
    for name, rows_ in (("A_O_HIER.json", hier_rows),
                        ("A_O_PARAMS_R_PR.json", param_rows),
                        ("B_NNAME.json", nname_rows),
                        (donor.smeta_table, pos_rows),
                        (donor.cenlvl_table, cen_rows),
                        (donor.viewnum_table, num_rows)):
        datasets[name] = dataset_json(donor.fields(name), rows_, donor.indexes(name))

    write_sobx(out_path, datasets)

    return {
        "positions": len(pos_rows),
        "sections": len(smeta.sections()),
        "nodes": len(hier_rows),
        "total_current": total_sum,
        "datasets": len(datasets),
        "warnings": warnings
    }
