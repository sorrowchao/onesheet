# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：onefile + 无控制台 GUI。

from PyInstaller.utils.hooks import collect_dynamic_libs

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('app/ui/assets/check.svg', 'app/ui/assets'),
           # 内置应用图标：随 exe 打包，换电脑后仍可在「视图 → 应用图标」中选择。
           ('app/icons', 'app/icons'),
           ('使用说明.txt', '.')],
    hiddenimports=['openpyxl', 'xlrd', 'xlwt', 'xlutils',
                   # Word / PDF 输入
                   'docx', 'pdfplumber', 'pdfminer', 'pypdfium2', 'PIL'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # PySide6.__init__ 会条件导入 QtNetwork（用于预加载 OpenSSL），本程序未使用；
    # 排除后仍会被其 try/except ImportError 兜住。
    excludes=['pandas', 'PySide6.QtNetwork'],
    noarchive=False,
    optimize=0,
)

# ---------------------------------------------------------------------------
# 精简：PyInstaller 的 Qt hook 会全量收集插件并沿依赖链带上大量本程序用不到
# 的 DLL。以下条目在 Analysis 之后直接从 binaries/datas 中剔除：
#   - opengl32sw.dll：Qt 软件 OpenGL 回退（纯 QWidget 程序走 raster 渲染）
#   - QML/Quick/虚拟键盘：由 platforminputcontexts 插件连带引入
#   - QtPdf + qpdf 插件：由 imageformats 全量收集连带引入
#   - QtNetwork / tls 插件 / Git 的 OpenSSL（-x64）：由上面的条件导入连带引入
#   - Qt 翻译文件：程序未安装 QTranslator，界面文本均为硬编码
#   - 未用到的图片格式与平台插件（保留 qwindows、qico、qjpeg、qsvg、qsvgicon）
# 需要保留的：QtCore/QtGui/QtWidgets、QtSvg（勾选框 SVG 与 .svg 图标）、
# 图标引擎 qsvgicon、图片插件 qico/qjpeg、样式 qmodernwindowsstyle。
_DROP = (
    'PySide6/opengl32sw.dll',
    'PySide6/Qt6Qml',
    'PySide6/Qt6Quick',
    'PySide6/Qt6VirtualKeyboard',
    'PySide6/Qt6OpenGL',
    'PySide6/Qt6Pdf',
    'PySide6/Qt6Network',
    'PySide6/QtNetwork.pyd',
    'PySide6/plugins/platforminputcontexts/',
    'PySide6/plugins/imageformats/qpdf.dll',
    'PySide6/plugins/imageformats/qgif.dll',
    'PySide6/plugins/imageformats/qicns.dll',
    'PySide6/plugins/imageformats/qtga.dll',
    'PySide6/plugins/imageformats/qtiff.dll',
    'PySide6/plugins/imageformats/qwbmp.dll',
    'PySide6/plugins/imageformats/qwebp.dll',
    'PySide6/plugins/platforms/qdirect2d.dll',
    'PySide6/plugins/platforms/qminimal.dll',
    'PySide6/plugins/platforms/qoffscreen.dll',
    'PySide6/plugins/generic/',
    'PySide6/translations/',
    'libcrypto-3-x64.dll',
    'libssl-3-x64.dll',
)


def _is_dropped(entry):
    name = entry[0].replace('\\', '/')
    return any(name == p or name.startswith(p) or name.endswith('/' + p)
               for p in _DROP)


a.binaries = [x for x in a.binaries if not _is_dropped(x)]
a.datas = [x for x in a.datas if not _is_dropped(x)]

# pypdfium2 的原生 DLL 由 hook 之外的动态加载引入，显式收集（重复项由 PyInstaller 去重）。
a.binaries += collect_dynamic_libs('pypdfium2')

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='onesheet',
    icon='app/ui/assets/onesheet.ico',   # exe 文件/任务栏默认图标
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                 # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
