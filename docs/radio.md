# Radio-model robustness — do the findings survive 802.11p path loss?

The project inherits the Heinzelman first-order radio from the base paper:
amplifier energy `eps_fs*d^2` below d0 = 87.71 m and `eps_mp*d^4` above it.
That model was designed for short-range sensor motes. At VANET distances
(100–150 m) the d^4 branch makes long links enormously expensive and absolute
lifetimes unrealistically short — `docs/module1.md` concedes it, and a
reviewer can compress the concession into one sentence: *"your findings may be
artifacts of an unrealistic energy model."*

This module answers that sentence with measurements. Every experiment behind
the six headline findings was re-run under a realistic log-distance path-loss
model with no knee, on paired seeds, and the deltas tabulated by a committed
runner (`src/run_radio.py`).

**Verdict table** — details in the numbered sections below.

| # | finding | verdict |
|---|---|---|
| 1 | coverage and deadline latency oppose (`priority.md` f.1) | **held** (ρ ≤ −0.89 both models) |
| 2 | priority is a DoS surface; authorisation → 0.000 (`priority.md` f.3) | **held** (0.000 in 12/12 seeds, both models) |
| 3 | trust demotion pays the attacker 2.0–2.4× (`module2.md`) | **held, stronger**: 2.21–3.02× |
| 4 | the restrained liar is invisible and still harmful (`priority.md` f.5) | **held** (45–47 % of max damage at detect ≤ FPR) |
| 5 | Module 1 protocol ordering + intra/energy ablation (`module1.md`) | **held** (same ordering, same significance pattern) |
| 6 | crypto cost is computation, not bytes (`module3b.md`) | **held, stronger**: break-even 200 → 263–454 m |

