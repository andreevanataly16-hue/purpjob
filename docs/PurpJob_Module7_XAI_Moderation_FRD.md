# PurpJob — Module 7: XAI & Moderation
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-0]
**Phase:** Local prototype (no authentication layer, no persistent backend, single local candidate session — see §7 for how the moderator role is handled without real auth)
**Depends on:** Module 3 (PROF.Index competency statuses), Module 4 (Contextual Probe question `reason_ru`), Module 6 (Trust Score component `explanation_ru`, `ContradictionCase`/`AttributionFinding`)
**Consumes but does not build:** anomaly detectors themselves (stylometry vs. Raw Input baseline, tab-switching) — accepted as an external event producer, see §2.2

---

## 1. Purpose

**Governing principle for this entire module, stated directly in the source spec: AI proposes a conclusion, it must never become an unappealable judge of the candidate.** Every requirement below exists to make that literally true in the architecture, not just true in the marketing copy — every automated conclusion must be (a) explained in checkable facts, (b) traceable to specific Evidence, (c) disputable by the candidate, (d) reviewable by a human, and (e) any human override must be permanently, precisely logged. This module is the closed loop that makes those five properties actually hold across every other module's output.

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| P1 — Evidence-Based Hiring | Every conclusion must resolve to specific Evidence, not just a claim about Evidence (US2). |
| XAI (Ch.9) | This module is the formalization of the "no bare score/status without a checkable reason" rule already required piecemeal in Modules 3, 4, and 6 — here it becomes one canonical, queryable contract instead of three separate ad-hoc ones (US1). |
| P5 — Dynamic Trust / non-punitive rule | Disputing a conclusion never itself changes any score — it's a request for review, not an admission (US3). |
| Ch.13 — Explainability as operational backbone | A moderator reviews a specific factual claim, not an entire decision from scratch — this is what makes manual moderation viable for a two-person team (US4). |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- A **canonical `Explanation` object** that unifies the "why" outputs already required in Modules 3 (competency status), 4 (probe question `reason_ru`), and 6 (Trust component `explanation_ru`) into one consistent, queryable shape — candidate-facing (US1)
- Guaranteed Evidence drill-down from any `Explanation` to the actual underlying `Evidence`/`Statement`/`Answer` records (US2)
- A general-purpose **dispute/escalation mechanism**: candidate can flag any `Explanation` as disputed and send it to manual moderation — distinct from Module 6's self-service Case 2 (three-path contradiction resolution); this is for when the candidate disagrees with the system's conclusion itself, or isn't satisfied by the self-service paths available there (US3)
- A **moderator queue view**: list of open `DisputeCase`s (from candidate escalation, accepted anomaly flags, or sampled audit) with the same factual `Explanation` and Evidence the candidate saw, plus moderator actions: uphold / override / request more info (US4)
- An **immutable, append-only history log** of every dispute case's state transitions and any resulting score/status change, viewable by both the candidate (their own case) and the moderator (US5)
- Local, no-real-auth implementation of the moderator role as a distinct UI mode (§7)

