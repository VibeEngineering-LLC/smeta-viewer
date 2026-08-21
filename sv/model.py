"""#SMETA-1: модель сметного документа — единое представление всех форматов.

Загрузчики из sv/io/ приводят .xlsx (Смета.РУ и ЛСР 421/пр), .sobx и .arp к этим
структурам; UI и проверки работают только с моделью и о форматах не знают.

ЕДИНИЦЫ: в позициях деньги — РУБЛИ, в шапке печатной формы
итоги напечатаны в ТЫСЯЧАХ рублей. В модели всё хранится в РУБЛЯХ; перевод делает
загрузчик, а не потребитель. Смешение даёт ошибку ровно в 1000 раз при внешне
правдоподобной таблице.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SmetaFormat(str, Enum):
    SMETARU_XLSX = "smetaru_xlsx"    # форма «Смета 12 гр. по ФЕР», экспорт Смета.РУ
    LSR_XLSX = "lsr_xlsx"            # входящая ЛСР по Методике 421/пр
    SOBX = "sobx"                    # экспорт объекта Смета.РУ (ZIP с дампами таблиц)
    ARPS = "arps"                    # обменный формат АРПС 1.10
    UNKNOWN = "unknown"


@dataclass
class Resources:
    zarplata_base: float | None = None
    zarplata_current: float | None = None
    ekspl_mashin_base: float | None = None
    ekspl_mashin_current: float | None = None
    zp_mashinistov_base: float | None = None
    zp_mashinistov_current: float | None = None
    materialy_base: float | None = None
    materialy_current: float | None = None
    nr_percent: float | None = None
    nr_base: float | None = None
    nr_current: float | None = None
    sp_percent: float | None = None
    sp_base: float | None = None
    sp_current: float | None = None
    zatraty_truda_qty: float | None = None
    zatraty_truda_value: float | None = None

    def is_empty(self) -> bool:
        """True, если ВСЕ поля равны None."""
        return all(v is None for v in self.__dict__.values())

    def rows(self) -> list[tuple[str, float | None, float | None]]:
        """Возвращает список (подпись, базис, текущая) только для заполненных составляющих."""
        result = []
        fields = [
            ("Зарплата", "zarplata_base", "zarplata_current"),
            ("Эксплуатация машин", "ekspl_mashin_base", "ekspl_mashin_current"),
            ("в т.ч. зарплата машинистов", "zp_mashinistov_base", "zp_mashinistov_current"),
            ("Материальные ресурсы", "materialy_base", "materialy_current"),
            ("Накладные расходы", "nr_base", "nr_current"),
            ("Сметная прибыль", "sp_base", "sp_current"),
            ("Затраты труда", "zatraty_truda_qty", "zatraty_truda_value")
        ]
        for label, base_field, current_field in fields:
            base_val = getattr(self, base_field)
            current_val = getattr(self, current_field)
            if base_val is not None or current_val is not None:
                result.append((label, base_val, current_val))
        return result


@dataclass
class Position:
    num: str = ""
    code: str = ""
    name: str = ""
    unit: str = ""
    qty: float | None = None
    price_base: float | None = None
    coef: str | None = None  # ВАЖНО: строка, а не число. В Смета.РУ это выражение вида `")*1,22"`
    cost_base: float | None = None
    index_point: str | None = None
    index: float | None = None
    cost_current: float | None = None
    total_base: float | None = None
    total_current: float | None = None
    labor: float | None = None
    section: str = ""
    subsection: str = ""
    resources: Resources = field(default_factory=Resources)
    note: str = ""              # пояснение из формы, напр. «Объем: 0,1=1/10»
    source_row: int | None = None  # строка исходного файла, для отладки и перехода к источнику

    def is_price_item(self) -> bool:
        """True, если `code` пустой ИЛИ содержит `"прайс"` без учёта регистра."""
        return not self.code or "прайс" in self.code.casefold()

    def match_key(self) -> tuple[str, str, str]:
        """
        Ключ сопоставления позиций при сравнении редакций: (section, code, name).
        Ключ включает раздел, потому что одна расценка встречается в смете многократно
        в разных разделах; при переносе позиции между разделами она будет показана как
        удалённая и добавленная — это осознанный осознанный компромисс.
        """
        return (self.section.strip().casefold(), self.code.strip().casefold(), self.name.strip().casefold())


@dataclass
class Section:
    name: str = ""
    subsections: list[str] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)

    def total_current(self) -> float:
        """Сумма `total_current` позиций, None считать нулём."""
        return sum(p.total_current or 0 for p in self.positions)

    def total_base(self) -> float:
        """Сумма `total_base` позиций, None считать нулём."""
        return sum(p.total_base or 0 for p in self.positions)


@dataclass
class Totals:
    total_base: float | None = None
    total_current: float | None = None
    construction_base: float | None = None
    construction_current: float | None = None
    installation_base: float | None = None
    installation_current: float | None = None
    equipment_base: float | None = None
    equipment_current: float | None = None
    other_base: float | None = None
    other_current: float | None = None
    labor_base: float | None = None
    labor_current: float | None = None
    wages_base: float | None = None
    wages_current: float | None = None

    def rows(self) -> list[tuple[str, float | None, float | None]]:
        """Для панели итогов, только заполненные, в порядке."""
        result = []
        fields = [
            ("Сметная стоимость", "total_base", "total_current"),
            ("Строительные работы", "construction_base", "construction_current"),
            ("Монтажные работы", "installation_base", "installation_current"),
            ("Оборудование", "equipment_base", "equipment_current"),
            ("Прочие затраты", "other_base", "other_current"),
            ("Трудоёмкость, чел.-ч", "labor_base", "labor_current"),
            ("Средства на оплату труда", "wages_base", "wages_current")
        ]
        for label, base_field, current_field in fields:
            base_val = getattr(self, base_field)
            current_val = getattr(self, current_field)
            if base_val is not None or current_val is not None:
                result.append((label, base_val, current_val))
        return result


@dataclass
class Smeta:
    path: str = ""
    fmt: SmetaFormat = SmetaFormat.UNKNOWN
    object_name: str = ""
    work_name: str = ""
    smeta_num: str = ""
    positions: list[Position] = field(default_factory=list)
    totals: Totals = field(default_factory=Totals)
    # Итоги «Итого по разделу/подразделу», как они напечатаны в форме:
    # {название: (базис, текущая)}. Нужны для сверки и панели итогов.
    section_totals: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)  # сообщения загрузчика

    def title(self) -> str:
        """Для заголовка вкладки: первое непустое из smeta_num, work_name, object_name;
        если все пусты — имя файла из path без каталога."""
        for attr in ["smeta_num", "work_name", "object_name"]:
            if getattr(self, attr):
                return getattr(self, attr)
        # Имя файла без пути
        return self.path.replace("\\", "/").rsplit("/", 1)[-1]

    def sections(self) -> list[Section]:
        """Сгруппировать позиции по полю `section`, СОХРАНЯЯ порядок первого появления."""
        section_map = {}
        # Ключ множества — ПАРА (раздел, подраздел), а не одно имя подраздела.
        # Глобальное множество имён теряло подраздел, встречающийся в двух разделах:
        # «Узел П6/П7/П8» есть и в холодоснабжении, и в теплоснабжении, и во втором
        # разделе они не попадали в список вовсе — ни в навигацию, ни в дерево
        # генератора, куда затем сваливались их позиции.
        subsection_set = set()
        for pos in self.positions:
            sec_name = pos.section
            if not sec_name:
                continue
            if sec_name not in section_map:
                section_map[sec_name] = Section(name=sec_name)
            section = section_map[sec_name]
            if pos.subsection and (sec_name, pos.subsection) not in subsection_set:
                section.subsections.append(pos.subsection)
                subsection_set.add((sec_name, pos.subsection))
            section.positions.append(pos)
        return list(section_map.values())

    def sum_positions_current(self) -> float:
        """Сумма `total_current` по всем позициям (None = 0)."""
        return sum(p.total_current or 0 for p in self.positions)

    def sum_positions_base(self) -> float:
        """Сумма `total_base` по всем позициям (None = 0)."""
        return sum(p.total_base or 0 for p in self.positions)

    def section_count(self) -> int:
        """Число уникальных непустых разделов."""
        return len(set(p.section for p in self.positions if p.section))

    def subsection_count(self) -> int:
        """Число уникальных непустых подразделов."""
        return len(set(p.subsection for p in self.positions if p.subsection))