One documented *explanation* is model-dependent and is re-scoped below: the
urban-vs-highway gap in the cost of priority (`priority.md` finding 2) comes
from the d^4 knee and collapses without it. The claim it supported ("the
bypass buys 0.000 deadline-miss for under 2 % of energy") survives in both
scenarios under both models — it just stops being more expensive in the city.

## The alternative model

`src/energy.py`, selected by `Config.radio_model = "logdistance"`:

    amp(d) = eps_ld * d^gamma,      eps_ld = eps_fs * d0^(2 - gamma)

**Calibration, stated explicitly:** `eps_ld` is chosen so both models charge
the same amplifier energy at d0 = 87.71 m — the one distance where
Heinzelman's own two branches agree. The models are therefore comparable
rather than arbitrarily scaled, and every difference between them is the tail
behaviour, which is exactly the contested part. With gamma = 2 the model *is*
the free-space branch extended over all distances.

Exponents, from the 5.9 GHz V2V measurement literature: **highway gamma = 2.0**
(LOS; measured 1.8–2.1, so 2.0 is mildly conservative) and **urban gamma =
3.0** (the harsh end of the 2.7–3.0 street-canyon bracket). What this does to
a 6400-bit transmission (`--experiment calibration`, which also asserts the
d0 agreement rather than leaving it to be trusted):

| d | Heinzelman | logdist γ=2 | logdist γ=3 |
|---|---|---|---|
| 60 m | 0.5504 mJ | 0.5504 (×1.00) | 0.4776 (×0.87) |
| 87.71 m | 0.8123 mJ | 0.8123 (×1.00) | 0.8123 (×1.00) |
| 150 m | 4.5320 mJ | 1.7600 (×0.39) | 2.7828 (×0.61) |
| 300 m | 67.712 mJ | 6.0800 (×0.09) | 20.022 (×0.30) |

What deliberately does **not** change: E_RX, aggregation and the electronics
term (receiver/processing, not propagation), TDMA capacity, the trust engine,
and every delay figure — delay is TDMA slots and the radio model prices
energy, not time, so no result here acquires milliseconds.

The exponent choice inside the urban bracket is a free parameter, shown
rather than asserted (`--experiment expsweep`, CHIRP vs CSGD-NET deltas,
10 seeds):

| gamma | FND Δ% | HND Δ% | mJ Δ% | orphan Δ% | intra Δ% |
|---|---|---|---|---|---|
| 2.00 | −6.2 | +5.3 | −5.4 | −82.8 | −14.5 |
| 2.50 | −4.1 | +5.5 | −6.5 | −81.3 | −11.4 |
| 2.75 | +1.4 | +8.9 | −8.5 | −83.0 | −13.4 |
| 3.00 | −2.3 | +10.2 | −8.8 | −80.9 | −12.9 |

Every significant delta keeps its sign across the whole bracket; FND wobbles
around zero exactly as its "statistically indistinguishable" status predicts.

## Method, and the guardrail

Paired seeds: mobility consumes only `Network.rng` and never sees energy, so
the same seed gives the same roads, speeds, attackers and traffic under both
models. The comparison is end-to-end, not a re-billing — CHIRP's objective
scores `tx_energy(d)` directly, so the election re-optimises against the new
cost landscape.

Every experiment's heinzelman arm re-derives a committed `results/*.json`
through the same code path and is checked float-for-float. All checks passed
identically: module1 56/56 per scenario, defence 72/72, greed 108/108,
coverage 28/28, bypass 48/48, freeride 96/96. **Exception, documented:**
`results/module1_ablation_highway.json` is *historical* evidence — it was
produced by the pre-reallocation objective (w_let = 0.25,
stability-triggered re-clustering, elect/rd 0.79) whose measurements set
today's weights, so today's command cannot and should not reproduce it. The
ablation here re-runs the **current** defaults under both models; its
heinzelman arm was validated instead against a fresh
`run_module1.py --ablate` run (identical to the last float).

## 1 — coverage vs deadline latency: held

6 seeds, reservation disabled, deadline 4 slots. Spearman rank correlation
between orphan rate and EMS deadline-miss across the seven protocols:

| | heinzelman | logdistance |
|---|---|---|
| urban | ρ = −0.964 (p = 0.0005) | ρ = −0.964 (p = 0.0005) |
| highway | ρ = −0.893 (p = 0.0068) | ρ = −0.964 (p = 0.0005) |

HEED still buys the best emergency latency with the worst coverage (urban
dl-miss 0.307 at 50.0 % orphans under log-distance); CHIRP is still the
reverse (0.891 at 3.9 %). The mechanism never contained an energy term —
orphans skip fusion, and that is topology — and the radio only decides who
dies when. Module 1's headline win remains a latency loss under both models.

## 2 — the DoS surface, and authorisation: held

12 seeds, CHIRP, 20 % attackers asserting at rate 1.0.

| | | dl-miss | drain % | detect | FPR |
|---|---|---|---|---|---|
| urban | hein, none | 0.437 | 11.26 | — | — |
| | hein, auth | **0.000** | 0.00 | 0.937 | 0.015 |
| | logd, none | 0.448 | 10.13 | — | — |
| | logd, auth | **0.000** | 0.00 | 0.950 | 0.016 |
| highway | hein, none | 0.472 | 6.01 | — | — |
| | hein, auth | **0.000** | 0.00 | 1.000 | 0.007 |
| | logd, none | 0.475 | 6.00 | — | — |
| | logd, auth | **0.000** | 0.00 | 1.000 | 0.011 |

Authorisation is 0.000 in 12/12 seeds under both models (p = 5.1e-06, the
minimum attainable at n = 12 — quote the difference, not the p). Trust still
roughly halves the damage without removing it (0.230/0.244 under
log-distance). The attack is an arbitration problem; the radio only prices
the stolen forwards, which is why the drain barely moves.

The documented "drain is half as bad on the highway" survives but its stated
mechanism was partly the knee: the urban/highway drain ratio narrows from
1.87× (11.26/6.01) to 1.69× (10.13/6.00). What remains of the gap is RSU
spacing itself — urban heads are simply farther from an RSU, at any exponent.

## 3 — the energy free ride: held, and stronger

12 seeds, urban, mixed Layer-A adversary. Attacker/honest mean residual
energy at the evaluation cutoff, CHIRP + trust:

| attacker % | heinzelman | logdistance γ=3 |
|---|---|---|
| 10 | 1.98 | 2.21 |
| 20 | 2.11 | 2.55 |
| 30 | 2.41 | 2.87 |
| 40 | 2.43 | 3.02 |

The free ride **grows** under the realistic model, and the mechanism explains
why: what demotion spares the attacker is the head role, whose cost is
dominated by receive + aggregation — distance-independent terms no path-loss
model touches — while the ordinary transmissions everyone pays get cheaper.
The distance-independent core of the head's bill becomes a *larger* fraction
of total spend, so exclusion is worth more. Detection (0.86–0.90), the PDR
win (0.960 vs 0.935 at 20 %), and attacker-CH suppression all hold.
Consequence unchanged and sharpened: a demotion-based defence cannot be
validated on energy metrics under either radio model.

## 4 — the restrained liar: held

12 seeds, 20 % attackers, greed swept. Under log-distance:

| greed | defence | dl-miss (urb/hwy) | detect (urb/hwy) | FPR (urb/hwy) |
|---|---|---|---|---|
| 0.50 | none | 0.201 / 0.222 | — | — |
| 0.50 | trust | 0.208 / 0.231 | 0.021 / 0.013 | 0.022 / 0.009 |
| 0.50 | auth | **0.000 / 0.000** | 0.021 / 0.017 | — |
| 1.00 | none | 0.448 / 0.475 | — | — |
| 1.00 | trust | 0.230 / 0.244 | 0.958 / 0.996 | 0.011 / 0.012 |

At greed 0.50 the attacker still takes **45 % (urban) and 47 % (highway) of
the maximum deadline damage** while detection sits at or below the
false-positive rate (0.021 vs 0.022 urban) — against 47 %/48 % documented.
Trust is still marginally *worse* than no defence at the stealth point, the
detection step function still sits between 0.50 and 0.75, and authorisation
still delivers 0.000 while its own behavioural detector is blind (0.021).
The claim was behavioural, not energetic, and behaves that way.

## 5 — Module 1's ordering and ablation: held

20 seeds. Urban under γ = 3.0 — the full seven-protocol table is in
`results/radio_module1_urban.json`; the energy-per-reading **ordering is
identical** to Heinzelman's (LEACH-C < CHIRP < PSO < GA < CSGD-NET < LEACH <
HEED), and CHIRP vs CSGD-NET keeps every direction and significance:

