# PurpJob — Module 6: Trust Score
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-0]
**Phase:** Local prototype (no authentication layer, no persistent backend, single local candidate session)
**Depends on:** Module 2 (`Evidence`/`Statement`, `DeclineRecord`), Module 4 (Understanding signal, Semantic Depth, Authenticity mechanics — copy-paste ban, Keystroke capture hook), Module 5 (NDA-sourced Evidence counts identically toward Trust)
**Consumes but does not own:** Module 3's PROF×Trust decision matrix (that matrix lives in Module 3's scope as a recruiter-facing concept; this module only produces the Trust Score half of it)
**Feeds into:** Module 3 (display alongside PROF.Index), future recruiter-facing modules (out of scope here — no recruiter surface exists yet)

---

## 1. Purpose

**Trust Score answers a different question than PROF.Index: not "how good is this specialist," but "how much can what's claimed in this profile actually be believed."**

> Trust Score не отвечает на вопрос "насколько хороший этот специалист". Он отвечает на вопрос "насколько достоверны сведения, на основании которых мы его оцениваем".

**Hard positioning constraint (must be reflected in every piece of UI copy this module produces):** Trust Score does **not** replace GitHub, a portfolio, references, or an interview. It aggregates existing sources and adds contextual verification of how well they match the claimed experience. Do not build or write anything that frames Trust Score as a standalone substitute for those — it's an aggregation-plus-verification layer on top of them, per the already-drafted PDF legend copy (reuse, don't rewrite):

> *"Trust Score - показатель достоверности профессионального профиля, рассчитанный на основе анализа цифрового следа и подтверждения ключевых компетенций через контекстные микро-кейсы. Не заменяет интервью, но даёт дополнительный слой информации о том, что заявленные навыки подтверждены независимыми источниками."*

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| P1 — Evidence-Based Hiring | Trust Score is a weighted aggregation of independent confirmations, never a self-reported number. |
| P5 — Dynamic Trust | Recalculated by event, not on a schedule — the score is a live snapshot of an ongoing process, not a one-time grade (US1). |
| XAI (Ch.9, cross-cutting) | No bare score without factual justification, ever — this is the module's central constraint, threaded through US2, US3, US4. |
| Non-punitive rule (Ch.6) | Weak or missing confirmation is "not yet proven," never "penalized" (US5) — this is a hard architectural constraint, not a tone choice. |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- Trust Score computation from three MVP components: **Authenticity**, **Understanding**, **Consistency** (US1)
- Independence-weighted aggregation: a new confirmation increases Trust only to the extent it adds independent information, not by raw count (US1, US2)
- Per-component, per-claim XAI explanation: concrete, fact-based, never a bare number (US2)
- "Next best action" guidance per weak/unconfirmed area — what specifically would strengthen it (US3)
- Dispute mechanism for contradictions/incorrect findings affecting Trust Score, with the master doc's fixed two-case model (US4):
  - **Case 1 — Attribution/currency:** free decline, no reason required, no score impact, nothing stays visible
  - **Case 2 — Contradiction between two already-owned facts:** three resolution paths (delete artifact / explain / correct claim), non-punitive, severity-graded
- **Local-only Consistency contradiction detection**: date-overlap and claimed-level-vs-evidence-described-level checks computed purely from the candidate's own already-provided Module 1/2 data — this is the local MVP's actual producer of Case 2 contradictions (see §2.2 on Digital Echo)
- Non-punitive scoring rule enforced structurally, not just in copy (US5)
- Keystroke Dynamics: **consumes** the raw capture hook already built in Module 4 (behind the same legal-gated feature flag) as an Authenticity input — this module does not re-implement capture, only scoring logic, and only when the flag is on

