"""按标签锚点检测整张表相对模板的行/列偏移（纯逻辑，无 Qt）。

模板里的字段位置（`label_row/label_col/value_row/value_col`）是创建模板时
那张表的绝对坐标。若源文件删除了顶部几行（或几列），所有位置都会整体
平移，按原坐标取值会读到空单元格或别的字段。这里用模板已记录的标签
（`label_row/label_col` + `key` 文本）在当前表里查找同一标签，投票得到
统一的 (行偏移, 列偏移)，供抽取、预览和反向写入修正坐标。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .detector import clean_label
from .models import FieldMapping, SheetData

_SOURCE_FILENAME = "filename"
_TRAILING_DIGITS = re.compile(r"[0-9]+$")

# 单字标签（甲/乙/序号等）过于通用，容易误命中，不作为锚点。
MIN_ANCHOR_LEN = 2

# 全角/半角与全角数字统一，便于匹配 AI 识别出的标签。
_WIDTH = str.maketrans({
    "（": "(", "）": ")", "：": ":", "，": ",",
    "　": " ",
    **{chr(0xFF10 + i): str(i) for i in range(10)},
})


def normalize_label(value: object) -> str:
    """标签归一化：去冒号、去全部空白、统一全角括号/数字。"""
    text = "" if value is None else str(value)
    text = clean_label(text.translate(_WIDTH))
    return "".join(text.split())


def label_variants(key: object) -> tuple[str, ...]:
    """标签的候选文本：原文本 + 去掉末尾数字的版本。

    横向表格的字段名是「项目名称1/2/3」，而实际表头只有「项目名称」，
    所以去数字的版本是必要的；同时保留原文本，避免误伤本身以数字结尾
    的真实标签（如「107-1」）。
    """
    norm = normalize_label(key)
    if len(norm) < MIN_ANCHOR_LEN:
        return ()
    base = _TRAILING_DIGITS.sub("", norm)
    if base != norm and len(base) >= MIN_ANCHOR_LEN:
        return (norm, base)
    return (norm,)


@dataclass(frozen=True)
class Alignment:
    """整表相对模板的偏移（1-based 坐标相加）。"""

    row_delta: int = 0
    col_delta: int = 0
    votes: int = 0          # 支持该偏移的标签锚点数
    anchor_count: int = 0    # 参与投票的标签锚点总数
    conflict: bool = False   # 锚点之间是否存在歧义

    @property
    def shifted(self) -> bool:
        return self.row_delta != 0 or self.col_delta != 0

    @property
    def reliable(self) -> bool:
        """找到锚点且无明显歧义。"""
        return self.votes > 0 and not self.conflict

    @property
    def offset(self) -> tuple[int, int]:
        """可安全应用的偏移；证据不足时保持模板原位置。"""
        if not self.reliable:
            return (0, 0)
        return (self.row_delta, self.col_delta)


def _text_index(grid: list[list]) -> dict[str, list[tuple[int, int]]]:
    """归一化文本 → 所有出现位置（0-based）。只索引字符串单元格。"""
    index: dict[str, list[tuple[int, int]]] = {}
    for r, row in enumerate(grid):
        for c, value in enumerate(row):
            if not isinstance(value, str):
                continue
            text = normalize_label(value)
            if text:
                index.setdefault(text, []).append((r, c))
    return index


def _anchors(fields: Iterable[FieldMapping]) -> dict[tuple[int, int], set[str]]:
    """按模板里的标签单元格归并锚点；同一标签格的多个字段只算一个锚点。"""
    anchors: dict[tuple[int, int], set[str]] = {}
    for f in fields:
        if f.source == _SOURCE_FILENAME:
            continue
        if f.label_row is None or f.label_col is None:
            continue
        texts = label_variants(f.key or f.target)
        if texts:
            anchors.setdefault((f.label_row, f.label_col), set()).update(texts)
    return anchors


def align_sheet(sheet: SheetData | None, fields: Iterable[FieldMapping],
                *, min_votes: int = 1) -> Alignment:
    """检测当前 sheet 相对模板的整表偏移。

    每个模板标签在当前表里出现的每个位置都给出一个候选 (dr, dc)，按
    所有锚点投票；票数最高者胜出，平票时取位移最小者（(0, 0) 优先）。
    """
    if sheet is None or not sheet.grid:
        return Alignment()
    anchors = _anchors(fields)
    if not anchors:
        return Alignment()

    index = _text_index(sheet.grid)
    votes: Counter[tuple[int, int]] = Counter()
    for (label_row, label_col), texts in anchors.items():
        deltas = {
            (r0 + 1 - label_row, c0 + 1 - label_col)
            for text in texts
            for r0, c0 in index.get(text, ())
        }
        for delta in deltas:  # 每个锚点对同一偏移最多投一票
            votes[delta] += 1

    if not votes:
        return Alignment(anchor_count=len(anchors))

    best = min(votes, key=lambda d: (-votes[d], abs(d[0]) + abs(d[1]), d))
    if votes[best] < min_votes:
        return Alignment(anchor_count=len(anchors), conflict=True)
    # 非零偏移必须有过半锚点支持：单个标签偶然出现在别处（或模板与文件
    # 本就不匹配）时不能把整表平移；零偏移则不要求过半。
    moved = best != (0, 0)
    majority = votes[best] * 2 > len(anchors)
    conflict = not majority and (moved or len(votes) > 1)
    return Alignment(best[0], best[1], votes[best], len(anchors), conflict)
