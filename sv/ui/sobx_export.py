"""#SMETA-8: экспорт открытой сметы в .sobx через интерфейс.

Генератору нужен файл-донор — рабочий .sobx, выгруженный самой Смета.РУ: из него
наследуются служебные датасеты и поля, смысл которых не установлен. Поэтому шагов
два: сначала донор, потом куда сохранить.

Результат показывается вместе с границами применимости. Умолчание здесь такое:
пользователю, который собирается отдать файл в сметную программу, важнее знать, что
именно не проверено, чем увидеть бодрое «готово».
"""
from __future__ import annotations

from PySide6 import QtWidgets, QtCore

from sv.io.sobx_donor import Donor
from sv.io.sobx_gen import build_sobx
from sv.model import Smeta


LIMITS_TEXT = (
    "Что важно знать об этом файле:\n\n"
    "• Служебные данные унаследованы от донора — реквизиты объекта, подписанты и "
    "нормативная база в новом файле те же, что в нём.\n"
    "• Индексы пересчёта восстановлены из сумм делением: суммы записаны точно, "
    "но при пересчёте импортирующей программой возможны расхождения в копейки.\n"
    "• Одноимённые подразделы внутри одного раздела объединяются в один.\n"
    "• Приём файла самой Смета.РУ не проверялся."
)


def _money(value: float) -> str:
    """Форматирует сумму с неразрывным пробелом и запятой как десятичным разделителем."""
    return f"{value:,.2f}".replace(",", " ").replace(" ", " ")


def export_to_sobx(smeta: Smeta, parent: QtWidgets.QWidget | None = None) -> bool:
    """Провести пользователя через экспорт. True — файл записан."""
    if not smeta.positions:
        QtWidgets.QMessageBox.warning(
            parent,
            "Экспорт в .sobx",
            "В смете нет позиций — экспортировать нечего."
        )
        return False

    QtWidgets.QMessageBox.information(
        parent,
        "Нужен файл-образец",
        "Для записи .sobx нужен образец — любой рабочий файл .sobx, выгруженный из "
        "Смета.РУ.\n\nИз него берутся служебные разделы файла, которые не хранятся в "
        "открытой смете. Данные позиций будут взяты из текущего документа, а не из "
        "образца."
    )

    donor_path, _ = QtWidgets.QFileDialog.getOpenFileName(
        parent,
        "Выберите файл-образец .sobx",
        "",
        "Файлы Смета.РУ (*.sobx);;Все файлы (*)"
    )
    if not donor_path:
        return False

    try:
        donor = Donor(donor_path)
    except Exception as exc:
        QtWidgets.QMessageBox.critical(
            parent,
            "Ошибка чтения",
            f"Не удалось прочитать файл-образец:\n{donor_path}\n\n{exc}"
        )
        return False

    if not donor.smeta_table or donor.obj_id is None:
        QtWidgets.QMessageBox.critical(
            parent,
            "Ошибка чтения",
            "Это не похоже на файл объекта Смета.РУ: в архиве нет таблицы позиций."
        )
        return False

    save_path, _ = QtWidgets.QFileDialog.getSaveFileName(
        parent,
        "Сохранить как .sobx",
        "",
        "Файлы Смета.РУ (*.sobx)"
    )
    if not save_path:
        return False

    if not save_path.lower().endswith(".sobx"):
        save_path += ".sobx"

    try:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        stats = build_sobx(smeta, donor, save_path)
    except Exception as exc:
        QtWidgets.QMessageBox.critical(
            parent,
            "Ошибка записи",
            f"Не удалось записать файл:\n{exc}"
        )
        return False
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()

    total = smeta.total
    message_lines = [
        f"Записано позиций: {stats['positions']}, разделов: {stats['sections']}.",
        f"Сумма в текущих ценах: {total:,.2f} ₽."
    ]

    warnings = stats.get("warnings")
    if warnings:
        message_lines.append("")
        message_lines.extend(warnings)

    msg_box = QtWidgets.QMessageBox(
        QtWidgets.QMessageBox.Information,
        "Файл записан",
        "\n".join(message_lines)
    )
    msg_box.setDetailedText(LIMITS_TEXT)
    msg_box.exec()
    return True
