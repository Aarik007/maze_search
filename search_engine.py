"""
search_engine.py  --  MODULE 1 of 4  (pure Python, no third-party deps, no GUI)
==============================================================================

The brain of the project.  It knows NOTHING about windows or colours; it only
turns a grid + an algorithm choice into a *stream of steps* that any front-end
(the Tkinter GUI in module 3) can animate one at a time.

Algorithms
    Uninformed : BFS, DFS, Uniform Cost Search
    Informed   : Greedy Best-First, A*, AO*, Hill Climbing   (Manhattan / Euclidean / Chebyshev h)

Grid convention  (module 2 - the maze editor - will produce exactly this)
    grid[row][col] == 0   -> WALL
    grid[row][col] >= 1   -> open cell; the number is the COST of entering it
                             (1 = normal floor, 5 = "mud", ...).

Integration contract (what the other modules rely on)
    ALGORITHMS, CATEGORIES, HEURISTICS   -> build menus automatically
    GridProblem(grid, start, goal, heuristic="Manhattan")
    create(key, problem).run()           -> yields Step objects
    Step.current / added / dropped / note / status / path / stats
    Stats                                -> time, expanded, peak memory, ...
    run_to_completion(problem, key)      -> (Stats, path) for comparisons
"""
from __future__ import annotations

import heapq
import itertools
import math
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import asdict, dataclass, field, replace
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Type

State = Tuple[int, int]          # (row, col)
WALL = 0
INF = float("inf")


# --------------------------------------------------------------------------- #
#  Heuristics
# --------------------------------------------------------------------------- #
def manhattan(a: State, b: State) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def euclidean(a: State, b: State) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def chebyshev(a: State, b: State) -> float:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


HEURISTICS: Dict[str, Callable[[State, State], float]] = {
    "Manhattan": manhattan,
    "Euclidean": euclidean,
    "Chebyshev": chebyshev,
}


# --------------------------------------------------------------------------- #
#  Problem definition (grid maze, 4-directional moves)
# --------------------------------------------------------------------------- #
class GridProblem:
    MOVES = ((-1, 0), (0, 1), (1, 0), (0, -1))     # up, right, down, left

    def __init__(self, grid: Sequence[Sequence[int]], start: State, goal: State,
                 heuristic: str = "Manhattan"):
        self.grid = [list(r) for r in grid]
        self.rows, self.cols = len(self.grid), len(self.grid[0])
        self.start, self.goal = tuple(start), tuple(goal)
        for name, s in (("start", self.start), ("goal", self.goal)):
            if not self.in_bounds(s) or self.grid[s[0]][s[1]] == WALL:
                raise ValueError(f"{name} {s} is outside the grid or on a wall")
        self.set_heuristic(heuristic)

    # ---- construction helpers ------------------------------------------------
    @classmethod
    def from_ascii(cls, text: str, heuristic: str = "Manhattan") -> "GridProblem":
        """'#' wall, '.' floor, '2'-'9' weighted floor, 'S' start, 'G' goal."""
        grid, start, goal = [], None, None
        for r, line in enumerate(l for l in text.strip("\n").splitlines() if l.strip()):
            row = []
            for c, ch in enumerate(line.strip()):
                if ch == "#": row.append(WALL)
                elif ch.isdigit() and ch != "0": row.append(int(ch))
                else: row.append(1)
                if ch == "S": start = (r, c)
                if ch == "G": goal = (r, c)
            grid.append(row)
        return cls(grid, start, goal, heuristic)

    def set_heuristic(self, name: str) -> None:
        self.heuristic_name = name
        self._h = HEURISTICS[name]

    # ---- the search interface --------------------------------------------------
    def in_bounds(self, s: State) -> bool:
        return 0 <= s[0] < self.rows and 0 <= s[1] < self.cols

    def is_goal(self, s: State) -> bool:
        return s == self.goal

    def neighbors(self, s: State) -> List[Tuple[State, float]]:
        out = []
        for dr, dc in self.MOVES:
            n = (s[0] + dr, s[1] + dc)
            if self.in_bounds(n) and self.grid[n[0]][n[1]] != WALL:
                out.append((n, self.grid[n[0]][n[1]]))
        return out

    def h(self, s: State) -> float:
        return self._h(s, self.goal)

    def path_cost(self, path: Sequence[State]) -> float:
        return sum(self.grid[r][c] for r, c in path[1:])


