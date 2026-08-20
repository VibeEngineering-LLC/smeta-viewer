"""#SMETA-5: сравнение двух смет — добавленные, удалённые, изменённые позиции.

Ключ сопоставления — Position.match_key() = (раздел, шифр, наименование). Раздел
входит в ключ потому, что одна расценка встречается в смете многократно в разных
разделах. Плата за это: позиция, перенесённая между разделами, показывается как
удалённая и добавленная — выбран этот
вариант как наименее склонный к ложным совпадениям.

Одинаковый ключ может повторяться внутри одной сметы (та же расценка дважды в одном
разделе с разными объёмами), поэтому позиции группируются в СПИСКИ, и внутри группы
сопоставляются по порядку.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sv.model import Position, Smeta


@dataclass
class Change:
    kind: str
    left: Position | None = None
    right: Position | None = None
    fields: list[str] = field(default_factory=list)

    def delta(self) -> float:
        """Разница по total_current. None у позиции трактуется как 0.

        Раньше метод мог вернуть None (позиция без итога — норма для .sobx и для
        обрезанных файлов), после чего sort_key падал на -abs(None) прямо в слоте
        кнопки «Сравнить»: окно оставалось пустым без всякого сообщения.
        """
        left_val = (self.left.total_current or 0.0) if self.left else 0.0
        right_val = (self.right.total_current or 0.0) if self.right else 0.0
        if self.kind == "added":
            return right_val
        if self.kind == "removed":
            return -left_val
        return right_val - left_val


    def title(self) -> str:
        pos = self.right or self.left
        if not pos:
            return ""
        code = pos.code or ""
        name = pos.name or ""
        if len(name) > 80:
            name = name[:77] + "..."
        return f"{code} · {name}"


@dataclass
class CompareResult:
    changes: list[Change] = field(default_factory=list)
    left_total: float = 0.0
    right_total: float = 0.0
    unchanged_count: int = 0

    def added(self) -> list[Change]:
        return [c for c in self.changes if c.kind == "added"]

    def removed(self) -> list[Change]:
        return [c for c in self.changes if c.kind == "removed"]

    def changed(self) -> list[Change]:
        return [c for c in self.changes if c.kind == "changed"]

    def delta_total(self) -> float:
        return self.right_total - self.left_total

    def delta_by_changes(self) -> float:
        return sum(c.delta() for c in self.changes)


def _diff_fields(l: Position, r: Position) -> list[str]:
    fields = []
    if abs((l.qty or 0) - (r.qty or 0)) > 1e-6:
        fields.append("количество")
    if l.unit.strip().casefold() != r.unit.strip().casefold():
        fields.append("единица")
    if abs((l.total_current or 0) - (r.total_current or 0)) > 0.01:
        fields.append("стоимость")
    if abs((l.price_base or 0) - (r.price_base or 0)) > 0.01:
        fields.append("цена")
    return fields


def compare(left: Smeta, right: Smeta, qty_tol: float = 1e-6, money_tol: float = 0.01) -> CompareResult:
    def group_positions(smeta: Smeta) -> dict[tuple, list[Position]]:
        groups = {}
        for pos in smeta.positions:
            key = pos.match_key()
            if key not in groups:
                groups[key] = []
            groups[key].append(pos)
        return groups

    left_groups = group_positions(left)
    right_groups = group_positions(right)

    all_keys = set(left_groups.keys()) | set(right_groups.keys())
    result = CompareResult()

    for key in all_keys:
        l_items = left_groups.get(key, [])
        r_items = right_groups.get(key, [])

        min_len = min(len(l_items), len(r_items))
        i = 0

        # Сравниваем по парам
        while i < min_len:
            l_pos = l_items[i]
            r_pos = r_items[i]
            diff_fields = _diff_fields(l_pos, r_pos)
            if not diff_fields:
                result.unchanged_count += 1
            else:
                result.changes.append(
                    Change("changed", left=l_pos, right=r_pos, fields=diff_fields)
                )
            i += 1

        # Добавляем оставшиеся элементы из левой сметы
        for pos in l_items[i:]:
            result.changes.append(Change("removed", left=pos))

        # Добавляем оставшиеся элементы из правой сметы
        for pos in r_items[i:]:
            result.changes.append(Change("added", right=pos))

    result.left_total = left.sum_positions_current()
    result.right_total = right.sum_positions_current()

    # Сортировка: сначала удалённые, потом добавленные, потом изменённые
    # внутри группы — по убыванию модуля delta()
    def sort_key(change):
        order = {"removed": 0, "added": 1, "changed": 2}
        return (order[change.kind], -abs(change.delta()))

    result.changes.sort(key=sort_key)

    return result


def _m(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def format_report(res: CompareResult, left_title: str = "", right_title: str = "") -> str:
    lines = []
    if left_title or right_title:
        lines.append(f"Сравнение смет: {left_title} ↔ {right_title}")
    lines.append(f"позиций совпало: {res.unchanged_count}")

    def add_group(group_name: str, changes: list[Change], sign: str):
        if not changes:
            return
        lines.append(f"{group_name}: {len(changes)}")
        for change in changes:
            delta_val = change.delta()
            # delta() уже возвращает знаковое число, а _m() печатает минус:
            # добавление своего знака давало в отчёте «-   -210 576,00».
            sign_str = "+" if delta_val > 0 else ""
            formatted_delta = _m(delta_val)
            title = change.title()
            if change.kind == "changed" and change.fields:
                fields_str = ", ".join(change.fields)
                lines.append(f"  {sign_str}{formatted_delta:>14}  {title} ({fields_str})")
            else:
                lines.append(f"  {sign_str}{formatted_delta:>14}  {title}")

    add_group("удалено", res.removed(), "-")
    add_group("добавлено", res.added(), "+")
    add_group("изменено", res.changed(), " ")

    left_total = _m(res.left_total)
    right_total = _m(res.right_total)
    delta_total = _m(res.delta_total())
    lines.append(f"итог первой: {left_total} ₽, итог второй: {right_total} ₽, разница: {delta_total} ₽")

    return "\n".join(lines)
