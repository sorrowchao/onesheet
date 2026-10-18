"""主窗口：拼装文件列表 / 预览 / 配置 / 结果面板 + 菜单栏。"""
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QSplitter, QTabWidget, QToolButton, QVBoxLayout,
                               QWidget)

from app.core.aggregator import aggregate
from app.core.detector import detect_form_pairs_pos
from app.core.exporter import export_csv, export_xlsx
from app.core.extractor import extract_file
from app.core.models import (SEQ_COLUMN, FieldMapping, OutputTable,
                             ResultTable, SheetData, duplicate_value_positions)
from app.core.reader import read_excel
from app.core.writer import _norm_key, preview_write_back, read_summary_xlsx
from app.service import settings
from app.service.worker import AiScanWorker, ExtractWorker, WriteBackWorker
from app.template import store as template_store
from app.ui import theme
from app.ui.config_panel import ConfigPanel
from app.ui.file_panel import FilePanel, collect_excel_files
from app.ui.preview_panel import PreviewPanel
from app.ui.result_panel import ResultPanel
from app.ui.template_manager import TemplateManagerDialog


class ApiKeyDialog(QDialog):
    """填写 / 修改 / 查看 DeepSeek API Key（默认密码显示，可切换明文）。"""

    def __init__(self, stored_key: str = "", env_key_set: bool = False,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("DeepSeek API Key")
        form = QFormLayout(self)

        if env_key_set:
            status = ("当前使用环境变量 DEEPSEEK_API_KEY（优先于本地保存，"
                      "会覆盖下面输入的 Key）")
        elif stored_key:
            status = "本地已保存 Key，可修改或清空"
        else:
            status = "尚未设置 Key"
        status_label = QLabel(status)
        status_label.setWordWrap(True)
        form.addRow(status_label)

        self.key_edit = QLineEdit(stored_key)
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-…")
        form.addRow("API Key", self.key_edit)

        self.show_box = QCheckBox("显示明文")
        self.show_box.toggled.connect(self._toggle_echo)
        form.addRow("", self.show_box)

        hint = QLabel("Key 保存在本地 data/settings.json；留空并点「确定」可清除本地 Key。")
        hint.setWordWrap(True)
        form.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _toggle_echo(self, show: bool):
        mode = QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        self.key_edit.setEchoMode(mode)

    def key(self) -> str:
        return self.key_edit.text().strip()


class TryExtractDialog(QDialog):
    """单文件试抽结果（只查看，不影响批量抽取结果）。"""

    def __init__(self, path: str, tables: dict[str, ResultTable], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"试抽：{Path(path).name}")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"文件：{path}"))
        self.result_panel = ResultPanel()
        self.result_panel.show_results(tables)
        layout.addWidget(self.result_panel, 1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        self.resize(900, 520)


class WriteBackDialog(QDialog):
    """反向写入参数对话框：选汇总来源、目标模板表、匹配字段、输出目录。"""

    def __init__(self, result_tables: dict[str, ResultTable],
                 output_tables: list[OutputTable],
                 original_tables: dict[str, ResultTable] | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("反向写入（总表 → 分表回填）")
        self._result_tables = result_tables
        self._output_tables = output_tables
        # 抽取原始快照（未经用户编辑），用于识别哪些列被改动过。
        self._original_tables = original_tables or {}
        self._imported_summary: ResultTable | None = None
        self._match_cols: list[int] = []

        form = QFormLayout(self)

        hint = QLabel(
            "把汇总表每一行的值，按模板记录的字段位置回填到对应分表，另存到输出目录（不覆盖原表）。\n"
            "「匹配字段」用于识别“哪一行回填到哪个分表”：程序读取每个分表里这些字段的值，"
            "再到汇总表里找这些字段全部相同的那一行来回填。若在字段映射里设了「主键」，"
            "默认只勾主键字段；否则默认只勾未被改动的列——你在结果区改过的列会被自动取消勾选，"
            "否则它们已与分表旧值不符，会导致一条也匹配不上。")
        hint.setWordWrap(True)
        form.addRow(hint)

        self.source_combo = QComboBox()
        self.source_combo.addItems(["当前抽取结果", "导入汇总 Excel"])
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        form.addRow("汇总来源", self.source_combo)

        self.table_combo = QComboBox()
        self.table_combo.addItems(list(result_tables.keys()))
        self.table_combo.currentIndexChanged.connect(self._on_table_changed)
        form.addRow("结果表", self.table_combo)

        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        file_btn = QPushButton("浏览…")
        file_btn.clicked.connect(self._browse_summary)
        file_row = QHBoxLayout()
        file_row.addWidget(self.file_edit, 1)
        file_row.addWidget(file_btn)
        form.addRow("汇总文件", file_row)

        self.output_table_combo = QComboBox()
        self.output_table_combo.addItems([ot.name for ot in output_tables])
        self.output_table_combo.currentIndexChanged.connect(self._refresh_match_columns)
        form.addRow("目标模板表", self.output_table_combo)

        self.key_list = QListWidget()
        self.key_list.setToolTip(
            "勾选用于匹配的字段：程序读取每个分表里这些字段的值，"
            "再到汇总表找这些字段全部相同的那一行来回填。设了「主键」时默认只勾主键，"
            "否则默认只勾未被改动的列（改过的列自动取消勾选）。")
        self.key_list.setMaximumHeight(140)
        form.addRow("匹配字段", self.key_list)

        self.outdir_edit = QLineEdit()
        outdir_btn = QPushButton("浏览…")
        outdir_btn.clicked.connect(self._browse_outdir)
        out_row = QHBoxLayout()
        out_row.addWidget(self.outdir_edit, 1)
        out_row.addWidget(outdir_btn)
        form.addRow("输出目录", out_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._on_source_changed()

    # ------------------------------------------------------------------
    def _on_source_changed(self):
        is_current = self.source_combo.currentIndex() == 0
        self.table_combo.setEnabled(is_current)
        self.file_edit.setEnabled(not is_current)
        if is_current:
            self._sync_output_table_to_result()
        self._refresh_match_columns()

    def _on_table_changed(self):
        if self.source_combo.currentIndex() == 0:
            self._sync_output_table_to_result()
        self._refresh_match_columns()

    def _sync_output_table_to_result(self):
        name = self.table_combo.currentText()
        idx = self.output_table_combo.findText(name)
        if idx >= 0:
            self.output_table_combo.setCurrentIndex(idx)

    def _current_columns(self) -> list[str]:
        if self.source_combo.currentIndex() == 0:
            rt = self._result_tables.get(self.table_combo.currentText())
            return list(rt.columns) if rt else []
        return list(self._imported_summary.columns) if self._imported_summary else []

    def _selected_output_table(self) -> OutputTable | None:
        i = self.output_table_combo.currentIndex()
        if 0 <= i < len(self._output_tables):
            return self._output_tables[i]
        return None

    def _changed_columns(self) -> set[str]:
        """当前来源表里被用户改动过的列名（对比抽取原始快照）。

        无基线可比时（导入汇总，或未抽取）返回空集——此时无法自动识别改动。
        """
        if self.source_combo.currentIndex() != 0:
            return set()
        name = self.table_combo.currentText()
        edited = self._result_tables.get(name)
        original = self._original_tables.get(name)
        if edited is None or original is None:
            return set()
        changed: set[str] = set()
        for j, col in enumerate(edited.columns):
            if col not in original.columns:
                changed.add(col)
                continue
            oi = original.columns.index(col)
            for er, orow in zip(edited.rows, original.rows):
                ev = er[j] if j < len(er) else None
                ov = orow[oi] if oi < len(orow) else None
                if _norm_key(ev) != _norm_key(ov):
                    changed.add(col)
                    break
        return changed

    @staticmethod
    def _key_target(ot: OutputTable | None) -> str | None:
        """目标模板表里被指定为主键的字段名（无则 None）。"""
        if ot is None:
            return None
        for f in ot.fields:
            if getattr(f, "is_key", False) and f.target:
                return f.target
        return None

    def _refresh_match_columns(self):
        """填充可勾选的匹配字段：排除序号列，只列目标模板里有取值位置的字段。

        默认勾选规则：设了「主键」时只勾主键字段、其余不勾；
        否则勾「未被改动」的列（用户在图里改过的列已与分表旧值不符，参与匹配会一条也匹配不上）。
        """
        cols = self._current_columns()
        ot = self._selected_output_table()
        match_cols: list[int] = []
        for i, c in enumerate(cols):
            if c == SEQ_COLUMN:
                continue
            if ot is not None and any(
                    f.target == c and f.value_row is not None and f.value_col is not None
                    for f in ot.fields):
                match_cols.append(i)
        self._match_cols = match_cols
        changed = self._changed_columns()
        key_target = self._key_target(ot)
        use_key = key_target is not None and any(cols[i] == key_target for i in match_cols)
        self.key_list.blockSignals(True)
        self.key_list.clear()
        for i in match_cols:
            item = QListWidgetItem(cols[i])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            if use_key:
                checked = cols[i] == key_target
            else:
                checked = cols[i] not in changed
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self.key_list.addItem(item)
        self.key_list.blockSignals(False)

    def _browse_summary(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择汇总 Excel", "", "Excel 文件 (*.xlsx *.xls *.xlsm)")
        if not path:
            return
        try:
            self._imported_summary = read_summary_xlsx(path)
            self.file_edit.setText(path)
            self._refresh_match_columns()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "读取失败", str(e))

    def _browse_outdir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if folder:
            self.outdir_edit.setText(folder)

    # ------------------------------------------------------------------
    def summary(self) -> ResultTable | None:
        """当前所选汇总（当前结果或导入文件）。"""
        if self.source_combo.currentIndex() == 0:
            return self._result_tables.get(self.table_combo.currentText())
        return self._imported_summary

    def output_table(self) -> OutputTable | None:
        return self._selected_output_table()

    def key_cols(self) -> list[int]:
        """返回被勾选的匹配列索引（0-based，指向汇总表 columns）。"""
        out: list[int] = []
        for i in range(self.key_list.count()):
            item = self.key_list.item(i)
            if item.checkState() == Qt.Checked and i < len(self._match_cols):
                out.append(self._match_cols[i])
        return out

    def output_dir(self) -> str:
        return self.outdir_edit.text().strip()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("一表通")
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self._sheets: list[SheetData] = []
        self._results: dict[str, ResultTable] = {}
        self._worker = None
        self._ai_worker = None
        self._current_file: str | None = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.file_panel = FilePanel()
        self.file_panel.file_activated.connect(self._on_file_activated)
        self.file_panel.import_files_requested.connect(self._import_files)
        self.file_panel.import_folder_requested.connect(self._import_folder)
        self.file_panel.files_dropped.connect(self._on_files_dropped)
        self.preview_panel = PreviewPanel()
        self.config_panel = ConfigPanel()
        self.config_panel.form_scan_requested.connect(self._on_scan_form)
        self.config_panel.ai_scan_requested.connect(self._on_ai_scan_form)
        self.config_panel.pair_requested.connect(self._on_pair_requested)
        self.config_panel.open_template_requested.connect(self._open_template)
        self.config_panel.save_template_requested.connect(self._save_template)
        self.config_panel.manage_templates_requested.connect(
            self._open_template_manager)
        self.config_panel.field_selected.connect(self._on_field_selected)
        self.preview_panel.pair_picked.connect(self._on_pair_picked)
        self.preview_panel.pair_step.connect(self._on_pair_step)
        self.preview_panel.sheet_changed.connect(self.config_panel.set_sheet)
        main_splitter.addWidget(self.file_panel)
        main_splitter.addWidget(self.preview_panel)
        main_splitter.addWidget(self.config_panel)
        main_splitter.setSizes([250, 470, 560])
        self.main_splitter = main_splitter

        self.result_panel = ResultPanel()

        # 日志页：默认收在「日志」标签页里，点标签才显示，不常驻底部。
        self.log = QPlainTextEdit()
        self.log.setObjectName("logView")
        self.log.setReadOnly(True)
        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(self.log)
        # 操作按钮放在页签栏右侧，与「汇总结果 / 日志」同一行。
        btn_try = QPushButton("试抽当前文件")
        btn_try.setToolTip("只抽取当前预览的文件，检查字段设置是否正确（不改变批量结果）")
        btn_try.clicked.connect(self._run_try_extract)
        btn_extract = QPushButton("批量抽取")
        btn_extract.clicked.connect(self._run_extract)
        btn_write = QPushButton("反向写入")
        btn_write.clicked.connect(self._run_write_back)
        btn_export = QToolButton()
        btn_export.setText("导出")
        btn_export.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        export_menu = QMenu(btn_export)
        export_menu.addAction("导出 xlsx…", self._export_xlsx)
        export_menu.addAction("导出 csv…", self._export_csv)
        btn_export.setMenu(export_menu)

        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(6)
        for btn in (btn_try, btn_extract, btn_write, btn_export):
            btn.setProperty("compact", True)   # theme.py: 更小的按钮内边距
            corner_layout.addWidget(btn)

        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.addTab(self.result_panel, "汇总结果")
        self.bottom_tabs.addTab(log_page, "日志")
        self.bottom_tabs.setCornerWidget(
            corner, Qt.Corner.TopRightCorner)

        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.addWidget(main_splitter)
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        bottom_layout.addWidget(self.bottom_tabs, 1)
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        progress_row.addWidget(self.progress, 1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setToolTip("停止正在进行的批量抽取 / 反向写入")
        self.btn_cancel.clicked.connect(self._cancel_task)
        progress_row.addWidget(self.btn_cancel)
        bottom_layout.addLayout(progress_row)
        v_splitter.addWidget(bottom)
        # 默认上方 2/3、下方结果区 1/3。注意 setSizes 会把小于各控件
        # minimumSizeHint 的数值抬到最小值，所以用大权重表示 2:1。
        v_splitter.setSizes([2000, 1000])
        self.v_splitter = v_splitter
        root.addWidget(v_splitter, 1)

        self._build_menus()
        self._set_theme(settings.get_theme(), persist=False)
        self._set_icon(settings.get_icon(), persist=False)
        self._restore_window_state()
        self.statusBar().showMessage("导入 Excel 文件开始")

    # ------------------------------------------------------------------
    def _build_menus(self):
        """按功能分组构建菜单栏：文件 / 模板 / 数据 / 帮助。"""
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        file_menu.addAction("导入文件…", self._import_files, "Ctrl+O")
        file_menu.addAction("导入文件夹…", self._import_folder, "Ctrl+Shift+O")
        file_menu.addAction("移除选中文件", self.file_panel.remove_checked)
        file_menu.addAction("清空文件列表", self.file_panel.clear)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close, "Ctrl+Q")

        tpl_menu = menubar.addMenu("模板")
        tpl_menu.addAction("打开模板…", self._open_template)
        tpl_menu.addAction("保存模板…", self._save_template, "Ctrl+S")
        tpl_menu.addAction("模板管理器…", self._open_template_manager, "Ctrl+T")

        data_menu = menubar.addMenu("数据")
        data_menu.addAction("扫描表单", self._on_scan_form)
        data_menu.addAction("AI 扫描表单", self._on_ai_scan_form)
        data_menu.addAction("DeepSeek API Key…", self._edit_api_key)
        data_menu.addAction("手动配对", self._on_pair_requested)
        data_menu.addSeparator()
        data_menu.addAction("试抽当前文件", self._run_try_extract)
        data_menu.addAction("批量抽取", self._run_extract, "F5")
        data_menu.addAction("反向写入", self._run_write_back, "Ctrl+Shift+W")
        data_menu.addSeparator()
        data_menu.addAction("导出 xlsx…", self._export_xlsx, "Ctrl+Shift+E")
        data_menu.addAction("导出 csv…", self._export_csv)

        view_menu = menubar.addMenu("视图")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        self._theme_actions = {}
        for key, label in ((theme.DARK, "深色主题"), (theme.LIGHT, "浅色主题")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda _checked=False, k=key: self._set_theme(k))
            theme_group.addAction(act)
            view_menu.addAction(act)
            self._theme_actions[key] = act

        view_menu.addSeparator()
        icon_menu = view_menu.addMenu("应用图标")
        self._icon_actions = {}
        icon_group = QActionGroup(self)
        icon_group.setExclusive(True)
        icon_files = settings.available_icons()
        if not icon_files:
            empty_act = icon_menu.addAction("（data/icons 下没有图标）")
            empty_act.setEnabled(False)
        for p in icon_files:
            act = QAction(p.stem, self)
            act.setCheckable(True)
            act.triggered.connect(
                lambda _checked=False, n=p.stem: self._set_icon(n))
            icon_group.addAction(act)
            icon_menu.addAction(act)
            self._icon_actions[p.stem] = act

        help_menu = menubar.addMenu("帮助")
        help_menu.addAction("使用说明", self._open_help)
        help_menu.addAction("关于", self._about)

    def _set_theme(self, name: str, persist: bool = True):
        """应用主题（深/浅），同步菜单勾选；persist 时写入设置文件。"""
        name = theme.normalize(name)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet(name))
        act = self._theme_actions.get(name)
        if act is not None:
            act.setChecked(True)
        if persist:
            settings.set_theme(name)

    def _set_icon(self, name: str, persist: bool = True):
        """应用 data/icons/ 下的图标，同步菜单勾选；persist 时写入设置。"""
        path = settings.icon_path(name)
        if path is None:
            return
        resolved = settings.resolve_icon_name(name)
        icon = QIcon(str(path))
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)
        self.setWindowIcon(icon)
        act = self._icon_actions.get(resolved)
        if act is not None:
            act.setChecked(True)
        if persist:
            settings.set_icon(resolved)

    def _open_help(self):
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            # 优先用 exe 旁的（可自行替换），其次上一级目录，最后回退打包内置副本。
            candidates = [
                exe_dir / "使用说明.txt",
                exe_dir.parent / "使用说明.txt",
                Path(getattr(sys, "_MEIPASS", exe_dir)) / "使用说明.txt",
            ]
        else:
            candidates = [Path(__file__).resolve().parent.parent / "使用说明.txt"]
        path = next((p for p in candidates if p.exists()), candidates[-1])
        if not path.exists():
            QMessageBox.information(self, "提示", f"未找到使用说明文件：{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _about(self):
        QMessageBox.about(
            self, "关于",
            "一表通（OneSheet）\n\n"
            "多表归一：从 Excel 文件中提取「表单（标签:值）」数据并汇总，"
            "支持把编辑后的汇总值反向写回源文件。")

    # ------------------------------------------------------------------
    # 文件
    # ------------------------------------------------------------------
    def _import_files(self):
        start = settings.get_last_import_dir()
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择 Excel 文件", start, "Excel 文件 (*.xlsx *.xls *.xlsm)")
        if paths:
            self.file_panel.add_files(paths)
            self._remember_import_dir(str(Path(paths[0]).parent))

    def _import_folder(self):
        start = settings.get_last_import_dir()
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹", start)
        if folder:
            files = collect_excel_files([folder])
            if files:
                self.file_panel.add_files(files)
                self._remember_import_dir(folder)
            else:
                QMessageBox.information(self, "提示", "该文件夹下没有 Excel 文件")

    @staticmethod
    def _remember_import_dir(path: str):
        """记住导入目录；设置文件不可写时不影响正常操作。"""
        try:
            settings.set_last_import_dir(path)
        except OSError:
            pass

    def _on_files_dropped(self, files: list[str]):
        """FilePanel 已把拖入的文件加入列表；这里只记住目录。"""
        if files:
            self._remember_import_dir(str(Path(files[0]).parent))

    # ------------------------------------------------------------------
    # 拖拽导入（拖到窗口任意空旷处也可）
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile()]
        event.acceptProposedAction()
        files = collect_excel_files(paths)
        if not files:
            self.statusBar().showMessage("拖入的内容里没有 Excel 文件")
            return
        self.file_panel.add_files(files)
        first = Path(paths[0])
        self._remember_import_dir(
            str(first if first.is_dir() else first.parent))
        self.statusBar().showMessage(f"已导入 {len(files)} 个文件")

    def _on_file_activated(self, path: str):
        try:
            self._sheets = read_excel(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "读取失败", str(e))
            return
        if not self._sheets:
            self.statusBar().showMessage("该文件没有 sheet")
            return
        self._current_file = path
        self.preview_panel.set_sheets(self._sheets)
        self.statusBar().showMessage(f"{path} — 共 {len(self._sheets)} 个 sheet")

    def _on_field_selected(self, field):
        """配置区字段表选中某行：预览区高亮对应标签/值。"""
        self.preview_panel.highlight_field(field)

    # ------------------------------------------------------------------
    # 扫描表单 / 手动配对
    # ------------------------------------------------------------------
    def _on_scan_form(self):
        sheet = self.preview_panel.current_sheet()
        if sheet is None:
            QMessageBox.information(self, "提示", "请先双击打开一个文件")
            return
        pairs = detect_form_pairs_pos(sheet)
        fields = [
            FieldMapping(target=label, source="kv", key=label,
                         label_row=lr, label_col=lc, value_row=vr, value_col=vc)
            for label, lr, lc, vr, vc in pairs
        ]
        self.config_panel.set_form_fields(fields)
        self.statusBar().showMessage(f"已扫描到 {len(fields)} 个字段，可勾选/取消，或直接改「值行/值列」")

    # ------------------------------------------------------------------
    # AI 扫描表单（DeepSeek）
    # ------------------------------------------------------------------
    def _edit_api_key(self):
        """菜单入口：填写 / 修改 / 查看 DeepSeek API Key。"""
        env = settings.env_api_key()
        dlg = ApiKeyDialog(settings.get_stored_api_key(), bool(env), self)
        if dlg.exec() != QDialog.Accepted:
            return
        settings.set_api_key(dlg.key())
        if env:
            self.statusBar().showMessage(
                "Key 已保存到本地设置；当前仍优先使用环境变量 DEEPSEEK_API_KEY")
        elif dlg.key():
            self.statusBar().showMessage("DeepSeek API Key 已保存")
        else:
            self.statusBar().showMessage("已清除本地 DeepSeek API Key")

    def _on_ai_scan_form(self):
        if self._ai_worker is not None and self._ai_worker.isRunning():
            self.statusBar().showMessage("AI 识别仍在进行中…")
            return
        sheet = self.preview_panel.current_sheet()
        if sheet is None:
            QMessageBox.information(self, "提示", "请先双击打开一个文件")
            return
        key = settings.get_api_key()
        if not key:
            dlg = ApiKeyDialog(settings.get_stored_api_key(),
                               bool(settings.env_api_key()), self)
            if dlg.exec() != QDialog.Accepted or not dlg.key():
                return
            settings.set_api_key(dlg.key())
            key = dlg.key()

        self.statusBar().showMessage("AI 识别中…")
        self._ai_worker = AiScanWorker(sheet, key)
        self._ai_worker.done.connect(self._on_ai_scan_done)
        self._ai_worker.error.connect(self._on_ai_scan_error)
        self._ai_worker.start()

    def _on_ai_scan_done(self, fields: list):
        if not fields:
            QMessageBox.information(self, "提示", "AI 未识别到字段")
            self.statusBar().showMessage("AI 未识别到字段")
            return
        self.config_panel.set_form_fields(fields)
        self.statusBar().showMessage(
            f"AI 识别到 {len(fields)} 个字段，可勾选/修改")

    def _on_ai_scan_error(self, msg: str):
        self.statusBar().showMessage("AI 识别失败")
        QMessageBox.warning(
            self, "AI 识别失败",
            f"{msg}\n\n可在下次点击「AI 扫描表单」时重新输入 Key，"
            "或设置环境变量 DEEPSEEK_API_KEY。")

    def _on_pair_requested(self):
        if self.preview_panel.current_sheet() is None:
            QMessageBox.information(self, "提示", "请先双击打开一个文件")
            return
        if self.preview_panel.is_pair_mode():
            self.preview_panel.set_pair_mode(False)
        else:
            self.preview_panel.set_pair_mode(True)

    def _on_pair_picked(self, label_text: str, label_row: int, label_col: int,
                        value_row: int, value_col: int):
        msg = self.config_panel.add_pair(label_text, label_row, label_col,
                                         value_row, value_col)
        if msg:
            self.preview_panel.mark_pair_rejected(msg)

    def _on_pair_step(self, msg: str):
        if msg:
            self.statusBar().showMessage(msg)

    # ------------------------------------------------------------------
    # 模板
    # ------------------------------------------------------------------
    def _open_template(self):
        tpl_dir = template_store.templates_dir()
        tpl_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self, "打开模板", str(tpl_dir), "模板 JSON (*.json)")
        if not path:
            return
        try:
            tpl = template_store.load(path)
            self.config_panel.set_template(tpl)
            self.statusBar().showMessage(f"已加载模板：{tpl.name}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "模板无效", str(e))

    def _save_template(self):
        tpl = self.config_panel.get_template()
        if not self._confirm_duplicate_positions(tpl.output_tables):
            return
        default = str(template_store.templates_dir() / (tpl.name + ".json"))
        path, _ = QFileDialog.getSaveFileName(self, "保存模板", default, "模板 JSON (*.json)")
        if not path:
            return
        try:
            saved = template_store.save_path(tpl, path)
            self.statusBar().showMessage(f"模板已保存：{saved}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(e))

    def _open_template_manager(self):
        """模板管理器：打开所选模板，或重命名/复制/删除模板文件。"""
        dlg = TemplateManagerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_template:
            self.config_panel.set_template(dlg.selected_template)
            self.statusBar().showMessage(
                f"已加载模板：{dlg.selected_template.name}")

    def _confirm_duplicate_positions(self, output_tables) -> bool:
        """字段取值位置重复时提示；用户选择继续则返回 True。"""
        warnings = duplicate_value_positions(output_tables)
        if not warnings:
            return True
        answer = QMessageBox.warning(
            self, "字段取值位置重复",
            "以下字段指向同一个单元格，会导出相同的值：\n\n"
            + "\n".join(warnings)
            + "\n\n仍要继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------------
    # 抽取 / 导出
    # ------------------------------------------------------------------
    def _run_try_extract(self):
        """只抽当前预览的文件，弹出结果供检查；不改变批量抽取结果。"""
        if self._current_file is None or not self._sheets:
            QMessageBox.information(self, "提示", "请先双击左侧文件，预览要试抽的文件")
            return
        tpl = self.config_panel.get_template()
        if not tpl.output_tables:
            QMessageBox.information(self, "提示", "请先配置至少一张结果表")
            return
        empty = [ot.name for ot in tpl.output_tables if not ot.fields]
        if empty:
            QMessageBox.warning(self, "提示",
                                "以下结果表还没有选择任何字段：\n" + "、".join(empty))
            return
        try:
            per_file = extract_file(self._sheets, tpl)
            merged = aggregate([per_file])
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "试抽失败", str(e))
            return
        total = sum(len(rt.rows) for rt in merged.values())
        self.statusBar().showMessage(
            f"试抽完成：{Path(self._current_file).name} — "
            f"{len(merged)} 张表，共 {total} 行")
        TryExtractDialog(self._current_file, merged, self).exec()

    def _run_extract(self):
        if self._task_running():
            return
        files = self.file_panel.checked_files()
        if not files:
            if self.file_panel.files():
                QMessageBox.information(self, "提示", "请至少勾选一个文件")
            else:
                QMessageBox.information(self, "提示", "请先导入文件")
            return
        tpl = self.config_panel.get_template()
        if not tpl.output_tables:
            QMessageBox.information(self, "提示", "请先配置至少一张结果表")
            return
        empty = [ot.name for ot in tpl.output_tables if not ot.fields]
        if empty:
            QMessageBox.warning(self, "提示",
                                "以下结果表还没有选择任何字段，导出会是空表：\n" + "、".join(empty))
            return
        if not self._confirm_duplicate_positions(tpl.output_tables):
            return

        self.log.clear()
        self._start_task()
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)
        self._worker = ExtractWorker(files, tpl)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_ok.connect(lambda p: self._log(f"成功：{p}"))
        self._worker.file_error.connect(lambda p, e: self._log(f"失败：{p} — {e}"))
        self._worker.done.connect(self._on_extract_done)
        self._worker.cancelled.connect(self._on_extract_cancelled)
        self._worker.start()

    def _on_progress(self, done: int, total: int):
        self.progress.setValue(done)
        self.statusBar().showMessage(f"抽取中 {done}/{total}")

    def _on_extract_done(self, merged: dict):
        self._finish_task()
        self._results = merged
        self.result_panel.show_results(merged)
        total_rows = sum(len(rt.rows) for rt in merged.values())
        self.statusBar().showMessage(f"抽取完成：{len(merged)} 张表，共 {total_rows} 行")

    def _on_extract_cancelled(self, processed: int, total: int):
        self._finish_task()
        self._log(f"已取消：处理了 {processed}/{total} 个文件（汇总结果未更新）")
        self.statusBar().showMessage(f"抽取已取消（{processed}/{total}）")

    def _log(self, text: str):
        self.log.appendPlainText(text)

    def _export_xlsx(self):
        if not self._results:
            QMessageBox.information(self, "提示", "还没有抽取结果")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 xlsx", "汇总结果.xlsx",
                                              "Excel 文件 (*.xlsx)")
        if not path:
            return
        try:
            export_xlsx(self._results, path)
            self.statusBar().showMessage(f"已导出：{path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_csv(self):
        if not self._results:
            QMessageBox.information(self, "提示", "还没有抽取结果")
            return
        folder = QFileDialog.getExistingDirectory(self, "选择导出文件夹")
        if not folder:
            return
        try:
            written = export_csv(self._results, folder)
            self.statusBar().showMessage(f"已导出 {len(written)} 个 csv 文件")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(e))

    # ------------------------------------------------------------------
    # 反向写入
    # ------------------------------------------------------------------
    def _run_write_back(self):
        if self._task_running():
            return
        files = self.file_panel.checked_files()
        if not files:
            if self.file_panel.files():
                QMessageBox.information(self, "提示", "请至少勾选一个文件")
            else:
                QMessageBox.information(self, "提示", "请先导入文件")
            return
        tpl = self.config_panel.get_template()
        if not tpl.output_tables:
            QMessageBox.information(self, "提示", "请先配置至少一张结果表")
            return
        # 用结果区当前（可能被用户编辑过）的数据作为汇总，而非抽取时的旧快照
        edited = self.result_panel.read_results()
        if not edited:
            QMessageBox.information(self, "提示", "请先批量抽取，或在对话框里导入汇总 Excel")
            return

        dlg = WriteBackDialog(edited, tpl.output_tables, self._results, self)
        if dlg.exec() != QDialog.Accepted:
            return

        summary = dlg.summary()
        if summary is None or not summary.columns:
            QMessageBox.warning(self, "提示", "没有可用的汇总数据")
            return
        ot = dlg.output_table()
        if ot is None:
            QMessageBox.warning(self, "提示", "未找到对应的目标模板表")
            return
        output_dir = dlg.output_dir()
        if not output_dir:
            QMessageBox.warning(self, "提示", "请选择输出目录")
            return
        key_cols = dlg.key_cols()
        if not key_cols:
            QMessageBox.warning(self, "提示", "请至少勾选一个匹配字段")
            return

        if not self._confirm_write_back_plan(files, ot, summary, key_cols):
            return

        self.log.clear()
        self._start_task()
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)
        self._worker = WriteBackWorker(files, ot, summary, key_cols, output_dir)
        self._worker.progress.connect(self._on_write_progress)
        self._worker.done.connect(self._on_write_back_done)
        self._worker.start()

    def _confirm_write_back_plan(self, files, ot, summary, key_cols) -> bool:
        """写盘前预演：显示将写入的文件数/单元格数，确认后返回 True。"""
        self.statusBar().showMessage("正在预演反向写入…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            plan = preview_write_back(files, ot, summary, key_cols)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "预演失败", str(e))
            return False
        finally:
            QApplication.restoreOverrideCursor()

        if plan.get("cancelled"):
            return False
        n_files = plan.get("file_count", 0)
        n_cells = plan.get("cell_count", 0)
        n_unmatched = len(plan.get("unmatched", []))
        n_errors = len(plan.get("errors", []))
        if n_files == 0:
            detail = ""
            if plan.get("errors"):
                detail = "\n\n错误示例：\n" + "\n".join(
                    f"{p} — {m}" for p, m in plan["errors"][:5])
            QMessageBox.warning(
                self, "反向写入预演",
                f"没有匹配到可写入的文件（未匹配 {n_unmatched} 个，"
                f"错误 {n_errors} 个）。{detail}")
            return False
        answer = QMessageBox.question(
            self, "反向写入预演",
            f"将读取 {len(files)} 个文件；\n"
            f"匹配到 {n_files} 个文件，将写入 {n_cells} 个单元格。\n"
            f"未匹配 {n_unmatched} 个，错误 {n_errors} 个。\n\n继续写入吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        return answer == QMessageBox.StandardButton.Yes

    def _on_write_progress(self, done: int, total: int):
        self.progress.setValue(done)
        self.statusBar().showMessage(f"回填中 {done}/{total}")

    def _on_write_back_done(self, report: dict):
        self._finish_task()
        written = report.get("written", [])
        unmatched = report.get("unmatched", [])
        errors = report.get("errors", [])
        cancelled = report.get("cancelled", False)
        for p in written:
            self._log(f"已写入：{p}")
        for p in unmatched:
            self._log(f"未匹配：{p}")
        for p, msg in errors:
            self._log(f"错误：{p} — {msg}")
        if cancelled:
            self._log("已取消：仅处理了部分文件")
        self.progress.setValue(self.progress.maximum())
        prefix = "回填已取消" if cancelled else "回填完成"
        summary = (f"{prefix}：写入 {len(written)} 个文件，未匹配 {len(unmatched)} 个，"
                   f"错误 {len(errors)} 个，未使用汇总行 "
                   f"{len(report.get('unused_rows', []))} 行")
        self._log(summary)
        self.statusBar().showMessage(summary)

    # ------------------------------------------------------------------
    # 后台任务：取消 / 状态
    # ------------------------------------------------------------------
    def _task_running(self) -> bool:
        if self._worker is not None and self._worker.isRunning():
            self.statusBar().showMessage("任务进行中，请等待完成或点「取消」")
            return True
        return False

    def _start_task(self):
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setText("取消")

    def _finish_task(self):
        self.btn_cancel.setEnabled(False)

    def _cancel_task(self):
        if self._worker is None or not self._worker.isRunning():
            return
        self._worker.cancel()
        self.btn_cancel.setEnabled(False)
        self.statusBar().showMessage("正在取消…（当前文件处理完后停止）")

    # ------------------------------------------------------------------
    # 窗口状态持久化
    # ------------------------------------------------------------------
    @staticmethod
    def _int_sizes(value, expected: int) -> list[int] | None:
        if (isinstance(value, list) and len(value) == expected
                and all(isinstance(v, (int, float)) for v in value)):
            return [int(v) for v in value]
        return None

    def _restore_window_state(self):
        state = settings.get_window_state()
        if not isinstance(state, dict):
            return
        width, height = state.get("width"), state.get("height")
        if (isinstance(width, int) and isinstance(height, int)
                and width >= 800 and height >= 500):
            self.resize(width, height)
        main_sizes = self._int_sizes(state.get("main_splitter"), 3)
        if main_sizes:
            self.main_splitter.setSizes(main_sizes)
        v_sizes = self._int_sizes(state.get("v_splitter"), 2)
        if v_sizes:
            self.v_splitter.setSizes(v_sizes)
        if state.get("maximized"):
            self.showMaximized()

    def closeEvent(self, event):
        geo = self.normalGeometry() if self.isMaximized() else self.geometry()
        try:
            settings.set_window_state({
                "width": geo.width(),
                "height": geo.height(),
                "maximized": self.isMaximized(),
                "main_splitter": self.main_splitter.sizes(),
                "v_splitter": self.v_splitter.sizes(),
            })
        except OSError:
            pass  # 设置文件不可写时不影响退出
        super().closeEvent(event)
