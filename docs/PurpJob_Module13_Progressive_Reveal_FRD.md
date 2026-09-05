# PurpJob — Module 13: Progressive Reveal
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP, same sequencing boundary as Module 12 — this is a layer on top of the recruiter view, not a standalone feature]
**Phase:** Local prototype (no authentication layer — see Module 12 §7 for the recruiter-mode pattern this module reuses)
**Depends on:** Module 3 (`VisibilityState`), Module 6/7 (`TrustScoreSnapshot`, `Explanation`, `consent_for_recruiter_view`), Module 12 (recruiter search/detail/comparison views — this module gates *when* parts of what Module 12 already renders become visible, not what data exists)
**Closes a previously-deferred item:** Module 8's `recruiter_interest` return trigger, explicitly deferred there for lack of a recruiter side — Module 12 built that side; this module is where the actual "recruiter showed interest" event first exists, and it should fire that trigger (§5, US2)

---

## 1. Purpose

Progressive Reveal exists for one specific, falsifiable reason, stated directly in the source material: **forcing the initial screening decision to be based on professional-relevance data alone**, before any identity-linked signal (name, photo) that correlates with age, gender, ethnicity, or other bias vectors ever enters the recruiter's view. This isn't a privacy feature dressed up as an anti-bias feature — it's specifically an anti-bias mechanism that happens to also respect the candidate's data.

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| P4 — Privacy/NDA respect | The candidate's identity-linked data is withheld by default until a deliberate, logged recruiter action — not exposed as a side effect of appearing in search results. |
| Bias reduction (Ch.9, the module's actual stated purpose) | Screening order is structurally enforced — a recruiter cannot skip straight to "does this person look/sound like our usual hire" before engaging with the evidence. |
| XAI, both directions, with candidate consent | This module doesn't introduce a new consent concept — it sequences the *timing* of what Module 12 already gates by `visibility_state`/`consent_for_recruiter_view`. |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- **Two-stage reveal, exactly as specified in the source material:**
  - **Stage 1 (default view):** PROF.Index, Trust Score + explanations, Match Score breakdown, competency/requirement detail — everything Module 12 already renders — **minus** the candidate's name and photo, replaced with a stable anonymized label (US1)
  - **Stage 2 (after an explicit recruiter action):** name and photo become visible for that specific candidate, to that specific recruiter (US2)
- Candidate-facing visibility into their own reveal state per recruiter interaction, plus an explicit opt-out control (US3 — see §0 flag below on exactly how much control this should be)
- Firing Module 8's `recruiter_interest` `ReturnTrigger` the moment a recruiter advances a candidate to Stage 2 — this is this module's natural byproduct, not extra work (§5)
- A lightweight, documented **Stage 3** extension (contact info, gated on *mutual* interest — candidate must also opt in, not just the recruiter) since it's the same staged-disclosure principle, even though it's sourced from a slightly different part of the material than the core two-stage mechanic (see §0)

### 2.2 Out of scope (explicitly deferred)
- **"Цена предубеждения"** (the age/gender-filter warning shown when a recruiter narrows search by those attributes) — a related but distinct Ch.9 bias mechanic, not requested by these three user stories, and explicitly tagged in the source material as shipping **without a precise number** until real data accumulates (Ch.13 calibration) — if built later, it must not display an illustrative statistic ("narrows funnel by 45%") as if it were measured
- Skill-Velocity-replaces-age-filter — [V2], depends on Skill Velocity (Module 3-adjacent, not built)
- Blind multimodal competency invariants (alternative verification channel for atypical speech patterns) — [V2], needs multiple parallel data channels per competency that don't exist yet
- "High Complexity / Low Data" appeal process — [V2], needs a human-assessor operational process (Ch.13), not just application logic
- Company-calibrated bias filters (Enterprise Customization) — [V3]

---

## ⚠️ 0. Two things to confirm before building this

**1. How much candidate control over the reveal sequence is actually intended.** Your US3 asks for the candidate to control what's available to the recruiter *at each stage*. But the source material (`Put_kandidata_MVP0_v2.md`) states the reveal *order* is explicitly **"recruiter-side механика, не входит в"** the candidate's own visibility-settings screen — implying the staged sequencing itself is a platform-enforced default the candidate doesn't get to reconfigure per-recruiter, precisely *because* letting candidates (or recruiters) casually bypass it would undermine the anti-bias purpose it exists for. **This FRD reconciles the two readings as follows, flagged rather than silently picked:** the candidate's existing `VisibilityState` (Module 3: `visible`/`hidden`) remains the absolute outer gate — nothing is ever staged-revealed to a `hidden` profile at all — and the candidate can see, per recruiter, what stage that recruiter has reached (transparency, not veto). On top of that, this FRD adds one explicit, visible candidate-level toggle — *"разрешить рекрутерам сразу видеть полное имя и фото, без поэтапного раскрытия"* — off by default, so a candidate who has a specific reason to want immediate full visibility isn't structurally blocked. **Confirm this is the right level of control before building** — if the intent was actually per-recruiter fine-grained control, or no candidate control at all beyond the visibility mode, this section needs a rewrite.

**2. Stage 3 (contacts after mutual interest) is documented separately from "Progressive Reveal" proper.** The two-stage PROF/Trust → name/photo sequence is the literal Ch.9 "Progressive Reveal" mechanic. Contact info gated on mutual interest is listed elsewhere in the source material as its own item under "Дополнительные настройки" (additional visibility settings), not inside the Progressive Reveal row itself. I'm including it here as **Stage 3** because your user stories speak generally of "этапы интереса" (plural) and the mechanic is a natural continuation of the same principle — but flagging that it's sourced from a different part of the document, in case that was intentional separation rather than an oversight.

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values (`stage1_professional`, `stage2_identity`, `stage3_contact`) | English |
| All UI copy | **Russian**, matching the register already established across Modules 2–12 |

New copy needed:
- Anonymized candidate label pattern: *"Кандидат #A17"* — stable per candidate for the duration of a recruiter's engagement with them (not re-randomized on every view, which would make it impossible for a recruiter to recognize "the same candidate I was looking at yesterday" pre-reveal).
- Stage-advance action label: *"Показать больше об этом кандидате"* or similar — must read as a deliberate, weighty action (advancing past anonymized screening), not a casual "expand" toggle.
- Candidate-facing transparency copy: *"Рекрутер [вакансия X] пока видит только ваш PROF.индекс и Trust Score. Имя и фото будут показаны, если рекрутер отметит интерес к вашему профилю."*
- Opt-out toggle label (§0): *"Разрешить рекрутерам сразу видеть моё имя и фото"* — off by default.

---

## 4. Data Model

Local-first, consistent with Modules 2–12. This module adds a thin state layer on top of Module 12's existing search/detail views — it introduces no new scoring or profile data of its own.

### 4.1 `RevealState` (per recruiter session × candidate pair)
```json
{
  "recruiter_session_id": "string",
  "candidate_id": "cand_001",
  "current_stage": "stage1_professional | stage2_identity | stage3_contact",
  "stage2_advanced_at": "ISO8601 | null",
  "stage3_advanced_at": "ISO8601 | null",
  "advance_trigger": "recruiter_marked_interest | mutual_interest_confirmed"
}
```
- Scoped per `(recruiter_session_id, candidate_id)`, **not** per vacancy — once a recruiter has reached Stage 2 for a candidate, that doesn't reset if the same recruiter later finds the same candidate under a different vacancy search; identity, once revealed to a specific recruiter, doesn't un-reveal.
- `stage3_advanced_at` requires **both** the recruiter's action **and** the candidate's own separate opt-in for that specific interaction (§5, US-Stage3) — this is what makes it "mutual," distinct from Stage 2's recruiter-only trigger.

### 4.2 `CandidateRevealPreference` (§0 opt-out)
```json
{ "allow_immediate_identity_reveal": false }
```
- Default `false` for every candidate — the staged default is the anti-bias mechanism; this is an explicit, visible opt-out, not a buried setting.

---

## 5. Functional Requirements

### US1 — See minimally necessary information first, so initial screening is based on professional relevance

| ID | Requirement |
|---|---|
| FR1.1 | Every candidate appearing in Module 12's search results or detail view starts, for a given recruiter, at `stage1_professional` — showing PROF.Index, Trust Score + explanations, Match Score breakdown, and competency/requirement detail (everything Module 12 US2–US4 already render) **except** name and photo. |
| FR1.2 | Name and photo are replaced with a stable anonymized label (§3) and a neutral placeholder — never left visibly "blank" in a way that reads as missing data or a broken profile; it should read as *intentionally* staged, not incomplete. |
| FR1.3 | This module changes nothing about *what* data exists or is computed — it only withholds *when* two specific fields (name, photo) are rendered to a recruiter. All of Module 12's existing privacy gates (`visibility_state`, `consent_for_recruiter_view`, the absolute exclusion of declined findings) apply exactly as already specified there, unmodified. |
| FR1.4 | Comparison view (Module 12 US5) must also respect Stage 1 by default — comparing multiple anonymized candidates side-by-side is precisely the scenario this feature is designed to support, and must not be silently bypassed just because multiple candidates are being viewed at once. |

**Acceptance criteria:** a recruiter opening any candidate for the first time sees full professional/evidence data with name and photo replaced by a stable anonymized label, with no other data withheld beyond those two fields.

---

### US2 — Reveal additional information only after the recruiter passes to the next stage of interest

| ID | Requirement |
|---|---|
| FR2.1 | A recruiter can take one explicit action (§3, *"Показать больше об этом кандидате"*) to advance a specific candidate from `stage1_professional` to `stage2_identity` — this must be a deliberate, single-purpose action, never a side effect of another action (e.g., not automatically triggered by "viewed for N seconds" or "opened detail view"). |
| FR2.2 | Advancing to Stage 2 reveals name and photo for that candidate, to that recruiter, from that point forward (§4.1) — it does not retroactively change anything about Stage 1's other content, and it does not affect any *other* recruiter's `RevealState` for the same candidate. |
| FR2.3 | **This module closes Module 8's previously-deferred `recruiter_interest` return trigger:** the moment a recruiter advances a candidate to Stage 2, this module creates a `ReturnTrigger(trigger_type: "recruiter_interest", related_ref: candidate_id)` (Module 8 §4.4 shape) — this is the first point in the whole series where that trigger type has a real producer; wire it in rather than leaving Module 8's placeholder unfilled now that it's finally possible. |
| FR2.4 | (§0, Stage 3 extension) A further, separate recruiter action can request contact information — this only actually reveals contacts if the candidate has **also**, independently, opted in for that specific recruiter/interaction (mutual interest) — a recruiter-only action is never sufficient for Stage 3, unlike Stage 2. |

**Acceptance criteria:** name/photo become visible only after the recruiter takes the specific, deliberate "show more" action — never automatically — and that action visibly triggers Module 8's retention-loop mechanism for the candidate.

---

### US3 — Candidate controls what data is available to the recruiter at each stage

| ID | Requirement |
|---|---|
| FR3.1 | The candidate can see, per recruiter/interaction, what `current_stage` has been reached (§4.1) — this is transparency, not a veto over an in-progress stage, consistent with §0's reconciliation. |
| FR3.2 | The candidate has one explicit, off-by-default toggle (`allow_immediate_identity_reveal`, §4.2) that, if enabled, skips straight to `stage2_identity` for every recruiter viewing them — a deliberate, visible opt-out of the staged default, not a hidden or easily-triggered setting. |
| FR3.3 | Stage 3 (contacts) always requires the candidate's own, per-interaction opt-in regardless of `allow_immediate_identity_reveal` — enabling immediate identity reveal does **not** imply consent to contact disclosure; these remain two independent decisions. |
| FR3.4 | None of this module's mechanics can ever expose a candidate whose `VisibilityState.mode == "hidden"` at any stage — Progressive Reveal operates entirely within the `visible`-gated pool Module 12 already established; it is a sequencing layer on top of that gate, never a way around it. |

**Acceptance criteria:** a candidate can see per-recruiter reveal progress, can opt out of the staged default entirely if they choose to, and Stage 3 contact disclosure never happens without their own separate, explicit action — none of this is possible for a `hidden`-mode profile regardless of any of these settings.

---

## 6. UI Flow

Extends Module 12's screens rather than introducing new ones:

1. **Module 12's search results/detail view:** render with anonymized label + hidden photo by default (Stage 1) — this is a rendering-layer change to an existing screen, not a new screen.
2. **New action on the candidate detail view:** *"Показать больше об этом кандидате"* — advances to Stage 2, fires FR2.3's trigger.
3. **New candidate-facing screen/section:** "Кто интересуется вашим профилем" — per-recruiter stage transparency (FR3.1), reachable from the same area as Module 6/8's other candidate-facing status views.
4. **Extend Module 3's visibility settings:** add the `allow_immediate_identity_reveal` toggle (§4.2) as one clearly-labeled, off-by-default item — do not bury it among unrelated settings, given its direct relevance to the anti-bias purpose of this whole module.

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication:** same local recruiter-mode pattern as Module 12 — `recruiter_session_id` is a local prototype construct, not a real account identifier.
- **Stable anonymized labels:** generate once per candidate (e.g. derived deterministically from `candidate_id`), not per view/session — a recruiter must be able to recognize "this is the same anonymized candidate I looked at before" across repeated visits pre-reveal.
- **Stage state is additive, not destructive:** `RevealState` never deletes or recomputes any underlying Module 3/6/10/12 data — it is purely a display-gating layer, easy to verify by confirming no code path in this module writes to those modules' entities.

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| **§0.1 confirmation** (exact scope of candidate control over reveal sequencing) | Genuine tension between the user story wording and the source material's "recruiter-side mechanic" framing — needs an explicit decision before this ships as specified. |
| **§0.2 confirmation** (whether Stage 3/mutual-interest-contacts belongs under this module's name at all) | Sourced from a different part of the material than the core two-stage mechanic — may have been intentionally kept separate. |
| "Цена предубеждения" age/gender-filter warning | Related Ch.9 bias mechanic, not requested by these three user stories — separate scope if wanted. |
| Illustrative bias-cost statistics ("narrows funnel by 45%") | Explicitly must not be shown as real numbers before Ch.13 calibration on actual pilot-cohort data — a hard constraint if this adjacent feature is ever built. |
| Skill Velocity / blind multimodal invariants / High Complexity-Low Data appeal | All [V2], unrelated to this specific module's two-stage mechanic. |

---

**H3-adjacent hypothesis this module feeds (recruiter-side, same sequencing tier as Module 12):**
- Recruiters who screen candidates through Stage 1 (professional data only) advance a materially different set of candidates to Stage 2 than they would have selected from name/photo-first browsing — this is the actual, falsifiable claim behind building Progressive Reveal at all, and it's only testable once real recruiters and real candidate volume exist (same MVP-1+ sequencing dependency as Module 12 itself).
