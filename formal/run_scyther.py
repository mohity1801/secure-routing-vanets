"""Run Scyther over the CHIRP Module 3a models and check them against the
results recorded in docs/module3.md.

    python3 formal/run_scyther.py
    SCYTHER=/path/to/scyther-mac python3 formal/run_scyther.py
    python3 formal/run_scyther.py --runs 5     # deeper search, slower

Two of the models are EXPECTED to have failing claims, and that is not a
regression:

  fusion-limit.spdl  exists to demonstrate that fusion destroys end-to-end
                     authentication. Its failure IS the result.
  priority.spdl      its cross-phase claims fail because the TA never learns
                     which cluster head the vehicle will later talk to; see the
                     file header and priority-assert.spdl.

The script therefore compares against an expected set rather than demanding a
clean sweep. Exit 0 means "matches what docs/module3.md records", exit 1 means
something changed and the documentation is now wrong.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

MODELS = ["register.spdl", "priority.spdl", "priority-assert.spdl",
          "aggregate.spdl", "fusion-limit.spdl"]

# (protocol, role, claim-kind) expected to FAIL, with the reason.
EXPECTED_FAIL = {
    ("chirp-fused-e2e", "R", "Niagree"):
        "by design: the RSU has no cryptographic link to the member",
    ("chirp-fused-e2e", "R", "Nisynch"):
        "by design: fusion destroys end-to-end authentication",
    ("chirp-priority", "V", "Weakagree"): "cross-phase; see file header",
    ("chirp-priority", "V", "Niagree"): "cross-phase; see file header",
    ("chirp-priority", "V", "Nisynch"): "cross-phase; see file header",
    ("chirp-priority", "TA", "Alive"): "TA never learns the head identity",
    ("chirp-priority", "TA", "Weakagree"): "TA never learns the head identity",
    ("chirp-priority", "C", "Weakagree"): "TA is not partnered with any head",
}

# The claims that carry the security argument.
HEADLINE = {
    ("chirp-priority", "C", "Nisynch"):
        "head grants a slot only to a TA-certified EMS vehicle, no replay",
    ("chirp-priority-assert", "C", "Nisynch"):
        "the assertion exchange alone is sound",
    ("chirp-verbatim", "R", "Nisynch"):
        "RSU authenticates the emergency vehicle end-to-end through the relay",
    ("chirp-aggregate", "R", "Nisynch"):
        "RSU authenticates the cluster head on the fused packet",
    ("chirp-member", "C", "Nisynch"):
        "head authenticates the member on its reading",
}


def find_scyther() -> str | None:
    env = os.environ.get("SCYTHER")
    if env and Path(env).exists():
        return env
    for name in ("scyther", "scyther-mac", "scyther-linux"):
        p = shutil.which(name)
        if p:
            return p
    for p in (HERE / "scyther-mac", HERE / "bin" / "scyther"):
        if p.exists():
            return str(p)
    return None


def parse(out: str):
    rows = []
    for line in out.splitlines():
        if not line.startswith("claim"):
            continue
        f = line.split()
        if len(f) < 6:
            continue
        # claim <proto>,<role>  <Kind>_<label>  -  <Ok|Fail>  [detail]
        proto, _, role = f[1].partition(",")
        kind = f[2].rsplit("_", 1)[0]
        status = "Fail" if "Fail" in line else ("Ok" if "Ok" in line else "?")
        rows.append((proto, role, kind, status))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=4)
    args = ap.parse_args()

    exe = find_scyther()
    if exe is None:
        print("Scyther not found. Set SCYTHER=/path/to/binary, or put the")
        print("binary in formal/. Source: github.com/cascremers/scyther")
        print("(v1.3.0 ships a native macOS arm64 build.)")
        return 2

    print(f"scyther:   {exe}")
    print(f"max-runs:  {args.runs}\n")

    ok = fail_unexpected = fail_expected = 0
    surprises = []

    for model in MODELS:
        print("=" * 76)
        print(model)
        print("=" * 76)
        try:
            res = subprocess.run(
                [exe, "--plain", f"--max-runs={args.runs}", str(HERE / model)],
                capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            print("  TIMEOUT -- lower --runs and retry\n")
            surprises.append((model, "timeout"))
            continue

        rows = parse(res.stdout)
        if not rows:
            print("  no claims parsed\n" + res.stdout[:1500] + "\n")
            surprises.append((model, "unparsed"))
            continue

        for proto, role, kind, status in rows:
            key = (proto, role, kind)
            note = ""
            if status == "Ok":
                ok += 1
                if key in EXPECTED_FAIL:
                    note = "  !! expected FAIL but passed -- docs are stale"
                    surprises.append((f"{proto}.{role}.{kind}", "now passes"))
                elif key in HEADLINE:
                    note = "  <<< " + HEADLINE[key]
            else:
                if key in EXPECTED_FAIL:
                    fail_expected += 1
                    note = "  (expected: " + EXPECTED_FAIL[key] + ")"
                else:
                    fail_unexpected += 1
                    surprises.append((f"{proto}.{role}.{kind}", "unexpected fail"))
                    note = "  !! UNEXPECTED"
            print(f"  {proto:<24}{role:<4}{kind:<11}{status:<6}{note}")
        print()

    print("=" * 76)
    print(f"{ok} verified, {fail_expected} failed as expected, "
          f"{fail_unexpected} failed unexpectedly")

    if surprises:
        print("\nDoes not match docs/module3.md:")
        for a, b in surprises:
            print(f"  {a}: {b}")
        return 1

    print("\nMatches the results recorded in docs/module3.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
