# Technical handoff

State of the project at commit `8d4ec64`, branch `master`, working tree clean,
**no remote configured — nothing has ever been pushed.**

`CLAUDE.md` is the short orientation and is read automatically. This file is the
long version: what is done, what is decided, what is open, and what will bite you.

---

## 1. Where things stand

| module | state | evidence |
|---|---|---|
| Simulator core, radio, TDMA, setup-phase energy | **done** | `src/network.py`, `src/energy.py` |
| Six baselines + CHIRP | **done** | `src/protocols/`, `results/module1_*.json` |
| Reproduction audit of the base paper | **done** | `docs/reproducibility.md`, `src/verify_table4.py` |
| Module 1 — mobility + multi-metric CH election | **done** | `docs/module1.md`, 20 seeds, both scenarios |
| Module 2 — trust engine, 5 attack behaviours | **done** | `docs/module2.md`, 12 seeds |
| Module 3a — Scyther verification | **done** | `docs/module3.md`, 32 verified / 8 by design |
| Module 3b — measured crypto cost | **done** | `docs/module3b.md`, `results/crypto_bench.json` |
| Module 5 — priority traffic and its attack | **done** | `docs/priority.md`, 12–16 seeds, both scenarios |
| 802.11p path-loss robustness check | **done** | `docs/radio.md`, `src/run_radio.py`, six findings verified under both radio models |
| **Module 4 — RSU-side IDS** | **NOT STARTED** | see §5 |
| Figs. 11–15 regeneration | not started | listed in `README.md` |
| Report / paper draft / slides | not started | — |

**Every table in `docs/` is now produced by a committed command.** There are no
inline-script results left. The regression gate passes 55/55.

---

## 2. The invariant you must not break

`results/regression_reference.json` fingerprints 55 configurations to the exact
float bits — the full 100-node energy vector, PDR counters, per-round orphan and
intra-distance traces, and trust scores.

```bash
python3 src/regression_gate.py /tmp/now.json
python3 src/regression_gate.py --diff results/regression_reference.json /tmp/now.json
```

**Run it before and after any change to `src/`.**

It holds structurally because `Network._priority_phase()` returns immediately
when `self.traffic is None`, and the `TrafficModel` is attached by the *runner*,
never constructed inside `Network` — constructing it there would consume draws
from `self.rng` and shift every mobility trace. If you add anything to the
priority path, preserve both properties.

Why it matters: every headline claim is a *difference against a baseline*
("+1.8 % energy", "0.437 → 0.000 deadline-miss"). If the baseline drifts while a
feature is being built, each difference measures two changes at once and no
statistics can separate them.

---

## 3. Traps — things that have already caught us

**Do not commit smoke-test output.** Two `results/*.json` files were overwritten
by 3-seed runs done to check a runner still executed, and were committed. They
sat wrong for three commits before the extraction caught them. If you run a
reduced-seed sanity check, **restore the file afterwards or do not let it write**.

**`--bypass-cost` ratios mix two effects.** The aggregate MAC is charged in both
arms, so turning the bypass off does not turn crypto off. Use `--crypto-decomp`
for the clean separation. The CSGD-NET highway −0.1 % in that table is noise.

**Changing `config.py` defaults invalidates documented tables.** `sig_bits` and
`mac_bits` went 0 → 576/128 in Module 3b and every Module 5 table had to be
re-run. The regression gate will *not* catch this, because it runs with no
traffic model. If you change a default that priority uses, re-run:
```bash
for s in urban highway; do
  python3 src/run_priority.py --scenario $s --seeds 6  --rounds 40 --coverage-latency
  python3 src/run_priority.py --scenario $s --seeds 12 --bypass-cost
  python3 src/run_priority.py --scenario $s --seeds 12
  python3 src/run_priority.py --scenario $s --seeds 12 --sweep-greed
done
```

**Zsh arrays are 1-indexed.** Cost a round of mis-named diagram files.

**`p = 5.134e-06` is not an effect size.** With 12 seeds where one arm is 0.000
in every seed, the ranks separate completely and that is the minimum attainable
p at n = 12. Quote the deadline-miss difference (0.437 → 0.000) as the effect.

**Numbers that must never be quoted as current** — all superseded:
urban bypass +2.1 %/+0.9 %; highway +0.4 %/+0.6 %; urban attack drain 10.41 %;
trust FPR cost 0.015; the pre-crypto coverage/latency table (HEED 46.8/4.22/0.273).

---

## 4. Conventions that look like sloppiness and are not

- **Disabled code paths are kept deliberately.** `w_survival = 0`,
  `assoc_let_weight = 0`, `recluster_max_rounds = 1` are all defaults *because
  the mechanism was tried and made things worse*, with the evidence in
  `docs/module1.md`. Do not delete them.
- **Delay is in TDMA slots, never milliseconds.** No channel, no time below the
  round. Same reason there is no throughput in Mbps, no jitter, no multi-hop
  latency — the topology is strictly member → CH → RSU.
- **Do not curve-fit to Table 4.** Its LEACH-C and CSGD-NET columns are not
  producible by the paper's own equations; only LEACH is a usable target. A
  ~300 m field would reproduce them, but Table 3 says 50 × 50 m. See
  `docs/reproducibility.md` finding 1.
- **Withdrawn claims stay visible.** The docs record what was believed, what the
  experiment showed, and why the claim changed. Do not tidy these into clean
  assertions — the corrections are part of the contribution.
