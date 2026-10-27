"""
compare.py  --  MODULE 4 of 4  (Tkinter, standard library only)
===============================================================

The "Algorithm Showdown" window, opened by the  "Compare all algorithms"
button in the main GUI.  It runs EVERY registered algorithm on the maze you are
currently looking at, then shows

    * a sortable results table (click any column heading)
    * four bar charts: compute time, nodes expanded, peak memory, path cost
      (winners get a gold outline and a star)
    * auto-written takeaways ("A* matched the optimal cost with 38% fewer
      expansions than UCS ...")
    * CSV export

It reads ALGORITHMS from search_engine.py, so any algorithm you add there shows
up here automatically.  Edit the maze in the main window, press "Re-run" here.

Entry point used by gui.py:   open_compare_window(parent, maze, heuristic)
"""
from __future__ import annotations

import csv
import statistics
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk
from typing import Callable, List, Optional

from gui import C, fmt_time
from search_engine import ALGORITHMS, HEURISTICS, run_to_completion

SHORT = {"bfs": "BFS", "dfs": "DFS", "ucs": "UCS", "greedy": "Greedy",
         "astar": "A*", "aostar": "AO*", "hill": "Hill Climb"}
CAT_COLOR = {"Uninformed": C["cyan"], "Informed": C["violet"]}


@dataclass
class Row:
    key: str
    name: str
    short: str
    category: str
    status: str
    time_s: float
    expanded: int
    generated: int
    peak_stored: int
    peak_frontier: int
    path_len: int
    path_cost: float

    @property
    def ok(self) -> bool:
        return self.status == "found"


