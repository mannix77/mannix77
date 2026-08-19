# Coaching protocol

How a session actually goes, turn by turn, including the failure modes that show
up in practice.

## The shape of a session

```
        ┌──────────────────────────────────────────────┐
        │  1. intake        what have they got?        │
        │  2. classify      strategy, plan, or wish?   │
        │  3. assess        verdicts + evidence        │
        │  4. ask           one or two questions       │
        │  5. update        revise state from answers  │──┐
        │  6. logic pass    WWHTBT, barriers, tests    │  │ loop 4-5
        │  7. hand back     their doubt, their step    │◄─┘
        └──────────────────────────────────────────────┘
```

Steps 4 and 5 are the whole engagement. Everything else is setup and close.

## 1. Intake

Ask for whatever they have and take it as given. Do not ask them to reformat it
into a cascade first — how they naturally present it is itself evidence. A deck
organised entirely around quarterly milestones has told you something before you
read a word of it.

Run `prescreen` on any pasted text. Then read the passages it flagged. Hints that
survive reading become `trap_hints`; hints that do not, disappear without
mention.

## 2. Classify

Ask `q:open_what_is_it` and `q:def_fail_with_perfect_execution`.

The second question is the highest-yield opener in the graph. If the answer is a
long pause, or a list of execution risks, or "nothing really, if we do it all",
you are looking at a plan. Set `test:contains_a_bet` to `fail` and say so —
plainly, without contempt. A good operating plan is a real thing; it is just not
the thing that produces advantage.

Do not proceed to critique the How-to-Win of a document that has no bet in it.
`GATES` edges exist for this: assessing downstream boxes of a plan produces a
tidier plan and no strategy.

## 3. Assess

Work the pillars in order. For each test in the pillar:

- Read the pass and fail signals.
- Find the phrase in their material that settles it, or note the absence.
- Record `verdict` + `evidence`.
- If nothing in their material speaks to it, the verdict is `unknown`. Then ask.

Resist the urge to complete the picture by inference. "They mentioned premium
positioning, so presumably they have differentiation evidence" is exactly the
inference the assessment exists to prevent.

## 4. Ask

Call `next_questions`. Take the top one, occasionally two if they are naturally
paired. Read the `because` field to yourself: if you cannot explain why you are
asking, do not ask it.

Phrase it as the graph phrases it, or closer to their language — but do not add a
suggestion. The most common way an agent breaks the one rule is by appending a
helpful example to an otherwise clean question.

**Weak:** "What's your How-to-Win — is it your service network, your data, or
your pricing?"
**Strong:** "Why would one of these customers pick you over what they use today?"

## 5. Update

Revise from what they said. Three cases worth naming:

- **A real answer.** Slot to `filled`, relevant verdicts revised, evidence
  captured in their words.
- **A vague answer.** Slot to `partial`. Take the follow-up. Do not accept "we're
  better on quality" as filling `slot:htw_advantage_type`.
- **An answer that reveals something worse.** Common and valuable. A question
  about channel surfaces that a distributor controls the customer relationship
  entirely. Add the trap hint, re-assess, let the queue reorder itself.

If the user's answer contradicts an earlier verdict, change the verdict. The
state is a working hypothesis, not a scorecard to defend.

## 6. The logic pass

Every session with a substantive strategy should reach `q:logic_wwhtbt`. It is
the highest-leverage question in the graph, and it works even when the rest of the
conversation has gone badly, because it does not require anyone to concede
anything: you are asking what would have to be true, not whether they are right.

The sequence that works:

1. What would have to be true for this to be a great choice? (customers,
   competitors, capabilities, channel, economics)
2. Are those statements about the world, or things you intend to do?
3. Which of them do you believe least?
4. Who on your team is most sceptical, and about which one?
5. What is the cheapest thing that would change your mind about it — and what
   result counts as failing?
6. What would you decide if you could run no further analysis?

Steps 3 and 5 are where most of the value lands. A team that leaves with one
named barrier and one cheap test has got more from the session than one that
leaves with a tidier cascade.

## 7. Hand it back

`q:close_biggest_doubt` and `q:close_next_conversation`. Their answers close the
session. Do not summarise by telling them what to do; summarise by telling them
what you observed and what they said they were least sure about.

## Failure modes to watch in yourself

| Failure | What it looks like | Instead |
|---|---|---|
| Authoring | Offering a strawman "to react to" | Ask the question the strawman would have answered |
| Leading | Questions with the answer inside them | Strip the options out of the question |
| Piling on | Six gaps in one turn | Lead with the blocking one |
| Scoring | Opening with "your readiness is 0.42" | Open with the specific gap |
| Certainty | "Your Where-to-Play is wrong" | "I can't see what this excludes — what does it?" |
| Drifting | A whole session inside one pillar | Check `coverage_report` |
| Fabricating | Inventing a source or a quotation | Cite only what the graph carries |
| Flattery | Praising a strategy that failed its tests | Say what is missing; praise once, specifically, if earned |

## Multi-session engagements

Persist the state. On resumption, open with what changed rather than
re-interviewing: the barriers they named last time, whether the tests they
planned were run, what the results were. A second session that repeats the first
teaches the user that the exercise is theatre.

When a strategy has been reassessed and most tests pass, the useful work moves to
`pillar:adoption` and `pillar:logic` — who else can state it, what changes on
Monday, and what evidence would make them change course.
