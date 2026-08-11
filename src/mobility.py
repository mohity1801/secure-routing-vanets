"""Mobility models for CHIRP Module 1.

The base paper assumes a static topology (Sect. 3.3: "the topology of the
vehicular network remains static"; Sect. 4.1: "OBU sensor nodes as stationary
entities") and concedes in Sect. 4.3 that this is its main limitation. These
models remove that assumption.

Two scenarios, both self-contained so the project carries no SUMO dependency:

  HighwayMobility  -- multi-lane bidirectional straight road. High relative
                      speed between opposing lanes, so links break fast; this
                      is the stress case for cluster stability.
  UrbanGridMobility -- Manhattan grid. Vehicles follow roads and turn at
                      intersections, so neighbourhoods churn rather than
                      simply passing.

Both wrap vehicles at the boundary to hold the node count constant, which keeps
per-round energy comparable to the static baseline.
"""

from __future__ import annotations

import numpy as np


class StaticMobility:
    """No movement -- reproduces the base paper's assumption."""

    name = "static"

    def __init__(self, cfg, rng):
        self.cfg, self.rng = cfg, rng

    def initial_state(self, n):
        pos = np.column_stack([
            self.rng.uniform(0, self.cfg.area_x, n),
            self.rng.uniform(0, self.cfg.area_y, n),
        ])
        return pos, np.zeros((n, 2))

    def step(self, pos, vel, dt):
        return pos, vel


class HighwayMobility:
    """Straight multi-lane road, half the lanes in each direction.

    Speeds are drawn per vehicle from a truncated normal and held, with small
    per-round jitter -- the standard free-flow highway assumption. Vehicles
    that run off either end re-enter at the opposite end in the same lane.
    """

    name = "highway"

    def __init__(self, cfg, rng):
        self.cfg, self.rng = cfg, rng
        self.lane_w = 3.5

    def initial_state(self, n):
        cfg, rng = self.cfg, self.rng
        lanes = cfg.n_lanes
        lane = rng.integers(0, lanes, n)
        direction = np.where(lane < lanes // 2, 1.0, -1.0)

        x = rng.uniform(0, cfg.area_x, n)
        y = (lane + 0.5) * self.lane_w
        pos = np.column_stack([x, y])

        speed = np.clip(rng.normal(cfg.speed_mean, cfg.speed_std, n),
                        cfg.speed_min, cfg.speed_max)
        vel = np.column_stack([speed * direction, np.zeros(n)])
        return pos, vel

    def step(self, pos, vel, dt):
        cfg, rng = self.cfg, self.rng
        # mild speed jitter, sign (lane direction) preserved
        sign = np.sign(vel[:, 0])
        speed = np.abs(vel[:, 0]) + rng.normal(0, 0.5, pos.shape[0])
        speed = np.clip(speed, cfg.speed_min, cfg.speed_max)
        vel = np.column_stack([speed * sign, np.zeros(pos.shape[0])])

        pos = pos + vel * dt
        pos[:, 0] = np.mod(pos[:, 0], cfg.area_x)      # wrap along the road
        return pos, vel


class UrbanGridMobility:
    """Manhattan grid: roads every `block` metres, turns at intersections.

    Each vehicle travels along one axis until it reaches an intersection, then
    turns with probability p_turn. Speeds are lower and headings change, so
    cluster membership churns without the extreme relative velocities of the
    highway case.
    """

    name = "urban"

    def __init__(self, cfg, rng):
        self.cfg, self.rng = cfg, rng

    def _snap(self, v):
        """Snap a coordinate to the nearest road line."""
        b = self.cfg.block
        return np.round(v / b) * b

    def initial_state(self, n):
        cfg, rng = self.cfg, self.rng
        horizontal = rng.random(n) < 0.5

        free = rng.uniform(0, cfg.area_x, n)
        fixed = self._snap(rng.uniform(0, cfg.area_y, n))
        x = np.where(horizontal, free, fixed)
        y = np.where(horizontal, fixed, free)
        pos = np.column_stack([x, y])

        speed = np.clip(rng.normal(cfg.speed_mean, cfg.speed_std, n),
                        cfg.speed_min, cfg.speed_max)
        direction = rng.choice([-1.0, 1.0], n)
        vel = np.column_stack([
            np.where(horizontal, speed * direction, 0.0),
            np.where(horizontal, 0.0, speed * direction),
        ])
        return pos, vel

    def step(self, pos, vel, dt):
        cfg, rng = self.cfg, self.rng
        b = cfg.block
        new_pos = pos + vel * dt

        moving_x = np.abs(vel[:, 0]) > np.abs(vel[:, 1])
        # An intersection is crossed when the travel coordinate passes a multiple of b
        travel_before = np.where(moving_x, pos[:, 0], pos[:, 1])
        travel_after = np.where(moving_x, new_pos[:, 0], new_pos[:, 1])
        crossed = np.floor(travel_before / b) != np.floor(travel_after / b)
        turning = crossed & (rng.random(pos.shape[0]) < cfg.p_turn)

        if turning.any():
            idx = np.where(turning)[0]
            speed = np.linalg.norm(vel[idx], axis=1)
            newdir = rng.choice([-1.0, 1.0], idx.size)
            was_x = moving_x[idx]
            # turn onto the perpendicular axis, snapping the now-fixed coordinate
            new_pos[idx, 0] = np.where(was_x, self._snap(new_pos[idx, 0]),
                                       new_pos[idx, 0])
            new_pos[idx, 1] = np.where(was_x, new_pos[idx, 1],
                                       self._snap(new_pos[idx, 1]))
            vel[idx, 0] = np.where(was_x, 0.0, speed * newdir)
            vel[idx, 1] = np.where(was_x, speed * newdir, 0.0)

        new_pos[:, 0] = np.mod(new_pos[:, 0], cfg.area_x)
        new_pos[:, 1] = np.mod(new_pos[:, 1], cfg.area_y)
        return new_pos, vel


MODELS = {
    "static": StaticMobility,
    "highway": HighwayMobility,
    "urban": UrbanGridMobility,
}


def build(cfg, rng):
    return MODELS[cfg.scenario](cfg, rng)
