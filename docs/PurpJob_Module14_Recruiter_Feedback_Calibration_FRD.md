# PurpJob — Module 14: Recruiter Feedback & Calibration
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-1+ / calibration tier — same sequencing boundary as Modules 12/13; per the master document's own roadmap, "Калибровка и итерация" is explicitly stage 3, after the MVP-1 recruiter pilot, not concurrent with MVP-0]
**Phase:** Local prototype (no authentication layer — reuses Module 12's recruiter-mode and Module 7's moderator-mode patterns)
**Depends on:** Module 3 (`PROFIndexSnapshot`), Module 6 (`TrustScoreSnapshot`), Module 7 (canonical `Explanation`, `DisputeCase`, `ModeratorOverride` — this module reuses that machinery, doesn't duplicate it), Module 12/13 (recruiter interactions this feedback attaches to)
**Closes a previously-deferred item:** Module 7's `DisputeCase(origin: "sampled_audit")` was explicitly reserved but left with no real producer/selection tooling (§2.2 there: *"team workflow, not application logic"*) — this module is that tooling (§0, US4)

---

## ⚠️ 0. Three feedback mechanisms already exist in this series — this is a fourth, distinct one, not a rename of any of them

Before building this, it's worth being precise about what's already there, since all four sound similar in isolation:

| Mechanism | Module | What it's for |
|---|---|---|
| `QuestionFeedback` ("Вопрос не подходит") | Module 4 | A **candidate** flags a specific probe question as poorly authored — feeds question-template quality, Backlog #25. |
| `DisputeCase` | Module 7 | A **candidate** disputes a specific conclusion about *themselves* — individual correction, human-reviewed, logged. |
| `ReturnTrigger`/growth history | Module 8 | Tracks whether a candidate acts after a nudge — a retention signal, not a correctness signal. |
| **`RecruiterFeedback`** (this module) | Module 14 | A **recruiter** reports whether a candidate's Trust/PROF turned out to match reality after a real-world interaction (interview, hiring decision) — an aggregate, cross-candidate **calibration** signal for the scoring formulas themselves, per the master document's "Trust Accuracy" metric. |

**This module's data must never get merged into any of the first three** — a recruiter's feedback about how well a score predicted reality is a fundamentally different kind of signal (aggregate, statistical, formula-facing) than a candidate disputing one fact about themselves (individual, case-facing). Keep the queues and their consumers separate.

**Also worth being explicit about upfront: this module is the actual mechanism that resolves the "calibration-pending, Ch.13" placeholder constants flagged throughout this entire FRD series** — Module 3's status→score mapping (§4.4), Module 6's independence-weighting formula (§4.2), Module 8's freshness-decay countdown (§4.3), Module 10's relevance threshold (§4.2), and Module 13's any-future bias-cost figures. This module doesn't recalibrate any of them automatically — it's the evidence base a human operator uses to decide whether/how to (§5, US3).

---

## 1. Purpose

Per the master document's own roadmap, this module implements the **"Trust Accuracy"** metric directly: *"совпадение AI-оценки с результатом живого интервью."* Everything else in this product can be internally consistent and still be wrong about the world — this module is the only place that actually checks the scoring system against reality, through the people positioned to observe that reality (recruiters who went on to interview or hire).

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| P5 — Dynamic Trust | Calibration changes how the *formula* scores future candidates — it must never retroactively punish the specific candidate whose case prompted the recalibration. |
| XAI (cross-cutting) | Any actual change to a scoring constant requires a mandatory, logged rationale — same discipline already established for Module 7's `ModeratorOverride`, applied here at the formula level instead of the individual-case level. |
| Evidence-Based Hiring, applied reflexively | The product holds its own scoring to the same evidentiary standard it holds candidates to — a claim ("this component predicts real-world fit") is only as good as its track record against outcomes. |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- Low-friction, single-action relevance outcome reporting after a recruiter interaction (US1)
- Granular, optional per-component/per-requirement "useful" vs. "misleading" feedback, addressed to the exact `Explanation`/subject the recruiter saw (US2)
- Operator-facing aggregation: misleading/useful rates per subject, flagged when they exceed a threshold with sufficient sample size, plus the `Trust Accuracy` metric itself (US3)
- A logged, human-reviewed `CalibrationConstantChangeLog` — any actual change to a named calibration constant requires this, never an automatic adjustment (US3)
- Selective audit batch creation (random or **divergence-prioritized**: cases where recruiter-reported outcome contradicted the score) that feeds directly into Module 7's existing `DisputeCase`/review machinery (US4)
- Aggregate pattern-finding across an audit batch — "what subject types were most often overridden" — distinct from Module 7's per-case review (US4)

### 2.2 Out of scope (explicitly deferred)
- Any automatic, un-reviewed adjustment of scoring formulas from live feedback — explicitly not built, this is a hard constraint (§5, US3), not a missing feature
- The retrospective 30-candidate validation test itself as an operational research project (Ch.13's "Калибровка и итерация" stage) — that's a research/ops process this module's tooling *supports*, not a feature this FRD delivers as a product screen
- Real recruiter/operator authentication — reuses the local mode-switch pattern already established (Modules 7/12), not rebuilt here
- Any change to Module 4's `QuestionFeedback` or Module 7's `DisputeCase` mechanics — this module is a new, fourth mechanism, not a modification of the other three (§0)

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values (`confirmed_relevant`, `not_relevant`, `partially_relevant`, `useful`, `misleading`) | English |
| All UI copy | **Russian**, matching the register already established across Modules 2–13 |

New copy needed:
- Relevance outcome prompt (low-friction, single question): *"Кандидат оказался релевантен после собеседования?"* with three clearly-labeled options — *"Да"*, *"Нет"*, *"Частично"*.
- Granular feedback prompt (optional, per-item): *"Эта информация оказалась полезной или вводящей в заблуждение?"* attached directly to the specific Trust component/competency/requirement the recruiter is viewing.
- Operator-facing calibration copy has no established precedent yet (first purely internal/operator screen after Module 7's moderator queue) — plain, factual, internal-tool register, same standard as Module 7 §3 established for moderator-facing copy.

---

## 4. Data Model

Local-first, consistent with Modules 2–13. This module reads Module 12/13's recruiter-interaction context and writes `RecruiterFeedback`; it computes (not stores as separate business data) `CalibrationInsight`/`TrustAccuracyMetric` aggregations; and it writes `CalibrationConstantChangeLog` and `AuditBatch`, the latter producing real Module 7 `DisputeCase` records rather than a parallel entity.

### 4.1 `RecruiterFeedback`
```json
{
  "id": "rf_001",
  "recruiter_session_id": "string",
  "candidate_id": "cand_001",
  "vacancy_id": "vac_001",
  "relevance_outcome": "confirmed_relevant | not_relevant | partially_relevant",
  "component_feedback": [
    { "explanation_id": "expl_010", "verdict": "useful | misleading", "comment_ru": "string | null" }
  ],
  "free_text_comment": "string | null",
  "submitted_at": "ISO8601"
}
```
- `relevance_outcome` is the only mandatory field — everything else (`component_feedback`, `free_text_comment`) is optional, keeping the base action low-friction so recruiters actually complete it (consistent with this product's general low-friction ethos, e.g. Module 4's optional `candidate_statement`).
- `component_feedback[].explanation_id` addresses the **exact** Module 7 `Explanation` the recruiter was looking at — this reuses the canonical explanation-addressing scheme rather than inventing a second, looser way to say "the Trust section was misleading."
- **Hard constraint:** submitting `RecruiterFeedback` must never write to, or in any way immediately change, the referenced candidate's own `PROFIndexSnapshot`/`TrustScoreSnapshot` — this is an input to aggregate calibration (§4.2), never a live per-candidate score mutation. A single recruiter's negative opinion must not be able to tank a specific candidate's score; that would violate Module 6's non-punitive/objectivity guarantees this whole product is built on.

### 4.2 `CalibrationInsight` (computed aggregation, operator-facing, not independently persisted business data)
```json
{
  "subject_type": "trust_component | prof_competency | match_requirement",
  "subject_id": "understanding",
  "sample_size": 42,
  "misleading_rate": 0.31,
  "useful_rate": 0.69,
  "flagged_for_review": true
}
```
- `flagged_for_review` requires both a minimum `sample_size` (calibration-pending constant, name it, don't hardcode inline) **and** `misleading_rate` above a calibration-pending threshold — a single comment must never trigger a "systematic problem" flag; this guards against exactly the kind of false-pattern-from-noise error this module exists to prevent, not commit.

### 4.3 `TrustAccuracyMetric` (the master document's named metric)
```json
{
  "period_label": "string",
  "total_feedback_count": 30,
  "matching_count": 24,
  "trust_accuracy_pct": 80
}
```
- `matching_count` = feedback entries where the recruiter's `relevance_outcome` agreed with what the candidate's Trust/PROF would have predicted (e.g. high Trust/PROF + `confirmed_relevant`, or low Trust/PROF + `not_relevant`) — the exact agreement rule (thresholds, how `partially_relevant` counts) is itself a calibration decision, not fixed by this FRD; ship the comparison logic as a clearly named, swappable function so this doesn't quietly become the first "final" formula in a document full of explicitly-provisional ones.

### 4.4 `CalibrationConstantChangeLog` (append-only, mirrors Module 7's `ModeratorOverride` discipline at the formula level)
```json
{
  "id": "ccl_001",
  "constant_ref": "module6.independence_weighting.v1 | module3.status_score_mapping | module8.decay_countdown_days | module10.min_match_score_to_notify",
  "previous_value": "any",
  "new_value": "any",
  "rationale_ru": "string",
  "based_on": { "feedback_count": 30, "trust_accuracy_before": 68 },
  "applied_by": "operator",
  "applied_at": "ISO8601"
}
```
- **`rationale_ru` is mandatory** — same symmetry rule as Module 7's `ModeratorOverride`: a human changing how the system scores *everyone* going forward is at least as consequential as a human overriding one candidate's status, and must be held to the same explainability standard.
- **Append-only** — same hard constraint as every other history log in this series (Modules 7/8): corrections are new entries, never edits to old ones, so the full calibration history is reconstructable.
- This is the **only** legitimate path by which any of this series' calibration-pending constants may actually change — no code path anywhere else should silently update one of these values without producing a corresponding log entry here.

### 4.5 `AuditBatch` (US4, produces real Module 7 `DisputeCase` records)
```json
{
  "id": "batch_001",
  "selection_criteria": "random | high_divergence",
  "candidate_ids": ["cand_003", "cand_017"],
  "dispute_case_ids": ["dc_010", "dc_011"],
  "created_at": "ISO8601"
}
```
- `high_divergence` selection prioritizes candidates whose `RecruiterFeedback.relevance_outcome` contradicted their score's implied prediction — a far more efficient use of a two-person team's limited manual-review bandwidth (Ch.13's own framing) than pure random sampling, and should be the default recommended mode, with `random` available for genuinely unbiased spot-checks.
- Each selected candidate becomes exactly one Module 7 `DisputeCase(origin: "sampled_audit")` — this module does not build a second review UI; Module 7's existing queue/uphold/override/history mechanism handles the actual case review unmodified.

---

## 5. Functional Requirements

### US1 — Mark whether a candidate was genuinely relevant after viewing the profile

| ID | Requirement |
|---|---|
| FR1.1 | After a recruiter interaction has reached at least Module 13's Stage 2 (identity revealed) for a candidate/vacancy pair, the recruiter can submit a single-action `relevance_outcome` — a light, one-tap action (`"Да"`/`"Нет"`/`"Частично"`), not a mandatory blocking form. |
| FR1.2 | Submitting `relevance_outcome` alone (no granular detail) is a fully valid, complete submission — this module must not pressure recruiters into more detail than they're willing to give, or the base action will simply go unused, undermining the whole calibration pipeline this module exists to feed. |
| FR1.3 | **Hard constraint:** no code path triggered by `RecruiterFeedback` submission may write to the referenced candidate's own `PROFIndexSnapshot`/`TrustScoreSnapshot` — this is strictly an aggregate calibration input (§4.1), verified the same way Module 6's non-punitive rule was verified (code-review checklist item, not just a UI convention). |

**Acceptance criteria:** a recruiter can report a relevance outcome in one action after an interaction, and doing so never visibly changes anything about that specific candidate's own scores.

---

### US2 — Indicate which parts of the profile were useful or misleading

| ID | Requirement |
|---|---|
| FR2.1 | Alongside the base `relevance_outcome`, a recruiter can optionally mark any specific Trust component, PROF competency, or Match requirement they viewed (addressed via its `Explanation.id`, reusing Module 7's canonical scheme) as `useful` or `misleading`, with an optional comment. |
| FR2.2 | This granular feedback must be reachable from the exact same view where the recruiter saw that `Explanation` in the first place (Module 7/12's existing "why" views) — not a separate, decontextualized feedback form the recruiter has to reconstruct their own memory of what they were looking at to fill in. |
| FR2.3 | Multiple `component_feedback` entries can be attached to a single `RecruiterFeedback` submission — a recruiter isn't limited to flagging just one thing about a candidate's profile. |

**Acceptance criteria:** a recruiter can flag one or more specific, addressable parts of a candidate's profile as useful or misleading, directly from the screen where they encountered that information, without a separate reconstruction step.

---

### US3 — Use recruiter feedback to calibrate PROF and Trust

| ID | Requirement |
|---|---|
| FR3.1 | The operator has an aggregation view surfacing `CalibrationInsight` (§4.2) per `subject_type`/`subject_id` — misleading/useful rates, with `flagged_for_review` requiring both minimum sample size and a calibration-pending misleading-rate threshold (never a single-comment trigger). |
| FR3.2 | The operator can view the `TrustAccuracyMetric` (§4.3) — the master document's own named calibration metric, computed directly from accumulated `RecruiterFeedback` against each candidate's Trust/PROF at the time of feedback. |
| FR3.3 | **Hard constraint, the actual point of this module:** any real change to a calibration-pending constant anywhere in this FRD series (Module 3/6/8/10/13's named, swappable placeholder values) must go through a `CalibrationConstantChangeLog` entry (§4.4) with mandatory `rationale_ru` — there is no automatic, feedback-triggered recalculation of any scoring formula. A human reviews the aggregated evidence and makes a deliberate, logged decision, same discipline already established for Module 7's `ModeratorOverride`, just applied one level up (the formula, not the individual case). |
| FR3.4 | A calibration change recorded here affects scoring **going forward only** — it must never retroactively alter a specific candidate's historical `TrustScoreSnapshot`/`PROFIndexSnapshot` versions (Module 6/3's versioning already establishes this pattern: past snapshots are historical fact, only new computations use the updated constant). |

**Acceptance criteria:** an operator can see which specific components/competencies/requirements are statistically flagged as misleading (with sufficient sample size), see the current Trust Accuracy figure, and — if they decide to act on it — only do so through a logged, rationale'd change that applies prospectively, never retroactively.

---

### US4 — Conduct selective manual audit to identify systematic errors

| ID | Requirement |
|---|---|
| FR4.1 | The operator can create an `AuditBatch` (§4.5) by either `random` selection or `high_divergence` selection (candidates whose recruiter-reported outcome contradicted their score) — `high_divergence` should be the recommended default given limited manual-review capacity (Ch.13's explicit framing of a two-person team). |
| FR4.2 | Each candidate selected into a batch produces exactly one Module 7 `DisputeCase(origin: "sampled_audit")` — this module is the **selector**, Module 7 remains the **reviewer**; do not build a second case-review UI here. |
| FR4.3 | This module adds an aggregate view **across** a completed batch's resulting `DisputeCase`s — which `subject_type`s were most often overridden, whether overrides cluster around a specific competency or Trust component — this is the "identify *systematic* errors" part of US4, distinct from Module 7's per-case handling, and should itself feed back into US3's calibration-insight view (a batch that reveals a systematic pattern is exactly the kind of evidence a `CalibrationConstantChangeLog` entry should cite in its `rationale_ru`). |

**Acceptance criteria:** an operator can select a batch of profiles for manual review (ideally prioritizing divergent cases), have each one land in Module 7's existing review queue unmodified, and afterward see an aggregate pattern summary across the whole batch, not just individual case outcomes.

---

## 6. UI Flow

Mostly new, operator-facing screens, plus one lightweight recruiter-facing addition:

1. **Extend Module 12/13's recruiter candidate view:** a small, persistent, low-friction relevance-outcome prompt (FR1.1) — three buttons, always available after Stage 2, never a blocking modal.
2. **Extend Module 7's `Explanation` views (as seen through Module 12):** an optional "useful/misleading" micro-action attached to each component (FR2.1–2.2) — small, secondary, not competing visually with the base relevance-outcome action.
3. **New operator screen: Calibration Dashboard** — `CalibrationInsight` table, `TrustAccuracyMetric` display, and the entry point for creating a `CalibrationConstantChangeLog` entry (which must always require the `rationale_ru` field before it can be submitted — enforce this in the form itself, not just as a documented convention).
4. **New operator screen: Audit Batch creation** — choose `random`/`high_divergence`, review resulting batch, then hand off directly into Module 7's existing moderator queue for the actual case-by-case review; a separate aggregate-summary view appears once a batch's cases are resolved (FR4.3).

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication:** reuses Module 12's recruiter-mode and Module 7's operator/moderator-mode local toggles — no new access-control mechanism introduced here.
- **Append-only enforcement for `CalibrationConstantChangeLog`:** same code-level constraint as every other history log in this series — no update/delete path.
- **Aggregation is computed, not duplicated storage:** `CalibrationInsight`/`TrustAccuracyMetric` should be derived on read from `RecruiterFeedback`, not maintained as a separately-updated running total that could drift out of sync with the underlying feedback records.
- **Named, swappable constants throughout:** the minimum-sample-size and misleading-rate thresholds (§4.2), and the outcome-agreement rule (§4.3), must all be implemented the same way every other calibration-pending value in this series has been — clearly named, not inline magic numbers.

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| The retrospective 30-candidate validation test itself | A research/ops project (Ch.13's Stage 3), not a product feature — this module's tooling supports it, doesn't automate the whole study. |
| Exact `TrustAccuracyMetric` agreement rule (how `partially_relevant` counts, exact score thresholds) | Explicitly a calibration decision, not fixed by this FRD — implement as a swappable function, not a hardcoded rule presented as final. |
| Minimum sample size / misleading-rate thresholds for `flagged_for_review` | Calibration-pending, same convention as every other placeholder constant in this series. |
| Real recruiter/operator authentication | Reuses existing local mode-switch patterns (Modules 7/12) — not addressed further here. |

---

**H2/H3 hypothesis this module exists specifically to test (per the master document's own hypothesis ordering):**
- This module is the actual instrument for **H2 (Verification Value)** — does the combination of digital footprint and Contextual Probe genuinely add information about profile trustworthiness, or does it add noise — and secondarily informs **H3 (Recruiter Value)**. If `trust_accuracy_pct` sits near chance level even after a reasonable sample size, that's a direct signal the core scoring model needs rethinking, not just its constants recalibrating — a distinction worth keeping visible in how this module's output gets discussed internally, not just its raw numbers.