### 2.2 Out of scope (explicitly deferred)
- **Ethics** component — [V2], requires accumulated on-platform behavioral history that doesn't exist on day one
- **Integrity** (overemployment risk) component — [V3], high false-positive risk, needs Ch.13 calibration before it can affect visibility
- **Digital Echo** (cross-verification against public web presence) as an external data source — separate module (8/9), not built here. This module accepts a `contradiction`/`attribution_finding` event shape from either producer (Digital Echo, once it exists, or the local Consistency checks built here) without special-casing which one produced it
- **Employer Trust** (mirror metric for recruiter/employer behavior) — [V2], separate metric entirely, never merged into candidate Trust Score
- Snapshot-on-response/offer + diff versioning for recruiter view — depends on an application/response flow that doesn't exist yet in this local phase; this module prepares the data shape (§4.1 `version`) but doesn't build the recruiter-facing freeze/diff UI
- "Актуализировать данные" (refresh connected sources) button — depends on live OAuth source connections (GitHub/LinkedIn direct pull), which Module 2 already tags [V2]; nothing to refresh yet in this phase
- PROF×Trust decision matrix rendering — Module 3's concern; this module only guarantees Trust Score is queryable in the shape that matrix needs

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values (`authenticity`, `understanding`, `consistency`, `attribution`, `contradiction`, `delete_artifact`, `explain`, `correct_claim`) | English |
| All UI copy: explanations, dispute screens, "next best action" prompts | **Russian**, matching the register already established across Modules 2–5 |

Reuse existing drafted copy verbatim wherever it already exists — do not re-derive:
- PDF legend text (§1) for the general "what is Trust Score" framing
- XAI factual-explanation pattern: *"в логах Jira 0 упоминаний участия в Code Review коллег"* — this is the model for FR2.1: a checkable fact, not a vague verdict like *"низкий балл за командную работу"*
- Actionable XAI pattern: *"Trust 63/100. Есть три неподтверждённых утверждения. Добавление проекта X или прохождение кейса Y даст независимое подтверждение компетенции Z."*
- Digital-echo-style finding prompt: *"Мы нашли X — это совпадает с вашим профилем?"* with `"Подтвердить"` / `"Это не я / не актуально"` — reuse this exact pattern for local Case 1 attribution findings (§5.4)

New copy needed (author in the same factual, non-verdict register):
- Contradiction screen framing (Case 2): three clearly-labeled actions, e.g. *"Удалить артефакт"*, *"Пояснить"*, *"Поправить заявление"* — do not present these as a "confession" flow; frame as routine profile maintenance, matching the product's overall non-punitive tone.

---

## 4. Data Model

Local-first constraint, consistent with Modules 2–5: flat local JSON per candidate session. This module reads Module 2's `Statement[]`/`Evidence[]`/`DeclineRecord[]` and Module 4's `Answer.routing` outputs; it writes its own `TrustScoreSnapshot`, `ContradictionCase[]`, and `AttributionFinding[]`.

### 4.1 `TrustScoreSnapshot`
```json
{
  "overall_score": 63,
  "computed_at": "ISO8601",
  "version": 1,
  "components": [
    {
      "component_id": "authenticity | understanding | consistency",
      "score": 70,
      "contributing_evidence_ids": ["ev_003", "ev_007"],
      "explanation_ru": "Ответы на 3 из 4 контекстных вопросов прошли проверку на шаблонность."
    }
  ]
}
```
- Recomputed on every relevant event (new Evidence, new probe `Answer`, dispute resolution), consistent with the "recompute by event, not batch" decision already fixed for this product — implement as recompute-on-read for this local phase (same convention as Modules 3–5), not a background job.
- `version` exists now as a forward-compatible field for the future snapshot-on-response/diff feature (§2.2) — increment it on every recompute even though nothing consumes it yet in this phase.
- `explanation_ru` at the component level is mandatory, and must be a checkable fact (FR2.1), never a bare adjective/verdict.

### 4.2 Independence-weighted aggregation (placeholder formula, calibration-pending)
Per component, group `contributing_evidence_ids` by their `source_category` (Module 2 concept, reused, not reinvented). A **placeholder** weighting rule for MVP:
```
component_score = f(distinct_source_categories_confirming_the_claim)
```
where each additional confirmation from a **new** `source_category` contributes more than an additional confirmation from a category already counted, and a confirmation cross-verified by two different mechanisms simultaneously (e.g. a Contextual Probe answer **and** an independently linked artifact for the same competency) counts more than either alone. This mirrors Module 3's `strong` status rule (≥2 distinct source categories) — reuse that logic's shape rather than inventing a second, divergent formula. **Exact weights are a Ch.13 calibration hypothesis, not a validated formula** — ship as a named, swappable constant set, same convention as Module 3's §4.4.

