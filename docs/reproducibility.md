# Reproducibility audit of the base paper

Independent re-verification. Method: assume the publication is correct unless
proven otherwise; for each claimed discrepancy, trace the paper's equations,
trace our implementation, and test whether the gap is caused by (1) our code,
(2) our misreading, (3) an undocumented assumption, or (4) a real inconsistency.

Scripts: `src/verify.py`, `src/verify_fit.py`.

**Summary of revisions to our earlier claims.** Finding 1's *energy-budget*
claim is withdrawn — the depletion rate is reproducible and we were wrong. Its
*residual-gap* claim is also withdrawn, in the other direction: we blamed our
LEACH-C and CSGD-NET, and the evidence says Table 4's own columns are at fault.
Finding 2 turned up a material bug in *our* implementation, not the paper's.
Finding 3 survived a direct attempt to refute it.

---

## Finding 1 — energy budget. **VERDICT: type 3, undocumented assumption. Our earlier claim was wrong and is withdrawn.**

### The paper

Table 3: `Eelec = 50`, `eps_fs = 10`, `eps_mp = 0.0013` (no units), packet size
6400 bit, 100 nodes, 50×50 m. Eqs. (9)–(11) give the standard Heinzelman radio.

### Intermediate calculation

```
k · Eelec                       = 6400 × 50e-9      = 0.3200 mJ
d0 = sqrt(eps_fs/eps_mp)                            = 87.7 m
   -> free-space term applies everywhere in a 50×50 m field
mean member->CH distance ~5.9 m -> amp              = 0.00226 mJ
mean CH->RSU distance   ~16.7 m -> amp              = 0.01778 mJ

member cost/frame                                   = 0.3223 mJ
CH cost/frame (9 RX + aggregate + TX)               = 3.5378 mJ
network/frame = 90×0.3223 + 10×3.5378 = 64.38 mJ    = 0.6438 mJ per node

Table 4 LEACH requires (0.5 − 0.039543)/40          = 11.5114 mJ per node/round
ratio                                               = 17.9×
```

### What we got wrong

We concluded the paper's depletion rate was unachievable. That inference assumed
**one frame per round**, which the paper never claims and which contradicts
LEACH itself: Heinzelman's steady-state phase is many TDMA frames per round. The
frame count is a free parameter the paper leaves unstated — not an error.

### Could another implementation reproduce the paper unchanged? **Yes.**

Fitting frames/round against Table 4's LEACH column (`src/verify_fit.py`):

| frames | RMSE vs LEACH |
|---|---|
| 16 | 0.06366 |
| 18 | 0.03981 |
| 20 | 0.01829 |
| **22** | **0.00832** |
| 24 | 0.02254 |

At 22 frames/round our LEACH reproduces Table 4's LEACH column closely:

| round | ours | paper |
|---|---|---|
| 10 | 0.3572 | 0.35529 |
| 20 | 0.2219 | 0.22091 |
| 30 | 0.1154 | 0.12717 |
| 40 | 0.0403 | 0.039543 |

The paper is reproducible. Default changed from 18 to 22 in `config.py`.

### Assumptions we make and must state

- `E_DA = 5 nJ/bit/signal` — the paper never gives an aggregation cost; this is
  the standard LEACH value.
- `E0 = 0.5 J` — Table 3 renders initial energy as "1.01 d", not a readable
  quantity; Table 4 starts every protocol at 0.5, so we take that.
- Table 4 is mean residual energy **per node**. Not stated; it is the only
  reading consistent with a 0.5 J start.
- Cluster geometry in the hand-calculation above assumes uniform deployment.

### Residual gap. **REVISED: it is not ours.**

At 22 frames/round, LEACH matches (RMSE 0.005) but **LEACH-C (0.049) and
CSGD-NET (0.046) do not** — ours die faster than the paper reports.

We originally recorded this as a defect in our implementation. That attribution
was tested directly (`src/verify_table4.py`) and **is withdrawn**. Three
independent arguments, and they agree.

**1. The protocol-dependent energy budget is ~0.002 J/node.** Per-round network
energy under Eqs. (9)–(11) splits into an electronics term,
`(2(n − n_ch) + n_ch)·k·E_elec` plus aggregation, and an amplifier term
`k·ε_fs·Σd²`. The electronics term does not depend on *which* nodes are heads:
for any head set, every member sends one packet and every head receives it and
sends one. So the amplifier is the entire budget a CH-selection algorithm has to
play with, and in a 50×50 m field with 10 heads it measures **0.00130–0.00204
J/node over ten rounds**.

**2. Table 4's spread is 20–44× that budget.** Cross-protocol spread at round 10:

| | spread at R10 | vs budget |
|---|---|---|
| ours, three protocols | 0.00068 | within |
| Table 4, LEACH/LEACH-C/CSGD-NET | 0.04018 | **19.7×** |
| Table 4, all six columns | 0.09018 | **44.2×** |

