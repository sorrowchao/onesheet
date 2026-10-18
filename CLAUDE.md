# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**一表通 (OneSheet)** — Windows desktop GUI (PySide6) for extracting "form (label:value)" data out of Excel files into summary tables, then writing edited summary values back into the source files. Single-user, local. Only the `表单（标签:值）` data shape is supported.

Docs: `PRD.md` (requirements), `M1技术方案.md` (technical design — §4 template JSON schema, §5.2 detection rules), `使用说明.txt` (user guide).

## Commands

```bash
# Run the GUI
python main.py

# Run all tests (194 tests in tests/)
python -m unittest discover -s tests

# Run a single test file / single test method
python -m unittest discover -s tests -p "test_writer.py"
python -m unittest discover -s tests -p "test_writer.py" -k test_round_trip

# Offscreen UI smoke test (must create QApplication before any QWidget)
QT_QPA_PLATFORM=offscreen python ...

# Build standalone exe (onefile, no console) -> dist/onesheet.exe (~25 MB)
python -m PyInstaller --noconfirm --clean onesheet.spec
```

`onesheet.spec` post-filters `a.binaries`/`a.datas` to drop Qt pieces the app never uses
(`opengl32sw`, QML/Quick/virtual-keyboard, QtPdf+qpdf plugin, QtNetwork+tls+Git OpenSSL,
translations, unused image/platform plugins). Keep `qwindows`, `qsvg`/`qsvgicon` (check.svg
and .svg icons), `qico`/`qjpeg` (icon files) and `qmodernwindowsstyle`. `PySide6.QtNetwork`
is also in `excludes` — harmless because PySide6's import of it is wrapped in try/except.

No linter is configured. `tests/` has no `__init__.py`, so always invoke tests via `discover -s tests`, not dotted module paths.

Note there are **two similarly named dirs**: `tests/` (plural) holds the unit tests; `test/` (singular) holds real sample `.xlsx` fixtures for manual/GUI testing (`test/1`, `test/2`, `test/3` — e.g. `张三.xlsx`, `国能混凝土107-*.xlsx`). Don't point the test runner at `test/`.

`AGENTS.md` is just a pointer to this file (for other agent tools) — this file is the single source of truth.

## Architecture

Entry `main.py` → `MainWindow` (`app/main_window.py`), which assembles a 3-panel splitter (FilePanel | PreviewPanel | ConfigPanel) over a bottom QTabWidget with two pages: 汇总结果 (the tabbed `ResultPanel`) and 日志 (`self.log`, read-only `QPlainTextEdit#logView`, hidden until that tab is selected — not a permanent bottom pane), plus a shared progress bar/cancel row, and wires all signals. 试抽当前文件/批量抽取/反向写入/导出▾ sit in the QTabWidget's top-right **corner widget**, sharing the tab bar row with 汇总结果/日志; they carry the dynamic property `compact=true` (`theme.py` shrinks their padding so they match the tab height). The vertical splitter default is `setSizes([2000, 1000])` → bottom result area = 1/3 of the window height (plain `[2, 1]` does NOT work: `setSizes` clamps each entry to the widget's `minimumSizeHint`, skewing the ratio). The window top is a **menu bar** (文件/模板/数据/视图/帮助 — `_build_menus`), not a flat toolbar; action buttons are **placed next to what they act on**: 导入文件/导入文件夹 live in `FilePanel` (emit `import_files_requested`/`import_folder_requested`), 打开模板/保存模板 live in `ConfigPanel` (emit `open_template_requested`/`save_template_requested`, backed by `btn_open_tpl`/`btn_save_tpl`), and 试抽当前文件/批量抽取/反向写入/导出▾ live in a header row above `ResultPanel`. The same actions also appear in the menu bar (intentional duplication) with shortcuts (F5 抽取, Ctrl+Shift+W 回写, Ctrl+O 导入文件, Ctrl+T 模板管理器, etc.). Files/folders can also be dropped onto the window (`MainWindow.dropEvent` / `FilePanel.dropEvent`); `FilePanel.files_dropped` lets the window remember the directory. The UI is skinned to look like VSCode via `app/ui/theme.py` (dark/light QSS, applied to `QApplication`), using rounded cards (8–10px), banded `#sectionHeader` labels and 4px splitters for clear panel separation; 视图 menu → 深色/浅色主题 toggles it live and persists the choice (`settings.get_theme`/`set_theme`, default `dark`). Checkbox ticks are drawn from `app/ui/assets/check.svg` via QSS `image: url(...)` (`theme.check_icon_path()`); the asset is listed in `onesheet.spec` `datas` so the onefile exe can resolve it. Global UI font: `main.py` calls `app/ui/font.py:apply_app_font(app)` **before** constructing `MainWindow`, setting a preferred-family chain (Microsoft YaHei UI → YaHei → Segoe UI → …) at 9.75pt; QSS base text is 13px, and `QPlainTextEdit#logView` (main log + write-back report) uses Consolas. Each panel carries a `#sectionHeader` label (文件管理器/预览/配置). `FilePanel`'s 全选/反选/全不选 all act on the currently **visible** (search-filtered) items; with a keyword, 全选 also unchecks the hidden ones, while 反选 only flips visible ones. Help → 使用说明 opens `使用说明.txt` via `QDesktopServices.openUrl`: source run uses the project root; frozen builds try exe dir, then its parent, then `sys._MEIPASS` (the spec `datas` bundles the file, so a standalone exe still has a copy).

