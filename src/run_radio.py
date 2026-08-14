"""802.11p path-loss robustness check -- do the findings survive the radio?

    python3 src/run_radio.py --experiment coverage
    python3 src/run_radio.py --experiment defence --scenario urban
    python3 src/run_radio.py --experiment all

The project inherits the Heinzelman first-order radio from the base paper:
eps_fs*d^2 below d0 = 87.71 m, eps_mp*d^4 above. That model was built for
short-range sensor motes, and at VANET distances the d^4 branch makes long
links enormously expensive -- docs/module1.md concedes it. The attackable
sentence is "your findings may be artifacts of an unrealistic energy model".

This runner re-runs the experiment behind each headline finding under BOTH
radio models -- the default, and log-distance path loss with no knee
(src/energy.py: amp = eps_ld * d^gamma, calibrated to agree with Heinzelman at
d0) -- on PAIRED seeds. Mobility consumes only Network.rng and never sees
energy, so the same seed gives the same roads, speeds, attackers and traffic
under both models; every difference is the radio and what the protocols do
about it. Exponents: 2.0 highway (5.9 GHz LOS), 3.0 urban (harsh end of the
2.7-3.0 street-canyon bracket; --experiment expsweep sweeps the bracket).

GUARDRAIL: each experiment's heinzelman arm re-derives a committed
results/*.json with the same seeds through the same code path, and is checked
against it float-for-float. If that check fails, the mirror of the experiment
has drifted and the logdistance arm proves nothing -- fix the mirror first.

Experiments, one per finding under test (docs/radio.md):

    coverage   docs/priority.md finding 1 -- coverage vs deadline latency
    defence    docs/priority.md finding 3 -- priority DoS; auth -> 0.000
    greed      docs/priority.md finding 5 -- restrained liar is invisible
    bypass     docs/priority.md finding 2 -- energy price of priority, and
               the RSU-density (d^2 vs d^4 knee) explanation
    freeride   docs/module2.md -- trust demotion pays the attacker 2.0-2.4x
    module1    docs/module1.md -- protocol ordering, CHIRP vs CSGD-NET
    ablation   docs/module1.md -- the intra/energy terms stay load-bearing
    expsweep   sensitivity of the urban conclusions to the exponent choice
    crypto     docs/module3b.md -- compute vs radio cost of verification
    calibration  the two models on one packet: they agree at d0 by
               construction, and the tail is the whole question

Delay stays in TDMA slots everywhere: the radio model prices energy, not
time, so no delay figure can change units here.

Exits NON-ZERO if any heinzelman arm stops reproducing the committed results
it mirrors -- same convention as formal/run_scyther.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NamedTuple

import numpy as np
from scipy.stats import mannwhitneyu, spearmanr

sys.path.insert(0, str(Path(__file__).parent))

from config import Config                          # noqa: E402
from energy import tx_energy                       # noqa: E402
from protocols.chirp import CHIRP                  # noqa: E402
from protocols.csgd_net import CSGDNet             # noqa: E402
from run_module1 import (ABLATION_TERMS, PROTOCOLS, SCENARIOS,  # noqa: E402
                         ablation_weights, compare_runs)
from run_module1 import run_once as m1_run_once    # noqa: E402
from run_module2 import run_once as m2_run_once    # noqa: E402
import run_priority                                # noqa: E402
from run_priority import base_cfg, mean_of         # noqa: E402
from run_priority import run_once as p_run_once    # noqa: E402

# Log-distance exponent per scenario. 5.9 GHz V2V measurements put highway
# LOS at ~1.8-2.1 and urban streets at ~2.7-3.0; we take 2.0 and the harsh
# end of the urban bracket. expsweep() covers the rest of the bracket.
RADIO_EXP = {"highway": 2.0, "urban": 3.0}

# The urban bracket, swept by exp_expsweep to show the exponent choice inside
# it is a free parameter. Recorded in that run's _meta instead of a single
# exponent, because for this experiment there is no single exponent.
EXPSWEEP_GAMMAS = (2.0, 2.5, 2.75, 3.0)

MODELS = ("heinzelman", "logdistance")

# Attacker fraction and greed levels the headline rows are read off. Named so
# the lookups below cannot drift from the loops that build the keys.
ATT_HEADLINE = 0.20
GREED_STEALTH = 0.50
GREED_MAX = 1.00
FREERIDE_FRACS = (0.1, 0.2, 0.3, 0.4)


def radio_kw(scenario: str, model: str) -> dict:
    if model == "heinzelman":
        return {}
    return {"radio_model": "logdistance",
            "path_loss_exp": RADIO_EXP[scenario]}


def prio_args(scenario: str, seeds: int, rounds: int = 60,
              ems: float = 0.05) -> SimpleNamespace:
    """The argparse surface run_priority's helpers expect."""
    return SimpleNamespace(scenario=scenario, seeds=seeds, rounds=rounds,
                           ems=ems)


