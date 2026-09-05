# PurpJob — Module 11: Candidate Retention Loop
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-0/MVP-1 boundary — see §0]
**Phase:** Local prototype (no authentication layer, no persistent backend, single local candidate session)
**Depends on:** Module 3 (`PROFIndexSnapshot`), Module 4 (existing Contextual Probe path), Module 7 (canonical `Explanation`), Module 8 (`ReturnTrigger`, `ProfileGrowthEvent`, global competency confirmation), Module 10 (`Vacancy`, `MatchResult`)
**This module builds no new scoring/matching logic of its own** — it's the closed loop that connects Module 10's Match mechanism to Module 8's return-trigger/growth-history mechanism, turning two already-built pieces into one retention flow.

---

## ⚠️ 0. Scope note — this module completes items two prior FRDs deliberately deferred

This isn't a fresh discrepancy between conflicting documents (like Modules 5/9's flags) — it's the planned graduation of specific items I explicitly stubbed out earlier in this same FRD series, and I want that traceable rather than silently resolved:

| Deferred in | Item | Status here |
|---|---|---|
| Module 8, §2.2 | `new_matching_vacancy` return trigger, tagged [MVP-1] because it needs live vacancy parsing as a proactive signal | **Built here**, but against a *simulated* local arrival mechanism (§4.3), not the live Telegram/career-page pipeline — that pipeline itself is still out of scope, consistent with Module 10 §2.2 |
| Module 10, §2.2 | Automatic push notification for a new matching vacancy — Module 10 was explicitly pull-based browsing only | **Built here** as the push half of the same feed Module 10 already renders |
| Module 8, §2.2 | `recruiter_interest` return trigger | **Still deferred** — genuinely needs a recruiter-side/auth system that doesn't exist anywhere in this module sequence yet; not built here either |

**Practical consequence:** this module doesn't need a live parsing pipeline to be fully demoable — it needs a way to simulate "a new vacancy just appeared" against the same static seed dataset Module 10 already uses (§4.3). When the real pipeline is eventually built, it becomes a second producer of the same event shape this module already consumes — same pattern already used repeatedly in this series (Digital Echo/local-consistency-checks in Module 6, anomaly-flag producers in Module 7).

---

## 1. Purpose

**Per the master document, retention/compounding (H1b) is the single most important, least certain hypothesis in the entire MVP — more uncertain than whether Trust Score can be computed at all.** This module is the concrete mechanism that either proves or disproves it: does a candidate actually come back and invest more effort in the profile because a specific, real opportunity makes that effort worthwhile *right now* — turning the profile from a one-time questionnaire into a compounding asset, as the source spec puts it directly.

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| Logic over Memory / Dynamic Trust | Returning to close a gap for one opportunity never means starting over — it means finishing exactly what's still open (US3). |
| XAI (cross-cutting) | A relevance claim ("this vacancy matters to you") is held to the same factual-explanation standard as every other conclusion in the product (US2). |
| H1b — Compounding (Ch.15, the actual hypothesis this module tests) | Every new confirmation must visibly increase the profile's value for opportunities beyond the one that triggered the return (US4) — this is the literal, falsifiable claim under test, not just marketing language. |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- Detection of a newly-arrived, sufficiently-relevant `Vacancy` against the candidate's current `PROFIndexSnapshot`, simulated locally against the seed dataset (US1, §0)
- A factual, Module-7-style `Explanation` for *why* a given vacancy triggered a notification — never a bare "we found something for you" (US2)
- A **focused return flow**: clicking a trigger lands the candidate directly on that vacancy's specific uncovered requirements and their routed recommendations (Module 10's existing mechanism), not a generic dashboard (US3)
- **Cross-vacancy compounding**: closing a gap must recompute `MatchResult` for every vacancy currently in the candidate's feed/history, not only the one that triggered the return, and this must be visibly logged (US4)
- In-app notification surfacing only (no real push/email/SMS channel — see §7)

