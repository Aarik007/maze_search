"""
maze.py  --  MODULE 2 of 4  (pure Python, no GUI)
=================================================

The editable maze *model*.  The GUI (module 3) will simply call these methods
from mouse/keyboard events and redraw whenever the maze notifies it.

Grid convention (shared with search_engine.py)
    0  = wall          >=1 = floor, number = cost of entering the cell

What it gives you
    * Tools      : WALL, ERASE, WEIGHT (mud 2-9), START, GOAL  -> apply_tool()
    * Smooth drag: paint_line() fills the gaps when the mouse moves fast
    * Undo/redo  : call begin_edit() on mouse-down, then paint freely
    * Resize     : resize(rows, cols) keeps what already fits
    * Generators : perfect maze (+loops), random walls, weighted terrain
    * Presets    : ready-made scenarios that show off each algorithm
    * File I/O   : save()/load() as JSON, to_ascii()/from_ascii() as text
    * Bridge     : to_problem(heuristic) -> search_engine.GridProblem
    * Observer   : add_listener(fn) -> fn() is called after every change
"""
from __future__ import annotations

import copy
import json
import random
from collections import deque
from enum import Enum
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from search_engine import GridProblem, WALL

Cell = Tuple[int, int]


class Tool(str, Enum):
    WALL = "wall"
    ERASE = "erase"
    WEIGHT = "weight"
    START = "start"
    GOAL = "goal"


def line_cells(a: Cell, b: Cell) -> Iterator[Cell]:
    """Bresenham line from a to b (inclusive) - makes fast mouse drags continuous."""
    r0, c0 = a
    r1, c1 = b
    dx, dy = abs(c1 - c0), -abs(r1 - r0)
    sx = 1 if c0 < c1 else -1
    sy = 1 if r0 < r1 else -1
    err = dx + dy
    while True:
        yield (r0, c0)
        if (r0, c0) == (r1, c1):
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            c0 += sx
        if e2 <= dx:
            err += dx
            r0 += sy


