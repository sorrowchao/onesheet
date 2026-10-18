"""反向写入：把汇总表每一行回填到对应分表。

按「匹配字段」（主键列）从分表定位汇总行，只回填有 value_row/value_col 的字段。
写回结果另存到指定目录，不覆盖原表。

格式分支：
- .xlsx（魔数 PK\\x03\\x04）：openpyxl 载入后改单元格保存，保留格式。
- .xls（魔数 OLE2）：xlrd + xlutils.copy 复制后写单元格保存，尽量保留格式/合并单元格。
"""
from copy import copy
from pathlib import Path
from typing import Any, Callable, Optional

from .models import FieldMapping, OutputTable, ResultTable
from .reader import detect_format, read_excel


def read_summary_xlsx(path: str) -> ResultTable:
    """读汇总 xlsx（第一个 sheet，首行=表头，余下=数据行）。"""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    max_row = ws.max_row or 0
    max_col = ws.max_column or 0
    columns: list[str] = []
    rows: list[list[Any]] = []
    for r in range(1, max_row + 1):
        vals = [ws.cell(row=r, column=c).value for c in range(1, max_col + 1)]
        if r == 1:
            columns = ["" if v is None else str(v) for v in vals]
        else:
            rows.append(vals)
    wb.close()
    return ResultTable(name=ws.title, columns=columns, rows=rows)


def _locate_sheet(sheets, keyword: str):
    """按 sheet 名关键字定位，返回 (SheetData, index)；找不到返回 (None, -1)。"""
    if not sheets:
        return None, -1
    if not keyword:
        return sheets[0], 0
    for i, s in enumerate(sheets):
        if keyword in s.name:
            return s, i
    return None, -1


def _cell(grid: list[list], r: int, c: int):
    """取 grid[r][c]（0-based），越界返回 None。"""
    if 0 <= r < len(grid):
        row = grid[r]
        if 0 <= c < len(row):
            return row[c]
    return None


def _norm_key(v) -> str:
    """键值归一化，用于跨格式/类型比对，避免「同一值因存储/类型不同而匹配不上」。

    - None → ""
    - 数值：整型浮点去掉小数位（34.0 → 34）；NaN 等特殊值原样
    - 字符串：去首尾空白；带千分位逗号或小数的数值字符串归一为数值形式
      （"1,234" → "1234"、"34.0" → "34"）；纯数字文本（如 "007"）保留原样以保住前导零
    """
    if v is None:
        return ""
    if isinstance(v, float):
        if v != v:  # NaN
            return "nan"
        if v.is_integer():
            return str(int(v))
        return str(v)
    if isinstance(v, int):
        return str(v)
    s = str(v).strip()
    if s == "":
        return ""
    # 只有含千分位逗号或小数点时才尝试按数值归一，
    # 避免把 "007" 之类的文本 ID 误压成 7。
    if "," in s or "，" in s or "." in s:
        t = s.replace(",", "").replace("，", "")
        try:
            f = float(t)
            if f.is_integer():
                return str(int(f))
            return str(f)
        except ValueError:
            return s
    return s


def _find_key_field(output_table: OutputTable, key_target: str):
    """在字段里找 target == key_target 且有值位置的字段；无则 None。"""
    for f in output_table.fields:
        if f.target == key_target and f.value_row is not None and f.value_col is not None:
            return f
    return None


