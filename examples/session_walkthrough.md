# Walkthrough: coaching a VP of Product

A worked scenario showing the assess-and-ask loop. Everything in the "graph says"
blocks is **real output** from the CLI against the committed state files — not an
illustrative transcript. Reproduce any of it with the commands shown.

**The strategy:** [`scenario_meridian.md`](scenario_meridian.md) — Priya Raman,
VP Product at a fictional post-acute healthcare data company, has written an
FY27 product strategy for her CPO and an exec review. It is OKR-shaped, sincere,
and not a strategy.

---

## Step 0 — Prescreen the document

```bash
PYTHONPATH=src python3 -m graphify prescreen examples/scenario_meridian.md
```

> **Graph says** — 4 hints, all `unverified`:
> | Trap | Matched |
> |---|---|
> | `trap:initiative_list` | `"2. Expand"` |
> | `trap:misplaced_shoulds` | `"Customers should"` |
> | `trap:moat_thinking` | `"moat"` |
> | `trap:plan_as_strategy` | `"by end of FY27"` |

These are reading prompts, not findings. The coach opens the document at each
match and decides. All four survive here; a doc that says "moat" while explaining
how the advantage gets renewed would not.

The coach also adds `trap:framework_as_strategy` by hand after reading the
structure — an objective and four key results occupying the place where the
choices belong. No regex found that; a person did.

## Step 1 — Assess before asking

State: [`meridian_turn1.json`](meridian_turn1.json). Twenty tests judged from the
document alone, each with the evidence that produced it. Nothing about Priya
herself is known yet.

```bash
PYTHONPATH=src python3 -m graphify assess examples/meridian_turn1.json
```

> **Graph says**
> ```
> overall readiness: 0.073   coverage: 0.39
> blocking:
>   ! The desired action is named, at a scale and on terms that are sustainable
>   ! The must-be-true conditions are written down
> weakest areas:
>   0.00  The Practitioner
>   0.00  Customer & Promise
>   0.00  Capabilities
>   0.00  Management Systems
> ```

Note that coverage is 0.39, not 1.0. Two thirds of the tests are still `unknown`,
and the report keeps that separate from failure. A 0.073 readiness here means
"barely anything has been established", not "this is 7% good".

## Step 2 — Ask what the graph puts in front of you

```bash
PYTHONPATH=src python3 -m graphify next examples/meridian_turn1.json --limit 3
```

> **Graph says** — three openers, each with its reason:
> 1. *"Before I apply any standard to this: what kind of organisation is this, and what would winning even mean in your setting?"* — probes `test:context_fit_acknowledged`
> 2. *"Before we look at the content: what is this document meant to be — a strategy, an operating plan, a budget, or a bit of each?"* — probes `test:contains_a_bet`
> 3. *"Before we look at the strategy itself — what is your role in this work, and what can you decide on your own?"* — probes `test:practitioner_scope_is_clear`

The coach asks two of them, not three.

**Priya's answers:** commercial B2B software, regulated customers. The document is
"our product strategy for the exec review". She owns roadmap and product scope.
Pricing and packaging belong to the CRO. The analytics rebuild is already
committed to three enterprise customers.

That third answer is why `pillar:practitioner` exists. Everything downstream is
now framed by it: telling Priya her arena is unbounded would be useless, because
she cannot bound it alone. The useful version becomes what the person who *can*
would need to hear.

Two verdicts follow immediately:

- `test:chooser_owns_the_choice` → **fail.** She is drafting choices for approval.
  The people who will resource them have not made them. (`trap:delegated_strategy`)
- `test:constraints_treated_as_choices` → **fail.** Pricing, packaging and the
  committed rebuild are all treated as facts of nature. None has been examined as
  a choice somebody made.

## Step 3 — The queue reorders itself

State: [`meridian_turn2.json`](meridian_turn2.json).

```bash
PYTHONPATH=src python3 -m graphify next examples/meridian_turn2.json --limit 4
```

> **Graph says** — the practitioner ground is covered, so the two blocking
> failures now dominate:
> 1. *"What exactly do you need a customer to do that they are not doing today — and at what price?"*
> 2. *"Set aside whether this is true for a moment. What would have to be true — about your customers, your competitors, your capabilities, your channel, and the economics — for this to be a great choice?"*
> 3. *"You have given me the number you need to hit. What has to become true out in the market for that number to appear?"*
> 4. *"If the action you need is not a purchase, what is it — and what would those people otherwise do…"*

Pillar coverage confirms the shift:

> ```
> What Strategy Is (and Is Not)  readiness=0.25  coverage=1.0
> The Practitioner               readiness=0.25  coverage=1.0
> Winning Aspiration             readiness=0.25  coverage=1.0
> ```

Fully covered, low readiness — the coach now *knows* these areas are weak rather
than merely unexamined. That distinction is the whole point of tracking `unknown`
separately.

Question 4 is offered because the graph does not assume a purchase. Here it is the
wrong branch — Meridian sells software — so the coach skips it. Its presence is
the fix for a rubric bug that used to fail non-commercial strategies for lacking
a price.

## Step 4 — What the coach does not do

The strongest finding available is that this is an OKR set, not a strategy. The
temptation is to be helpful:

> ❌ *"Your real How-to-Win is probably that your regulatory content library lets
> you guarantee audit outcomes competitors can't. Try framing it that way."*

That sentence would be well received and it would ruin the exercise. It is a
strategy Priya did not choose, cannot defend in the exec review, and has no
reason to believe. The graph's version:

> ✅ *"Take any one item off your roadmap. Does anything else stop working?"*
> (`q:htw_drop_one_item`)
>
> ✅ *"What does this strategy ask you to do that your strongest competitor would
> refuse to do?"* (`q:htw_what_would_rival_refuse`)

Same target — the missing winning logic. One supplies the answer; the other makes
the absence visible to the person who has to fill it.

A test enforces this at the data layer: every question must end in a question
mark and contain no authoring language.

## Step 5 — Where it lands

The high-value ground is `pillar:logic`, and the queue is already pointing there.
The sequence that pays:

1. What would have to be true for this to be a great choice?
2. Are those statements about the world, or things you intend to do?
3. Which of them do you believe least?
4. Who on your team is most sceptical, and about which one?
5. What is the cheapest thing that would change your mind — and what result counts as failing?

For Meridian, step 3 has an obvious candidate that Priya wrote herself: customers
*should* recognise that the compliance coverage is more complete. That is the
load-bearing assumption, it is stated as an obligation on the customer, and
nothing in the document tests it or measures it.

A good session ends with Priya holding one named barrier and one cheap test —
plus, given her authority, a clear view of which conversation with the CRO she
needs to have. Not a better document.

---

## Reproducing this

```bash
PYTHONPATH=src python3 -m graphify prescreen examples/scenario_meridian.md
PYTHONPATH=src python3 -m graphify assess    examples/meridian_turn1.json
PYTHONPATH=src python3 -m graphify next      examples/meridian_turn1.json --limit 3
PYTHONPATH=src python3 -m graphify next      examples/meridian_turn2.json --limit 4
PYTHONPATH=src python3 -m graphify plan      examples/meridian_turn2.json --rounds 4
```

`plan` previews the whole line of questioning without changing state — useful for
inspecting the policy, not for reading aloud.