### 2.2 Out of scope (explicitly deferred)
- The live vacancy-parsing pipeline itself — unchanged from Module 10 §2.2, still infra/ops work
- `recruiter_interest` return trigger — needs a recruiter-side/auth system not present anywhere in this series (§0)
- Real push notification delivery (browser push, email, SMS) — this phase surfaces triggers only within the local app session (§7); an actual delivery channel is a separate, later integration
- Vacancy-Specific Probe (new question generation per vacancy) — still [V2] per Module 10 §2.2, unchanged here; the focused return flow (US3) routes only to Module 2/4's existing mechanisms, exactly as Module 10 already established

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values | English |
| All UI copy: notification text, relevance explanations, return-flow framing | **Russian**, matching the register already established across Modules 2–10 |

Reuse existing drafted copy verbatim, do not re-derive:
- Notification pattern (Module 8 §3, already established): *"Нашли вакансию под ваш профиль, соответствие 62% - добавьте кейс X, чтобы поднять до 80%"* — this is the exact model for US1/US2 combined: relevance number **and** the specific action, in one line.
- Factual relevance explanation, same register as Modules 6/7/10's XAI pattern: *"Совпадение 62% - подтверждены 4 из 5 обязательных требований, не хватает независимого подтверждения по ClickHouse."*
- Cross-vacancy compounding confirmation (new copy, same factual register): *"Эта компетенция теперь учитывается ещё в 2 подходящих вакансиях в вашей ленте."*

---

## 4. Data Model

Local-first constraint, consistent with Modules 2–10. This module extends Module 8's `ReturnTrigger` (adds the fields a vacancy-based trigger actually needs) and reads Module 10's `Vacancy`/`MatchResult`; it does not introduce a new scoring engine.

### 4.1 `ReturnTrigger` (extends Module 8 §4.4 — additive fields only, not a redefinition)
```json
{
  "id": "rt_002",
  "trigger_type": "white_spot_reminder | competency_decay_warning | new_matching_vacancy",
  "related_ref": "vac_001",
  "match_score_at_detection": 62,
  "explanation_ref": "expl_010",
  "status": "pending | sent | acted_upon | dismissed",
  "created_at": "ISO8601"
}
```
- `new_matching_vacancy` is the one net-new `trigger_type` value this module activates — `related_ref` points to a `Vacancy.id`, and `match_score_at_detection` is stored so the notification's claim ("62% match") stays accurate to the moment it fired even if the underlying `MatchResult` later changes.
- `explanation_ref` points to a Module 7 `Explanation` record (new `subject_type` value needed there: `"vacancy_match"` — small additive patch to that module's schema, same pattern already used when Module 5 needed a new `Evidence.type` added to Module 2).
- `acted_upon` remains the only metric this module treats as meaningful, per Module 8's own established rule (§4.4 there) — a trigger that was merely `sent` proves nothing about Compounding.

### 4.2 `RelevanceThreshold` (calibration-pending constant)
```json
{ "min_match_score_to_notify": 55 }
```
- Ship as a single named, swappable constant — same calibration-pending convention used everywhere else in this series (Modules 3/4/6/8). The number `55` is illustrative, not a validated figure — do not present it as final without Ch.13 calibration.

### 4.3 Local detection simulation (replaces live parsing for this phase)
```json
{ "last_checked_at": "ISO8801", "newly_seen_vacancy_ids": ["vac_007"] }
```
- A lightweight local marker: on each simulated "check" (e.g. app open, or a manual "check for new vacancies" test action in this prototype), compare `Vacancy.created_at` in the seed dataset against `last_checked_at`; any entries newer than that are candidates for `new_matching_vacancy` detection (FR1.1).
- This is explicitly a **stand-in** for the real parsing pipeline's arrival signal — when that pipeline exists, it becomes the actual producer of "newly seen" vacancies, and this local marker mechanism can be retired without changing anything downstream of it (§0).

---

## 5. Functional Requirements

### US1 — Get notified when a relevant opportunity appears

| ID | Requirement |
|---|---|
| FR1.1 | On each detection sweep (§4.3), any `Vacancy` newer than `last_checked_at` has its `MatchResult` computed (Module 10, unchanged) against the candidate's current `PROFIndexSnapshot`. If `overall_match_score` meets or exceeds `RelevanceThreshold.min_match_score_to_notify` (§4.2), create a `ReturnTrigger(trigger_type: "new_matching_vacancy")`. |
| FR1.2 | Only vacancies genuinely new since the last check are considered — this module must not re-notify for a vacancy the candidate has already seen/dismissed, even if their `PROFIndexSnapshot` has since changed and would now score differently (that case is better served by the candidate revisiting the feed themselves, not a repeat notification, to avoid notification fatigue that would undermine the "not spray-and-apply" constraint Module 10 already established). |
| FR1.3 | Consistent with Module 8's explicit single-trigger-tested-at-a-time discipline: this module does not compete with `white_spot_reminder` for attention — if both are simultaneously eligible, prioritize surfacing them separately/sequentially rather than merging into one noisier notification, so it stays possible to attribute a candidate's return action to a specific trigger type (needed for the H1b measurement itself, §8). |

**Acceptance criteria:** simulating the arrival of a new, sufficiently relevant seed vacancy produces exactly one `ReturnTrigger(new_matching_vacancy)`, and no trigger is produced for vacancies already seen or below threshold.

---

### US2 — Understand why the system considers a vacancy relevant

| ID | Requirement |
|---|---|
| FR2.1 | Every `ReturnTrigger(new_matching_vacancy)` carries a Module 7 canonical `Explanation` (new `subject_type: "vacancy_match"`) with a factual `conclusion_ru` — e.g. *"Совпадение 62% - подтверждены 4 из 5 обязательных требований, не хватает независимого подтверждения по ClickHouse"* — never a bare percentage or a vague "this looks like a good fit for you." |
| FR2.2 | This explanation must be traceable to Module 10's actual `MatchResult.covered_requirements`/`uncovered_requirements` for that vacancy (`evidence_refs` in Module 7's shape) — this module does not compute a separate, parallel "relevance" judgment; it renders the existing Match breakdown as the explanation. |
| FR2.3 | The same universal `"Почему такой вывод?"` entry point established in Module 7 must work here too — a candidate reaching this explanation from a notification must land in the exact same explanation view as one reaching it by manually opening the vacancy from Module 10's feed, not a separate, notification-specific screen with different content. |

