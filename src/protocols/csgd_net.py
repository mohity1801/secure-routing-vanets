"""CSGD-NET -- faithful reimplementation of the base paper's protocol.

Sellami, Mchergui & Alaya, Cluster Computing 29:16 (2026), Sect. 3.3 and
Algorithm 2.

Cuckoo Search where a "nest" is a candidate CH set. A new candidate is drawn by
Levy flight (Eq. 3-6); if it does not improve, a second candidate is drawn by
Gaussian random walk (Sect. 3.3.1). Fitness is Eq. 9:

    f = E / (E0 * dist(CH_i, RSU))

TWO READINGS OF EQ. 9 -- see docs/reproducibility.md finding 2.

The paper's prose says the objective "targets the minimization of ... the energy
consumption of Cluster Heads relative to overall network energy and the distance
separating the CHs from the RSU", but its symbol list defines E as "the overall
residual energy within the vehicular network".

  mode "A" (literal): E is the whole network's residual energy. That value is
      identical for every candidate CH set within a round, so it cancels and
      Eq. 9 collapses to a pure distance-to-RSU criterion -- node energy plays
      no part in CH selection at all.
  mode "C" (charitable): E is the summed residual energy of the candidate CH
      set, matching the prose's intent that CH energy should matter.

The two are NOT equivalent: mode A gives FND ~12 rounds, mode C ~22. We default
to C because comparing our protocol against a strawman reading would be
worthless, but the choice is ours, not the paper's, and it flatters CSGD-NET.

Either way the printed expression must be MAXIMISED, not minimised: residual
energy is in the numerator and distance in the denominator. Maximising the
printed form is identical to minimising its reciprocal, so this costs no
generality -- it is a presentational error in the source, not an ambiguity.
"""

from __future__ import annotations

import numpy as np
from scipy.special import gamma


def levy(rng, size, beta: float = 1.5) -> np.ndarray:
    """Mantegna's algorithm for Levy-stable steps (Eq. 4)."""
    num = gamma(1 + beta) * np.sin(np.pi * beta / 2)
    den = gamma((1 + beta) / 2) * beta * 2 ** ((beta - 1) / 2)
    sigma = (num / den) ** (1 / beta)
    u = rng.normal(0, sigma, size)
    v = rng.normal(0, 1, size)
    return u / np.abs(v) ** (1 / beta)


class CSGDNet:
    name = "CSGD-NET"

    def __init__(self, cfg, rng):
        self.cfg = cfg
        self.rng = rng

    # --- Eq. 9 ---------------------------------------------------------
    def fitness(self, net, ch: np.ndarray) -> float:
        cfg = self.cfg
        if ch.size == 0:
            return -np.inf
        d = max(net.dist_to_rsu(ch).sum(), 1e-9)
        if cfg.fitness_mode == "A":
            e = net.energy[net.alive].sum()   # constant within a round
        else:
            e = net.energy[ch].sum()
        return float(e / (cfg.initial_energy * d))

    def _pool(self, net) -> np.ndarray:
        """Nodes eligible to be elected. Subclasses narrow this."""
        return np.where(net.alive)[0]

    def select_ch(self, net) -> np.ndarray:
        cfg, rng = self.cfg, self.rng
        alive = self._pool(net)
        if alive.size == 0:
            return np.array([], dtype=int)
        k = min(cfg.n_ch, alive.size)

        # Initial population of NH nests (Eq. 5)
        nests = [rng.choice(alive, size=k, replace=False)
                 for _ in range(cfg.n_cuckoos)]
        fit = np.array([self.fitness(net, n) for n in nests])
        best_i = int(fit.argmax())
        best, best_fit = nests[best_i].copy(), fit[best_i]

        for _ in range(cfg.max_iterations):
            for i in range(cfg.n_cuckoos):
                # 1. Levy-flight candidate (Eq. 6)
                cand = self._walk(net, nests[i], alive, mode="levy")
                f = self.fitness(net, cand)
                if f > fit[i]:
                    nests[i], fit[i] = cand, f
                else:
                    # 2. fall back to a Gaussian walk (Sect. 3.3.1, step 4)
                    cand = self._walk(net, nests[i], alive, mode="gauss")
                    f = self.fitness(net, cand)
                    if f > fit[i]:
                        nests[i], fit[i] = cand, f

            # 3. abandon a fraction pa of the worst nests
            n_drop = int(cfg.pa * cfg.n_cuckoos)
            if n_drop:
                for i in np.argsort(fit)[:n_drop]:
                    nests[i] = rng.choice(alive, size=k, replace=False)
                    fit[i] = self.fitness(net, nests[i])

            j = int(fit.argmax())
            if fit[j] > best_fit:
                best, best_fit = nests[j].copy(), fit[j]

        return best

    def _walk(self, net, nest, alive, mode: str) -> np.ndarray:
        """Move each CH in the nest through space, then snap to the nearest
        alive node -- the continuous CS operators applied to a discrete
        node-selection problem."""
        cfg, rng = self.cfg, self.rng
        pts = net.pos[nest].astype(float)
        if mode == "levy":
            step = cfg.levy_alpha * levy(rng, pts.shape, cfg.levy_beta)
            step *= (net.pos[net.alive].max(axis=0) -
                     net.pos[net.alive].min(axis=0) + 1e-9)
        else:
            scale = cfg.gauss_sigma * max(cfg.area_x, cfg.area_y)
            step = rng.normal(0, scale, pts.shape)
        pts = pts + step
        pts[:, 0] = np.clip(pts[:, 0], 0, cfg.area_x)
        pts[:, 1] = np.clip(pts[:, 1], 0, cfg.area_y)

        d = np.linalg.norm(net.pos[alive][None, :, :] - pts[:, None, :], axis=2)
        out, taken = [], set()
        for row in d:
            for idx in np.argsort(row):
                node = int(alive[idx])
                if node not in taken:
                    taken.add(node)
                    out.append(node)
                    break
        return np.array(out, dtype=int)
