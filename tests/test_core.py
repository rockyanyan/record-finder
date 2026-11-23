"""核心逻辑测试：折叠匹配、查询语法、导入规整、存储与导出。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import exporter, importer, search, store  # noqa: E402


SAMPLE = """序号\t数据标题\t产品名称\t产品规格
1\tRM.MP.RNB.020\t圆形裸端子\tRNBS5.5-4-90D
2\tRM.MP.RNB.019\t圆形裸端子\tRNB8-4
3\tRM.MP.RNB.014\t圆形裸端子\tRNB2-10
4\tRM.MP.RNB.001\t圆形裸端子\tRNB5.5-5
"""


def test_fold_drops_symbols_and_case():
    assert search.norm("RNBS5.5-4-90D") == "rnbs55490d"
    assert search.norm("ＲＮＢ８－４") == "rnb84"


def test_parse_query_and_or():
    assert search.parse_query("  裸端子   5.5 ") == [["裸端子"], ["55"]]
    assert search.parse_query("RNB2|RNB3 rnb") == [["rnb2", "rnb3"], ["rnb"]]


def test_paste_table_and_header():
    table = importer.paste_to_table(SAMPLE, name="端子清单")
    assert table.columns == ["序号", "数据标题", "产品名称", "产品规格"]
    assert len(table.rows) == 4
    assert table.rows[0] == ["1", "RM.MP.RNB.020", "圆形裸端子", "RNBS5.5-4-90D"]


def test_single_column_paste_gets_default_header():
    table = importer.paste_to_table("RNB8-4\nRNB14-8\n")
    assert table.columns == ["列1"]
    assert len(table.rows) == 2


def test_search_finds_variant_forms():
    table = importer.paste_to_table(SAMPLE)
    recs = [
        search.Record(table.source or "t", 1, i + 1, r)
        for i, r in enumerate(table.rows)
    ]
    hits = search.search(recs, "rnbs5.5-4")
    assert len(hits) == 1
    assert hits[0].record.values[3] == "RNBS5.5-4-90D"
    assert hits[0].score >= search.SCORE_PREFIX

    hits = search.search(recs, "RNB2|RNB3")
    assert [h.record.values[3] for h in hits] == ["RNB2-10"]

    assert len(search.search(recs, "裸端子 5.5")) == 2


def test_spans_mark_case_insensitive_region():
    s = search.spans("RNBS5.5-4-90D", [search.norm("rnbs5.5-4")])
    assert s and s[0][0] == 0 and s[0][1] == 9


def test_store_roundtrip(tmp_path):
    st = store.Store(tmp_path / "t.db")
    pid = st.create_project("端子项目", "测试用")
    table = importer.paste_to_table(SAMPLE)
    st.add_dataset(pid, "清单A", table.columns, table.rows, table.source)

    recs = st.load_records(pid)
    assert len(recs) == 4
    hits = search.search(recs, "rnb8-4")
    assert hits and hits[0].record.values[1] == "RM.MP.RNB.019"

    assert st.get_project(pid).nrows == 4
    assert st.list_datasets(pid)[0].columns == table.columns

    dup = st.duplicate_project(pid, "端子项目副本")
    assert len(st.load_records(dup)) == 4

    st.delete_dataset(st.list_datasets(pid)[0].id)
    assert st.load_records(pid) == []
    st.close()


def test_export_csv_and_xlsx(tmp_path):
    st = store.Store(tmp_path / "t.db")
    pid = st.create_project("p")
    table = importer.paste_to_table(SAMPLE)
    st.add_dataset(pid, "清单A", table.columns, table.rows)
    recs = st.load_records()
    cols = ["序号", "数据标题", "产品名称", "产品规格"]

    csv_path = exporter.export(tmp_path / "out.csv", recs, cols, with_source=True)
    text = csv_path.read_text(encoding="utf-8-sig")
    assert "数据表" in text.splitlines()[0]
    assert "RNBS5.5-4-90D" in text

    xlsx_path = exporter.export(tmp_path / "out.xlsx", recs, cols)
    assert xlsx_path.exists() and xlsx_path.stat().st_size > 0
    st.close()


def test_excel_import_roundtrip(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "端子"
    for line in SAMPLE.strip().splitlines():
        ws.append(line.split("\t"))
    path = tmp_path / "端子.xlsx"
    wb.save(str(path))

    tables = importer.to_tables(path)
    assert len(tables) == 1
    assert tables[0].columns == ["序号", "数据标题", "产品名称", "产品规格"]
    assert len(tables[0].rows) == 4
    assert tables[0].source.endswith("端子.xlsx")


def test_totals_dedup_keeps_unique_rows():
    text = "A\tB\n1\tx\n1\tx\n2\ty\n"
    table = importer.paste_to_table(text)
    assert len(table.rows) == 2
    assert table.total_rows == 3


def test_data_dir_prefers_env_override(tmp_path, monkeypatch):
    """RECORD_FINDER_HOME 必须最优先，便于脚本/多套数据隔离。"""
    target = tmp_path / "custom-home"
    monkeypatch.setenv("RECORD_FINDER_HOME", str(target))
    assert store.data_dir() == target
    assert store.default_db_path() == target / "record-finder.db"


def test_installed_build_never_uses_app_dir_for_data(tmp_path, monkeypatch):
    """安装版（注册表里有 DataPath）必须把数据放到该路径，

    绝不能落在程序目录 —— 那个目录卸载时会被清掉，会导致用户数据丢失。
    """
    monkeypatch.delenv("RECORD_FINDER_HOME", raising=False)
    monkeypatch.delenv("RECORD_FINDER_DB", raising=False)
    fake_data = tmp_path / "localappdata" / "RecordFinder"
    monkeypatch.setattr(store, "_registry_data_dir", lambda: fake_data)

    resolved = store.data_dir()
    assert resolved == fake_data
    assert resolved.exists()


def test_portable_build_uses_adjacent_data_dir(tmp_path, monkeypatch):
    """绿色版（无注册表）仍然把数据放在程序旁边，方便随身携带。"""
    monkeypatch.delenv("RECORD_FINDER_HOME", raising=False)
    monkeypatch.setattr(store, "_registry_data_dir", lambda: None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe = tmp_path / "app" / "记录检索器.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe))

    assert store.data_dir() == tmp_path / "app" / "data"