# --------------------------------------------------------------------------- #
#  Data the GUI consumes
# --------------------------------------------------------------------------- #
@dataclass
class Stats:
    """Live metrics; a fresh snapshot is attached to every Step."""
    status: str = "idle"          # idle | running | found | failed
    steps: int = 0
    expanded: int = 0             # nodes popped & expanded  (TIME driver)
    generated: int = 0            # nodes ever created
    frontier_size: int = 0        # nodes waiting right now
    peak_frontier: int = 0
    stored_nodes: int = 0         # nodes held in memory right now (SPACE driver)
    peak_stored: int = 0          # worst-case memory -> measured space complexity
    time_s: float = 0.0           # pure compute time (animation delays excluded)
    path_length: int = 0
    path_cost: float = 0.0

    @property
    def time_ms(self) -> float:
        return self.time_s * 1000.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Step:
    current: Optional[State]                       # node expanded this step
    added: List[State] = field(default_factory=list)    # newly on the frontier
    note: str = ""                                 # human-readable explanation
    dropped: List[State] = field(default_factory=list)  # removed from frontier
    status: str = "running"                        # running | found | failed
    path: Optional[List[State]] = None             # solution (or HC trail on fail)
    stats: Optional[Stats] = None


# --------------------------------------------------------------------------- #
#  Base class
# --------------------------------------------------------------------------- #
def _trace(parents: Dict[State, Optional[State]], node: State) -> List[State]:
    path = []
    while node is not None:
        path.append(node)
        node = parents[node]
    return path[::-1]


class SearchAlgorithm(ABC):
    key = ""
    name = ""
    category = ""
    description = ""
    time_complexity = ""
    space_complexity = ""
    complete = True
    optimal = False

    def __init__(self, problem: GridProblem):
        self.problem = problem
        self.stats = Stats()

    # Public: wraps the algorithm so timing excludes whatever the GUI does
    # between steps (animation delays, drawing, ...).
    def run(self) -> Iterator[Step]:
        self.stats = Stats(status="running")
        gen = self._search()
        while True:
            t0 = time.perf_counter()
            try:
                step = next(gen)
            except StopIteration:
                return
            self.stats.time_s += time.perf_counter() - t0
            self.stats.steps += 1
            if step.status != "running":
                self.stats.status = step.status
            step.stats = replace(self.stats)
            yield step

    @abstractmethod
    def _search(self) -> Iterator[Step]: ...

    # helpers
    def _track(self, frontier: int, stored: int) -> None:
        s = self.stats
        s.frontier_size, s.stored_nodes = frontier, stored
        s.peak_frontier = max(s.peak_frontier, frontier)
        s.peak_stored = max(s.peak_stored, stored)

    def _found(self, path: List[State], note: str = "Goal reached!") -> Step:
        self.stats.path_length = len(path) - 1
        self.stats.path_cost = self.problem.path_cost(path)
        return Step(path[-1], note=note, status="found", path=path)

    @staticmethod
    def _failed(note: str, path: Optional[List[State]] = None) -> Step:
        return Step(None, note=note, status="failed", path=path)


# --------------------------------------------------------------------------- #
#  UNINFORMED
# --------------------------------------------------------------------------- #
class BreadthFirstSearch(SearchAlgorithm):
    key, name, category = "bfs", "Breadth-First Search", "Uninformed"
    description = ("Expands the shallowest node first using a FIFO queue. Finds "
                   "the path with the fewest moves (ignores cell costs).")
    time_complexity = "O(b^d)"
    space_complexity = "O(b^d)"
    complete, optimal = True, False      # optimal only for uniform step costs

    def _search(self):
        p, s = self.problem, self.stats
        parents = {p.start: None}
        queue = deque([p.start])
        s.generated = 1
        self._track(1, 1)
        yield Step(None, [p.start], "Start node placed in the queue")
        while queue:
            cur = queue.popleft()
            s.expanded += 1
            if p.is_goal(cur):
                yield self._found(_trace(parents, cur)); return
            new = []
            for nxt, _ in p.neighbors(cur):
                if nxt not in parents:
                    parents[nxt] = cur
                    queue.append(nxt)
                    new.append(nxt)
            s.generated += len(new)
            self._track(len(queue), len(parents))
            yield Step(cur, new, f"Expand {cur}: queued {len(new)} new neighbour(s)")
        yield self._failed("Queue empty - the goal is unreachable")


