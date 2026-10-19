"""模板 dataclass 与 JSON 互转 + 校验。"""
from dataclasses import asdict

from app.core.models import (ExtractTemplate, FieldMapping, OutputTable,
                             SheetConfig)

VALID_SOURCE = {"kv", "filename"}


# --------------------------------------------------------------------------
# dict -> dataclass
# --------------------------------------------------------------------------

def field_from_dict(d: dict) -> FieldMapping:
    return FieldMapping(
        target=d.get("target", ""),
        source=d.get("source", "kv"),
        is_key=d.get("is_key", False),
        key=d.get("key"),
        value_type=d.get("value_type", "text"),
        label_row=d.get("label_row"),
        label_col=d.get("label_col"),
        value_row=d.get("value_row"),
        value_col=d.get("value_col"),
    )


def sheet_from_dict(d: dict) -> SheetConfig:
    return SheetConfig(sheet_keyword=d.get("sheet_keyword", ""))


def output_table_from_dict(d: dict) -> OutputTable:
    return OutputTable(
        name=d.get("name", ""),
        sheet=sheet_from_dict(d.get("sheet") or {}),
        fields=[field_from_dict(f) for f in (d.get("fields") or [])],
    )


def from_dict(data: dict) -> ExtractTemplate:
    return ExtractTemplate(
        name=data.get("name", ""),
        version=data.get("version", 2),
        output_tables=[output_table_from_dict(o) for o in (data.get("output_tables") or [])],
    )


# --------------------------------------------------------------------------
# dataclass -> dict
# --------------------------------------------------------------------------

def to_dict(template: ExtractTemplate) -> dict:
    return asdict(template)


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------

def validate(data: dict) -> list[str]:
    """校验模板 dict，返回错误信息列表（空列表 = 合法）。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["模板根节点必须是对象"]

    if not data.get("name"):
        errors.append("缺少模板名称 name")

    tables = data.get("output_tables")
    if not isinstance(tables, list) or not tables:
        errors.append("output_tables 必须是非空数组")
    else:
        for i, t in enumerate(tables):
            if not isinstance(t, dict):
                errors.append(f"output_tables[{i}] 必须是对象")
                continue
            if not t.get("name"):
                errors.append(f"output_tables[{i}] 缺少 name")
            for j, f in enumerate(t.get("fields") or []):
                if f.get("source") not in VALID_SOURCE:
                    errors.append(f"output_tables[{i}].fields[{j}].source 非法：{f.get('source')}")

    return errors
