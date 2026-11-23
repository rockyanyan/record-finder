"""检索内核：文本规范化、查询解析、打分排序、命中区间定位。

设计要点
--------
* 匹配时把全角/半角、大小写、以及 ``- . / _`` 之类的符号全部折叠掉，
  所以搜 ``rnbs5.5-4`` 能命中 ``RNBS5.5-4-90D``，搜 ``rnb14-6s`` 也能命中 ``RNB14-6S``。
* 空格分隔的多个关键词是「与」关系，``|`` 是「或」关系，例如 ``裸端子 5.5`` 或 ``RNB2|RNB3``。
* 每条记录预计算一份折叠文本（各单元格用 ``\x00`` 连接，避免跨列误命中），
  先在整条记录上做一次快速排除，再定位到具体列，几千到十万行都是毫秒级。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_SPLIT_RE = re.compile(r"\s+")

# 匹配时需要剔除的符号（规格型号里高频出现，保留会挡住子串匹配）
_STRIP = set("-_./\\|,，。;；:：()（）[]【】{}<>《》\"'“”‘’`~!@#$%^&*+=?？、·•—–～＃＠＆％…")


def fold(text: str) -> tuple[str, list[int]]:
    """折叠文本，同时给出每个折叠后字符在原文里的下标（用于高亮定位）。"""
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch).casefold():
            if c.isspace() or c in _STRIP:
                continue
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def norm(text: str) -> str:
    """只取折叠后的文本。"""
    return fold(text)[0]


def parse_query(query: str) -> list[list[str]]:
    """把查询串切成「或词组」列表：外层是与，内层是或。"""
    groups: list[list[str]] = []
    for part in _SPLIT_RE.split(unicodedata.normalize("NFKC", query or "").strip()):
        if not part:
            continue
        alts = [norm(a) for a in part.split("|")]
        alts = [a for a in alts if a]
        if alts:
            groups.append(alts)
    return groups


SCORE_EXACT = 1000
SCORE_PREFIX = 400
SCORE_CONTAINS = 200


@dataclass
class Record:
    """一条数据行。``dataset`` 是所属数据表名，``project`` 是所属项目名。"""

    dataset: str
    dataset_id: int
    row_no: int
    values: list[str]
    project: str = ""
    norms: list[str] = field(default_factory=list)
    joined: str = ""

    def __post_init__(self) -> None:
        if not self.norms:
            self.norms = [norm(v) for v in self.values]
        if not self.joined:
            self.joined = "\x00".join(self.norms)

    def as_dict(self) -> dict:
        return {
            "project": self.project,
            "dataset": self.dataset,
            "dataset_id": self.dataset_id,
            "row_no": self.row_no,
            "values": self.values,
        }


@dataclass
class Hit:
    record: Record
    score: int
    terms: list[str]  # 实际命中的折叠词，用于高亮

    @property
    def columns_hit(self) -> list[int]:
        return sorted({ci for ci, _ in _locate(self.record, self.terms)})


def _locate(record: Record, terms: list[str]) -> list[tuple[int, str]]:
    out = []
    for ci, cn in enumerate(record.norms):
        for t in terms:
            if t and t in cn:
                out.append((ci, t))
    return out


def _score_cell(cell_norm: str, term: str) -> int:
    pos = cell_norm.find(term)
    if pos < 0:
        return 0
    if cell_norm == term:
        return SCORE_EXACT
    if pos == 0:
        return SCORE_PREFIX
    return SCORE_CONTAINS


def search(records: list[Record], query: str, limit: int = 0) -> list[Hit]:
    """在记录集合里检索，返回按相关度排序的命中列表。"""
    groups = parse_query(query)
    if not groups:
        return []

    hits: list[Hit] = []
    for rec in records:
        joined = rec.joined
        total = 0
        matched_terms: list[str] = []
        ok = True
        for alts in groups:
            best = 0
            best_term = ""
            for alt in alts:
                if alt not in joined:
                    continue
                for cn in rec.norms:
                    if not cn:
                        continue
                    s = _score_cell(cn, alt)
                    if s > best:
                        best = s
                        best_term = alt
                        if s == SCORE_EXACT:
                            break
                if best == SCORE_EXACT:
                    break
            if best <= 0:
                ok = False
                break
            total += best
            matched_terms.append(best_term)
        if ok:
            # 命中列越少、关键词越长，通常越精准
            hits.append(Hit(rec, total, matched_terms))

    hits.sort(key=lambda h: (-h.score, h.record.dataset_id, h.record.row_no))
    return hits[:limit] if limit and limit > 0 else hits


def spans(text: str, terms: list[str]) -> list[tuple[int, int]]:
    """在原文里找出所有命中词的区间，供界面高亮。"""
    folded, idx = fold(text)
    if not folded:
        return []
    found: set[tuple[int, int]] = set()
    for t in terms:
        if not t:
            continue
        start = 0
        while True:
            pos = folded.find(t, start)
            if pos < 0:
                break
            a = idx[pos]
            b = idx[min(pos + len(t) - 1, len(idx) - 1)] + 1
            found.add((a, b))
            start = pos + 1
    return sorted(found)
