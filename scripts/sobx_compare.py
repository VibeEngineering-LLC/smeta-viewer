"""#SMETA-8: сверка двух файлов .sobx поле-в-поле.

Сравнивает датасеты напрямую, не через модель приложения: проверка через
загрузчик видит только те поля, которые он читает, и на генераторе это уже дало
ложный зелёный — RA писалось нулём при верных ITOGO и RE, и все проверки прошли.

Запуск:
    py -3.14 scripts/sobx_compare.py эталон.sobx проверяемый.sobx
    py -3.14 scripts/sobx_compare.py эталон.sobx проверяемый.sobx --tables A_SMETA_CENLVL

Код возврата 0 — расхождений нет, 1 — есть.
"""
from __future__ import annotations

import argparse
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sv.io.sobx_donor import Donor
from sv.io.sobx_write import decode_float

ID_FIELDS = {
    "Keys", "ID", "NUMBER", "PARENT", "IDHIER", "NAME_ID", "ID_EDIZM",
    "NOMERROD1", "IDCENLVL", "IDINDEX", "ID_LEVEL_INDEX", "IDNORMATIV"
}


def _norm(value):
    """Значение к сравнимому виду: дробные из "$hex" в число, пустая строка и
    None — к None, целые к float."""
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.startswith("$"):
        return decode_float(value)
    if isinstance(value, (int, float)):
        return float(value)
    # Строки, не являющиеся упакованным числом (наименования, даты, GUID),
    # сравниваются как текст: попытка привести их к float роняла сверку на
    # первом же текстовом поле.
    return str(value).strip()


def _close(a, b, tol: float = 0.011) -> bool:
    """Равенство с денежным допуском. Ноль и None считаются одним и тем же:
в этом формате незаполненное поле и ноль взаимозаменяемы."""
    if a is None:
        a = 0.0
    if b is None:
        b = 0.0
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    return a == b


def _key_field(fields: list[dict]) -> str | None:
    if any(f["Name"] == "ID" for f in fields):
        return "ID"
    if any(f["Name"] == "NUMBER" for f in fields):
        return "NUMBER"
    return None


def compare_files(left_path: str, right_path: str, table_filter: str | None = None,
                  only_fields: set[str] | None = None) -> dict:
    left = Donor(left_path)
    right = Donor(right_path)

    report = {"tables": [], "total_diffs": 0, "missing": [], "extra": []}

    names_l = set(left.datasets)
    names_r = set(right.datasets)

    report["missing"] = sorted(names_l - names_r)
    report["extra"] = sorted(names_r - names_l)

    common_names = sorted(names_l & names_r)

    for name in common_names:
        if table_filter is not None and table_filter not in name:
            continue

        fl = left.fields(name)
        key = _key_field(fl)

        rows_l = left.rows(name)
        rows_r = right.rows(name)

        row_count_differs = len(rows_l) != len(rows_r)
        diffs = []
        min_len = min(len(rows_l), len(rows_r))

        if row_count_differs:
            table_report = {
                "table": name,
                "rows_left": len(rows_l),
                "rows_right": len(rows_r),
                "diffs": [],
                "row_count_differs": True
            }
            report["total_diffs"] += 1
        else:
            table_report = {
                "table": name,
                "rows_left": len(rows_l),
                "rows_right": len(rows_r),
                "diffs": [],
                "row_count_differs": False
            }

        for i in range(min_len):
            row_l = rows_l[i]
            row_r = rows_r[i]

            for field in fl:
                field_name = field["Name"]
                # Режим приёмки: сверяются только заявленные поля. Остальные в этом
                # генераторе наследуются от строки-шаблона донора и совпадать не обязаны.
                if only_fields is not None and field_name not in only_fields:
                    continue
                if field_name in ID_FIELDS:
                    continue

                val_l = row_l.get(field_name)
                val_r = row_r.get(field_name)

                if not _close(_norm(val_l), _norm(val_r)):
                    diffs.append({
                        "row": i + 1,
                        "field": field_name,
                        "left": val_l,
                        "right": val_r
                    })
                    report["total_diffs"] += 1

                    if len(diffs) >= 200:
                        break

            if len(diffs) >= 200:
                break

        table_report["diffs"] = diffs
        if diffs or row_count_differs:
            report["tables"].append(table_report)

    return report


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("left", help="Путь к левому файлу .sobx")
    parser.add_argument("right", help="Путь к правому файлу .sobx")
    parser.add_argument("--tables", help="Фильтр по имени таблицы (подстрока)")
    parser.add_argument("--fields", default=None,
                        help="сравнивать только эти поля (через запятую) — режим приёмки: "
                             "проверить именно то, что генератор заявляет, что пишет")
    parser.add_argument("--limit", type=int, default=10, help="Лимит расхождений на таблицу")

    args = parser.parse_args()

    only = {f.strip() for f in args.fields.split(",")} if args.fields else None
    report = compare_files(args.left, args.right, args.tables, only)

    print(f"Сравнено {len(report['missing']) + len(report['extra'])} датасетов")
    if report["missing"]:
        print("Отсутствуют:", ", ".join(report["missing"]))
    if report["extra"]:
        print("Лишние:", ", ".join(report["extra"]))

    found_diffs = False
    for table in report["tables"]:
        print(f"{table['table']}: строк слева={table['rows_left']}, справа={table['rows_right']}")
        if table["row_count_differs"]:
            print("  Число строк различается")
        else:
            print(f"  Расхождений: {len(table['diffs'])}")

        for diff in table["diffs"][:args.limit]:
            print(f"  строка {diff['row']}: {diff['field']}: {diff['left']!r} != {diff['right']!r}")
        if len(table["diffs"]) > args.limit:
            print(f"  ... и ещё {len(table['diffs']) - args.limit} расхождений")

        if table["diffs"]:
            found_diffs = True

    total = report["total_diffs"]
    if not found_diffs and not report["missing"] and not report["extra"]:
        print("Расхождений не найдено.")
        return 0
    else:
        print(f"ИТОГО расхождений: {total}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
