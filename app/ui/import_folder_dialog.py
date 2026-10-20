"""导入文件夹的筛选设置对话框。

选完文件夹后弹出：包含子文件夹、每个直接父文件夹的数量上限、
排序优先级、文件大小范围、文件名正则，并实时预览将导入的文件。
"""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QSpinBox, QVBoxLayout)

from app.core.folder_scan import (FolderScanError, SORT_CHOICES,
                                  normalize_options, scan_folder)

PREVIEW_LIMIT = 200
MB = 1024 * 1024


def _bytes_to_mb(value) -> float:
    return (value or 0) / MB


def _mb_to_bytes(value: float) -> int:
    return int(round(value * MB))


class ImportFolderDialog(QDialog):
    """文件夹导入选项 + 预览。"""

    def __init__(self, folder: str, parent=None, *, initial: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("导入文件夹")
        self._folder = str(folder)
        self._files: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)

        header = QLabel("导入文件夹")
        header.setObjectName("sectionHeader")
        layout.addWidget(header)

        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(2, 0, 2, 0)
        folder_caption = QLabel("当前文件夹")
        folder_caption.setObjectName("dialogHint")
        folder_row.addWidget(folder_caption)
        self.folder_label = QLabel(self._folder)
        self.folder_label.setObjectName("dialogHint")
        self.folder_label.setWordWrap(True)
        self.folder_label.setToolTip(self._folder)
        folder_row.addWidget(self.folder_label, 1)
        layout.addLayout(folder_row)

        self.settings_box = QGroupBox("筛选设置")
        form = QFormLayout(self.settings_box)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.recursive_box = QCheckBox("包含子文件夹")
        form.addRow(self.recursive_box)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 1_000_000)
        self.limit_spin.setSpecialValueText("不限")
        self.limit_spin.setToolTip(
            "按文件所在的直接父文件夹分组（根目录也算一组）；"
            "每组排序后最多保留 N 个，0 表示不限。")
        form.addRow("每个文件夹最多", self.limit_spin)

        self.sort_combo = QComboBox()
        for key, label in SORT_CHOICES:
            self.sort_combo.addItem(label, key)
        self.sort_combo.setToolTip("优先级同时决定保留哪些文件以及列表顺序。")
        form.addRow("优先级", self.sort_combo)

        self.min_size_spin = QDoubleSpinBox()
        self.max_size_spin = QDoubleSpinBox()
        for spin in (self.min_size_spin, self.max_size_spin):
            spin.setRange(0, 102_400)
            spin.setDecimals(2)
            spin.setSingleStep(1.0)
            spin.setSuffix(" MB")
            spin.setSpecialValueText("不限")
        size_row = QHBoxLayout()
        size_row.addWidget(self.min_size_spin)
        size_row.addWidget(QLabel("—"))
        size_row.addWidget(self.max_size_spin)
        form.addRow("文件大小", size_row)

        self.pattern_edit = QLineEdit()
        self.pattern_edit.setClearButtonEnabled(True)
        self.pattern_edit.setPlaceholderText(r"例如：项目|明细")
        self.pattern_edit.setToolTip(
            "对文件名（含扩展名）做正则搜索 re.search；默认区分大小写，可写 (?i) 忽略大小写。")
        form.addRow("文件名正则", self.pattern_edit)
        layout.addWidget(self.settings_box)

        self.preview_box = QGroupBox("预览")
        preview_layout = QVBoxLayout(self.preview_box)
        preview_layout.setSpacing(8)
        self.summary_label = QLabel()
        preview_layout.addWidget(self.summary_label)

        self.preview_list = QListWidget()
        self.preview_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        preview_layout.addWidget(self.preview_list, 1)

        self.error_label = QLabel()
        self.error_label.setObjectName("errorText")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        preview_layout.addWidget(self.error_label)
        layout.addWidget(self.preview_box, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._refresh_preview)

        opts = normalize_options(initial)
        for w in (self.recursive_box, self.limit_spin, self.sort_combo,
                  self.min_size_spin, self.max_size_spin, self.pattern_edit):
            w.blockSignals(True)
        self.recursive_box.setChecked(opts["recursive"])
        self.limit_spin.setValue(opts["per_folder_limit"])
        idx = self.sort_combo.findData(opts["sort_by"])
        if idx >= 0:
            self.sort_combo.setCurrentIndex(idx)
        self.min_size_spin.setValue(_bytes_to_mb(opts["min_size"]))
        self.max_size_spin.setValue(_bytes_to_mb(opts["max_size"]))
        self.pattern_edit.setText(opts["name_pattern"])
        for w in (self.recursive_box, self.limit_spin, self.sort_combo,
                  self.min_size_spin, self.max_size_spin, self.pattern_edit):
            w.blockSignals(False)

        self.recursive_box.toggled.connect(self._schedule_preview)
        self.limit_spin.valueChanged.connect(self._schedule_preview)
        self.sort_combo.currentIndexChanged.connect(self._schedule_preview)
        self.min_size_spin.valueChanged.connect(self._schedule_preview)
        self.max_size_spin.valueChanged.connect(self._schedule_preview)
        self.pattern_edit.textChanged.connect(self._schedule_preview)

        self.resize(720, 680)
        self._refresh_preview()

    # ------------------------------------------------------------------
    def options(self) -> dict:
        """当前选项（与 scan_folder 参数同名，大小单位为字节）。"""
        return {
            "recursive": self.recursive_box.isChecked(),
            "per_folder_limit": self.limit_spin.value(),
            "sort_by": self.sort_combo.currentData(),
            "min_size": _mb_to_bytes(self.min_size_spin.value()),
            "max_size": _mb_to_bytes(self.max_size_spin.value()),
            "name_pattern": self.pattern_edit.text(),
        }

    def selected_files(self) -> list[str]:
        """完整的选择结果（不受预览条数上限影响）。"""
        return list(self._files)

    def _schedule_preview(self, *_args):
        self._timer.start()

    def _refresh_preview(self):
        try:
            files = scan_folder(self._folder, **self.options())
        except FolderScanError as e:
            self._files = []
            self._apply_preview([], str(e))
            return
        self._files = files
        self._apply_preview(files, None)

    def _apply_preview(self, files: list[str], error: str | None):
        self.preview_list.clear()
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)

        if error:
            self.error_label.setText(error)
            self.error_label.show()
            self.summary_label.setText("无法预览")
            ok.setEnabled(False)
            return

        self.error_label.hide()
        if not files:
            self.summary_label.setText("没有匹配的文件")
            ok.setEnabled(False)
            return

        parents = {str(Path(f).parent) for f in files}
        self.summary_label.setText(
            f"将导入 {len(files)} 个文件（来自 {len(parents)} 个文件夹）")
        for f in files[:PREVIEW_LIMIT]:
            rel = str(Path(f).relative_to(self._folder)).replace("\\", "/")
            item = QListWidgetItem(rel)
            item.setToolTip(f)
            self.preview_list.addItem(item)
        if len(files) > PREVIEW_LIMIT:
            more = QListWidgetItem(f"…还有 {len(files) - PREVIEW_LIMIT} 个未显示")
            more.setFlags(Qt.ItemFlag.NoItemFlags)
            self.preview_list.addItem(more)
        ok.setEnabled(True)

    def _on_accept(self):
        # 先同步重算，避免用 250ms 防抖期的旧结果
        self._refresh_preview()
        if self.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled() \
                and self._files:
            self.accept()