# ------------------------------------------------------------------ guardrail
def check_committed(path: str, mine: dict) -> dict:
    """Compare a heinzelman arm against the committed file it re-derives.

    Exact equality is the expectation, not a tolerance band: same seeds, same
    Config construction, same code path, and the regression gate already
    proves the default radio branch is bit-identical. Only keys present in
    both are compared (this runner deliberately runs a subset of some grids).

    Any status other than "OK" fails the run in main(). "VACUOUS" is its own
    status because an empty comparison is NOT a pass: if the mirror's keys stop
    matching the committed file's, nothing is compared and a naive
    "no differences found" would report success while checking nothing.
    """
    p = Path(path)
    if not p.exists():
        print(f"  [check] {path} not found -- guardrail could not run")
        return {"committed": path, "status": "missing"}
    ref = json.loads(p.read_text())
    n_ok, diffs = 0, []
    for key, rec in mine.items():
        if key not in ref or not isinstance(rec, dict):
            continue
        for f, v in rec.items():
            rv = ref[key].get(f)
            if rv is None or not isinstance(v, (int, float)):
                continue
            same = (v == rv) or (isinstance(v, float) and isinstance(rv, float)
                                 and np.isnan(v) and np.isnan(rv))
            if same:
                n_ok += 1
            else:
                diffs.append((key, f, rv, v))
    if diffs:
        status = "MISMATCH"
    elif n_ok == 0:
        status = "VACUOUS"
    else:
        status = "OK"
    print(f"  [check vs {p.name}] {n_ok} values identical, "
          f"{len(diffs)} differ -> {status}")
    if status == "VACUOUS":
        print("      nothing was compared -- the mirror's keys no longer match "
              f"{p.name}, so this check proves nothing")
    for k, f, rv, v in diffs[:6]:
        print(f"      {k}.{f}: committed {rv}  rerun {v}")
    return {"committed": path, "status": status, "n_identical": n_ok,
            "n_mismatch": len(diffs)}


def break_even_distance(cfg, bits: int, energy_mj: float) -> float:
    """Distance at which transmitting `bits` costs `energy_mj`, in closed form.

    tx_energy is monotonic in d and analytically invertible under both models,
    so this needs no search: solve k*(e_elec + eps*d^n) = E for d. Returns 0.0
    when the per-bit electronics alone already exceed the budget, i.e. the
    radio costs more at every distance.
    """
    amp = energy_mj * 1e-3 / bits - cfg.e_elec       # J/bit left for the amplifier
    if amp <= 0:
        return 0.0
    if cfg.radio_model == "logdistance":
        return float((amp / cfg.eps_ld) ** (1.0 / cfg.path_loss_exp))
    d_fs = float((amp / cfg.eps_fs) ** 0.5)          # free-space branch
    return d_fs if d_fs <= cfg.d0 else float((amp / cfg.eps_mp) ** 0.25)


# ---------------------------------------------------------------- experiments
def exp_coverage(scen: str, seeds: int, rounds: int) -> dict:
    """Finding 1: deadline-miss tracks orphan rate inversely, 7 protocols.

    The claim contains no energy term -- delay is slots, orphaning is
    topology -- but the radio decides who dies when, and deaths move orphan
    rates and cluster sizes. If the inverse relationship needs d^4 to hold,
    this is where it breaks.
    """
    out = {}
    for model in MODELS:
        print(f"\n--- {model}" + (f" (gamma={RADIO_EXP[scen]})"
                                  if model == "logdistance" else ""))
        args = prio_args(scen, seeds, rounds)
        out[model] = run_priority.coverage_latency(args, **radio_kw(scen, model))
        rho, p = spearmanr([out[model][k]["orphan_pct"] for k in out[model]],
                           [out[model][k]["ems_miss"] for k in out[model]])
        out[model]["_spearman"] = {"rho": float(rho), "p": float(p)}
        print(f"  Spearman orphan%% vs deadline-miss across protocols: "
              f"rho={rho:+.3f} (p={p:.4f})")
    out["_check"] = check_committed(
        f"results/priority_coverage_{scen}.json",
        {k: v for k, v in out["heinzelman"].items() if not k.startswith("_")})
    return out