The decisive case needs no estimate. Set the amplifier to zero — perfect
clustering, physically unreachable — and LEACH-C reaches **0.35920** at round 10
against Table 4's **0.37000**, still short by 0.0108 J/node. *No cluster-head
selection algorithm can close that*, because the energy it would have to save is
not spent on anything clustering controls.

**3. Two columns are not monotone in drain rate.** Drain per round =
(alive nodes) × (per-node cost). Nodes only die, and per-node cost is dominated
by the constant electronics term, so drain cannot rise between intervals.

| protocol | source | drops R1–10, 10–20, 20–30, 30–40 | max rise |
|---|---|---|---|
| LEACH | paper | 0.1447 0.1344 0.0937 0.0876 | −6.5 % |
| LEACH | ours | 0.1428 0.1342 0.1066 0.0757 | −6.0 % |
| LEACH-C | paper | 0.1300 0.0866 0.1355 0.1040 | **+56.5 %** |
| LEACH-C | ours | 0.1421 0.1421 0.1412 0.0717 | 0.0 % |
| CSGD-NET | paper | 0.1702 0.0689 0.1103 0.0763 | **+60.2 %** |
| CSGD-NET | ours | 0.1428 0.1414 0.1258 0.0797 | −0.9 % |

**The correlation is the diagnosis.** The only Table 4 column internally
consistent with the paper's own model is LEACH — and LEACH is the only column we
reproduce. The two we fail on are exactly the two that violate a constraint the
model cannot violate.

### What we ruled out before concluding

- **Alternative readings of "Remaining energy"**, which the paper never defines.
  Mean over all nodes, mean over survivors only, and network total, each crossed
  with both round alignments (row 1 = 0.5 hints the row may be *before* the
  round), refitting frames/round for each of the six readings. Best LEACH-C RMSE
  across all six: 0.0489, against the current reading's 0.0490. Nothing closes.
  "Network total" is excluded outright — it would put the column near 50 J.
- **An undocumented larger field.** A ~300 m square *does* reproduce the spread,
  because past d0 = 87.7 m the d⁴ branch makes clustering quality dominate cost.
  But Table 3 states "Simulation Zone 50 × 50 m" with nothing contradicting it
  anywhere in the paper, so adopting 300 m would be fitting a curve against an
  explicitly published parameter. **We did not make that change.** It is
  recorded because it is the most likely benign explanation: Table 4 may have
  been produced under a different field size than Table 3 documents.