### 2.2 Out of scope (explicitly deferred)
- **The anomaly detectors themselves** (psycholinguistic/stylometric comparison against Raw Input, tab-switching/blur-focus detection) — per the master document these are tagged [MVP] under Ch.9, but building them is not requested by this module's five user stories and is a materially different engineering task (behavioral/text analysis, not explanation/moderation UI). This module accepts an `AnomalyFlag` event shape (§4.4) as an input to the moderation queue without building the producer — **flagging this explicitly so the detector work isn't silently dropped from scope**, it needs its own FRD if intended for this phase.
- Recruiter-facing display of explanations ("XAI works in both directions, with candidate consent" per the master doc) — no recruiter surface exists yet in this local phase; this module prepares a consent field (§4.1) but doesn't build any recruiter-side rendering
- "Цена предубеждения" (simplified bias-cost signal) and Progressive Reveal — both explicitly recruiter-facing Ch.9 features, not this module
- Periodic sampled random audit as an *operational process* (a few profiles/week reviewed manually) — this is a team workflow (Ch.13), not application logic; this module only makes sampled cases representable as a `DisputeCase(origin: "sampled_audit")` so the workflow has somewhere to land
- Real authentication/RBAC for the moderator role — local mode-switch only in this phase, explicitly flagged as not production-safe (§7)
- Reward mechanics for confirmed question-quality bugs (Backlog #25) — that's Module 4's adjacent concern (question feedback), not this module's dispute mechanism, even though both feed the same underlying "manual review queue" idea operationally

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values (`prof_competency_status`, `trust_component`, `contradiction_finding`, `candidate_escalation`, `anomaly_flag`, `sampled_audit`, `queued`, `in_review`, `resolved_upheld`, `resolved_overridden`) | English |
| All UI copy: explanation text, dispute prompts, moderator-facing labels | **Russian**, matching the register already established across Modules 2–6 |

Reuse existing established patterns, do not re-derive:
- Factual explanation style already fixed in Module 6 §3: *"в логах Jira 0 упоминаний участия в Code Review коллег"* — this is now the house style for **every** `Explanation.conclusion_ru` in the system, not just Trust Score's.
- `"Почему такой вывод?"` — proposed universal entry point label next to any score/status; use this consistently rather than inventing a different phrase per module.
- Dispute action label: `"Оспорить и передать на модерацию"` — must read as a normal, low-friction action, not a formal grievance process; matches the product's overall non-adversarial tone.

Moderator-facing UI copy has no established precedent yet in this product (no moderator screens exist before this module) — author it in a plain, internal-tool register, distinct from candidate-facing warmth; it doesn't need the same tone-of-voice care since it's not a candidate touchpoint, but it must still be precise and fact-anchored, not just internally consistent for its own sake.

---

## 4. Data Model

Local-first constraint, consistent with Modules 2–6: flat local JSON. This module reads Explanations from Modules 3/4/6 (normalizing their existing fields into one shape) and writes its own `DisputeCase[]`/`DisputeHistoryEntry[]`/`ModeratorOverride[]`.

### 4.1 `Explanation` (canonical, cross-module contract)
```json
{
  "id": "expl_001",
  "subject_type": "prof_competency_status | trust_component | contradiction_finding | probe_question_reason",
  "subject_id": "rest_api_design",
  "conclusion_ru": "В логах Jira 0 упоминаний участия в Code Review коллег.",
  "evidence_refs": ["ev_003", "a_007"],
  "generated_by": "module_3 | module_4 | module_6",
  "candidate_consent_for_recruiter_view": false,
  "created_at": "ISO8601"
}
```
- **Compatibility note (small patch required to Modules 3/4/6):** those modules already produce this information under their own field names (`Statement`'s status "why", `Question.reason_ru`, `TrustScoreSnapshot.components[].explanation_ru`). This module doesn't ask them to stop doing that — it asks that each of those be **also** exposed through this canonical shape, so there's one place the candidate (and later, a moderator) can query "why" for anything in the product, instead of three inconsistent per-module views. Treat this as a thin adapter layer per producing module, not a rewrite of their internal logic.
- `evidence_refs` must never be empty for a `confirmed`/scored conclusion — for a `not_started`/zero conclusion, it may legitimately be empty, but the `conclusion_ru` must say so explicitly (e.g. *"Пока нет ни одного независимого подтверждения"*), never leave the field silently empty with no comment.
- `candidate_consent_for_recruiter_view` is a forward-compatible field only in this phase (§2.2) — no recruiter surface reads it yet.

### 4.2 `DisputeCase`
```json
{
  "id": "dc_001",
  "explanation_id": "expl_001",
  "origin": "candidate_escalation | anomaly_flag | sampled_audit",
  "candidate_statement": "string | null",
  "status": "queued | in_review | resolved_upheld | resolved_overridden | needs_more_info",
  "assigned_moderator": "string | null",
  "created_at": "ISO8601"
}
```
- `candidate_statement` is optional — the candidate is never required to build a case or justify why they're disputing something; "I don't think this is right" with no elaboration is a fully valid, sufficient reason to escalate (consistent with the product's non-punitive, low-friction posture elsewhere).
- Creating a `DisputeCase` **never** changes `status` on the underlying subject (competency status, Trust component score) — it only adds a pending review record. See FR3.3.

### 4.3 `DisputeHistoryEntry` (append-only, US5)
```json
{
  "dispute_case_id": "dc_001",
  "event_type": "opened | status_changed | moderator_note_added | override_applied | info_requested | candidate_responded",
  "actor": "candidate | moderator | system",
  "before_value": "any | null",
  "after_value": "any | null",
  "note_ru": "string | null",
  "timestamp": "ISO8601"
}
```
- **Hard constraint: append-only.** No code path may edit or delete an existing `DisputeHistoryEntry` — corrections are new entries, never mutations of old ones. This is the actual mechanism behind "restore why Trust or a profile changed" (US5) — if entries could be edited, the history would stop being trustworthy as a record.
- Every `DisputeCase` must have at least the `opened` entry the moment it's created — there is no such thing as a dispute case with no history.

### 4.4 `ModeratorOverride`
```json
{
  "dispute_case_id": "dc_001",
  "target_type": "prof_competency_status | trust_component_score | contradiction_case_resolution",
  "target_id": "rest_api_design",
  "previous_value": "limited",
  "new_value": "medium",
  "rationale_ru": "Кандидат предоставил дополнительный контекст, подтверждающий независимость источника.",
  "applied_at": "ISO8601"
}
```
- `rationale_ru` is **mandatory**, not optional — this is the moderator-side mirror of the same XAI rule the system itself must follow (FR1.2): a human override without a stated reason would be exactly the "unappealable judge" problem this module exists to prevent, just moved from AI to a person.
- An override always targets one **specific** field on one specific subject — never a blanket "fix this candidate's profile" action (FR4.4).
- Applying a `ModeratorOverride` must also append a `DisputeHistoryEntry(event_type: "override_applied")` with matching `before_value`/`after_value` — these two records must never diverge; if practical, generate the history entry automatically from the override record rather than requiring two independent writes.

### 4.5 `AnomalyFlag` (accepted external event shape, no producer built here)
```json
{
  "id": "af_flag_001",
  "flag_type": "stylometric_mismatch | tab_switching | keystroke_anomaly",
  "subject_evidence_or_answer_id": "a_001",
  "detected_at": "ISO8601"
}
```
- This module accepts this shape and can create a `DisputeCase(origin: "anomaly_flag")` from it — but no detector producing these exists in this phase (§2.2). Do not fabricate a fake detector to demonstrate the flow; leave this path genuinely unreachable until the detector module is built, and say so in any demo.

---

## 5. Functional Requirements

### US1 — Understand why the system reached a specific PROF or Trust conclusion

| ID | Requirement |
|---|---|
| FR1.1 | Every PROF.Index competency status (Module 3) and every Trust Score component (Module 6) must be queryable as a canonical `Explanation` (§4.1) via the small adapter layer noted there — not just visible as a string somewhere in that module's own UI. |
| FR1.2 | `Explanation.conclusion_ru` must always be a checkable fact, never a bare adjective/verdict — this is the same rule already fixed in Module 6 §3, now made universal across all `subject_type` values, not just Trust components. |
| FR1.3 | A single, consistent entry point (`"Почему такой вывод?"`) must appear next to every score/status surface in the product (PROF radar, Evidence Map status, Trust Score components, probe question reasons) and route to the same `Explanation` detail view regardless of which module produced it — the candidate should never have to learn three different "why" UI patterns for three different scores. |

**Acceptance criteria:** for any PROF competency status or Trust component score shown anywhere in the product, the candidate can reach one consistent explanation view with a factual, checkable statement — not a different pattern per module.

---

### US2 — See the concrete Evidence behind a conclusion

| ID | Requirement |
|---|---|
| FR2.1 | Every `Explanation` with a non-empty `evidence_refs` list must let the candidate open each referenced item and see the actual underlying record (`Evidence.raw_text`/`url`/`file_ref` from Module 2, or the specific `Answer.text` from Module 4) — a reference that doesn't resolve to a real, viewable record is a defect, not an acceptable simplification. |
| FR2.2 | An `Explanation` for a `not_started`/zero conclusion must explicitly say there's no evidence yet (per §4.1) rather than silently showing an empty list with no comment — absence of evidence must always be stated as a fact, same as presence of evidence. |
| FR2.3 | Where a conclusion is based on **multiple** pieces of Evidence (e.g. Trust Score's independence-weighted aggregation, Module 6 §4.2), the `Explanation` view must show all of them, not just the most recent or most convenient one to display — partial disclosure of the evidentiary basis would violate the same transparency rule as no disclosure at all. |

**Acceptance criteria:** from any `Explanation`, the candidate can open every one of its `evidence_refs` and see the real content behind it, with no dead links and no unexplained gaps.

---

### US3 — Dispute a result and escalate to manual moderation

| ID | Requirement |
|---|---|
| FR3.1 | Every `Explanation` view offers an `"Оспорить и передать на модерацию"` action, distinct from and in addition to Module 6's self-service Case 2 resolution (delete/explain/correct) — this path is for when the candidate disagrees with the system's conclusion or its logic itself, not just wants to add context to a specific contradiction. A candidate may reach this path either directly from any `Explanation`, or after finding Module 6's three self-service options don't fit their situation. |
| FR3.2 | Creating a `DisputeCase` requires only selecting which `Explanation` is disputed — `candidate_statement` (free text) is optional, never mandatory, consistent with the product's non-punitive, low-burden posture. |
| FR3.3 | **Escalating a dispute never itself changes any score or status.** The subject stays exactly as it was, pending review — disputing is a request for review, not an admission of anything and not an automatic downgrade either way. |
| FR3.4 | The candidate can track their own `DisputeCase.status` (`queued`/`in_review`/`resolved_upheld`/`resolved_overridden`/`needs_more_info`) and see the full `DisputeHistoryEntry` timeline for their own case (§5.5, US5) — this is not a black-box ticket system where they submit and wait blindly. |

**Acceptance criteria:** a candidate can dispute any conclusion shown anywhere in the product with a single action and no mandatory justification, see zero immediate score change, and track the case's status and history afterward.

---

### US4 — Moderator reviews disputed cases and corrects erroneous conclusions

| ID | Requirement |
|---|---|
| FR4.1 | The moderator queue lists all `DisputeCase`s with `status` in (`queued`, `in_review`, `needs_more_info`), sourced from all three `origin` values (candidate escalation, accepted anomaly flags, sampled audit) in one unified view — a moderator should not need to check three different places for three different origins of the same underlying "needs a human look" event. |
| FR4.2 | Opening a case shows the moderator the **exact same** `Explanation` and resolved `evidence_refs` the candidate saw — not a separate, richer "internal" view diverging from what was shown to the candidate. Per Ch.13's operating principle, this is what lets a moderator check one specific factual claim quickly, rather than re-investigating an entire profile from scratch. |
| FR4.3 | Moderator actions on a case, in order of increasing consequence: **(a) uphold** — no change, case closes as `resolved_upheld` with a mandatory short rationale; **(b) request more info** — case moves to `needs_more_info`, candidate is asked a specific, named follow-up (reusing the same factual-question pattern as everywhere else in the product, not a vague "please clarify"); **(c) override** — creates a `ModeratorOverride` (§4.4) with mandatory `rationale_ru`, case closes as `resolved_overridden`. |
| FR4.4 | An override must always target one specific `target_type`/`target_id` (one competency status, one Trust component score, one contradiction resolution) — a moderator cannot apply a blanket profile-wide adjustment through this mechanism. If a moderator believes multiple things need correcting, that's multiple overrides, each independently rationale'd and logged. |
| FR4.5 | Every moderator action must append the corresponding `DisputeHistoryEntry` (§4.3) — there is no moderator action in this module that doesn't produce a permanent, attributed record. |

**Acceptance criteria:** a moderator can open any queued case, see exactly what the candidate saw plus the resolved evidence, and resolve it via uphold/request-info/override — with every path producing a mandatory rationale and a corresponding history entry.

---

### US5 — Persist history of dispute-case changes so Trust/profile changes are reconstructable

| ID | Requirement |
|---|---|
| FR5.1 | `DisputeHistoryEntry` records are append-only and immutable (§4.3, hard constraint) — enforce this at the code level (no update/delete operation should exist for this entity in the codebase), not just as a team convention. |
| FR5.2 | The full history for any `DisputeCase` must be viewable by both the candidate (their own case) and the moderator — this extends the "no black box" principle from scoring itself to the *process* of reviewing and overriding a score, which is just as capable of feeling arbitrary if it's opaque. |
| FR5.3 | A `ModeratorOverride`'s logged `previous_value`/`new_value` (§4.4) must be precise enough to fully reconstruct the prior state — not a vague "score improved," but the exact prior and new value of the specific targeted field. |
| FR5.4 | This history mechanism is the actual implementation behind Module 6's forward-compatible `TrustScoreSnapshot.version` field — connect the two directly (an override that changes a Trust component should increment that snapshot's version and be traceable back to the `DisputeHistoryEntry` that caused it) rather than building a second, disconnected versioning concept. |

**Acceptance criteria:** for any resolved dispute case, both the candidate and a moderator can reconstruct exactly what the system originally concluded, what was disputed, who reviewed it, what (if anything) was changed, to what value, and why — as an ordered, unmodifiable timeline.

---

## 6. Cross-cutting architectural rule (from the source spec's governing principle)

This isn't a separate user story, but it's the requirement that ties all five together and must be checked against every other requirement in this document:

| ID | Requirement |
|---|---|
| FR-Gov.1 | No `Explanation` may ever be rendered without its associated dispute entry point (FR3.1) — there is no "final," undisputable conclusion anywhere in this module's scope. |
| FR-Gov.2 | No score/status change resulting from moderation may occur without a `ModeratorOverride` record and its mandatory `rationale_ru` (FR4.3c) — a moderator adjusting a value by editing underlying data directly, bypassing this module, would defeat the entire purpose of the module and must not be a possible code path. |
| FR-Gov.3 | Every state change this module causes must be logged before/as it takes effect, not backfilled after the fact — `DisputeHistoryEntry` write and the actual score/status change should be as close to atomic as the local storage model allows. |

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication, including for the moderator role.** This phase implements the moderator queue/actions as a **distinct local UI mode** (e.g. a mode toggle, not a login), reachable in the same local prototype — there is no real access control here, and this must be flagged clearly in code/README as **not production-safe**: real RBAC (who is allowed to be a moderator, audit of moderator identity) is required before any multi-user deployment.
- **Immutability enforcement:** `DisputeHistoryEntry` should be implemented as an append-only log structure (e.g. a simple array that's only ever pushed to, never spliced/mapped-and-replaced) — this is cheap to get right locally and expensive to retrofit later, worth doing correctly now even though the local JSON store has no database-level immutability guarantees to lean on.
- **Adapter layer, not a rewrite:** the compatibility patch needed for Modules 3/4/6 (§4.1) should be additive — each module keeps its existing internal field names and logic, and exposes an additional thin mapping into the canonical `Explanation` shape. Do not use this module as a pretext to refactor those three modules' internals.

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| Anomaly detectors (stylometry vs. Raw Input, tab-switching) | Tagged [MVP] in the master document's Ch.9, but not requested by this module's five user stories and a materially different engineering task — needs its own FRD if it's meant to ship alongside this module. |
| Recruiter-facing explanation display + candidate consent gate | No recruiter surface exists in this local phase; `candidate_consent_for_recruiter_view` field is prepared but unused. |
| Sampled random audit as a scheduled operational process | Team workflow (Ch.13: "a few profiles a week, manually"), not application logic — this module only makes a sampled case representable as a `DisputeCase`. |
| Real moderator authentication/RBAC | Explicitly deferred per §7 — local mode-switch only, flagged as not production-safe. |
| Reward mechanism tie-in for confirmed question-quality bugs (Module 4, Backlog #25) | Adjacent but separate feedback loop; this module's dispute mechanism is for conclusions about the candidate, not question quality — don't conflate the two queues even though both eventually involve manual review. |

---

**H1 hypotheses this module should let you test (not guarantees):**
- H1 (Moderation load feasibility): the volume of `DisputeCase`s a two-person team can resolve per week, given the "review one factual claim, not a whole decision" design (FR4.2), is the actual test of whether Ch.13's "manual moderation is viable at MVP scale" assumption holds — instrument time-per-case from the start so this is measurable.
- H1 (Dispute rate as a quality signal): if a particular `subject_type` (e.g. a specific Trust component, or a specific type of contradiction check) generates disproportionately more disputes than others, that's a direct signal the underlying scoring logic in that module needs recalibration (Ch.13) — this module's data should make that pattern visible, not just log disputes for their own sake.
