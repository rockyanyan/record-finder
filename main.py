#!/usr/bin/env python
"""record-finder 入口。

默认打开图形界面；带参数时提供命令行能力，方便批量导入或脚本调用：

    record-finder.exe                       # 打开界面
    record-finder.exe --cli search 关键词   # 命令行检索当前库
    record-finder.exe --cli import 文件.xlsx [项目名]
    record-finder.exe --cli projects        # 列出项目
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def cli(argv: list[str]) -> int:
    from src import importer
    from src.search import search
    from src.store import Store

    store = Store()
    cmd = argv[0] if argv else "help"

    if cmd == "projects":
        for p in store.list_projects():
            print(f"{p.id}\t{p.name}\t{p.nrows} 条\t{p.ndatasets} 表")
        return 0

    if cmd == "import":
        if len(argv) < 2:
            print("用法：--cli import <文件> [项目名]")
            return 2
        src = Path(argv[1])
        pid = store.create_project(argv[2] if len(argv) > 2 else src.stem)
        n = 0
        for t in importer.to_tables(src):
            store.add_dataset(pid, t.source, t.columns, t.rows, t.source)
            n += len(t.rows)
        print(f"已导入 {n} 行到项目 {pid}")
        store.close()
        return 0

    if cmd == "search":
        query = " ".join(argv[1:])
        if not query:
            print("用法：--cli search <关键词>")
            return 2
        hits = search(store.load_records(), query)
        print(f"命中 {len(hits)} 条")
        for h in hits[:50]:
            cols = store.dataset_columns(h.record.dataset_id)
            pairs = ", ".join(
                f"{c}={v}" for c, v in zip(cols, h.record.values) if v
            )
            print(f"[{h.score}] {h.record.project}/{h.record.dataset}#{h.record.row_no}  {pairs}")
        store.close()
        return 0

    print(__doc__ or "用法：--cli {projects|import|search}")
    store.close()
    return 0


def attach_console() -> bool:
    """打包成窗口程序后默认没有控制台。

    返回 True 表示临时开了控制台窗口（交互式，需要按回车才关）。
    如果父进程给了重定向管道（例如脚本调用并抓输出），就直接复用那些句柄，
    这样 ``程序 --cli search xxx > out.txt`` 依然有效。
    """
    if not getattr(sys, "frozen", False):
        return False
    if sys.stdout is not None and not getattr(sys.stdout, "closed", True):
        return False
    try:
        import ctypes
        import io
        import msvcrt
        import os as _os

        kernel32 = ctypes.windll.kernel32
        # 先试继承来的标准输出句柄（管道/文件重定向）
        handle = kernel32.GetStdHandle(-11)
        if handle and handle != ctypes.c_void_p(-1).value:
            try:
                fd = msvcrt.open_osfhandle(handle, _os.O_WRONLY | getattr(_os, "O_BINARY", 0))
                sys.stdout = io.TextIOWrapper(
                    _os.fdopen(fd, "wb", closefd=False), encoding="utf-8",
                    errors="replace", write_through=True, line_buffering=True,
                )
                sys.stderr = sys.stdout
                return False
            except OSError:
                pass
        # 否则自己开一个控制台窗口
        if kernel32.AttachConsole(-1) == 0:
            kernel32.AllocConsole()
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stderr = sys.stdout
        return True
    except Exception:  # noqa: BLE001
        return False


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] in {"--cli", "-c"}:
        interactive = attach_console()
        code = cli(args[1:])
        if interactive:
            try:
                input("\n按回车键关闭…")
            except (EOFError, OSError):
                pass
        return code
    if args and args[0] in {"-h", "--help"}:
        interactive = attach_console()
        print(__doc__)
        if interactive:
            try:
                input("\n按回车键关闭…")
            except (EOFError, OSError):
                pass
        return 0
    from src.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
