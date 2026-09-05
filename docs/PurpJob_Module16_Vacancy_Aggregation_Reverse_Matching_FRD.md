# PurpJob — Module 16: Vacancy Aggregation / Reverse Matching
## Architecture-Readiness Specification — [V2], Not in Current Build Scope

**Status:** [V2] — explicitly **not** part of the MVP-0/MVP-1 build queue (Modules 1–15). This document exists to (a) specify the target capability precisely enough that it isn't reinvented ad hoc later, and (b) define the **readiness contract** — what Modules 6/10/11/12 must keep true so this can be added on top of them later without rearchitecting the TrustScore core.
**Depends on (as a consumer, never a modifier):** Module 6 (`TrustScoreSnapshot`), Module 10 (`Vacancy`, `MatchResult`, Filter Б), Module 11 (`ReturnTrigger`), Module 12 (candidate rendering, `visibility_state` gate)
**This document does not specify a buildable FRD in the sense Modules 1–15 were** — there are no local seed datasets, no acceptance criteria to implement this sprint. It's a blueprint plus a constraint list.

---

## 1. Purpose — and the one architectural decision this entire module exists to protect

The master document is explicit that early drafts of this product **conflated two different things**: (A) PurpJob as trust infrastructure — the actual product, everything Modules 1–15 build — and (B) PurpJob as an intelligent job aggregator with a reverse-matching marketplace (vacancy → requirement analysis → matched verified candidates → ready-made report for the recruiter, without the recruiter asking). The considered decision, already made and worth protecting rather than re-litigating: **(A) is the core; (B) is a future distribution layer on top of it, not an alternative product and not a co-equal concern to build alongside the core.**

**This FRD's real job is to keep that separation real in the architecture, not just in the roadmap document.** Concretely: Reverse Matching/Aggregation must be buildable **entirely as a consumer** of Module 10's Match engine and Module 12's candidate rendering — it introduces no new scoring logic of its own, never reaches into Module 6's Trust Score internals directly, and must be removable without affecting the TrustScore core's ability to function completely on its own. If building this module ever requires changing how Module 6 computes Trust Score, that's a sign the separation has been violated, not a normal implementation detail.

**Product principle mapping (for when this is eventually built):**

| Principle | How this module would implement it |
|---|---|
| Layer 3 network effect (Ch.4) | This is explicitly the mechanism the master document places at "Layer 3" — the classical network effect that requires Layers 1 (candidate-level compounding, Modules 8/11) and 2 (platform-level calibration, Module 14) to already be working; it's a lift on top of an accelerating system, not the initial engine. |
| Non-conflation of scoring and distribution | Match/Trust computation stays exactly where it already lives (Modules 6/10); this module only decides *when* and *to whom* to surface an existing computation, at greater scale and in the reverse direction. |

---

## 2. Target capability (for future build — described at blueprint depth, not acceptance-criteria depth)

### US1 — Candidate sees vacancies from multiple sources in one place
Already substantially architected in Module 10: `Vacancy.source_channel` and the explicit dedup requirement (Module 10 §5, FR1.4 — duplicate postings across channels merge into one card retaining all sources) are exactly the data shape a real, large-scale, multi-source aggregation pipeline (Telegram channels, career pages) would populate. **Nothing about this module changes that contract** — it's the same `Vacancy` shape, fed by real parsing infrastructure instead of a hand-seeded local dataset.

### US2 — System automatically matches discovered vacancies to the candidate's PROF
Already fully specified by Module 10's `Match Score = f(PROF.Index, vacancy-specific weights)` formula and Module 11's `ReturnTrigger(new_matching_vacancy)` push mechanism (built against a *simulated* local arrival signal there, explicitly noted as a stand-in for this exact future pipeline). **This module's only real addition is running that same computation at real scale** — across potentially thousands of parsed vacancies against every `visible`-mode candidate — which is an infrastructure/performance concern (vector similarity search, background job scheduling), not a new functional contract.

### US3 — Candidate receives only genuinely relevant vacancies (not spam)
This is where Module 10's explicitly-deferred **Filter В** (junk-vacancy detection, tagged [V2] there specifically because it wasn't critical to test H1a/H1b at MVP-0 scale) finally becomes necessary — at real aggregation scale, an unfiltered feed would reintroduce exactly the job-board noise problem this product is positioned against. Building Filter В is a natural, in-scope part of this module when it's eventually built, not a separate deferred item to track elsewhere.

### US4 — Recruiter receives candidates who already fit the vacancy and are verified, unprompted
This is the actual direction-flip: instead of Module 12's recruiter-*initiated* search, the system runs Module 10's Match engine automatically the moment a new vacancy is parsed, against the *entire* verified-candidate base, and proactively produces a structured "here's who fits and why" report — reusing Module 12's exact candidate rendering (PROF/Trust/Match breakdown), never a second reporting format. This is also where **"Цена завышенных требований"** (the mirror of Module 13's "Цена предубеждения") would live: while a vacancy is being composed, a recruiter sees how many strong, verified candidates a stricter-than-typical requirement excludes — the same requirement-analysis engine (Filter Б, Module 10) applied at authoring time instead of only at report-viewing time.