def exp_defence(scen: str, seeds: int, rounds: int) -> dict:
    """Finding 3 + 4: the DoS surface, and authorisation taking it to zero.

    Reduced to the undefended baseline and the headline 20% row -- the full
    grid is in results/priority_defence_*.json; nothing in between changes
    the robustness question.
    """
    out = {}
    for model in MODELS:
        print(f"\n--- {model}" + (f" (gamma={RADIO_EXP[scen]})"
                                  if model == "logdistance" else ""))
        print(f"{'att%':>5}{'defence':<8}{'dl-miss':>9}{'delay':>7}"
              f"{'prio mJ':>9}{'false%':>8}{'drain%':>8}{'detect':>8}{'FPR':>7}")
        arm, per_seed = {}, {}
        for frac in (0.0, ATT_HEADLINE):
            for d in ("none", "trust", "auth"):
                cfg = base_cfg(prio_args(scen, seeds, rounds),
                               attacker_frac=frac, **radio_kw(scen, model))
                runs = [p_run_once(cfg, CHIRP, s, d) for s in range(seeds)]
                m = mean_of(runs)
                arm[f"{frac}|{d}"] = m
                per_seed[f"{frac}|{d}"] = [r["ems_miss"] for r in runs]
                det = "-" if np.isnan(m["detect"]) else f"{m['detect']:.3f}"
                fpr = "-" if np.isnan(m["fpr"]) else f"{m['fpr']:.3f}"
                print(f"{frac*100:>5.0f}{d:<8}{m['ems_miss']:>9.3f}"
                      f"{m['ems_delay']:>7.2f}{m['prio_mJ']:>9.0f}"
                      f"{m['prio_false_pct']:>8.0f}{m['drain_pct']:>8.2f}"
                      f"{det:>8}{fpr:>7}")
        a, b = per_seed[f"{ATT_HEADLINE}|auth"], per_seed[f"{ATT_HEADLINE}|none"]
        _, p = mannwhitneyu(a, b, alternative="less")
        print(f"  dl-miss at 20%: auth {np.mean(a):.3f} vs none "
              f"{np.mean(b):.3f}  (p={p:.4g}); auth zero in "
              f"{sum(v == 0.0 for v in a)}/{seeds} seeds")
        arm["_headline"] = {"auth_miss": float(np.mean(a)),
                            "none_miss": float(np.mean(b)), "p": float(p),
                            "auth_zero_seeds": int(sum(v == 0.0 for v in a))}
        out[model] = arm
    out["_check"] = check_committed(
        f"results/priority_defence_{scen}.json",
        {k: v for k, v in out["heinzelman"].items() if not k.startswith("_")})
    return out


def exp_greed(scen: str, seeds: int, rounds: int) -> dict:
    """Finding 5: the restrained liar. Greed 0.50 is the headline row --
    detection at or below FPR while ~half the maximum deadline damage lands;
    0.18 and 1.00 anchor the ends."""
    out = {}
    for model in MODELS:
        print(f"\n--- {model}" + (f" (gamma={RADIO_EXP[scen]})"
                                  if model == "logdistance" else ""))
        print(f"{'greed':>6}{'defence':<8}{'dl-miss':>9}{'drain%':>8}"
              f"{'detect':>8}{'FPR':>7}")
        arm = {}
        for greed in (0.18, GREED_STEALTH, GREED_MAX):
            for d in ("none", "trust", "auth"):
                cfg = base_cfg(prio_args(scen, seeds, rounds),
                               attacker_frac=0.20, falsepriority_rate=greed,
                               **radio_kw(scen, model))
                m = mean_of([p_run_once(cfg, CHIRP, s, d)
                             for s in range(seeds)])
                arm[f"{greed}|{d}"] = m
                det = "-" if np.isnan(m["detect"]) else f"{m['detect']:.3f}"
                fpr = "-" if np.isnan(m["fpr"]) else f"{m['fpr']:.3f}"
                print(f"{greed:>6.2f}{d:<8}{m['ems_miss']:>9.3f}"
                      f"{m['drain_pct']:>8.2f}{det:>8}{fpr:>7}")
            print()
        half = (arm[f"{GREED_STEALTH}|none"]["ems_miss"]
                / max(arm[f"{GREED_MAX}|none"]["ems_miss"], 1e-12))
        arm["_headline"] = {
            "stealth_damage_frac": float(half),
            "stealth_detect": arm[f"{GREED_STEALTH}|trust"]["detect"],
            "stealth_fpr": arm[f"{GREED_STEALTH}|trust"]["fpr"],
            "auth_miss_at_stealth": arm[f"{GREED_STEALTH}|auth"]["ems_miss"],
            "auth_detect_at_stealth": arm[f"{GREED_STEALTH}|auth"]["detect"]}
        h = arm["_headline"]
        print(f"  greed 0.50: {half*100:.0f}% of max damage, detect "
              f"{h['stealth_detect']:.3f} vs FPR {h['stealth_fpr']:.3f}; "
              f"auth miss {h['auth_miss_at_stealth']:.3f} while its detector "
              f"sees {h['auth_detect_at_stealth']:.3f}")
        out[model] = arm
    out["_check"] = check_committed(
        f"results/priority_greed_{scen}.json",
        {k: v for k, v in out["heinzelman"].items() if not k.startswith("_")})
    return out


