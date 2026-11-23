# -*- coding: utf-8 -*-
"""把 record-finder 上传到 GitHub（本机没有 git，走 Git Data API）。

流程：
  1. 建仓库（公开）
  2. 一次性提交全部源码（blob -> tree -> commit -> ref）
  3. 打 tag v1.0.0 并创建 Release
  4. 把 exe / 安装包作为 Release 附件上传（不进版本库）

用法：
    set GITHUB_TOKEN=ghp_xxx
    python tools/upload_github.py --dry-run     # 只列出将上传的文件
    python tools/upload_github.py               # 真正上传

环境变量：
    GITHUB_TOKEN  必填，需要 repo 权限
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
ROOT = Path(__file__).resolve().parent.parent

OWNER = "rockyanyan"
REPO = "record-finder"
DESCRIPTION = (
    "把项目清单导进来，搜一个词就定位到那一行。"
    "Windows 桌面小工具：宽松匹配（忽略大小写与 - . / 符号）、跨项目检索、"
    "Excel/CSV/网页表格粘贴导入、结果导出。单文件 exe，免安装 Python。"
)
TAG = "v1.0.0"
RELEASE_NAME = "记录检索器 v1.0.0"
PRIVATE = False

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

# 不进版本库的路径
EXCLUDE_DIRS = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".git", "node_modules", ".venv", "venv", "build", "dist", "data",
}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".db", ".db-journal", ".db-wal", ".log", ".tmp"}
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}

# 作为 Release 附件上传（不放进仓库）
BINARIES = [
    ROOT / "dist" / "记录检索器.exe",
    ROOT / "dist" / "installer" / "记录检索器-1.0.0-安装程序.exe",
]

RELEASE_NOTES = """## 记录检索器 v1.0.0

把项目清单（Excel / CSV / 网页表格）导进来，以后只搜一个词就能定位到对应的那一行。

### 下载哪个

| 文件 | 说明 |
| --- | --- |
| `记录检索器-1.0.0-安装程序.exe` | **推荐**。下一步装完，带开始菜单图标，可在「设置 → 应用」卸载 |
| `记录检索器.exe` | 绿色单文件，免安装，数据跟着文件夹走 |

系统要求：Windows 10 / 11（64 位），不需要装 Python。

### 亮点

- **宽松匹配**：忽略大小写和 `- . /` 等符号，搜 `rnbs5.5-4` 能命中 `RNBS5.5-4-90D`
- **查询语法**：空格表示「同时包含」，`|` 表示「任一」，如 `RNB2|RNB3`
- **三种导入**：Excel/CSV 文件、网页表格直接粘贴、命令行批量导入
- **跨项目检索**：范围切到「全部项目」，一次搜完所有清单
- **数据安全**：本地 SQLite，不联网不上传；卸载时默认保留数据

### 已知限制

- Excel 仅支持 `.xlsx / .xlsm`，旧版 `.xls` 请先另存
- 结果表最多渲染 5000 行，导出不受限制
- 未做代码签名，首次运行 SmartScreen 可能提示「未知发布者」，选择「仍要运行」即可