**Acceptance criteria:** opening any relevance notification shows a factual explanation directly traceable to specific covered/uncovered requirements, using the same explanation view already established for every other conclusion in the product.

---

### US3 — Return and strengthen only the competencies that matter for the new opportunity

| ID | Requirement |
|---|---|
| FR3.1 | Clicking/opening a `new_matching_vacancy` trigger navigates the candidate directly to that vacancy's Module 10 detail view, scrolled/focused on its `uncovered_requirements` and their routed `recommended_action` — not to a generic profile dashboard the candidate would then have to search through themselves. |
| FR3.2 | This module reuses Module 10's FR4.1 routing exactly (`answer_existing_probe` vs. `add_evidence`) — it does not introduce a third path or a vacancy-triggered variant of either mechanism. The only thing this module adds is *how the candidate arrived* at that already-existing recommendation, not what the recommendation is or does. |
| FR3.3 | Only the requirements genuinely relevant to *this* vacancy are surfaced in the focused return flow — already-`medium`/`strong` competencies for this vacancy (whether from this role or reused from another declared role, Module 8 US2) are not re-presented as if they needed attention; this is the direct enforcement of "only where evidence is insufficient" (Module 8 US3) inside the retention loop specifically. |

**Acceptance criteria:** a candidate who clicks a relevance notification lands on exactly the gaps that matter for that vacancy, with no unrelated profile sections demanding attention first, and sees the same routed action Module 10 would show them if they'd found the vacancy on their own.

---

### US4 — Every new confirmation increases the profile's usefulness for future opportunities