def exp_bypass(scen: str, seeds: int, rounds: int) -> dict:
    """Finding 2: the energy price of priority, no attackers.

    Radio-exposed twice over: the bypass forwards verbatim at head->RSU
    distances (the knee's favourite range), and the documented explanation
    for urban costing more than highway IS the d^2/d^4 knee. Under
    logdistance there is no knee, so if the explanation is right the
    urban/highway gap should narrow.
    """
    out = {}
    for model in MODELS:
        print(f"\n--- {model}" + (f" (gamma={RADIO_EXP[scen]})"
                                  if model == "logdistance" else ""))
        print(f"{'protocol':<10}{'bypass':>7}{'mJ/reading':>12}{'delay':>7}"
              f"{'dl-miss':>9}")
        arm = {}
        for name, cls in (("CSGD-NET", CSGDNet), ("CHIRP", CHIRP)):
            base = None
            for label, slots in (("off", 0), ("on", 1)):
                cfg = base_cfg(prio_args(scen, seeds, rounds),
                               emergency_slots=slots, attacker_frac=0.0,
                               **radio_kw(scen, model))
                m = mean_of([p_run_once(cfg, cls, s) for s in range(seeds)])
                arm[f"{name}|{label}"] = m
                delta = ("" if base is None
                         else f"  ({(m['mJ_per_reading']/base-1)*100:+.2f}%)")
                if base is None:
                    base = m["mJ_per_reading"]
                print(f"{name:<10}{label:>7}{m['mJ_per_reading']:>12.4f}"
                      f"{m['ems_delay']:>7.2f}{m['ems_miss']:>9.3f}{delta}")
        for name in ("CSGD-NET", "CHIRP"):
            arm[f"_cost_{name}"] = (arm[f"{name}|on"]["mJ_per_reading"]
                                    / arm[f"{name}|off"]["mJ_per_reading"]
                                    - 1) * 100
        out[model] = arm
    out["_check"] = check_committed(
        f"results/priority_bypass_{scen}.json",
        {k: v for k, v in out["heinzelman"].items() if not k.startswith("_")})
    return out


def exp_freeride(scen: str, seeds: int, rounds: int) -> dict:
    """Module 2's free ride: detected attackers end with 2.0-2.4x the
    residual energy of honest nodes, because demotion spares them the head
    role. Head cost is dominated by RX + aggregation, which no path-loss
    model touches -- but the forward leg it also skips is pure radio, so the
    ratio can legitimately move. Urban only, like docs/module2.md.
    """
    kinds = ("blackhole", "greyhole", "onoff", "badmouth", "ballot")
    variants = [("CSGD-NET", CSGDNet, False),
                ("CHIRP (no trust)", CHIRP, False),
                ("CHIRP + trust", CHIRP, True)]
    out = {}
    for model in MODELS:
        print(f"\n--- {model}" + (f" (gamma={RADIO_EXP[scen]})"
                                  if model == "logdistance" else ""))
        print(f"{'att%':>5}{'protocol':<18}{'PDR':>7}{'Eadv':>7}"
              f"{'att CH%':>9}{'detect':>8}{'rnds':>6}")
        arm = {}
        for frac in FREERIDE_FRACS:
            for label, cls, wt in variants:
                cfg = Config(max_rounds=rounds, attacker_frac=frac,
                             attack_kinds=kinds, **SCENARIOS[scen],
                             **radio_kw(scen, model))
                runs = [m2_run_once(cfg, cls, s, wt) for s in range(seeds)]
                # mean_of, not a hand-rolled nanmean: it documents ttd=NaN as a
                # legitimate "not applicable" and suppresses the resulting
                # all-NaN-slice RuntimeWarning in one place.
                m = mean_of(runs)
                arm[f"{frac}|{label}"] = m
                det = "-" if np.isnan(m["detect"]) else f"{m['detect']:.3f}"
                print(f"{frac*100:>5.0f}{label:<18}{m['pdr']:>7.3f}"
                      f"{m['e_adv']:>7.2f}{m['att_ch_share']*100:>9.1f}"
                      f"{det:>8}{m['rounds']:>6.0f}")
            print()
        e = [arm[f"{f}|CHIRP + trust"]["e_adv"] for f in FREERIDE_FRACS]
        arm["_headline"] = {"e_adv_min": float(min(e)),
                            "e_adv_max": float(max(e))}
        print(f"  CHIRP+trust attacker/honest residual energy: "
              f"{min(e):.2f}-{max(e):.2f}x")
        out[model] = arm
    out["_check"] = check_committed(
        f"results/module2_{scen}.json",
        {k: v for k, v in out["heinzelman"].items() if not k.startswith("_")})
    return out