Core pipeline (`app/core/`), one direction is extract, the other is write-back:

- `reader.read_excel` — reads one file's sheets into `SheetData` (full `grid[r][c]` snapshot + merged-cell `Region`s). Dispatches xlsx/xls by **magic bytes**, not extension; `reader.detect_format(path)` holds that logic and is shared with `writer._save`.
- `detector.detect_form_pairs_pos` — heuristically finds `(label, label_row, label_col, value_row, value_col)` pairs in a form sheet (1-based).
- `extractor.extract_file` — per file: produces `{table_name: ResultTable}` from the template's `output_tables` (one row per file, form mode).
- `aggregator.aggregate` — merges per-file results by table name: union of columns (first-seen order), trims, drops empty rows, sorts by first data column, then prepends a `序号` sequence column (`SEQ_COLUMN`).
- `exporter` — writes `{name: ResultTable}` to multi-sheet xlsx, or one csv per table (utf-8-sig).
- `writer.write_back` — reverse write: matches each summary row to a source file by **composite key** (`key_cols`), then writes back only fields with `value_row`/`value_col` positions into `out_dir` (never overwrites originals). Key values are compared via `_norm_key`. Matching lives in `_plan_files`; `preview_write_back` reuses it to report `file_count`/`cell_count` without writing, and `write_back` saves the planned matches. The result table header's 试抽当前文件 uses `extract_file` + `aggregate` on the current preview file in a `TryExtractDialog` (doesn't touch `self._results`). The completion report is **not** a dialog: `_on_write_back_done` writes per-file results plus one summary line (written / unmatched / errors / unused rows) to the log and status bar.
- `ai_scan.recommend_fields` — **AI path** for generating fields: renders the previewed sheet as text (`build_sheet_text`: one line per row, `行N: 列=值 | 列=值 | …`, only non-empty cells, explicit column numbers) → POSTs to DeepSeek's OpenAI-compatible chat completions → parses the JSON reply into `FieldMapping`s. Pure logic, no Qt; network via stdlib `urllib.request` (**no new dependency** — don't add `requests`). `caller` is injectable for tests; `AiScanError` carries friendly zh messages. The local heuristic (`detector.detect_form_pairs_pos`) is unchanged — AI is only an extra "generate fields" entry.

Templates (`app/template/`): `schema.py` (dict ↔ dataclass + `validate`) and `store.py` (JSON under `data/templates/`, base dir from `app/paths.data_dir()`; `save_path`/`duplicate`/`rename`/`delete` power the template manager; `list_templates` returns `{path, name, mtime}`). The manager dialog (`app/ui/template_manager.py`) is a 3-column table (模板名/最后修改/文件) sorted by mtime descending, auto-selecting the newest row, and offers open/rename/duplicate/delete/refresh; entry points are 模板 → 模板管理器… (Ctrl+T) and the ConfigPanel 管理 button.

ConfigPanel → preview linkage: selecting a row in the field table emits `field_selected(FieldMapping)`, and `PreviewPanel.highlight_field` scrolls to and selects the label/value cells (or finds the label text when the field has no positions).

