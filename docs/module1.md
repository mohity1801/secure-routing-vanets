# Module 1 — mobility-aware, multi-metric cluster-head election

Removes the base paper's static-topology assumption (Sect. 3.3, conceded as the
main limitation in Sect. 4.3) and replaces Eq. 9's two-term objective.

**Controlled comparison.** CHIRP subclasses `CSGDNet` and inherits the Cuckoo
Search engine — Levy flight, Gaussian walk, abandonment, iteration count — byte
for byte. Only the objective and the re-clustering trigger differ. Every
protocol runs on identical mobility traces (same seed → same road, same speeds).
Any difference is therefore attributable to the objective, not the optimiser.

## What was built

- `mobility.py` — highway (6-lane bidirectional, 1 km) and urban Manhattan grid
  (600 m, 200 m blocks, turns at intersections). Self-contained, no SUMO
  dependency. `static` reproduces the paper exactly.
- `metrics.py` — Su & Zhang Link Expiration Time, cluster balance.
- `chirp.py` — six-term fitness, stability-triggered re-clustering.
- `network.py` — velocities, multi-RSU placement, setup-phase energy.

## Two model corrections made along the way

**Setup-phase energy.** The base paper charges nothing for re-clustering, so
electing every round appears free. It is not: each election floods an ADV from
every head and a JOIN from every member. `run_setup_phase()` now charges it.
Without this, CHIRP's stability trigger cannot show any benefit.

**Fitness scored in energy, not distance.** The radio model has a knee at
d0 = sqrt(eps_fs/eps_mp) = 87.7 m, beyond which cost goes as d⁴ rather than d².
A head 150 m from an RSU is 1.7× farther than one at 88 m but costs ~9× as much
to reach. A distance-linear fitness cannot see that, so the RSU and intra terms
now score `tx_energy(d)` directly.

## Ablation — how the weights were set

Highway, 10 seeds. Each row drops one term and renormalises the rest.

| dropped | FND | HND | mJ/reading | orphan% | intra m | elect/rd |
|---|---|---|---|---|---|---|
| none (full) | 16.2 | 31.5 | 0.7278 | 0.5 | 28.6 | 0.79 |
| **energy** | **10.3** | 31.8 | 0.7177 | 0.3 | 29.7 | 0.91 |
| rsu | 16.4 | 31.5 | 0.7287 | 0.5 | 27.7 | 0.76 |
| **intra** | 15.6 | 30.6 | **0.7441** | 0.6 | **32.4** | 0.81 |
| let | 16.2 | 31.4 | 0.7310 | 0.7 | 28.5 | 0.77 |
| balance | 15.8 | 31.5 | 0.7299 | 0.4 | 29.3 | 0.78 |

Only **energy** (−37 % FND when dropped) and **intra** (+2.2 % energy, +13 %
intra distance when dropped) are load-bearing. RSU, LET and balance each moved
every metric by under 1 %. Weights were reallocated on that evidence — LET
0.25 → 0.05, into energy (0.40) and intra (0.30) — rather than chosen by hand.

**The intra term is the one Eq. 9 omits**, and the ablation confirms it is the
second most important term in the objective. That is the central criticism of
the base paper, now measured rather than asserted.

## Diagnosing the urban first-node-death regression