### US5 — PurpJob uses the aggregated market as both a candidate-acquisition channel and a reverse-matching source
Two already-decided, separable threads, not one mechanism:
- **Candidate acquisition** is already live at MVP-0 scale via Module 10's pull-based feed (Cold Start driver #1) — this module just extends it to real multi-source volume.
- **B2B distribution/lead generation** reuses the exact monetization decision already closed in the source material (Backlog #24): a parsed vacancy is a *pure GTM lead-generation trigger* into the already-existing Ch.11 revenue streams (SaaS subscription / Pay-per-Verified-Match) — there is no separate "pay per lead" pricing model, and this document doesn't introduce one.
- **Crowdsourced source discovery** (candidates independently naming the same job-search channel, which then gets prioritized for parsing) is a related, smaller network-effect mechanic worth keeping on the same roadmap page, but it's a minor addition to the parsing-source-discovery process, not a core requirement of this module's five user stories.

---

## 3. Architecture-readiness checklist — what must already be true (and mostly already is)

This is the actual deliverable of this FRD: confirming the interfaces this future module will consume are stable enough not to require rework.

| Requirement for future readiness | Current state |
|---|---|
| `Vacancy` schema supports multi-source provenance and dedup | ✅ Already specified, Module 10 §4.1/§5 — `source_channel`, dedup-into-one-card rule |
| Match computation is vacancy-agnostic and reusable in either direction (candidate→vacancy or vacancy→candidates) | ✅ Already true by construction — Module 10's `f(PROF.Index, vacancy weights)` doesn't care which side initiated the query; Module 12 already applies it in a loop across a candidate pool for recruiter-initiated search, which is structurally the same operation Reverse Matching would run automatically |
| A per-candidate "new relevant vacancy" event already has a home | ✅ Module 11's `ReturnTrigger(new_matching_vacancy)`, currently fed by a local simulation — a real parsing pipeline becomes a second, drop-in producer of the same event shape, no redesign needed |
| Candidate privacy gate is enforced at the data layer, not just UI | ✅ Module 12 §4.1/§6 — `visibility_state.mode == "visible"` as a hard, structural read-gate; Reverse Matching, when built, must call into this exact same gate, never re-implement a parallel visibility check |
| Recruiter consumption of match results reuses one rendering path | ✅ Module 12's candidate detail/comparison views — a proactive Reverse Matching report must render through these, not a second, divergent report template |
| Requirement-extraction (Filter Б) is already decoupled from *how* the vacancy text arrived | ✅ Module 10 (parsed feed) and Module 15 (pasted plugin text) already both call the same Filter Б logic — a third caller (real-time aggregation pipeline) fits the same pattern without change |
| Monetization treatment of a parsed vacancy is already decided | ✅ Backlog #24 (closed) — pure GTM tool, no separate lead-fee pricing; this module doesn't need to resolve anything new commercially |

**The one gap that would need new work, not just reuse:** Filter В (junk detection) doesn't exist anywhere yet — building it is real, net-new scope when this module is picked up, not something already quietly covered elsewhere.

---

## 4. Explicitly not in scope for this document (and not to be started opportunistically alongside MVP-0/1)

| Item | Why it stays out now |
|---|---|
| Live, large-scale parsing infrastructure (Telegram ingestion across 100+ channels, career-page scraping at scale, a vector database for fast large-scale matching, background job scheduling) | Genuine infrastructure engineering, gated on the trigger condition in §5, not something to prototype speculatively while the candidate core is still being validated |
| Filter В (junk-vacancy detection) | Net-new scope, only worth building once real aggregation volume makes it necessary (§2, US3) |
| "Цена завышенных требований" vacancy-authoring UI | A recruiter-facing authoring-time feature — depends on a structured, in-platform vacancy-creation flow that doesn't exist anywhere in Modules 1–15 |
| Crowdsourced source discovery | Minor, related mechanic — not required for the five core user stories, safe to defer independently even after the rest of this module is built |
| Any B2B outreach/sales-motion tooling for contacting the vacancy's original poster | GTM/sales process, not application logic — this document only confirms the monetization *policy* is already settled, not the outreach tooling |

---

## 5. Trigger condition — when this actually becomes worth building

Reused directly from the master document's own gating logic, not invented for this FRD: this mechanism **"имеет смысл только после того, как на платформе уже накопились кандидаты, качественные профили и минимальная recruiter value"** — i.e., not before Module 12/14's H3 (recruiter decision-impact) hypothesis has shown a real signal. Building the aggregation/reverse-matching layer before that point would mean offering recruiters a "here's who fits" report on a candidate base that doesn't yet have enough verified depth to make the report meaningful — the exact "nothing to offer yet" problem the master document itself flags as the reason this stays [V2].

---

**Bottom line for planning purposes:** almost everything this future module needs from the rest of the system already exists as a stable, reusable interface (§3) — which is the direct, intended payoff of having built Modules 10/11/12 the way they were specified (single-direction Match engine, event-shaped return triggers, gate-enforced candidate rendering). When the trigger condition in §5 is met, this module should be a genuinely additive layer, not a rewrite.
