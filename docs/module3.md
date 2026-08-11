# Module 3a — formal verification of the authorisation layer

Scyther v1.3.0, `--max-runs=4`. **32 claims verified, 8 failing by design.**

```bash
SCYTHER=/path/to/scyther-mac python3 formal/run_scyther.py
```

The runner compares against the expected set below and exits non-zero if
anything moves, so this document cannot silently go stale.

## Why this module is not box-ticking

A Scyther or AVISPA section is near-standard in VANET security papers and
usually decorative. This one is load-bearing, and `docs/priority.md` is why.

Module 5 measured three ways to stop a vehicle falsely claiming emergency
status and taking an ambulance's reserved slot:

| defence | EMS deadline-miss at 20 % attackers | detection |
|---|---|---|
| none | 0.441 urban / 0.467 highway | — |
| behavioural (assertion rate + trust) | 0.239 / 0.256 | 0.954 / 1.000 |
| **authenticated role attribute** | **0.000 / 0.000** | not used |

The greed sweep showed why the middle row can never reach the bottom one. An
attacker asserting at rate 0.50 is detected at **0.008** on the highway — below
its own false-positive rate of 0.012, i.e. the detector contributes nothing —
while still taking 48 % of the maximum deadline damage. At rate 0.18 its
per-node behaviour is *identical* to a real ambulance's, so no rate-based test
separates them at any threshold.

**The distinguishing fact is not behavioural. It is whether the vehicle holds
the role.** In the simulator that is a boolean, `is_ems`. Here it is discharged.

## Results

### `register.spdl` — certificate issuance — 8/8 verified

The TA binds a pseudonym to a role attribute and signs it. Vehicle and TA agree
on which role was issued, with no replay.

Message 1 is authenticated under `k(V,TA)`, a credential installed out of band
when an emergency vehicle is commissioned. Without it the model would describe a
TA that issues an EMS certificate to anyone who asks, which would make Module
5's authorisation defence vacuous — the false-priority attacker would simply
register as an ambulance.

### `priority.spdl` — the slot grant — headline claim verified

| role | Alive | Weakagree | Niagree | Nisynch |
|---|---|---|---|---|
| V | Ok | Fail | Fail | Fail |
| TA | Fail | Fail | — | — |
| **C** | **Ok** | Fail | **Ok** | **Ok** |

**`claim_C4(C, Nisynch)` — Ok, proof of correctness.** Over a three-role
protocol, Nisynch requires every preceding event in *every* role to have a
matching partner. So whenever a cluster head completes and grants a slot, there
was a real TA run that issued that role to that vehicle and a real vehicle run
that asserted it, agreeing on pseudonym, role and nonce. Freshness rules out
replay. That is the sentence Module 5 assumed.

**The six failures are structural, not vulnerabilities.** The TA never learns
which cluster head the vehicle will later talk to — registration happens
offline and once, message 1 carries no head identity, and nothing ever tells
the TA one. Weakagree over three roles asks whether every other role is
"running the protocol with" the claimer, and the TA is not running with any
head.

That diagnosis was tested rather than asserted: delete the TA role, keep the
assertion exchange otherwise identical, and all claims verify. Which is:

### `priority-assert.spdl` — the assertion exchange alone — 8/8 verified

Confirms the exchange itself is sound in isolation. Together with the two models
above, the whole path is covered with nothing papered over:

| | covers | result |
|---|---|---|
| `register.spdl` | certificate issuance | 8/8 Ok |
| `priority.spdl` | head's agreement **with provenance** | C: Niagree, Nisynch Ok |
| `priority-assert.spdl` | the assertion exchange alone | 8/8 Ok |

The certificate is deliberately absent from `priority-assert.spdl`. A Scyther
role can only send terms it can derive, and V cannot construct `{...}sk(TA)` —
it does not hold the TA's signing key, which is the whole point of a
certificate. Modelling it without the TA role would mean declaring it a global
constant and handing it to the adversary too.

### `aggregate.spdl` — the three data-path message types — 12/12 verified

`chirp-member` (reading → head), `chirp-aggregate` (fused packet → RSU) and
`chirp-verbatim` (class-2 → RSU, relayed untouched) all verify on all four
claims.

