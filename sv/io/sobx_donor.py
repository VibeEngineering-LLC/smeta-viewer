"""#SMETA-8: чтение файла-донора .sobx для генератора.

Донор — рабочий файл, выгруженный самой Смета.РУ. Из него берутся справочники,
служебные датасеты и СТРОКИ-ШАБЛОНЫ позиций: в позиции 144 поля, в строке цен 151,
и смысл большинства не установлен. Наследование даёт им заведомо рабочие значения.

CRC в B_NNAME — знаковый CRC32 от наименования в кодировке cp1251. Проверено на
доноре: совпало 432 из 432 строк с непустым именем (utf-8 и adler32 не совпали ни
разу). Поэтому новые наименования получают вычисленный CRC, а не ноль.
"""
from __future__ import annotations

import json
import re
import zipfile
import zlib


def name_crc(name: str) -> int:
    """Знаковый CRC32 наименования в cp1251 — как в B_NNAME донора."""
    raw = zlib.crc32((name or "").encode("cp1251", errors="replace"))
    return raw - 2**32 if raw >= 2**31 else raw


class Donor:
    """Прочитанный в память файл-донор: датасеты, справочники, шаблоны."""

    def __init__(self, path: str):
        self.path = path
        self.datasets: dict[str, dict] = {}
        self.unreadable = []
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                try:
                    text = zf.read(name).decode("cp1251")
                    d = json.loads(text, strict=False)
                    self.datasets[name] = {
                        "fields": d["Fields"],
                        "indexes": d.get("Indexes") or [],
                        "data": d.get("Data") or []
                    }
                except Exception:
                    self.unreadable.append(name)
        self._detect_ids()

    def _detect_ids(self):
        """Определяет идентификаторы объекта и типа сметы по имени файла."""
        self.obj_id = None
        self.smeta_type = None
        self.smeta_table = None
        self.cenlvl_table = None
        self.viewnum_table = None

        pattern_smeta = re.compile(r"^A_SMETA_(\d+)_(\d+)\.json$")
        pattern_cenlvl = re.compile(r"^A_SMETA_CENLVL_(\d+)_(\d+)\.json$")
        pattern_viewnum = re.compile(r"^A_SMETA_VIEW_NUM_(\d+)_(\d+)\.json$")

        for name in self.datasets:
            match = pattern_smeta.match(name)
            if match:
                self.smeta_table = name
                self.obj_id = int(match.group(1))
                self.smeta_type = int(match.group(2))

            match = pattern_cenlvl.match(name)
            if match:
                self.cenlvl_table = name

            match = pattern_viewnum.match(name)
            if match:
                self.viewnum_table = name

    def fields(self, name: str) -> list[dict]:
        """Поля датасета."""
        return self.datasets.get(name, {}).get("fields", [])

    def indexes(self, name: str) -> list[dict]:
        """Индексы датасета."""
        return self.datasets.get(name, {}).get("indexes", [])

    def rows(self, name: str) -> list[dict]:
        """Строки датасета словарями {имя поля: значение}. Значения НЕ декодируются —
        дробные остаются в виде "$hex", как в файле: то, что уходит обратно без изменений, не
        должно проходить через преобразование туда-обратно."""
        ds = self.datasets.get(name)
        if not ds:
            return []
        names = [f["Name"] for f in ds["fields"]]
        result = []
        for row in ds["data"]:
            row_dict = dict(zip(names, row))
            # Заполнить недостающие поля None
            for i in range(len(names)):
                if i >= len(row):
                    row_dict[names[i]] = None
            result.append(row_dict)
        return result

    def template(self, name: str, **match) -> dict | None:
        """Первая строка датасета, у которой поля равны переданным значениям.
        Служит образцом для новых строк: `donor.template(donor.smeta_table, RABMAT=0)`."""
        rows = self.rows(name)
        if not match:
            return rows[0] if rows else None
        for row in rows:
            if all(row.get(k) == v for k, v in match.items()):
                return row
        return None

    def names_index(self) -> dict[str, int]:
        """Наименование → ID из B_NNAME (для повторного использования существующих
        записей справочника)."""
        return {row["NAME"]: row["ID"] for row in self.rows("B_NNAME.json") if row.get("NAME")}

    def units_index(self) -> dict[str, int]:
        """Единица измерения → ID из B_EDIZM, ключ приведён к нижнему регистру."""
        return {
            str(row["NAME"]).strip().casefold(): row["ID"]
            for row in self.rows("B_EDIZM.json")
            if row.get("NAME")
        }

    def max_id(self, name: str, field: str = "ID") -> int:
        """Максимальное целое значение поля в датасете."""
        rows = self.rows(name)
        if not rows:
            return 0
        max_val = 0
        for row in rows:
            val = row.get(field)
            if isinstance(val, int) and val > max_val:
                max_val = val
        return max_val
