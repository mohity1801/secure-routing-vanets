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

Delay stays in TDMA slots everywhere: the radio model prices energy, not
time, so no delay figure can change units here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy.stats import mannwhitneyu, spearmanr

sys.path.insert(0, str(Path(__file__).parent))

from config import Config                          # noqa: E402
from protocols.chirp import CHIRP                  # noqa: E402
from protocols.csgd_net import CSGDNet             # noqa: E402
from run_module1 import PROTOCOLS, SCENARIOS       # noqa: E402
from run_module1 import run_once as m1_run_once    # noqa: E402
from run_module2 import run_once as m2_run_once    # noqa: E402
import run_priority                                # noqa: E402
from run_priority import base_cfg, mean_of         # noqa: E402
from run_priority import run_once as p_run_once    # noqa: E402

# Log-distance exponent per scenario. 5.9 GHz V2V measurements put highway
# LOS at ~1.8-2.1 and urban streets at ~2.7-3.0; we take 2.0 and the harsh
# end of the urban bracket. expsweep() covers the rest of the bracket.
RADIO_EXP = {"highway": 2.0, "urban": 3.0}

MODELS = ("heinzelman", "logdistance")


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
def check_committed(path: str, mine: dict, model: str) -> dict:
    """Compare a heinzelman arm against the committed file it re-derives.

    Exact equality is the expectation, not a tolerance band: same seeds, same
    Config construction, same code path, and the regression gate already
    proves the default radio branch is bit-identical. Only keys present in
    both are compared (this runner deliberately runs a subset of some grids).
    """
    if model != "heinzelman":
        return {}
    p = Path(path)
    if not p.exists():
        print(f"  [check] {path} not found -- skipped")
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
    status = "OK" if not diffs else "MISMATCH"
    print(f"  [check vs {p.name}] {n_ok} values identical, "
          f"{len(diffs)} differ -> {status}")
    for k, f, rv, v in diffs[:6]:
        print(f"      {k}.{f}: committed {rv}  rerun {v}")
    return {"committed": path, "status": status, "n_identical": n_ok,
            "n_mismatch": len(diffs)}


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
        {k: v for k, v in out["heinzelman"].items() if not k.startswith("_")},
        "heinzelman")
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
        for frac in (0.0, 0.20):
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
        a, b = per_seed["0.2|auth"], per_seed["0.2|none"]
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
        {k: v for k, v in out["heinzelman"].items() if not k.startswith("_")},
        "heinzelman")
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
        for greed in (0.18, 0.50, 1.00):
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
        half = arm["0.5|none"]["ems_miss"] / max(arm["1.0|none"]["ems_miss"],
                                                 1e-12)
        arm["_headline"] = {
            "stealth_damage_frac": float(half),
            "stealth_detect": arm["0.5|trust"]["detect"],
            "stealth_fpr": arm["0.5|trust"]["fpr"],
            "auth_miss_at_stealth": arm["0.5|auth"]["ems_miss"],
            "auth_detect_at_stealth": arm["0.5|auth"]["detect"]}
        h = arm["_headline"]
        print(f"  greed 0.50: {half*100:.0f}% of max damage, detect "
              f"{h['stealth_detect']:.3f} vs FPR {h['stealth_fpr']:.3f}; "
              f"auth miss {h['auth_miss_at_stealth']:.3f} while its detector "
              f"sees {h['auth_detect_at_stealth']:.3f}")
        out[model] = arm
    out["_check"] = check_committed(
        f"results/priority_greed_{scen}.json",
        {k: v for k, v in out["heinzelman"].items() if not k.startswith("_")},
        "heinzelman")
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
        {k: v for k, v in out["heinzelman"].items() if not k.startswith("_")},
        "heinzelman")
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
        for frac in (0.1, 0.2, 0.3, 0.4):
            for label, cls, wt in variants:
                cfg = Config(max_rounds=rounds, attacker_frac=frac,
                             attack_kinds=kinds, **SCENARIOS[scen],
                             **radio_kw(scen, model))
                runs = [m2_run_once(cfg, cls, s, wt) for s in range(seeds)]
                m = {k: float(np.nanmean([r[k] for r in runs]))
                     for k in runs[0]}
                arm[f"{frac}|{label}"] = m
                det = "-" if np.isnan(m["detect"]) else f"{m['detect']:.3f}"
                print(f"{frac*100:>5.0f}{label:<18}{m['pdr']:>7.3f}"
                      f"{m['e_adv']:>7.2f}{m['att_ch_share']*100:>9.1f}"
                      f"{det:>8}{m['rounds']:>6.0f}")
            print()
        e = [arm[f"{f}|CHIRP + trust"]["e_adv"] for f in (0.1, 0.2, 0.3, 0.4)]
        arm["_headline"] = {"e_adv_min": float(min(e)),
                            "e_adv_max": float(max(e))}
        print(f"  CHIRP+trust attacker/honest residual energy: "
              f"{min(e):.2f}-{max(e):.2f}x")
        out[model] = arm
    out["_check"] = check_committed(
        f"results/module2_{scen}.json",
        {k: v for k, v in out["heinzelman"].items() if not k.startswith("_")},
        "heinzelman")
    return out


