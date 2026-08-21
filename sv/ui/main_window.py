"""#SMETA-1: главное окно просмотрщика смет.

Несколько документов одновременно — вкладками; список недавних файлов; открытие
по Ctrl+O и перетаскиванием файла в окно. Формат определяется по расширению и
содержимому, а не по имени.
"""
from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets

from sv.io.arps import load as load_arps
from sv.io.export_xlsx import export_smeta_xlsx
from sv.io.lsr_xlsx import load as load_lsr
from sv.io.lsr_xlsx import looks_like_lsr
from sv.io.smetaru_xlsx import load as load_smetaru
from sv.io.sobx import load as load_sobx
from sv.ui.smeta_tab import SmetaTab
from sv.ui import theme
from sv.ui.compare_dialog import CompareDialog
from sv.ui.print_export import export_pdf, print_smeta
from sv.ui.sobx_export import export_to_sobx

MAX_RECENT = 10
ORG = "VibeEngineering-LLC"
APP = "SmetaViewer"


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Просмотрщик смет")
        self.resize(1480, 900)
        self._settings = QtCore.QSettings(ORG, APP)
        # Тему применяем ПОСЛЕ сборки вкладок: _apply_theme обходит открытые
        # документы, а на этом шаге self._tabs ещё не существует.
        theme.set_current(self._settings.value("theme", theme.DEFAULT_THEME))

        # Центральный виджет — вкладки
        self._tabs = QtWidgets.QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)

        # Подсказка при отсутствии вкладок
        self._hint = QtWidgets.QLabel(
            "Откройте файл сметы: Ctrl+O, либо перетащите его в окно\n\nПоддерживаются .xlsx (Смета.РУ и ЛСР), .sobx, .arp"
        )
        self._hint.setAlignment(QtCore.Qt.AlignCenter)
        self._hint.setStyleSheet("color: #9a9ca0;")

        self._stack = QtWidgets.QStackedWidget()
        self._stack.addWidget(self._hint)
        self._stack.addWidget(self._tabs)

        self.setCentralWidget(self._stack)

        # Статусбар
        self._status_sel = QtWidgets.QLabel()
        self.statusBar().addPermanentWidget(self._status_sel)

        # Меню
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("Файл")
        open_action = file_menu.addAction("Открыть...")
        open_action.setShortcut(QtGui.QKeySequence.Open)
        open_action.triggered.connect(self._open_dialog)

        self._recent_menu = file_menu.addMenu("Недавние файлы")
        self._rebuild_recent()

        file_menu.addSeparator()

        # #SMETA-7: экспорт и печать — действуют на АКТИВНУЮ вкладку; без открытых
        # документов пункты выключены, чтобы не показывать пустой диалог сохранения.
        self._act_xlsx = file_menu.addAction("Экспорт в Excel…")
        self._act_xlsx.triggered.connect(self._export_xlsx)
        self._act_pdf = file_menu.addAction("Экспорт в PDF…")
        self._act_pdf.triggered.connect(self._export_pdf)
        self._act_sobx = file_menu.addAction("Сохранить как .sobx…")
        self._act_sobx.triggered.connect(self._export_sobx)
        self._act_print = file_menu.addAction("Печать…")
        self._act_print.setShortcut(QtGui.QKeySequence.Print)
        self._act_print.triggered.connect(self._print)
        self._tabs.currentChanged.connect(self._sync_actions)

        file_menu.addSeparator()

        close_tab_action = file_menu.addAction("Закрыть вкладку")
        close_tab_action.setShortcut(QtGui.QKeySequence("Ctrl+W"))
        close_tab_action.triggered.connect(self._close_current_tab)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("Выход")
        exit_action.setShortcut(QtGui.QKeySequence.Quit)
        exit_action.triggered.connect(self.close)

        view_menu = menu_bar.addMenu("Вид")
        expand_action = view_menu.addAction("Развернуть всё")
        expand_action.setShortcut(QtGui.QKeySequence("Ctrl+E"))
        expand_action.triggered.connect(self._expand_all)

        view_menu.addSeparator()
        # #SMETA-4: выбор темы — радиогруппа, отметка соответствует действующей теме
        theme_menu = view_menu.addMenu("Тема")
        self._theme_group = QtGui.QActionGroup(self)
        self._theme_group.setExclusive(True)
        for code, title in ((theme.THEME_DARK, "Тёмная"), (theme.THEME_LIGHT, "Светлая")):
            act = theme_menu.addAction(title)
            act.setCheckable(True)
            act.setChecked(theme.current() == code)
            act.triggered.connect(lambda _checked=False, c=code: self._apply_theme(c))
            self._theme_group.addAction(act)

        collapse_action = view_menu.addAction("Свернуть всё")
        collapse_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+E"))
        collapse_action.triggered.connect(self._collapse_all)

        service_menu = menu_bar.addMenu("Сервис")
        cmp_action = service_menu.addAction("Сравнить сметы…")
        cmp_action.setShortcut(QtGui.QKeySequence("Ctrl+D"))
        cmp_action.triggered.connect(self._open_compare)

        help_menu = menu_bar.addMenu("Справка")
        about_action = help_menu.addAction("О программе")
        about_action.triggered.connect(self._show_about)

        self._apply_theme(theme.current(), save=False)
        self.setAcceptDrops(True)
        self._sync_stack()

    def _open_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Открыть файл сметы",
            self._settings.value("last_dir", ""),
            "Сметы (*.xlsx *.sobx *.arp);;Все файлы (*)"
        )
        if path:
            self.open_file(path)

    def _apply_theme(self, code: str, save: bool = True) -> None:
        """#SMETA-4: применить тему ко всему приложению.

        QSS ставится и на QApplication, и на окно: контекстные меню и всплывающие
        подсказки — попапы без родителя-виджета, стиль окна до них не каскадирует.
        Плашки контроля перекрашиваются явно — их цвет задаётся кодом, а не QSS.
        """
        theme.set_current(code)
        css = theme.qss(theme.current())
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.setStyleSheet(css)
        self.setStyleSheet(css)
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            upd = getattr(tab, "_update_check", None)
            if callable(upd):
                upd()
            view = getattr(tab, "_view", None)
            if view is not None:
                view.viewport().update()
        if save:
            self._settings.setValue("theme", theme.current())

    def open_file(self, path: str):
        # Один и тот же файл приходит из диалога как "D:\x", из drag-and-drop как
        # "D:/x": без приведения к одному виду он открывался дважды и дважды
        # попадал в список недавних.
        path = os.path.normpath(path)
        # Проверка, открыт ли файл уже
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            if hasattr(tab, 'smeta') and tab.smeta.path == path:
                self._tabs.setCurrentIndex(i)
                return

        # Определение загрузчика по расширению
        # QFileInfo.suffix() возвращает расширение БЕЗ точки ("xlsx"), сравнение с
        # ".xlsx" не срабатывало никогда и любой файл считался неизвестным форматом.
        ext = QtCore.QFileInfo(path).suffix().lower()
        if ext == "xlsx":
            # #SMETA-6: .xlsx бывает и формой Смета.РУ, и входящей ЛСР 421/пр —
            # различаем по содержимому шапки, не по имени файла.
            loader = load_lsr if looks_like_lsr(path) else load_smetaru
        elif ext == "sobx":
            loader = load_sobx
        elif ext == "arp":
            loader = load_arps
        else:
            QtWidgets.QMessageBox.critical(
                self,
                "Не удалось открыть файл",
                f"Неизвестный формат файла: {path}"
            )
            return

        # Загрузка сметы
        try:
            smeta = loader(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                "Не удалось открыть файл",
                f"{path}\n\n{exc}"
            )
            return

        # Создание вкладки
        tab = SmetaTab(smeta)
        tab.selectionSummary.connect(self._status_sel.setText)
        index = self._tabs.addTab(tab, smeta.title())
        self._tabs.setTabToolTip(index, path)

        # Запоминание каталога и обновление списка недавних
        dir_path = QtCore.QFileInfo(path).absolutePath()
        self._settings.setValue("last_dir", dir_path)
        self._add_recent(path)
        self._sync_stack()

        # Статусбар
        self.statusBar().showMessage(
            f"{smeta.title()}: позиций {len(smeta.positions)}, разделов {smeta.section_count()}",
            5000
        )

    def _open_compare(self) -> None:
        """#SMETA-5: сравнение двух открытых смет."""
        smetas = [self._tabs.widget(i).smeta for i in range(self._tabs.count())]
        if len(smetas) < 2:
            QtWidgets.QMessageBox.information(
                self, "Сравнение смет",
                "Откройте хотя бы две сметы — сравнение идёт между открытыми вкладками.")
            return
        dlg = CompareDialog(smetas, self)
        dlg.exec()

    def _close_tab(self, index: int) -> None:
        """Закрыть вкладку и освободить её.

        removeTab только снимает вкладку с панели, но виджет остаётся жить в
        родителе: после нескольких открытий-закрытий в памяти висели все копии
        сметы со всеми позициями. deleteLater отдаёт его Qt на удаление.
        """
        widget = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if widget is not None:
            # Одного deleteLater мало: пока на вкладку подписан сигнал и пока она
            # держит разобранную смету, все её позиции остаются в памяти.
            try:
                widget.selectionSummary.disconnect()
            except (RuntimeError, TypeError):
                pass
            model = getattr(widget, "_model", None)
            if model is not None:
                model.set_smeta(None)
            widget.smeta = None
            widget.setParent(None)
            widget.deleteLater()
        self._sync_stack()


    def _close_current_tab(self):
        current = self._tabs.currentIndex()
        if current >= 0:
            self._close_tab(current)

    def _add_recent(self, path):
        recent = self._settings.value("recent", [])
        try:
            recent.remove(path)
        except ValueError:
            pass
        recent.insert(0, path)
        recent = recent[:MAX_RECENT]
        self._settings.setValue("recent", recent)
        self._rebuild_recent()

    def _rebuild_recent(self):
        self._recent_menu.clear()
        recent = self._settings.value("recent", [])
        if not recent:
            action = self._recent_menu.addAction("(пусто)")
            action.setEnabled(False)
        else:
            for path in recent:
                name = QtCore.QFileInfo(path).fileName()
                action = self._recent_menu.addAction(name)
                action.setToolTip(path)
                action.triggered.connect(lambda _, p=path: self.open_file(p))

    def _sync_stack(self):
        self._stack.setCurrentIndex(1 if self._tabs.count() > 0 else 0)
        self._sync_actions()

    def _sync_actions(self):
        """#SMETA-7: пункты экспорта и печати живут только при открытом документе."""
        enabled = self._tabs.count() > 0
        for act in (self._act_xlsx, self._act_pdf, self._act_sobx, self._act_print):
            act.setEnabled(enabled)

    def _current_smeta(self):
        return getattr(self._tabs.currentWidget(), "smeta", None)

    def _suggested_name(self, ext: str) -> str:
        """Имя по умолчанию при сохранении: имя исходного файла с новым расширением."""
        smeta = self._current_smeta()
        if smeta is None:
            return ""
        base = QtCore.QFileInfo(smeta.path).completeBaseName() or "Смета"
        directory = self._settings.value("last_export_dir", "") or QtCore.QFileInfo(smeta.path).absolutePath()
        return os.path.join(directory, f"{base}{ext}")

    def _export_sobx(self):
        """#SMETA-8: запись открытой сметы в формат объекта Смета.РУ."""
        smeta = self._current_smeta()
        if smeta is not None:
            export_to_sobx(smeta, self)

    def _export_xlsx(self):
        smeta = self._current_smeta()
        if smeta is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Экспорт в Excel",
          self._suggested_name(" (просмотр).xlsx"), "Книга Excel (*.xlsx)")
        if not path:
            return
        try:
            export_smeta_xlsx(smeta, path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Не удалось сохранить", f"{path}\n\n{exc}")
            return
        self._settings.setValue("last_export_dir", QtCore.QFileInfo(path).absolutePath())
        self.statusBar().showMessage(f"Сохранено: {path}", 5000)

    def _export_pdf(self):
        smeta = self._current_smeta()
        if smeta is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Экспорт в PDF",
          self._suggested_name(".pdf"), "Документ PDF (*.pdf)")
        if not path:
            return
        # Печать сметы в тысячу позиций занимает секунды — без курсора ожидания
        # окно выглядит зависшим. restoreOverrideCursor обязан стоять в finally:
        # иначе при ошибке экспорта курсор ожидания остаётся висеть на приложении.
        QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
        try:
            export_pdf(smeta, path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Не удалось сохранить", f"{path}\n\n{exc}")
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._settings.setValue("last_export_dir", QtCore.QFileInfo(path).absolutePath())
        self.statusBar().showMessage(f"Сохранено: {path}", 5000)

    def _print(self):
        smeta = self._current_smeta()
        if smeta is None:
            return
        try:
            printed = print_smeta(smeta, self)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Не удалось напечатать", str(exc))
            return
        if printed:
            self.statusBar().showMessage("Отправлено на печать", 5000)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_file(url.toLocalFile())

    def _expand_all(self):
        current = self._tabs.currentWidget()
        if isinstance(current, SmetaTab):
            current.expand_all()

    def _collapse_all(self):
        current = self._tabs.currentWidget()
        if isinstance(current, SmetaTab):
            current.collapse_all()

    def _show_about(self):
        QtWidgets.QMessageBox.about(
            self,
            "О программе",
            "Просмотрщик смет\n\nЧтение и просмотр смет: .xlsx (Смета.РУ и ЛСР 421/пр), .sobx, .arp.\nПросмотр без редактирования."
        )
