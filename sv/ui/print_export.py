"""#SMETA-7: печать сметы и экспорт в PDF.

HTML-форма собирается один раз в build_html() и используется и печатью, и PDF —
единый источник разметки, как _current_header_text в waterfall-viewer/panels.py
избавляет от рассинхронизации между двумя путями показа одних и тех же данных.
"""
from __future__ import annotations

import html

from PySide6 import QtGui, QtWidgets
from PySide6.QtPrintSupport import QPrintDialog, QPrinter

from sv.model import Smeta

# Доли ширины 12 колонок печатной формы, в процентах; сумма = 100.
# Пропорции сняты с эталонной печатной формы: наименованию отдаётся треть листа,
# служебным колонкам — минимум.
COL_WIDTHS = (3, 8, 31, 4, 5, 7, 3, 10, 8, 4, 12, 5)


def _fmt_money(v: float | None) -> str:
    if v is None:
        return ""
    return f"{v:,.2f}".replace(",", " ").replace(".", ",")


def _fmt_qty(v: float | None) -> str:
    if v is None:
        return ""
    if v == int(v):
        return f"{int(v):g}".replace(".", ",")
    return f"{v:g}".replace(".", ",")


def _escape(s: str) -> str:
    return html.escape(s or "", quote=False)


def build_html(smeta: Smeta) -> str:
    lines = []

    lines.append('<html><body style="font-family: Arial, sans-serif; font-size: 9pt;">')

    # Заголовок
    title = next((s for s in [smeta.smeta_num, smeta.work_name, smeta.object_name] if s), "Смета")
    lines.append(f'<h3 style="text-align:center;">{_escape(title)}</h3>')

    # Подзаголовок
    if smeta.object_name:
        lines.append(f'<p style="text-align:center; font-style: italic;">{_escape(smeta.object_name)}</p>')

    # Таблица итогов
    lines.append('<table style="margin: 8px auto;">')
    for label, base, current in smeta.totals.rows():
        base_str = _fmt_money(base / 1000) + " тыс.руб." if base is not None else ""
        current_str = _fmt_money(current / 1000) + " тыс.руб." if current is not None else ""
        bold = '<b>' if 'Сметная стоимость' in label else ''
        lines.append(f'<tr><td>{label}</td><td align="right">{bold}{base_str}</td><td align="right">{bold}{current_str}</td></tr>')
    lines.append('</table>')

    # Основная таблица
    lines.append('<table border="1" cellspacing="0" cellpadding="2" width="100%" style="font-size: 7pt; border-collapse: collapse;">')

    # Заголовок таблицы. Ширина колонки задаётся атрибутом width прямо на <th>:
    # <colgroup> QTextDocument игнорирует, и 12 колонок делились почти поровну —
    # «Наименование» получало ~6% ширины, разваливалось на десятки строк, и
    # эталонная смета печаталась на 185 страницах вместо 38.
    # Подписи заголовков намеренно короткие: длинные («Коэфф. пересчёта») в узкой
    # колонке рвались по слогам на четыре строки и раздували шапку таблицы.
    header = ['№', 'Шифр', 'Наименование', 'Ед.изм.', 'Кол-во', 'Цена', 'К-т', 'Стоимость баз.', 'Пункт', 'Индекс', 'Стоимость тек.', 'ЗТР']
    lines.append('<tr style="font-weight:bold; background:#eee;">')
    for h, w in zip(header, COL_WIDTHS):
        lines.append(f'<th width="{w}%">{h}</th>')
    lines.append('</tr>')

    for section in smeta.sections():
        lines.append(f'<tr><td colspan="12" style="font-weight:bold; padding-top:6px;">Раздел: {_escape(section.name)}</td></tr>')
        prev_subsection = ""
        for position in section.positions:
            if position.subsection and position.subsection != prev_subsection:
                lines.append(f'<tr><td colspan="12" style="font-weight:bold; font-style:italic;">Подраздел: {_escape(position.subsection)}</td></tr>')
                prev_subsection = position.subsection

            # Строка позиции
            # Колонки 7/9/10 (коэффициент, пункт коэффициента пересчёта, сам
            # коэффициент) в печатной форме заполнены именно в строке позиции —
            # оставлять их пустыми значило бы отдать 17 % ширины листа ни подо что.
            lines.append(
                f'<tr><td>{position.num}</td><td>{_escape(position.code)}</td><td>{_escape(position.name)}</td>'
                f'<td>{_escape(position.unit)}</td><td align="right">{_fmt_qty(position.qty)}</td>'
                f'<td align="right">{_fmt_money(position.price_base)}</td>'
                f'<td>{_escape(position.coef or "")}</td><td></td>'
                f'<td>{_escape(position.index_point or "")}</td>'
                f'<td align="right">{_fmt_qty(position.index)}</td><td></td><td></td></tr>'
            )

            # Ресурсные строки
            for label, base, current in position.resources.rows():
                lines.append(
                    f'<tr style="color:#777; font-style:italic;"><td></td><td></td>'
                    f'<td>&nbsp;&nbsp;&nbsp;&nbsp;{_escape(label)}</td><td></td><td></td><td></td>'
                    f'<td></td><td align="right">{_fmt_money(base)}</td><td></td><td></td>'
                    f'<td align="right">{_fmt_money(current)}</td><td></td></tr>'
                )

            # Примечание
            if position.note:
                lines.append(f'<tr style="color:#777; font-style:italic; font-size:7pt;"><td colspan="12">{_escape(position.note)}</td></tr>')

            # Итог позиции
            lines.append(
                f'<tr style="font-weight:bold;"><td colspan="7"></td>'
                f'<td align="right">{_fmt_money(position.total_base)}</td><td colspan="2"></td>'
                f'<td align="right">{_fmt_money(position.total_current)}</td><td align="right">{_fmt_money(position.labor)}</td></tr>'
            )

    lines.append('</table>')
    lines.append('</body></html>')

    return "\n".join(lines)


def _build_printer() -> QPrinter:
    printer = QPrinter(QPrinter.HighResolution)
    printer.setPageOrientation(QtGui.QPageLayout.Portrait)
    printer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.A4))
    return printer


def export_pdf(smeta: Smeta, path: str) -> None:
    printer = _build_printer()
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    doc = QtGui.QTextDocument()
    doc.setHtml(build_html(smeta))
    doc.print_(printer)


def print_smeta(smeta: Smeta, parent: QtWidgets.QWidget | None = None) -> bool:
    printer = _build_printer()
    dlg = QPrintDialog(printer, parent)
    if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return False
    doc = QtGui.QTextDocument()
    doc.setHtml(build_html(smeta))
    doc.print_(printer)
    return True
