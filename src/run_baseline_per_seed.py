"""Preserve per-seed static-baseline traces needed for Figure 14.

The committed ``results/baseline.json`` intentionally stores only means.  That
is sufficient for Figures 11, 12, 13 and 15, but a confidence interval cannot
be reconstructed from it.  This runner reuses ``run_baseline.run_once`` without
changing the simulation and preserves each seed's dead-node trace.

Before writing, a normal 30-seed run must reproduce every aggregate in the
committed baseline file bit-for-bit.  A reduced-seed smoke test must use
``--dry`` and never writes an artifact.

    python3 src/run_baseline_per_seed.py
    python3 src/run_baseline_per_seed.py --seeds 2 --dry
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config                         # noqa: E402
from run_baseline import PROTOCOLS, run_once      # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = ROOT / "results" / "baseline.json"
DEFAULT_OUTPUT = ROOT / "results" / "baseline_per_seed.json"


def _pad(run: dict, key: str, length: int) -> list:
    values = run[key]
    if len(values) > length:
        raise ValueError(f"{key} trace is longer than the reference")
    if key == "packets":
        fill = values[-1]
    else:
        fill = 0
    return values + [fill] * (length - len(values))


def verify_reference(reference: dict, runs_by_protocol: dict) -> int:
    """Require the rerun to reproduce all committed baseline aggregates."""
    comparisons = 0
    if list(reference) != list(PROTOCOLS):
        raise ValueError("baseline protocol names/order differ from PROTOCOLS")

    for name in PROTOCOLS:
        runs = runs_by_protocol[name]
        rec = reference[name]
        for key in ("residual", "alive", "packets"):
            length = max(len(run[key]) for run in runs)
            got = np.mean([_pad(run, key, length) for run in runs], axis=0)
            expected = np.asarray(rec[key], dtype=float)
            if not np.array_equal(got, expected):
                if got.shape != expected.shape:
                    detail = f"shape {got.shape} != {expected.shape}"
                else:
                    detail = f"max abs diff {np.max(np.abs(got - expected)):.3g}"
                raise ValueError(f"{name}.{key} does not reproduce baseline: {detail}")
            comparisons += expected.size

        for key in ("fnd", "hnd", "lnd"):
            got = float(np.mean([run[key] for run in runs]))
            if got != rec[key]:
                raise ValueError(
                    f"{name}.{key} does not reproduce baseline: "
                    f"{got!r} != {rec[key]!r}"
                )
            comparisons += 1
    return comparisons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--rounds", type=int, default=60)
    ap.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument(
        "--dry", action="store_true",
        help="smoke-test only; skip the committed-reference check and write nothing",
    )
    args = ap.parse_args()

    if args.seeds < 1 or args.rounds < 1:
        ap.error("--seeds and --rounds must be positive")
    if not args.reference.exists():
        ap.error(f"reference file not found: {args.reference}")

    cfg = Config(max_rounds=args.rounds)
    seeds = list(range(args.seeds))
    runs_by_protocol = {}
    for name, proto_cls in PROTOCOLS.items():
        print(f"running {name}: {args.seeds} seeds", flush=True)
        runs_by_protocol[name] = [run_once(cfg, proto_cls, seed) for seed in seeds]

    if args.dry:
        print("dry run complete; no reference check and no file written")
        return 0

    reference_bytes = args.reference.read_bytes()
    reference = json.loads(reference_bytes)
    comparisons = verify_reference(reference, runs_by_protocol)
    print(f"baseline reference check: {comparisons} values bit-identical")

    protocols = {}
    for name, runs in runs_by_protocol.items():
        protocol_runs = []
        for seed, run in zip(seeds, runs):
            alive = [int(v) for v in _pad(run, "alive", args.rounds)]
            protocol_runs.append({
                "seed": seed,
                "rounds_completed": len(run["alive"]),
                "fnd": run["fnd"],
                "hnd": run["hnd"],
                "lnd": run["lnd"],
                "dead": [cfg.n_nodes - value for value in alive],
            })
        protocols[name] = protocol_runs

    artifact = {
        "_meta": {
            "generated_by": "python3 src/run_baseline_per_seed.py",
            "method": "run_baseline.run_once; unchanged static baseline",
            "scenario": cfg.scenario,
            "n_nodes": cfg.n_nodes,
            "initial_energy_j": cfg.initial_energy,
            "max_rounds": args.rounds,
            "n_seeds": args.seeds,
            "seeds": seeds,
            "trace_indexing": (
                "dead[i] is the end-of-round count for round i+1; "
                "round 0 is deterministically 0 and is not stored"
            ),
            "post_death_padding": "alive=0, therefore dead=n_nodes",
            "reference": str(args.reference.relative_to(ROOT)),
            "reference_sha256": hashlib.sha256(reference_bytes).hexdigest(),
            "reference_check": (
                f"{comparisons} aggregate trace/lifetime values bit-identical"
            ),
        },
        "protocols": protocols,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2) + "\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
