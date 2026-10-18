"""模板管理器：列出 data/templates 下的模板，可打开 / 重命名 / 复制 / 删除。"""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from app.template import store


def format_mtime(value: float) -> str:
    """时间戳 → 本地时间文本；无效值显示「—」。"""
    if not value or value <= 0:
        return "—"
    try:
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "—"


class TemplateManagerDialog(QDialog):
    """模板列表（按最后修改时间倒序）+ 重命名/复制/删除；「打开」后 selected_template 有值。"""

    COL_NAME = 0
    COL_MTIME = 1
    COL_FILE = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("模板管理器")
        self.resize(720, 460)
        self.selected_template = None

        layout = QVBoxLayout(self)

        self.dir_label = QLabel()
        self.dir_label.setWordWrap(True)
        layout.addWidget(self.dir_label)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["模板名", "最后修改", "文件"])
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            self.COL_MTIME, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            self.COL_FILE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemDoubleClicked.connect(lambda _item: self._open())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.table, 1)

        self.empty_label = QLabel("（暂无模板。保存模板后，模板会出现在这里。）")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)

        buttons = QHBoxLayout()
        self.btn_rename = QPushButton("重命名")
        self.btn_rename.clicked.connect(self._rename)
        self.btn_duplicate = QPushButton("复制")
        self.btn_duplicate.clicked.connect(self._duplicate)
        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._delete)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(lambda: self._reload())
        for btn in (self.btn_rename, self.btn_duplicate, self.btn_delete,
                    btn_refresh):
            buttons.addWidget(btn)
        buttons.addStretch(1)
        self.btn_open = QPushButton("打开")
        self.btn_open.setDefault(True)
        self.btn_open.clicked.connect(self._open)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.reject)
        buttons.addWidget(self.btn_open)
        buttons.addWidget(self.btn_close)
        layout.addLayout(buttons)

        self._reload()

    # ------------------------------------------------------------------
    def _reload(self, select_path: str | None = None):
        keep = select_path or self._current_path()
        entries = store.list_templates()
        for entry in entries:
            entry["_mtime"] = self._entry_mtime(entry)
        entries.sort(key=lambda e: (-e["_mtime"], e["name"]))

        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(entry["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, entry["path"])
            name_item.setToolTip(entry["path"])
            self.table.setItem(row, self.COL_NAME, name_item)
            time_item = QTableWidgetItem(format_mtime(entry["_mtime"]))
            time_item.setToolTip("最后修改时间")
            self.table.setItem(row, self.COL_MTIME, time_item)
            file_item = QTableWidgetItem(Path(entry["path"]).name)
            file_item.setToolTip(entry["path"])
            self.table.setItem(row, self.COL_FILE, file_item)
            if keep and entry["path"] == keep:
                self.table.selectRow(row)
        if (self.table.selectionModel().selectedRows() == []
                and self.table.rowCount() > 0):
            self.table.selectRow(0)   # 默认选中最新模板，打开按钮可直接用
        self.table.blockSignals(False)

        directory = store.templates_dir()
        self.dir_label.setText(
            f"模板目录：{directory}（共 {len(entries)} 个，按最后修改时间倒序）")
        self.dir_label.setToolTip(str(directory))
        self.empty_label.setVisible(not entries)
        self._update_buttons()

    @staticmethod
    def _entry_mtime(entry: dict) -> float:
        value = entry.get("mtime")
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        try:
            return Path(entry["path"]).stat().st_mtime
        except OSError:
            return 0.0

    def _update_buttons(self):
        has_selection = self._current_path() is not None
        for btn in (self.btn_open, self.btn_rename,
                    self.btn_duplicate, self.btn_delete):
            btn.setEnabled(has_selection)

    def _current_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _current_path(self) -> str | None:
        row = self._current_row()
        if row < 0:
            return None
        item = self.table.item(row, self.COL_NAME)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _current_name(self) -> str:
        row = self._current_row()
        if row < 0:
            return ""
        item = self.table.item(row, self.COL_NAME)
        return item.text() if item is not None else ""

    def _open(self):
        path = self._current_path()
        if not path:
            return
        try:
            self.selected_template = store.load(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "打开失败", str(e))
            return
        self.accept()

    def _ask_name(self, title: str, default: str) -> str | None:
        name, ok = QInputDialog.getText(self, title, "新模板名：", text=default)
        if not ok:
            return None
        name = name.strip()
        if not name:
            QMessageBox.information(self, "提示", "模板名不能为空")
            return None
        return name

    def _rename(self):
        path = self._current_path()
        if not path:
            return
        name = self._ask_name("重命名模板", self._current_name())
        if name is None or name == self._current_name():
            return
        try:
            new_path = store.rename(path, name)
        except FileExistsError as e:
            QMessageBox.warning(self, "重命名失败", str(e))
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "重命名失败", str(e))
            return
        self._reload(select_path=new_path)

    def _duplicate(self):
        path = self._current_path()
        if not path:
            return
        name = self._ask_name("复制模板", f"{self._current_name()} 副本")
        if name is None:
            return
        try:
            new_path = store.duplicate(path, name)
        except FileExistsError as e:
            QMessageBox.warning(self, "复制失败", str(e))
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "复制失败", str(e))
            return
        self._reload(select_path=new_path)

    def _delete(self):
        path = self._current_path()
        if not path:
            return
        answer = QMessageBox.question(
            self, "删除模板",
            f"确定删除模板「{self._current_name()}」吗？\n{Path(path).name}\n\n"
            "只删除模板文件，不会删除已导出的数据。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            store.delete(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "删除失败", str(e))
            return
        self._reload()
