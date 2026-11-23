"""对已打包的 exe 做端到端验收：命令行模式 + 图形界面启动。

用法：python tools/verify_exe.py [exe路径]
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "记录检索器.exe"
WORK = Path(os.environ.get("TEMP", ".")) / "rf-verify"


def run(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    e = os.environ.copy()
    e["PYTHONIOENCODING"] = "utf-8"
    if env:
        e.update(env)
    return subprocess.run(
        [str(EXE), *args], capture_output=True, timeout=180, env=e,
    )


def main() -> int:
    if not EXE.exists():
        print(f"找不到 exe：{EXE}")
        return 2
    print(f"exe：{EXE}  ({EXE.stat().st_size / 1024 / 1024:.2f} MB)")

    if WORK.exists():
        shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    db = WORK / "verify.db"
    env = {"RECORD_FINDER_DB": str(db)}

    # 1. 命令行导入
    xlsx = ROOT / "samples" / "端子清单.xlsx"
    r = run(["--cli", "import", str(xlsx), "端子项目"], env)
    print("import rc=", r.returncode, r.stdout.decode("utf-8", "replace").strip(),
          r.stderr.decode("utf-8", "replace").strip()[:300])
    assert r.returncode == 0, "命令行导入失败"

    # 2. 命令行检索
    r = run(["--cli", "search", "rnbs5.5-4"], env)
    out = r.stdout.decode("utf-8", "replace")
    print("search rc=", r.returncode, out.strip()[:300])
    assert "RNBS5.5-4-90D" in out, "检索没有命中预期行"

    # 3. 图形界面启动（3 秒内不崩溃即视为可启动）
    proc = subprocess.Popen([str(EXE)], env={**os.environ, **env})
    time.sleep(6)
    alive = proc.poll() is None
    print("GUI 进程存活：", alive, "pid", proc.pid)
    if alive:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    else:
        print("!! GUI 启动后立即退出，返回码", proc.returncode)
        return 1

    print("验收通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