def _plan_files(files: list[str], output_table: OutputTable,
                summary: ResultTable, key_cols: list[int],
                progress_cb: Optional[Callable[[int, int], None]] = None,
                cancel_cb: Optional[Callable[[], bool]] = None) -> dict:
    """读取并匹配所有分表，但**不写盘**（供预演与正式写入共用）。

    返回：
        matched: [(路径, SheetData, sheet 序号, writes)]，writes 为 {(行, 列): 值}
        unmatched: [未匹配到汇总行的输入路径...]
        errors: [(路径, 错误信息)...]
        unused_rows: [未被任何文件使用的汇总数据行号（1-based）...]
        cancelled: 是否因取消而提前结束
    """
    plan: dict = {"matched": [], "unmatched": [], "errors": [],
                  "unused_rows": [], "cancelled": False}

    # 每个匹配列 → 模板里对应的定位字段；没有定位位置的列记为「缺失」。
    key_specs: list[tuple[int, FieldMapping]] = []
    missing_targets: list[str] = []
    for kc in key_cols:
        if not (0 <= kc < len(summary.columns)):
            continue
        target = summary.columns[kc]
        f = _find_key_field(output_table, target)
        if f is None:
            missing_targets.append(str(target))
        else:
            key_specs.append((kc, f))

    used_rows: set[int] = set()
    total = len(files)

    for i, path in enumerate(files):
        if cancel_cb is not None and cancel_cb():
            plan["cancelled"] = True
            break
        try:
            if missing_targets:
                plan["errors"].append(
                    (path, f"目标模板里没有与匹配列「{'、'.join(missing_targets)}」对应的定位字段"))
                continue

            sheets = read_excel(path)
            sheet, sheet_idx = _locate_sheet(sheets, output_table.sheet.sheet_keyword)
            if sheet is None:
                plan["errors"].append(
                    (path, f"未找到 sheet：{output_table.sheet.sheet_keyword or '(第一个)'}"))
                continue

            # 读取分表里每个匹配字段的值
            key_values = [_cell(sheet.grid, f.value_row - 1, f.value_col - 1)
                          for _kc, f in key_specs]
            if all(_norm_key(v) == "" for v in key_values):
                plan["unmatched"].append(path)
                continue

            matched: Optional[list[Any]] = None
            for idx, row in enumerate(summary.rows):
                if all(_norm_key(row[kc] if kc < len(row) else None) == _norm_key(kv)
                       for (kc, _f), kv in zip(key_specs, key_values)):
                    matched = row
                    used_rows.add(idx)
                    break
            if matched is None:
                plan["unmatched"].append(path)
                continue

            writes: dict[tuple[int, int], Any] = {}
            for f in output_table.fields:
                if f.value_row is None or f.value_col is None:
                    continue
                if f.target not in summary.columns:
                    continue
                col_i = summary.columns.index(f.target)
                val = matched[col_i] if col_i < len(matched) else None
                if val is None:
                    continue
                writes[(f.value_row, f.value_col)] = val

            plan["matched"].append((path, sheet, sheet_idx, writes))
        except Exception as e:  # noqa: BLE001 — 单文件失败不中断整体
            plan["errors"].append((path, str(e)))
        finally:
            if progress_cb:
                progress_cb(i + 1, total)

    plan["unused_rows"] = [idx + 1 for idx in range(len(summary.rows))
                           if idx not in used_rows]
    return plan


def preview_write_back(files: list[str], output_table: OutputTable,
                       summary: ResultTable, key_cols: list[int],
                       progress_cb: Optional[Callable[[int, int], None]] = None,
                       cancel_cb: Optional[Callable[[], bool]] = None) -> dict:
    """预演反向写入：只读取匹配，不写任何文件。

    返回 {file_count, cell_count, unmatched, errors, unused_rows, cancelled}。
    """
    plan = _plan_files(files, output_table, summary, key_cols,
                       progress_cb=progress_cb, cancel_cb=cancel_cb)
    return {
        "file_count": len(plan["matched"]),
        "cell_count": sum(len(writes) for _p, _s, _i, writes in plan["matched"]),
        "unmatched": plan["unmatched"],
        "errors": plan["errors"],
        "unused_rows": plan["unused_rows"],
        "cancelled": plan["cancelled"],
    }


def write_back(files: list[str], output_table: OutputTable,
               summary: ResultTable, key_cols: list[int], output_dir: str,
               progress_cb: Optional[Callable[[int, int], None]] = None,
               cancel_cb: Optional[Callable[[], bool]] = None) -> dict:
    """把 summary 每行回填到对应分表，返回报告。

    key_cols：勾选的匹配列索引（可多个）。分表行只有在这些列的值
    与汇总行「全部一致」时才视为匹配（复合主键，避免重复匹配）。

    报告结构：
        written: [输出路径...]
        unmatched: [未匹配到汇总行的输入路径...]
        errors: [(路径, 错误信息)...]
        unused_rows: [未被任何文件使用的汇总数据行号（1-based）...]
        cancelled: 是否因取消而提前结束
    """
    plan = _plan_files(files, output_table, summary, key_cols,
                       progress_cb=progress_cb, cancel_cb=cancel_cb)
    report: dict = {"written": [],
                    "unmatched": plan["unmatched"],
                    "errors": list(plan["errors"]),
                    "unused_rows": plan["unused_rows"],
                    "cancelled": plan["cancelled"]}

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for path, sheet, sheet_idx, writes in plan["matched"]:
        try:
            report["written"].append(_save(path, sheet, sheet_idx, writes, out_dir))
        except Exception as e:  # noqa: BLE001 — 单文件失败不中断整体
            report["errors"].append((path, str(e)))
    return report


