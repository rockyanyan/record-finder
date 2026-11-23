"""tkinter 图形界面：左边项目，右边检索 + 结果 + 详情。

界面刻意做得简单：一个搜索框、一张结果表、一块详情区，
导进来的表格原样保留列，搜到一个词就能定位到对应那一行。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from . import APP_NAME, __version__, importer
from .exporter import export, export_rows
from .search import Hit, Record, search, spans
from .store import Store

MAX_SHOWN = 5000  # 结果表最多渲染这么多行，再多就只提示条数

FONT_FAMILY = "Microsoft YaHei UI"
COLOR_BG = "#f6f7f9"
COLOR_HIT = "#fff3c4"
COLOR_HEAD = "#eef2f7"


def dpi_aware() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def text_width(s: str) -> int:
    """估算显示宽度：中文按 2 个字符宽。"""
    return sum(2 if ord(c) > 127 else 1 for c in str(s))


class App(tk.Tk):
    def __init__(self, db_path: str | None = None) -> None:
        super().__init__()
        self.store = Store(db_path)
        self.records: list[Record] = []
        self.hits: list[Hit] = []
        self._hit_by_iid: dict[str, Hit] = {}
        self._tree_cols: list[str] = []
        self._search_job: str | None = None
        self._ds_columns: dict[int, list[str]] = {}
        self._ds_project: dict[int, int] = {}
        self._project_names: dict[int, str] = {}

        self.title(f"{APP_NAME} {__version__}")
        self.geometry("1280x800")
        self.minsize(980, 620)
        self.configure(bg=COLOR_BG)

        self._init_fonts()
        self._init_style()
        self._build_menu()
        self._build_ui()
        self._bind_keys()

        self.reload_projects()
        self.after(50, self.focus_search)
        self.after(200, self._first_run_hint)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ 外观
    def _init_fonts(self) -> None:
        families = set(tkfont.families())
        family = FONT_FAMILY if FONT_FAMILY in families else "Microsoft YaHei"
        if family not in families:
            family = "SimSun"
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=family, size=10)
            except tk.TclError:
                pass
        self.ui_font = (family, 10)
        self.small_font = (family, 9)
        self.bold_font = (family, 10, "bold")
        self.search_font = (family, 13)
        self.title_font = (family, 11, "bold")

    def _init_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            style.theme_use("clam")
        style.configure("TFrame", background=COLOR_BG)
        style.configure("TLabel", background=COLOR_BG)
        style.configure("Toolbar.TFrame", background="#ffffff")
        style.configure("Tool.TButton", padding=(10, 5))
        style.configure(
            "Treeview",
            rowheight=self._row_height(),
            fieldbackground="#ffffff",
            background="#ffffff",
        )
        style.configure("Treeview.Heading", font=self.bold_font, background=COLOR_HEAD)
        style.map("Treeview", background=[("selected", "#cfe3ff")])
        style.configure("Status.TLabel", background="#ffffff", foreground="#5b6470")
        style.configure("Hint.TLabel", background=COLOR_BG, foreground="#8a929c")

    def _row_height(self) -> int:
        try:
            return max(24, tkfont.nametofont("TkDefaultFont").metrics("linespace") + 8)
        except tk.TclError:
            return 26

    # ------------------------------------------------------------------ 菜单
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="导入文件…（Excel / CSV）", accelerator="Ctrl+O", command=self.import_files)
        m_file.add_command(label="粘贴表格导入…", command=self.import_paste)
        m_file.add_separator()
        m_file.add_command(label="导出当前结果…", accelerator="Ctrl+E", command=self.export_results)
        m_file.add_command(label="备份数据库…", command=self.backup_db)
        m_file.add_separator()
        m_file.add_command(label="退出", command=self.on_close)
        menubar.add_cascade(label="文件", menu=m_file)

        m_proj = tk.Menu(menubar, tearoff=0)
        m_proj.add_command(label="新建项目…", accelerator="Ctrl+N", command=self.new_project)
        m_proj.add_command(label="重命名项目…", command=self.rename_project)
        m_proj.add_command(label="复制项目…", command=self.duplicate_project)
        m_proj.add_command(label="管理数据表…", command=self.manage_datasets)
        m_proj.add_separator()
        m_proj.add_command(label="删除项目…", command=self.delete_project)
        menubar.add_cascade(label="项目", menu=m_proj)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="使用说明", command=self.show_help)
        m_help.add_command(label="数据库位置", command=self.show_db_info)
        m_help.add_command(label="打开数据文件夹", command=self.open_data_folder)
        m_help.add_separator()
        m_help.add_command(label=f"关于 {APP_NAME}", command=self.show_about)
        menubar.add_cascade(label="帮助", menu=m_help)

        self.config(menu=menubar)

    # ------------------------------------------------------------------ 布局
    def _build_ui(self) -> None:
        self._build_toolbar()

        outer = ttk.PanedWindow(self, orient="horizontal")
        outer.pack(fill="both", expand=True, padx=8, pady=(6, 2))
        outer.add(self._build_sidebar(outer), weight=0)
        outer.add(self._build_main(outer), weight=1)

        status = tk.Frame(self, bg="#ffffff", height=26)
        status.pack(fill="x", side="bottom")
        self.status = ttk.Label(status, text="就绪", style="Status.TLabel", anchor="w")
        self.status.pack(side="left", padx=10, pady=3)
        self.db_label = ttk.Label(status, text="", style="Status.TLabel", anchor="e")
        self.db_label.pack(side="right", padx=10, pady=3)
        self._refresh_db_label()

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, style="Toolbar.TFrame")
        bar.pack(fill="x", side="top")
        inner = tk.Frame(bar, bg="#ffffff")
        inner.pack(fill="x", padx=10, pady=8)

        def btn(text, cmd):
            b = ttk.Button(inner, text=text, command=cmd, style="Tool.TButton")
            b.pack(side="left", padx=(0, 8))
            return b

        btn("＋ 新建项目", self.new_project)
        btn("⬆ 导入文件", self.import_files)
        btn("📋 粘贴导入", self.import_paste)
        ttk.Separator(inner, orient="vertical").pack(side="left", fill="y", padx=4)
        btn("⬇ 导出结果", self.export_results)
        tk.Label(
            inner,
            text="把项目清单导进来，以后只搜一个词就能定位到那一行",
            bg="#ffffff",
            fg="#98a1ab",
            font=self.small_font,
        ).pack(side="right", padx=6)

    def _build_sidebar(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, width=250)
        head = tk.Frame(frame, bg=COLOR_BG)
        head.pack(fill="x", pady=(0, 4))
        tk.Label(head, text="我的项目", bg=COLOR_BG, font=self.title_font).pack(side="left")
        tk.Label(head, text="（右键更多）", bg=COLOR_BG, fg="#98a1ab", font=self.small_font).pack(
            side="right"
        )

        self.proj_filter = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=self.proj_filter)
        entry.pack(fill="x", pady=(0, 4))
        self.proj_filter.trace_add("write", lambda *_: self.reload_projects())

        wrap = tk.Frame(frame, bg=COLOR_BG)
        wrap.pack(fill="both", expand=True)
        self.proj_tree = ttk.Treeview(wrap, columns=("n",), show="tree headings", selectmode="browse")
        self.proj_tree.heading("#0", text="项目")
        self.proj_tree.heading("n", text="行数")
        self.proj_tree.column("#0", width=150, anchor="w")
        self.proj_tree.column("n", width=60, anchor="e", stretch=False)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.proj_tree.yview)
        self.proj_tree.configure(yscrollcommand=sb.set)
        self.proj_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.proj_tree.bind("<<TreeviewSelect>>", lambda e: self.on_project_select())
        self.proj_tree.bind("<Button-3>", self._project_menu)

        self._proj_menu = tk.Menu(self, tearoff=0)
        self._proj_menu.add_command(label="新建项目…", command=self.new_project)
        self._proj_menu.add_command(label="重命名…", command=self.rename_project)
        self._proj_menu.add_command(label="复制项目…", command=self.duplicate_project)
        self._proj_menu.add_command(label="管理数据表…", command=self.manage_datasets)
        self._proj_menu.add_separator()
        self._proj_menu.add_command(label="导出该项目…", command=lambda: self.export_results(whole=True))
        self._proj_menu.add_command(label="删除项目…", command=self.delete_project)

        self.proj_summary = ttk.Label(frame, text="", style="Hint.TLabel", wraplength=240)
        self.proj_summary.pack(fill="x", pady=(4, 6))
        return frame

    def _build_main(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent)

        # 搜索区
        box = tk.Frame(frame, bg="#ffffff", highlightbackground="#d9dee5", highlightthickness=1)
        box.pack(fill="x", pady=(0, 6))
        inner = tk.Frame(box, bg="#ffffff")
        inner.pack(fill="x", padx=10, pady=8)

        tk.Label(inner, text="🔍", bg="#ffffff", font=(self.ui_font[0], 14)).pack(side="left")
        self.q = tk.StringVar()
        self.search_entry = tk.Entry(
            inner, textvariable=self.q, font=self.search_font, relief="flat", bg="#ffffff"
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.search_entry.bind("<Return>", lambda e: self.run_search())
        self.search_entry.bind("<Escape>", lambda e: self.clear_search())
        tk.Button(
            inner, text="清空", command=self.clear_search, relief="flat",
            bg="#ffffff", fg="#6b7280", activebackground="#f0f2f5", cursor="hand2",
        ).pack(side="right", padx=(6, 0))

        scope = tk.Frame(box, bg="#ffffff")
        scope.pack(fill="x", padx=10, pady=(0, 8))
        self.scope = tk.StringVar(value="当前项目")
        ttk.Combobox(
            scope, textvariable=self.scope, values=["当前项目", "全部项目"],
            state="readonly", width=9,
        ).pack(side="left")
        self._syncing_scope = False
        self.scope.trace_add("write", self._on_scope_change)
        self.hint = tk.Label(
            scope,
            text="多个词用空格分隔（同时满足）；用 | 表示任一，如 RNB2|RNB3；忽略大小写与 - . 等符号",
            bg="#ffffff", fg="#98a1ab", font=self.small_font,
        )
        self.hint.pack(side="left", padx=10)
        self.count_label = tk.Label(scope, text="", bg="#ffffff", fg="#2563eb", font=self.bold_font)
        self.count_label.pack(side="right")

        vpane = ttk.PanedWindow(frame, orient="vertical")
        vpane.pack(fill="both", expand=True)

        # 结果表
        table_wrap = tk.Frame(vpane, bg="#ffffff")
        self.tree = ttk.Treeview(table_wrap, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)
        self.tree.tag_configure("odd", background="#fbfcfe")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_result_select())
        self.tree.bind("<Double-1>", lambda e: self.open_detail())
        self.tree.bind("<Control-c>", lambda e: self.copy_row())
        vpane.add(table_wrap, weight=3)

        # 详情
        detail_wrap = tk.Frame(vpane, bg="#ffffff")
        head = tk.Frame(detail_wrap, bg="#ffffff")
        head.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(head, text="详情", bg="#ffffff", font=self.title_font).pack(side="left")
        for text, cmd in (
            ("复制该行", self.copy_row),
            ("复制值", self.copy_value),
            ("放大查看", self.open_detail),
        ):
            b = tk.Button(
                head, text=text, command=cmd, relief="flat", bg="#f0f2f5",
                activebackground="#e2e6ec", cursor="hand2", padx=8, pady=2,
            )
            b.pack(side="right", padx=4)

        self.detail = tk.Text(
            detail_wrap, height=8, wrap="word", relief="flat", bg="#ffffff",
            font=self.ui_font, padx=8, pady=6, cursor="arrow",
        )
        self.detail.pack(fill="both", expand=True, padx=6, pady=(2, 8))
        self.detail.tag_configure("k", foreground="#6b7280", font=self.bold_font)
        self.detail.tag_configure("v", foreground="#111827")
        self.detail.tag_configure("hl", background=COLOR_HIT, foreground="#92400e")
        self.detail.tag_configure("meta", foreground="#2563eb", font=self.small_font)
        self.detail.tag_configure("sep", foreground="#d1d5db")
        self.detail.configure(state="disabled")
        vpane.add(detail_wrap, weight=2)
        return frame

    def _bind_keys(self) -> None:
        self.bind("<Control-f>", lambda e: self.focus_search())
        self.bind("<Control-n>", lambda e: self.new_project())
        self.bind("<Control-o>", lambda e: self.import_files())
        self.bind("<Control-e>", lambda e: self.export_results())
        self.bind("<F5>", lambda e: self.run_search())

    def focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    def _first_run_hint(self) -> None:
        """空库时提示可以先加载示例数据，降低上手门槛。"""
        if self.store.list_projects():
            return
        if messagebox.askyesno(
            "第一次使用",
            "当前还没有任何数据。\n\n"
            "要不要先载入一份内置示例（端子清单 + 传感器清单）试试效果？\n"
            "选「否」可以直接导入你自己的 Excel / CSV。",
        ):
            from . import samples

            n_proj, n_rows = samples.load(self.store)
            first = self.store.list_projects()[0]
            self.reload_projects(keep=first.id)
            self.q.set("rnbs5.5-4")
            self.run_search()
            self.status.configure(text=f"已载入 {n_proj} 个示例项目 · {n_rows} 条记录")

    # ------------------------------------------------------------------ 项目
    def current_project_id(self) -> int | None:
        sel = self.proj_tree.selection()
        if not sel:
            return None
        iid = sel[0]
        if iid == "all":
            return None
        try:
            return int(iid)
        except ValueError:
            return None

    def reload_projects(self, keep: int | None = None) -> None:
        keep = keep if keep is not None else self.current_project_id()
        keyword = self.proj_filter.get().strip()
        projects = self.store.list_projects(keyword)
        self._project_names = {p.id: p.name for p in projects}

        self.proj_tree.delete(*self.proj_tree.get_children())
        total_rows = sum(p.nrows for p in projects)
        self.proj_tree.insert("", "end", iid="all", text="🗂 全部项目", values=(total_rows,))
        for p in projects:
            label = p.name
            if p.ndatasets > 1:
                label += f"（{p.ndatasets} 表）"
            self.proj_tree.insert("", "end", iid=str(p.id), text=label, values=(p.nrows,))

        target = str(keep) if keep is not None and self.proj_tree.exists(str(keep)) else "all"
        self.proj_tree.selection_set(target)
        self.proj_tree.see(target)
        self.proj_summary.configure(text=f"共 {len(projects)} 个项目 · {total_rows} 条记录")
        self.on_project_select()

    def on_project_select(self) -> None:
        pid = self.current_project_id()
        # 选中「全部项目」时，检索范围也必须跟着切到全部，否则看起来搜索无结果
        want = "全部项目" if pid is None else "当前项目"
        if self.scope.get() != want:
            self._syncing_scope = True
            self.scope.set(want)
            self._syncing_scope = False
        self._reload_schema(pid)
        self._schedule_search(0)
        self._refresh_db_label()

    def _project_menu(self, event) -> None:
        iid = self.proj_tree.identify_row(event.y)
        if iid:
            self.proj_tree.selection_set(iid)
        try:
            self._proj_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._proj_menu.grab_release()

    def new_project(self) -> None:
        name = self._ask_text("新建项目", "项目名称：", default="新项目")
        if not name:
            return
        pid = self.store.create_project(name)
        self.reload_projects(keep=pid)
        self.status.configure(text=f"已创建项目「{name}」，可以导入数据了")
        if messagebox.askyesno("导入数据", "项目已创建。现在导入 Excel / CSV 文件吗？"):
            self.import_files()

    def rename_project(self) -> None:
        pid = self.current_project_id()
        if pid is None:
            messagebox.showinfo("提示", "请先在左侧选中一个具体项目。")
            return
        info = self.store.get_project(pid)
        if not info:
            return
        name = self._ask_text("重命名项目", "项目名称：", default=info.name)
        if not name:
            return
        self.store.rename_project(pid, name)
        self.reload_projects(keep=pid)

    def duplicate_project(self) -> None:
        pid = self.current_project_id()
        if pid is None:
            messagebox.showinfo("提示", "请先选中一个具体项目。")
            return
        info = self.store.get_project(pid)
        name = self._ask_text("复制项目", "新项目名称：", default=f"{info.name} 副本" if info else "副本")
        if not name:
            return
        new_id = self.store.duplicate_project(pid, name)
        self.reload_projects(keep=new_id)
        self.status.configure(text=f"已复制为「{name}」")

    def delete_project(self) -> None:
        pid = self.current_project_id()
        if pid is None:
            messagebox.showinfo("提示", "请先选中一个具体项目（不能删除「全部项目」）。")
            return
        info = self.store.get_project(pid)
        if not info:
            return
        if not messagebox.askyesno(
            "删除项目", f"确定删除「{info.name}」吗？\n将同时删除其中 {info.nrows} 条记录。"
        ):
            return
        self.store.delete_project(pid)
        self.reload_projects(keep=None)
        self.status.configure(text="项目已删除")

    def manage_datasets(self) -> None:
        pid = self.current_project_id()
        if pid is None:
            messagebox.showinfo("提示", "请先选中一个具体项目。")
            return
        DatasetManager(self, pid)

    # ------------------------------------------------------------------ 导入
    def import_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择要导入的表格文件",
            filetypes=[
                ("表格文件", "*.xlsx *.xlsm *.csv *.tsv *.txt"),
                ("Excel", "*.xlsx *.xlsm"),
                ("CSV / 文本", "*.csv *.tsv *.txt"),
                ("所有文件", "*.*"),
            ],
        )
        if not paths:
            return

        pid = self.current_project_id()
        created = False
        if pid is None:
            from pathlib import Path

            pid = self.store.create_project(Path(paths[0]).stem)
            created = True

        added: list[str] = []
        failed: list[str] = []
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            for path in paths:
                try:
                    tables = importer.to_tables(path)
                    if not tables:
                        failed.append(f"{path}（没读到数据）")
                        continue
                    for i, table in enumerate(tables):
                        name = table.source or f"数据{i + 1}"
                        self.store.add_dataset(pid, name, table.columns, table.rows, table.source)
                        added.append(f"{name} · {len(table.rows)} 行")
                except Exception as exc:  # noqa: BLE001 - 单个文件失败不影响其它
                    failed.append(f"{path}（{exc}）")
        finally:
            self.config(cursor="")
        self.store.invalidate()
        self.reload_projects(keep=pid)
        msg = "导入完成：" + "、".join(added) if added else "没有导入任何数据"
        if failed:
            msg += "\n\n失败：\n" + "\n".join(failed)
        self.status.configure(text=msg.split("\n")[0])
        if created and added:
            messagebox.showinfo("导入完成", f"已新建项目并导入：\n" + "\n".join(added))

    def import_paste(self) -> None:
        PasteDialog(self)

    def do_paste_import(self, text: str, name: str, has_header: bool) -> None:
        try:
            table = importer.paste_to_table(text, name, has_header=has_header)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导入失败", str(exc))
            return
        if not table.columns:
            messagebox.showwarning("没有数据", "粘贴的内容没解析出数据行。")
            return
        pid = self.current_project_id()
        if pid is None:
            pid = self.store.create_project(name or "粘贴导入")
        self.store.add_dataset(pid, name or "粘贴数据", table.columns, table.rows, table.source)
        self.store.invalidate()
        self.reload_projects(keep=pid)
        self.status.configure(
            text=f"已导入「{name or '粘贴数据'}」：{len(table.rows)} 行 × {len(table.columns)} 列"
        )

    # ------------------------------------------------------------------ 检索
    def _reload_schema(self, pid: int | None) -> None:
        if pid is not None:
            datasets = self.store.list_datasets(pid)
        else:
            datasets = [d for p in self.store.list_projects() for d in self.store.list_datasets(p.id)]
        self._ds_columns = {d.id: d.columns for d in datasets}
        self._ds_project = {d.id: d.project_id for d in datasets}

    def _display_columns(self, hits: list[Hit] | None = None) -> list[str]:
        """展示哪些列：优先只取「有命中的数据表」的列，避免混入无关列。"""
        pools: list[list[str]] = []
        if hits:
            used: list[int] = []
            for h in hits:
                if h.record.dataset_id not in used:
                    used.append(h.record.dataset_id)
                if len(used) >= 20:
                    break
            pools = [self._ds_columns.get(d, []) for d in used]
        if not any(pools):
            pools = list(self._ds_columns.values())
        cols: list[str] = []
        seen: set[str] = set()
        for ds_cols in pools:
            for c in ds_cols:
                if c not in seen:
                    seen.add(c)
                    cols.append(c)
        return cols

    def _on_scope_change(self, *_) -> None:
        if getattr(self, "_syncing_scope", False):
            return
        self._syncing_scope = True
        try:
            if self.scope.get() == "全部项目":
                # 侧栏也跟着高亮「全部项目」，避免选中态和搜索范围不一致
                if self.proj_tree.exists("all") and self.proj_tree.selection() != ("all",):
                    self.proj_tree.selection_set("all")
                self._reload_schema(None)
            else:
                self._reload_schema(self.current_project_id())
        finally:
            self._syncing_scope = False
        self._schedule_search(0)

    def _schedule_search(self, delay: int = 160) -> None:
        if self._search_job is not None:
            self.after_cancel(self._search_job)
        self._search_job = self.after(delay, self.run_search)

    def run_search(self) -> None:
        self._search_job = None
        pid = self.current_project_id()
        scope_all = self.scope.get() == "全部项目"
        query = self.q.get().strip()

        self.store.conn.commit()
        records = self.store.load_records(None if scope_all else pid)
        self.records = records

        if query:
            self.hits = search(records, query)
        else:
            self.hits = [Hit(r, 0, []) for r in records]

        self._render_results()
        count_text = f"命中 {len(self.hits)} 条" if query else f"共 {len(self.hits)} 条"
        self.count_label.configure(text=count_text)
        scope_text = "全部项目" if scope_all else "当前项目"
        extra = "" if query else " · 直接输入关键词开始搜索"
        self.status.configure(
            text=f"范围：{scope_text} · 记录 {len(records)} 条 · {count_text}{extra}"
        )

    def _render_results(self) -> None:
        cols = self._display_columns(self.hits)
        show_meta = self.scope.get() == "全部项目"
        head = (["项目", "数据表"] if show_meta else []) + cols
        widths = self._measure_columns(head, cols, show_meta)
        if head != self._tree_cols:
            self._tree_cols = head
            self.tree.configure(columns=[f"c{i}" for i in range(len(head))])
            for i, name in enumerate(head):
                self.tree.heading(f"c{i}", text=name)
                self.tree.column(
                    f"c{i}", width=widths[i], minwidth=56, stretch=False, anchor="w"
                )
        else:
            for i, width in enumerate(widths):
                self.tree.column(f"c{i}", width=width)

        self.tree.delete(*self.tree.get_children())
        self._hit_by_iid.clear()
        shown = self.hits[:MAX_SHOWN]
        for idx, hit in enumerate(shown):
            rec = hit.record
            values: list[str] = []
            if show_meta:
                values += [rec.project, rec.dataset]
            mapping = {
                c: (rec.values[i] if i < len(rec.values) else "")
                for i, c in enumerate(self._ds_columns.get(rec.dataset_id, []))
            }
            values += [mapping.get(c, "") for c in cols]
            iid = self.tree.insert("", "end", values=values, tags=("odd",) if idx % 2 else ())
            self._hit_by_iid[iid] = hit

        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])
            self.tree.see(children[0])
            self._render_detail(shown[0])
        else:
            self._render_detail(None)
        if len(self.hits) > MAX_SHOWN:
            self.status.configure(text=f"命中 {len(self.hits)} 条，结果表仅显示前 {MAX_SHOWN} 条")

    def _measure_columns(
        self, head: list[str], cols: list[str], show_meta: bool
    ) -> list[int]:
        """按表头 + 前若干行的实际内容估算列宽，中文按双宽计算。"""
        samples: list[list[str]] = [[] for _ in head]
        for hit in self.hits[:120]:
            rec = hit.record
            mapping = {
                c: (rec.values[i] if i < len(rec.values) else "")
                for i, c in enumerate(self._ds_columns.get(rec.dataset_id, []))
            }
            offset = 0
            if show_meta:
                samples[0].append(rec.project)
                samples[1].append(rec.dataset)
                offset = 2
            for j, c in enumerate(cols):
                samples[j + offset].append(mapping.get(c, ""))
        widths: list[int] = []
        for i, name in enumerate(head):
            widest = max([text_width(name)] + [text_width(v) for v in samples[i]])
            widths.append(max(70, min(320, widest * 8 + 30)))
        return widths

    def current_hit(self) -> Hit | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return self._hit_by_iid.get(sel[0])

    def on_result_select(self) -> None:
        hit = self.current_hit()
        if hit:
            self._render_detail(hit)

    def _render_detail(self, hit: Hit | None) -> None:
        d = self.detail
        d.configure(state="normal")
        d.delete("1.0", "end")
        if hit is None:
            d.insert("end", "选择上方任意一行，这里会显示完整信息。", "sep")
            d.configure(state="disabled")
            return

        rec = hit.record
        terms = hit.terms
        d.insert("end", "项目 ", "k")
        d.insert("end", f"{rec.project or '—'}    ")
        d.insert("end", "数据表 ", "k")
        d.insert("end", f"{rec.dataset or '—'}    ")
        d.insert("end", "第 ", "k")
        d.insert("end", f"{rec.row_no} ")
        d.insert("end", "行\n", "k")
        d.insert("end", "─" * 64 + "\n", "sep")

        col_names = self._ds_columns.get(
            rec.dataset_id, [f"列{i + 1}" for i in range(len(rec.values))]
        )
        pad = max((text_width(c) for c in col_names), default=8)
        for i, name in enumerate(col_names):
            value = rec.values[i] if i < len(rec.values) else ""
            d.insert("end", name)
            d.insert("end", " " * max(1, pad - text_width(name) + 2))
            d.insert("end", "│ ", "sep")
            self._insert_highlighted(value, terms)
            d.insert("end", "\n")
        d.configure(state="disabled")

    def _insert_highlighted(self, value: str, terms: list[str]) -> None:
        marks = spans(value, terms)
        if not marks:
            self.detail.insert("end", value, "v")
            return
        pos = 0
        for a, b in marks:
            if a > pos:
                self.detail.insert("end", value[pos:a], "v")
            self.detail.insert("end", value[a:b], "hl")
            pos = b
        if pos < len(value):
            self.detail.insert("end", value[pos:], "v")

    def clear_search(self) -> None:
        self.q.set("")
        self.search_entry.focus_set()
        self._schedule_search(0)

    # ------------------------------------------------------------------ 导出/复制
    def _rows_for_export(self, records: list[Record], cols: list[str], show_meta: bool) -> list[list[str]]:
        out: list[list[str]] = []
        for rec in records:
            mapping = {
                c: (rec.values[i] if i < len(rec.values) else "")
                for i, c in enumerate(self._ds_columns.get(rec.dataset_id, []))
            }
            row = ([rec.project, rec.dataset] if show_meta else [])
            out.append(row + [mapping.get(c, "") for c in cols])
        return out

    def export_results(self, whole: bool = False) -> None:
        show_meta = self.scope.get() == "全部项目"
        if whole:
            pid = self.current_project_id()
            if pid is None:
                messagebox.showinfo("提示", "请先选中一个项目。")
                return
            ds_ids = set(self.store._all_project_datasets(pid))
            records = [r for r in self.store.load_records(pid) if r.dataset_id in ds_ids]
            if not records:
                messagebox.showinfo("提示", "这个项目还没有数据。")
                return
            cols = self._display_columns([Hit(r, 0, []) for r in records[:50]])
            default = f"{self._project_names.get(pid, '项目')}.csv"
            show_meta = True
        else:
            if not self.hits:
                messagebox.showinfo("提示", "当前没有可导出的结果。")
                return
            records = [h.record for h in self.hits]
            cols = self._display_columns(self.hits)
            default = "检索结果.csv"

        path = filedialog.asksaveasfilename(
            title="导出",
            defaultextension=".csv",
            initialfile=default,
            filetypes=[("CSV（Excel 可直接打开）", "*.csv"), ("Excel 工作簿", "*.xlsx")],
        )
        if not path:
            return
        head = (["项目", "数据表"] if show_meta else []) + cols
        try:
            out = export_rows(path, head, self._rows_for_export(records, cols, show_meta))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导出失败", str(exc))
            return
        self.status.configure(text=f"已导出 {len(records)} 条到 {out.name}")
        if messagebox.askyesno(
            "导出完成", f"已导出 {len(records)} 条到：\n{out}\n\n现在打开所在文件夹吗？"
        ):
            import os

            os.startfile(str(out.parent))  # noqa: S606

    def copy_row(self) -> None:
        hit = self.current_hit()
        if not hit:
            return
        self.clipboard_clear()
        self.clipboard_append("\t".join(hit.record.values))
        self.status.configure(text="已复制整行（制表符分隔，可直接粘进 Excel）")

    def copy_value(self) -> None:
        hit = self.current_hit()
        if not hit:
            return
        idx = self._focused_column_index()
        vals = hit.record.values
        value = vals[idx] if idx is not None and 0 <= idx < len(vals) else "\t".join(vals)
        self.clipboard_clear()
        self.clipboard_append(value)
        self.status.configure(text=f"已复制：{value[:60]}")

    def _focused_column_index(self) -> int | None:
        x = self.winfo_pointerx() - self.tree.winfo_rootx()
        col = self.tree.identify_column(x)
        if not col or not col.startswith("#"):
            return None
        try:
            i = int(col[1:]) - 1
        except ValueError:
            return None
        offset = 2 if self.scope.get() == "全部项目" else 0
        return i - offset

    # ------------------------------------------------------------------ 其它对话框
    def open_detail(self) -> None:
        hit = self.current_hit()
        if not hit:
            return
        DetailDialog(self, hit, self._ds_columns.get(hit.record.dataset_id, []))

    def backup_db(self) -> None:
        path = filedialog.asksaveasfilename(
            title="备份数据库",
            defaultextension=".db",
            initialfile="record-finder-backup.db",
            filetypes=[("数据库文件", "*.db")],
        )
        if not path:
            return
        try:
            self.store.backup(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("备份失败", str(exc))
            return
        self.status.configure(text=f"已备份到 {path}")

    def open_data_folder(self) -> None:
        import os

        folder = self.store.db_path.parent
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(folder))  # noqa: S606
        except OSError as exc:
            messagebox.showerror("打不开", f"{folder}\n\n{exc}")

    def show_db_info(self) -> None:
        st = self.store.stats()
        size = st["size"] / 1024 / 1024
        messagebox.showinfo(
            "数据库位置",
            f"文件：{self.store.db_path}\n\n"
            f"项目 {st['projects']} 个 · 数据表 {st['datasets']} 张 · 记录 {st['rows']} 条\n"
            f"占用 {size:.2f} MB\n\n"
            "把这个 .db 文件拷走就能带走全部数据。\n"
            "（菜单「帮助 → 打开数据文件夹」可以直接定位）",
        )

    def show_help(self) -> None:
        messagebox.showinfo(
            "使用说明",
            "① 点「导入文件」选 Excel/CSV，或「粘贴导入」直接把网页上的表格粘进来。\n"
            "② 左边选中项目，在搜索框输入任意一个词（型号、编码、名称…）。\n"
            "③ 结果表里点一行，下方详情会高亮命中的部分。\n\n"
            "搜索技巧：\n"
            "· 忽略大小写和 - . / 等符号，rnbs5.5-4 能搜到 RNBS5.5-4-90D\n"
            "· 空格分隔多个词表示同时包含，如「裸端子 5.5」\n"
            "· 用 | 表示任一，如 RNB2|RNB3\n"
            "· 范围可切到「全部项目」跨项目搜索\n\n"
            "快捷键：Ctrl+F 搜索，Ctrl+O 导入，Ctrl+E 导出，F5 重新搜索，双击结果看大图。",
        )

    def show_about(self) -> None:
        messagebox.showinfo(
            f"关于 {APP_NAME}",
            f"{APP_NAME} {__version__}\n\n"
            "把项目/物料清单导进来，搜一个词就定位到那一行。\n"
            "数据存在本地 SQLite 文件里，不联网、不上传。",
        )

    def _ask_text(self, title: str, prompt: str, default: str = "") -> str:
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg="#ffffff")
        dlg.transient(self)
        dlg.resizable(False, False)
        tk.Label(dlg, text=prompt, bg="#ffffff", font=self.ui_font).pack(
            anchor="w", padx=16, pady=(16, 6)
        )
        var = tk.StringVar(value=default)
        entry = ttk.Entry(dlg, textvariable=var, width=40, font=self.ui_font)
        entry.pack(padx=16, fill="x")
        entry.focus_set()
        entry.select_range(0, "end")
        result: dict[str, str] = {}

        def ok(_=None):
            result["v"] = var.get().strip()
            dlg.destroy()

        row = tk.Frame(dlg, bg="#ffffff")
        row.pack(fill="x", padx=16, pady=14)
        ttk.Button(row, text="确定", command=ok).pack(side="right", padx=(6, 0))
        ttk.Button(row, text="取消", command=dlg.destroy).pack(side="right")
        entry.bind("<Return>", ok)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        self._center(dlg)
        self.wait_window(dlg)
        return result.get("v", "")

    def _center(self, win: tk.Toplevel) -> None:
        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _refresh_db_label(self) -> None:
        try:
            st = self.store.stats()
            self.db_label.configure(
                text=f"本地数据库 {st['projects']} 项目 / {st['rows']} 条 · {self.store.db_path.name}"
            )
        except Exception:  # noqa: BLE001
            pass

    def on_close(self) -> None:
        try:
            self.store.close()
        finally:
            self.destroy()


class DetailDialog(tk.Toplevel):
    """放大查看某一行，便于看长文本。"""

    def __init__(self, master: App, hit: Hit, columns: list[str]) -> None:
        super().__init__(master)
        self.title(f"详情 · {hit.record.dataset} 第 {hit.record.row_no} 行")
        self.geometry("760x460")
        self.configure(bg="#ffffff")
        rec = hit.record

        bar = tk.Frame(self, bg="#ffffff")
        bar.pack(fill="x", padx=12, pady=8)
        tk.Label(
            bar, text=f"{rec.project} / {rec.dataset}", bg="#ffffff", font=master.title_font
        ).pack(side="left")

        def copy_all():
            self.clipboard_clear()
            self.clipboard_append(
                "\n".join(
                    f"{c}：{rec.values[i] if i < len(rec.values) else ''}"
                    for i, c in enumerate(columns)
                )
            )

        tk.Button(
            bar, text="复制全部", command=copy_all, relief="flat", bg="#f0f2f5",
            cursor="hand2", padx=10, pady=2,
        ).pack(side="right")

        text = tk.Text(self, wrap="word", font=master.ui_font, relief="flat", padx=12, pady=8)
        text.pack(fill="both", expand=True)
        text.tag_configure("k", foreground="#6b7280", font=master.bold_font)
        text.tag_configure("v", foreground="#111827")
        text.tag_configure("hl", background=COLOR_HIT, foreground="#92400e")

        for i, name in enumerate(columns):
            value = rec.values[i] if i < len(rec.values) else ""
            text.insert("end", f"{name}\n", "k")
            marks = spans(value, hit.terms)
            pos = 0
            if marks:
                for a, b in marks:
                    if a > pos:
                        text.insert("end", value[pos:a], "v")
                    text.insert("end", value[a:b], "hl")
                    pos = b
                if pos < len(value):
                    text.insert("end", value[pos:], "v")
            else:
                text.insert("end", value or "（空）", "v")
            text.insert("end", "\n\n")
        text.configure(state="disabled")
        master._center(self)


class PasteDialog(tk.Toplevel):
    """粘贴表格：直接从网页/Excel 复制一块区域贴进来。"""

    def __init__(self, master: App) -> None:
        super().__init__(master)
        self.app = master
        self.title("粘贴表格导入")
        self.geometry("780x540")
        self.configure(bg="#ffffff")
        self.transient(master)

        tk.Label(
            self,
            text="从网页或 Excel 里框选复制，然后按 Ctrl+V 粘贴到下方（会自动识别表头和列）",
            bg="#ffffff", font=master.small_font, fg="#6b7280",
        ).pack(anchor="w", padx=14, pady=(12, 6))

        row = tk.Frame(self, bg="#ffffff")
        row.pack(fill="x", padx=14)
        tk.Label(row, text="数据表名：", bg="#ffffff", font=master.ui_font).pack(side="left")
        self.name = tk.StringVar(value="粘贴数据")
        ttk.Entry(row, textvariable=self.name, width=30).pack(side="left")
        self.header_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="首行是表头", variable=self.header_var).pack(side="left", padx=12)

        wrap = tk.Frame(self, bg="#ffffff")
        wrap.pack(fill="both", expand=True, padx=14, pady=8)
        self.text = tk.Text(wrap, wrap="none", font=master.ui_font, relief="solid", borderwidth=1)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.text.yview)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        btns = tk.Frame(self, bg="#ffffff")
        btns.pack(fill="x", padx=14, pady=(0, 12))
        self.preview = tk.Label(btns, text="", bg="#ffffff", fg="#2563eb", font=master.bold_font)
        self.preview.pack(side="left")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="导入", command=self.do_import).pack(side="right")

        self.text.bind("<<Modified>>", self._on_modify)
        self.text.focus_set()
        master._center(self)

    def _on_modify(self, _=None) -> None:
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        raw = self.text.get("1.0", "end")
        if not raw.strip():
            self.preview.configure(text="")
            return
        try:
            table = importer.paste_to_table(raw, "", has_header=self.header_var.get())
        except Exception:  # noqa: BLE001
            self.preview.configure(text="解析失败")
            return
        self.preview.configure(
            text=f"将导入 {len(table.rows)} 行 × {len(table.columns)} 列："
                 + " / ".join(table.columns[:6])
        )

    def do_import(self) -> None:
        raw = self.text.get("1.0", "end")
        if not raw.strip():
            messagebox.showwarning("没有内容", "请先粘贴表格内容。", parent=self)
            return
        self.destroy()
        self.app.do_paste_import(raw, self.name.get().strip(), self.header_var.get())


class DatasetManager(tk.Toplevel):
    """管理一个项目下的数据表。"""

    def __init__(self, master: App, project_id: int) -> None:
        super().__init__(master)
        self.app = master
        self.pid = project_id
        info = master.store.get_project(project_id)
        self.title(f"数据表管理 · {info.name if info else ''}")
        self.geometry("700x430")
        self.configure(bg="#ffffff")
        self.transient(master)

        wrap = tk.Frame(self, bg="#ffffff")
        wrap.pack(fill="both", expand=True, padx=12, pady=12)
        self.tree = ttk.Treeview(
            wrap, columns=("name", "cols", "rows", "src"), show="headings", selectmode="browse"
        )
        for key, text, width in (
            ("name", "数据表", 190), ("cols", "列", 60), ("rows", "行数", 80), ("src", "来源", 300),
        ):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="w")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btns = tk.Frame(self, bg="#ffffff")
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="关闭", command=self._close).pack(side="right")
        ttk.Button(btns, text="删除数据表", command=self._delete).pack(side="right", padx=6)
        ttk.Button(btns, text="重命名", command=self._rename).pack(side="right")
        ttk.Button(btns, text="导出这张表", command=self._export).pack(side="left")

        self.fill()
        master._center(self)

    def fill(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for d in self.app.store.list_datasets(self.pid):
            self.tree.insert(
                "", "end", iid=str(d.id),
                values=(d.name, len(d.columns), d.nrows, d.source),
            )

    def _selected(self) -> int | None:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _rename(self) -> None:
        ds = self._selected()
        if ds is None:
            return
        old = self.app.store.dataset_name(ds)
        name = self.app._ask_text("重命名数据表", "名称：", default=old)
        if not name:
            return
        self.app.store.rename_dataset(ds, name)
        self.fill()
        self.app.store.invalidate()
        self.app.reload_projects(keep=self.pid)

    def _delete(self) -> None:
        ds = self._selected()
        if ds is None:
            return
        name = self.app.store.dataset_name(ds)
        if not messagebox.askyesno("删除", f"确定删除数据表「{name}」及其数据吗？", parent=self):
            return
        self.app.store.delete_dataset(ds)
        self.fill()
        self.app.store.invalidate()
        self.app.reload_projects(keep=self.pid)

    def _export(self) -> None:
        ds = self._selected()
        if ds is None:
            return
        cols = self.app.store.dataset_columns(ds)
        rows = self.app.store.dataset_rows(ds)
        path = filedialog.asksaveasfilename(
            title="导出数据表", defaultextension=".csv",
            initialfile=f"{self.app.store.dataset_name(ds)}.csv",
            filetypes=[("CSV", "*.csv"), ("Excel 工作簿", "*.xlsx")],
            parent=self,
        )
        if not path:
            return
        recs = [Record(self.app.store.dataset_name(ds), ds, i + 1, r) for i, r in enumerate(rows)]
        export(path, recs, cols)
        self.app.status.configure(text=f"已导出 {len(rows)} 行到 {path}")

    def _close(self) -> None:
        self.app.store.invalidate()
        self.app.reload_projects(keep=self.pid)
        self.destroy()


def run(db_path: str | None = None) -> int:
    dpi_aware()
    app = App(db_path)
    app.mainloop()
    return 0
