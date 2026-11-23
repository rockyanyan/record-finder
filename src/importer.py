"""导入层：把 Excel / CSV / 浏览器表格粘出来的文本统一变成「表头 + 行」。"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".tsv", ".txt"}

_HEADER_HINTS = (
    "序号", "标题", "名称", "规格", "型号", "编码", "编号", "代码", "单位",
    "数量", "日期", "备注", "描述", "分类", "品牌", "价格", "库存", "项目",
    "name", "code", "spec", "model", "id", "qty", "date", "title", "desc",
)
_NUMERIC_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")


@dataclass
class Table:
    """一张待入库的二维表。"""

    columns: list[str]
    rows: list[list[str]]
    source: str = ""
    total_rows: int = 0


# --------------------------------------------------------------------------- 读取


def read_sheets(path: str | Path) -> list[tuple[str, list[list[str]]]]:
    """按后缀读取文件，返回 [(表名, 二维表), ...]（Excel 每个工作表一项）。"""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return _read_xlsx(p)
    if suffix in {".csv", ".tsv", ".txt"}:
        return [(p.stem, _read_text_file(p))]
    raise ValueError(f"不支持的文件类型：{suffix}（支持 .xlsx / .csv / .tsv / .txt）")


def read_file(path: str | Path) -> list[list[str]]:
    """只取第一个非空工作表的原始行，便于快速预览。"""
    sheets = read_sheets(path)
    return sheets[0][1] if sheets else []


def _read_xlsx(path: Path) -> list[tuple[str, list[list[str]]]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - 打包时已内置
        raise ValueError("缺少 openpyxl，无法读取 Excel") from exc

    wb = load_workbook(filename=str(path), read_only=True, data_only=True)
    try:
        out: list[tuple[str, list[list[str]]]] = []
        for sheet in wb.worksheets:
            block = _sheet_rows(sheet)
            if block:
                out.append((sheet.title, block))
        return out
    finally:
        wb.close()


def _sheet_rows(sheet) -> list[list[str]]:
    out: list[list[str]] = []
    for row in sheet.iter_rows(values_only=True):
        cells = [_cell_text(v) for v in row]
        while cells and cells[-1] == "":
            cells.pop()
        out.append(cells)
    while out and not any(out[-1]):
        out.pop()
    return out


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _read_text_file(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - 极少发生
        text = raw.decode("utf-8", "replace")
    return read_paste(text, prefer_tab=path.suffix.lower() in {".tsv", ".txt"})


def read_paste(text: str, prefer_tab: bool = True) -> list[list[str]]:
    """把「从网页/Excel 复制出来的文本」解析成二维表。

    依次尝试：制表符分隔 → 竖线分隔 → 连续两个以上空格分隔 → 逗号分隔。
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln for ln in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return []

    if any("\t" in ln for ln in lines):
        sep_mode = "tab"
    elif any("|" in ln for ln in lines):
        sep_mode = "pipe"
    elif any("  " in ln.strip() for ln in lines):
        sep_mode = "space"
    elif prefer_tab is False and any("," in ln for ln in lines):
        sep_mode = "csv"
    else:
        sep_mode = "single"

    rows: list[list[str]] = []
    if sep_mode == "csv":
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))]
    else:
        splitter = {
            "tab": lambda ln: ln.split("\t"),
            "pipe": lambda ln: ln.split("|"),
            "space": lambda ln: re.split(r"\s{2,}", ln.strip()),
            "single": lambda ln: [ln],
        }[sep_mode]
        for ln in lines:
            if not ln.strip():
                rows.append([])
                continue
            rows.append([c.strip() for c in splitter(ln)])

    while rows and not any(c for c in rows[0]):
        rows.pop(0)
    while rows and not any(c for c in rows[-1]):
        rows.pop()
    return rows


# --------------------------------------------------------------------------- 规整


def looks_like_header(first: list[str], second: list[str] | None = None) -> bool:
    """判断第一行是不是表头。"""
    cells = [c for c in first if c]
    if not cells:
        return False
    if all(_NUMERIC_RE.match(c) for c in cells):
        return False
    hits = sum(1 for c in cells if any(h in c.lower() for h in _HEADER_HINTS))
    if hits:
        return True
    # 单列数据（例如一列型号）：没有关键词就不当表头，否则第一行会被吃掉
    if len(cells) == 1:
        return False
    # 没有表头关键词时：第一行全是短文本，且第二行出现了第一行没有的值
    if any(len(c) > 24 for c in cells):
        return False
    if second:
        first_set = set(cells)
        novel = [c for c in second if c and c not in first_set]
        if novel:
            return True
    return second is None


def build_table(
    raw_rows: list[list[str]],
    source: str = "",
    has_header: bool | None = None,
) -> Table:
    """把原始二维表规整成 Table：去空行空列、补空表头、去重表头。"""
    rows = [list(r) for r in raw_rows]
    if not rows:
        return Table([], [], source)

    width = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (width - len(r)) for r in rows]

    if has_header is None:
        has_header = looks_like_header(rows[0], rows[1] if len(rows) > 1 else None)

    header = [c.strip() for c in rows[0]] if has_header else ["" for _ in range(width)]
    body = rows[1:] if has_header else rows

    body = [r for r in body if any(c.strip() for c in r)]

    keep = [i for i in range(width) if any(r[i].strip() for r in body)]
    header = [header[i] for i in keep]
    body = [[row[i] for i in keep] for row in body]

    columns: list[str] = []
    used: dict[str, int] = {}
    for i, name in enumerate(header):
        name = name.strip() or f"列{i + 1}"
        if name in used:
            used[name] += 1
            name = f"{name}_{used[name]}"
        else:
            used[name] = 1
        columns.append(name)

    total = len(body)
    # 完全一模一样的数据行只保留一份（很多导出表带重复行）
    seen: set[tuple[str, ...]] = set()
    deduped: list[list[str]] = []
    for r in body:
        key = tuple(c.strip() for c in r)
        if key in seen:
            continue
        seen.add(key)
        deduped.append([c.strip() for c in r])

    return Table(columns, deduped, source, total)


def to_tables(path: str | Path, has_header: bool | None = None) -> list[Table]:
    """把一个文件读成若干张 Table（Excel 多工作表会拆成多张，空表跳过）。"""
    p = Path(path)
    sheets = [(name, rows) for name, rows in read_sheets(p) if rows]
    tables: list[Table] = []
    multi = len(sheets) > 1
    for sheet_name, rows in sheets:
        label = f"{p.stem} · {sheet_name}" if multi else p.name
        table = build_table(rows, source=label, has_header=has_header)
        if table.columns:
            tables.append(table)
    return tables


def paste_to_table(text: str, name: str = "", has_header: bool | None = None) -> Table:
    return build_table(read_paste(text), source=name, has_header=has_header)
