# PurpJob — Module 8: Cumulative Profile & Logic over Memory
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-0]
**Phase:** Local prototype (no authentication layer, no persistent backend, single local candidate session)
**Depends on:** Module 2 (`Statement`/`Evidence`), Module 3 (`PROFIndexSnapshot`, multi-role support), Module 4 (White Spot targeting, non-re-ask rule), Module 6 (`TrustScoreSnapshot`), Module 7 (history/logging pattern, reused not duplicated)
**This module owns no new candidate-facing data collection** — it owns the architectural guarantees and the growth-history surface that make previously built modules behave as a genuinely cumulative asset rather than a per-session tool.

---

## 1. Purpose

**This is the module that makes PurpJob structurally different from a take-home test.** A test's result is discarded the moment the hiring loop closes. Here, the result of a verification is meant to become a permanent asset of the candidate — reusable across every future opportunity, never re-demanded once proven. Per the master document, this isn't a nice-to-have UX polish; it's directly **H1b (Compounding)**, one of the four core, independently-falsifiable MVP hypotheses: will a candidate actually invest effort in building this asset repeatedly, for value that arrives later, when LinkedIn/GitHub/a portfolio already exist and cost nothing extra to maintain.

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| Logic over Memory (Principle 4 of 5) | Direct implementation: a candidate is never asked again for something already confirmed, regardless of how much time passed or how many unrelated roles they've since declared. |
| P5 — Dynamic Trust | The score changes as new evidence arrives, but the underlying confirmed facts themselves are never re-litigated from scratch. |
| P1 — Evidence-Based Hiring | Reuse is legitimate specifically because it's evidence-backed, not because the candidate simply says "trust me, I already proved this once." |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- **Persistence guarantee**: no code path anywhere in the system may delete or archive `Statement`/`Evidence`/`TrustScoreSnapshot` data as a side effect of a job-search episode ending (US1)
- **Global competency confirmation**: a `Statement`'s confirmed status is a property of the *candidate*, not of any single declared role/`PROFIndexSnapshot` — it must be reused identically across every role that references the same `competency_id` (US2)
- **Cross-role, cross-time non-re-ask enforcement**: Module 4's existing "never re-probe `strong`" rule (established there for a single session/role) is extended here into an explicit, testable guarantee across time and across multiple declared roles (US3)
- **Profile Growth History**: an append-only, candidate-facing timeline of how the profile strengthened over time — distinct from Module 7's dispute-audit log, which exists for accountability, not motivation (US4)
- **Competency freshness/market-relevance weighting** (Backlog #18): a time-based, non-destructive weight applied at aggregation time in Module 3's PROF.Index calculation — see §0 discrepancy flag below, this needs an explicit reconciliation with Module 6's absolute non-punitive rule before it's built as specified
- **Priority return trigger for MVP-0**: "unclosed White Spot" reminder (per the master doc's own prioritization — only one trigger is tested at MVP-0 to keep the H1b signal clean)
- **Secondary return trigger for MVP-0**: competency freshness/staleness countdown notification

### 2.2 Out of scope (explicitly deferred)
- "New matching vacancy" and "recruiter interest" return triggers — both explicitly [MVP-1] per the master doc (depend on Telegram vacancy parsing and a recruiter-facing surface, neither exists in this phase)
- Vacancy-Specific Probe and its cross-vacancy reuse pattern (e.g. an AI-leverage competency confirmed for a CMO role reused for Head of Growth six months later) — explicitly [V2], depends on a base Contextual Probe already working at scale and an accumulated verified-profile base; this module's global-confirmation principle (US2) is the same underlying idea, just not extended to vacancy-specific (non-reference-profile) competencies yet
- Any application/response ("отклик") flow itself, or a `SearchContext`/opportunity entity with real business logic — no such flow exists yet; this module only guarantees that *whenever* one is built later, it must not be able to delete accumulated data (§4.1 documents a minimal forward-compatible marker only)
- Resume export / public widget rendering (PDF export, LinkedIn/Telegram/hh.ru widget) — Module 3/15 concern, this module only guarantees the underlying data it would read from is live and accumulated, not a frozen snapshot from account creation

---

## ⚠️ 0. Discrepancy flag — competency freshness decay vs. the absolute non-punitive rule

The master document (Ch.4/Backlog #18) specifies a return trigger: after a fixed countdown (starting value 3 days, explicitly uncalibrated) without refreshing a competency, its **weight is lowered** in the profile if the candidate doesn't act. Read literally, "we will lower the weight of competency X" is a decrease in something the candidate can see, caused by *time passing without action* rather than by an action itself.

Module 6's Trust Score FRD established an **absolute** rule (FR5.1 there): *"no code path in this module may ever decrease `overall_score` or any `component_score` as a consequence of a candidate's action"* — framed as unconditional, not scoped to "action-caused decreases only."

**These aren't necessarily contradictory, but they need an explicit reconciliation before this ships, and I'm making the distinction I'm building to explicit rather than silently picking one reading:**

- Freshness decay, per the master doc's own framing, is **not** a Trust Score mechanic — it's described purely as a PROF.Index / market-relevance concept ("рынок меняется"), never mentioned alongside Authenticity/Understanding/Consistency in Ch.6.
- **This FRD implements freshness decay as a multiplier applied only at PROF.Index aggregation time (Module 3's `overall_score` computation), never touching Trust Score, and never mutating or deleting the underlying `Statement.status`/`Evidence` themselves.** The confirmed fact stays confirmed and fully visible forever (satisfies US1/US4); only how much it currently counts toward *role-fit* can drift with market relevance, and only downward as a display weight, recoverable with one click (the "Актуализировать" pattern already touched on in Module 6 §2.2).
- **Confirm this reading before building it.** If the intent was actually for freshness decay to also touch Trust Score, that would need Module 6's FR5.1 to be explicitly amended (removing "absolute"), which is a bigger, more consequential change than this module alone should make unilaterally.

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values (`evidence_added`, `competency_status_upgraded`, `role_added`, `fresh`, `decaying`, `stale`) | English |
| All UI copy: growth-history entries, return-trigger notifications | **Russian**, matching the register already established across Modules 2–7 |

Reuse existing drafted copy verbatim:
- White Spot reminder trigger: *"У вас есть неподтверждённая компетенция — один вопрос закроет её."*
- Freshness countdown trigger: *"Рынок меняется — через 3 дня мы понизим вес компетенции X в вашем профиле, если данные не обновятся. Зайдите и обновите, чтобы остаться актуальным."*
- FAQ entries already drafted and directly relevant to this module (reuse, don't rewrite): *"Могу ли я вернуться и дополнить профиль позже?"*, *"Могу ли я указать несколько ролей и зачем это нужно?"*

New copy needed (same factual, non-alarming register): growth-history entry lines, e.g. *"12 марта: подтверждена компетенция «Проектирование REST API» — добавлен независимый источник."* — model these directly on the existing Evidence Map "why" pattern, just past-tense and timeline-framed instead of present-tense status.

---

## 4. Data Model

Local-first constraint, consistent with Modules 2–7: flat local JSON per candidate session. This module mostly *reads* other modules' data to enforce guarantees and build the timeline; it writes only `ProfileGrowthEvent[]`, `CompetencyFreshness[]`, and `ReturnTrigger[]`.

### 4.1 `SearchContext` (minimal forward-compatible marker only — see §2.2)
```json
{
  "id": "sctx_001",
  "label": "string",
  "started_at": "ISO8601",
  "closed_at": "ISO8601 | null"
}
```
- This entity exists in this phase **only** to prove the persistence guarantee is testable: any `Evidence`/`Statement`/probe `Answer` may optionally reference a `search_context_id` for provenance, but closing a `SearchContext` (`closed_at` set) must have **zero effect** on any referenced data — no cascade, no archival, no visibility change. If no real apply-flow exists to create these yet, this entity can remain entirely synthetic/test-only in this phase.

### 4.2 `ProfileGrowthEvent` (US4, append-only)
```json
{
  "id": "pge_001",
  "event_type": "evidence_added | competency_status_upgraded | trust_component_increased | role_added | dispute_resolved_in_favor | competency_reused_across_role",
  "subject_ref": "stmt_001 | ev_003 | rest_api_design",
  "description_ru": "Подтверждена компетенция «Проектирование REST API» — добавлен независимый источник.",
  "occurred_at": "ISO8601"
}
```
- **Append-only, same hard constraint as Module 7's `DisputeHistoryEntry`** — no update/delete code path. This is a distinct log from Module 7's: that one exists for accountability (what a moderator changed and why), this one exists for candidate motivation and the literal proof of "your profile got stronger" (US4). Do not merge them into one log with mixed purposes — the audiences and tones differ.
- `competency_reused_across_role` is the specific event type that makes US2 visible to the candidate — logged whenever a newly-declared role's `PROFIndexSnapshot` recompute finds an already-`medium`/`strong` `Statement` satisfying one of its reference-profile competencies without any new Evidence being added for that role specifically.

### 4.3 `CompetencyFreshness` (Backlog #18, PROF.Index-only per §0)
```json
{
  "competency_id": "rest_api_design",
  "last_confirmed_at": "ISO8601",
  "market_weight_multiplier": 1.0,
  "decay_countdown_started_at": "ISO8601 | null",
  "status": "fresh | decaying | stale"
}
```
- `market_weight_multiplier` is applied **only** when Module 3 computes `overall_score`/`radar_points` — it must never be read by Module 6's Trust Score computation (§0).
- Countdown length (starting value 3 days per the master doc) is explicitly uncalibrated — ship as a named, swappable constant, same convention as every other calibration-pending value in this project (Modules 3/4/6's placeholder formulas).
- One click on the "Актуализировать" action (wherever it's surfaced) resets `market_weight_multiplier` to `1.0` and clears the countdown — never requires re-proving the underlying competency from scratch, consistent with the whole point of this module.

### 4.4 `ReturnTrigger`
```json
{
  "id": "rt_001",
  "trigger_type": "white_spot_reminder | competency_decay_warning",
  "related_ref": "rest_api_design",
  "status": "pending | sent | acted_upon | dismissed",
  "created_at": "ISO8601"
}
```
- Only these two `trigger_type` values are built in this phase (§2.2) — `new_matching_vacancy` and `recruiter_interest` are documented as future values, not implemented.
- **The key metric this data model must support is `acted_upon`, not `sent`** — per the master doc's own explicit correction: opening a notification is not evidence of Compounding value; taking a real action after returning (closing the White Spot, refreshing a competency) is. Do not conflate "trigger fired" with "trigger worked" anywhere in this schema or in any dashboard built on top of it.

---

## 5. Functional Requirements

### US1 — Confirmed experience persists after a specific job search ends

| ID | Requirement |
|---|---|
| FR1.1 | No code path in Modules 2, 3, 4, 6, or 7 may delete, archive, or hide `Statement`/`Evidence`/`TrustScoreSnapshot` records as a side effect of a `SearchContext` closing (§4.1) — this is a **constraint on all prior modules**, verified here, not new storage logic of its own. |
| FR1.2 | If/when a real application/response flow is built later (out of scope here), it must reference a `search_context_id` for provenance only — it must never gain the ability to cascade-delete or downgrade anything through that reference. This FRD fixes that constraint now so the future module isn't designed to violate it by omission. |
| FR1.3 | Any future export/reuse of the profile (PDF resume, public widget — Module 3/15) must read the **live, currently accumulated** `Statement`/`Evidence`/`TrustScoreSnapshot` state at the moment of export, never a copy frozen from an earlier point (except where Module 6's `TrustScoreSnapshot.version`/future snapshot-on-response mechanism explicitly calls for a frozen hiring-context snapshot — that's a different, deliberate freeze, not data loss). |

**Acceptance criteria:** simulate closing a `SearchContext` (or simply the passage of "time"/session end in this local prototype) and confirm every previously confirmed `Statement`/`Evidence`/Trust component is still fully present, visible, and unchanged afterward.

---

### US2 — A passed verification can be reused if relevant to another vacancy/role

| ID | Requirement |
|---|---|
| FR2.1 | `Statement.status` (Module 2/3) is a property of the candidate, keyed by `competency_id` — it is **not** duplicated or re-scoped per `PROFIndexSnapshot`/declared role. When a candidate declares a new role (up to the existing cap of 3 concurrent roles, Module 3), that role's snapshot must read the *same* global `Statement` records for any competency its reference profile shares with an already-declared role. |
| FR2.2 | Adding a new declared role must **not** trigger fresh Contextual Probe questions (Module 4) for any `competency_id` already at `medium`/`strong` from prior confirmation — only genuinely new White Spots specific to the new role's reference profile may generate new questions. |
| FR2.3 | **Open edge case, flag rather than silently assume:** reference profiles can specify different `required_depth` (Module 3 §4.1) for the same `competency_id` across roles/levels (e.g. Middle vs. Senior). Whether an existing `medium` confirmation satisfies a role requiring `deep` is not resolved by this document — until Ch.13 calibration defines a depth-comparison rule, the safe default is: **carry the status over as-is** (no forced re-probe), and let the role-specific `PROFIndexSnapshot`'s own `weight`/display reflect any gap qualitatively, rather than silently blocking reuse or silently pretending depth requirements don't exist. |
| FR2.4 | Log a `ProfileGrowthEvent(event_type: "competency_reused_across_role")` (§4.2) whenever FR2.1 actually carries a confirmation over into a newly declared role without new evidence — this is the concrete, demonstrable proof of the reuse principle, not just an internal implementation detail. |
| FR2.5 | This module does not build Vacancy-Specific Probe reuse (§2.2, [V2]) — but any future implementation of it must follow the same FR2.1 pattern (global confirmation, not per-vacancy silos) rather than introducing a second, incompatible reuse mechanism. |

**Acceptance criteria:** declaring a second role that shares a competency already `medium`/`strong` under the first role immediately reflects that status in the new role's snapshot, with zero new probe questions generated for that competency and a visible growth-history entry recording the reuse.

---

### US3 — Get new questions only where existing evidence is insufficient

| ID | Requirement |
|---|---|
| FR3.1 | This requirement is Module 4's FR1.1/FR1.4 (never re-probe `strong`, never re-ask across sessions), **extended here to an explicit, testable guarantee across multiple declared roles and across arbitrary elapsed time** — not a new mechanism, a stronger, more explicit version of an existing one. |
| FR3.2 | A regression check this module is responsible for defining (even if Module 4 is what executes it): adding Role B must produce **zero** new `pending` `Question`s for any `competency_id` already `medium`/`strong` under Role A, regardless of how much time has passed since Role A's confirmation. |
| FR3.3 | Returning to the platform after any gap (a day, a month) must never reset or re-trigger confirmation for anything already proven — the only new questions a returning candidate ever sees are for competencies still genuinely unconfirmed, or newly relevant due to a newly declared role (FR2.1–2.2), or a freshness-decay-triggered voluntary refresh (§4.3) — never a blanket "let's re-verify everything since it's been a while." |

**Acceptance criteria:** across a simulated multi-session, multi-role test sequence, no `Question` is ever generated for a `competency_id` whose current `Statement.status` is already `medium`/`strong`.

---

### US4 — See the history of how the profile strengthened over time

| ID | Requirement |
|---|---|
| FR4.1 | A dedicated, candidate-facing **Growth History** view renders `ProfileGrowthEvent` (§4.2) as a chronological, human-readable timeline — distinct in purpose, tone, and location from Module 7's moderation/dispute history (that one is for accountability when something was disputed; this one is for showing the candidate their own accumulated progress, present even for a profile that's never had a single dispute). |
| FR4.2 | Every meaningful strengthening action anywhere in the product must produce a `ProfileGrowthEvent`: new confirmed Evidence, a competency status upgrade (e.g. `limited`→`medium`), a Trust Score component increase, a new declared role, a dispute resolved in the candidate's favor (Module 7), and cross-role competency reuse (FR2.4). This module doesn't re-detect these itself where avoidable — it should be a thin listener/adapter on events already happening in Modules 2/3/6/7, not a duplicate computation. |
| FR4.3 | The timeline must be genuinely readable as *growth*, not a raw event dump — group by time period (e.g. by month) and lead with the outcome (*"подтверждена компетенция X"*), not the mechanism (*"добавлена запись Evidence типа link"*) — the candidate-facing framing matters here as much as the data completeness. |
| FR4.4 | This view is available in both visibility modes (Module 3's `visible`/`hidden`) — it's part of Self-Audit's full-feature-parity guarantee (Module 3 FR4.2): a candidate in `hidden` mode sees their full growth history exactly as a `visible`-mode candidate would. |

**Acceptance criteria:** after a sequence of profile-strengthening actions across at least two sessions, the candidate can open one view and see a readable, chronological account of what got stronger and when, without cross-referencing multiple modules' own internal screens.

---

### 5.5 Competency freshness / return triggers (supporting mechanism for US1–US4, per §0's reconciliation)

| ID | Requirement |
|---|---|
| FR5.1 | Implement exactly two `ReturnTrigger` types in this phase: `white_spot_reminder` (priority — the master doc explicitly designates this the *only* trigger meaningfully tested at MVP-0) and `competency_decay_warning` (secondary). Do not build `new_matching_vacancy` or `recruiter_interest` — both are [MVP-1], with dependencies (Telegram parsing as an automated trigger, a recruiter surface) that don't exist here. |
| FR5.2 | `white_spot_reminder` fires against any open White Spot from Module 3 that has remained unconfirmed for a calibratable period (starting value not fixed here — same open-calibration convention as elsewhere) — content reuses the exact copy already established (§3). |
| FR5.3 | `competency_decay_warning` fires per §4.3's countdown, applies only to PROF.Index weighting (§0), and always offers the one-click "Актуализировать" resolution rather than demanding the candidate re-prove anything. |
| FR5.4 | **The only metric this module records as meaningful for either trigger is `acted_upon`** (§4.4) — a `sent`-only trigger with no follow-up action is not logged anywhere as a success signal. This directly operationalizes the master doc's explicit correction: opening a notification proves nothing about Compounding value; a real action afterward does. |

---

## 6. UI Flow

Largely new surfaces — no equivalent exists yet in `purpjob-wireframe-v3.jsx`:

1. **New screen: Growth History** — the timeline view (FR4.1–4.3), reachable from the main profile/dashboard navigation alongside PROF.Index and Trust Score, not buried.
2. **Extend `dashboard`:** the existing `"Следующее лучшее действие"` block (already reused across Modules 3/6) is the natural home for surfacing an active `ReturnTrigger`'s prompt (white spot reminder or decay warning) — don't introduce a third parallel "what to do next" pattern.
3. **Multi-role declaration screen (extends existing onboarding flow):** must visibly reflect FR2.1/2.4 — when a shared competency carries over into a newly declared role, show this explicitly (e.g. *"Уже подтверждено для роли Backend-разработчик — переносим без дополнительных вопросов"*) rather than silently recomputing in the background, since this visible moment is itself part of what makes the reuse principle real to the candidate, not just technically true.
4. **"Актуализировать" action:** surfaced wherever a `decaying`/`stale` `CompetencyFreshness` status is shown (Evidence Map, PROF.Index detail) — one click, resets weight, no re-proof required (§4.3).

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication:** same single implicit local session as Modules 2–7.
- **Append-only enforcement for `ProfileGrowthEvent`:** same code-level constraint already established for Module 7's `DisputeHistoryEntry` — no update/delete path, ever.
- **Adapter-first implementation:** this module should be built as a thin listener/aggregator over events already produced by Modules 2/3/4/6/7, not a parallel computation engine — the actual scoring/status logic lives in those modules; this module's job is guaranteeing persistence, reuse, and visibility of what they already produce.
- **Freshness weight isolation:** enforce at the code level that `CompetencyFreshness.market_weight_multiplier` is read only by Module 3's aggregation path — a lint rule or code-review checklist item, given how easy it would be to accidentally wire it into Module 6 and silently violate §0's reconciliation.

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| **§0 reconciliation (freshness decay vs. absolute non-punitive rule)** | Needs an explicit founder confirmation that decay is PROF.Index-only, never Trust Score — this FRD proceeds on that reading but flags it rather than assuming silently. |
| Required-depth comparison across roles (FR2.3) | Genuinely unresolved in the source material — needs Ch.13 calibration input, not a documentation gap on this FRD's part. |
| `new_matching_vacancy` / `recruiter_interest` triggers | [MVP-1] — depend on Telegram parsing as an automated trigger and a recruiter surface, neither built yet. |
| Vacancy-Specific Probe cross-vacancy reuse | [V2] — depends on a mature base Contextual Probe and an accumulated verified-profile base. |
| Countdown length for freshness decay (starting value "3 days") | Explicitly uncalibrated in the source document — ship as a named constant, not a validated figure. |
| Real `SearchContext`/application-flow business logic | No apply-flow module exists yet; §4.1 is a minimal forward-compatible marker only. |

---

**H1b hypothesis this module exists specifically to let you test (not a guarantee):**
- Candidates who receive a `white_spot_reminder` return-trigger take a real action afterward (close the White Spot, add evidence) at a rate meaningfully above zero — and specifically, `acted_upon` divided by `sent` is the number that matters, not open/click-through rate. If this ratio is low, per the master doc's own framing, that's not "people forgot" — it's "people tried this once and didn't see enough value to come back for," a materially more serious signal that should change the roadmap, not just the notification copy.
