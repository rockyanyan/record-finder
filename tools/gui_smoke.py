"""GUI 冒烟测试：启动界面 → 切项目 → 搜索 → 截图，并检查控件内容。

用法：python tools/gui_smoke.py [输出目录]
需要能创建窗口的桌面会话（Windows 本机即可）。
"""

from __future__ import annotations

import sys
from pathlib import Path

# CI 的英文代码页控制台无法输出中文（UnicodeEncodeError），统一切成 UTF-8
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "shots"


def shoot(app, name: str, settle_ms: int = 320) -> Path | None:
    """截取窗口区域。优先 ImageGrab（渲染真实），失败再退回 PrintWindow。"""
    import time

    deadline = time.time() + settle_ms / 1000
    while time.time() < deadline:
        app.update()
        app.update_idletasks()
        time.sleep(0.02)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.png"
    app.lift()
    app.update()
    try:
        from PIL import ImageGrab

        x, y = app.winfo_rootx(), app.winfo_rooty()
        w, h = app.winfo_width(), app.winfo_height()
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        img.save(path)
        print(f"@ 截图 {path}  ({w}x{h})")
        return path
    except Exception as exc:  # noqa: BLE001
        print(f"! {name}: ImageGrab 失败 {exc}，改用 PrintWindow")
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(app.winfo_id())
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        parent = user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
        rect = wintypes.RECT()
        user32.GetWindowRect(parent, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            print(f"! {name}: 窗口尺寸异常 {w}x{h}")
            return None

        hdc = user32.GetWindowDC(parent)
        mem = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
        gdi32.SelectObject(mem, bmp)
        user32.PrintWindow(parent, mem, 2)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth = w
        bi.biHeight = -h
        bi.biPlanes = 1
        bi.biBitCount = 32
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(parent, hdc)

        from PIL import Image

        img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{name}.png"
        img.save(path)
        print(f"@ 截图 {path}  ({w}x{h})")
        return path
    except Exception as exc:  # noqa: BLE001
        print(f"! {name}: 截图失败 {exc}")
        return None


def main() -> int:
    from src.app import App

    db = OUT / "smoke.db"
    OUT.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()

    app = App(str(db))
    app.geometry("1280x820+40+40")

    # 空库状态
    app.update()
    shoot(app, "01-empty")

    # 导入样例文件
    from src import importer

    pid = app.store.create_project("端子项目")
    for path in sorted((ROOT / "samples").glob("*.xlsx")):
        for table in importer.to_tables(path):
            app.store.add_dataset(pid, table.source, table.columns, table.rows, table.source)
    pid2 = app.store.create_project("传感器项目")
    for table in importer.to_tables(ROOT / "samples" / "传感器清单.xlsx"):
        app.store.add_dataset(pid2, table.source, table.columns, table.rows, table.source)
    app.store.invalidate()
    app.reload_projects(keep=pid)
    app.update()
    shoot(app, "02-loaded")

    # 搜索
    app.q.set("rnbs5.5-4")
    app.run_search()
    app.update()
    print("命中：", app.count_label.cget("text"))
    print("详情首行：", app.detail.get("1.0", "3.0").strip().replace("\n", " | "))
    shoot(app, "03-search")

    app.q.set("RNB2|RNB3")
    app.run_search()
    app.update()
    print("或查询命中：", app.count_label.cget("text"))
    shoot(app, "04-or-search")

    app.q.set("")
    app.scope.set("全部项目")
    app.run_search()
    app.update()
    print("全部范围：", app.count_label.cget("text"))
    assert app.count_label.cget("text") == f"共 {len(app.records)} 条", app.count_label.cget("text")
    app.q.set("变送器")
    app.run_search()
    app.update()
    print("跨项目命中：", app.count_label.cget("text"))
    assert len(app.hits) == 4, f"期望跨项目命中 4 条，实际 {len(app.hits)}"
    shoot(app, "05-all-projects")

    # 选中「全部项目」时范围应自动切到全部
    app.proj_tree.selection_set("all")
    app.update()
    print("选全部项目后范围：", app.scope.get(), app.count_label.cget("text"))
    assert app.scope.get() == "全部项目"

    # 切回具体项目后范围应回到当前项目
    proj_items = [i for i in app.proj_tree.get_children() if i != "all"]
    app.proj_tree.selection_set(proj_items[0])
    app.update()
    print("选具体项目后范围：", app.scope.get(), app.count_label.cget("text"))
    assert app.scope.get() == "当前项目"

    # 放大详情
    sel = app.tree.selection()
    if sel:
        app.open_detail()
        app.update()
        shoot(app, "06-detail")
        for w in app.winfo_children():
            pass
        app.grab_release()

    # 粘贴导入对话框
    app.q.set("")
    app.run_search()
    dlg_cls = __import__("src.app", fromlist=["PasteDialog"]).PasteDialog
    dlg = dlg_cls(app)
    dlg.name.set("粘贴测试")
    dlg.text.insert("1.0", "序号\t产品名称\t产品规格\n9\t圆形裸端子\tRNB2-4\ntest\t环形端子\tRNB3.5-6\n")
    dlg._on_modify()
    app.update()
    print("粘贴预览：", dlg.preview.cget("text"))
    shoot(app, "07-paste")
    dlg.destroy()

    # 数据表管理
    mgr = __import__("src.app", fromlist=["DatasetManager"]).DatasetManager(app, pid)
    app.update()
    shoot(app, "08-datasets")
    mgr.destroy()

    app.store.close()
    app.destroy()
    print("GUI 冒烟测试完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