**`chirp-verbatim` R.Nisynch is the interesting one.** The RSU authenticates the
emergency vehicle *end to end, through a relay it does not trust at all*.

The relay is deliberately not a Scyther role. Modelling it as one makes Nisynch
require the relay to be honest, which is strictly weaker than what we want to
claim; under Dolev-Yao the network already *is* the adversary, so a two-role
V → R protocol is the correct way to say "carried by an untrusted relay". This
was found the hard way — the three-role version failed all four claims, and the
two-role version verifies all four.

### `fusion-limit.spdl` — a deliberate negative result — 2/2 failed, as designed

Can the RSU authenticate the *member* whose reading is inside a fused packet?
Both legs are individually sound, but the fused value is fresh at the head and
not a recoverable function of the readings. R's Niagree and Nisynch **fail**.

That failure is the result. It is the formal counterpart of a property the
simulator cannot express: **a compromised cluster head can fabricate a fused
value and no aggregate MAC will detect it**, because the MAC attests to who sent
the value, never to whether the value faithfully summarises anything.

So a "no attacks" result on `chirp-aggregate` must not be read as "the fused
value is trustworthy". And the class-2 bypass gains a second justification that
is not about latency at all: **it is the only path in CHIRP that gives the RSU
end-to-end authentication of the originating vehicle.** Fusion buys energy and
costs provenance.

## The attack Scyther found, and the fix

The first version of `aggregate.spdl` MAC'd both the member reading and the
fused aggregate as `{sender, value, nonce, receiver}k(sender,receiver)`. Those
are structurally identical. Scyther produced this trace:

> Alice, as a **head sending a fused aggregate to RSU Charlie**, emits
> `(Alice, agg, nc, {Alice, agg, nc, Charlie}k(Alice,Charlie))`.
> Charlie accepts the same bitstring as a **member reading from Alice**.

A head's aggregate could be replayed into another cluster as a member's reading,
and vice versa. Niagree and Nisynch failed on both legs while Alive and
Weakagree passed — the receiver had the right peer but the wrong message
meaning.

The fix is a distinct constant tag inside every MAC and signature, so the
message types occupy disjoint formats. All twelve claims then verified, and the
whole suite verifies identically whether the files are checked separately or
concatenated into one — no cross-protocol attacks remain.

**This is the concrete return on doing the formal work.** The flaw is invisible
in the simulator, where message types are Python fields that cannot be confused,
and it would have survived into a paper.

## What Scyther cannot do here, and is therefore not claimed

- **The TA's out-of-band vetting.** That an EMS credential reached only a real
  ambulance is a property of the registration desk, not of any message exchange.
  What is verified is that the role attribute cannot be **forged, replayed, or
  transplanted** onto another vehicle's assertion — not that the TA's issuing
  policy is correct.
- **Conditional privacy and unlinkability.** Whether an observer can link two
  pseudonyms of one vehicle is an equivalence property. Scyther proves secrecy
  and authentication only; this needs ProVerif's observational equivalence or
  Tamarin's diff mode.
- **Pseudonym confidentiality.** A signature is not an envelope: `{m}sk(TA)` is
  readable by anyone with `pk(TA)`. The pseudonym is public by design —
  unlinkable, not secret — so no `Secret` claim is made on it. One would fail,
  correctly.
- **ECC itself.** Symbolic verification assumes perfect cryptography. Point
  multiplication is an abstract one-way function here. This verifies the message
  flow, not the curve.
- **Bounded search.** `--max-runs=4`. Every result above is "no attack within
  four concurrent runs", which is the standard bound but is a bound.
- **Anything with a cost.** Bytes, milliseconds and millijoules are Module 3b.
  `sig_bits` and `mac_bits` in `config.py` remain 0, so Module 5's measured
  cost of priority is still a lower bound.

## Reproducing

Scyther v1.3.0 ships a native macOS arm64 binary — no Rosetta needed, contrary
to the tool's reputation from its long-dormant 1.1.3 release.

```bash
# binary from github.com/cascremers/scyther releases, v1.3.0
SCYTHER=/path/to/Scyther/scyther-mac python3 formal/run_scyther.py
python3 formal/run_scyther.py --runs 5      # deeper search
```