class DepthFirstSearch(SearchAlgorithm):
    key, name, category = "dfs", "Depth-First Search", "Uninformed"
    description = ("Dives down one branch as far as possible using a LIFO stack, "
                   "then backtracks. Fast to memory but the path is rarely short.")
    time_complexity = "O(b^m)"
    space_complexity = "O(b*m)"
    complete, optimal = True, False      # complete here because of the visited set

    def _search(self):
        p, s = self.problem, self.stats
        parents: Dict[State, Optional[State]] = {}
        stack = [(p.start, None)]
        s.generated = 1
        self._track(1, 1)
        yield Step(None, [p.start], "Start node pushed on the stack")
        while stack:
            cur, par = stack.pop()
            if cur in parents:                       # stale duplicate
                continue
            parents[cur] = par
            s.expanded += 1
            if p.is_goal(cur):
                yield self._found(_trace(parents, cur)); return
            new = []
            for nxt, _ in reversed(p.neighbors(cur)):   # keeps U,R,D,L order
                if nxt not in parents:
                    stack.append((nxt, cur))
                    new.append(nxt)
            s.generated += len(new)
            self._track(len(stack), len(parents) + len(stack))
            yield Step(cur, new, f"Go deeper from {cur}: pushed {len(new)} neighbour(s)")
        yield self._failed("Stack empty - the goal is unreachable")


class _BestFirst(SearchAlgorithm):
    """Shared engine for Uniform Cost Search and A*; they differ only in priority."""

    rescore = True        # False = never revise a node once discovered (greedy)

    def priority(self, g: float, state: State) -> tuple:
        raise NotImplementedError

    def note(self, cur: State, g: float, n_new: int) -> str:
        return f"Expand {cur} (g={g:g}): {n_new} new neighbour(s)"

    def _search(self):
        p, s = self.problem, self.stats
        tie = itertools.count()
        g = {p.start: 0}
        parents = {p.start: None}
        closed = set()
        heap = [(self.priority(0, p.start), next(tie), p.start)]
        s.generated = 1
        self._track(1, 1)
        yield Step(None, [p.start], "Start node placed in the priority queue")
        while heap:
            _, _, cur = heapq.heappop(heap)
            if cur in closed:                        # stale heap entry
                continue
            closed.add(cur)
            s.expanded += 1
            if p.is_goal(cur):
                yield self._found(_trace(parents, cur)); return
            new = []
            for nxt, cost in p.neighbors(cur):
                ng = g[cur] + cost
                if nxt not in g or (self.rescore and ng < g[nxt]):
                    if nxt not in g:
                        new.append(nxt)
                    g[nxt], parents[nxt] = ng, cur
                    closed.discard(nxt)              # re-open if a cheaper way found
                    heapq.heappush(heap, (self.priority(ng, nxt), next(tie), nxt))
            s.generated += len(new)
            self._track(len(g) - len(closed), len(g))
            yield Step(cur, new, self.note(cur, g[cur], len(new)))
        yield self._failed("Priority queue empty - the goal is unreachable")


class UniformCostSearch(_BestFirst):
    key, name, category = "ucs", "Uniform Cost Search", "Uninformed"
    description = ("Always expands the cheapest-so-far node g(n). Optimal for "
                   "weighted cells (mud, water...) - Dijkstra's algorithm.")
    time_complexity = "O(b^(1+C*/e))"
    space_complexity = "O(b^(1+C*/e))"
    complete, optimal = True, True

    def priority(self, g, state):
        return (g,)


# --------------------------------------------------------------------------- #
#  INFORMED
# --------------------------------------------------------------------------- #
class AStarSearch(_BestFirst):
    key, name, category = "astar", "A* Search", "Informed"
    description = ("Expands the node with lowest f(n) = g(n) + h(n). With an "
                   "admissible heuristic like Manhattan distance it is optimal "
                   "and explores far fewer nodes than UCS.")
    time_complexity = "O(b^d) worst, far less with a good h"
    space_complexity = "O(b^d)"
    complete, optimal = True, True

    def priority(self, g, state):
        h = self.problem.h(state)
        return (g + h, h)                             # tie-break: closer to goal

    def note(self, cur, g, n_new):
        h = self.problem.h(cur)
        return f"Expand {cur}: g={g:g} + h={h:g} = f={g + h:g}; {n_new} new neighbour(s)"