| metric | heinzelman | logdistance γ=3 |
|---|---|---|
| FND | +0.0 %, p = 0.54 (ns) | −2.0 %, p = 0.74 (ns) |
| HND | +14.6 %, p < 0.0001 | +10.8 %, p < 0.0001 |
| mJ/reading | −11.7 %, p < 0.0001 | −9.3 %, p < 0.0001 |
| orphan | −82.7 %, p < 0.0001 | −80.0 %, p < 0.0001 |
| intra | −8.1 %, p = 0.0001 | −12.7 %, p < 0.0001 |

Absolute lifetimes stretch about 30 % (CHIRP FND 9.4 → 12.5 rounds), which is
the acknowledged artifact correcting itself — and why absolute round counts
were never quoted as OBU lifetimes.

The highway is a near no-op (FND +46.0 % → +42.5 %; everything else within a
point; HEED and LEACH-C still beat CHIRP on raw FND). That is itself a
finding: with 5 RSUs per km, heads sit inside the 87.71 m knee where the two
models coincide, so **the highway results never depended on the d^4 branch at
all**.

Ablation (highway, 10 seeds, current defaults, both models):

| dropped | FND Δ (hein) | FND Δ (logd) | mJ Δ (hein) | mJ Δ (logd) | intra Δ (hein) | intra Δ (logd) |
|---|---|---|---|---|---|---|
| energy | **−22.0 %** | **−21.0 %** | −2.2 % | −1.7 % | −10 % | −10 % |
| intra | −6.0 % | −1.3 % | **+2.5 %** | **+3.2 %** | **+15.9 %** | **+16.2 %** |
| rsu / let / balance | ≤ 4.7 % | ≤ 2.6 % | ≤ 0.3 % | ≤ 0.3 % | ≤ 1 % | ≤ 4 % |

Energy and intra remain the only load-bearing terms, and the intra term —
the term Eq. 9 omits, the central criticism of the base paper — costs slightly
*more* energy to drop under pure d² than under the knee model. The criticism
does not depend on the d^4 branch. (Intra's FND column is directional only;
at 10 seeds those differences are inside seed noise.)

## 6 — computation vs radio: held, and stronger

The one finding expected to be sensitive, because the documented ratio
("ECDSA verification ≈ 15× the radio cost of the signature it checks") has
radio energy in its denominator. Re-priced from the committed measurements
(`results/crypto_bench.json`: verify 97.4 µs; 25× OBU slowdown, 0.5 W →
1.217 mJ) against transmitting the 576-bit class-2 overhead:

| model | 90 m | 120 m | 150 m | 300 m | break-even |
|---|---|---|---|---|---|
| heinzelman | 15.6× | 6.6× | 3.0× | 0.2× | 200 m |
| logdistance γ=3 (urban) | 15.9× | 8.6× | 4.9× | 0.7× | 263 m |
| logdistance γ=2 (highway) | 16.1× | 10.9× | 7.7× | 2.2× | 454 m |

