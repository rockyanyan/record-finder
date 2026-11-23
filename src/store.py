"""存储层：SQLite 单文件数据库，项目 / 数据表 / 数据行三级结构。

数据库默认放在程序旁边的 ``data`` 目录；对已安装到 Program Files 的情况，
自动退回到 ``%LOCALAPPDATA%\\RecordFinder``。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .search import Record

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    note        TEXT DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    source      TEXT DEFAULT '',
    columns     TEXT NOT NULL,
    nrows       INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rows (
    dataset_id  INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    row_no      INTEGER NOT NULL,
    values_json TEXT NOT NULL,
    PRIMARY KEY (dataset_id, row_no)
);

CREATE INDEX IF NOT EXISTS idx_datasets_project ON datasets(project_id);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _writable(target: Path) -> bool:
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".writable"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _registry_data_dir() -> Path | None:
    """安装版会把这个路径写进注册表；绿色版没有这项，返回 None。"""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\RecordFinder") as key:
            value, _ = winreg.QueryValueEx(key, "DataPath")
    except (OSError, ImportError):
        return None
    if not value:
        return None
    return Path(value)


def data_dir() -> Path:
    """数据目录。

    优先级：
      1. 环境变量 RECORD_FINDER_HOME（脚本/多套数据时用）
      2. 安装版：注册表里记录的 %LOCALAPPDATA%\\RecordFinder
         —— 安装目录可能不可写，且卸载会清空它，所以数据绝不能放那里
      3. 绿色版：程序目录旁边的 data（可随身携带）
      4. 兜底：%LOCALAPPDATA%\\RecordFinder
    """
    explicit = os.environ.get("RECORD_FINDER_HOME")
    if explicit:
        return Path(explicit)

    installed = _registry_data_dir()
    if installed is not None:
        installed.mkdir(parents=True, exist_ok=True)
        return installed

    if getattr(sys, "frozen", False):
        portable = Path(sys.executable).resolve().parent / "data"
    else:
        portable = Path(__file__).resolve().parent.parent / "data"
    if _writable(portable):
        return portable

    fallback = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RecordFinder"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def default_db_path() -> Path:
    override = os.environ.get("RECORD_FINDER_DB")
    if override:
        return Path(override)
    return data_dir() / "record-finder.db"


@dataclass
class ProjectInfo:
    id: int
    name: str
    note: str
    created_at: str
    nrows: int = 0
    ndatasets: int = 0


@dataclass
class DatasetInfo:
    id: int
    project_id: int
    name: str
    source: str
    columns: list[str]
    nrows: int
    created_at: str


class Store:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._cache: dict[int, list[Record]] = {}
        self._dataset_names: dict[int, str] = {}

    # ------------------------------------------------------------------ 项目
    def list_projects(self, keyword: str = "") -> list[ProjectInfo]:
        sql = """
            SELECT p.id, p.name, p.note, p.created_at,
                   COALESCE(SUM(d.nrows), 0) AS nrows,
                   COUNT(d.id) AS ndatasets
            FROM projects p LEFT JOIN datasets d ON d.project_id = p.id
        """
        args: list = []
        if keyword:
            sql += " WHERE p.name LIKE ? OR p.note LIKE ?"
            args += [f"%{keyword}%", f"%{keyword}%"]
        sql += " GROUP BY p.id ORDER BY p.id DESC"
        return [
            ProjectInfo(
                r["id"], r["name"], r["note"] or "", r["created_at"],
                int(r["nrows"] or 0), int(r["ndatasets"] or 0),
            )
            for r in self.conn.execute(sql, args)
        ]

    def get_project(self, project_id: int) -> ProjectInfo | None:
        row = self.conn.execute(
            "SELECT id, name, note, created_at FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not row:
            return None
        info = ProjectInfo(row["id"], row["name"], row["note"] or "", row["created_at"])
        for d in self.list_datasets(project_id):
            info.nrows += d.nrows
            info.ndatasets += 1
        return info

    def create_project(self, name: str, note: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO projects(name, note, created_at) VALUES (?, ?, ?)",
            (name.strip() or "未命名项目", note.strip(), now()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def rename_project(self, project_id: int, name: str, note: str | None = None) -> None:
        if note is None:
            self.conn.execute(
                "UPDATE projects SET name = ? WHERE id = ?", (name.strip(), project_id)
            )
        else:
            self.conn.execute(
                "UPDATE projects SET name = ?, note = ? WHERE id = ?",
                (name.strip(), note.strip(), project_id),
            )
        self.conn.commit()

    def delete_project(self, project_id: int) -> None:
        for ds in self.list_datasets(project_id):
            self._cache.pop(ds.id, None)
        self.conn.execute("DELETE FROM rows WHERE dataset_id IN (SELECT id FROM datasets WHERE project_id = ?)", (project_id,))
        self.conn.execute("DELETE FROM datasets WHERE project_id = ?", (project_id,))
        self.conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.conn.commit()

    def duplicate_project(self, project_id: int, new_name: str) -> int:
        src = self.get_project(project_id)
        if not src:
            raise ValueError("项目不存在")
        new_id = self.create_project(new_name, src.note)
        for ds in reversed(self.list_datasets(project_id)):
            self.conn.execute(
                "INSERT INTO datasets(project_id, name, source, columns, nrows, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (new_id, ds.name, ds.source, json.dumps(ds.columns, ensure_ascii=False),
                 ds.nrows, now()),
            )
            new_ds = int(self.conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            self.conn.execute(
                "INSERT INTO rows(dataset_id, row_no, values_json) "
                "SELECT ?, row_no, values_json FROM rows WHERE dataset_id = ?",
                (new_ds, ds.id),
            )
        self.conn.commit()
        return new_id

    # ------------------------------------------------------------------ 数据表
    def list_datasets(self, project_id: int) -> list[DatasetInfo]:
        rows = self.conn.execute(
            "SELECT id, project_id, name, source, columns, nrows, created_at "
            "FROM datasets WHERE project_id = ? ORDER BY id",
            (project_id,),
        )
        out = []
        for r in rows:
            out.append(
                DatasetInfo(
                    r["id"], r["project_id"], r["name"], r["source"] or "",
                    json.loads(r["columns"] or "[]"), int(r["nrows"] or 0), r["created_at"],
                )
            )
        return out

    def add_dataset(
        self, project_id: int, name: str, columns: list[str],
        rows: list[list[str]], source: str = "",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO datasets(project_id, name, source, columns, nrows, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, name.strip() or "未命名数据", source,
             json.dumps(columns, ensure_ascii=False), len(rows), now()),
        )
        ds_id = int(cur.lastrowid)
        payload = [
            (ds_id, i + 1, json.dumps(list(r), ensure_ascii=False))
            for i, r in enumerate(rows)
        ]
        self.conn.executemany(
            "INSERT INTO rows(dataset_id, row_no, values_json) VALUES (?, ?, ?)", payload
        )
        self.conn.commit()
        self._cache.pop(ds_id, None)
        self._dataset_names[ds_id] = name
        return ds_id

    def delete_dataset(self, dataset_id: int) -> None:
        self.conn.execute("DELETE FROM rows WHERE dataset_id = ?", (dataset_id,))
        self.conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
        self.conn.commit()
        self._cache.pop(dataset_id, None)

    def rename_dataset(self, dataset_id: int, name: str) -> None:
        self.conn.execute("UPDATE datasets SET name = ? WHERE id = ?", (name.strip(), dataset_id))
        self.conn.commit()
        self._cache.pop(dataset_id, None)
        self._dataset_names[dataset_id] = name

    def delete_rows(self, dataset_id: int) -> None:
        """清空某张数据表的行（保留列结构）。"""
        self.conn.execute("DELETE FROM rows WHERE dataset_id = ?", (dataset_id,))
        self.conn.execute("UPDATE datasets SET nrows = 0 WHERE id = ?", (dataset_id,))
        self.conn.commit()
        self._cache.pop(dataset_id, None)

    # ------------------------------------------------------------------ 检索
    def load_records(self, project_id: int | None = None) -> list[Record]:
        """把数据行装进内存并折叠好，供检索使用（带缓存）。"""
        datasets = (
            self.list_datasets(project_id)
            if project_id is not None
            else self._all_datasets()
        )
        proj_names = self._project_names()
        out: list[Record] = []
        ds_project: dict[int, int] = {}
        for ds in datasets:
            ds_project[ds.id] = ds.project_id
            self._dataset_names[ds.id] = ds.name
            cached = self._cache.get(ds.id)
            if cached is None:
                cached = self._load_dataset_records(ds)
                self._cache[ds.id] = cached
            out.extend(cached)
        for rec in out:
            rec.project = proj_names.get(ds_project.get(rec.dataset_id, -1), "")
        return out

    def _project_names(self) -> dict[int, str]:
        return {
            int(r[0]): r[1]
            for r in self.conn.execute("SELECT id, name FROM projects")
        }

    def _all_datasets(self) -> list[DatasetInfo]:
        rows = self.conn.execute(
            "SELECT id, project_id, name, source, columns, nrows, created_at FROM datasets ORDER BY project_id, id"
        ).fetchall()
        return [
            DatasetInfo(r["id"], r["project_id"], r["name"], r["source"] or "",
                        json.loads(r["columns"] or "[]"), int(r["nrows"] or 0), r["created_at"])
            for r in rows
        ]

    def _load_dataset_records(self, ds: DatasetInfo) -> list[Record]:
        cur = self.conn.execute(
            "SELECT row_no, values_json FROM rows WHERE dataset_id = ? ORDER BY row_no",
            (ds.id,),
        )
        recs: list[Record] = []
        for row_no, values_json in cur:
            values = json.loads(values_json)
            n = len(ds.columns)
            if len(values) < n:
                values = values + [""] * (n - len(values))
            recs.append(Record(ds.name, ds.id, int(row_no), values))
        return recs

    def dataset_columns(self, dataset_id: int) -> list[str]:
        row = self.conn.execute("SELECT columns FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        return json.loads(row[0] or "[]") if row else []

    def _all_project_datasets(self, project_id: int) -> list[int]:
        return [
            int(r[0]) for r in self.conn.execute(
                "SELECT id FROM datasets WHERE project_id = ?", (project_id,)
            )
        ]

    def dataset_rows(self, dataset_id: int) -> list[list[str]]:
        return [
            json.loads(v) for (v,) in self.conn.execute(
                "SELECT values_json FROM rows WHERE dataset_id = ? ORDER BY row_no",
                (dataset_id,),
            )
        ]

    def dataset_name(self, dataset_id: int) -> str:
        if dataset_id in self._dataset_names:
            return self._dataset_names[dataset_id]
        row = self.conn.execute("SELECT name FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        return row[0] if row else ""

    # ------------------------------------------------------------------ 维护
    def stats(self) -> dict:
        p = self.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        d = self.conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        r = self.conn.execute("SELECT COUNT(*) FROM rows").fetchone()[0]
        size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {"projects": p, "datasets": d, "rows": r, "size": size}

    def vacuum(self) -> None:
        self.conn.execute("VACUUM")
        self.conn.commit()

    def invalidate(self) -> None:
        """数据变更后清掉内存缓存，下次检索重新载入。"""
        self._cache.clear()

    def backup(self, target: str | Path) -> Path:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            shutil.copy2(self.db_path, target)
        return target

    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.close()
        except sqlite3.ProgrammingError:
            pass
