# PurpJob — Module 3: PROF.Index
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-0]
**Phase:** Local prototype (no authentication layer, no persistent backend, single local candidate session)
**Depends on:** Module 1 (Profile core), Module 2 (One-Click Enrichment & Evidence) — PROF.Index is computed *from* Module 2's `Statement`/`Evidence` data, it does not collect evidence itself.
**Consumed by:** Module 5 (Trust Score — separate, independent axis, not built here), future Module 4 (Contextual Probe engine — feeds new competency signals into this module once it exists)

---

## 1. Purpose

PROF.Index turns the candidate's accumulated Evidence (Module 2) into a structured, measurable fit-to-role indicator — a set of scored competencies against a fixed reference profile, not a paraphrased resume. It answers "how well does this candidate's *proven* skill set match a specific role/level," not "is this a good specialist" in the abstract, and not "can this candidate be trusted" (that's Trust Score, out of scope here).

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| P1 — Evidence-Based Hiring | Every competency score is derived only from `Evidence`-backed `Statement`s (Module 2); nothing is scored from unverified resume text alone. |
| P2 — Automation / Logic over Memory | Score recalculates automatically as new Evidence arrives; candidate never re-declares what's already proven. |
| P3 (implicit, hard-skills-only design) | PROF.Index deliberately excludes soft skills — no material artifact trail exists for them, so they are structurally out of scope, not a future add-on (see §7). |
| P5 — Dynamic Trust | Index is a live snapshot, recalculated on each new Evidence event, not a one-time score. |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- PROF.Index computed against **one fixed reference profile**: segment **Backend/Fullstack (Python/Go)**, level **Middle or Senior** (candidate self-declares target level; both levels have distinct reference weights) (US1)
- Per-competency breakdown (Hard Skills + Complexity of Solved Tasks) with status (`not_started`/`limited`/`medium`/`strong`, reusing Module 2's status model) (US1, US2)
- Radar diagram data: candidate's actual competency levels overlaid on reference-profile requirements (US1)
- White Spot detection: reference-profile competencies with insufficient Evidence, surfaced as a prioritized, actionable list (US3)
- Self-Audit mode: candidate can build/view PROF.Index with the profile hidden from any external view (US4)
- Two visibility modes only: **visible** / **hidden** (a third mode, whitelist-based "for selected companies only," is explicitly [V2] — see §7)

### 2.2 Out of scope (explicitly deferred)
- Trust Score calculation and the PROF×Trust decision matrix (Module 5/6)
- Contextual Probe question generation engine (Module 4) — this module only defines the data contract for *receiving* a probe result as a new competency signal
- Skill Velocity (rate of closing the gap to reference profile over time) — [V2], requires 2–3 years of accumulated history
- Match Score against a specific job posting — derived metric, separate module, [V2]/MVP-limited per master doc (recruiter sees only overall PROF.Index on MVP)
- Auto-aggregated reference-profile generation from market job postings (two-step process: auto-aggregation + expert calibration) — this module consumes a reference profile as **static seed data**, it does not build the aggregation pipeline (that belongs to the vacancy-parsing module)
- Multi-segment/multi-level reference library beyond Backend/Fullstack Python/Go Middle+Senior
- "What if I targeted role Y" simulator — [V3]
- Authentication, cross-device persistence, multi-user storage

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values (`not_started`, `limited`, `medium`, `strong`, `visible`, `hidden`, competency canonical keys) | English, as specified in this document |
| All UI copy: labels, tooltips, White Spot explanations, radar diagram axis labels, Self-Audit onboarding copy, visibility-mode names | **Russian**, matching the register already used in `purpjob-wireframe-v3.jsx` and the master document. Reuse existing strings wherever a screen/state already exists there, e.g.: |

Reference strings already established in the product (reuse verbatim, do not re-translate):
- `"PROF.индекс · Backend-разработчик"` — index label pattern (role name inline)
- `"Ваша прозрачность для рынка — 65%"` — index framing copy used elsewhere in the doc; confirm with product before reusing verbatim in this exact module, tone must stay consistent either way
- `"Hard Skills — Medium"`, `"Сложность решенных задач — Limited"`, `"Professional Footprint — Not started"` — existing per-competency status display pattern from `evidenceMap`, this module must produce data in the same shape
- `"Подтверждено на основе Contextual Probe. Добавление независимого источника повысит статус до Strong"` — existing "why" explanation pattern (XAI requirement, see FR2.4)
- `"Настройте видимость и опубликуйте профиль"`, `"Полная видимость"`, `"Инкогнито"` — existing visibility-mode screen and full-visibility mode label

**Discrepancy flag (wireframe vs. spec):** `purpjob-wireframe-v3.jsx` currently shows **three** visibility options (`Полная видимость`, `Инкогнито`, `Только для избранных`). The master document fixes MVP at **two** modes only — full visibility and hidden — with the whitelist mode ("Только для избранных") tagged [V2]. This module's implementation must ship two modes; the third option should be removed from the visibility screen or shown disabled/"coming soon," not built as functional in this phase.

**Canonical competency keys:** per the Module 2 FRD convention already adopted, store each reference-profile competency with an English canonical key (for stable matching/versioning) plus a `name_ru` display field. Do not invent a second convention for this module.

---

## 4. Data Model

Local-first constraint, same as Module 2: flat local JSON per candidate session, no server DB in this phase. This module reads Module 2's `Statement[]`/`Evidence[]` and writes its own derived snapshot; it must never mutate Module 2 data directly.

### 4.1 `ReferenceProfile` (seed data, not user-generated)
```json
{
  "id": "ref_backend_fullstack_python_go_middle",
  "segment": "Backend/Fullstack (Python/Go)",
  "level": "Middle | Senior",
  "competencies": [
    {
      "competency_id": "rest_api_design",
      "name_ru": "Проектирование REST API",
      "category": "hard_skill | task_complexity",
      "weight": 0.15,
      "required_depth": "basic | working | deep"
    }
  ]
}
```
- Exactly **two** `ReferenceProfile` records ship with this MVP: Middle and Senior, same segment.
- This is static seed content curated by the founders/domain expert for this phase — no admin UI is required to build it in this module; it can be a checked-in JSON file.
- `weight` values across a profile's `competencies` should sum to 1.0 per `category`, or a single pooled 1.0 across all — pick one convention and document it in the seed file itself; do not leave this implicit in code.

### 4.2 `CompetencyResult` (derived, per candidate session)
```json
{
  "competency_id": "rest_api_design",
  "status": "not_started | limited | medium | strong",
  "statement_ids": ["stmt_001"],
  "evidence_count": 2,
  "score_contribution": 0.6
}
```
- `status` is copied/derived from the linked Module 2 `Statement.status` (see Module 2 FRD §3.4) for the `Statement`(s) mapped to this `competency_id`. If no `Statement` maps to this competency, status is `not_started` and it is a candidate White Spot.
- `score_contribution` = `status_score(status) × weight`, where `status_score` mapping is a **placeholder, calibration-pending value** (see §4.4), not a fixed guarantee of accuracy.

### 4.3 `PROFIndexSnapshot`
```json
{
  "segment": "Backend/Fullstack (Python/Go)",
  "level": "Middle",
  "overall_score": 58,
  "computed_at": "ISO8601",
  "components": [ "CompetencyResult[]" ],
  "white_spots": ["competency_id", "..."],
  "radar_points": [
    { "competency_id": "rest_api_design", "candidate_value": 0.6, "reference_value": 1.0 }
  ]
}
```
- `overall_score` is a 0–100 integer for display (matches existing UI pattern, e.g. `"PROF.индекс · Backend-разработчик" → 58`).
- Recomputed on every read in this local phase (cheap given local-only data volume) rather than cached — avoids stale-snapshot bugs before a real backend/event system exists.
- One snapshot exists **per declared level** the candidate is tracking (matches wireframe's `"Backend-разработчик (PROF 58) · Tech Lead (PROF 42)"` multi-role pattern) — this module must support 1–3 concurrent snapshots per candidate (existing UI cap: "максимум 3 роли всего" from Module 1/2 onboarding).

### 4.4 Status → score mapping (placeholder, testable hypothesis)
| Status | Score value |
|---|---|
| `not_started` | 0.0 |
| `limited` | 0.25 |
| `medium` | 0.6 |
| `strong` | 1.0 |

**This mapping is a placeholder for H1 calibration (master doc Ch.13, "Калибровка первого сегмента"), not a validated formula.** Ship it as a single named constant/config, not hardcoded inline, so it can be recalibrated without touching scoring logic.

### 4.5 `VisibilityState`
```json
{ "mode": "hidden | visible", "changed_at": "ISO8601" }
```
- Default for a newly created PROF.Index in this MVP: **hidden** (Self-Audit-first — matches the "candidate arrives without job-search intent" framing in FR4.1). Confirm with product before final default; document why in code comments either way.

---

## 5. Functional Requirements

### US1 — Structured PROF.Index instead of resume-as-text

| ID | Requirement |
|---|---|
| FR1.1 | Candidate declares one or more target (segment, level) pairs. MVP constraint: segment is fixed to Backend/Fullstack (Python/Go); level is Middle or Senior only — any other input is rejected/redirected with an explanatory message, not silently coerced. |
| FR1.2 | For each declared (segment, level), the system loads the matching `ReferenceProfile` and computes a `PROFIndexSnapshot` (§4.3) from the candidate's current Module 2 `Statement`/`Evidence` data. |
| FR1.3 | The candidate-facing view shows the `overall_score` as a percentage, per declared role, in the existing pattern (`PROF.индекс · <role> → NN`). |
| FR1.4 | The system renders a radar diagram: reference-profile requirement per competency vs. candidate's actual `score_contribution`, using `radar_points` (§4.3). This is the primary "not a resume, a set of measurable characteristics" surface for US1 — build it, don't substitute a table for it. |
| FR1.5 | Complexity of Solved Tasks is scored as its own `category` of competencies (§4.1), not folded into generic Hard Skills — driven by Module 2 `Evidence` of type `link`/`file` pointing to code/task-tracker artifacts. MVP heuristic: presence + non-trivial description length counts as `limited`→`medium`; do not simulate a deeper complexity-analysis model that doesn't exist yet — mark this heuristic explicitly as a placeholder pending Ch.13 calibration, same as §4.4. |
| FR1.6 | The module exposes a defined ingestion point for future Contextual Probe results (Module 4): a new competency discovered through a live-question answer, not originally claimed, must be able to create a new `Statement`→`CompetencyResult` mapping and feed `overall_score` without requiring a redesign of this data model. Do not build the probe itself here — only the contract. |

**Acceptance criteria:** candidate with ≥1 confirmed Evidence item (from Module 2) sees a numeric PROF.Index and a radar diagram reflecting it, for each declared role, recomputed automatically after any Module 2 change — no manual "recalculate" action required.

---

### US2 — Which competencies are strongly evidenced vs. weak

| ID | Requirement |
|---|---|
| FR2.1 | Every competency in the active `ReferenceProfile` is shown with its current `status` (`not_started`/`limited`/`medium`/`strong`), using the same four-tier language already established in Module 2's Evidence Map. |
| FR2.2 | Status is never shown as a bare label — every competency row must carry a one-line "why" explanation sourced from its linked `Statement`/`Evidence`, e.g. matching the existing pattern: *"Подтверждено на основе Contextual Probe. Добавление независимого источника повысит статус до Strong."* This is a hard XAI requirement (Ch.9), not optional polish. |
| FR2.3 | Competencies are groupable/filterable by status in the UI (e.g. "show only Limited and below") so the candidate can scan strong vs. weak areas at a glance, not just read a flat list. |
| FR2.4 | `strong` status requires evidence from ≥2 distinct source categories (inherits Module 2's §3.4 rule) — this module must not invent a separate, looser threshold; reuse the same computation, don't duplicate logic. |

**Acceptance criteria:** for any competency in the reference profile, the candidate can see its status and the specific reason for that status without leaving the PROF.Index view.

---

### US3 — White Spots: which competencies are worth confirming further

| ID | Requirement |
|---|---|
| FR3.1 | A competency is a **White Spot** if its `status` is `not_started` or `limited` (i.e., insufficient independent confirmation per the reference profile's requirement). |
| FR3.2 | White Spots are surfaced as a **prioritized, actionable list**, not just a filtered table — ordered by `weight` (highest-impact gaps first), each with a direct call-to-action back into Module 2 (add a link/file, describe a case, or — once Module 4 exists — answer a targeted question). |
| FR3.3 | The system must never present all reference-profile competencies as equally urgent — the point of White Spots is "what's worth confirming *next*," not a full audit checklist. Cap the default view (e.g. top 3–5) with an option to expand. |
| FR3.4 | White Spot list must be reactive: closing a gap in Module 2 (new Evidence pushes status above `limited`) removes that competency from the White Spot list on next view without any extra step. |
| FR3.5 | This module does **not** generate new questions to close a White Spot (that's Module 4/Contextual Probe) — its job is detection and surfacing only. The CTA in FR3.2 may link to a "coming soon" state for the probe-based path until Module 4 ships, same pattern as Module 2's Mirror Task stub. |

**Acceptance criteria:** candidate can open a single view listing their highest-priority unconfirmed competencies, each with one concrete next action, and see the list shrink as they act on it.

---

### US4 — Self-Audit: PROF.Index for self-development, not just job search

| ID | Requirement |
|---|---|
| FR4.1 | Candidate can build and view a full PROF.Index while `VisibilityState.mode = "hidden"` — nothing about entering Self-Audit requires any job-search intent, application, or recruiter-facing action. |
| FR4.2 | Hidden mode must be functionally complete: every US1–US3 feature (index, radar, statuses, White Spots) works identically whether `mode` is `hidden` or `visible`. Self-Audit is not a stripped-down preview — it is the full module with output hidden from anyone but the candidate. |
| FR4.3 | The system supports exactly two `VisibilityState.mode` values in this MVP: `hidden` and `visible`. No third mode is implemented (see Localization §3 discrepancy flag) — a whitelist/"selected companies only" mode is [V2] and out of scope. |
| FR4.4 | Switching from `hidden` to `visible` is an explicit, candidate-initiated action (not automatic on reaching some score threshold) — matches the non-punitive, candidate-owned-data principle: the platform never publishes on the candidate's behalf. |
| FR4.5 | Since this phase has no recruiter-facing surface at all, `visible` mode has no external effect yet — implement the state and its toggle now so Module 6's recruiter view has a stable contract to read from later, but do not build any recruiter-side rendering in this module. |

**Acceptance criteria:** a candidate can go through the entire PROF.Index experience (build index, see statuses, close White Spots) with `mode: "hidden"` set from the start, with zero UI friction implying they must "publish" to get value from the module.

---

## 6. UI Flow (maps to existing wireframe screens)

1. `firstResult` → partially satisfies US1 (per-role PROF.Index number already shown: `"PROF.индекс · Backend-разработчик → 58"`) — needs the radar diagram (FR1.4) added, currently text-only.
2. `evidenceMap` → largely satisfies US2/US3 already: per-competency status + "why" pattern (`"Hard Skills — Medium"` + explanation) matches FR2.1–FR2.2 almost directly; the "2 из 4 компонентов профиля еще нуждаются в независимом подтверждении" line is the seed of the White Spot summary (FR3.2) but needs to become a dedicated prioritized list, not just a footer sentence.
3. `dashboard` (`overview` tab) → the "Следующее лучшее действие" ("Next best action") block is the closest existing analog to a single top-priority White Spot (FR3.2/FR3.3) — reuse this pattern, don't build a parallel one.
4. `visibilitySettings` → needs correction per the discrepancy flag in §3: reduce to two `SelectCard` options for this module's scope, not three.
5. **New screen needed:** a dedicated radar-diagram view is not yet in the wireframe — closest entry point is `firstResult`/`fullProfile`, either can host it.
6. `fullProfile` → already frames "this is what only you see, regardless of visibility settings" — natural home for the Self-Audit full view (FR4.2).

---

## 7. Why No Soft Skills (carried over from master doc, binding constraint)

PROF.Index measures **Hard Skills only**, by deliberate architectural decision, not a gap to fill later:
- Hard skills leave a material trail (commit, ticket, document); most soft skills don't.
- Scenario-based questions for soft skills ("how do you usually resolve conflict") have no anchor to verify against — they'd reintroduce "resume inflation" under a new name, the exact problem PROF.Index exists to solve.
- Evaluating "is this person a good leader" is a subjective judgment, not a checkable fact — same risk class as the already-blocked Culture Fit feature (legal review required, not built).
- Verifiable *facts* adjacent to soft skills (e.g., team size actually managed) belong to Trust Score's Understanding component (Module 5/6) as a factual check, not to PROF.Index as a skill score.

**Do not add a soft-skill dimension to this module under any framing** (e.g., "communication score," "leadership index") without an explicit founder decision reversing this — it's a closed backlog item (#28), not an oversight.

---

## 8. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication:** same single implicit local session model as Module 2 — this module reads/writes to the same local JSON store, under its own top-level keys (`reference_profiles`, `prof_index_snapshots`, `visibility_state`), not mixed into Module 2's `Statement`/`Evidence` arrays.
- **Reference profile as static seed:** ship the two `ReferenceProfile` JSON records (Middle, Senior) as version-controlled seed files, not a database migration — no admin UI to edit them in this phase.
- **Recompute-on-read:** given local-only data volumes, recompute `PROFIndexSnapshot` on each view rather than maintaining a cache/event pipeline — simpler and avoids stale-score bugs before a real backend exists.
- **No cross-session persistence guarantees beyond what Module 2 already provides** — this module inherits Module 2's local storage lifetime, doesn't need its own.

---

## 9. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| Reference profile auto-aggregation from market vacancies | Belongs to the vacancy-parsing module (Ch.3/11/20); this module only consumes the output as static seed data. |
| Contextual Probe engine | Module 4 — this module only defines the ingestion contract (FR1.6), doesn't generate questions. |
| Skill Velocity | [V2] — needs 2–3 years of accumulated commit/project history, not available at MVP launch. |
| Match Score vs. a specific vacancy | Separate derived metric; MVP recruiter view (out of scope here) shows only overall PROF.Index. |
| Status→score constants (§4.4) and task-complexity heuristic (FR1.5) | Explicitly flagged as calibration-pending per master doc Ch.13 — do not present these numbers to stakeholders as validated, only as the current working hypothesis. |
| Default visibility mode on profile creation (§4.5) | Recommended `hidden`-by-default in this draft; confirm with product before locking it in. |
| Third visibility mode ("Только для избранных") | [V2] per master doc; wireframe currently shows it as if MVP — needs correcting, see §3. |

---

**H1 hypotheses this module should let you test (not guarantees):**
- Candidates who see a radar diagram + explicit White Spot list take at least one gap-closing action (back in Module 2) more often than candidates shown only a flat competency list (informal, not a formal experiment in this phase — but design the UI so this comparison is possible later).
- Self-Audit entry (hidden-by-default) does not suppress engagement with White Spots relative to visible-mode entry — i.e., hiding the profile from recruiters doesn't reduce the candidate's own motivation to strengthen it.