def exp_module1(scen: str, seeds: int, rounds: int) -> dict:
    """Module 1's protocol table and the CHIRP vs CSGD-NET significance runs.

    The most radio-exposed experiment in the project: CHIRP's objective
    scores tx_energy(d) directly, so changing the model changes the
    optimisation landscape itself, not just the bill.
    """
    metrics = (("fnd", "higher"), ("hnd", "higher"), ("mj_per_reading",
               "lower"), ("orphan", "lower"), ("intra", "lower"))
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
        sig = {}
        for metric, better in metrics:
            a = [r[metric] for r in raw["CHIRP"]]
            b = [r[metric] for r in raw["CSGD-NET"]]
            _, p = mannwhitneyu(
                a, b, alternative="greater" if better == "higher" else "less")
            ma, mb = float(np.mean(a)), float(np.mean(b))
            sig[metric] = {"chirp": ma, "csgd": mb,
                           "delta_pct": (ma - mb) / mb * 100 if mb else
                           float("nan"), "p": float(p)}
            print(f"  {metric:<15} CHIRP {ma:>9.2f}  CSGD-NET {mb:>9.2f}  "
                  f"{sig[metric]['delta_pct']:>+7.1f}%  p={p:.4f}"
                  f"{'  significant' if p < 0.05 else '  ns'}")
        arm["_chirp_vs_csgd"] = sig
        out[model] = arm
    out["_check"] = check_committed(
        f"results/module1_{scen}.json",
        {k: v for k, v in out["heinzelman"].items() if not k.startswith("_")},
        "heinzelman")
    return out


def exp_ablation(scen: str, seeds: int, rounds: int) -> dict:
    """The fitness ablation behind the intra-term claim -- Eq. 9's missing
    term is the second most load-bearing. The knee is what made distant
    members so expensive; with gamma = 2 there is no knee at all, which is
    the harshest test the intra term can face."""
    terms = ["w_energy", "w_rsu", "w_intra", "w_let", "w_balance"]
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
            w = dict(full)
            if drop:
                w[drop] = 0.0
            s = sum(w.values()) or 1.0
            w = {k: v / s * sum(full.values()) for k, v in w.items()}
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
    for gamma in (2.0, 2.5, 2.75, 3.0):
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


def exp_crypto(*_ignored) -> dict:
    """Module 3b's ratio re-priced: ECDSA verification vs transmitting the
    signature it checks, under each radio model.

    Pure computation on measured inputs -- no simulation. Timings come from
    the committed results/crypto_bench.json; radio cost from tx_energy under
    each model. The documented claim ("~15x at 90 m, 25x OBU slowdown,
    0.5 W") has radio energy in its DENOMINATOR, so of the six findings this
    is the one with a direct mechanical dependence on the model.
    """
    bench = json.loads(Path("results/crypto_bench.json").read_text())
    verify_us = bench["ecdsa"]["verify_us"]
    sig_bits = bench["sig_bits_digest"]
    slowdown, cpu_w = 25, 0.5            # the documented OBU assumption
    verify_mj = verify_us * slowdown * 1e-6 * cpu_w * 1e3

    cfgs = {"heinzelman": Config(),
            "logdistance g=2.0 (highway)": Config(radio_model="logdistance",
                                                  path_loss_exp=2.0),
            "logdistance g=3.0 (urban)": Config(radio_model="logdistance",
                                                path_loss_exp=3.0)}
    from energy import tx_energy
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
        # distance at which the radio catches up with the computation
        ds = np.linspace(1, 2000, 200_000)
        tx = np.asarray(tx_energy(cfg, sig_bits, ds), dtype=float) * 1e3
        idx = np.argmax(tx >= verify_mj)
        be = float(ds[idx]) if tx[idx] >= verify_mj else float("inf")
        row += f"{be:>10.0f} m"
        print(row)
        out[name] = {"ratios": ratios, "break_even_m": be}
    print("\nBreak-even = distance beyond which sending the signature costs "
          "more than verifying it.\nHeinzelman's d^4 branch inflates the "
          "radio side, so it is the CONSERVATIVE model for\nthe "
          "computation-dominates claim; removing the knee extends compute "
          "dominance further out.")
    return out


EXPERIMENTS = {
    "coverage": (exp_coverage, 6, 40, ("urban", "highway")),
    "defence": (exp_defence, 12, 60, ("urban", "highway")),
    "greed": (exp_greed, 12, 60, ("urban", "highway")),
    "bypass": (exp_bypass, 12, 60, ("urban", "highway")),
    "freeride": (exp_freeride, 12, 60, ("urban",)),
    "module1": (exp_module1, 20, None, ("urban", "highway")),   # rounds per scen
    "ablation": (exp_ablation, 10, 120, ("highway",)),
    "expsweep": (exp_expsweep, 10, 150, ("urban",)),
    "crypto": (exp_crypto, 0, 0, (None,)),
}
M1_ROUNDS = {"urban": 150, "highway": 120}      # the documented commands


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
    for name in todo:
        fn, seeds, rounds, scens = EXPERIMENTS[name]
        seeds = args.seeds or seeds
        for scen in scens:
            if scen is not None and args.scenario != "both" \
                    and scen != args.scenario:
                continue
            r = M1_ROUNDS[scen] if name == "module1" else rounds
            hdr = f"{name}" + (f" -- {scen}" if scen else "")
            if scen:
                hdr += (f", {seeds} seeds, logdistance gamma="
                        f"{RADIO_EXP[scen]}")
            print(f"\n{'=' * 74}\n{hdr}\n{'=' * 74}")
            out = fn(scen, seeds, r)
            out["_meta"] = {"experiment": name, "scenario": scen,
                            "seeds": seeds, "rounds": r,
                            "path_loss_exp": RADIO_EXP.get(scen),
                            "generated_by": "src/run_radio.py"}
            if not args.dry:
                Path("results").mkdir(exist_ok=True)
                tag = f"radio_{name}" + (f"_{scen}" if scen else "")
                Path(f"results/{tag}.json").write_text(
                    json.dumps(out, indent=2))
                print(f"\nwrote results/{tag}.json")


if __name__ == "__main__":
    main()