The first version of Module 1 lost FND in urban (8.0 vs CSGD-NET's 9.4) while
winning every other metric. `src/diagnose_fnd.py` traces the identity and
history of the first node to die rather than guessing from aggregates:

| protocol | FND | was CH | CH rounds | mean cluster | orphan rounds |
|---|---|---|---|---|---|
| CSGD-NET | 9.4 | 60 % | 0.8 | 6.1 | 3.5 |
| CHIRP | 8.0 | **85 %** | **2.2** | **10.6** | 0.5 |

CHIRP's first casualty is almost always a cluster head that served a large
cluster for several rounds. Mean load was 8.3 members/CH against CSGD-NET's 6.6
— 58.5 vs 46.6 mJ/round of receive energy alone.

Per-round cost by role (urban, E0 = 500 mJ):

| role | cost/round | rounds to death |
|---|---|---|
| cluster head (8 members) | **88.00 mJ** | **5.7** |
| orphan (direct to RSU) | 25.34 mJ | 19.7 |
| ordinary member | 11.61 mJ | 43.0 |
| one re-election (setup) | **0.2833 mJ** | — |

Two things follow, and they overturn a design decision.

1. CHIRP's *better coverage* was the cause. CSGD-NET orphans 21.9 % of nodes;
   orphans pay their own direct-to-RSU cost. CHIRP absorbs them into clusters,
   moving that cost onto the heads, and receive energy scales linearly with
   cluster size.
2. Serving as head costs **311x** what one re-election costs. So first-node-
   death is governed by how often the *same node* is re-elected — and
   stability-triggered re-clustering, which holds heads for up to 5 rounds,
   was burning 440 mJ of a head's 500 mJ budget to save 0.28 mJ of control
   traffic.

The fix is therefore not a new fitness term but the opposite of the original
design: re-elect every round (`recluster_max_rounds = 1`) and add a LEACH-style
cooldown so a node cannot be head again for `ch_cooldown` rounds.

Cooldown sweep at `recluster_max_rounds = 1`, 12 seeds:

| cooldown | urban FND | urban LND | highway FND | highway LND |
|---|---|---|---|---|
| 0 | 9.2 | 24.4 | 21.9 | 39.8 |
| 2 | 10.1 | 25.0 | 22.7 | 39.7 |
| **3** | 9.7 | 24.2 | **23.3** | 39.9 |
| 5 | 10.2 | 23.7 | 23.5 | 39.7 |
| 7 | 10.2 | 23.3 | 24.0 | 39.1 |

FND plateaus around 3–5 while last-node-death slowly declines. Default 3.

## Negative result — the survival term

The obvious fix for the above was a fitness term predicting each head's actual
round cost (receive + aggregate + forward) and rewarding the weakest head's
remaining rounds. It backfired, monotonically:

| w_survival | urban FND | orphan% |
|---|---|---|
| 0.00 | **8.5** | **3.9** |
| 0.20 | 7.8 | 3.9 |
| 0.35 | 7.6 | 4.5 |
| 0.50 | 7.4 | 5.4 |
| 0.65 | 7.0 | 6.0 |

Orphans do not count toward a head's predicted cost, so the optimiser raised
minimum survival by *orphaning members* — orphan rate climbs with the weight.
The `coverage` multiplier was not enough to offset it. Default 0; code kept.

## Negative result — LET-aware member association

Members normally join the *nearest* head. On a bidirectional road that head is
often in the opposing lane, closing at up to 66 m/s, so the link dies within a
round. The obvious fix is to join the head whose link survives longest.

It does not work. Sweeping the blend on the highway, 8 seeds (α = 0 nearest,
1 = longest-lived):

| α | FND | HND | mJ/reading | orphan% | intra m | elect/rd |
|---|---|---|---|---|---|---|
| **0.00** | **16.1** | **31.2** | **0.7275** | 0.5 | **28.3** | 0.78 |
| 0.25 | 15.8 | 30.9 | 0.7396 | 0.4 | 30.4 | 0.79 |
| 0.50 | 15.5 | 30.2 | 0.7573 | 0.4 | 33.2 | 0.78 |
| 0.75 | 13.2 | 29.6 | 0.7779 | 0.3 | 36.0 | 0.82 |
| 1.00 | 14.1 | 29.2 | 0.7916 | 0.3 | 37.7 | 0.79 |

Monotonically worse on every metric that matters, while re-clustering barely
moves (0.78 → 0.79). At 1 node per 10 m there is always a nearby same-direction
candidate, so biasing toward link lifetime only buys distance. Default is α = 0;
the code path is kept because the negative result is worth reporting.

The CH energy statistic (mean vs min vs blend of head residual energy) was also
tested and made no significant difference; `mean` is kept as the simplest.

## Results — highway, 20 seeds, 1 km 6-lane, 5 RSUs, E0 0.5 J

| protocol | FND | HND | LND | mJ/reading | orphan% | intra m | elect/rd |
|---|---|---|---|---|---|---|---|
| LEACH | 19.6 | 33.1 | 44.5 | 0.6936 | 25.1 | 34.1 | 1.00 |
| LEACH-C | 25.2 | 31.8 | 41.1 | 0.7189 | 0.9 | 24.1 | 1.00 |
| HEED | 27.4 | 35.0 | 38.9 | 0.6577 | 46.8 | 36.4 | 1.00 |
| PSO | 15.5 | 31.9 | 46.0 | 0.7164 | 0.2 | 25.8 | 1.00 |
| GA | 13.8 | 31.2 | 47.0 | 0.7295 | 1.0 | 27.7 | 1.00 |
| CSGD-NET | 15.8 | 30.8 | 40.6 | 0.7509 | 10.0 | 38.8 | 1.00 |
| **CHIRP** | **23.0** | **31.8** | 39.9 | **0.7190** | **0.2** | **27.4** | 1.00 |

CHIRP vs CSGD-NET, Mann-Whitney U — **all five significant**:
FND **+46.0 %** (p<0.0001), HND +3.4 % (p<0.0001), energy/reading −4.2 %
(p<0.0001), orphan rate −98.3 % (p<0.0001), intra distance −29.3 % (p<0.0001).

CHIRP is not the best FND overall — HEED (27.4) and LEACH-C (25.2) beat it,
buying that with a 46.8 % and 0.9 % orphan rate respectively. Say so in the
report.

## Results — urban, 20 seeds, 600 m grid, 9 RSUs, E0 0.5 J

| protocol | FND | HND | LND | mJ/reading | orphan% | intra m | elect/rd |
|---|---|---|---|---|---|---|---|
| LEACH | 8.9 | 14.3 | 20.9 | 1.5519 | 37.6 | 61.0 | 1.00 |
| LEACH-C | 9.9 | 18.1 | 26.5 | 1.2690 | 6.5 | 45.8 | 1.00 |
| HEED | 8.0 | 13.2 | 18.1 | 1.6988 | 45.4 | 64.5 | 1.00 |
| PSO | 7.7 | 17.3 | 26.6 | 1.3106 | 6.0 | 51.9 | 1.00 |
| GA | 7.5 | 16.2 | 25.8 | 1.3795 | 9.3 | 53.0 | 1.00 |
| CSGD-NET | 9.4 | 15.4 | 20.8 | 1.4646 | 21.9 | 60.5 | 1.00 |
| **CHIRP** | 9.4 | **17.6** | 24.2 | **1.2938** | **3.8** | **55.6** | 1.00 |

HND **+14.6 %**, energy/reading **−11.7 %**, orphan **−82.7 %**, intra −8.1 %,
all p<0.0001. FND is 9.45 for both, p=0.54 — statistically indistinguishable,
which resolves the −15.3 % regression the first version carried.

LEACH-C remains the strongest baseline in urban on raw energy (1.2690 vs
CHIRP's 1.2938) and on LND. CHIRP does not dominate every protocol on every
metric and the report should not claim it does.

## Limitation worth stating

The Heinzelman radio model was designed for short-range sensor motes. At VANET
distances (100–150 m) it charges d⁴, making long links enormously expensive and
absolute lifetimes short. Trends between protocols remain comparable because all
protocols are charged identically, but absolute round counts should not be read
as realistic OBU lifetimes. The base paper's 50×50 m field hides this entirely.

**This limitation is now measured rather than conceded** (`docs/radio.md`,
`src/run_radio.py`): under log-distance path loss with no knee (γ = 2.0
highway, 3.0 urban) the seven-protocol energy ordering is identical, every
significant CHIRP-vs-CSGD-NET delta keeps its direction and significance, FND
stays statistically indistinguishable in urban, and the ablation still finds
energy and intra the only load-bearing terms. Absolute lifetimes stretch
~30 % in urban — the artifact correcting itself — and the highway table
barely moves at all, because its heads sit inside the 87.71 m knee where the
two models coincide.

## Reproduce

```bash
python3 src/run_module1.py --scenario highway --seeds 20
python3 src/run_module1.py --scenario urban --seeds 20 --rounds 150
python3 src/run_module1.py --scenario highway --seeds 10 --ablate
python3 src/run_module1.py --scenario highway --seeds 8 --sweep-assoc
python3 src/diagnose_fnd.py
```

## Summary for the report

Three of Module 1's initial design decisions were wrong and the measurements
say so. Stability-triggered re-clustering, LET-aware association, and the
survival fitness term all made things worse and are all defaulted off with the
evidence recorded. What actually carries the module is narrower and better
supported: the intra-cluster distance term Eq. 9 omits, energy-scored rather
than distance-scored costs, and cluster-head rotation via a cooldown.

That is a more honest and more defensible story than six terms that all
supposedly help, and the ablation and sweeps are the evidence.