def exp_module1(scen: str, seeds: int, rounds: int) -> dict:
    """Module 1's protocol table and the CHIRP vs CSGD-NET significance runs.

    The most radio-exposed experiment in the project: CHIRP's objective
    scores tx_energy(d) directly, so changing the model changes the
    optimisation landscape itself, not just the bill.
    """
    out = {}
    for model in MODELS:
        print(f"\n--- {model}" + (f" (gamma={RADIO_EXP[scen]})"
                                  if model == "logdistance" else ""))
        cfg = Config(max_rounds=rounds, **SCENARIOS[scen],
                     **radio_kw(scen, model))
        print(f"{'protocol':<10}{'FND':>7}{'HND':>7}{'LND':>7}"
              f"{'mJ/reading':>12}{'orphan%':>9}{'intra m':>9}")
        raw, arm = {}, {}
        for name, cls in PROTOCOLS.items():
            runs = [m1_run_once(cfg, cls, s) for s in range(seeds)]
            raw[name] = runs
            arm[name] = {k: float(np.mean([r[k] for r in runs]))
                         for k in runs[0]}
            d = arm[name]
            print(f"{name:<10}{d['fnd']:>7.1f}{d['hnd']:>7.1f}"
                  f"{d['lnd']:>7.1f}{d['mj_per_reading']:>12.4f}"
                  f"{d['orphan']*100:>9.1f}{d['intra']:>9.1f}")
        # Same helper run_module1 uses for the docs/module1.md table, so the
        # two runners cannot disagree about direction or effect size.
        sig = compare_runs(raw["CHIRP"], raw["CSGD-NET"])
        for metric, st in sig.items():
            print(f"  {metric:<15} CHIRP {st['a']:>9.2f}  "
                  f"CSGD-NET {st['b']:>9.2f}  {st['delta_pct']:>+7.1f}%  "
                  f"p={st['p']:.4f}"
                  f"{'  significant' if st['p'] < 0.05 else '  ns'}")
        arm["_chirp_vs_csgd"] = sig
        out[model] = arm
    out["_check"] = check_committed(
        f"results/module1_{scen}.json",
        {k: v for k, v in out["heinzelman"].items() if not k.startswith("_")})
    return out


