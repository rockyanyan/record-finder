"""导出层：把检索结果或整张数据表写成 CSV / Excel。"""

from __future__ import annotations

import csv
from pathlib import Path

from .search import Hit, Record


def _matrix(records: list[Record], columns: list[str], with_source: bool) -> list[list[str]]:
    head = (["数据表"] if with_source else []) + ["序号"] + columns
    out = [head]
    for rec in records:
        vals = list(rec.values)[: len(columns)]
        vals += [""] * (len(columns) - len(vals))
        row = ([rec.dataset] if with_source else []) + [str(rec.row_no)] + vals
        out.append(row)
    return out


def export_csv(
    path: str | Path,
    records: list[Record],
    columns: list[str],
    with_source: bool = False,
) -> Path:
    """写 UTF-8 BOM 的 CSV，Excel 直接双击打开不乱码。"""
    p = Path(path)
    with p.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerows(_matrix(records, columns, with_source))
    return p


def export_xlsx(
    path: str | Path,
    records: list[Record],
    columns: list[str],
    with_source: bool = False,
    title: str = "检索结果",
) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    p = Path(path)
    wb = Workbook()
    ws = wb.active
    ws.title = title[:30] or "检索结果"

    data = _matrix(records, columns, with_source)
    for row in data:
        ws.append(row)

    head_fill = PatternFill("solid", fgColor="EAF1FB")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"

    widths: dict[int, int] = {}
    for row in data[:400]:
        for i, val in enumerate(row, start=1):
            width = sum(2 if ord(ch) > 127 else 1 for ch in str(val))
            widths[i] = max(widths.get(i, 6), min(width + 2, 52))
    for i, width in widths.items():
        ws.column_dimensions[get_column_letter(i)].width = width

    wb.save(str(p))
    return p


def export(
    path: str | Path,
    records: list[Record] | list[Hit],
    columns: list[str],
    with_source: bool = False,
) -> Path:
    """按后缀分派导出。"""
    plain = [r.record if isinstance(r, Hit) else r for r in records]
    p = Path(path)
    if p.suffix.lower() in {".xlsx", ".xlsm"}:
        return export_xlsx(p, plain, columns, with_source)
    return export_csv(p, plain, columns, with_source)


def export_rows(path: str | Path, header: list[str], rows: list[list[str]]) -> Path:
    """直接写已经拼好的二维表（表头 + 行），按后缀分派。"""
    p = Path(path)
    if p.suffix.lower() in {".xlsx", ".xlsm"}:
        return _write_xlsx(p, header, rows)
    with p.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return p


def _write_xlsx(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "检索结果"
    ws.append(header)
    for row in rows:
        ws.append(row)

    head_fill = PatternFill("solid", fgColor="EAF1FB")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"

    widths: dict[int, int] = {}
    for row in [header] + rows[:400]:
        for i, val in enumerate(row, start=1):
            width = sum(2 if ord(ch) > 127 else 1 for ch in str(val))
            widths[i] = max(widths.get(i, 6), min(width + 2, 52))
    for i, width in widths.items():
        ws.column_dimensions[get_column_letter(i)].width = width
    wb.save(str(path))
    return path
