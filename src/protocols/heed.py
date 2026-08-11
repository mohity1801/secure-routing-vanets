"""HEED -- Hybrid Energy-Efficient Distributed clustering.

Younis & Fahmy, IEEE Trans. Mobile Computing 3(4), 2004. Cited as [48] in the
base paper and used in its Table 4 comparison.

CH election is probabilistic in residual energy, with intra-cluster
communication cost as the secondary tie-break:

    CH_prob = max(C_prob * E_residual / E_max, p_min)

Each iteration a node that has not yet covered itself advertises with that
probability, then doubles CH_prob, until it reaches 1.
"""

from __future__ import annotations

import numpy as np


class HEED:
    name = "HEED"

    def __init__(self, cfg, rng, c_prob: float = 0.05, p_min: float = 1e-4):
        self.cfg = cfg
        self.rng = rng
        self.c_prob = c_prob
        self.p_min = p_min

    def select_ch(self, net) -> np.ndarray:
        cfg, rng = self.cfg, self.rng
        alive = np.where(net.alive)[0]
        if alive.size == 0:
            return np.array([], dtype=int)

        e_max = cfg.initial_energy
        ch_prob = np.maximum(self.c_prob * net.energy[alive] / e_max, self.p_min)

        tentative = np.zeros(alive.size, dtype=bool)
        final = np.zeros(alive.size, dtype=bool)

        for _ in range(int(np.ceil(np.log2(1 / self.p_min))) + 1):
            draw = rng.random(alive.size)
            newly = (~final) & (draw < ch_prob)
            tentative |= newly
            final |= ch_prob >= 1.0
            ch_prob = np.minimum(ch_prob * 2, 1.0)
            if final.all():
                break

        ch = alive[tentative | final]
        if ch.size == 0:
            ch = alive[np.argsort(-net.energy[alive])[:cfg.n_ch]]

        # HEED tie-break: intra-cluster communication cost, normalised by
        # residual energy. Ranking on cost alone is static -- positions do not
        # change, so the same central nodes would win every round and burn out
        # (first node dead by round ~4). Dividing by residual energy restores
        # the rotation that HEED's energy-driven election is meant to provide.
        if ch.size > cfg.n_ch:
            cost = np.linalg.norm(
                net.pos[alive][:, None, :] - net.pos[ch][None, :, :], axis=2
            ).mean(axis=0)
            score = cost / np.maximum(net.energy[ch], 1e-12)
            ch = ch[np.argsort(score)[:cfg.n_ch]]
        return ch
