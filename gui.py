"""
gui.py  --  MODULE 3 of 4  (Tkinter, standard library only)
===========================================================

The visual front-end. Wires together:
    maze.py          -> the editable Maze model      (module 2)
    search_engine.py -> the step-by-step algorithms  (module 1)

Layout
    left   : algorithm picker (Uninformed / Informed), heuristic, maze tools,
             presets, size, undo/redo, save/open
    centre : the maze canvas + play / step / reset / instant-solve + speed
    right  : live metrics (compute time, expanded, frontier, memory, path),
             animated memory chart, complexity notes, step-by-step log

Mouse     left-drag paints the selected tool, right-drag erases,
          drag the green S / red G to move start and goal.
Keys      Space play/pause - N or Right step - R reset - Ctrl/Cmd+Z / Y undo/redo

Run:      python main.py      (or  python gui.py)
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk
from typing import Dict, List, Optional, Set, Tuple

from maze import Maze, Tool, line_cells
from search_engine import ALGORITHMS, CATEGORIES, HEURISTICS, Stats, Step, create

Cell = Tuple[int, int]

# --------------------------------------------------------------------------- #
#  Palette
# --------------------------------------------------------------------------- #
C = dict(
    bg="#0c0f16", panel="#121722", card="#171d2b", card2="#1f2638", line="#2b344b",
    text="#e8ebf4", muted="#8a93ab", accent="#6c8cff", accent_hi="#8aa4ff",
    cyan="#22d3ee", floor="#161b28", wall="#4a5478", start="#34d399", goal="#fb7185",
    frontier="#fbbf24", current="#ffffff", path="#4ade80", trail="#fb923c",
    ok="#34d399", warn="#fbbf24", bad="#fb7185", violet="#7c5cff",
)


def _rgb(h: str) -> Tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def lerp(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    a, b = _rgb(c1), _rgb(c2)
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def fmt_time(sec: float) -> str:
    us = sec * 1e6
    if us < 1000:
        return f"{us:,.0f} µs"
    if us < 1e6:
        return f"{us / 1000:,.2f} ms"
    return f"{us / 1e6:,.2f} s"


# --------------------------------------------------------------------------- #
#  Application
# --------------------------------------------------------------------------- #
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self._enable_hidpi()
        self.title("Maze Pathfinder Lab  -  informed & uninformed search")
        w = min(1480, self.winfo_screenwidth() - 40)
        h = min(900, self.winfo_screenheight() - 80)
        self.geometry(f"{w}x{h}")
        self.minsize(1240, 760)
        self.configure(bg=C["bg"])

        # model ---------------------------------------------------------------
        self.maze = Maze(15, 25)
        self.maze.add_listener(self._on_maze_changed)

        # search / animation state --------------------------------------------
        self.algo = None
        self.gen = None
        self.running = False
        self.finished = False
        self.after_id: Optional[str] = None
        self.path_after: Optional[str] = None
        self.explored: Dict[Cell, int] = {}
        self.frontier: Set[Cell] = set()
        self.current: Optional[Cell] = None
        self.path_set: Set[Cell] = set()
        self.trail_set: Set[Cell] = set()
        self.dirty: Set[Cell] = set()
        self.mem_hist: List[int] = []
        self.fr_hist: List[int] = []

        # editing state ---------------------------------------------------------
        self.tool = Tool.WALL
        self._painting = False
        self._drag_tool = Tool.WALL
        self._last: Optional[Cell] = None

        # canvas geometry ---------------------------------------------------------
        self.rects: List[List[int]] = []
        self.cs, self.ox, self.oy = 20, 0, 0
        self._cfg_job: Optional[str] = None

        self._build_fonts()
        self._build_styles()
        self._build_ui()
        self._bind_keys()

        self._set_category(next(iter(CATEGORIES)))
        self._sync_controls()
        self._show_stats(None)
        self._set_status("READY", "idle")
        self._log("Welcome! Pick an algorithm, shape the maze, press Play or Step.", "dim")

    # ================================================================ setup ==
    @staticmethod
    def _enable_hidpi() -> None:
        if sys.platform.startswith("win"):
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass

    def _build_fonts(self) -> None:
        fams = set(tkfont.families(self))
        pick = lambda names, d: next((n for n in names if n in fams), d)
        ui = pick(["Inter", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Cantarell",
                   "Noto Sans", "DejaVu Sans"], "TkDefaultFont")
        mono = pick(["JetBrains Mono", "Cascadia Code", "Menlo", "Consolas", "SF Mono",
                     "DejaVu Sans Mono"], "TkFixedFont")
        self.f_ui = (ui, 10)
        self.f_bold = (ui, 10, "bold")
        self.f_small = (ui, 8, "bold")
        self.f_big = (mono, 17, "bold")
        self.f_mid = (mono, 12, "bold")
        self.f_title = (ui, 16, "bold")
        self.f_mono = (mono, 9)
        self.f_head = (ui, 9, "bold")

    def _build_styles(self) -> None:
        st = ttk.Style(self)
        st.theme_use("clam")
        self.option_add("*TCombobox*Listbox.background", C["card2"])
        self.option_add("*TCombobox*Listbox.foreground", C["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.option_add("*TCombobox*Listbox.font", self.f_ui)
        st.configure(".", background=C["card"], foreground=C["text"], font=self.f_ui,
                     bordercolor=C["line"], focuscolor=C["card"])
        st.configure("TFrame", background=C["card"])
        st.configure("TLabel", background=C["card"], foreground=C["text"])

        def button(name, bg, fg, active, pad=(10, 7)):
            st.configure(name, background=bg, foreground=fg, bordercolor=bg,
                         lightcolor=bg, darkcolor=bg, padding=pad, relief="flat",
                         focuscolor=bg, font=self.f_bold)
            st.map(name, background=[("disabled", C["card"]), ("pressed", active), ("active", active)],
                   foreground=[("disabled", C["line"])])

        button("TButton", C["card2"], C["text"], C["line"])
        button("Accent.TButton", C["accent"], "#ffffff", C["accent_hi"], (14, 8))
        button("Seg.TButton", C["card2"], C["muted"], C["line"], (8, 7))
        button("SegOn.TButton", C["accent"], "#ffffff", C["accent_hi"], (8, 7))
        button("Tool.TButton", C["card2"], C["text"], C["line"], (4, 8))
        button("ToolOn.TButton", C["violet"], "#ffffff", "#9079ff", (4, 8))

        st.configure("TCombobox", fieldbackground=C["card2"], background=C["card2"],
                     foreground=C["text"], arrowcolor=C["muted"], bordercolor=C["line"],
                     lightcolor=C["card2"], darkcolor=C["card2"], padding=6,
                     selectbackground=C["card2"], selectforeground=C["text"])
        st.map("TCombobox", fieldbackground=[("readonly", C["card2"]), ("disabled", C["card"])],
               foreground=[("readonly", C["text"]), ("disabled", C["line"])],
               arrowcolor=[("disabled", C["line"])])
        st.configure("TSpinbox", fieldbackground=C["card2"], background=C["card2"],
                     foreground=C["text"], arrowcolor=C["muted"], bordercolor=C["line"],
                     lightcolor=C["card2"], darkcolor=C["card2"], padding=4)
        st.configure("Horizontal.TScale", background=C["accent"], troughcolor=C["card2"],
                     bordercolor=C["card"], lightcolor=C["accent"], darkcolor=C["accent"])
        st.configure("Vertical.TScrollbar", background=C["card2"], troughcolor=C["card"],
                     bordercolor=C["card"], arrowcolor=C["muted"], lightcolor=C["card2"],
                     darkcolor=C["card2"])

    # ================================================================== UI ==
    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_sidebar()
        self._build_center()
        self._build_right()

    def _section(self, parent: tk.Misc, title: str, fill_y: bool = False) -> tk.Frame:
        outer = tk.Frame(parent, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
        outer.pack(fill="both" if fill_y else "x", expand=fill_y, pady=(0, 10))
        tk.Label(outer, text=title, bg=C["card"], fg=C["muted"], font=self.f_head
                 ).pack(anchor="w", padx=12, pady=(10, 4))
        inner = tk.Frame(outer, bg=C["card"])
        inner.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        return inner

    def _btn(self, parent, text, cmd, style="TButton", **kw) -> ttk.Button:
        return ttk.Button(parent, text=text, command=cmd, style=style, takefocus=False, **kw)

    # ----------------------------------------------------------------- header
    def _build_header(self) -> None:
        h = tk.Frame(self, bg=C["bg"])
        h.grid(row=0, column=0, columnspan=3, sticky="ew", padx=16, pady=(12, 6))
        tk.Label(h, text="◈", bg=C["bg"], fg=C["accent"], font=(self.f_title[0], 20, "bold")
                 ).pack(side="left", padx=(0, 8))
        box = tk.Frame(h, bg=C["bg"])
        box.pack(side="left")
        tk.Label(box, text="Maze Pathfinder Lab", bg=C["bg"], fg=C["text"], font=self.f_title).pack(anchor="w")
        tk.Label(box, text="informed & uninformed search, one step at a time",
                 bg=C["bg"], fg=C["muted"], font=self.f_ui).pack(anchor="w")
        self.status_pill = tk.Label(h, text="READY", font=self.f_head, padx=14, pady=5)
        self.status_pill.pack(side="right")
        self.status_msg = tk.Label(h, text="", bg=C["bg"], fg=C["muted"], font=self.f_ui)
        self.status_msg.pack(side="right", padx=14)

    # ---------------------------------------------------------------- sidebar
    def _build_sidebar(self) -> None:
        sb = tk.Frame(self, bg=C["bg"], width=290)
        sb.grid(row=1, column=0, sticky="ns", padx=(16, 8), pady=(0, 12))
        sb.pack_propagate(False)

        # -- algorithm ------------------------------------------------------
        a = self._section(sb, "ALGORITHM")
        seg = tk.Frame(a, bg=C["card"])
        seg.pack(fill="x")
        seg.grid_columnconfigure((0, 1), weight=1, uniform="seg")
        self.seg_btns: Dict[str, ttk.Button] = {}
        for i, cat in enumerate(CATEGORIES):
            b = self._btn(seg, cat.replace(" Search", ""), lambda c=cat: self._set_category(c), "Seg.TButton")
            b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 3, 3 if i == 0 else 0))
            self.seg_btns[cat] = b
        tk.Label(a, text="Method", bg=C["card"], fg=C["muted"], font=self.f_ui).pack(anchor="w", pady=(10, 2))
        self.algo_var = tk.StringVar()
        self.algo_combo = ttk.Combobox(a, textvariable=self.algo_var, state="readonly", takefocus=False)
        self.algo_combo.pack(fill="x")
        self.algo_combo.bind("<<ComboboxSelected>>", lambda e: self._on_algo_change())
        tk.Label(a, text="Heuristic h(n)", bg=C["card"], fg=C["muted"], font=self.f_ui).pack(anchor="w", pady=(10, 2))
        self.heur_var = tk.StringVar(value="Manhattan")
        self.heur_combo = ttk.Combobox(a, textvariable=self.heur_var, state="readonly",
                                       values=list(HEURISTICS), takefocus=False)
        self.heur_combo.pack(fill="x")
        self.heur_combo.bind("<<ComboboxSelected>>", lambda e: self._cancel_search())
        self._btn(a, "📊  Compare all algorithms", self._open_compare).pack(fill="x", pady=(12, 0))

        # -- tools ------------------------------------------------------------
        t = self._section(sb, "MAZE TOOLS")
        grid = tk.Frame(t, bg=C["card"])
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="tool")
        self.tool_btns: Dict[Tool, ttk.Button] = {}
        specs = [(Tool.WALL, "▇ Wall"), (Tool.ERASE, "◌ Erase"), (Tool.WEIGHT, "≈ Mud"),
                 (Tool.START, "● Start"), (Tool.GOAL, "◆ Goal")]
        for i, (tool, label) in enumerate(specs):
            b = self._btn(grid, label, lambda tl=tool: self._set_tool(tl), "Tool.TButton")
            b.grid(row=i // 3, column=i % 3, sticky="ew", padx=2, pady=2)
            self.tool_btns[tool] = b
        wrow = tk.Frame(t, bg=C["card"])
        wrow.pack(fill="x", pady=(10, 0))
        self.weight_var = tk.IntVar(value=5)
        self.weight_lbl = tk.Label(wrow, text="Mud cost  5", bg=C["card"], fg=C["text"], font=self.f_ui)
        self.weight_lbl.pack(side="left")
        ttk.Scale(wrow, from_=2, to=9, variable=self.weight_var, command=self._on_weight, takefocus=False
                  ).pack(side="right", fill="x", expand=True, padx=(12, 0))
        tk.Label(t, text="Left-drag paints · right-drag erases\nDrag S / G to move them",
                 bg=C["card"], fg=C["muted"], font=(self.f_ui[0], 8), justify="left"
                 ).pack(anchor="w", pady=(8, 0))
        self._set_tool(Tool.WALL)

        # -- maze ---------------------------------------------------------------
        m = self._section(sb, "MAZE")
        prow = tk.Frame(m, bg=C["card"])
        prow.pack(fill="x")
        self.preset_var = tk.StringVar(value=Maze.PRESETS[0])
        ttk.Combobox(prow, textvariable=self.preset_var, values=Maze.PRESETS, state="readonly",
                     takefocus=False, width=16).pack(side="left", fill="x", expand=True)
        self._btn(prow, "Load", self._load_preset).pack(side="right", padx=(6, 0))
        srow = tk.Frame(m, bg=C["card"])
        srow.pack(fill="x", pady=(10, 0))
        self.rows_var, self.cols_var = tk.StringVar(), tk.StringVar()
        tk.Label(srow, text="Size", bg=C["card"], fg=C["muted"], font=self.f_ui).pack(side="left")
        ttk.Spinbox(srow, from_=Maze.MIN_SIZE, to=Maze.MAX_ROWS, width=3, textvariable=self.rows_var,
                    takefocus=False).pack(side="left", padx=(8, 4))
        tk.Label(srow, text="×", bg=C["card"], fg=C["muted"], font=self.f_ui).pack(side="left")
        ttk.Spinbox(srow, from_=Maze.MIN_SIZE, to=Maze.MAX_COLS, width=3, textvariable=self.cols_var,
                    takefocus=False).pack(side="left", padx=(4, 8))
        self._btn(srow, "Apply", self._apply_size, width=6).pack(side="right")
        brow = tk.Frame(m, bg=C["card"])
        brow.pack(fill="x", pady=(10, 0))
        brow.grid_columnconfigure(tuple(range(6)), weight=1, uniform="mb")
        self.undo_btn = self._btn(brow, "↶ Undo", self.maze.undo)
        self.redo_btn = self._btn(brow, "↷ Redo", self.maze.redo)
        self.undo_btn.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=2)
        self.redo_btn.grid(row=0, column=2, columnspan=2, sticky="ew", padx=2, pady=2)
        self._btn(brow, "✕ Clear", self.maze.clear).grid(row=0, column=4, columnspan=2, sticky="ew", padx=2, pady=2)
        self._btn(brow, "💾 Save", self._save).grid(row=1, column=0, columnspan=3, sticky="ew", padx=2, pady=2)
        self._btn(brow, "📂 Open", self._open).grid(row=1, column=3, columnspan=3, sticky="ew", padx=2, pady=2)
        self.maze_info = tk.Label(m, text="", bg=C["card"], fg=C["muted"], font=(self.f_ui[0], 8))
        self.maze_info.pack(anchor="w", pady=(8, 0))

    # ----------------------------------------------------------------- centre
    def _build_center(self) -> None:
        ctr = tk.Frame(self, bg=C["bg"])
        ctr.grid(row=1, column=1, sticky="nsew", padx=8, pady=(0, 12))
        ctr.grid_rowconfigure(1, weight=1)
        ctr.grid_columnconfigure(0, weight=1)

        legend = tk.Frame(ctr, bg=C["bg"])
        legend.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for color, name in [(C["start"], "Start"), (C["goal"], "Goal"), (C["wall"], "Wall"),
                            ("#a8672b", "Mud"), (C["frontier"], "Frontier"),
                            (C["violet"], "Explored"), (C["current"], "Current"), (C["path"], "Path")]:
            tk.Label(legend, text="■", fg=color, bg=C["bg"], font=(self.f_ui[0], 11)).pack(side="left")
            tk.Label(legend, text=name, fg=C["muted"], bg=C["bg"], font=(self.f_ui[0], 9)
                     ).pack(side="left", padx=(2, 12))

        wrap = tk.Frame(ctr, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
        wrap.grid(row=1, column=0, sticky="nsew")
        self.canvas = tk.Canvas(wrap, bg=C["panel"], highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Button-1>", lambda e: self._press(e, False))
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        for b in (2, 3):                       # right click (Win/Linux = 3, macOS = 2)
            self.canvas.bind(f"<Button-{b}>", lambda e: self._press(e, True))
            self.canvas.bind(f"<B{b}-Motion>", self._drag)
            self.canvas.bind(f"<ButtonRelease-{b}>", self._release)

        bar = tk.Frame(ctr, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
        bar.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        inner = tk.Frame(bar, bg=C["card"])
        inner.pack(fill="x", padx=12, pady=10)
        self.play_btn = self._btn(inner, "▶  Play", self._toggle_play, "Accent.TButton", width=10)
        self.play_btn.pack(side="left")
        self._btn(inner, "⏭  Step", self._step_once, width=7).pack(side="left", padx=(8, 0))
        self._btn(inner, "⚡ Instant", self._solve_instant, width=8).pack(side="left", padx=(8, 0))
        self._btn(inner, "↺  Reset", self._cancel_search, width=7).pack(side="left", padx=(8, 0))
        self.speed = tk.IntVar(value=40)
        ttk.Scale(inner, from_=1, to=100, variable=self.speed, takefocus=False, length=140
                  ).pack(side="right")
        tk.Label(inner, text="Speed", bg=C["card"], fg=C["muted"], font=self.f_ui).pack(side="right", padx=(0, 10))
        self._build_log(ctr)

    # ------------------------------------------------------------------ right
    def _build_right(self) -> None:
        rp = tk.Frame(self, bg=C["bg"], width=340)
        rp.grid(row=1, column=2, sticky="ns", padx=(8, 16), pady=(0, 12))
        rp.pack_propagate(False)

        # -- live metrics ---------------------------------------------------
        s = self._section(rp, "LIVE METRICS")
        g = tk.Frame(s, bg=C["card"])
        g.pack(fill="x")
        g.grid_columnconfigure((0, 1, 2), weight=1, uniform="stat")
        self.stat: Dict[str, tk.Label] = {}
        self._sub_defaults: Dict[str, str] = {}
        self._stat_card(g, "Compute time", "time", 0, 0, 3, big=True, sub="pure compute time · animation excluded")
        self._stat_card(g, "Expanded", "expanded", 1, 0, sub="nodes popped")
        self._stat_card(g, "Generated", "generated", 1, 1, sub="nodes created")
        self._stat_card(g, "Frontier", "frontier", 1, 2, sub="waiting")
        self._stat_card(g, "Memory", "memory", 2, 0, sub="nodes stored")
        self._stat_card(g, "Path length", "plen", 2, 1, sub="moves")
        self._stat_card(g, "Path cost", "pcost", 2, 2, sub="total weight")

        # -- dynamic space ----------------------------------------------------
        sp = self._section(rp, "SPACE USAGE  ·  LIVE")
        top = tk.Frame(sp, bg=C["card"])
        top.pack(fill="x")
        self.mem_lbl = tk.Label(top, text="0 / 0 nodes", bg=C["card"], fg=C["text"], font=self.f_mono)
        self.mem_lbl.pack(side="left")
        self.mem_pct = tk.Label(top, text="0%", bg=C["card"], fg=C["muted"], font=self.f_mono)
        self.mem_pct.pack(side="right")
        self.membar = tk.Canvas(sp, height=10, bg=C["card2"], highlightthickness=0)
        self.membar.pack(fill="x", pady=(4, 8))
        self.chart = tk.Canvas(sp, height=72, bg=C["card2"], highlightthickness=0)
        self.chart.pack(fill="x")
        lg = tk.Frame(sp, bg=C["card"])
        lg.pack(fill="x", pady=(6, 0))
        tk.Label(lg, text="━ stored nodes", fg=C["cyan"], bg=C["card"], font=(self.f_ui[0], 8)).pack(side="left")
        tk.Label(lg, text="━ frontier", fg=C["frontier"], bg=C["card"], font=(self.f_ui[0], 8)).pack(side="left", padx=10)
        self.chart.bind("<Configure>", lambda e: self._draw_chart())

        # -- complexity ----------------------------------------------------------
        ci = self._section(rp, "COMPLEXITY  ·  THIS ALGORITHM")
        self.info_name = tk.Label(ci, text="", bg=C["card"], fg=C["text"], font=self.f_bold)
        self.info_name.pack(anchor="w")
        self.info_desc = tk.Label(ci, text="", bg=C["card"], fg=C["muted"], font=(self.f_ui[0], 9),
                                  wraplength=290, justify="left")
        self.info_desc.pack(anchor="w", pady=(2, 8))
        self.info_time = self._kv(ci, "Time")
        self.info_space = self._kv(ci, "Space")
        self.info_flags = self._kv(ci, "Properties")

    def _build_log(self, parent: tk.Misc) -> None:
        box = tk.Frame(parent, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
        box.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        tk.Label(box, text="STEP LOG", bg=C["card"], fg=C["muted"], font=self.f_head
                 ).pack(anchor="w", padx=12, pady=(8, 3))
        row = tk.Frame(box, bg=C["card"])
        row.pack(fill="x", padx=12, pady=(0, 10))
        self.log = tk.Text(row, height=6, bg=C["card2"], fg=C["text"], font=self.f_mono, wrap="word",
                           relief="flat", highlightthickness=0, padx=8, pady=6, state="disabled",
                           insertbackground=C["text"], cursor="arrow")
        sb = ttk.Scrollbar(row, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="x", expand=True)
        for tag, col in (("head", C["accent_hi"]), ("note", C["text"]), ("ok", C["ok"]),
                         ("bad", C["bad"]), ("dim", C["muted"])):
            self.log.tag_configure(tag, foreground=col)
        self.log.tag_configure("head", font=(self.f_mono[0], 9, "bold"))

    def _stat_card(self, parent, title, key, row, col, span=1, big=False, sub="") -> None:
        f = tk.Frame(parent, bg=C["card2"], padx=9, pady=5)
        f.grid(row=row, column=col, columnspan=span, sticky="nsew", padx=3, pady=3)
        tk.Label(f, text=title.upper(), bg=C["card2"], fg=C["muted"], font=(self.f_ui[0], 7, "bold")).pack(anchor="w")
        v = tk.Label(f, text="–", bg=C["card2"], fg=C["cyan"] if big else C["text"],
                     font=(self.f_big[0], 20, "bold") if big else self.f_mid)
        v.pack(anchor="w")
        lbl = tk.Label(f, text=sub or " ", bg=C["card2"], fg=C["muted"], font=(self.f_ui[0], 8))
        lbl.pack(anchor="w")
        self.stat[key], self.stat[key + "_sub"] = v, lbl
        self._sub_defaults[key + "_sub"] = sub or " "

    def _kv(self, parent, key) -> tk.Label:
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", pady=1)
        tk.Label(row, text=key, bg=C["card"], fg=C["muted"], font=(self.f_ui[0], 9), width=9, anchor="w").pack(side="left")
        v = tk.Label(row, text="", bg=C["card"], fg=C["text"], font=self.f_mono, anchor="w")
        v.pack(side="left")
        return v

    def _bind_keys(self) -> None:
        def guard(fn):
            def h(e=None):
                if isinstance(self.focus_get(), (ttk.Combobox, ttk.Spinbox, tk.Text)):
                    return
                fn()
            return h
        self.bind_all("<space>", guard(self._toggle_play))
        self.bind_all("<Key-n>", guard(self._step_once))
        self.bind_all("<Right>", guard(self._step_once))
        self.bind_all("<Key-r>", guard(self._cancel_search))
        for mod in ("Control", "Command"):
            try:
                self.bind_all(f"<{mod}-z>", lambda e: self.maze.undo())
                self.bind_all(f"<{mod}-y>", lambda e: self.maze.redo())
                self.bind_all(f"<{mod}-Shift-Z>", lambda e: self.maze.redo())
            except tk.TclError:
                pass

    # ============================================================== selection ==
    def _set_category(self, cat: str) -> None:
        self.category = cat
        for c, b in self.seg_btns.items():
            b.configure(style="SegOn.TButton" if c == cat else "Seg.TButton")
        self._algo_names = {ALGORITHMS[k].name: k for k in CATEGORIES[cat]}
        self.algo_combo.configure(values=list(self._algo_names))
        self.algo_var.set(next(iter(self._algo_names)))
        self._on_algo_change()

    def _on_algo_change(self) -> None:
        self.algo_key = self._algo_names[self.algo_var.get()]
        cls = ALGORITHMS[self.algo_key]
        informed = cls.category == "Informed"
        self.heur_combo.configure(state="readonly" if informed else "disabled")
        self.info_name.config(text=f"{cls.name}  ·  {cls.category}")
        self.info_desc.config(text=cls.description)
        self.info_time.config(text=cls.time_complexity)
        self.info_space.config(text=cls.space_complexity)
        tick = lambda b: "✓" if b else "✗"
        self.info_flags.config(text=f"complete {tick(cls.complete)}   optimal {tick(cls.optimal)}")
        self._cancel_search()

    def _set_tool(self, tool: Tool) -> None:
        self.tool = tool
        for t, b in self.tool_btns.items():
            b.configure(style="ToolOn.TButton" if t == tool else "Tool.TButton")

    def _on_weight(self, _v=None) -> None:
        w = int(round(float(self.weight_var.get())))
        self.weight_lbl.config(text=f"Mud cost  {w}")
        if self.tool != Tool.WEIGHT:
            self._set_tool(Tool.WEIGHT)

    # ================================================================ canvas ==
    def _on_canvas_configure(self, _e) -> None:
        if self._cfg_job:
            self.after_cancel(self._cfg_job)
        self._cfg_job = self.after(60, self._rebuild_canvas)

    def _rebuild_canvas(self) -> None:
        cv = self.canvas
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 60 or H < 60:
            return
        cv.delete("all")
        R, Cn, m = self.maze.rows, self.maze.cols, 16
        self.cs = max(4, int(min((W - 2 * m) / Cn, (H - 2 * m) / R)))
        self.ox, self.oy = (W - self.cs * Cn) // 2, (H - self.cs * R) // 2
        cv.create_rectangle(self.ox - 4, self.oy - 4, self.ox + self.cs * Cn + 4,
                            self.oy + self.cs * R + 4, outline=C["line"], fill=C["bg"])
        cs = self.cs
        self.rects = [[cv.create_rectangle(self.ox + c * cs, self.oy + r * cs,
                                           self.ox + (c + 1) * cs, self.oy + (r + 1) * cs,
                                           fill=C["floor"], outline=C["bg"], width=1)
                       for c in range(Cn)] for r in range(R)]
        self.lbl_s = cv.create_text(0, 0, text="S", fill="#052e1f", font=self.f_bold)
        self.lbl_g = cv.create_text(0, 0, text="G", fill="#4c0519", font=self.f_bold)
        self._paint_all()

    def _place_labels(self) -> None:
        if not self.rects:
            return
        size = max(7, int(self.cs * 0.5))
        for item, (r, c) in ((self.lbl_s, self.maze.start), (self.lbl_g, self.maze.goal)):
            self.canvas.coords(item, self.ox + c * self.cs + self.cs / 2, self.oy + r * self.cs + self.cs / 2)
            self.canvas.itemconfig(item, font=(self.f_ui[0], size, "bold"),
                                   state="normal" if self.cs >= 12 else "hidden")
            self.canvas.tag_raise(item)

    def _cell_color(self, cell: Cell) -> str:
        m = self.maze
        if cell == m.start:
            return C["start"]
        if cell == m.goal:
            return C["goal"]
        if cell in self.path_set:
            return C["path"]
        if cell in self.trail_set:
            return C["trail"]
        if cell == self.current:
            return C["current"]
        v = m.grid[cell[0]][cell[1]]
        if v == 0:
            return C["wall"]
        if cell in self.explored:
            t = self.explored[cell] / max(1.0, m.open_count * 0.75)
            return lerp("#5b3fd6", "#18c3d6", t)
        if cell in self.frontier:
            return C["frontier"]
        if v > 1:
            return lerp("#3b3220", "#c0702a", (v - 2) / 7)
        return C["floor"]

    def _paint_cell(self, cell: Cell) -> None:
        r, c = cell
        if self.rects and 0 <= r < len(self.rects) and 0 <= c < len(self.rects[0]):
            self.canvas.itemconfig(self.rects[r][c], fill=self._cell_color(cell))

    def _paint_all(self) -> None:
        if not self.rects:
            return
        for r in range(self.maze.rows):
            for c in range(self.maze.cols):
                self._paint_cell((r, c))
        self._place_labels()

    def _flush(self) -> None:
        for cell in self.dirty:
            self._paint_cell(cell)
        self.dirty.clear()

    # ----------------------------------------------------------------- mouse
    def _cell_at(self, e) -> Optional[Cell]:
        r, c = (e.y - self.oy) // self.cs, (e.x - self.ox) // self.cs
        return (r, c) if self.maze.in_bounds((r, c)) and e.x >= self.ox and e.y >= self.oy else None

    def _press(self, e, erase: bool) -> None:
        cell = self._cell_at(e)
        if cell is None:
            return
        if self.gen is not None or self.explored or self.path_set or self.trail_set:
            self._cancel_search()
        self.maze.begin_edit()
        self._painting = True
        self._drag_tool = (Tool.START if cell == self.maze.start else
                           Tool.GOAL if cell == self.maze.goal else
                           Tool.ERASE if erase else self.tool)
        self._last = cell
        self._paint_stroke(cell, cell)

    def _drag(self, e) -> None:
        if not self._painting:
            return
        cell = self._cell_at(e)
        if cell is None or cell == self._last:
            return
        self._paint_stroke(self._last, cell)
        self._last = cell

    def _paint_stroke(self, a: Cell, b: Cell) -> None:
        before = (self.maze.start, self.maze.goal)
        self.maze.paint_line(self._drag_tool, a, b, self.weight_var.get())
        for cell in (*line_cells(a, b), *before, self.maze.start, self.maze.goal):
            self._paint_cell(cell)
        self._place_labels()

    def _release(self, _e) -> None:
        if self._painting:
            self._painting = False
            self.maze.end_edit()
            self._sync_controls()

    # ============================================================ maze events ==
    def _on_maze_changed(self) -> None:
        if self._painting:
            return
        self._cancel_search(refresh=False)
        if self.rects and (len(self.rects) != self.maze.rows or len(self.rects[0]) != self.maze.cols):
            self._rebuild_canvas()
        else:
            self._paint_all()
        self._sync_controls()

    def _sync_controls(self) -> None:
        m = self.maze
        self.rows_var.set(str(m.rows))
        self.cols_var.set(str(m.cols))
        self.maze_info.config(text=f"{m.rows} × {m.cols}  ·  {m.wall_count} walls  ·  {m.weighted_count} mud")
        self.undo_btn.state(["!disabled" if m.can_undo else "disabled"])
        self.redo_btn.state(["!disabled" if m.can_redo else "disabled"])

    def _load_preset(self) -> None:
        self.maze.load_preset(self.preset_var.get())
        self._set_message(f"Loaded “{self.preset_var.get()}”")

    def _apply_size(self) -> None:
        try:
            self.maze.resize(int(self.rows_var.get()), int(self.cols_var.get()))
        except ValueError:
            self._sync_controls()

    def _save(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Maze", "*.json")])
        if path:
            self.maze.save(path)
            self._set_message("Maze saved")

    def _open(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Maze", "*.json")])
        if path:
            try:
                self.maze.replace_with(Maze.load(path))
                self._set_message("Maze loaded")
            except Exception as exc:
                messagebox.showerror("Could not open maze", str(exc))

    def _open_compare(self) -> None:
        try:
            from compare import open_compare_window          # module 4
        except ImportError:
            messagebox.showinfo("Compare", "Module 4 (compare.py) has not been added yet.")
            return
        open_compare_window(self, self.maze, self.heur_var.get())

    # ============================================================== running ==
    def _speed_params(self) -> Tuple[int, int]:
        s = self.speed.get()
        if s <= 70:
            return max(1, int(400 * ((70 - s) / 70) ** 2)), 1
        return 1, 1 + int(s - 70) * 2

    def _init_search(self) -> None:
        self._cancel_search(refresh=False)
        problem = self.maze.to_problem(self.heur_var.get())
        self.algo = create(self.algo_key, problem)
        self.gen = self.algo.run()
        self.finished = False
        self._paint_all()
        self._clear_log()
        extra = f" · {self.heur_var.get()} heuristic" if ALGORITHMS[self.algo_key].category == "Informed" else ""
        self._log(f"▶ {ALGORITHMS[self.algo_key].name}{extra}", "head")

    def _advance(self) -> Optional[Step]:
        try:
            step = next(self.gen)
        except (StopIteration, TypeError):
            self.finished = True
            return None
        self._apply_step(step)
        if step.status != "running":
            self.finished = True
        return step

    def _apply_step(self, st: Step) -> None:
        if self.current is not None:
            self.dirty.add(self.current)
        self.current = st.current
        if st.current is not None:
            self.frontier.discard(st.current)
            self.explored.setdefault(st.current, len(self.explored))
            self.dirty.add(st.current)
        for n in st.added:
            if n not in self.explored:
                self.frontier.add(n)
                self.dirty.add(n)
        for n in st.dropped:                      # after "added": net effect wins
            self.frontier.discard(n)
            self.dirty.add(n)
        self.mem_hist.append(st.stats.stored_nodes)
        self.fr_hist.append(st.stats.frontier_size)

    def _toggle_play(self) -> None:
        if self.running:
            self._pause()
            return
        if self.gen is None or self.finished:
            self._init_search()
        self.running = True
        self._set_status("RUNNING", "run")
        self._update_play_btn()
        self._tick()

    def _pause(self) -> None:
        self.running = False
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        if not self.finished:
            self._set_status("PAUSED", "warn")
        self._update_play_btn()

    def _tick(self) -> None:
        if not self.running:
            return
        delay, per_tick = self._speed_params()
        last = None
        for _ in range(per_tick):
            step = self._advance()
            if step is None:
                break
            last = step
            if self.finished:
                break
        self._flush()
        if last is not None:
            self._after_step(last)
        if self.finished:
            self.running = False
            self._update_play_btn()
        else:
            self.after_id = self.after(delay, self._tick)

    def _step_once(self) -> None:
        if self.running:
            self._pause()
        if self.gen is None or self.finished:
            self._init_search()
        step = self._advance()
        self._flush()
        if step is not None:
            self._after_step(step)
            if not self.finished:
                self._set_status("PAUSED", "warn")
        self._update_play_btn()

    def _solve_instant(self) -> None:
        if self.running:
            self._pause()
        self._init_search()
        last = None
        while not self.finished:
            step = self._advance()
            if step is None:
                break
            last = step
        self.dirty.clear()
        if last is not None:
            self._after_step(last, instant=True)
        self._paint_all()
        self._update_play_btn()

    def _after_step(self, st: Step, instant: bool = False) -> None:
        self._show_stats(st.stats)
        self._draw_chart()
        self._log(f"#{st.stats.steps:<4} {st.note}", "note" if st.status == "running" else
                  "ok" if st.status == "found" else "bad")
        if st.status != "running":
            self._finish(st, instant)

    def _finish(self, st: Step, instant: bool) -> None:
        self.running = False
        self.dirty.add(self.current) if self.current else None
        self.current = None
        s = st.stats
        if st.status == "found":
            self._set_status("PATH FOUND", "ok")
            self._set_message(f"length {s.path_length} · cost {s.path_cost:g} · {fmt_time(s.time_s)}")
            self._log(f"✓ Path found: {s.path_length} moves, cost {s.path_cost:g}", "ok")
            if instant:
                self.path_set = set(st.path)
            else:
                self._animate_path(st.path, 0)
        else:
            stuck = self.algo_key == "hill"
            self._set_status("STUCK" if stuck else "NO PATH", "bad")
            self._set_message("local minimum - no neighbour is closer to the goal" if stuck
                              else "the goal cannot be reached")
            self._log("✗ " + ("Stuck in a local minimum" if stuck else "No path exists"), "bad")
            if st.path:
                self.trail_set = set(st.path)
        self._flush()

    def _animate_path(self, path: List[Cell], i: int) -> None:
        if self.gen is None:                      # reset while animating
            return
        stride = max(1, len(path) // 70)
        for cell in path[i:i + stride]:
            self.path_set.add(cell)
            self._paint_cell(cell)
        if i + stride < len(path):
            self.path_after = self.after(14, self._animate_path, path, i + stride)

    def _cancel_search(self, refresh: bool = True) -> None:
        self.running = False
        for attr in ("after_id", "path_after"):
            job = getattr(self, attr)
            if job:
                self.after_cancel(job)
                setattr(self, attr, None)
        self.gen = self.algo = None
        self.finished = False
        self.explored.clear(); self.frontier.clear(); self.dirty.clear()
        self.path_set.clear(); self.trail_set.clear()
        self.current = None
        self.mem_hist.clear(); self.fr_hist.clear()
        self._show_stats(None)
        self._draw_chart()
        self._set_status("READY", "idle")
        self._set_message("")
        self._update_play_btn()
        if refresh:
            self._paint_all()

    # ========================================================== info panels ==
    def _show_stats(self, s: Optional[Stats]) -> None:
        st = self.stat
        if s is None:
            for k, w in st.items():
                w.config(text=self._sub_defaults.get(k, " ") if k.endswith("_sub") else "–")
            self.mem_lbl.config(text=f"0 / {self.maze.open_count} nodes")
            self.mem_pct.config(text="0%")
            self.membar.delete("all")
            return
        st["time"].config(text=fmt_time(s.time_s))
        st["expanded"].config(text=f"{s.expanded:,}")
        st["generated"].config(text=f"{s.generated:,}")
        st["frontier"].config(text=f"{s.frontier_size:,}")
        st["frontier_sub"].config(text=f"peak {s.peak_frontier:,}")
        st["memory"].config(text=f"{s.stored_nodes:,}")
        st["memory_sub"].config(text=f"peak {s.peak_stored:,}")
        done = s.status == "found"
        st["plen"].config(text=f"{s.path_length}" if done else "…")
        st["pcost"].config(text=f"{s.path_cost:g}" if done else "…")
        total = max(1, self.maze.open_count)
        pct = s.stored_nodes / total
        self.mem_lbl.config(text=f"{s.stored_nodes:,} / {total:,} nodes")
        self.mem_pct.config(text=f"peak {s.peak_stored / total:.0%}")
        w, h = self.membar.winfo_width(), 10
        self.membar.delete("all")
        self.membar.create_rectangle(0, 0, w * min(1, pct), h, width=0,
                                     fill=lerp(C["cyan"], C["violet"], pct))
        self.membar.create_line(w * min(1, s.peak_stored / total), 0, w * min(1, s.peak_stored / total), h,
                                fill="#ffffff", width=2)

    def _draw_chart(self) -> None:
        cv = self.chart
        W, H = cv.winfo_width(), cv.winfo_height()
        cv.delete("all")
        if W < 20:
            return
        for i in range(1, 4):
            cv.create_line(0, H * i / 4, W, H * i / 4, fill=C["line"])
        n = len(self.mem_hist)
        if n < 2:
            cv.create_text(W / 2, H / 2, text="memory over time appears here", fill=C["muted"], font=(self.f_ui[0], 8))
            return
        top = max(max(self.mem_hist), 1)
        stride = max(1, n // 280)
        idx = list(range(0, n, stride))
        if idx[-1] != n - 1:
            idx.append(n - 1)
        pad = 6

        def line(data, color):
            pts = []
            for i in idx:
                pts += [pad + (W - 2 * pad) * i / (n - 1), H - pad - (H - 2 * pad) * data[i] / top]
            cv.create_line(*pts, fill=color, width=2, joinstyle="round")

        line(self.fr_hist, C["frontier"])
        line(self.mem_hist, C["cyan"])
        cv.create_text(W - 6, 8, text=f"max {top:,}", fill=C["muted"], anchor="e", font=(self.f_ui[0], 8))

    def _update_play_btn(self) -> None:
        self.play_btn.config(text="⏸  Pause" if self.running else
                             "↻  Replay" if self.finished else "▶  Play")

    def _set_status(self, text: str, kind: str) -> None:
        bg, fg = {"idle": (C["card2"], C["muted"]), "run": (C["accent"], "#ffffff"),
                  "warn": (C["warn"], "#2a1d00"), "ok": (C["ok"], "#042f1f"),
                  "bad": (C["bad"], "#4c0519")}[kind]
        self.status_pill.config(text=text, bg=bg, fg=fg)

    def _set_message(self, text: str) -> None:
        self.status_msg.config(text=text)

    def _clear_log(self) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _log(self, text: str, tag: str = "note") -> None:
        self.log.config(state="normal")
        self.log.insert("end", text + "\n", tag)
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 300:
            self.log.delete("1.0", f"{lines - 300}.0")
        self.log.see("end")
        self.log.config(state="disabled")


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