class Maze:
    MIN_SIZE, MAX_ROWS, MAX_COLS = 3, 60, 100
    MIN_WEIGHT, MAX_WEIGHT = 2, 9
    HISTORY_LIMIT = 100

    def __init__(self, rows: int = 15, cols: int = 25):
        rows = max(self.MIN_SIZE, min(rows, self.MAX_ROWS))
        cols = max(self.MIN_SIZE, min(cols, self.MAX_COLS))
        self.grid: List[List[int]] = [[1] * cols for _ in range(rows)]
        self.start: Cell = (rows // 2, 1 if cols >= 5 else 0)
        self.goal: Cell = (rows // 2, cols - (2 if cols >= 5 else 1))
        self._undo: List[tuple] = []
        self._redo: List[tuple] = []
        self._listeners: List[Callable[[], None]] = []

    # ------------------------------------------------------------------ basics
    @property
    def rows(self) -> int:
        return len(self.grid)

    @property
    def cols(self) -> int:
        return len(self.grid[0])

    def in_bounds(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.rows and 0 <= cell[1] < self.cols

    def is_wall(self, cell: Cell) -> bool:
        return self.grid[cell[0]][cell[1]] == WALL

    def cost(self, cell: Cell) -> int:
        return self.grid[cell[0]][cell[1]]

    @property
    def wall_count(self) -> int:
        return sum(v == WALL for row in self.grid for v in row)

    @property
    def weighted_count(self) -> int:
        return sum(v > 1 for row in self.grid for v in row)

    @property
    def open_count(self) -> int:
        return self.rows * self.cols - self.wall_count

    def add_listener(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in self._listeners:
            fn()

    # ----------------------------------------------------------------- editing
    def apply_tool(self, tool: Tool, cell: Cell, weight: int = 5) -> bool:
        """Apply one tool to one cell. Returns True if anything changed."""
        if not self.in_bounds(cell):
            return False
        r, c = cell
        endpoint = cell in (self.start, self.goal)
        changed = False
        if tool == Tool.WALL:
            if not endpoint and self.grid[r][c] != WALL:
                self.grid[r][c], changed = WALL, True
        elif tool == Tool.ERASE:
            if self.grid[r][c] != 1:
                self.grid[r][c], changed = 1, True
        elif tool == Tool.WEIGHT:
            w = max(self.MIN_WEIGHT, min(int(weight), self.MAX_WEIGHT))
            if not endpoint and self.grid[r][c] != w:
                self.grid[r][c], changed = w, True
        elif tool in (Tool.START, Tool.GOAL):
            other = self.goal if tool == Tool.START else self.start
            if cell != other:
                self.grid[r][c] = 1 if self.grid[r][c] == WALL else self.grid[r][c]
                if tool == Tool.START and cell != self.start:
                    self.start, changed = cell, True
                if tool == Tool.GOAL and cell != self.goal:
                    self.goal, changed = cell, True
        if changed:
            self._notify()
        return changed

    def paint_line(self, tool: Tool, a: Cell, b: Cell, weight: int = 5) -> bool:
        """Apply a tool along a straight line (use between two mouse events)."""
        if tool in (Tool.START, Tool.GOAL):            # endpoints just jump
            return self.apply_tool(tool, b, weight)
        changed = False
        for cell in line_cells(a, b):
            changed |= self.apply_tool(tool, cell, weight)
        return changed

    def fill_rect(self, a: Cell, b: Cell, value: int) -> None:
        """Set a rectangle to `value` (0 wall, 1 floor, 2-9 mud); endpoints are kept."""
        (r0, c0), (r1, c1) = a, b
        for r in range(max(0, min(r0, r1)), min(self.rows, max(r0, r1) + 1)):
            for c in range(max(0, min(c0, c1)), min(self.cols, max(c0, c1) + 1)):
                if (r, c) not in (self.start, self.goal):
                    self.grid[r][c] = value
        self._notify()

    def clear(self, keep_start_goal: bool = True) -> None:
        self.begin_edit()
        self.grid = [[1] * self.cols for _ in range(self.rows)]
        if not keep_start_goal:
            self.start = (self.rows // 2, 1 if self.cols >= 5 else 0)
            self.goal = (self.rows // 2, self.cols - (2 if self.cols >= 5 else 1))
        self._notify()

    def clear_weights(self) -> None:
        self.begin_edit()
        self.grid = [[1 if v > 1 else v for v in row] for row in self.grid]
        self._notify()

    def resize(self, rows: int, cols: int) -> None:
        """Change grid size, keeping the overlapping part; endpoints are clamped."""
        rows = max(self.MIN_SIZE, min(rows, self.MAX_ROWS))
        cols = max(self.MIN_SIZE, min(cols, self.MAX_COLS))
        if (rows, cols) == (self.rows, self.cols):
            return
        self.begin_edit()
        new = [[1] * cols for _ in range(rows)]
        for r in range(min(rows, self.rows)):
            for c in range(min(cols, self.cols)):
                new[r][c] = self.grid[r][c]
        self.grid = new
        clamp = lambda p: (min(p[0], rows - 1), min(p[1], cols - 1))
        self.start, self.goal = clamp(self.start), clamp(self.goal)
        if self.start == self.goal:
            self.goal = (rows - 1, cols - 1) if self.start != (rows - 1, cols - 1) else (0, 0)
        for r, c in (self.start, self.goal):
            if self.grid[r][c] == WALL:
                self.grid[r][c] = 1
        self._notify()

    # ------------------------------------------------------------ undo / redo
    def _snapshot(self) -> tuple:
        return (copy.deepcopy(self.grid), self.start, self.goal)

    def _restore(self, snap: tuple) -> None:
        self.grid, self.start, self.goal = copy.deepcopy(snap[0]), snap[1], snap[2]

    def begin_edit(self) -> None:
        """Call ONCE per user action (e.g. mouse-down) before painting."""
        self._undo.append(self._snapshot())
        if len(self._undo) > self.HISTORY_LIMIT:
            self._undo.pop(0)
        self._redo.clear()

    def end_edit(self) -> None:
        """Call on mouse-up: drops the undo entry if the drag changed nothing."""
        if self._undo and self._undo[-1] == self._snapshot():
            self._undo.pop()

    def replace_with(self, other: "Maze") -> None:
        """Swap in another maze's contents (undoable) - used by File > Open."""
        self.begin_edit()
        self.grid = copy.deepcopy(other.grid)
        self.start, self.goal = other.start, other.goal
        self._notify()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        self._notify()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        self._notify()
        return True

    # ------------------------------------------------------------- solvability
    def reachable(self) -> set:
        seen, q = {self.start}, deque([self.start])
        while q:
            r, c = q.popleft()
            for dr, dc in GridProblem.MOVES:
                n = (r + dr, c + dc)
                if self.in_bounds(n) and n not in seen and self.grid[n[0]][n[1]] != WALL:
                    seen.add(n)
                    q.append(n)
        return seen

    def is_solvable(self) -> bool:
        return self.goal in self.reachable()

    def _carve_l_path(self) -> None:
        """Guarantee a route: open an L-shaped corridor start -> goal."""
        (r0, c0), (r1, c1) = self.start, self.goal
        step = 1 if c1 >= c0 else -1
        for c in range(c0, c1 + step, step):
            if self.grid[r0][c] == WALL:
                self.grid[r0][c] = 1
        step = 1 if r1 >= r0 else -1
        for r in range(r0, r1 + step, step):
            if self.grid[r][c1] == WALL:
                self.grid[r][c1] = 1

    # -------------------------------------------------------------- generators
    def generate_maze(self, loops: float = 0.08, seed: Optional[int] = None) -> None:
        """Recursive-backtracker maze. loops (0-1) knocks down walls to create
        alternative routes - without them there is only one path, so every
        algorithm would find the same one."""
        rng = random.Random(seed)
        self.begin_edit()
        R, C = self.rows, self.cols
        self.grid = [[WALL] * C for _ in range(R)]
        self.grid[0][0] = 1
        stack = [(0, 0)]
        while stack:
            r, c = stack[-1]
            opts = [(r + dr, c + dc) for dr, dc in ((-2, 0), (2, 0), (0, -2), (0, 2))
                    if 0 <= r + dr < R and 0 <= c + dc < C and self.grid[r + dr][c + dc] == WALL]
            if not opts:
                stack.pop()
                continue
            nr, nc = rng.choice(opts)
            self.grid[(r + nr) // 2][(c + nc) // 2] = 1
            self.grid[nr][nc] = 1
            stack.append((nr, nc))
        self.start = (0, 0)
        self.goal = ((R - 1) // 2 * 2, (C - 1) // 2 * 2)
        walls = [(r, c) for r in range(1, R - 1) for c in range(1, C - 1)
                 if self.grid[r][c] == WALL and
                 ((self.grid[r - 1][c] and self.grid[r + 1][c]) or
                  (self.grid[r][c - 1] and self.grid[r][c + 1]))]
        rng.shuffle(walls)
        for r, c in walls[:int(len(walls) * max(0.0, min(1.0, loops)))]:
            self.grid[r][c] = 1
        self._notify()

    def generate_random(self, density: float = 0.28, seed: Optional[int] = None) -> None:
        """Scatter random walls; always leaves the maze solvable."""
        rng = random.Random(seed)
        self.begin_edit()
        density = max(0.0, min(0.7, density))
        for _ in range(40):
            self.grid = [[WALL if (r, c) not in (self.start, self.goal) and rng.random() < density
                          else 1 for c in range(self.cols)] for r in range(self.rows)]
            if self.is_solvable():
                break
        else:
            self._carve_l_path()
        self._notify()

    def generate_terrain(self, density: float = 0.15, seed: Optional[int] = None) -> None:
        """Random walls plus blobs of mud (cost 3/5/8) - great for UCS vs BFS."""
        rng = random.Random(seed)
        self.generate_random(density, seed)
        for _ in range(max(2, self.rows * self.cols // 55)):
            cr, cc, rad = rng.randrange(self.rows), rng.randrange(self.cols), rng.randint(1, 3)
            w = rng.choice((3, 5, 8))
            for r in range(max(0, cr - rad), min(self.rows, cr + rad + 1)):
                for c in range(max(0, cc - rad), min(self.cols, cc + rad + 1)):
                    if (r - cr) ** 2 + (c - cc) ** 2 <= rad * rad + 1 \
                            and self.grid[r][c] != WALL and (r, c) not in (self.start, self.goal):
                        self.grid[r][c] = w
        self._notify()

    # ----------------------------------------------------------------- presets
    PRESETS = ["Open Field", "Hill-Climbing Trap", "Mud vs Detour",
               "Perfect Maze", "Maze with Loops", "Random Walls", "Weighted Terrain"]

    def load_preset(self, name: str, seed: Optional[int] = None) -> None:
        if name == "Open Field":
            self.clear(keep_start_goal=True)
        elif name == "Hill-Climbing Trap":
            self._preset_trap()
        elif name == "Mud vs Detour":
            self._preset_mud()
        elif name == "Perfect Maze":
            self.generate_maze(loops=0.0, seed=seed)
        elif name == "Maze with Loops":
            self.generate_maze(loops=0.12, seed=seed)
        elif name == "Random Walls":
            self.generate_random(0.28, seed)
        elif name == "Weighted Terrain":
            self.generate_terrain(0.15, seed)
        else:
            raise ValueError(f"unknown preset {name!r}")

    def _preset_trap(self) -> None:
        """A cup facing the goal: Hill Climbing & Greedy march in and get stuck."""
        self.begin_edit()
        self.grid = [[1] * 25 for _ in range(15)]
        self.start, self.goal = (7, 2), (7, 22)
        for r in range(3, 12):
            self.grid[r][10] = WALL
        for c in range(5, 11):
            self.grid[3][c] = WALL
            self.grid[11][c] = WALL
        self._notify()

    def _preset_mud(self) -> None:
        """Straight line is short in STEPS but costly; the detour is cheap in COST."""
        self.begin_edit()
        self.grid = [[1] * 25 for _ in range(11)]
        self.start, self.goal = (5, 1), (5, 23)
        for r in range(1, 10):
            for c in range(8, 17):
                self.grid[r][c] = 9
        self._notify()

    # -------------------------------------------------------------- bridge/IO
    def to_problem(self, heuristic: str = "Manhattan") -> GridProblem:
        """Hand the current maze to the search engine."""
        return GridProblem(self.grid, self.start, self.goal, heuristic)

    def to_ascii(self) -> str:
        lines = []
        for r in range(self.rows):
            row = []
            for c in range(self.cols):
                v = self.grid[r][c]
                row.append("S" if (r, c) == self.start else "G" if (r, c) == self.goal
                           else "#" if v == WALL else "." if v == 1 else str(min(v, 9)))
            lines.append("".join(row))
        return "\n".join(lines)

    @classmethod
    def from_ascii(cls, text: str) -> "Maze":
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        if not lines or len({len(l) for l in lines}) != 1:
            raise ValueError("maze text must be a non-empty rectangle")
        m = cls(len(lines), len(lines[0]))
        start = goal = None
        for r, line in enumerate(lines):
            for c, ch in enumerate(line):
                m.grid[r][c] = WALL if ch == "#" else int(ch) if ch.isdigit() and ch != "0" else 1
                if ch == "S": start = (r, c)
                if ch == "G": goal = (r, c)
        if start is None or goal is None:
            raise ValueError("maze text needs one 'S' and one 'G'")
        m.start, m.goal = start, goal
        return m

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"rows": self.rows, "cols": self.cols, "start": self.start,
                       "goal": self.goal, "grid": self.grid}, f)

    @classmethod
    def load(cls, path: str) -> "Maze":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        m = cls(d["rows"], d["cols"])
        m.grid = [list(map(int, row)) for row in d["grid"]]
        m.start, m.goal = tuple(d["start"]), tuple(d["goal"])
        return m

    def copy(self) -> "Maze":
        m = Maze(self.rows, self.cols)
        m.grid, m.start, m.goal = copy.deepcopy(self.grid), self.start, self.goal
        return m


# --------------------------------------------------------------------------- #
#  Terminal demo:  python maze.py
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    from search_engine import ALGORITHMS, run_to_completion

    m = Maze()
    for name in ("Hill-Climbing Trap", "Mud vs Detour", "Maze with Loops"):
        m.load_preset(name, seed=7)
        print(f"\n=== {name}  ({m.rows}x{m.cols}, solvable={m.is_solvable()}) ===")
        print(m.to_ascii())
        prob = m.to_problem("Manhattan")
        print(f"\n{'Algorithm':<26}{'Result':<8}{'Expanded':>9}{'PeakMem':>9}{'Cost':>7}")
        for key, cls in ALGORITHMS.items():
            st, _ = run_to_completion(prob, key)
            print(f"{cls.name:<26}{st.status:<8}{st.expanded:>9}{st.peak_stored:>9}{st.path_cost:>7g}")

    # undo / redo / file round-trip self-check
    m.load_preset("Open Field")
    m.begin_edit(); m.paint_line(Tool.WALL, (0, 0), (5, 5))
    walls = m.wall_count
    m.undo(); assert m.wall_count == 0 and m.redo() and m.wall_count == walls
    m.save("/tmp/_maze.json"); assert Maze.load("/tmp/_maze.json").to_ascii() == m.to_ascii()
    print("\nundo/redo + save/load self-check: OK")