def exp_ablation(scen: str, seeds: int, rounds: int) -> dict:
    """The fitness ablation behind the intra-term claim -- Eq. 9's missing
    term is the second most load-bearing. The knee is what made distant
    members so expensive; with gamma = 2 there is no knee at all, which is
    the harshest test the intra term can face."""
    terms = ABLATION_TERMS
    base = Config(max_rounds=rounds, **SCENARIOS[scen])
    full = {t: getattr(base, t) for t in terms}
    out = {}
    for model in MODELS:
        print(f"\n--- {model}" + (f" (gamma={RADIO_EXP[scen]})"
                                  if model == "logdistance" else ""))
        print(f"{'dropped':<12}{'FND':>7}{'HND':>7}{'mJ/reading':>13}"
              f"{'orphan%':>10}{'intra m':>9}")
        arm = {}
        for drop in [None] + terms:
            # shared with run_module1.py --ablate, so both build the same
            # objective by construction rather than by textual coincidence
            w = ablation_weights(full, drop)
            cfg = Config(max_rounds=rounds, **w, **SCENARIOS[scen],
                         **radio_kw(scen, model))
            runs = [m1_run_once(cfg, CHIRP, sd) for sd in range(seeds)]
            m = {k: float(np.mean([r[k] for r in runs])) for k in runs[0]}
            arm[drop or "none (full)"] = m
            label = "none (full)" if drop is None else drop.replace("w_", "")
            print(f"{label:<12}{m['fnd']:>7.1f}{m['hnd']:>7.1f}"
                  f"{m['mj_per_reading']:>13.4f}{m['orphan']*100:>10.1f}"
                  f"{m['intra']:>9.1f}")
        ref = arm["none (full)"]
        arm["_deltas"] = {
            t: {"fnd_pct": (arm[t]["fnd"] / ref["fnd"] - 1) * 100,
                "mj_pct": (arm[t]["mj_per_reading"] / ref["mj_per_reading"]
                           - 1) * 100,
                "intra_pct": (arm[t]["intra"] / ref["intra"] - 1) * 100}
            for t in terms}
        d = arm["_deltas"]
        print("  dropping a term, vs the full objective:")
        for t in terms:
            print(f"    {t.replace('w_', ''):<9} FND {d[t]['fnd_pct']:+6.1f}%"
                  f"   mJ/reading {d[t]['mj_pct']:+6.2f}%"
                  f"   intra {d[t]['intra_pct']:+6.1f}%")
        out[model] = arm
    # No check against results/module1_ablation_*.json: that file is kept
    # HISTORICAL evidence -- it was produced by the pre-reallocation objective
    # (w_let = 0.25, stability-triggered re-clustering, elect/rd 0.79) whose
    # measurements SET today's defaults, and regenerating it would erase the
    # evidence for the weights. This experiment ablates the CURRENT defaults
    # under both radio models; its heinzelman arm is validated instead by
    # running `run_module1.py --ablate` from a scratch cwd and diffing.
    return out


def exp_expsweep(scen: str, seeds: int, rounds: int) -> dict:
    """Is anything sensitive to the exponent CHOICE inside the urban bracket?
    CHIRP vs CSGD-NET headline deltas at gamma across [2.0, 3.0]. If the
    signs hold across the sweep, the bracket choice is a free parameter."""
    out = {}
    print(f"\n{'gamma':>6}{'':>2}{'FND d%':>8}{'HND d%':>8}{'mJ d%':>8}"
          f"{'orphan d%':>11}{'intra d%':>10}")
    for gamma in EXPSWEEP_GAMMAS:
        cfg = Config(max_rounds=rounds, **SCENARIOS[scen],
                     radio_model="logdistance", path_loss_exp=gamma)
        ra = [m1_run_once(cfg, CHIRP, s) for s in range(seeds)]
        rb = [m1_run_once(cfg, CSGDNet, s) for s in range(seeds)]
        deltas = {}
        for metric in ("fnd", "hnd", "mj_per_reading", "orphan", "intra"):
            a = np.mean([r[metric] for r in ra])
            b = np.mean([r[metric] for r in rb])
            deltas[metric] = float((a - b) / b * 100) if b else float("nan")
        out[f"gamma={gamma}"] = deltas
        print(f"{gamma:>6.2f}{'':>2}{deltas['fnd']:>+8.1f}"
              f"{deltas['hnd']:>+8.1f}{deltas['mj_per_reading']:>+8.1f}"
              f"{deltas['orphan']:>+11.1f}{deltas['intra']:>+10.1f}")
    return out