- **A defect in our LEACH-C.** It produces the shortest member links of any
  protocol tested (6.09 m mean against LEACH's 12.88 m) and the best
  first-node-death (28.3 rounds against LEACH's 11.4). It is clustering well.

### Consequence, and why our LEACH-C looks worse

Mean residual energy over all nodes is a perverse metric: a dead node stops
consuming, so a protocol that kills nodes early has fewer consumers and appears
to conserve energy. Our LEACH-C keeps 94.8 nodes alive at round 30 against
LEACH's 79.6 — better balance, therefore more consumers, therefore a faster
fall in the mean. It trails LEACH from round 20 on *because* it is doing its job.

That is a further reason not to compare protocols on this metric alone. Module 1
reports first/half/last-node-death and energy per delivered reading instead.

Reproduce: `python3 src/verify_table4.py`

---

## Finding 2 — Eq. 9. **VERDICT: type 4 for the min/max wording (cosmetic), but type 1 for the reading we shipped — a real bug in our code.**

### The paper, verbatim

> "The objective function *f* … targets the **minimization** of two key aspects:
> the **energy consumption of Cluster Heads (CHs) relative to overall network
> energy** and the distance separating the CHs from the RSU."

> "*dis* denotes the distance between the cluster heads and the RSU, *E*
> represents the **overall residual energy within the vehicular network**, and
> *E0* is the initial energy."

    f = E / (E0 · dis(CH_i, RSU))                                    (9)

### Two contradictions inside these three lines

1. The prose says the numerator is CH energy *consumption*; the symbol list says
   E is the network's *residual* energy. Different quantities.
2. "Minimization" cannot be right for the printed expression: residual energy is
   in the numerator, distance in the denominator, so minimising it would seek
   drained heads far from the RSU. **This one is harmless** — maximising the
   printed form is exactly minimising its reciprocal, so every implementer lands
   on the same ranking. Presentational, not substantive.

### The substantive problem, which is ours

Taking the symbol list literally, E is a **network-wide** quantity: identical for
every candidate CH set within a round. It cancels. Eq. 9 then collapses to a
pure distance-to-RSU criterion — **node energy plays no role in CH selection.**

We shipped a different, unstated reading: E = summed residual energy of the
*candidate CH set*. That was never documented and it is not what the paper says.
Measured effect, 10 seeds:

| mode | reading | residual@end | FND | packets |
|---|---|---|---|---|
| A | E = network residual, set-level (**literal**) | 0.02117 | 11.8 | 10800 |
| B | E = network residual, per-CH sum (literal) | 0.01287 | 9.6 | 10800 |
| **C** | **E = summed CH energy (what we shipped)** | 0.00003 | **22.2** | 9727 |
| D | E = each CH's own energy, per-CH | 0.00008 | 18.2 | 9637 |

The choice nearly **doubles** first-node-death (11.8 → 22.2). Our undocumented
reading materially flattered CSGD-NET's lifetime.

### Could another implementation reproduce the paper unchanged?

Only by picking a reading. All four are defensible from the text, and they give
different answers, so Eq. 9 as published does not determine an implementation.

### Resolution

`fitness_mode` is now an explicit config field. Default `"C"` — beating a
strawman reading of the baseline would be worthless — but the choice is ours,
is documented, and both readings get reported.

---

## Finding 3 — Table 4's HEED/PSO/GA columns. **VERDICT: type 4, survives refutation. Cause not determinable from outside.**

### The observation

| Protocol | Successive differences | Std |
|---|---|---|
| LEACH | −0.14471, −0.13438, −0.09374, −0.08763 | 2.5e−02 |
| LEACH-C | −0.13000, −0.08661, −0.13554, −0.10398 | 2.0e−02 |
| CSGD-NET | −0.17018, −0.06887, −0.11031, −0.07629 | 4.0e−02 |
| HEED | −0.09000 ×4 | 2.0e−17 |
| PSO | −0.08500 ×4 | 2.4e−17 |
| GA | −0.08000 ×4 | 2.4e−17 |

### The strongest counter-hypothesis, and its test

While all nodes are alive the per-round drain is near-constant, so residual
energy really is near-linear. HEED/PSO/GA are reported to 2 dp. **Rounding a
near-linear trace to 2 dp could produce exactly equal differences by accident.**

Tested directly (`src/verify.py`, Test 3): take our own simulated traces, sample
at rounds 1/10/20/30/40, round to 2 dp, count exact arithmetic progressions.

| protocol | std of diffs, full | std @2dp | exactly linear @2dp |
|---|---|---|---|
| LEACH | 0.0124 | 0.0124 | **0/60** |
| LEACH-C | 0.0048 | 0.0043 | **0/60** |
| HEED | 0.0054 | 0.0049 | **0/60** |
| CSGD-NET | 0.0082 | 0.0084 | **0/60** |

Zero hits in 240 real traces. Rounding does not explain it. The counter-
hypothesis fails and the observation stands.

### Supporting evidence

- Every figure narrative (Figs. 11, 12, 13, 15) discusses **only three**
  protocols — LEACH, LEACH-C, CSGD-NET — while Table 4 has six columns.
- The three linear columns are reported to 2–3 s.f.; the three irregular ones to
  5 s.f. The precision split matches the linearity split exactly.

### What we do *not* claim

We cannot determine how those columns were produced. A benign explanation exists
and is consistent with everything above: the values may have been taken or
interpolated from the cited HEED [48], PSO [49] and GA [50] papers rather than
re-simulated in this setup. That would still make them unusable as a like-for-
like baseline, since they would not share the paper's parameters.

State it in the report as an observation about published numbers with a stated
methodological consequence. Do not allege fabrication — the linearity is a fact,
the cause is not knowable from outside.

### Consequence

Table 4's HEED/PSO/GA figures cannot serve as a baseline. We re-implement all
five comparison protocols and report our own measurements.

---

## Finding 4 — smaller defects found while tracing (all type 4, all cosmetic)

- **Duplicate equation number.** The fitness function (p. 11) and the transmit
  energy model (p. 13) are both numbered **(9)**.
- Eq. (9) on p. 13 writes `E_TX-amp(1, d)` where Eq. (11) defines
  `E_TX-amp(k, d)` — the `1` should be `k`.
- Sect. 4.2, Fig. 12 discussion: "in LEACH-C, all nodes are completely dead
  after 46 rounds, and in LEACH-C, all nodes are completely dead after 45
  rounds" — the first should read LEACH.
- Table 3's initial energy renders as "1.01 d".
- Figures are referenced as "Figure 0.11" and "Figure 0.15" in the body text.

## Finding 5 — no variance reported

No seed count or confidence interval accompanies Table 4 or Figs. 11–13, 15;
only Fig. 14 mentions a 95 % interval. We report mean ± 95 % CI over 30 seeds
with Mann-Whitney U tests. Type 3.

---

## Where this leaves the project

The genuinely load-bearing criticism of the base paper is **not** its arithmetic
— that reproduces. It is:

1. Eq. 9 does not determine an implementation, and under its literal reading it
   ignores node energy entirely (Finding 2).
2. Eq. 9 has no intra-cluster distance term, so heads are pulled toward the RSU
   and edge members transmit far. The PSO/GA clustering cost of Latiff et al.,
   which we implement in `swarm.py`, includes that term.
3. Static topology in a vehicular network — the paper's own §4.3 concedes it.
4. No security model at all.

Items 1–2 are what Module 1's multi-metric fitness fixes; items 3–4 are Modules
1–4. None of these depend on Finding 1 or 3 being true, which is the right place
for the project to stand.