| ID | Requirement |
|---|---|
| FR4.1 | Whenever a `Statement.status` upgrade occurs (via any path: Module 2 evidence, Module 4 probe answer, Module 5 NDA-alternative, or this module's own focused return flow), this module recomputes `MatchResult` for **every** `Vacancy` currently in the candidate's local feed/history — not only the one that triggered the return session. |
| FR4.2 | If a recompute causes a previously-uncovered requirement to flip to covered on a *different* vacancy than the one the candidate was working on, log a `ProfileGrowthEvent` (Module 8 §4.2, reuse the entity, extend `event_type` with `"match_score_increased_across_vacancies"`) — this is the literal, demonstrable evidence for the module's own stated purpose: proof the confirmation compounded beyond its original context. |
| FR4.3 | Surface this cross-vacancy effect to the candidate explicitly when it happens, using the established factual register (§3): *"Эта компетенция теперь учитывается ещё в 2 подходящих вакансиях в вашей ленте."* Do not let this compounding effect happen invisibly in the background — the whole point of testing H1b is that the candidate perceives the value, not just that the system technically computed it correctly. |
| FR4.4 | This module builds no new scoring logic to satisfy this requirement — it is a direct, mechanical consequence of Module 8's already-established global-confirmation guarantee (that module's US2/FR2.1) plus Module 10's already-established recompute-on-read convention, simply triggered across the *whole* feed instead of a single vacancy. If FR4.1 requires new code, it should be "loop over all vacancies and call Module 10's existing recompute," not a parallel implementation. |

**Acceptance criteria:** closing a gap that happens to matter for more than one vacancy in the local feed produces a visible, factual notice of the cross-vacancy effect, and a corresponding growth-history entry — demonstrated on at least one seed scenario where the same competency is required by two different seed vacancies.

---

## 6. Cross-cutting constraint (carried over from Module 10, still binding here)

This module is the most tempting place in the whole series to accidentally reintroduce spray-and-apply patterns (notifications are inherently attention-grabbing) — the constraint from Module 10 §6 applies without exception:

| ID | Requirement |
|---|---|
| FR-Constraint.1 | No apply/quick-apply action is introduced by this module either — a relevance notification leads to a *strengthening* action (US3), never an application action, since no application flow exists anywhere in this series. |
| FR-Constraint.2 | Notification frequency/volume must never become the module's own success metric — per FR1.3 and Module 8's established discipline, `acted_upon` rate is the only meaningful signal; a high notification-send rate with a low action rate is a **failure** signal for H1b, not a feature working as intended. |

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication:** same single implicit local session as Modules 2–10.
- **No real push/delivery channel:** this phase surfaces `ReturnTrigger`s only within the local app session (e.g. a badge/banner shown at next open) — there is no browser push subscription, email, or SMS integration here; that's a separate later integration, not something this FRD's UI requirements assume exists.
- **Detection sweep is a manual/simulated trigger in this phase** (§4.3) — implement it as an explicit, callable check (even a debug/test action) rather than a real scheduled background job, since there's no backend to host a scheduler on yet.
- **Explanation schema patch:** confirm Module 7's `Explanation.subject_type` enum is extended to include `"vacancy_match"` — small additive change, same convention as prior cross-module patches in this series (Module 5→2, Module 7→3/4/6).

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| Live vacancy-parsing pipeline | Unchanged from Module 10 §2.2 — infra/ops task, this module consumes its eventual output as a second event producer, same shape. |
| `recruiter_interest` trigger | Needs a recruiter-side/auth system genuinely absent from this whole module series (§0). |
| Real push/email/SMS delivery | Separate integration; this phase is in-app-only surfacing. |
| `RelevanceThreshold.min_match_score_to_notify` exact value | Explicitly calibration-pending (§4.2), same convention as every other placeholder constant in this series. |
| Vacancy-Specific Probe | Still [V2] per Module 10 — this module's focused return flow routes only to already-existing mechanisms. |

---

**H1b hypothesis this module exists specifically to test (the master document's own words, restated as the concrete falsifiable claim):**
- A candidate notified of a specific, factually-explained relevant opportunity (US1/US2) returns and takes a real strengthening action (US3) at a meaningfully non-zero rate, **and** that action's value is visible beyond the single triggering vacancy (US4) — if candidates open notifications but rarely act, or act but the effect looks purely local to one vacancy with no visible compounding, that's a direct signal the "накопительный актив" thesis isn't holding, not a UI-copy problem to iterate around.