### 4.3 `AttributionFinding` (Case 1 — free decline)
```json
{
  "id": "af_001",
  "finding_text_ru": "Мы нашли X — это совпадает с вашим профилем?",
  "source_ref": "string",
  "candidate_response": "confirmed | not_me_or_outdated | null",
  "responded_at": "ISO8601 | null"
}
```
- Declining (`not_me_or_outdated`) never lowers `overall_score`, requires no reason, and — per the master doc — nothing about a declined finding remains visible anywhere, including to a future recruiter view. This is stronger than the generic `DeclineRecord` non-punitive guarantee (§4.4 below): it's not just "no penalty," it's "no trace."
- In this local, no-external-data phase, `AttributionFinding` records can only be produced by locally-available data (e.g. two candidate-provided Evidence items referencing the same unclaimed third-party project/link) — Digital-Echo-sourced findings (public web cross-checks) are a future producer, not built here (§2.2).

### 4.4 `ContradictionCase` (Case 2 — three resolution paths)
```json
{
  "id": "cc_001",
  "statement_ids": ["stmt_001", "stmt_004"],
  "detected_by": "local_consistency_check | digital_echo",
  "check_type": "date_overlap | level_mismatch",
  "severity": "minor | major",
  "resolution_path": "delete_artifact | explain | correct_claim | null",
  "explanation_text": "string | null",
  "corrected_value": "string | null",
  "status": "open | resolved | unresolved",
  "visibility_suspended": false,
  "created_at": "ISO8601"
}
```
- `detected_by: "local_consistency_check"` is this module's own producer (§5.1, FR-Cons.1–2), fully buildable now with no external dependency. `"digital_echo"` is a documented future producer (Module 8/9) — accept the shape, don't build the producer.
- `severity` and its calibrated threshold are **not fixed in this document** — per the master doc, this is an explicit open calibration value (Ch.13). Ship as a named constant, default conservatively (favor `minor` until real data justifies tightening it), and never hardcode a specific number as if it were validated.
- `visibility_suspended` has no visible effect in this local phase (no recruiter-facing listing exists yet) — set the field correctly per the rule (`major` + `status: "unresolved"` → `true`) so the future recruiter module can consume it without a data-model change later.
- If `status` stays `open` with no `resolution_path` chosen, the disputed `Statement` remains unconfirmed (`0`, not negative) — same non-punitive rule as an unanswered Contextual Probe question (Module 4).

---

## 5. Functional Requirements

### US1 — Get a Trust Score reflecting the degree of confirmation of the profile