# --------------------------------------------------------------------------- #
class CompareWindow(tk.Toplevel):
    COLUMNS = [  # id, heading, width, anchor
        ("algo", "Algorithm", 190, "w"), ("cat", "Type", 90, "w"), ("result", "Result", 100, "w"),
        ("time", "Compute time", 110, "e"), ("exp", "Expanded", 85, "e"), ("gen", "Generated", 90, "e"),
        ("mem", "Peak memory", 100, "e"), ("len", "Path len", 75, "e"), ("cost", "Path cost", 80, "e"),
        ("delta", "vs optimal", 85, "e"),
    ]

    def __init__(self, parent, maze, heuristic: str = "Manhattan") -> None:
        super().__init__(parent)
        self.parent, self.maze = parent, maze
        self.title("Algorithm Showdown")
        self.configure(bg=C["bg"])
        w = min(1240, self.winfo_screenwidth() - 40)
        h = min(860, self.winfo_screenheight() - 80)
        self.geometry(f"{w}x{h}")
        self.minsize(1040, 680)
        self.transient(parent)

        self.f_ui = getattr(parent, "f_ui", ("TkDefaultFont", 10))
        self.f_bold = getattr(parent, "f_bold", (self.f_ui[0], 10, "bold"))
        self.f_head = getattr(parent, "f_head", (self.f_ui[0], 9, "bold"))
        self.f_mono = getattr(parent, "f_mono", ("TkFixedFont", 9))
        self.f_title = getattr(parent, "f_title", (self.f_ui[0], 16, "bold"))

        self.rows: List[Row] = []
        self.best_cost: Optional[float] = None
        self._busy = False
        self._sort_col, self._sort_rev = None, False
        self.heur_var = tk.StringVar(value=heuristic)
        self.runs_var = tk.StringVar(value="3")

        self._styles()
        self._build()
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(150, self.run)

    # ------------------------------------------------------------------ UI --
    def _styles(self) -> None:
        st = ttk.Style(self)
        st.configure("Treeview", background=C["card2"], fieldbackground=C["card2"], foreground=C["text"],
                     rowheight=29, borderwidth=0, font=self.f_ui)
        st.configure("Treeview.Heading", background=C["card"], foreground=C["muted"], relief="flat",
                     font=self.f_head, padding=(8, 7), borderwidth=0)
        st.map("Treeview.Heading", background=[("active", C["line"])])
        st.map("Treeview", background=[("selected", C["accent"])], foreground=[("selected", "#ffffff")])
        st.configure("Cmp.Horizontal.TProgressbar", troughcolor=C["card2"], background=C["accent"],
                     bordercolor=C["bg"], lightcolor=C["accent"], darkcolor=C["accent"], thickness=6)

    def _card(self, parent: tk.Misc, title: str = "") -> tk.Frame:
        outer = tk.Frame(parent, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
        if title:
            tk.Label(outer, text=title, bg=C["card"], fg=C["muted"], font=self.f_head
                     ).pack(anchor="w", padx=12, pady=(9, 3))
        return outer

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # header ---------------------------------------------------------------
        head = tk.Frame(self, bg=C["bg"])
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 4))
        tk.Label(head, text="⚔", bg=C["bg"], fg=C["accent"], font=(self.f_title[0], 20, "bold")
                 ).pack(side="left", padx=(0, 10))
        box = tk.Frame(head, bg=C["bg"])
        box.pack(side="left")
        tk.Label(box, text="Algorithm Showdown", bg=C["bg"], fg=C["text"], font=self.f_title).pack(anchor="w")
        self.maze_lbl = tk.Label(box, text="", bg=C["bg"], fg=C["muted"], font=self.f_ui)
        self.maze_lbl.pack(anchor="w")

        ctl = tk.Frame(head, bg=C["bg"])
        ctl.pack(side="right")
        self.run_btn = ttk.Button(ctl, text="↻  Re-run", style="Accent.TButton", takefocus=False, command=self.run)
        self.run_btn.pack(side="right", padx=(10, 0))
        ttk.Button(ctl, text="Export CSV", takefocus=False, command=self._export).pack(side="right", padx=(10, 0))
        ttk.Spinbox(ctl, values=(1, 3, 5, 10), width=3, textvariable=self.runs_var, takefocus=False
                    ).pack(side="right")
        tk.Label(ctl, text="timing runs", bg=C["bg"], fg=C["muted"], font=self.f_ui).pack(side="right", padx=(14, 6))
        ttk.Combobox(ctl, textvariable=self.heur_var, values=list(HEURISTICS), state="readonly",
                     width=11, takefocus=False).pack(side="right")
        tk.Label(ctl, text="heuristic", bg=C["bg"], fg=C["muted"], font=self.f_ui).pack(side="right", padx=(0, 6))

        prog = tk.Frame(self, bg=C["bg"])
        prog.grid(row=1, column=0, sticky="ew", padx=18)
        self.progress = ttk.Progressbar(prog, style="Cmp.Horizontal.TProgressbar", mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.status_lbl = tk.Label(prog, text="", bg=C["bg"], fg=C["muted"], font=self.f_ui, width=26, anchor="e")
        self.status_lbl.pack(side="right")

        body = tk.Frame(self, bg=C["bg"])
        body.grid(row=2, column=0, sticky="nsew", padx=18, pady=(8, 14))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(2, weight=1)

        # table -----------------------------------------------------------------
        tcard = self._card(body, "RESULTS  ·  click a heading to sort")
        tcard.grid(row=0, column=0, sticky="ew")
        tw = tk.Frame(tcard, bg=C["card"])
        tw.pack(fill="x", padx=12, pady=(0, 12))
        self.tree = ttk.Treeview(tw, columns=[c[0] for c in self.COLUMNS], show="headings",
                                 height=len(ALGORITHMS), selectmode="browse")
        for cid, text, width, anchor in self.COLUMNS:
            self.tree.heading(cid, text=text, anchor=anchor, command=lambda c=cid: self._sort(c))
            self.tree.column(cid, width=width, anchor=anchor, stretch=True)
        self.tree.tag_configure("fail", foreground=C["bad"])
        self.tree.tag_configure("best", foreground=C["ok"])
        self.tree.pack(fill="x")

        # takeaways ------------------------------------------------------------------
        self.take_card = self._card(body, "TAKEAWAYS")
        self.take_card.grid(row=1, column=0, sticky="ew", pady=10)
        self.take_box = tk.Frame(self.take_card, bg=C["card"])
        self.take_box.pack(fill="x", padx=12, pady=(0, 10))

        # charts ---------------------------------------------------------------------
        ccard = self._card(body)
        ccard.grid(row=2, column=0, sticky="nsew")
        legend = tk.Frame(ccard, bg=C["card"])
        legend.pack(fill="x", padx=12, pady=(9, 0))
        tk.Label(legend, text="HEAD TO HEAD", bg=C["card"], fg=C["muted"], font=self.f_head).pack(side="left")
        for txt, col in (("★ winner (lower is better)", C["frontier"]), ("Informed", C["violet"]),
                         ("Uninformed", C["cyan"])):
            tk.Label(legend, text=txt if txt.startswith("★") else f"■ {txt}", bg=C["card"], fg=col,
                     font=(self.f_ui[0], 9)).pack(side="right", padx=(12, 0))
        grid = tk.Frame(ccard, bg=C["card"])
        grid.pack(fill="both", expand=True, padx=8, pady=8)
        self.charts = []
        specs = [("Compute time", lambda r: r.time_s, fmt_time),
                 ("Nodes expanded", lambda r: r.expanded, lambda v: f"{v:,.0f}"),
                 ("Peak memory (nodes)", lambda r: r.peak_stored, lambda v: f"{v:,.0f}"),
                 ("Path cost", lambda r: r.path_cost if r.ok else None, lambda v: f"{v:g}")]
        for i, spec in enumerate(specs):
            grid.grid_columnconfigure(i, weight=1, uniform="ch")
            cv = tk.Canvas(grid, bg=C["card2"], highlightthickness=0, height=200)
            cv.grid(row=0, column=i, sticky="nsew", padx=4)
            cv.bind("<Configure>", lambda e: self._draw_charts())
            self.charts.append((cv, *spec))
        grid.grid_rowconfigure(0, weight=1)

    # ------------------------------------------------------------- running --
    def run(self) -> None:
        if self._busy:
            return
        try:
            runs = max(1, min(25, int(self.runs_var.get())))
        except ValueError:
            runs = 3
        self._busy, self.rows = True, []
        self.run_btn.state(["disabled"])
        m = self.maze
        self.maze_lbl.config(text=f"{m.rows} × {m.cols} maze  ·  {m.wall_count} walls  ·  "
                                  f"{m.weighted_count} mud  ·  start {m.start} → goal {m.goal}")
        self._problem = m.to_problem(self.heur_var.get())
        self._keys = list(ALGORITHMS)
        self.progress.configure(maximum=len(self._keys), value=0)
        self.after(20, self._run_next, 0, runs)

    def _run_next(self, i: int, runs: int) -> None:
        if not self.winfo_exists():
            return
        if i >= len(self._keys):
            self._finish()
            return
        key = self._keys[i]
        cls = ALGORITHMS[key]
        self.status_lbl.config(text=f"running {SHORT.get(key, cls.name)} …")
        self.update_idletasks()
        times, st = [], None
        for _ in range(runs):
            st, _path = run_to_completion(self._problem, key)
            times.append(st.time_s)
        self.rows.append(Row(key, cls.name, SHORT.get(key, cls.name), cls.category, st.status,
                             statistics.median(times), st.expanded, st.generated, st.peak_stored,
                             st.peak_frontier, st.path_length, st.path_cost))
        self.progress["value"] = i + 1
        self.after(5, self._run_next, i + 1, runs)

    def _finish(self) -> None:
        self._busy = False
        self.run_btn.state(["!disabled"])
        self.status_lbl.config(text="done")
        found = [r.path_cost for r in self.rows if r.ok]
        self.best_cost = min(found) if found else None
        self._refresh()

    def _refresh(self) -> None:
        self._populate()
        self._draw_charts()
        self._takeaways()

    # --------------------------------------------------------------- table --
    def _populate(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for r in self.rows:
            if r.ok:
                result = "✓ found"
                delta = "optimal" if r.path_cost == self.best_cost else \
                    f"+{(r.path_cost / self.best_cost - 1) * 100:.0f}%"
                tag = "best" if r.path_cost == self.best_cost else ""
            else:
                result = "✗ stuck" if r.key == "hill" else "✗ no path"
                delta, tag = "—", "fail"
            self.tree.insert("", "end", iid=r.key, tags=(tag,), values=(
                r.name, r.category, result, fmt_time(r.time_s), f"{r.expanded:,}", f"{r.generated:,}",
                f"{r.peak_stored:,}", r.path_len if r.ok else "—", f"{r.path_cost:g}" if r.ok else "—", delta))

    def _sort(self, col: str) -> None:
        keyfn = {"algo": lambda r: r.name, "cat": lambda r: r.category, "result": lambda r: not r.ok,
                 "time": lambda r: r.time_s, "exp": lambda r: r.expanded, "gen": lambda r: r.generated,
                 "mem": lambda r: r.peak_stored, "len": lambda r: r.path_len if r.ok else 1e18,
                 "cost": lambda r: r.path_cost if r.ok else 1e18,
                 "delta": lambda r: r.path_cost if r.ok else 1e18}[col]
        self._sort_rev = (not self._sort_rev) if self._sort_col == col else False
        self._sort_col = col
        self.rows.sort(key=keyfn, reverse=self._sort_rev)
        self._refresh()

    # -------------------------------------------------------------- charts --
    def _draw_charts(self) -> None:
        for cv, title, getter, fmt in self.charts:
            self._draw_chart(cv, title, getter, fmt)

    def _draw_chart(self, cv: tk.Canvas, title: str, getter: Callable, fmt: Callable) -> None:
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        cv.create_text(12, 14, text=title.upper(), anchor="w", fill=C["muted"], font=self.f_head)
        if not self.rows or W < 100:
            return
        vals = [getter(r) for r in self.rows]
        real = [v for v in vals if v is not None]
        vmax = max(real) if real and max(real) > 0 else 1
        contenders = [v for r, v in zip(self.rows, vals) if r.ok and v is not None]
        best = min(contenders) if contenders else None
        top, label_w, right_pad = 32, 74, 74
        row_h = (H - top - 8) / len(self.rows)
        for i, (r, v) in enumerate(zip(self.rows, vals)):
            y = top + i * row_h
            cy = y + row_h / 2
            cv.create_text(12, cy, text=r.short, anchor="w", font=(self.f_ui[0], 9),
                           fill=C["text"] if r.ok else C["muted"])
            if v is None:
                cv.create_text(label_w + 6, cy, text="✗ failed", anchor="w", fill=C["bad"], font=(self.f_ui[0], 8))
                continue
            width = max(3.0, (W - label_w - right_pad - 10) * v / vmax)
            color = CAT_COLOR.get(r.category, C["accent"])
            if not r.ok:
                color = C["line"]
            win = r.ok and best is not None and v == best
            cv.create_rectangle(label_w, y + row_h * 0.2, label_w + width, y + row_h * 0.8, fill=color,
                                outline=C["frontier"] if win else color, width=2 if win else 1)
            cv.create_text(label_w + width + 6, cy, text=fmt(v) + (" ★" if win else ""), anchor="w",
                           fill=C["frontier"] if win else C["muted"], font=(self.f_mono[0], 8))

    # ----------------------------------------------------------- takeaways --
    def _takeaways(self) -> None:
        for w in self.take_box.winfo_children():
            w.destroy()
        rows, lines = self.rows, []
        ok = [r for r in rows if r.ok]
        if not ok:
            lines.append((C["bad"], "No algorithm reached the goal - this maze is unsolvable. "
                                    "Open a path in the main window and re-run."))
        else:
            opt = [r for r in ok if r.path_cost == self.best_cost]
            lines.append((C["ok"], f"Optimal cost is {self.best_cost:g}, reached by: "
                                   + ", ".join(r.short for r in opt) + "."))
            worse = [r for r in ok if r.path_cost > self.best_cost]
            if worse:
                lines.append((C["warn"], "Faster but costlier: " + ", ".join(
                    f"{r.short} (cost {r.path_cost:g}, +{(r.path_cost / self.best_cost - 1) * 100:.0f}%)"
                    for r in worse) + " - they trade path quality for speed or memory."))
            fastest = min(ok, key=lambda r: r.time_s)
            lines.append((C["text"], f"Fastest to finish: {fastest.short} ({fmt_time(fastest.time_s)}). "
                                     f"Smallest memory: {min(ok, key=lambda r: r.peak_stored).short} "
                                     f"({min(r.peak_stored for r in ok):,} nodes)."))
            base = next((r for r in opt if r.key == "ucs"), None)
            lean = min(opt, key=lambda r: r.expanded)
            if base and lean.key != "ucs" and base.expanded:
                lines.append((C["accent_hi"], f"Among optimal algorithms, {lean.short} expanded the fewest nodes "
                                              f"({lean.expanded:,}) - {(1 - lean.expanded / base.expanded) * 100:.0f}% "
                                              f"fewer than UCS ({base.expanded:,}). That is what a good heuristic buys you."))
        for r in rows:
            if not r.ok:
                why = "got stuck in a local minimum" if r.key == "hill" else "could not reach the goal"
                lines.append((C["bad"], f"{r.name} {why} after expanding {r.expanded:,} node(s)."))
        for color, text in lines:
            tk.Label(self.take_box, text="•  " + text, bg=C["card"], fg=color, font=(self.f_ui[0], 9),
                     anchor="w", justify="left", wraplength=1100).pack(anchor="w", pady=1)

    # ------------------------------------------------------------- export --
    def _export(self) -> None:
        if not self.rows:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            initialfile="search_comparison.csv")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                wr = csv.writer(f)
                wr.writerow(["algorithm", "type", "status", "compute_time_ms", "expanded", "generated",
                             "peak_memory_nodes", "peak_frontier", "path_length", "path_cost"])
                for r in self.rows:
                    wr.writerow([r.name, r.category, r.status, f"{r.time_s * 1000:.4f}", r.expanded,
                                 r.generated, r.peak_stored, r.peak_frontier,
                                 r.path_len if r.ok else "", f"{r.path_cost:g}" if r.ok else ""])
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)


# --------------------------------------------------------------------------- #
_open_windows = {}


def open_compare_window(parent, maze, heuristic: str = "Manhattan") -> CompareWindow:
    """Called by gui.py. Re-uses the window if it is already open (and re-runs)."""
    win = _open_windows.get(id(parent))
    if win is not None and win.winfo_exists():
        win.heur_var.set(heuristic)
        win.lift()
        win.run()
        return win
    win = CompareWindow(parent, maze, heuristic)
    _open_windows[id(parent)] = win
    return win


if __name__ == "__main__":
    print("compare.py is opened from the main window (python main.py -> 'Compare all algorithms').")