Settings (`app/service/settings.py`): `data/settings.json` holds the DeepSeek API key, the theme, the chosen app icon, the window state (`window_state`: width/height/maximized/splitter sizes), and the last import directory (`last_import_dir`) (base dir from `app/paths.data_dir()`, shared with `store.py`/`ai_scan`). `MainWindow._restore_window_state` applies it at startup and `closeEvent` saves it; import dialogs start in `get_last_import_dir()`. `get_api_key` prefers env `DEEPSEEK_API_KEY`, else the file; missing/corrupt JSON returns `{}` instead of raising. App icons live in `data/icons/` (`.png/.ico/.svg/.jpg/...`); `available_icons` sorts numeric names numerically, `resolve_icon_name`/`get_icon` default to the file named `1` (then the first available). 视图 → 应用图标 lists them; `MainWindow._set_icon` applies the `QIcon` to both `QApplication` and the window and persists the choice.

Threading (`app/service/worker.py`): `ExtractWorker` / `WriteBackWorker` / `AiScanWorker` are `QThread` subclasses that emit progress/result signals back to the main thread. `ExtractWorker` and `WriteBackWorker` support cancellation (`cancel()` + `_cancelled`; Extract emits `cancelled(processed, total)` and returns without `done`; WriteBack passes `cancel_cb` into `writer.write_back`, which sets `report["cancelled"]` and keeps already-written files). `MainWindow` re-entry-guards tasks with `_task_running()` and toggles `btn_cancel` via `_start_task`/`_finish_task`/`_cancel_task`.

Results (`app/ui/result_panel.py`): `ResultPanel` hosts one `ResultTableWidget` (QTableWidget subclass) per table. The widget is editable with Excel-like operations: Ctrl+C/Ctrl+V TSV clipboard, Ctrl+Z/Ctrl+Y undo/redo (full-table snapshots, max 100), Delete clear, context menu insert/delete rows, and `_renumber_seq()` keeps the `序号` column ordered. `read_results()` reads edits back and coerces numbers using baseline types captured in `show_results`.

## Conventions

- `Region`, and `FieldMapping` `value_row/value_col/label_row/label_col`, are **1-based and inclusive**; `bottom/right = -1` means "to the end". `SheetData.grid` is 0-based.
- `FieldMapping.source` is `kv` (the only supported source; the field is vestigial). A `kv` field without `value_row/value_col` resolves the value by matching `key` against scanned `label:value` pairs.
- Output column names come from `FieldMapping.target`. Duplicate targets are auto-renamed by `models.dedupe_targets` (first keeps its name, later ones get `2`, `3`… — only `target` changes, `key` stays).
- `ResultTable` is the universal in-memory table shape (`columns` + `rows`).
- `SEQ_COLUMN` (`序号`) is reserved as the first column and is excluded from write-back matching.

## Gotchas