详见 [CHANGELOG](CHANGELOG.md)。
"""


# --------------------------------------------------------------------------- HTTP


def api(method: str, path: str, payload=None, retries: int = 3, base: str = API):
    url = base + path
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "record-finder-uploader",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"

    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last = f"HTTP {exc.code}: {detail[:400]}"
            if exc.code in (401, 403, 404, 422) and exc.code != 403:
                raise RuntimeError(last) from None
            if exc.code == 403 and "rate limit" not in detail.lower():
                raise RuntimeError(last) from None
            time.sleep(2 + attempt * 2)
        except urllib.error.URLError as exc:
            last = str(exc)
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"请求失败 {method} {path}: {last}")


def upload_asset(upload_url: str, path: Path) -> dict:
    """上传 Release 附件（走 uploads.github.com，单独的 Content-Type）。"""
    name = path.name
    url = f"{upload_url.split('{')[0]}?name={urllib.parse.quote(name)}"
    data = path.read_bytes()
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "record-finder-uploader",
        "Content-Type": ctype,
        "Content-Length": str(len(data)),
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"附件上传失败 {name}: HTTP {exc.code} {detail[:300]}") from None


# --------------------------------------------------------------------------- 文件收集


def collect_files() -> list[tuple[str, Path]]:
    """返回 (仓库内相对路径, 本地路径)，已按 .gitignore 规则过滤。"""
    out: list[tuple[str, Path]] = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        parts = set(rel.parts)
        if parts & EXCLUDE_DIRS:
            continue
        if rel.name in EXCLUDE_NAMES:
            continue
        if p.suffix.lower() in EXCLUDE_SUFFIX:
            continue
        out.append((rel.as_posix(), p))
    return out


def is_binary(path: Path) -> bool:
    try:
        path.read_bytes()[:8192].decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


# --------------------------------------------------------------------------- 主流程


def ensure_branch(branch: str) -> list[str]:
    """空仓库无法直接建 blob（409 Git Repository is empty）。

    先通过 Contents API 落一个初始提交把分支建立起来，返回其父提交列表。
    """
    try:
        ref = api("GET", f"/repos/{OWNER}/{REPO}/git/ref/heads/{branch}")
        return [ref["object"]["sha"]]
    except RuntimeError:
        pass

    print("      空仓库，先建立初始提交")
    seed_path = ROOT / ".gitignore"
    seed = seed_path.read_text(encoding="utf-8") if seed_path.exists() else "# init\n"
    resp = api("PUT", f"/repos/{OWNER}/{REPO}/contents/.gitignore", {
        "message": "chore: 初始化仓库",
        "content": base64.b64encode(seed.encode("utf-8")).decode("ascii"),
        "branch": branch,
    })
    return [resp["commit"]["sha"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只列出将上传的文件")
    ap.add_argument("--skip-release", action="store_true", help="不上传 Release 附件")
    args = ap.parse_args()

    files = collect_files()
    total = sum(p.stat().st_size for _, p in files)
    print(f"将上传 {len(files)} 个文件，共 {total / 1024:.1f} KB\n")
    for rel, p in files:
        print(f"  {p.stat().st_size:>9,} B  {rel}")
    print()
    for b in BINARIES:
        mark = "" if b.exists() else "  （缺失，将跳过）"
        size = f"{b.stat().st_size / 1024 / 1024:.2f} MB" if b.exists() else "-"
        print(f"  Release 附件：{b.name}  {size}{mark}")

    if args.dry_run:
        print("\n[dry-run] 未做任何改动")
        return 0

    if not TOKEN:
        print("缺少 GITHUB_TOKEN 环境变量")
        return 2

    # 1. 建仓库（存在则沿用）
    print(f"\n[1/4] 创建仓库 {OWNER}/{REPO}")
    try:
        repo = api("POST", "/user/repos", {
            "name": REPO,
            "description": DESCRIPTION,
            "private": PRIVATE,
            "has_issues": True,
            "has_wiki": False,
            "has_projects": False,
            "auto_init": False,
        })
        print(f"      已创建：{repo['html_url']}")
    except RuntimeError as exc:
        if "422" in str(exc):
            print("      仓库已存在，改为更新现有仓库")
            api("PATCH", f"/repos/{OWNER}/{REPO}", {
                "description": DESCRIPTION,
                "private": PRIVATE,
            })
        else:
            raise

    repo = api("GET", f"/repos/{OWNER}/{REPO}")
    branch = repo.get("default_branch") or "main"
    print(f"      默认分支：{branch}")

    parents = ensure_branch(branch)    # 2. 上传 blob
    print(f"\n[2/4] 上传 {len(files)} 个文件内容")
    entries = []
    for i, (rel, path) in enumerate(files, 1):
        data = path.read_bytes()
        binary = is_binary(path)
        payload = {
            "content": base64.b64encode(data).decode("ascii"),
            "encoding": "base64",
        }
        blob = api("POST", f"/repos/{OWNER}/{REPO}/git/blobs", payload)
        entries.append({
            "path": rel,
            "mode": "100755" if rel.endswith(".sh") else "100644",
            "type": "blob",
            "sha": blob["sha"],
        })
        if i % 10 == 0 or i == len(files):
            print(f"      {i}/{len(files)} ...")

    # 3. tree -> commit -> ref
    print("\n[3/4] 创建提交")
    tree = api("POST", f"/repos/{OWNER}/{REPO}/git/trees", {"tree": entries})

    commit_msg = (
        "feat: 记录检索器 v1.0.0\n\n"
        "把项目清单导进来，搜一个词就定位到那一行。\n\n"
        "- 折叠索引匹配：忽略大小写与 - . / 等符号\n"
        "- 查询语法：空格=与，|=或\n"
        "- Excel/CSV/粘贴/命令行四种录入方式\n"
        "- 跨项目检索、结果导出 CSV/xlsx\n"
        "- tkinter 界面 + PyInstaller 单文件打包 + Inno Setup 安装程序\n"
        "- 13 个单元测试 + exe/安装包端到端验收脚本"
    )

    parents = []
    try:
        ref = api("GET", f"/repos/{OWNER}/{REPO}/git/ref/heads/{branch}")
        parents = [ref["object"]["sha"]]
    except RuntimeError:
        pass  # 空仓库，首个提交

    commit = api("POST", f"/repos/{OWNER}/{REPO}/git/commits", {
        "message": commit_msg,
        "tree": tree["sha"],
        "parents": parents,
    })

    if parents:
        api("PATCH", f"/repos/{OWNER}/{REPO}/git/refs/heads/{branch}",
            {"sha": commit["sha"], "force": False})
    else:
        api("POST", f"/repos/{OWNER}/{REPO}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
    print(f"      提交 {commit['sha'][:10]} 已推送到 {branch}")    # 4. Release + 附件
    if args.skip_release:
        print("\n[4/4] 跳过 Release")
    else:
        print(f"\n[4/4] 创建 Release {TAG} 并上传附件")
        try:
            release = api("POST", f"/repos/{OWNER}/{REPO}/releases", {
                "tag_name": TAG,
                "name": RELEASE_NAME,
                "body": RELEASE_NOTES,
                "draft": False,
                "prerelease": False,
            })
        except RuntimeError as exc:
            if "422" in str(exc):
                release = api("GET", f"/repos/{OWNER}/{REPO}/releases/tags/{TAG}")
                print("      Release 已存在，沿用")
            else:
                raise

        existing = {a["name"] for a in release.get("assets", [])}
        for b in BINARIES:
            if not b.exists():
                print(f"      跳过（不存在）：{b.name}")
                continue
            if b.name in existing:
                print(f"      已存在，跳过：{b.name}")
                continue
            print(f"      上传 {b.name} ({b.stat().st_size / 1024 / 1024:.2f} MB) ...")
            asset = upload_asset(release["upload_url"], b)
            print(f"        -> {asset.get('browser_download_url', 'ok')}")

    final = api("GET", f"/repos/{OWNER}/{REPO}")
    print("\n完成：")
    print(f"  仓库：{final['html_url']}")
    print(f"  Release：{final['html_url']}/releases/tag/{TAG}")
    print(f"  克隆：git clone {final['clone_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
