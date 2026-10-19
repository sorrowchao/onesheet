"""关于对话框：软件简介、致谢与联系方式。

与主界面共用主题（`#sectionHeader` 标题条、圆角卡片、`#dialogHint`
次要文字），随深色 / 浅色主题自动切换。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QLabel, QVBoxLayout)

from app import __version__

APP_NAME = "一表通（OneSheet）"
APP_DESC = ("多表归一：从 Excel / Word / PDF / CSV 文件中提取「表单（标签:值）」"
            "数据并汇总，支持把编辑后的汇总值反向写回 Excel 源文件。")
ICON_SOURCE_URL = (
    "https://www.iconfont.cn/spm=a313x.search_index.i3.2.39b63a81JBa7Zv")
CONTACT_EMAIL = "13074050195@163.com"


def _link_label(url: str, text: str) -> QLabel:
    """可点击、用系统浏览器 / 邮件客户端打开的链接标签。"""
    label = QLabel(f'<a href="{url}">{text}</a>')
    label.setOpenExternalLinks(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    label.setToolTip(url)
    return label


class AboutDialog(QDialog):
    """帮助 → 关于。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)

        header = QLabel("关于")
        header.setObjectName("sectionHeader")
        layout.addWidget(header)

        self.app_name_label = QLabel(APP_NAME)
        self.app_name_label.setStyleSheet(
            "font-size: 15px; font-weight: bold; padding: 2px 2px 0 2px;")
        layout.addWidget(self.app_name_label)

        self.version_label = QLabel(f"版本 {__version__}")
        self.version_label.setObjectName("dialogHint")
        layout.addWidget(self.version_label)

        self.desc_label = QLabel(APP_DESC)
        self.desc_label.setObjectName("dialogHint")
        self.desc_label.setWordWrap(True)
        layout.addWidget(self.desc_label)

        self.credit_box = QGroupBox("致谢与联系")
        form = QFormLayout(self.credit_box)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.addRow("图标", _link_label(ICON_SOURCE_URL, "阿里巴巴矢量图标库"))
        form.addRow("代码", QLabel("忧凉 & DeepSeek-V4.1-Flash-1017"))
        form.addRow("邮箱", _link_label(f"mailto:{CONTACT_EMAIL}", CONTACT_EMAIL))
        form.addRow("声明", QLabel("如有侵权，联系删除。"))
        layout.addWidget(self.credit_box)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.resize(480, 330)
