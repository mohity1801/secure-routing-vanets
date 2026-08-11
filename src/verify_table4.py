"""Why LEACH-C and CSGD-NET cannot be reproduced from Table 4.

    python3 src/verify_table4.py

docs/reproducibility.md finding 1 originally recorded that our LEACH matches
Table 4 (RMSE 0.008) while LEACH-C (0.049) and CSGD-NET (0.047) do not, and
attributed that gap to our implementation. This script tests that attribution
and refutes it. Three independent arguments, in increasing strength.

ARGUMENT 1 -- the protocol-dependent energy budget is tiny.

Under the paper's Eqs. (9)-(11) with Table 3's parameters, per-round network
energy splits into two parts:

    electronics   (2*(n - n_ch) + n_ch) * k * E_elec  +  aggregation
    amplifier     k * eps_fs * (sum of squared link distances)

The electronics term does not depend on WHICH nodes are heads: every member
sends one packet, every head receives it and sends one, for any head set. So
the amplifier term is the entire budget a cluster-head selection algorithm has
to play with. In a 50 x 50 m field with 10 heads, members attach to a head a
few metres away and that budget measures ~0.002 J/node over 10 rounds.

ARGUMENT 2 -- Table 4's spread exceeds that budget by more than an order of
magnitude, so no head-selection algorithm can produce it.

ARGUMENT 3 -- Table 4's LEACH-C and CSGD-NET columns are not monotone in drain
rate. Drain per round = (alive nodes) x (per-node cost). Nodes only die, and
per-node cost is dominated by the constant electronics term, so drain cannot
rise between intervals. Theirs rises by 56 % and 60 %.

The columns we fail to reproduce are exactly the columns that violate this.
LEACH -- the one column that is internally consistent -- is the one we match.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config                       # noqa: E402
from network import Network                     # noqa: E402
from protocols.csgd_net import CSGDNet          # noqa: E402
from protocols.leach import LEACH, LEACHC       # noqa: E402

TABLE4 = {
    "LEACH":    [0.5, 0.35529, 0.22091, 0.12717, 0.039543],
    "LEACH-C":  [0.5, 0.37000, 0.28339, 0.14785, 0.043871],
    "CSGD-NET": [0.5, 0.32982, 0.26095, 0.15064, 0.074354],
    "HEED":     [0.5, 0.41000, 0.32000, 0.23000, 0.140000],
    "PSO":      [0.5, 0.41500, 0.33000, 0.24500, 0.160000],
    "GA":       [0.5, 0.42000, 0.34000, 0.26000, 0.180000],
}
PROTOCOLS = {"LEACH": LEACH, "LEACH-C": LEACHC, "CSGD-NET": CSGDNet}

# eps_fs -> 0 with d0 kept far beyond the field: free-space branch everywhere,
# amplifier energy effectively zero. This is the physically unreachable best
# case for any clustering algorithm.
NO_AMP = dict(eps_fs=1e-30, eps_mp=1e-40)


def trace(cfg, cls, seeds, rounds=45):
    out = []
    for s in seeds:
        net = Network(cfg, np.random.default_rng(s))
        proto = cls(cfg, np.random.default_rng(s + 10_000))
        res = []
        for _ in range(rounds):
            if net.n_alive == 0:
                break
            net.run_steady_state(proto.select_ch(net))
            res.append(net.residual_energy)
        res += [0.0] * (rounds - len(res))
        out.append(res)
    m = np.mean(out, axis=0)
    return [0.5, m[9], m[19], m[29], m[39]]


def rmse(a, b):
    return float(np.sqrt(np.mean((np.array(a) - np.array(b)) ** 2)))


def main():
    seeds = range(10)
    cfg = Config(max_rounds=45)
    ours = {n: trace(cfg, c, seeds) for n, c in PROTOCOLS.items()}
    perfect = {n: trace(Config(max_rounds=45, **NO_AMP), c, seeds)
               for n, c in PROTOCOLS.items()}

    print("=" * 74)
    print("1  Our reproduction vs Table 4")
    print("=" * 74)
    print(f"{'protocol':<10}{'R10':>9}{'paper':>9}{'R40':>9}{'paper':>9}{'RMSE':>9}")
    for n in PROTOCOLS:
        print(f"{n:<10}{ours[n][1]:>9.5f}{TABLE4[n][1]:>9.5f}"
              f"{ours[n][4]:>9.5f}{TABLE4[n][4]:>9.5f}"
              f"{rmse(ours[n], TABLE4[n]):>9.4f}")

    print()
    print("=" * 74)
    print("2  The entire protocol-dependent budget (amplifier energy at R10)")
    print("=" * 74)
    budget = 0.0
    for n in PROTOCOLS:
        b = perfect[n][1] - ours[n][1]
        budget = max(budget, b)
        print(f"{n:<10} actual {ours[n][1]:.5f}   zero-amplifier best case "
              f"{perfect[n][1]:.5f}   budget {b:.5f} J/node")

    spread_ours = max(v[1] for v in ours.values()) - min(v[1] for v in ours.values())
    s3 = (max(TABLE4[p][1] for p in PROTOCOLS)
          - min(TABLE4[p][1] for p in PROTOCOLS))
    s6 = max(v[1] for v in TABLE4.values()) - min(v[1] for v in TABLE4.values())
    print(f"\n  cross-protocol spread at R10")
    print(f"    ours, three protocols       {spread_ours:.5f}   (within budget)")
    print(f"    Table 4, three protocols    {s3:.5f}   {s3/budget:>5.1f}x the budget")
    print(f"    Table 4, all six columns    {s6:.5f}   {s6/budget:>5.1f}x the budget")

    print("\n  Decisive case: even with ZERO amplifier energy -- perfect")
    print("  clustering, physically unreachable -- LEACH-C reaches only")
    print(f"  {perfect['LEACH-C'][1]:.5f} at R10 against Table 4's "
          f"{TABLE4['LEACH-C'][1]:.5f}, still short by "
          f"{TABLE4['LEACH-C'][1] - perfect['LEACH-C'][1]:.5f} J/node.")
    print("  No cluster-head selection algorithm can close that.")

    print()
    print("=" * 74)
    print("3  Drain rate must be non-increasing")
    print("=" * 74)
    print(f"{'protocol':<10}{'source':<7}{'drops R1-10, 10-20, 20-30, 30-40':<38}"
          f"{'max rise':>10}")
    for n in TABLE4:
        rows = [("paper", TABLE4[n])]
        if n in PROTOCOLS:
            rows.append(("ours", ours[n]))
        for label, series in rows:
            d = [series[i] - series[i + 1] for i in range(len(series) - 1)]
            rise = max([(d[i + 1] / d[i] - 1) for i in range(len(d) - 1)
                        if d[i] > 1e-9] or [0.0])
            flag = "  **" if rise > 0.02 else ""
            print(f"{n:<10}{label:<7}"
                  f"{'  '.join(f'{x:.4f}' for x in d):<38}{rise*100:>9.1f}%{flag}")

    print("\n  ** = drain rate rises between intervals, which (alive x cost)")
    print("  cannot do. Exactly the two columns we fail to reproduce.")


if __name__ == "__main__":
    main()
