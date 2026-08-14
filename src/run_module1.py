"""Module 1 evaluation: mobility-aware multi-metric CH election.

    python3 src/run_module1.py --scenario highway --seeds 20

Every protocol runs on identical mobility traces (same seed -> same road,
same speeds), so differences come from CH selection alone. CHIRP reuses
CSGD-NET's Cuckoo Search engine unchanged and differs only in the objective.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import mannwhitneyu

sys.path.insert(0, str(Path(__file__).parent))

from config import Config                          # noqa: E402
from network import Network                        # noqa: E402
from protocols.chirp import CHIRP                  # noqa: E402
from protocols.csgd_net import CSGDNet             # noqa: E402
from protocols.heed import HEED                    # noqa: E402
from protocols.leach import LEACH, LEACHC          # noqa: E402
from protocols.swarm import GACluster, PSOCluster  # noqa: E402

PROTOCOLS = {
    "LEACH": LEACH, "LEACH-C": LEACHC, "HEED": HEED,
    "PSO": PSOCluster, "GA": GACluster, "CSGD-NET": CSGDNet, "CHIRP": CHIRP,
}

# The fitness terms the ablation drops, and the metrics the CHIRP-vs-baseline
# comparison reports. Module-level so run_radio.py's robustness re-runs share
# one definition with the tables in docs/module1.md rather than copying them --
# two copies only stay mirrors of each other by textual coincidence.
ABLATION_TERMS = ["w_energy", "w_rsu", "w_intra", "w_let", "w_balance"]

COMPARE_METRICS = (("fnd", "higher"), ("hnd", "higher"),
                   ("mj_per_reading", "lower"), ("orphan", "lower"),
                   ("intra", "lower"))

SCENARIOS = {
    # Highway: 1 km of 6-lane bidirectional road, RSUs every 200 m.
    # Opposing lanes close at up to 66 m/s, so links break fastest here.
    "highway": dict(scenario="highway", area_x=1000.0, area_y=21.0,
                    n_lanes=6, n_rsus=5, tx_range=100.0,
                    speed_mean=25.0, speed_std=4.0, speed_min=8.0,
                    speed_max=33.0, initial_energy=0.5, n_nodes=100),
    # Urban: 600 m Manhattan grid, 200 m blocks, RSUs at the quadrant centres.
    "urban":   dict(scenario="urban", area_x=600.0, area_y=600.0,
                    block=200.0, p_turn=0.35, n_rsus=9, tx_range=150.0,
                    speed_mean=12.0, speed_std=3.0, speed_min=4.0,
                    speed_max=18.0, initial_energy=0.5, n_nodes=100),
}


def ablation_weights(full: dict, drop: str | None) -> dict:
    """Zero one fitness term and renormalise the rest to the original total.

    Shared with run_radio.py's ablation so both build the SAME objective: the
    ablation is only meaningful as a comparison against the full weights, and
    two copies of this arithmetic could silently diverge.
    """
    w = dict(full)
    if drop:
        w[drop] = 0.0
    s = sum(w.values()) or 1.0
    return {k: v / s * sum(full.values()) for k, v in w.items()}


def compare_runs(runs_a: list, runs_b: list) -> dict:
    """Mann-Whitney U over COMPARE_METRICS, one-sided in the direction the
    metric improves. Returns {metric: {a, b, delta_pct, p}}."""
    out = {}
    for metric, better in COMPARE_METRICS:
        a = [r[metric] for r in runs_a]
        b = [r[metric] for r in runs_b]
        alt = "greater" if better == "higher" else "less"
        _, p = mannwhitneyu(a, b, alternative=alt)
        ma, mb = float(np.mean(a)), float(np.mean(b))
        out[metric] = {"a": ma, "b": mb, "p": float(p),
                       "delta_pct": (ma - mb) / mb * 100 if mb else float("nan")}
    return out


def run_once(cfg, proto_cls, seed):
    # Same seed for the network across protocols => identical mobility trace.
    net = Network(cfg, np.random.default_rng(seed))
    proto = proto_cls(cfg, np.random.default_rng(seed + 10_000))
    # Baselines associate members to the nearest head; CHIRP declares "let".
    net.association_mode = getattr(proto, "association", "nearest")

    fnd = hnd = lnd = None
    elections = 0

    for r in range(cfg.max_rounds):
        if net.n_alive == 0:
            break
        ch = proto.select_ch(net)
        # Baselines re-elect unconditionally; CHIRP reports when it did.
        if getattr(proto, "reelected", True):
            elections += 1
            net.run_setup_phase(ch)

        net.run_steady_state(ch)
        net.step_mobility()

        dead = cfg.n_nodes - net.n_alive
        if fnd is None and dead >= 1:
            fnd = r + 1
        if hnd is None and dead >= cfg.n_nodes // 2:
            hnd = r + 1
        if lnd is None and net.n_alive == 0:
            lnd = r + 1

    rounds = max(len(net.orphan_rate), 1)
    spent = cfg.n_nodes * cfg.initial_energy - net.energy.sum()
    # Energy per delivered reading. Unlike raw packet count this cannot be
    # gamed by orphaning nodes onto direct-to-RSU links: those deliver data
    # but cost far more energy, so the ratio gets worse, not better.
    per_reading = spent / max(net.packets_offered, 1) * 1e3   # mJ
    return {
        "fnd": fnd or cfg.max_rounds,
        "hnd": hnd or cfg.max_rounds,
        "lnd": lnd or cfg.max_rounds,
        "mj_per_reading": float(per_reading),
        "orphan": float(np.mean(net.orphan_rate)),
        "intra": float(np.mean(net.intra_dist)),
        "elections": elections / rounds,
        "residual": net.residual_energy,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=list(SCENARIOS), default="highway")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--rounds", type=int, default=120)
    ap.add_argument("--sweep-assoc", action="store_true",
                    help="sweep the LET/proximity association blend for CHIRP")
    ap.add_argument("--ablate", action="store_true",
                    help="drop each fitness term in turn")
    args = ap.parse_args()

    if args.ablate:
        # Zero one fitness term at a time, renormalise the rest, and measure.
        # This is what separates "the multi-metric objective helps" from
        # "the Cuckoo Search engine helps" -- the engine is identical to
        # CSGD-NET's throughout.
        terms = ABLATION_TERMS
        base = Config(max_rounds=args.rounds, **SCENARIOS[args.scenario])
        full = {t: getattr(base, t) for t in terms}

        print(f"\nFitness ablation, {args.scenario}, {args.seeds} seeds")
        print("Each row drops one term and renormalises the others.\n")
        print(f"{'dropped':<12}{'FND':>7}{'HND':>7}{'mJ/reading':>13}"
              f"{'orphan%':>10}{'intra m':>9}{'elect/rd':>10}")

        rows = {}
        for drop in [None] + terms:
            w = ablation_weights(full, drop)
            cfg = Config(max_rounds=args.rounds, **w, **SCENARIOS[args.scenario])
            runs = [run_once(cfg, CHIRP, sd) for sd in range(args.seeds)]
            m = {k: float(np.mean([r[k] for r in runs])) for k in runs[0]}
            rows[drop or "none (full)"] = m
            label = "none (full)" if drop is None else drop.replace("w_", "")
            print(f"{label:<12}{m['fnd']:>7.1f}{m['hnd']:>7.1f}"
                  f"{m['mj_per_reading']:>13.4f}{m['orphan']*100:>10.1f}"
                  f"{m['intra']:>9.1f}{m['elections']:>10.2f}")

        Path("results").mkdir(exist_ok=True)
        Path(f"results/module1_ablation_{args.scenario}.json").write_text(
            json.dumps(rows, indent=2))
        return

    if args.sweep_assoc:
        print(f"\nAssociation blend sweep, {args.scenario}, "
              f"{args.seeds} seeds  (alpha=0 nearest, 1 longest-lived)\n")
        print(f"{'alpha':>7}{'FND':>8}{'HND':>8}{'mJ/reading':>13}"
              f"{'orphan%':>10}{'intra m':>9}{'elect/rd':>10}")
        for a in (0.0, 0.25, 0.5, 0.75, 1.0):
            cfg = Config(max_rounds=args.rounds, assoc_let_weight=a,
                         **SCENARIOS[args.scenario])
            runs = [run_once(cfg, CHIRP, s) for s in range(args.seeds)]
            m = {k: float(np.mean([r[k] for r in runs])) for k in runs[0]}
            print(f"{a:>7.2f}{m['fnd']:>8.1f}{m['hnd']:>8.1f}"
                  f"{m['mj_per_reading']:>13.4f}{m['orphan']*100:>10.1f}"
                  f"{m['intra']:>9.1f}{m['elections']:>10.2f}")
        return

    cfg = Config(max_rounds=args.rounds, **SCENARIOS[args.scenario])
    print(f"\nScenario: {args.scenario}  |  {cfg.n_nodes} nodes, "
          f"{cfg.area_x:.0f}x{cfg.area_y:.0f} m, {cfg.n_rsus} RSU(s), "
          f"tx_range {cfg.tx_range:.0f} m, E0 {cfg.initial_energy} J")
    print(f"{args.seeds} seeds, {args.rounds} rounds max, "
          f"{cfg.round_duration}s of movement per round\n")

    raw, out = {}, {}
    for name, cls in PROTOCOLS.items():
        runs = [run_once(cfg, cls, s) for s in range(args.seeds)]
        raw[name] = runs
        out[name] = {k: float(np.mean([r[k] for r in runs])) for k in runs[0]}

    hdr = (f"{'protocol':<10}{'FND':>7}{'HND':>7}{'LND':>7}{'mJ/reading':>12}"
           f"{'orphan%':>9}{'intra m':>9}{'elect/rd':>10}")
    print(hdr)
    print("-" * len(hdr))
    for name in PROTOCOLS:
        d = out[name]
        print(f"{name:<10}{d['fnd']:>7.1f}{d['hnd']:>7.1f}{d['lnd']:>7.1f}"
              f"{d['mj_per_reading']:>12.4f}{d['orphan']*100:>9.1f}"
              f"{d['intra']:>9.1f}{d['elections']:>10.2f}")

    # CHIRP vs the base paper's protocol, with significance
    print(f"\nCHIRP vs CSGD-NET  ({args.seeds} seeds, Mann-Whitney U)")
    for metric, st in compare_runs(raw["CHIRP"], raw["CSGD-NET"]).items():
        sig = "significant" if st["p"] < 0.05 else "not significant"
        print(f"  {metric:<10} CHIRP {st['a']:>9.2f}  CSGD-NET {st['b']:>9.2f}  "
              f"{st['delta_pct']:>+7.1f}%   p={st['p']:.4f}  {sig}")

    Path("results").mkdir(exist_ok=True)
    Path(f"results/module1_{args.scenario}.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