| ID | Requirement |
|---|---|
| FR1.1 | Trust Score is computed from exactly three MVP components in this phase: **Authenticity**, **Understanding**, **Consistency** — Ethics and Integrity are not computed at all (not even as 0/hidden placeholders that could be mistaken for "measured and found lacking"; they simply don't exist yet in the UI). |
| FR1.2 | **Authenticity** score is derived from Module 4's integrity signals already captured there: copy-paste-block events, Semantic Depth follow-up outcomes, and — only if the legal-gated flag is on — Keystroke Dynamics comparison against the candidate's own Raw Input baseline (never against a population norm). This module computes the score from those inputs; it does not re-capture them. |
| FR1.3 | **Understanding** score is derived from Module 4's `Answer.routing.understanding_signal` outputs across all answered probes — this is a direct, non-reinvented consumption of a signal Module 4 already defined. |
| FR1.4 | **Consistency** score is derived from the local Consistency checks (§5.1) plus any `ContradictionCase`/`AttributionFinding` resolutions — a profile with zero detected contradictions and all findings confirmed scores higher than one with open, unresolved cases. |
| FR1.5 | `overall_score` is computed from the three component scores using the independence-weighted logic in §4.2 — not a simple average, and not a fixed-weight sum presented as final; both the formula and its constants must be swappable for calibration (Ch.13). |
| FR1.6 | Recomputation happens **by event** (new Evidence added, new probe answered, dispute resolved) — implemented as recompute-on-read in this local phase, consistent with Modules 3–5's established convention, not a scheduled/batch job. |

**Acceptance criteria:** a candidate with confirmed Evidence and answered probes sees a single `overall_score` plus a visible per-component breakdown, which changes immediately (on next view) after any relevant action — never on a delay, never requiring a manual "recalculate."

---

### US2 — Understand which independent confirmations influenced Trust Score

| ID | Requirement |
|---|---|
| FR2.1 | Every component score must carry a factual `explanation_ru` (§4.1) — a checkable statement referencing specific evidence, never a vague verdict. Follow the master doc's own contrast exactly: not *"низкий балл за командную работу"*, but *"в логах Jira 0 упоминаний участия в Code Review коллег"* — the second is disputable with facts, the first only emotionally. Any explanation this module generates must be of the second kind. |
| FR2.2 | The candidate can drill from any component score down to the specific `contributing_evidence_ids` (§4.1) that produced it — this is the same "traceability to source" requirement Module 2 already established for individual competencies (Statement→Evidence), applied here one level up, at the Trust Score component level. |
| FR2.3 | Where the independence-weighting logic (§4.2) caused a new confirmation to add little or no score (e.g. a third self-reported restatement of the same fact, same `source_category`), this must be explained, not silently absorbed — e.g. *"Это подтверждение похоже на уже учтённое — для роста нужен независимый источник."* Silently ignoring a candidate's added evidence without explanation would violate the XAI rule as much as a bare low score would. |

**Acceptance criteria:** for any component score, the candidate can identify exactly which pieces of Evidence/probe answers counted toward it, and if something they added didn't move the score, they can find out why in the same view.

---

### US3 — See what additional actions would strengthen trust in specific parts of the profile

| ID | Requirement |
|---|---|
| FR3.1 | Alongside the score, the module surfaces a **"next best action"** per weak component/claim — following the master doc's exact pattern: *"Trust 63/100. Есть три неподтверждённых утверждения. Добавление проекта X или прохождение кейса Y даст независимое подтверждение компетенции Z."* Not a generic "improve your score" nudge — a specific, named action tied to a specific gap. |
| FR3.2 | This module does not invent a new gap-detection mechanism for this — it reuses Module 3's White Spot list (for Understanding/PROF-adjacent gaps) and its own open `ContradictionCase`/`AttributionFinding` records (for Consistency gaps) as the source of "what's weak," and routes the suggested action to the correct existing entry point (Module 2 evidence-adding, Module 4 probe, or this module's own dispute-resolution screen). |
| FR3.3 | Suggested actions must be prioritized (highest-impact first), not a flat unordered list — reuse Module 3's White Spot prioritization convention (FR3.2/3.3 of that module) rather than establishing a second ranking rule. |

**Acceptance criteria:** from the Trust Score view, the candidate can identify at least one concrete, specific action to take next for their weakest component, with a direct link into the module that actually lets them take it.

---

### US4 — Dispute a mistaken or incorrect statement affecting Trust Score

| ID | Requirement |
|---|---|
| FR4.1 | **Case 1 (Attribution/currency)**: for any `AttributionFinding`, the candidate can respond `confirmed` or `not_me_or_outdated` freely — no reason required, no score impact either way for the decline option, and a declined finding leaves **no visible trace** anywhere (stronger than a normal decline — see §4.3). |
| FR4.2 | **Case 2 (Contradiction between two already-owned facts)**: for any `ContradictionCase`, the candidate is offered exactly three resolution paths, and must be able to choose any one of them without justification beyond what each path itself requires: |
| FR4.2a | — **Delete artifact**: removes the source Evidence and cascades deletion of everything bound specifically to it (per Module 2's cascade convention); the disputed claim returns to unopposed status. This is a voluntary withdrawal by the candidate, not a system-imposed removal — does not violate the non-punitive rule. |
| FR4.2b | — **Explain**: candidate provides a free-text explanation, stored in profile history (same pattern as any other clarification, Module 2/4) — if the explanation resolves the contradiction (e.g. a mid-period promotion), both facts remain confirmed with the explained history attached, not one overwriting the other. |
| FR4.2c | — **Correct claim**: candidate directly edits the original claim down to what's actually supported (e.g. "director" → "acting director") — the most natural path for an honest overstatement; the candidate isn't disputing the finding, they're aligning their own claim with it. |
| FR4.3 | If none of the three paths is chosen, the same rule as an unanswered Contextual Probe question applies: the disputed fact remains unconfirmed (`0`, not negative), and the finding plus the non-response are visible via the standard XAI explanation pattern — not a verdict, the same transparency principle used everywhere else in the product. |
| FR4.4 | **Severity-graded visibility (§4.4 `severity`/`visibility_suspended`):** contradictions above the calibrated threshold temporarily suspend the profile from active search **under the disputed level** until resolved — this reuses the same suspension mechanism already established for post-verification recruiter complaints (a different module, same mechanism). Minor/stylistic discrepancies never trigger this. **This has no visible effect in the current local, no-recruiter-surface phase — implement the field correctly (§4.4) so the future recruiter module can consume it without rework, but there is nothing to demonstrate yet.** |
| FR4.5 | This module must not build a second, parallel implementation of "free decline, no reason, no penalty" for Case 1 — reuse Module 2's `DeclineRecord` non-punitive contract, extended with the "leaves no trace at all" property specific to attribution findings. |

**Acceptance criteria:** a candidate facing a Case 1 finding can decline it with one click and see it disappear entirely; a candidate facing a Case 2 contradiction can resolve it via any of the three paths (or leave it open) and see the correct, non-punitive consequence in each case.

### 5.1 Local Consistency check producers (this module's own contradiction source, no external dependency)

| ID | Requirement |
|---|---|
| FR-Cons.1 — Date overlap | Detect when two `Statement`-linked employment/project periods (from Module 1/2 candidate-provided data) overlap in a way inconsistent with both being full-time, unless the candidate has explicitly indicated part-time/parallel work. Produces a `ContradictionCase(check_type: "date_overlap")`. |
| FR-Cons.2 — Level mismatch | Detect when a candidate's claimed role/level (e.g. "director," "Senior") is described, in the candidate's own linked Evidence (e.g. a project description or Blind Witness answer), in terms suggesting materially different seniority (e.g. explicitly junior-scope responsibilities). Produces a `ContradictionCase(check_type: "level_mismatch")`. MVP heuristic only — this is not a validated NLP classifier, flag accordingly, same calibration-pending convention as elsewhere in this document. |
| FR-Cons.3 | Both checks run only against data the candidate themselves provided (Module 1/2) — this module performs **no external lookup**, consistent with "no passive/background data collection" (Ch.6/Principle 3) and with Digital Echo being explicitly out of scope here (§2.2). |

---

### US5 — Weak confirmation means "needs more verification," never an automatic penalty

| ID | Requirement |
|---|---|
| FR5.1 | **Hard constraint, structural not just presentational:** no code path in this module may ever decrease `overall_score` or any `component_score` as a consequence of a candidate's action. The only states are "confirmed to some degree" and "not yet confirmed" (`0`). There is no negative value anywhere in this data model. |
| FR5.2 | An answer that fails Semantic Depth even after follow-up, a skipped probe, a declined finding, or an unresolved `ContradictionCase` all resolve to the same outcome for their respective claim: unconfirmed, not penalized retroactively. |
| FR5.3 | Detected low-effort input (e.g. a copy-paste attempt blocked in Module 4) does not "score" the candidate negatively — the detector simply does not count that fragment as a confirmation. Absence of credit, not presence of a debit. |
| FR5.4 | This rule must be verifiable by code review, not just by reading the UI copy: no arithmetic operation in the score-computation path may subtract from a running total based on a negative event — only addition based on positive, independent confirmation. |
| FR5.5 | UI copy must never use the words "штраф"/"наказание"/"снижен" (or English equivalents: "penalty," "penalized," "lowered") in connection with a score change caused by unconfirmed/declined/failed input — reserve score-decrease language exclusively for legitimate cases like a resolved `ContradictionCase` correction (which isn't a penalty either — it's the score reflecting what's now actually confirmed, per FR4.2c). |

**Acceptance criteria:** across every flow in this module (skip, decline, fail Semantic Depth, leave a contradiction unresolved), `overall_score` either stays the same or increases — it is not possible to construct a sequence of candidate actions in this module that decreases it.

---

## 6. UI Flow

No dedicated Trust Score screens currently exist in `purpjob-wireframe-v3.jsx` beyond the bare number already shown in `evidenceMap`/`dashboard` (`"Trust Score: 65/100"`, `"Trust Score: 65"`). This module needs new UI, not just wiring into existing screens:

1. **Extend `evidenceMap`/`dashboard overview`:** the existing bare Trust Score number needs its component breakdown (US1) and top next-best-action (US3, reusing the existing `"Следующее лучшее действие"` block pattern already established in `dashboard`) attached — don't introduce a competing UI pattern for "what to do next," reuse the one Module 3 already established.
2. **New screen: Trust Score detail view** — per-component scores with `explanation_ru`, drill-down to `contributing_evidence_ids` (US2).
3. **New screen: Attribution finding** — `"Мы нашли X — это совпадает с вашим профилем?"` + confirm/decline, matching the existing pattern already drafted in the master doc for Digital Echo (reuse even though the producer differs in this phase).
4. **New screen: Contradiction resolution** — the three-path screen (delete/explain/correct), per FR4.2, styled as routine profile maintenance, not an accusation.

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication:** same single implicit local session as Modules 2–5.
- **Recompute-on-read:** consistent with Modules 3–5, given local-only data volumes — no event pipeline/cache needed yet.
- **Formula constants as named, swappable config:** §4.2's independence-weighting logic and §5.1's level-mismatch heuristic must both be implemented as clearly separable, named constants/config, not inline magic numbers — both are explicitly calibration-pending (Ch.13), and burying them in logic would make recalibration a code change instead of a config change.
- **No negative-value fields anywhere in the score data model** — enforce this at the schema level if practical (e.g. unsigned score types), not just by convention, given FR5.4's code-review requirement.

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| Digital Echo as a `ContradictionCase`/`AttributionFinding` producer | Separate module (8/9), needs external web data access this local phase doesn't have; this module accepts the event shape already. |
| Ethics, Integrity components | [V2]/[V3] respectively — Ethics needs on-platform history that doesn't exist yet; Integrity needs Ch.13 calibration before it's safe to expose. |
| Employer Trust | [V2], separate metric, not this module's concern at all. |
| Snapshot-on-response/offer + recruiter-facing diff versioning | Depends on an application/response flow not built in this phase; `version` field is prepared (§4.1) but unused. |
| "Актуализировать данные" refresh button | Depends on live OAuth source connections, [V2] per Module 2. |
| Exact independence-weighting formula and contradiction-severity threshold | Both explicitly open calibration values per Ch.13 — do not present current placeholder constants as final to stakeholders. |
| Level-mismatch detection quality (FR-Cons.2) | Hand-built heuristic for MVP, not a validated classifier — revisit once real candidate data exists. |

---

**H1 hypotheses this module should let you test (not guarantees):**
- H1 (Score comprehensibility): candidates shown the factual `explanation_ru` pattern (FR2.1) can correctly restate why their score is what it is, at a higher rate than a bare-number control — worth designing the UI so this is testable, not assumed to work because the copy "sounds explainable."
- H1 (Non-punitive framing effectiveness): candidates who hit a `not_started`/unresolved state don't disengage at a higher rate than those who don't — if they do, the "law of increasing returns, not penalty" framing isn't landing as intended regardless of what the copy says.
