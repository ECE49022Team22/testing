"""
Robot-centric local costmap + A* planner for LiDAR obstacle avoidance.

The costmap is rebuilt every scan from the last `memory` seconds of points, in the
sensor frame (0 deg = forward = +y, clockwise). With the sensor stationary that is
fine as-is; once the robot moves, older scans must be shifted by the pose change
before being added (or keep `memory` short).
"""
import heapq
import math
import time
from collections import deque

import numpy as np
from scipy.ndimage import distance_transform_edt

FREE, UNKNOWN, OCCUPIED = 0, 1, 2
LETHAL = math.inf

# 8-connected moves: (d_row, d_col, length)
MOVES = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
         (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (1, 1, math.sqrt(2))]


class LocalCostmap:
    def __init__(self, size_m=8.0, res=0.05, robot_radius=0.25, inflation=0.6,
                 memory=0.5, unknown_cost=2.0, min_range=None):
        self.res = res
        self.n = int(round(size_m / res))
        self.half = size_m / 2
        self.robot_radius = robot_radius
        self.inflation = inflation            # soft-cost band beyond robot_radius (m)
        self.memory = memory
        # returns inside the robot's own footprint are the robot (chassis, mount, cables)
        self.min_range = robot_radius if min_range is None else min_range
        self.unknown_cost = unknown_cost      # extra cost for driving through unseen cells
        self.scans = deque()                  # (t, x, y)
        self.state = np.full((self.n, self.n), UNKNOWN, np.uint8)
        self.cost = np.ones((self.n, self.n), np.float32)
        self.clearance = np.zeros((self.n, self.n), np.float32)

    # ---- frame helpers (row = y, col = x; robot at grid centre) ----
    def to_cell(self, x, y):
        return int((y + self.half) / self.res), int((x + self.half) / self.res)

    def to_xy(self, row, col):
        return (col + 0.5) * self.res - self.half, (row + 0.5) * self.res - self.half

    def _flat(self, x, y):
        col = ((x + self.half) / self.res).astype(np.int64)
        row = ((y + self.half) / self.res).astype(np.int64)
        ok = (col >= 0) & (col < self.n) & (row >= 0) & (row < self.n)
        return row[ok] * self.n + col[ok]

    def update(self, ang, dist, t=None):
        """ang in radians, dist in metres (0-distance/no-return beams already removed)."""
        t = time.time() if t is None else t
        body = dist >= self.min_range
        ang, dist = ang[body], dist[body]
        self.scans.append((t, dist * np.sin(ang), dist * np.cos(ang)))
        while self.scans and self.scans[0][0] < t - self.memory:
            self.scans.popleft()

        state = np.full(self.n * self.n, UNKNOWN, np.uint8)

        # free space: ray-cast the newest scan only
        reach = self.half * math.sqrt(2)
        keep = dist < reach
        a, d = ang[keep], dist[keep]
        if d.size:
            r = np.arange(0, reach, self.res / 2, dtype=np.float32)[None, :].repeat(d.size, 0)
            m = r < (d[:, None] - self.res)
            rr, aa = r[m], np.broadcast_to(a[:, None], r.shape)[m]
            state[self._flat(rr * np.sin(aa), rr * np.cos(aa))] = FREE

        # obstacles: every point still in memory
        for _, x, y in self.scans:
            state[self._flat(x, y)] = OCCUPIED
        self.state = state.reshape(self.n, self.n)

        # inflate: distance (m) from every cell to the nearest obstacle
        occ = self.state == OCCUPIED
        self.clearance = (distance_transform_edt(~occ) * self.res if occ.any()
                          else np.full(occ.shape, np.inf, np.float32))
        beyond = self.clearance - self.robot_radius
        cost = 1.0 + 10.0 * np.clip(1.0 - beyond / self.inflation, 0.0, 1.0) ** 2
        cost[self.state == UNKNOWN] += self.unknown_cost
        cost[beyond < 0] = LETHAL
        self.cost = cost.astype(np.float32)

    def plan(self, goal_xy):
        """A* from the robot (grid centre) to goal_xy (metres, sensor frame).
        Returns (list of (x, y), message)."""
        n = self.n
        start = self.to_cell(0.0, 0.0)
        goal = self.to_cell(*goal_xy)
        if not (0 <= goal[0] < n and 0 <= goal[1] < n):
            return None, "goal outside local map"
        if math.isinf(self.cost[goal]):
            return None, "goal in collision"
        if math.isinf(self.cost[start]):
            return None, "robot in collision (obstacle within robot radius)"
        path = astar(self.cost, start, goal)
        if path is None:
            return None, "no path"
        return [self.to_xy(r, c) for r, c in path], f"path {len(path) * self.res:.1f} m"


def astar(cost, start, goal):
    """8-connected A* over a cost grid (inf = blocked). Step cost = length x mean cell cost."""
    rows, cols = cost.shape
    c = cost.ravel().tolist()
    s, g = start[0] * cols + start[1], goal[0] * cols + goal[1]
    gr, gc = goal
    sqrt2m2 = math.sqrt(2) - 2

    def h(r, col):                          # octile distance; min cell cost is 1
        dr, dc = abs(r - gr), abs(col - gc)
        return dr + dc + sqrt2m2 * min(dr, dc)

    g_score = {s: 0.0}
    came = {}
    closed = bytearray(rows * cols)
    heap = [(h(*start), 0.0, s)]
    while heap:
        _, gu, u = heapq.heappop(heap)
        if closed[u]:
            continue
        if u == g:
            path = [u]
            while u in came:
                u = came[u]
                path.append(u)
            return [divmod(p, cols) for p in reversed(path)]
        closed[u] = 1
        ur, uc = divmod(u, cols)
        cu = c[u]
        for dr, dc, length in MOVES:
            r, col = ur + dr, uc + dc
            if not (0 <= r < rows and 0 <= col < cols):
                continue
            v = r * cols + col
            cv = c[v]
            if closed[v] or cv == LETHAL:
                continue
            if dr and dc and (c[ur * cols + col] == LETHAL or c[r * cols + uc] == LETHAL):
                continue                    # no cutting corners past obstacles
            ng = gu + length * 0.5 * (cu + cv)
            if ng < g_score.get(v, math.inf):
                g_score[v] = ng
                came[v] = u
                heapq.heappush(heap, (ng + h(r, col), ng, v))
    return None
