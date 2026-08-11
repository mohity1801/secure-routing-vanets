"""Week-1 deliverable: reproduce Table 4 / Figs. 11-15 of the base paper.

    python3 src/run_baseline.py --seeds 30
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "protocols"))

from config import Config                       # noqa: E402
from network import Network                     # noqa: E402
from protocols.csgd_net import CSGDNet          # noqa: E402
from protocols.heed import HEED                 # noqa: E402
from protocols.leach import LEACH, LEACHC       # noqa: E402
from protocols.swarm import GACluster, PSOCluster  # noqa: E402

PROTOCOLS = {
    "LEACH": LEACH, "LEACH-C": LEACHC, "HEED": HEED,
    "PSO": PSOCluster, "GA": GACluster, "CSGD-NET": CSGDNet,
}

# Table 4 of the paper: mean residual energy at rounds 1/10/20/30/40/50
PAPER_TABLE4 = {
    "LEACH":    {1: 0.5, 10: 0.35529, 20: 0.22091, 30: 0.12717, 40: 0.039543},
    "LEACH-C":  {1: 0.5, 10: 0.37000, 20: 0.28339, 30: 0.14785, 40: 0.043871},
    "CSGD-NET": {1: 0.5, 10: 0.32982, 20: 0.26095, 30: 0.15064, 40: 0.074354,
                 50: 0.0},
    "HEED":     {1: 0.5, 10: 0.41000, 20: 0.32000, 30: 0.23000, 40: 0.140000},
    "PSO":      {1: 0.5, 10: 0.41500, 20: 0.33000, 30: 0.24500, 40: 0.160000},
    "GA":       {1: 0.5, 10: 0.42000, 20: 0.34000, 30: 0.26000, 40: 0.180000},
}


def run_once(cfg: Config, proto_cls, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    net = Network(cfg, rng)
    proto = proto_cls(cfg, np.random.default_rng(seed + 10_000))

    residual, alive, pkts = [], [], []
    fnd = hnd = lnd = None
    for r in range(cfg.max_rounds):
        if net.n_alive == 0:
            break
        ch = proto.select_ch(net)
        net.run_steady_state(ch)

        residual.append(net.residual_energy)
        alive.append(net.n_alive)
        pkts.append(net.packets_to_rsu)

        dead = cfg.n_nodes - net.n_alive
        if fnd is None and dead >= 1:
            fnd = r + 1
        if hnd is None and dead >= cfg.n_nodes // 2:
            hnd = r + 1
        if lnd is None and net.n_alive == 0:
            lnd = r + 1

    return {
        "residual": residual, "alive": alive, "packets": pkts,
        "fnd": fnd, "hnd": hnd, "lnd": lnd or len(residual),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--rounds", type=int, default=60)
    args = ap.parse_args()

    cfg = Config(max_rounds=args.rounds)
    out: dict = {}

    for name, cls in PROTOCOLS.items():
        runs = [run_once(cfg, cls, s) for s in range(args.seeds)]
        n = max(len(r["residual"]) for r in runs)
        pad = lambda r, key, fill: r[key] + [fill] * (n - len(r[key]))  # noqa: E731
        out[name] = {
            "residual": np.mean([pad(r, "residual", 0.0) for r in runs], axis=0).tolist(),
            "alive":    np.mean([pad(r, "alive", 0) for r in runs], axis=0).tolist(),
            "packets":  np.mean([pad(r, "packets", r["packets"][-1]) for r in runs], axis=0).tolist(),
            "fnd":  float(np.mean([r["fnd"] for r in runs])),
            "hnd":  float(np.mean([r["hnd"] for r in runs])),
            "lnd":  float(np.mean([r["lnd"] for r in runs])),
        }

    Path("results").mkdir(exist_ok=True)
    Path("results/baseline.json").write_text(json.dumps(out, indent=2))

    print(f"\n{args.seeds} seeds, {cfg.n_nodes} nodes, "
          f"{cfg.area_x:.0f}x{cfg.area_y:.0f} m, E0={cfg.initial_energy} J\n")
    print("Mean residual energy per node  (paper's Table 4 in brackets)")
    print(f"{'Round':>6} " + "".join(f"{p:>26}" for p in PROTOCOLS))
    for r in (1, 10, 20, 30, 40, 50):
        row = f"{r:>6} "
        for p in PROTOCOLS:
            series = out[p]["residual"]
            got = series[r - 1] if r <= len(series) else 0.0
            ref = PAPER_TABLE4[p].get(r)
            cell = f"{got:.5f}" + (f" [{ref:.5f}]" if ref is not None else " [--]")
            row += f"{cell:>26}"
        print(row)

    print("\nLifetime (rounds)")
    print(f"{'':>10}{'FND':>8}{'HND':>8}{'LND':>8}")
    for p in PROTOCOLS:
        d = out[p]
        print(f"{p:>10}{d['fnd']:>8.1f}{d['hnd']:>8.1f}{d['lnd']:>8.1f}")

    print("\nTotal packets delivered to RSU")
    for p in PROTOCOLS:
        print(f"{p:>10}{out[p]['packets'][-1]:>12.0f}")


if __name__ == "__main__":
    main()
