"""Module 5 evaluation: priority traffic, and priority as an attack surface.

    python3 src/run_priority.py --scenario urban --seeds 12
    python3 src/run_priority.py --scenario urban --seeds 12 --bypass-cost
    python3 src/run_priority.py --scenario urban --seeds 12 --sweep-greed
    python3 src/run_priority.py --scenario urban --seeds 6  --coverage-latency
    python3 src/run_priority.py --scenario urban --seeds 16 --crypto-decomp

Three questions, in order:

1. What does priority COST? Aggregation is where the base paper's energy
   saving comes from, and an emergency message cannot be aggregated.
2. What does priority BREAK? A reserved slot is a finite resource and a
   cluster head cannot authenticate the claim on it.
3. What FIXES it, and is trust enough or is the certificate necessary?

Two of these answer questions that come BEFORE those three:

    --coverage-latency  why priority needs a bypass at all. Runs all seven
                        protocols with the reservation disabled, so every
                        reading is aggregated, and shows that emergency
                        deadline-miss tracks orphan rate inversely.
    --crypto-decomp     what the crypto layer actually costs, separated from
                        what the bypass costs, with paired significance tests.
                        The headline ratios in --bypass-cost mix the two,
                        because the aggregate MAC is charged in both arms.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
from scipy.stats import mannwhitneyu, wilcoxon

sys.path.insert(0, str(Path(__file__).parent))

from attacks import Adversary                      # noqa: E402
from config import Config                          # noqa: E402
from metrics import deadline_miss, weighted_mean, weighted_percentile  # noqa: E402
from network import Network                        # noqa: E402
from protocols.chirp import CHIRP                  # noqa: E402
from protocols.csgd_net import CSGDNet             # noqa: E402
from run_module1 import PROTOCOLS, SCENARIOS       # noqa: E402
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


def coverage_latency(args):
    """Why a bypass is needed at all: coverage and emergency latency oppose.

    Runs every protocol with the reservation DISABLED (emergency_slots = 0), so
    every reading is aggregated and class-2 traffic gets no special treatment.
    What comes out is the motivating result for the whole of Module 5: emergency
    deadline-miss tracks orphan rate almost perfectly INVERSELY.

    The mechanism is that orphans skip fusion. An orphan sends straight to the
    RSU and waits for nobody, so it is the lowest-delay path in the network. A
    protocol that is good at coverage absorbs would-be orphans into clusters,
    which makes clusters larger, frames longer and every reading in them later --
    and removes the accidental fast path that orphaning provided.

    Read it as a negative result about our own work: CHIRP has the best coverage
    and therefore the worst, or near-worst, emergency latency.

    No adversary and no trust engine here -- this is about the architecture, not
    about attack. `sig_bits` never applies because nothing is ever bypassed.
    """
    cfg_ref = Config()
    print(f"\nCoverage vs emergency latency -- {args.scenario}, {args.seeds} "
          f"seeds, {args.ems*100:.0f}% EMS")
    print(f"reservation DISABLED (emergency_slots = 0): every reading is "
          f"aggregated, deadline = {cfg_ref.deadline_slots:.0f} slots\n")
    print(f"  {'protocol':<11}{'orphan %':>10}{'mean delay':>12}"
          f"{'EMS dl-miss':>13}{'mean cluster':>14}")

    out = {}
    for name, cls in PROTOCOLS.items():
        rows = []
        for s in range(args.seeds):
            cfg = base_cfg(args, emergency_slots=0, attacker_frac=0.0)
            net = Network(cfg, np.random.default_rng(s))
            from traffic import TrafficModel
            net.traffic = TrafficModel(cfg, np.random.default_rng(s + 999),
                                       cfg.n_nodes)
            proto = cls(cfg, np.random.default_rng(s + 10_000))
            net.association_mode = getattr(proto, "association", "nearest")
            for r in range(cfg.max_rounds):
                if net.n_alive == 0:
                    break
                net.traffic.begin_round(r)
                ch = proto.select_ch(net)
                if getattr(proto, "reelected", True):
                    net.run_setup_phase(ch)
                net.run_steady_state(ch)
                net.step_mobility()
            rows.append((
                float(np.mean(net.orphan_rate)) * 100,
                weighted_mean(net.delay_norm),
                deadline_miss(net.delay_emerg_gen, net.emerg_gen_dropped,
                              cfg.deadline_slots),
                float(np.mean(net.n_clusters)),
            ))
        m = np.nanmean(np.array(rows), axis=0)
        out[name] = {"orphan_pct": m[0], "norm_delay": m[1],
                     "ems_miss": m[2], "mean_clusters": m[3]}
        print(f"  {name:<11}{m[0]:>10.1f}{m[1]:>12.2f}{m[2]:>13.3f}{m[3]:>14.1f}")

    order = sorted(out, key=lambda k: -out[k]["orphan_pct"])
    print("\n  sorted by orphan rate, most-stranded first:")
    print("  " + "  >  ".join(f"{k} ({out[k]['ems_miss']:.3f})" for k in order))
    print("  Deadline-miss rises as orphan rate falls: the protocol that strands"
          " the most nodes")
    print("  has the BEST emergency latency. The relationship is strong across"
          " the range, but")
    print("  protocols that already orphan almost nothing are indistinguishable"
          " from each other --")
    print("  once the fast path is gone it cannot be lost twice.")
    return out


def crypto_decomposition(args):
    """What the crypto layer costs, separated from what the bypass costs.

    --bypass-cost reports a ratio that mixes two effects, because the aggregate
    MAC is charged in BOTH arms: turning the bypass off does not turn crypto
    off. This decomposes them, adding one thing at a time.

    Paired Wilcoxon across seeds, because each seed gives the same mobility
    trace in both arms -- an unpaired test would throw that away.

    The result is the opposite of what Module 5 predicted before Module 3b was
    measured. The transmission cost of the whole crypto layer is under 2 %, and
    the per-message signature is statistically undetectable: 576 bits ride on a
    transmission already carrying a 6400-bit payload plus a fixed electronics
    term, and class-2 traffic is under 1 % of all readings. Where the cost
    actually falls is COMPUTATION -- see docs/module3b.md, which the simulator
    does not charge.
    """
    ref = Config()
    steps = [("no crypto, no bypass", 0, 0, 0),
             ("+ aggregate MAC", 0, ref.mac_bits, 0),
             ("+ bypass, no signature", 0, ref.mac_bits, 1),
             ("+ per-message signature", ref.sig_bits, ref.mac_bits, 1)]

    print(f"\nCrypto cost decomposition -- {args.scenario}, {args.seeds} seeds, "
          f"{args.ems*100:.0f}% EMS, CHIRP")
    print(f"mJ per delivered reading; each row adds one thing to the row above; "
          f"paired Wilcoxon\n")
    print(f"  {'configuration':<26}{'mJ/reading':>12}{'delta':>10}"
          f"{'cumulative':>12}{'p':>10}")

    out, base, prev = {}, None, None
    for name, sig, mac, slots in steps:
        cfg = base_cfg(args, sig_bits=sig, mac_bits=mac,
                       emergency_slots=slots, attacker_frac=0.0)
        v = np.array([run_once(cfg, CHIRP, s)["mJ_per_reading"]
                      for s in range(args.seeds)])
        m = float(v.mean())
        rec = {"mJ_per_reading": m, "sig_bits": sig, "mac_bits": mac,
               "emergency_slots": slots}
        if prev is None:
            base = m
            print(f"  {name:<26}{m:>12.4f}{'--':>10}{'--':>12}{'--':>10}")
        else:
            # identical vectors would make wilcoxon raise; report p = 1.0
            p = 1.0 if np.allclose(v, prev) else float(wilcoxon(v, prev).pvalue)
            rec.update({"delta_pct": (m / prev.mean() - 1) * 100,
                        "cumulative_pct": (m / base - 1) * 100, "p": p})
            print(f"  {name:<26}{m:>12.4f}{rec['delta_pct']:>9.2f}%"
                  f"{rec['cumulative_pct']:>11.2f}%{p:>10.4f}")
        out[name] = rec
        prev = v

    print("\n  Report the per-message signature as 'we could not detect a cost'"
          " -- not as 'free'.")
    print("  Absence of a detected effect is not proof of no effect at this"
          " seed count.")
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
    ap.add_argument("--coverage-latency", action="store_true",
                    help="all protocols, reservation disabled: why a bypass is needed")
    ap.add_argument("--crypto-decomp", action="store_true",
                    help="separate the crypto cost from the bypass cost")
    args = ap.parse_args()

    if args.bypass_cost:
        out, tag = bypass_cost(args), "bypass"
    elif args.sweep_greed:
        out, tag = greed_sweep(args), "greed"
    elif args.coverage_latency:
        out, tag = coverage_latency(args), "coverage"
    elif args.crypto_decomp:
        out, tag = crypto_decomposition(args), "cryptodecomp"
    else:
        out, tag = defence_sweep(args), "defence"

    Path("results").mkdir(exist_ok=True)
    Path(f"results/priority_{tag}_{args.scenario}.json").write_text(
        json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
