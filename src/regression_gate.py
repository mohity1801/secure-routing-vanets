"""Regression gate: Module 5 must not perturb Modules 1 and 2.

Exercises Network and every protocol on fixed seeds across the static, highway
and urban scenarios plus the trust engine under attack, and fingerprints the
exact float bits of the results -- energy vector, PDR counters, orphan and
intra-cluster traces, trust scores.

THE INVARIANT: with `ems_frac = 0` and `sig_bits = mac_bits = 0`, every
pre-Module-5 result must be bit-identical. Priority traffic is opt-in and a
node's class-2 messages are a subset of the readings it already sends, so
nothing about the base model may move. Without this check it is very easy for
priority accounting to silently shift the reproduction the whole project rests
on.

    python3 src/regression_gate.py results/regression_reference.json   # capture
    python3 src/regression_gate.py /tmp/now.json                       # re-run
    python3 src/regression_gate.py --diff results/regression_reference.json \\
                                          /tmp/now.json                # compare
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from attacks import Adversary               # noqa: E402
from config import Config                   # noqa: E402
from network import Network                 # noqa: E402
from protocols.chirp import CHIRP           # noqa: E402
from protocols.csgd_net import CSGDNet      # noqa: E402
from protocols.heed import HEED             # noqa: E402
from protocols.leach import LEACH, LEACHC   # noqa: E402
from protocols.swarm import GACluster, PSOCluster  # noqa: E402
from run_module1 import SCENARIOS           # noqa: E402
from trust import TrustEngine               # noqa: E402

PROTOCOLS = {
    "LEACH": LEACH, "LEACH-C": LEACHC, "HEED": HEED,
    "PSO": PSOCluster, "GA": GACluster, "CSGD-NET": CSGDNet, "CHIRP": CHIRP,
}


def fingerprint(a: np.ndarray) -> str:
    """Hash of the exact float bits -- catches changes a rounded mean hides."""
    return hashlib.sha256(np.ascontiguousarray(a, dtype=np.float64).tobytes()
                          ).hexdigest()[:16]


def run(cfg, proto_cls, seed, rounds, with_trust=False, adversary=False):
    net = Network(cfg, np.random.default_rng(seed))
    adv = (Adversary(cfg, np.random.default_rng(seed + 555), cfg.n_nodes)
           if adversary else None)
    trust = TrustEngine(cfg, cfg.n_nodes) if with_trust else None
    try:
        proto = proto_cls(cfg, np.random.default_rng(seed + 10_000), trust=trust)
    except TypeError:
        proto = proto_cls(cfg, np.random.default_rng(seed + 10_000))
    net.association_mode = getattr(proto, "association", "nearest")

    for r in range(rounds):
        if net.n_alive == 0:
            break
        ch = proto.select_ch(net)
        if getattr(proto, "reelected", True):
            net.run_setup_phase(ch)
        outcome = net.run_steady_state(ch, adversary=adv)
        if trust is not None:
            trust.observe(net, outcome, adv, r)
        net.step_mobility()

    rec = {
        "energy_fp": fingerprint(net.energy),
        "residual": round(net.residual_energy, 12),
        "n_alive": net.n_alive,
        "packets_to_rsu": int(net.packets_to_rsu),
        "readings_generated": round(net.readings_generated, 6),
        "readings_delivered": round(net.readings_delivered, 6),
        "orphan_fp": fingerprint(np.array(net.orphan_rate)),
        "intra_fp": fingerprint(np.array(net.intra_dist)),
        "rounds_run": net.round,
    }
    if trust is not None:
        rec["trust_fp"] = fingerprint(trust.score())
    return rec


def collect() -> dict:
    out = {}
    # 1. the paper's static reproduction setting
    for name, cls in PROTOCOLS.items():
        for seed in (0, 1, 2):
            cfg = Config(max_rounds=45)
            out[f"static|{name}|{seed}"] = run(cfg, cls, seed, 45)

    # 2. both mobility scenarios
    for scen, kw in SCENARIOS.items():
        for name, cls in PROTOCOLS.items():
            for seed in (0, 1):
                cfg = Config(max_rounds=40, **kw)
                out[f"{scen}|{name}|{seed}"] = run(cfg, cls, seed, 40)

    # 3. Module 2: trust engine under a mixed adversary
    kinds = ("blackhole", "greyhole", "onoff", "badmouth", "ballot")
    for frac in (0.0, 0.2, 0.4):
        for seed in (0, 1):
            cfg = Config(max_rounds=35, attacker_frac=frac, attack_kinds=kinds,
                         **SCENARIOS["urban"])
            out[f"trust|{frac}|{seed}"] = run(
                cfg, CHIRP, seed, 35, with_trust=True, adversary=True)
    return out


def main():
    if sys.argv[1] == "--diff":
        a = json.loads(Path(sys.argv[2]).read_text())
        b = json.loads(Path(sys.argv[3]).read_text())
        keys = sorted(set(a) | set(b))
        bad = []
        for k in keys:
            if a.get(k) != b.get(k):
                bad.append(k)
        if not bad:
            print(f"IDENTICAL across {len(keys)} configurations")
            return 0
        print(f"DIFFERS in {len(bad)}/{len(keys)} configurations:")
        for k in bad[:20]:
            print(f"\n  {k}")
            va, vb = a.get(k, {}), b.get(k, {})
            for f in sorted(set(va) | set(vb)):
                if va.get(f) != vb.get(f):
                    print(f"    {f}: {va.get(f)}  ->  {vb.get(f)}")
        return 1

    res = collect()
    Path(sys.argv[1]).write_text(json.dumps(res, indent=2, sort_keys=True))
    print(f"wrote {sys.argv[1]}  ({len(res)} configurations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
