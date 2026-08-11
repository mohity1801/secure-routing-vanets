"""LEACH (Heinzelman et al., 2000) and LEACH-C (centralised variant).

LEACH: each node self-elects with probability T(n) (Eq. 1 of the base paper),
re-electing so that every node is CH once per 1/p rounds.

LEACH-C: the RSU knows every node's energy and position, and picks the CH set
that minimises total member->CH distance among nodes with above-average energy.
"""

from __future__ import annotations

import numpy as np


class LEACH:
    name = "LEACH"

    def __init__(self, cfg, rng):
        self.cfg = cfg
        self.rng = rng
        self.p = cfg.ch_percent
        self.last_ch_round = np.full(cfg.n_nodes, -10**9)

    def select_ch(self, net) -> np.ndarray:
        cfg, r = self.cfg, net.round
        period = int(round(1 / self.p))
        eligible = net.alive & (r - self.last_ch_round >= period)
        denom = 1 - self.p * (r % period)
        thresh = self.p / denom if denom > 0 else 1.0
        draw = self.rng.random(cfg.n_nodes)
        ch = np.where(eligible & (draw < thresh))[0]
        if ch.size == 0:                       # guarantee progress
            alive = np.where(net.alive)[0]
            if alive.size:
                ch = self.rng.choice(alive, size=min(cfg.n_ch, alive.size),
                                     replace=False)
        self.last_ch_round[ch] = r
        return ch


class LEACHC:
    name = "LEACH-C"

    def __init__(self, cfg, rng):
        self.cfg = cfg
        self.rng = rng

    def select_ch(self, net) -> np.ndarray:
        cfg = self.cfg
        alive = np.where(net.alive)[0]
        if alive.size == 0:
            return np.array([], dtype=int)
        avg_e = net.energy[alive].mean()
        pool = alive[net.energy[alive] >= avg_e]
        if pool.size < cfg.n_ch:
            pool = alive
        k = min(cfg.n_ch, pool.size)

        # Simulated-annealing-lite: greedy k-medoid style seeding, then swap.
        best = self.rng.choice(pool, size=k, replace=False)
        best_cost = self._cost(net, alive, best)
        for _ in range(60):
            cand = best.copy()
            cand[self.rng.integers(k)] = self.rng.choice(pool)
            if np.unique(cand).size < k:
                continue
            c = self._cost(net, alive, cand)
            if c < best_cost:
                best, best_cost = cand, c
        return best

    @staticmethod
    def _cost(net, alive, ch) -> float:
        d = np.linalg.norm(net.pos[alive][:, None, :] - net.pos[ch][None, :, :],
                           axis=2)
        return float((d.min(axis=1) ** 2).sum())