def exp_calibration(scen=None, seeds=0, rounds=0) -> dict:
    """The two models side by side on one packet -- the table in docs/radio.md.

    Analytic, like exp_crypto: takes the dispatcher's uniform signature and
    uses none of it. Exists because the calibration table in docs/radio.md
    must be reproducible by a committed command like every other table in
    docs/ -- it demonstrates the one property the whole comparison rests on,
    that eps_ld = eps_fs * d0^(2-gamma) makes both models charge the SAME
    amplifier energy at d0, so their difference is tail behaviour and not
    scale. If the calibration is ever changed, re-running this shows it.
    """
    del scen, seeds, rounds
    ref = Config()
    k = ref.packet_bits
    models = {
        "heinzelman": ref,
        "logdist g=2.0": Config(radio_model="logdistance", path_loss_exp=2.0),
        "logdist g=3.0": Config(radio_model="logdistance", path_loss_exp=3.0),
    }
    print(f"\nOne {k}-bit packet, mJ to transmit, and the ratio to Heinzelman.")
    print(f"Calibration: eps_ld = eps_fs * d0^(2-gamma), so every model agrees "
          f"at d0 = {ref.d0:.2f} m.\n")
    print(f"  {'d (m)':>8}" + "".join(f"{n:>22}" for n in models))
    out = {"packet_bits": k, "d0_m": float(ref.d0), "rows": {}}
    for d in (30.0, 60.0, float(ref.d0), 90.0, 120.0, 150.0, 200.0, 300.0):
        base = float(tx_energy(ref, k, d)) * 1e3
        row, rec = f"  {d:>8.2f}", {}
        for name, cfg in models.items():
            mj = float(tx_energy(cfg, k, d)) * 1e3
            rec[name] = {"mJ": mj, "ratio_vs_heinzelman": mj / base}
            row += f"{mj:>13.4f} (x{mj / base:.2f})"
        out["rows"][f"{d:g}"] = rec
        print(row)
    agree = {n: r["ratio_vs_heinzelman"]
             for n, r in out["rows"][f"{float(ref.d0):g}"].items()}
    out["agree_at_d0"] = all(abs(v - 1.0) < 1e-12 for v in agree.values())
    print(f"\n  all models identical at d0: {out['agree_at_d0']}"
          f"   (ratios {', '.join(f'{v:.6f}' for v in agree.values())})")
    print("  Below d0 the logdistance g=3 curve is CHEAPER than free space and "
          "above it\n  far cheaper than d^4 -- that gap is the whole "
          "robustness question.")
    return out


BENCH_PATH = "results/crypto_bench.json"


def exp_crypto(scen=None, seeds=0, rounds=0) -> dict:
    """Module 3b's ratio re-priced: ECDSA verification vs transmitting the
    signature it checks, under each radio model.

    Pure computation on measured inputs -- no simulation, so this takes the
    dispatcher's uniform (scen, seeds, rounds) and uses none of them; it is
    registered analytic=True so its _meta claims no seed count. Timings come
    from the committed results/crypto_bench.json; radio cost from tx_energy
    under each model. The documented claim ("~15x at 90 m, 25x OBU slowdown,
    0.5 W") has radio energy in its DENOMINATOR, so of the six findings this
    is the one with a direct mechanical dependence on the model.
    """
    del scen, seeds, rounds
    p = Path(BENCH_PATH)
    if not p.exists():
        print(f"  [crypto] {BENCH_PATH} not found -- run this from the repo "
              f"root, or `python3 src/crypto_bench.py` to generate it")
        return {"_check": {"committed": BENCH_PATH, "status": "missing"}}
    bench = json.loads(p.read_text())
    verify_us = bench["ecdsa"]["verify_us"]
    sig_bits = bench["sig_bits_digest"]
    slowdown, cpu_w = 25, 0.5            # the documented OBU assumption
    verify_mj = verify_us * slowdown * 1e-6 * cpu_w * 1e3

    cfgs = {"heinzelman": Config(),
            "logdistance g=2.0 (highway)": Config(radio_model="logdistance",
                                                  path_loss_exp=2.0),
            "logdistance g=3.0 (urban)": Config(radio_model="logdistance",
                                                path_loss_exp=3.0)}
    print(f"\nECDSA P-256 verify, {slowdown}x OBU slowdown, {cpu_w} W: "
          f"{verify_mj:.3f} mJ  (measured {verify_us:.1f} us)")
    print(f"vs transmitting the {sig_bits}-bit class-2 overhead:\n")
    print(f"{'model':<28}"
          + "".join(f"{d:>9} m" for d in (60, 90, 120, 150, 200, 300))
          + f"{'break-even':>12}")
    out = {"verify_mJ": verify_mj, "assumptions":
           {"obu_slowdown": slowdown, "cpu_w": cpu_w,
            "verify_us_measured": verify_us, "sig_bits": sig_bits}}
    for name, cfg in cfgs.items():
        row, ratios = f"{name:<28}", {}
        for d in (60, 90, 120, 150, 200, 300):
            tx = float(tx_energy(cfg, sig_bits, float(d))) * 1e3
            ratios[str(d)] = {"tx_mJ": tx, "ratio": verify_mj / tx}
            row += f"{verify_mj / tx:>8.1f}x"
        # distance at which the radio catches up with the computation,
        # solved rather than scanned -- no grid resolution, no upper cap
        be = break_even_distance(cfg, sig_bits, verify_mj)
        row += f"{be:>10.0f} m"
        print(row)
        out[name] = {"ratios": ratios, "break_even_m": be}
    print("\nBreak-even = distance beyond which sending the signature costs "
          "more than verifying it.\nHeinzelman's d^4 branch inflates the "
          "radio side, so it is the CONSERVATIVE model for\nthe "
          "computation-dominates claim; removing the knee extends compute "
          "dominance further out.")
    return out


