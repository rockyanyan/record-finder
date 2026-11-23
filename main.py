#!/usr/bin/env python
"""record-finder 入口。

默认打开图形界面；带参数时提供命令行能力，方便批量导入或脚本调用：

    record-finder.exe                       # 打开界面
    record-finder.exe --cli search 关键词   # 命令行检索当前库
    record-finder.exe --cli import 文件.xlsx [项目名]
    record-finder.exe --cli projects        # 列出项目
"""

from __future__ import annotations

import os
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


def _dbg(msg: str) -> None:
    """设置 RF_DEBUG_LOG=<文件路径> 时记录启动诊断信息（打包后排错用）。"""
    path = os.environ.get("RF_DEBUG_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{msg}\n")
    except OSError:
        pass


def _parent_stdout_is_redirected() -> bool:
    """父进程是否把 stdout 重定向到了管道/文件（脚本调用、CI）。

    窗口模式的 exe 没有控制台，sys.stdout 是 None；但 GetStdHandle 仍能拿到
    父进程给的句柄。有句柄就说明是「被调用」而不是「用户双击」，此时绝不能
    弹控制台、也绝不能等回车，否则调用方会一直阻塞到超时。
    """
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        if not handle:
            _dbg("stdout handle: NULL")
            return False
        if handle == ctypes.c_void_p(-1).value:
            _dbg("stdout handle: INVALID")
            return False
        # GetFileType: 2=FILE_TYPE_CHAR（真控制台），1=FILE_TYPE_DISK，3=FILE_TYPE_PIPE
        ftype = ctypes.windll.kernel32.GetFileType(ctypes.c_void_p(handle))
        _dbg(f"stdout handle: {handle} filetype={ftype}")
        return ftype in (1, 3)
    except Exception as exc:  # noqa: BLE001
        _dbg(f"stdout handle probe failed: {exc!r}")
        return False


def attach_console() -> bool:
    """打包成窗口程序后默认没有控制台。

    返回 True 表示临时开了控制台窗口（交互式，需要按回车才关）。
    如果父进程给了重定向管道（脚本调用 / CI 抓输出），就直接复用那些句柄，
    绝不等待输入，这样 ``程序 --cli search xxx > out.txt`` 能正常结束。
    """
    if not getattr(sys, "frozen", False):
        _dbg("not frozen, skip console attach")
        return False
    if sys.stdout is not None and not getattr(sys.stdout, "closed", True):
        _dbg("stdout already usable")
        return False
    try:
        import io
        import msvcrt
        import os as _os

        # 情况一：父进程已重定向（管道/文件）→ 复用句柄，不弹窗、不等输入
        if _parent_stdout_is_redirected():
            import ctypes

            handle = ctypes.windll.kernel32.GetStdHandle(-11)
            try:
                fd = msvcrt.open_osfhandle(handle, _os.O_WRONLY | getattr(_os, "O_BINARY", 0))
                sys.stdout = io.TextIOWrapper(
                    _os.fdopen(fd, "wb", closefd=False), encoding="utf-8",
                    errors="replace", write_through=True, line_buffering=True,
                )
                sys.stderr = sys.stdout
                _dbg("attached to redirected stdout handle")
                return False
            except OSError as exc:
                _dbg(f"open_osfhandle failed: {exc!r}")
        # 情况二：用户手动在终端里跑 → 挂到父控制台，跑完等回车便于看输出
        import ctypes

        kernel32 = ctypes.windll.kernel32
        if kernel32.AttachConsole(-1) == 0:
            kernel32.AllocConsole()
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stderr = sys.stdout
        _dbg("allocated new console")
        return True
    except Exception as exc:  # noqa: BLE001
        _dbg(f"attach_console failed: {exc!r}")
        return False


def wait_for_key() -> None:
    """交互式窗口跑完后等回车，避免控制台一闪而过。

    仅当确实有可交互的 stdin 时才等待；被脚本/CI 调用时立即返回，
    不会把调用方挂死。
    """
    try:
        if sys.stdin is None:
            return
        input("\n按回车键关闭…")
    except (EOFError, OSError, RuntimeError):
        pass


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] in {"--cli", "-c"}:
        interactive = attach_console()
        try:
            code = cli(args[1:])
        finally:
            try:
                sys.stdout.flush()
            except Exception:  # noqa: BLE001
                pass
        if interactive:
            wait_for_key()
        return code
    if args and args[0] in {"-h", "--help"}:
        interactive = attach_console()
        print(__doc__)
        try:
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass
        if interactive:
            wait_for_key()
        return 0
    from src.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
