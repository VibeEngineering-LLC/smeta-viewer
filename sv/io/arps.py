"""#SMETA-1: загрузчик обменного формата АРПС 1.10 (.arp).

Кодировка cp866 БЕЗ BOM, строки CRLF, поля разделены '#'. Тип записи — первое поле.
Спецификация формата: АРПС 1.10.

ИТОГ ПОЗИЦИИ в файле не хранится — он вычисляется:
    ПЗ      = поле15 * объём                       (прямые затраты в текущих ценах)
    база    = (поле16 + поле18) * объём            (ОЗП + ЗП машинистов, текущие)
    НР      = база * коэффициент записи 25 типа 2
    СП      = база * коэффициент записи 25 типа 3
    итог    = ПЗ + НР + СП
Формула сверена на реальном файле: результат совпадает со стоимостью тех же
позиций в .xlsx- и .sobx-версиях той же сметы.

ЧИСЛА записаны с ДЕСЯТИЧНОЙ ЗАПЯТОЙ ("12,78"); точка как разделитель не встречается.
"""
from __future__ import annotations

from sv.model import Position, Resources, Smeta, SmetaFormat, Totals


def _num(s: str) -> float | None:
    """Преобразовать строку в число или None."""
    if not s:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _get(parts: list[str], i: int) -> str:
    """Получить поле по 1-БАЗИРОВАННОМУ индексу."""
    if i < 1 or i >= len(parts):
        return ""
    return parts[i]


def load(path: str) -> Smeta:
    """Загрузить файл АРПС 1.10."""
    with open(path, "rb") as f:
        content = f.read().decode("cp866", errors="replace")
    lines = content.splitlines()

    positions: list[Position] = []
    current_section = ""
    current_subsection = ""
    last: Position | None = None
    smeta_name = ""
    nr_koef: float | None = None
    sp_koef: float | None = None

    def _finish():
        """Завершить текущую позицию."""
        nonlocal last, nr_koef, sp_koef
        if not last:
            return
        qty = last.qty or 0.0
        pz = (pz_unit or 0.0) * qty
        base = ((ozp_unit or 0.0) + (zpm_unit or 0.0)) * qty
        nr = base * (nr_koef or 0.0)
        sp = base * (sp_koef or 0.0)
        last.total_current = pz + nr + sp
        last.resources.nr_current = nr
        last.resources.sp_current = sp

        # Перевести ресурсы из "на единицу" в "на объём"
        if last.resources.zarplata_base is not None:
            last.resources.zarplata_base *= qty
        if last.resources.zarplata_current is not None:
            last.resources.zarplata_current *= qty
        if last.resources.ekspl_mashin_base is not None:
            last.resources.ekspl_mashin_base *= qty
        if last.resources.ekspl_mashin_current is not None:
            last.resources.ekspl_mashin_current *= qty
        if last.resources.zp_mashinistov_base is not None:
            last.resources.zp_mashinistov_base *= qty
        if last.resources.zp_mashinistov_current is not None:
            last.resources.zp_mashinistov_current *= qty
        if last.resources.materialy_base is not None:
            last.resources.materialy_base *= qty
        if last.resources.materialy_current is not None:
            last.resources.materialy_current *= qty

        # ВАЖНО: функция меняет ресурсы НА МЕСТЕ (умножает на объём), поэтому она
        # обязана быть однократной. Вызовов три: перед новой позицией, перед
        # заголовком раздела и в конце файла — позиция, за которой идёт заголовок,
        # финализировалась дважды, и её ресурсы умножались на объём повторно
        # (под позицией в 29 тыс. ₽ показывались миллионы). Гасим ссылку.
        last = None

    for line_num, line in enumerate(lines, 1):
        if not line.strip():
            continue
        parts = line.split("#")
        kind = parts[0].strip()
        if kind == "3":
            # Идентификация документа
            name = _get(parts, 3)
            doc_name = _get(parts, 6)
            if name:
                smeta_name = name
            elif doc_name:
                smeta_name = doc_name
        elif kind == "10":
            # Заголовок раздела
            _finish()
            level = _get(parts, 1)
            name = _get(parts, 3)
            if level == "0":
                current_section = name
                current_subsection = ""
            else:
                current_subsection = name
        elif kind == "20":
            # Позиция
            _finish()
            num = _get(parts, 1)
            code = _get(parts, 2)
            unit = _get(parts, 3)
            name = _get(parts, 4)
            price_base = _num(_get(parts, 5))
            qty = _num(_get(parts, 26))
            zarplata_base = _num(_get(parts, 6))
            ekspl_mashin_base = _num(_get(parts, 7))
            zp_mashinistov_base = _num(_get(parts, 8))
            materialy_base = _num(_get(parts, 9))
            zatraty_truda_qty = _num(_get(parts, 13))
            zarplata_current = _num(_get(parts, 16))
            ekspl_mashin_current = _num(_get(parts, 17))
            zp_mashinistov_current = _num(_get(parts, 18))
            materialy_current = _num(_get(parts, 19))
            section = current_section
            subsection = current_subsection
            source_row = line_num

            last = Position(
                num=num,
                code=code,
                unit=unit,
                name=name,
                price_base=price_base,
                qty=qty,
                resources=Resources(
                    zarplata_base=zarplata_base,
                    ekspl_mashin_base=ekspl_mashin_base,
                    zp_mashinistov_base=zp_mashinistov_base,
                    materialy_base=materialy_base,
                    zatraty_truda_qty=zatraty_truda_qty,
                    zarplata_current=zarplata_current,
                    ekspl_mashin_current=ekspl_mashin_current,
                    zp_mashinistov_current=zp_mashinistov_current,
                    materialy_current=materialy_current,
                ),
                section=section,
                subsection=subsection,
                source_row=source_row,
            )
            positions.append(last)   # без этого позиции создавались и терялись
            # Промежуточные величины
            pz_unit = _num(_get(parts, 15))
            ozp_unit = _num(_get(parts, 16))
            zpm_unit = _num(_get(parts, 18))
            nr_koef = None
            sp_koef = None
        elif kind == "25":
            # Коэффициенты
            kind_koef = _get(parts, 1)
            value = _num(_get(parts, 4))
            if kind_koef == "2" and nr_koef is None:
                nr_koef = value
            elif kind_koef == "3":
                sp_koef = value

    _finish()

    # Итог документа в АРПС не хранится. Подставлять сюда сумму позиций нельзя:
    # сверка сравнивала бы величину саму с собой и всегда показывала «норма».
    totals = Totals()

    warnings = []
    if not positions:
        warnings.append("не найдено записей типа 20 — файл не похож на АРПС 1.10")
    warnings.append("итог позиции вычислен по формуле ПЗ + НР + СП: в формате АРПС он не хранится")
    warnings.append("итог документа в АРПС не хранится — сверка с суммой позиций невозможна")

    return Smeta(
        path=path,
        fmt=SmetaFormat.ARPS,
        smeta_num=smeta_name,
        positions=positions,
        totals=totals,
        warnings=warnings,
    )