- **Estimates stay labelled.** Everything about OBU computation energy is an
  extrapolation with stated assumptions, not a measurement.
- **`results/module1_ablation_*.json` are historical evidence, not
  reproducible outputs.** They were produced by the *pre-reallocation*
  objective (w_let = 0.25, stability-triggered re-clustering, elect/rd 0.79)
  and are the measurements that SET today's weights — re-running
  `run_module1.py --ablate` at current defaults gives different numbers
  (full-objective FND 23.2, not 16.2) and must not overwrite them. The
  current-defaults ablation, under both radio models, lives in
  `results/radio_ablation_highway.json`.

---

## 5. Open decision 1 — Module 4

**Intended:** RSU-side IDS, behavioural features → Random Forest / autoencoder,
with a revoke → trust-reset → exclude loop, validated on VeReMi.

**Actual state: nothing exists.** No `run_module4.py`, no `ids.py`, no
`docs/module4.md`, no `sklearn` import anywhere in `src/`. The only "VeReMi" in
the code is a docstring in `attacks.py` explaining what VeReMi does *not*
contain. (`scikit-learn` is in the README install line, provisioned and unused.)

**The case for cutting it**, from `docs/related_work.md`:
- Comparison paper P2 (*SN Computer Science* 2026) already runs RF-style ML on
  the same public VeReMi dataset from Kaggle.
- **VeReMi never simulated routing**, so it contains none of the Layer-A attacks
  this project actually defends against. Validating on it would prove little.
- Nothing else in the project depends on it.

**The case for building it:** Module 2 identified two remedies for the energy
free ride — *revocation rather than demotion*, and *duty rebalancing* — and both
were assigned to Module 4. They are the one unfinished thread from a headline
finding.

If cutting: say so in `README.md` and `docs/related_work.md`, and drop
`scikit-learn` from the install line. If building: the free-ride remedies are
the valuable half, not the classifier.

---

## 6. Open decision 2 — publication blockers

One resolved, one open. Neither blocked the BTP.

1. **Heinzelman radio at VANET distances — RESOLVED.** `docs/radio.md` /
   `src/run_radio.py` re-run the six headline findings under log-distance
   path loss with no knee (γ = 2.0 highway, 3.0 urban, calibrated to agree
   with Heinzelman at d0). All six hold; two get *stronger* (the free ride
   grows to 2.21–3.02×, the crypto break-even moves out to 263–454 m); the
   one thing that moved is an explanation, not a finding — the urban premium
   on the cost of priority was the d⁴ knee, and `docs/priority.md` finding 2
   is re-scoped accordingly. Default radio unchanged; gate still 55/55.
2. **Synthetic mobility — OPEN.** Both scenarios come from `src/mobility.py`,
   not SUMO. Comparison paper P3 uses SUMO + OSM + NS-2.35. A day or two of
   work, removes an easy reviewer objection.

Also open but lower priority: computation energy is measured and reported but
**not charged** in the simulator (charging it would move the Module 1 and 2
baselines); unlinkability is claimed as a design goal but not verified, because
Scyther cannot express it — ProVerif or Tamarin could.

**Framing, and this is the one to get right:** the base paper's §5 announces
that its own authors are building the mobility-aware version of CSGD-NET, which
is Module 1. **Module 1 must not be the headline.** Frame it as infrastructure
and lead with the security, priority and audit work — that survives even if
their paper lands first. See `docs/related_work.md`.

---

## 7. What is actually contributory

Mechanisms are mostly *not* novel — trust in a metaheuristic fitness, Beta
reputation, credibility weighting, ECC pseudonyms all have prior art, and
`docs/related_work.md` says so explicitly. Five findings are:

1. **Trust-based demotion pays the attacker** — 2.0–2.4× residual energy.
   Corollary: a trust defence cannot be validated on energy metrics.
2. **Priority is a DoS surface**, and a behavioural detector provably cannot
   separate a restrained liar from a real ambulance.
3. **Coverage and deadline latency are in direct opposition** — 7 protocols × 2
   scenarios.
4. **Crypto's cost is computation, not bytes** — invisible to a radio-only model.
5. **The reproduction audit** — Eq. 9 under-determined; Table 4's LEACH-C and
   CSGD-NET columns unreachable.

Plus the methodology: the controlled-optimiser comparison (CHIRP subclasses
CSGDNet, so a difference is attributable to the objective), the regression gate,
and four published negative results.

---

## 8. Fast orientation for a new session

```bash
cat CLAUDE.md                      # conventions and the invariant
cat docs/handoff.md                # this file
cat docs/related_work.md           # before any novelty claim
python3 src/regression_gate.py /tmp/now.json && \
  python3 src/regression_gate.py --diff results/regression_reference.json /tmp/now.json
git log --oneline                  # 7 commits, each with its findings in the message
```

The commit messages are written to be read — each carries the finding, not just
the change. `CHIRP_Complete_Project_Extraction.pdf` (79 pages) is the full
A-to-Z if you need depth, but it is a **snapshot at commit `07c9aec` + the
regeneration fix**; `docs/` and `results/` are canonical.

**Environment:** numpy, scipy, matplotlib. Scyther is *not* in the repo — get
v1.3.0 from github.com/cascremers/scyther (native macOS arm64 binary) and point
`$SCYTHER` at it. `openssl` CLI is used by `crypto_bench.py`.