- **Format detection**: a WPS-saved `.xls` (OLE2) may be named `.xlsx`. Read magic bytes first (`PK\x03\x04` → openpyxl, `\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1` → xlrd), fall back to extension only if unrecognized.
- **Data dir when frozen**: `app/paths.py` resolves it for `store.py`/`settings.py`/`ai_scan.py`. The exe's own `data/templates/` wins if it holds templates; otherwise a parent `data/templates/` with templates is used (so running `dist/onesheet.exe` sees the project's `data/` instead of an empty `dist/data/`); with none it falls back to the exe directory. Don't reintroduce per-module `sys.frozen` branches.
- **Edited results must be read back**: `ResultPanel.read_results()` re-reads the editable QTableWidget and coerces cells back to int/float using the baseline types; `main_window._run_write_back` uses this, not the stale `self._results`.
- **Duplicate value positions**: `models.duplicate_value_positions()` warns when several fields in one output table share the same `(value_row, value_col)`. `MainWindow._confirm_duplicate_positions()` is called by both `_save_template` and `_run_extract`; the user may still proceed.
- **Template save path**: `_save_template` opens a save dialog defaulting to `data/templates/<name>.json` and MUST call `template_store.save_path(tpl, path)` — `save()` ignores the dialog path and writes to the template dir.
- **QComboBox popup**: the popup is a QListView. On real Windows, `selection-color` is applied to the current item but the selection background is not drawn unless an explicit `QComboBox QAbstractItemView::item:selected { background-color; color; }` rule exists — without it the current item is white-on-white in the light theme.
- **Key normalization**: write-back matching uses `writer._norm_key` so `"1,234"`, `1234`, `1234.0` compare equal while `"007"` keeps its leading zeros.
- **config_panel `_loading`**: rebuilding a form under `_loading=True` suppresses `currentRowChanged`; `_rebuild_table_list` must call `_populate_form` explicitly or the first table's form ends up empty.
- **Field-map table selection**: `_FieldsTable` uses `ExtendedSelection` so `删除选中` (`_del_field_row`) can delete several selected rows at once (falls back to the current row when nothing is selected); `_selected_rows()` reads `selectionModel().selectedRows()`. `全选`/`反选`/`全不选` (`_select_all_form`/`_invert_checked`/`_clear_form`) only change check states; `清空` (`_clear_all_form`) deletes every field behind a `QMessageBox` confirm. Row drag-reorder still acts on `currentRow()` only.
- **detector**: do not add a `MIN_HEADER_CELLS` threshold — it kills single-cell headers (e.g. `甲`), which the M1 spec does not require.
- **Persisted templates in-repo**: `data/templates/*.json` (e.g. `11.json`, `xm.json`) are real user templates written by `store.py`; editing them changes behavior at runtime.
- **AI scan**: `ai_scan` sends only the **current previewed sheet** (truncated to `max_rows`/`max_cols`, defaults 200×40 — the 107-2 statistics form runs to ~91 rows, so a smaller cap truncates real fields) and reads the key from env `DEEPSEEK_API_KEY` first, else `data/settings.json` (plaintext — accepted for a single-user local tool). `main_window._on_ai_scan_form` guards reentry via `self._ai_worker` and prompts with `ApiKeyDialog` only when no key is configured. `ApiKeyDialog` is also reachable any time via 数据 → “DeepSeek API Key…” (`_edit_api_key`): it shows the locally stored key masked, with a 显示明文 toggle; submitting empty clears it. The dialog notes when env `DEEPSEEK_API_KEY` is set (env still wins over the file). `settings.get_stored_api_key()` reads only the file; `settings.env_api_key()` reads only the env.
- **AI scan prompt covers three layouts** (it must **not** tell the model to ignore headers — the old prompt did, killing the `107-1` table form): (1) adjacent `label:value` (value = nearest non-empty cell right/below); (2) **横向表格** — header row holds column labels, data rows below, each `header × data-row` a field numbered `项目名称1/2/3…`, sharing the header cell as `label_row/label_col`; (3) **纵向指标表** (e.g. `107-2表`) — `指标名称/计量单位/代码/数量` columns, label in col 1, value in the `数量` column (NOT the `计量单位`/`代码` columns in between). `build_sheet_text` gives every cell its **explicit column number** (`列=值`) so the model never counts tabs — sparse grids made it drift (107-2 returned the empty col 7 instead of the `数量` col 10, and the empty-value filter then dropped everything). It also collapses in-cell newlines/tabs to single spaces, or embedded `\n` (e.g. `项目研究开发人员\n（人）`) adds phantom lines and misaligns row numbers.
- **AI scan filters empty values**: `parse_pairs` drops any field whose resolved value cell is empty/whitespace (`_cell_is_empty`) — so label-only columns (e.g. an empty `其中：政府资金` column, or an empty trailing data row) never make it into the field table. The prompt also asks the model to skip them, but the filter is the reliable guarantee.
- **AI scan logs every real call** to `data/logs/ai_scan.log` (under `app.paths.data_dir()`, appended): parsed fields + raw model reply. Only written when `caller is default_caller` (injected/test callers skip it). Use it to iterate on the prompt — the log shows exactly what the model returned vs. what survived parsing/filtering. Known failure modes seen in the log and counter-instructed in the prompt: (a) form-admin boilerplate (`表号`/`制表机关`/`文号`/`有效期至`) — told to ignore, keep only entity identifiers like `统一社会信用代码`/`单位详细名称`; (b) **off-by-one `value_col`** when the value sits past an empty column (caught by the empty filter, but the prompt now says "列号必须数准"); (c) unit annotations glued to labels (`项目研究开发人员 （人）1`) — prompt now asks for `项目研究开发人员（人）1` (no stray space, number last).