class GreedyBestFirstSearch(_BestFirst):
    key, name, category = "greedy", "Greedy Best-First Search", "Informed"
    description = ("Always expands the node that LOOKS closest to the goal, "
                   "f(n) = h(n), ignoring the cost already paid. Very fast and "
                   "goal-directed, but the path it finds can be longer than "
                   "optimal and it can be lured into dead-end pockets.")
    time_complexity = "O(b^m) worst, often near O(b*d)"
    space_complexity = "O(b^m)"
    complete, optimal = True, False      # complete here because of the closed set
    rescore = False                      # classic greedy: first discovery sticks

    def priority(self, g, state):
        return (self.problem.h(state),)

    def note(self, cur, g, n_new):
        return f"Expand {cur}: h={self.problem.h(cur):g} (lowest on frontier); {n_new} new neighbour(s)"


class AOStarSearch(SearchAlgorithm):
    """
    Genuine AO* over an AND-OR graph.  A grid move is an OR choice (pick ONE
    successor), so the best solution graph degenerates to a single path, but the
    machinery is the real thing: keep a partial solution graph, expand a tip on
    the current best path, then REVISE cost estimates back up to the root and
    mark nodes SOLVED.  Arcs that would create a cycle are skipped (AO* needs an
    acyclic graph) - going back to an ancestor never helps with positive costs.
    """
    key, name, category = "aostar", "AO* Search", "Informed"
    description = ("Builds an AND-OR solution graph: expand a tip on the current "
                   "best partial solution, back-propagate revised cost estimates "
                   "to the root and mark nodes solved. On a maze every move is "
                   "an OR arc, so the solution is one path.")
    time_complexity = "O(b^d) worst case"
    space_complexity = "O(b^d)"
    complete, optimal = True, True

    def _search(self):
        p, s = self.problem, self.stats
        start = p.start
        value: Dict[State, float] = {start: p.h(start)}   # current cost estimate
        arcs: Dict[State, List[Tuple[float, List[State]]]] = {}  # AND/OR hyper-arcs
        best: Dict[State, Optional[int]] = {}
        parents: Dict[State, set] = {start: set()}
        solved = set()
        tips = set()                                      # generated, unexpanded
        s.generated = 1
        if p.is_goal(start):
            solved.add(start); value[start] = 0
        else:
            tips.add(start)
        self._track(len(tips), len(value))
        yield Step(None, [start], "Root of the AND-OR graph created")

        while start not in solved:
            if value[start] == INF:
                yield self._failed("Every branch is a dead end - goal unreachable")
                return
            tip = self._find_tip(start, arcs, best, solved)
            if tip is None:                                # safety net
                yield self._failed("No expandable tip left")
                return
            s.expanded += 1
            tips.discard(tip)
            anc = self._ancestors(tip, parents)
            new, tip_arcs = [], []
            for nxt, cost in p.neighbors(tip):
                if nxt in anc or nxt == tip:               # would close a cycle
                    continue
                if nxt not in value:
                    value[nxt] = 0 if p.is_goal(nxt) else p.h(nxt)
                    parents[nxt] = set()
                    new.append(nxt)
                    if p.is_goal(nxt):
                        solved.add(nxt)
                    else:
                        tips.add(nxt)
                parents[nxt].add(tip)
                tip_arcs.append((cost, [nxt]))             # OR arc, single child
            arcs[tip] = tip_arcs
            best[tip] = None
            s.generated += len(new)
            self._revise(tip, value, arcs, best, parents, solved)
            self._track(len(tips), len(value))
            yield Step(tip, new,
                       f"Expand tip {tip}; revised root estimate f={value[start]:g}")

        # follow the best arcs from the root to read off the solution path
        path, node = [start], start
        while not p.is_goal(node):
            node = arcs[node][best[node]][1][0]
            path.append(node)
        yield self._found(path, "Root marked SOLVED - solution graph complete")

    # ---- AO* internals ---------------------------------------------------------
    @staticmethod
    def _ancestors(node, parents):
        seen, stack = set(), [node]
        while stack:
            for par in parents[stack.pop()]:
                if par not in seen:
                    seen.add(par); stack.append(par)
        return seen

    @staticmethod
    def _find_tip(start, arcs, best, solved):
        """First unexpanded, unsolved node reachable via best arcs (AND = all kids)."""
        stack, seen = [start], set()
        while stack:
            n = stack.pop()
            if n in seen or n in solved:
                continue
            seen.add(n)
            if n not in arcs:
                return n
            if best.get(n) is not None:
                stack.extend(reversed(arcs[n][best[n]][1]))
        return None

    @staticmethod
    def _revise(tip, value, arcs, best, parents, solved):
        queue = deque([tip])
        while queue:
            n = queue.popleft()
            if n not in arcs:                    # tip / goal: nothing to recompute
                continue
            old_v, old_s = value[n], n in solved
            bv, bi = INF, None
            for i, (cost, kids) in enumerate(arcs[n]):
                v = cost + sum(value[k] for k in kids)     # AND = sum of children
                if v < bv:
                    bv, bi = v, i
            value[n], best[n] = bv, bi
            if bi is not None and all(k in solved for k in arcs[n][bi][1]):
                solved.add(n)
            if value[n] != old_v or (n in solved) != old_s or n == tip:
                queue.extend(parents[n])


