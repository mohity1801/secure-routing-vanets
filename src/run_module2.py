"""Module 2 evaluation: trust-aware CH election under attack.

    python3 src/run_module2.py --scenario urban --seeds 15
    python3 src/run_module2.py --scenario urban --seeds 15 --ablate

Baselines carry no defence, so the comparison is not "who is faster" but
"what happens when 0-40% of the network is hostile".
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import mannwhitneyu

sys.path.insert(0, str(Path(__file__).parent))

from attacks import Adversary                     # noqa: E402
from config import Config                         # noqa: E402
from network import Network                       # noqa: E402
from protocols.chirp import CHIRP                 # noqa: E402
from protocols.csgd_net import CSGDNet            # noqa: E402
from protocols.leach import LEACHC                # noqa: E402
from run_module1 import SCENARIOS                 # noqa: E402
from trust import TrustEngine                     # noqa: E402


def run_once(cfg, proto_cls, seed, with_trust, use_cred=True):
    net = Network(cfg, np.random.default_rng(seed))
    adv = Adversary(cfg, np.random.default_rng(seed + 555), cfg.n_nodes)

    trust = (TrustEngine(cfg, cfg.n_nodes, use_credibility=use_cred)
             if with_trust else None)
    try:
        proto = proto_cls(cfg, np.random.default_rng(seed + 10_000), trust=trust)
    except TypeError:
        proto = proto_cls(cfg, np.random.default_rng(seed + 10_000))
    net.association_mode = getattr(proto, "association", "nearest")

    ch_slots = 0
    ch_slots_attacker = 0
    late_slots = 0
    late_attacker = 0

    # Evaluate over the network's USEFUL lifetime, i.e. up to half-node-death.
    # Past that point the survivors are overwhelmingly attackers -- dropping
    # skips the forward transmit, so attacking is cheaper than behaving and
    # attackers outlive honest nodes. Averaging PDR or attacker-CH share over
    # fixed rounds therefore measures the endgame, where a handful of surviving
    # attackers hold every head slot by default, rather than the defence.
    stop_alive = cfg.n_nodes * cfg.eval_alive_frac
    for r in range(cfg.max_rounds):
        if net.n_alive <= stop_alive:
            break
        ch = proto.select_ch(net)
        if getattr(proto, "reelected", True):
            net.run_setup_phase(ch)

        ch_slots += ch.size
        n_att_ch = int(adv.is_attacker[ch].sum()) if ch.size else 0
        ch_slots_attacker += n_att_ch
        # steady state, after the trust engine has had time to gather evidence
        if r >= cfg.trust_warmup:
            late_slots += ch.size
            late_attacker += n_att_ch

        outcome = net.run_steady_state(ch, adversary=adv)
        if trust is not None:
            trust.observe(net, outcome, adv, r)
        net.step_mobility()

    pdr = net.readings_delivered / max(net.readings_generated, 1)
    att, hon = adv.is_attacker, ~adv.is_attacker
    e_adv = (float(net.energy[att].mean() / max(net.energy[hon].mean(), 1e-12))
             if att.any() else 1.0)
    res = {
        "pdr": float(pdr),
        "att_ch_share": ch_slots_attacker / max(ch_slots, 1),
        "att_ch_late": late_attacker / max(late_slots, 1),
        "detect": 0.0, "fpr": 0.0, "ttd": float("nan"),
        "e_adv": e_adv, "rounds": float(r + 1),
    }

    if trust is not None and adv.attackers.size:
        sc = trust.score()
        # only nodes that actually drop are detectable by a forwarding watchdog
        droppers = np.array([adv.behaviour[i] in ("blackhole", "greyhole", "onoff")
                             for i in range(cfg.n_nodes)])
        d = droppers & att
        res["detect"] = float((sc[d] < cfg.trust_gate).mean()) if d.any() else float("nan")
        res["fpr"] = float((sc[hon] < cfg.trust_gate).mean())
        ttd = trust.first_flagged[d]
        ttd = ttd[ttd >= 0]
        res["ttd"] = float(ttd.mean()) if ttd.size else float("nan")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=list(SCENARIOS), default="urban")
    ap.add_argument("--seeds", type=int, default=15)
    ap.add_argument("--rounds", type=int, default=60)
    ap.add_argument("--ablate", action="store_true",
                    help="credibility weighting on vs off under collusion")
    args = ap.parse_args()

    kinds = ("blackhole", "greyhole", "onoff", "badmouth", "ballot")

    if args.ablate:
        # Two mixes. The full mix is realistic but dilutes the effect, since
        # only 2 of its 5 behaviours falsify reports at all. The collusion mix
        # isolates what credibility weighting actually defends against: a
        # coordinated group bad-mouthing honest heads while vouching for each
        # other. Half the colluders drop, so there is real misbehaviour to
        # detect underneath the lies.
        mixes = {
            "full mix": kinds,
            "collusion only": ("badmouth", "ballot", "greyhole"),
        }
        for mix_name, mix in mixes.items():
            print(f"\nCredibility ablation -- {args.scenario}, {args.seeds} "
                  f"seeds, {mix_name}: {', '.join(mix)}\n")
            print(f"{'frac':>6}{'credibility':>13}{'PDR':>8}{'detect':>9}"
                  f"{'FPR':>8}{'att CH%':>9}")
            for frac in (0.1, 0.2, 0.3, 0.4):
                row = {}
                for use_cred in (True, False):
                    cfg = Config(max_rounds=args.rounds, attacker_frac=frac,
                                 attack_kinds=mix, **SCENARIOS[args.scenario])
                    runs = [run_once(cfg, CHIRP, s, True, use_cred)
                            for s in range(args.seeds)]
                    m = {k: float(np.nanmean([r[k] for r in runs])) for k in runs[0]}
                    row[use_cred] = m
                    print(f"{frac:>6.1f}{('on' if use_cred else 'OFF'):>13}"
                          f"{m['pdr']:>8.3f}{m['detect']:>9.3f}"
                          f"{m['fpr']:>8.3f}{m['att_ch_share']*100:>9.1f}")
                fo, fn = row[False]["fpr"], row[True]["fpr"]
                if fo > 0:
                    print(f"{'':>6}{'-> FPR':>13}{'':>8}{'':>9}"
                          f"{(1 - fn / fo) * 100:>7.0f}%  lower with credibility")
        return

    cfg0 = Config(max_rounds=args.rounds, **SCENARIOS[args.scenario])
    print(f"\nScenario: {args.scenario} | {cfg0.n_nodes} nodes | "
          f"{args.seeds} seeds | {args.rounds} rounds")
    print(f"Attack mix: {', '.join(kinds)}\n")

    variants = [("CSGD-NET", CSGDNet, False), ("LEACH-C", LEACHC, False),
                ("CHIRP (no trust)", CHIRP, False), ("CHIRP + trust", CHIRP, True)]

    print(f"{'attacker%':>10}{'protocol':<20}{'PDR':>8}{'att CH%':>9}"
          f"{'late%':>8}{'detect':>9}{'FPR':>8}{'TTD':>7}{'Eadv':>7}{'rnds':>6}")
    out = {}
    for frac in (0.0, 0.1, 0.2, 0.3, 0.4):
        cfg = Config(max_rounds=args.rounds, attacker_frac=frac,
                     attack_kinds=kinds, **SCENARIOS[args.scenario])
        for label, cls, wt in variants:
            runs = [run_once(cfg, cls, s, wt) for s in range(args.seeds)]
            m = {k: float(np.nanmean([r[k] for r in runs])) for k in runs[0]}
            out[f"{frac}|{label}"] = m
            ttd = "-" if np.isnan(m["ttd"]) else f"{m['ttd']:.1f}"
            det = "-" if np.isnan(m["detect"]) else f"{m['detect']:.3f}"
            print(f"{frac*100:>10.0f}{label:<20}{m['pdr']:>8.3f}"
                  f"{m['att_ch_share']*100:>9.1f}{m['att_ch_late']*100:>8.1f}"
                  f"{det:>9}{m['fpr']:>8.3f}{ttd:>7}"
                  f"{m['e_adv']:>7.2f}{m['rounds']:>6.0f}")
        print()

    # headline significance at 20% attackers
    cfg = Config(max_rounds=args.rounds, attacker_frac=0.2,
                 attack_kinds=kinds, **SCENARIOS[args.scenario])
    a = [run_once(cfg, CHIRP, s, True)["pdr"] for s in range(args.seeds)]
    b = [run_once(cfg, CSGDNet, s, False)["pdr"] for s in range(args.seeds)]
    _, p = mannwhitneyu(a, b, alternative="greater")
    print(f"PDR at 20% attackers: CHIRP+trust {np.mean(a):.3f} vs "
          f"CSGD-NET {np.mean(b):.3f}  ({(np.mean(a)/np.mean(b)-1)*100:+.1f}%, "
          f"p={p:.4f})")

    Path("results").mkdir(exist_ok=True)
    Path(f"results/module2_{args.scenario}.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