class Exp(NamedTuple):
    """One registered experiment.

    `rounds` is an int, or a {scenario: rounds} mapping when the documented
    command differs per scenario -- resolved uniformly in main() so no
    experiment needs a special case there. `gammas` overrides the scenario's
    default exponent for the metadata when an experiment sweeps it. `analytic`
    marks a run with no simulation, so its _meta claims no seeds or rounds.
    """
    fn: Any
    seeds: int
    rounds: Any                     # int, or {scenario: int}
    scenarios: tuple
    analytic: bool = False
    gammas: Any = None              # None -> RADIO_EXP[scenario]

    def rounds_for(self, scen):
        return self.rounds[scen] if isinstance(self.rounds, dict) else self.rounds

    def gammas_for(self, scen):
        return list(self.gammas) if self.gammas else RADIO_EXP.get(scen)


EXPERIMENTS = {
    "coverage": Exp(exp_coverage, 6, 40, ("urban", "highway")),
    "defence": Exp(exp_defence, 12, 60, ("urban", "highway")),
    "greed": Exp(exp_greed, 12, 60, ("urban", "highway")),
    "bypass": Exp(exp_bypass, 12, 60, ("urban", "highway")),
    "freeride": Exp(exp_freeride, 12, 60, ("urban",)),
    # the documented commands use 150 rounds in urban, 120 on the highway
    "module1": Exp(exp_module1, 20, {"urban": 150, "highway": 120},
                   ("urban", "highway")),
    "ablation": Exp(exp_ablation, 10, 120, ("highway",)),
    "expsweep": Exp(exp_expsweep, 10, 150, ("urban",),
                    gammas=EXPSWEEP_GAMMAS),
    "calibration": Exp(exp_calibration, 0, 0, (None,), analytic=True),
    "crypto": Exp(exp_crypto, 0, 0, (None,), analytic=True),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", choices=[*EXPERIMENTS, "all"],
                    required=True)
    ap.add_argument("--scenario", choices=["urban", "highway", "both"],
                    default="both")
    ap.add_argument("--seeds", type=int, default=0,
                    help="override the documented seed count (smoke tests)")
    ap.add_argument("--dry", action="store_true",
                    help="do not write results/ (smoke tests; see the "
                         "handoff's smoke-test trap)")
    args = ap.parse_args()

    todo = list(EXPERIMENTS) if args.experiment == "all" else [args.experiment]
    failures = []
    for name in todo:
        exp = EXPERIMENTS[name]
        seeds = args.seeds or exp.seeds
        for scen in exp.scenarios:
            if scen is not None and args.scenario != "both" \
                    and scen != args.scenario:
                continue
            r = exp.rounds_for(scen)
            hdr = f"{name}" + (f" -- {scen}" if scen else "")
            if scen:
                hdr += (f", {seeds} seeds, logdistance gamma="
                        f"{exp.gammas_for(scen)}")
            print(f"\n{'=' * 74}\n{hdr}\n{'=' * 74}")
            out = exp.fn(scen, seeds, r)
            meta = {"experiment": name, "scenario": scen,
                    "generated_by": "src/run_radio.py"}
            if not exp.analytic:
                meta.update(seeds=seeds, rounds=r,
                            path_loss_exp=exp.gammas_for(scen))
            out["_meta"] = meta

            # The guardrail ENFORCES: a drifted mirror must not be able to
            # regenerate the docs silently. Anything but OK is a failure, and
            # that includes a check that could not run at all.
            status = (out.get("_check") or {}).get("status")
            if status not in (None, "OK"):
                failures.append(f"{name}" + (f"/{scen}" if scen else "")
                                + f": {status}")

            if not args.dry:
                Path("results").mkdir(exist_ok=True)
                tag = f"radio_{name}" + (f"_{scen}" if scen else "")
                Path(f"results/{tag}.json").write_text(
                    json.dumps(out, indent=2))
                print(f"\nwrote results/{tag}.json")

    if failures:
        print(f"\n{'=' * 74}\nGUARDRAIL FAILED -- a heinzelman arm no longer "
              f"reproduces the committed\nresults it mirrors, so the "
              f"logdistance arm proves nothing:\n")
        for f in failures:
            print(f"  {f}")
        print("\nFix the mirror before trusting or regenerating any table in "
              "docs/radio.md.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
