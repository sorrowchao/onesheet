"""左侧：文件列表。"""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout,
                               QWidget)

from app.core.folder_scan import INPUT_EXTS, SORT_PATH, scan_folder


def collect_input_files(paths: list[str]) -> list[str]:
    """展开传入的文件/文件夹，收集受支持的输入文件路径（去重）。"""
    result: list[str] = []
    seen: set[str] = set()

    def add(path: str):
        if path not in seen:
            seen.add(path)
            result.append(path)

    for p in paths:
        path = Path(p)
        if path.is_file():
            if path.suffix.lower() in INPUT_EXTS:
                add(str(path))
        elif path.is_dir():
            for f in scan_folder(path, recursive=True, sort_by=SORT_PATH):
                add(f)
    return result


class FilePanel(QWidget):
    file_activated = Signal(str)  # 双击某个文件路径
    import_files_requested = Signal()   # 请求导入文件
    import_folder_requested = Signal()  # 请求导入文件夹
    files_dropped = Signal(list)        # 拖入并已加入列表的输入文件

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: list[str] = []
        self.setObjectName("sidePanel")
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.header_label = QLabel("文件管理器")
        self.header_label.setObjectName("sectionHeader")
        layout.addWidget(self.header_label)

        import_bar = QHBoxLayout()
        self.btn_import_files = QPushButton("导入文件")
        self.btn_import_files.clicked.connect(self.import_files_requested.emit)
        self.btn_import_folder = QPushButton("导入文件夹")
        self.btn_import_folder.clicked.connect(self.import_folder_requested.emit)
        import_bar.addWidget(self.btn_import_files)
        import_bar.addWidget(self.btn_import_folder)
        import_bar.addStretch(1)
        layout.addLayout(import_bar)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索文件名关键词…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        bar = QHBoxLayout()
        for text, slot in (("全选", self._select_all),
                           ("反选", self._invert_checks),
                           ("全不选", self._deselect_all),
                           ("移除选中", self.remove_checked)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._on_double_clicked)
        self.list.itemChanged.connect(lambda _item: self._update_status())
        layout.addWidget(self.list)

        self._update_status()

    def _on_double_clicked(self, item):
        self.file_activated.emit(self._item_path(item))

    # ------------------------------------------------------------------
    # 拖拽导入（文件或文件夹）
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
        files = collect_input_files(paths)
        event.acceptProposedAction()
        if files:
            self.add_files(files)
        self.files_dropped.emit(files)

    @staticmethod
    def _item_path(item) -> str:
        """列表项显示的是文件名，完整路径存于 UserRole。"""
        return item.data(Qt.UserRole)

    def _visible_items(self) -> list[QListWidgetItem]:
        return [self.list.item(i) for i in range(self.list.count())
                if not self.list.item(i).isHidden()]

    def _apply_filter(self, text: str):
        text = text.strip().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())
        self._update_status()

    def _update_status(self):
        total = self.list.count()
        visible = len(self._visible_items())
        checked = len(self.checked_files())
        if visible == total:
            self.status_label.setText(f"共 {total} 个文件，已勾选 {checked}")
        else:
            self.status_label.setText(f"显示 {visible}/{total}，已勾选 {checked}")

    def add_files(self, paths: list[str]):
        text = self.search.text().strip().lower()
        for p in paths:
            if p not in self._files:
                self._files.append(p)
                item = QListWidgetItem(Path(p).name)
                item.setData(Qt.UserRole, p)
                item.setToolTip(p)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.list.addItem(item)
                item.setHidden(bool(text) and text not in p.lower())
        self._update_status()

    def files(self) -> list[str]:
        return list(self._files)

    def checked_files(self) -> list[str]:
        """返回当前勾选（参与抽取/反向写入）的文件路径。"""
        out: list[str] = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(self._item_path(item))
        return out

    def _set_all_check_state(self, state):
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)
        self.list.blockSignals(False)

    def _select_all(self):
        if self.search.text().strip():
            # 有关键词时：只勾选搜索结果，其余取消勾选。
            self.list.blockSignals(True)
            for i in range(self.list.count()):
                item = self.list.item(i)
                item.setCheckState(Qt.Unchecked if item.isHidden() else Qt.Checked)
            self.list.blockSignals(False)
        else:
            self._set_all_check_state(Qt.Checked)
        self._update_status()

    def _deselect_all(self):
        self.list.blockSignals(True)
        for item in self._visible_items():
            item.setCheckState(Qt.Unchecked)
        self.list.blockSignals(False)
        self._update_status()

    def _invert_checks(self):
        """反选当前可见的文件（有搜索词时只反选搜索结果）。"""
        self.list.blockSignals(True)
        for item in self._visible_items():
            item.setCheckState(
                Qt.Unchecked if item.checkState() == Qt.Checked
                else Qt.Checked)
        self.list.blockSignals(False)
        self._update_status()

    def remove_checked(self):
        """移除所有勾选项（仅从列表移除，不删除磁盘文件）。"""
        for i in range(self.list.count() - 1, -1, -1):
            if self.list.item(i).checkState() == Qt.Checked:
                self.list.takeItem(i)
        self._files = [self._item_path(self.list.item(i)) for i in range(self.list.count())]
        self._update_status()

    def clear(self):
        self._files.clear()
        self.list.clear()
        self.search.clear()
        self._update_status()
