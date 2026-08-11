"""Module 5 evaluation: priority traffic, and priority as an attack surface.

    python3 src/run_priority.py --scenario urban --seeds 12
    python3 src/run_priority.py --scenario urban --seeds 12 --bypass-cost
    python3 src/run_priority.py --scenario urban --seeds 12 --sweep-greed

Three questions, in order:

1. What does priority COST? Aggregation is where the base paper's energy
   saving comes from, and an emergency message cannot be aggregated.
2. What does priority BREAK? A reserved slot is a finite resource and a
   cluster head cannot authenticate the claim on it.
3. What FIXES it, and is trust enough or is the certificate necessary?
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
from scipy.stats import mannwhitneyu

sys.path.insert(0, str(Path(__file__).parent))

from attacks import Adversary                      # noqa: E402
from config import Config                          # noqa: E402
from metrics import deadline_miss, weighted_mean, weighted_percentile  # noqa: E402
from network import Network                        # noqa: E402
from protocols.chirp import CHIRP                  # noqa: E402
from protocols.csgd_net import CSGDNet             # noqa: E402
from run_module1 import SCENARIOS                  # noqa: E402
from trust import TrustEngine                      # noqa: E402

# none  -- emergency slots reserved, but any node may claim one
# trust -- plus the behavioural assertion-rate detector feeding reputation
# auth  -- plus an authenticated EMS role attribute (Module 3's certificate)
DEFENCES = ("none", "trust", "auth")


def run_once(cfg, proto_cls, seed, defence="none"):
    use_trust = defence in ("trust", "auth")
    cfg = Config(**{**cfg.__dict__,
                    "require_ems_auth": defence == "auth",
                    "priority_trust_gate": defence == "trust"})

    net = Network(cfg, np.random.default_rng(seed))
    adv = (Adversary(cfg, np.random.default_rng(seed + 555), cfg.n_nodes)
           if cfg.attacker_frac > 0 else None)
    trust = TrustEngine(cfg, cfg.n_nodes) if use_trust else None
    net.trust = trust

    from traffic import TrafficModel
    net.traffic = TrafficModel(cfg, np.random.default_rng(seed + 999),
                               cfg.n_nodes, adversary=adv)
    try:
        proto = proto_cls(cfg, np.random.default_rng(seed + 10_000), trust=trust)
    except TypeError:
        proto = proto_cls(cfg, np.random.default_rng(seed + 10_000))
    net.association_mode = getattr(proto, "association", "nearest")

    stop_alive = cfg.n_nodes * cfg.eval_alive_frac
    r = 0
    for r in range(cfg.max_rounds):
        if net.n_alive <= stop_alive:
            break
        net.traffic.begin_round(r)
        ch = proto.select_ch(net)
        if getattr(proto, "reelected", True):
            net.run_setup_phase(ch)
        outcome = net.run_steady_state(ch, adversary=adv)
        if trust is not None:
            trust.observe(net, outcome, adv, r)
            trust.observe_priority(net, r)
        net.step_mobility()

    spent = cfg.initial_energy * cfg.n_nodes - float(net.energy.sum())
    res = {
        # what a real ambulance experienced
        "ems_miss": deadline_miss(net.delay_emerg_gen, net.emerg_gen_dropped,
                                  cfg.deadline_slots),
        "ems_delay": weighted_mean(net.delay_emerg_gen),
        "ems_p95": weighted_percentile(net.delay_emerg_gen, 95),
        # ordinary telemetry, which is delay-tolerant by construction
        "norm_delay": weighted_mean(net.delay_norm),
        # what priority handling cost, and who it was spent on
        "prio_mJ": net.priority_energy * 1000,
        "prio_false_pct": (net.priority_energy_false
                           / max(net.priority_energy, 1e-12) * 100),
        "drain_pct": net.priority_energy_false / max(spent, 1e-12) * 100,
        "mJ_per_reading": spent * 1000 / max(net.readings_delivered, 1),
        "pdr": net.readings_delivered / max(net.readings_generated, 1),
        "rounds": float(r + 1),
        "detect": float("nan"), "fpr": float("nan"),
    }

    if trust is not None and adv is not None and adv.attackers.size:
        sc = trust.score()
        liar = np.array([adv.asserts_false_priority(i)
                         for i in range(cfg.n_nodes)])
        honest = ~adv.is_attacker
        res["detect"] = (float((sc[liar] < cfg.trust_gate).mean())
                         if liar.any() else float("nan"))
        res["fpr"] = float((sc[honest] < cfg.trust_gate).mean())
    return res


def mean_of(runs):
    # detect/fpr are NaN for every seed when there are no attackers, which is
    # a legitimate "not applicable", not a numerical problem
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return {k: float(np.nanmean([r[k] for r in runs])) for k in runs[0]}


def base_cfg(args, **kw):
    return Config(max_rounds=args.rounds, ems_frac=args.ems,
                  attack_kinds=("falsepriority",), **SCENARIOS[args.scenario], **kw)


# ---------------------------------------------------------------- experiments
def bypass_cost(args):
    """Q1: what does bypassing aggregation cost, and what does it buy?"""
    print(f"\nAggregation bypass -- {args.scenario}, {args.seeds} seeds, "
          f"{args.ems*100:.0f}% EMS, no attackers\n")
    print(f"{'protocol':<12}{'bypass':>8}{'mJ/reading':>12}{'EMS delay':>11}"
          f"{'EMS p95':>9}{'dl miss':>9}{'rounds':>8}")
    out = {}
    for name, cls in (("CSGD-NET", CSGDNet), ("CHIRP", CHIRP)):
        base = None
        for label, slots in (("off", 0), ("on", 1)):
            cfg = base_cfg(args, emergency_slots=slots, attacker_frac=0.0)
            m = mean_of([run_once(cfg, cls, s) for s in range(args.seeds)])
            out[f"{name}|{label}"] = m
            delta = "" if base is None else f"  ({(m['mJ_per_reading']/base-1)*100:+.1f}%)"
            if base is None:
                base = m["mJ_per_reading"]
            print(f"{name:<12}{label:>8}{m['mJ_per_reading']:>12.4f}"
                  f"{m['ems_delay']:>11.2f}{m['ems_p95']:>9.1f}"
                  f"{m['ems_miss']:>9.3f}{m['rounds']:>8.1f}{delta}")
    return out


def defence_sweep(args):
    """Q2 and Q3: the attack, and whether trust or the certificate stops it."""
    print(f"\nFalse-priority attack -- {args.scenario}, {args.seeds} seeds, "
          f"{args.ems*100:.0f}% EMS, CHIRP")
    print(f"greed = {Config().falsepriority_rate:.2f} "
          f"(attacker asserts on this fraction of its own readings)\n")
    print(f"{'att%':>5}{'defence':<9}{'EMS dl miss':>13}{'EMS delay':>11}"
          f"{'prio mJ':>10}{'false%':>8}{'net drain%':>12}"
          f"{'detect':>9}{'FPR':>7}")
    out = {}
    for frac in (0.0, 0.05, 0.10, 0.20, 0.30, 0.40):
        for d in DEFENCES:
            cfg = base_cfg(args, attacker_frac=frac)
            m = mean_of([run_once(cfg, CHIRP, s, d) for s in range(args.seeds)])
            out[f"{frac}|{d}"] = m
            det = "-" if np.isnan(m["detect"]) else f"{m['detect']:.3f}"
            fpr = "-" if np.isnan(m["fpr"]) else f"{m['fpr']:.3f}"
            print(f"{frac*100:>5.0f}{d:<9}{m['ems_miss']:>13.3f}"
                  f"{m['ems_delay']:>11.2f}{m['prio_mJ']:>10.1f}"
                  f"{m['prio_false_pct']:>8.0f}{m['drain_pct']:>12.2f}"
                  f"{det:>9}{fpr:>7}")
        print()

    # headline significance at 20% attackers
    cfg = base_cfg(args, attacker_frac=0.20)
    a = [run_once(cfg, CHIRP, s, "auth")["ems_miss"] for s in range(args.seeds)]
    b = [run_once(cfg, CHIRP, s, "none")["ems_miss"] for s in range(args.seeds)]
    _, p = mannwhitneyu(a, b, alternative="less")
    print(f"EMS deadline-miss at 20% attackers: auth {np.mean(a):.3f} vs "
          f"undefended {np.mean(b):.3f}  (p={p:.4g})")
    return out


def greed_sweep(args):
    """The stealth/impact trade-off a behavioural detector cannot escape."""
    genuine = Config().ems_msgs_per_round / Config().packets_per_round
    print(f"\nAttacker greed sweep -- {args.scenario}, {args.seeds} seeds, "
          f"20% attackers, CHIRP")
    print(f"a genuine EMS vehicle asserts at rate {genuine:.2f}; "
          f"the detector flags above {Config().priority_flag_rate:.2f}\n")
    print(f"{'greed':>7}{'defence':<9}{'EMS dl miss':>13}{'net drain%':>12}"
          f"{'detect':>9}{'FPR':>7}")
    out = {}
    for greed in (0.18, 0.30, 0.50, 0.75, 1.00):
        for d in ("none", "trust", "auth"):
            cfg = base_cfg(args, attacker_frac=0.20, falsepriority_rate=greed)
            m = mean_of([run_once(cfg, CHIRP, s, d) for s in range(args.seeds)])
            out[f"{greed}|{d}"] = m
            det = "-" if np.isnan(m["detect"]) else f"{m['detect']:.3f}"
            fpr = "-" if np.isnan(m["fpr"]) else f"{m['fpr']:.3f}"
            print(f"{greed:>7.2f}{d:<9}{m['ems_miss']:>13.3f}"
                  f"{m['drain_pct']:>12.2f}{det:>9}{fpr:>7}")
        print()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=list(SCENARIOS), default="urban")
    ap.add_argument("--seeds", type=int, default=12)
    ap.add_argument("--rounds", type=int, default=60)
    ap.add_argument("--ems", type=float, default=0.05)
    ap.add_argument("--bypass-cost", action="store_true")
    ap.add_argument("--sweep-greed", action="store_true")
    args = ap.parse_args()

    if args.bypass_cost:
        out, tag = bypass_cost(args), "bypass"
    elif args.sweep_greed:
        out, tag = greed_sweep(args), "greed"
    else:
        out, tag = defence_sweep(args), "defence"

    Path("results").mkdir(exist_ok=True)
    Path(f"results/priority_{tag}_{args.scenario}.json").write_text(
        json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