class HillClimbing(SearchAlgorithm):
    key, name, category = "hill", "Hill Climbing", "Informed"
    description = ("Steepest-ascent: from the current cell always jump to the "
                   "neighbour with the best (lowest) heuristic and never look "
                   "back. Tiny memory, but gets trapped in local minima (dead-end "
                   "pockets facing the goal).")
    time_complexity = "O(b*d)"
    space_complexity = "O(1)"
    complete, optimal = False, False

    def _search(self):
        p, s = self.problem, self.stats
        cur, trail = p.start, [p.start]
        s.generated = 1
        self._track(1, 1)
        yield Step(None, [cur], "Start at the initial cell")
        while True:
            s.expanded += 1
            if p.is_goal(cur):
                yield self._found(trail); return
            cands = [(p.h(n), c, n) for n, c in p.neighbors(cur)]
            s.generated += len(cands)
            # algorithm state = current cell + its neighbours (the trail is only
            # kept so we can draw it, so it is not counted as memory)
            self._track(len(cands), 1 + len(cands))
            if not cands:
                yield self._failed(f"Dead end at {cur}", trail); return
            hb, _, nxt = min(cands)
            if hb >= p.h(cur):
                yield Step(cur, [n for _, _, n in cands],
                           f"Stuck at {cur}: no neighbour has h < {p.h(cur):g}", )
                yield self._failed(
                    f"Local minimum at {cur} (h={p.h(cur):g}) - hill climbing is stuck",
                    trail)
                return
            dropped = [n for _, _, n in cands if n != nxt]
            yield Step(cur, [n for _, _, n in cands], dropped=dropped,
                       note=f"At {cur} (h={p.h(cur):g}): best neighbour {nxt} (h={hb:g})")
            cur = nxt
            trail.append(cur)


# --------------------------------------------------------------------------- #
#  Registry  (the GUI builds its dropdowns from these - add a class, get a menu)
# --------------------------------------------------------------------------- #
ALGORITHMS: Dict[str, Type[SearchAlgorithm]] = {
    cls.key: cls for cls in (BreadthFirstSearch, DepthFirstSearch, UniformCostSearch,
                             GreedyBestFirstSearch, AStarSearch, AOStarSearch, HillClimbing)
}
CATEGORIES: Dict[str, List[str]] = {}
for _k, _c in ALGORITHMS.items():
    CATEGORIES.setdefault(_c.category + " Search", []).append(_k)


def create(key: str, problem: GridProblem) -> SearchAlgorithm:
    return ALGORITHMS[key](problem)


def run_to_completion(problem: GridProblem, key: str,
                      max_steps: int = 1_000_000) -> Tuple[Stats, Optional[List[State]]]:
    """Run without animation. Used for the comparison table/chart (module 4)."""
    algo, last = create(key, problem), None
    for i, last in enumerate(algo.run()):
        if i >= max_steps:
            break
    return algo.stats, (last.path if last and last.status == "found" else None)


# --------------------------------------------------------------------------- #
#  Quick terminal demo:  python search_engine.py
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    DEMO = """
    S.......#.....
    .#####..#.###.
    .#...#..#.#...
    .#.#.#.##.#.#.
    .#.#...#..#.#.
    .#.#####.##.#.
    .#.......#..#.
    .#######.#.##.
    ........2#....
    .######.##.##.
    ..3333..#...#G
    """
    prob = GridProblem.from_ascii(DEMO)
    print(f"Maze {prob.rows}x{prob.cols}  start={prob.start}  goal={prob.goal}  "
          f"heuristic={prob.heuristic_name}\n")
    print(f"{'Algorithm':<26}{'Result':<8}{'Time ms':>9}{'Expanded':>10}"
          f"{'PeakMem':>9}{'PathLen':>9}{'Cost':>7}")
    for key in ALGORITHMS:
        st, path = run_to_completion(prob, key)
        print(f"{ALGORITHMS[key].name:<26}{st.status:<8}{st.time_ms:>9.3f}"
              f"{st.expanded:>10}{st.peak_stored:>9}{st.path_length:>9}{st.path_cost:>7g}")
