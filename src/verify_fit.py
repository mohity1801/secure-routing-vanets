"""Can a reasonable implementation reproduce Table 4 without altering any
equation -- by choosing only the frames-per-round the paper never states?

Fits packets_per_round against the LEACH column of Table 4, then checks the
resulting curve shape against LEACH-C and CSGD-NET.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from config import Config                       # noqa: E402
from network import Network                     # noqa: E402
from protocols.csgd_net import CSGDNet          # noqa: E402
from protocols.leach import LEACH, LEACHC       # noqa: E402

TABLE4 = {
    "LEACH":    [0.5, 0.35529, 0.22091, 0.12717, 0.039543],
    "LEACH-C":  [0.5, 0.37,    0.28339, 0.14785, 0.043871],
    "CSGD-NET": [0.5, 0.32982, 0.26095, 0.15064, 0.074354],
}
ROUNDS = [1, 10, 20, 30, 40]


def trace(cfg, cls, seeds=8):
    out = []
    for s in range(seeds):
        net = Network(cfg, np.random.default_rng(s))
        proto = cls(cfg, np.random.default_rng(s + 10_000))
        t = []
        for _ in range(cfg.max_rounds):
            if net.n_alive == 0:
                t.append(0.0)
                continue
            net.run_steady_state(proto.select_ch(net))
            t.append(net.residual_energy)
        out.append(t)
    m = np.mean(out, axis=0)
    return np.array([m[r - 1] for r in ROUNDS])


print("Fitting frames/round to Table 4's LEACH column (E0 = 0.5 J from Table 4)\n")
print(f"  {'frames':>7}{'RMSE vs LEACH':>16}   sampled curve")
best = (None, np.inf)
for f in (12, 14, 16, 18, 20, 22, 24):
    cfg = Config(packets_per_round=f, max_rounds=45)
    got = trace(cfg, LEACH)
    rmse = float(np.sqrt(((got - np.array(TABLE4["LEACH"])) ** 2).mean()))
    print(f"  {f:>7}{rmse:>16.5f}   " + " ".join(f"{v:.3f}" for v in got))
    if rmse < best[1]:
        best = (f, rmse)

print(f"\nBest fit: {best[0]} frames/round, RMSE {best[1]:.5f}\n")

cfg = Config(packets_per_round=best[0], max_rounds=45)
print(f"At {best[0]} frames/round -- ours vs Table 4:\n")
print(f"  {'round':>6}" + "".join(f"{p:>26}" for p in TABLE4))
sims = {n: trace(cfg, c) for n, c in
        (("LEACH", LEACH), ("LEACH-C", LEACHC), ("CSGD-NET", CSGDNet))}
for i, r in enumerate(ROUNDS):
    row = f"  {r:>6}"
    for p in TABLE4:
        row += f"{sims[p][i]:>12.4f} [{TABLE4[p][i]:>8.4f}]"
    print(row)

print("\nPer-column RMSE:")
for p in TABLE4:
    rmse = float(np.sqrt(((sims[p] - np.array(TABLE4[p])) ** 2).mean()))
    print(f"  {p:<10}{rmse:>10.5f}")
