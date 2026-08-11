"""Why does CHIRP lose first-node-death in the urban scenario?

Traces the identity and history of the first node to die, rather than guessing
from aggregate metrics.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from config import Config                    # noqa: E402
from network import Network                  # noqa: E402
from protocols.chirp import CHIRP            # noqa: E402
from protocols.csgd_net import CSGDNet       # noqa: E402
from run_module1 import SCENARIOS            # noqa: E402


def trace_first_death(cfg, proto_cls, seed):
    net = Network(cfg, np.random.default_rng(seed))
    proto = proto_cls(cfg, np.random.default_rng(seed + 10_000))
    net.association_mode = getattr(proto, "association", "nearest")

    n = cfg.n_nodes
    ch_rounds = np.zeros(n, int)       # rounds spent as CH
    members_served = np.zeros(n, int)  # cumulative members received from
    orphan_rounds = np.zeros(n, int)   # rounds spent orphaned
    prev_alive = np.ones(n, bool)

    for r in range(cfg.max_rounds):
        if net.n_alive == 0:
            break
        ch = proto.select_ch(net)
        if getattr(proto, "reelected", True):
            net.run_setup_phase(ch)

        members, slot, _, orphans = net.assign_members(ch)
        ch_rounds[ch] += 1
        orphan_rounds[orphans] += 1
        if slot is not None and members.size:
            counts = np.bincount(slot, minlength=ch.size)
            members_served[ch] += counts

        net.run_steady_state(ch)
        net.step_mobility()

        died = prev_alive & ~net.alive
        if died.any():
            i = int(np.where(died)[0][0])
            return {
                "round": r + 1,
                "node": i,
                "ch_rounds": int(ch_rounds[i]),
                "members_served": int(members_served[i]),
                "orphan_rounds": int(orphan_rounds[i]),
                "was_ch": bool(ch_rounds[i] > 0),
                "mean_cluster": members_served[i] / max(ch_rounds[i], 1),
            }
        prev_alive = net.alive.copy()
    return None


def main():
    for scen, rounds in (("urban", 150), ("highway", 120)):
        cfg = Config(max_rounds=rounds, **SCENARIOS[scen])
        print(f"\n=== {scen} — first node to die, 20 seeds ===")
        print(f"{'protocol':<10}{'FND':>7}{'was CH%':>9}{'CH rounds':>11}"
              f"{'mean cluster':>14}{'orphan rds':>12}")
        for name, cls in (("CSGD-NET", CSGDNet), ("CHIRP", CHIRP)):
            recs = [trace_first_death(cfg, cls, s) for s in range(20)]
            recs = [r for r in recs if r]
            print(f"{name:<10}"
                  f"{np.mean([r['round'] for r in recs]):>7.1f}"
                  f"{np.mean([r['was_ch'] for r in recs])*100:>9.0f}"
                  f"{np.mean([r['ch_rounds'] for r in recs]):>11.1f}"
                  f"{np.mean([r['mean_cluster'] for r in recs]):>14.1f}"
                  f"{np.mean([r['orphan_rounds'] for r in recs]):>12.1f}")

        # per-round CH receive load, which is what a head actually pays for
        print(f"\n  mean members per CH per round:")
        for name, cls in (("CSGD-NET", CSGDNet), ("CHIRP", CHIRP)):
            net = Network(cfg, np.random.default_rng(0))
            proto = cls(cfg, np.random.default_rng(10_000))
            net.association_mode = getattr(proto, "association", "nearest")
            loads = []
            for _ in range(12):
                if net.n_alive == 0:
                    break
                ch = proto.select_ch(net)
                members, slot, _, orphans = net.assign_members(ch)
                if ch.size:
                    loads.append(members.size / ch.size)
                net.run_steady_state(ch)
                net.step_mobility()
            k, cfg_ = cfg.packet_bits, cfg
            rx_mj = np.mean(loads) * k * cfg_.e_elec * cfg_.packets_per_round * 1e3
            print(f"    {name:<10}{np.mean(loads):>6.1f} members  "
                  f"-> {rx_mj:>6.1f} mJ/round of receive alone")


if __name__ == "__main__":
    main()