At the documented 90 m reference the ratio barely moves — the calibration
pins the models together near d0, and 90 m is 2 m past it. Everywhere else it
moves in the direction that *reinforces* the conclusion: the d^4 branch was
inflating the radio side of the ratio, so **Heinzelman is the conservative
model for the computation-dominates claim**. Removing the knee pushes the
break-even (the distance beyond which sending the signature costs more than
verifying it) from 200 m out to 263 m urban and 454 m highway — past any
plausible cluster radius in either scenario. The in-simulator side agrees:
the whole crypto layer stays statistically marginal under log-distance (the
bypass + MAC + signature cost is under 1 % in all four scenario × protocol
cells below).

## What moved: the cost of priority lost its urban premium

`priority.md` finding 2 reports the bypass costing +1.8 % (CHIRP) / +1.2 %
(CSGD-NET) in urban against +0.5 % / −0.1 % on the highway, and attributes
the gap to RSU density via the knee: urban heads transmit past d0 where
forwards cost d^4. That explanation is correct *within the Heinzelman model* —
and the model is exactly what makes it true. 12 seeds, no attackers:

| | CHIRP hein | CHIRP logd | CSGD-NET hein | CSGD-NET logd |
|---|---|---|---|---|
| urban | +1.85 % | +0.90 % | +1.16 % | −0.33 % (noise) |
| highway | +0.52 % | +0.96 % | −0.14 % (noise) | −0.25 % (noise) |

Under log-distance the urban premium vanishes — the bypass costs under 1 %
everywhere, and half the cells are statistically indistinguishable from zero
(the CSGD-NET negatives are the same seed noise the handoff already warns
about). Deadline-miss is 0.000 with the bypass in every cell of every model.

So: the *claim* ("priority costs a small single-digit percentage and buys
deadline-miss zero") holds and tightens; the *explanation* ("a deployment
that wants cheap priority should buy RSUs") is re-scoped to the Heinzelman
model. Under realistic path loss, priority is cheap at any of the RSU
densities tested, and the remaining urban/highway differences (e.g. the
attack-drain ratio, §2) come from RSU spacing, not from a knee.

## Limitations, stated

- **Log-distance is a mean-path-loss model, not a channel.** No shadowing
  variance, no fading, no loss/retransmission. This check re-prices energy;
  it does not add the 802.11p MAC, and delay remains in TDMA slots.
- **One exponent per scenario.** Real urban propagation mixes LOS and NLOS
  per link. The expsweep shows conclusions are stable across γ ∈ [2.0, 3.0],
  which brackets that mix in the mean; it does not model it per link.
- **Absolute joules are still not OBU-realistic.** The calibration
  deliberately anchors the alternative model to the paper's amplifier scale
  at d0, so cross-protocol orderings and deltas are the testable objects,
  not absolute lifetimes — same discipline as everywhere else in `docs/`.
- **Electronics unchanged.** `e_elec`/`e_da` are Heinzelman's values under
  both models; finding 3's growth with cheaper radio would only grow further
  if receive electronics were re-priced downward too.

## Reproduce

```bash
python3 src/run_radio.py --experiment all              # everything below, ~40 min
python3 src/run_radio.py --experiment coverage         # finding 1
python3 src/run_radio.py --experiment defence          # finding 2
python3 src/run_radio.py --experiment freeride         # finding 3
python3 src/run_radio.py --experiment greed            # finding 4
python3 src/run_radio.py --experiment module1          # finding 5 (ordering)
python3 src/run_radio.py --experiment ablation         # finding 5 (terms)
python3 src/run_radio.py --experiment crypto           # finding 6
python3 src/run_radio.py --experiment bypass           # the re-scoped f.2 cost
python3 src/run_radio.py --experiment expsweep         # exponent sensitivity
python3 src/run_radio.py --experiment calibration      # the two-model table above
```

Outputs land in `results/radio_*.json`, each carrying both arms, the
committed-file check, and the run metadata. `--seeds N --dry` smoke-tests
without writing. The default model is untouched: `radio_model = "heinzelman"`
everywhere else, and the regression gate passes 55/55 bit-identical with this
module in the tree.

**The runner exits non-zero if any heinzelman arm stops reproducing the
committed results it mirrors** — same convention as `formal/run_scyther.py`.
A check that compared nothing counts as a failure (`VACUOUS`), not a pass, so
renaming a result key cannot make the guardrail succeed by vacuity. Reduced
`--seeds` therefore fails by design: the mirrors are pinned to the documented
seed counts.
