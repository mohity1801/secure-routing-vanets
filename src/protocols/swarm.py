"""PSO- and GA-based clustering baselines, cited as [49] and [50] in the base
paper's Table 4 comparison.

Both optimise the standard clustering cost of Latiff, Tsimenidis & Sharif
(PIMRC 2007), which is what the PSO-C / GA-clustering literature uses:

    f  = beta * f1 + (1 - beta) * f2
    f1 = max_k  mean_{i in C_k} d(n_i, CH_k)      (intra-cluster compactness)
    f2 = sum_i E(n_i) / sum_k E(CH_k)             (head energy)

Lower is better. Note this cost already contains the intra-cluster term that
CSGD-NET's Eq. 9 omits -- which is why PSO and GA hold more energy than
CSGD-NET late in the run in our reproduction.
"""

from __future__ import annotations

import numpy as np


def clustering_cost(net, ch: np.ndarray, beta: float = 0.5) -> float:
    if ch.size == 0:
        return np.inf
    alive = np.where(net.alive)[0]
    members = alive[~np.isin(alive, ch)]
    if members.size == 0:
        return np.inf

    d = np.linalg.norm(net.pos[members][:, None, :] - net.pos[ch][None, :, :],
                       axis=2)
    nearest = d.argmin(axis=1)
    f1 = 0.0
    for slot in range(ch.size):
        sel = nearest == slot
        if sel.any():
            f1 = max(f1, float(d[sel, slot].mean()))

    e_ch = net.energy[ch].sum()
    f2 = float(net.energy[alive].sum() / e_ch) if e_ch > 0 else np.inf
    return beta * f1 + (1 - beta) * f2


class PSOCluster:
    """Discrete PSO over CH index sets; velocity is a swap probability."""

    name = "PSO"

    def __init__(self, cfg, rng, n_particles: int = 10, iters: int = 20,
                 w: float = 0.7, c1: float = 1.5, c2: float = 1.5):
        self.cfg, self.rng = cfg, rng
        self.n_particles, self.iters = n_particles, iters
        self.w, self.c1, self.c2 = w, c1, c2

    def select_ch(self, net) -> np.ndarray:
        rng = self.rng
        alive = np.where(net.alive)[0]
        if alive.size == 0:
            return np.array([], dtype=int)
        k = min(self.cfg.n_ch, alive.size)

        pos = [rng.choice(alive, size=k, replace=False)
               for _ in range(self.n_particles)]
        cost = np.array([clustering_cost(net, p) for p in pos])
        pbest = [p.copy() for p in pos]
        pbest_cost = cost.copy()
        g = int(cost.argmin())
        gbest, gbest_cost = pos[g].copy(), cost[g]

        for _ in range(self.iters):
            for i in range(self.n_particles):
                cand = pos[i].copy()
                for j in range(k):
                    r = rng.random()
                    if r < self.w * 0.3:                      # inertia: random swap
                        cand[j] = rng.choice(alive)
                    elif r < self.w * 0.3 + self.c1 * 0.2:    # toward personal best
                        cand[j] = pbest[i][j]
                    elif r < self.w * 0.3 + self.c1 * 0.2 + self.c2 * 0.2:
                        cand[j] = gbest[j]                    # toward global best
                if np.unique(cand).size < k:
                    continue
                c = clustering_cost(net, cand)
                pos[i] = cand
                if c < pbest_cost[i]:
                    pbest[i], pbest_cost[i] = cand.copy(), c
                if c < gbest_cost:
                    gbest, gbest_cost = cand.copy(), c
        return gbest


class GACluster:
    """Steady-state GA with tournament selection and uniform crossover."""

    name = "GA"

    def __init__(self, cfg, rng, pop: int = 10, gens: int = 20,
                 p_mut: float = 0.15):
        self.cfg, self.rng = cfg, rng
        self.pop, self.gens, self.p_mut = pop, gens, p_mut

    def select_ch(self, net) -> np.ndarray:
        rng = self.rng
        alive = np.where(net.alive)[0]
        if alive.size == 0:
            return np.array([], dtype=int)
        k = min(self.cfg.n_ch, alive.size)

        pop = [rng.choice(alive, size=k, replace=False) for _ in range(self.pop)]
        cost = np.array([clustering_cost(net, p) for p in pop])

        for _ in range(self.gens):
            # tournament of 2, twice, for the parents
            def pick():
                a, b = rng.integers(self.pop, size=2)
                return pop[a] if cost[a] < cost[b] else pop[b]

            child = np.where(rng.random(k) < 0.5, pick(), pick())
            mut = rng.random(k) < self.p_mut
            if mut.any():
                child = child.copy()
                child[mut] = rng.choice(alive, size=int(mut.sum()))
            if np.unique(child).size < k:
                continue

            c = clustering_cost(net, child)
            worst = int(cost.argmax())
            if c < cost[worst]:
                pop[worst], cost[worst] = child, c

        return pop[int(cost.argmin())]