def _save(path: str, sheet, sheet_idx: int,
          writes: dict[tuple[int, int], Any], out_dir: Path) -> str:
    """按真实格式把单元格写回，输出到 out_dir，返回输出路径。"""
    fmt = detect_format(path)
    stem = Path(path).stem
    out_path = out_dir / (stem + (".xlsx" if fmt == "xlsx" else ".xls"))
    if fmt == "xlsx":
        _save_xlsx(path, sheet.name, writes, str(out_path))
    else:
        _save_xls(path, sheet_idx, writes, str(out_path))
    return str(out_path)


def _save_xlsx(path: str, sheet_name: str,
               writes: dict[tuple[int, int], Any], out_path: str) -> None:
    import openpyxl
    wb = openpyxl.load_workbook(path)
    if sheet_name not in wb.sheetnames:
        sheet_name = wb.sheetnames[0]
    ws = wb[sheet_name]
    # 合并单元格里只有左上角可写，其余是只读的 MergedCell；
    # 把落在合并区内的写入重定向到该区左上角，避免写只读单元格报错。
    merge_topleft: dict[tuple[int, int], tuple[int, int]] = {}
    for rng in ws.merged_cells.ranges:
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                merge_topleft[(r, c)] = (rng.min_row, rng.min_col)
    for (r, c), v in writes.items():
        tr, tc = merge_topleft.get((r, c), (r, c))
        cell = ws.cell(row=tr, column=tc)
        cell.value = v
        # 回填单元格默认水平居中（保留原有其它对齐属性）
        align = copy(cell.alignment)
        align.horizontal = "center"
        cell.alignment = align
    wb.save(out_path)
    wb.close()


def _save_xls(path: str, sheet_idx: int,
              writes: dict[tuple[int, int], Any], out_path: str) -> None:
    import xlrd
    import xlwt
    from xlutils.filter import XLRDReader, XLWTWriter, process
    try:
        rb = xlrd.open_workbook(path, formatting_info=True)
    except Exception:  # noqa: BLE001 — 极少数 .xls 无法读取格式信息时回退
        rb = xlrd.open_workbook(path)
    # 直接用 XLWTWriter 复制：它会产出按「原始 xf 索引」对齐的 style_list，
    # 使我们在改写单元格时能沿用其原有字体/边框/底色等格式（普通 xlcopy 做不到）。
    writer = XLWTWriter()
    process(XLRDReader(rb, Path(path).name), writer)
    wb = writer.output[0][1]
    if not (0 <= sheet_idx < len(rb.sheets())):
        sheet_idx = 0
    ws = wb.get_sheet(sheet_idx)
    style_list = getattr(writer, "style_list", [])
    rd_sheet = rb.sheet_by_index(sheet_idx) if rb.formatting_info else None
    for (r, c), v in writes.items():
        ws.write(r - 1, c - 1, v, _centered_xls_style(style_list, rd_sheet, r - 1, c - 1))
    wb.save(out_path)


def _centered_xls_style(style_list: list, rd_sheet, r: int, c: int):
    """取原单元格样式（若有）并改为水平居中；取不到则用默认居中样式。"""
    import xlwt
    if rd_sheet is not None and style_list:
        xf_index = rd_sheet.cell_xf_index(r, c)
        if 0 <= xf_index < len(style_list):
            style = copy(style_list[xf_index])
            style.alignment = copy(style.alignment)
            style.alignment.horz = xlwt.Alignment.HORZ_CENTER
            return style
    style = xlwt.XFStyle()
    style.alignment.horz = xlwt.Alignment.HORZ_CENTER
    return style
