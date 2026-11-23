"""交互式走一遍安装向导并逐页截图，确认中文、图片、文案的实际观感。

做法：不数页数，而是每轮重新找窗口、截图；页数变少了也不会把窗口提前按消失。

用法：python tools/shot_installer.py
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP = ROOT / "dist" / "installer" / "记录检索器-1.0.0-安装程序.exe"
OUT = Path(os.environ.get("TEMP", ".")) / "rf-installer-shots"
APP_DIR = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "RecordFinder"
DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "RecordFinder"

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def force_front(hwnd: int) -> None:
    user32.ShowWindow(hwnd, 9)
    fg = user32.GetForegroundWindow()
    cur = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    tgt_tid = user32.GetWindowThreadProcessId(hwnd, None)
    for tid in {fg_tid, tgt_tid}:
        user32.AttachThreadInput(cur, tid, True)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    for tid in {fg_tid, tgt_tid}:
        user32.AttachThreadInput(cur, tid, False)
    time.sleep(0.15)


def find_window(title_part: str = "安装") -> int | None:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if title_part in buf.value:
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            if cls.value.startswith("T"):
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def grab(hwnd: int, name: str) -> bool:
    from PIL import ImageGrab

    force_front(hwnd)
    time.sleep(0.6)
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w < 200 or h < 200:
        print(f"! {name} 窗口尺寸异常 {w}x{h}")
        return False
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{name}.png"
    img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
    if img.width < 2 or img.height < 2:
        print(f"! {name} 截图为空")
        return False
    img.save(p)
    print(f"@ {p.name}  ({w}x{h})")
    return True


def press(key: str = "{ENTER}", title: str = "安装") -> None:
    ps = (
        "$w = New-Object -ComObject WScript.Shell; "
        f"$w.AppActivate('{title}'); Start-Sleep -Milliseconds 350; "
        f"$w.SendKeys('{key}')"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)


def main() -> int:
    if not SETUP.exists():
        print("找不到安装包")
        return 2
    for d in (APP_DIR, DATA_DIR):
        shutil.rmtree(d, ignore_errors=True)
    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen([str(SETUP)])
    hwnd = None
    for _ in range(40):
        time.sleep(0.5)
        hwnd = find_window()
        if hwnd:
            break
    if not hwnd:
        print("没找到安装向导窗口")
        proc.terminate()
        return 1

    names = ["01-welcome", "02-dir", "03-tasks", "04-ready", "05-progress", "06-finish"]
    shot = 0
    last_alive = time.time()
    for _ in range(120):
        time.sleep(0.8)
        hwnd = find_window()
        if not hwnd:
            if proc.poll() is not None or time.time() - last_alive > 15:
                break
            continue
        last_alive = time.time()
        if shot < len(names):
            if grab(hwnd, names[shot]):
                shot += 1
        press()

    time.sleep(2)
    subprocess.run(["taskkill", "/IM", "记录检索器.exe", "/F"], capture_output=True)
    for d in (APP_DIR, DATA_DIR):
        shutil.rmtree(d, ignore_errors=True)
    print(f"完成，共 {shot} 张截图")
    return 0 if shot >= 3 else 1


if __name__ == "__main__":
    sys.exit(main())
