# PurpJob — Module 10: Vacancies & Basic Match
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-0]
**Phase:** Local prototype (no authentication layer, no persistent backend, single local candidate session)
**Depends on:** Module 3 (`PROFIndexSnapshot`, `CompetencyResult`), Module 4 (existing Contextual Probe path, reused not extended)
**Does not build:** the live vacancy-parsing pipeline itself (Telegram/career-page scraping), or vacancy-specific question generation — both are separate engineering efforts, see §2.2

---

## 1. Purpose

This module gives the candidate a concrete reason to use PurpJob **before any recruiter-side market exists** — per the master document's own Cold Start framing, an aggregated, relevant vacancy feed is a reason to visit the platform on day one, independent of whether a single recruiter has signed up yet.

**Hard constraint, stated directly in the source spec and binding on every requirement below: this must not become another "spray 100 applications" tool.** Match exists to connect the *already-accumulated* profile to *one specific opportunity* at a time — depth over volume, relationship over funnel. Every UI/UX decision in this module should be checked against that constraint, not just the explicit functional requirements.

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| P1 — Evidence-Based Hiring | Match Score is a projection of already-evidenced PROF.Index data onto a specific vacancy's weights — never a fresh, separate judgment. |
| Logic over Memory (Module 8) | A vacancy-specific gap that happens to coincide with an already-confirmed competency is never re-probed — this module surfaces existing confirmation, it doesn't reset it. |
| XAI (cross-cutting) | Every requirement in a vacancy is shown as covered/uncovered with a factual reason, never a bare percentage (US3). |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- Candidate-facing, **pull-based** vacancy feed, filtered to the candidate's declared segment/level (US1)
- **Match Score** computation per the master document's fixed formula: `Match Score = f(PROF.Index, vacancy-specific critical-requirement weights)` — a projection, never an independent score (US2)
- Per-vacancy requirement breakdown: covered vs. vacancy-specific white spots vs. unevaluated Role-Breadth clusters (US3)
- Per-vacancy strengthening recommendation, routed to the two mechanisms that already exist (Module 2 evidence-adding, Module 4's existing Contextual Probe) — no new vacancy-specific question-generation engine (US4)
- All five documented Match-divergence mechanisms (extra requirement beyond reference profile / reweighted criticality / narrower specialization / Role Breadth combined-role handling / level-vs-actual-complexity mismatch)
- Role Breadth cluster-level matching (High/Medium/Low), including the explicit "not evaluated" state for clusters with no matching reference profile in this MVP's single-segment library
- Industry Context (Backlog #34) as an additional requirement tag on a vacancy, scored through the same mechanism as any other extra requirement — not a separate metric

### 2.2 Out of scope (explicitly deferred)
- **The live parsing pipeline itself** (Telegram channel ingestion, career-page scraping, deduplication across sources) — this is infrastructure/ops work (channel list curation, Telethon/Scrapy setup), not candidate-facing application logic, and doesn't fit this phase's "local, no live external network calls" constraint already established for every other module that touches external data (Module 2's OAuth pull, Module 6's Digital Echo). This module consumes a **static seed `Vacancy[]` dataset**, already pre-processed as if Filters А/Б had run on it — same convention as Module 3's `ReferenceProfile` and Module 5's `MirrorTaskScenario` seed content.
- **Filter В** (junk-vacancy detection) — [V2] per the master doc; this MVP's feed quality relies on the seed dataset being hand-curated as realistic, not on an automated junk filter.
- **Full AI Leverage Requirement scoring impact on Match Score** — detection/tagging is [MVP] and is represented as a static, pre-computed field on seed vacancies; but the recruiter-confirmation loop ("human-in-the-loop, recruiter accepts/rejects the tag") that the master doc specifies for it doesn't exist without a recruiter side, and full scoring impact is explicitly [V2] regardless.
- **Vacancy-Specific Probe** — generating new Contextual Probe questions targeting a gap that exists *only* because of this specific vacancy (not the reference profile) is explicitly [V2] per the master doc's own Backlog #31 resolution: *"MVP - декомпозиция вакансии, Role Breadth... V2 - полноценный Vacancy-Specific Probe с накоплением evidence и учётом в Match Score."* This module's recommendation (US4) therefore only ever routes to Module 2/4's **existing** mechanisms, never spins up a new one.
- Automatic "new matching vacancy" **push** notification as a return trigger — Module 8 already explicitly defers this to MVP-1 (it requires live parsing as a proactive signal, not just a browsable feed); this module implements the **pull**-based browsing experience only.
- Reverse Matching / Crowdsourced source discovery — [V2], needs an accumulated base of verified profiles this MVP doesn't have yet.
- Any apply/quick-apply flow, application tracking, or application-count gamification — **deliberately absent, not merely unbuilt** (see §6 hard constraint).

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values (`filter_a_grade`, `role_breadth`, `mandatory`, `nice_to_have`, `not_evaluated`) | English |
| All UI copy: vacancy cards, Match Score breakdown, recommendation text | **Russian**, matching the register already established across Modules 2–9 |

Reuse existing patterns, don't re-derive:
- Role Breadth framing must stay factual/structural, never evaluative — per the master doc's own instruction: *"не оценочное суждение о качестве вакансии, а структурное описание"* — e.g. *"Эта вакансия объединяет 2 функциональных кластера: Backend-разработка и DevOps"*, never *"эта вакансия слишком размыта."*
- Unevaluated-cluster framing: *"эта часть требований пока не оценена платформой"* — explicit and neutral, never silently dropped (reuses the exact non-silent-drop principle already established for Module 3's Role-Breadth-adjacent White Spot handling).
- Requirement-gap explanation: reuse the factual XAI pattern from Modules 6/7 verbatim — e.g. *"ClickHouse — в вашем профиле нет ни одного независимого подтверждения"*, never *"недостаточно хороший стек."*

---

## 4. Data Model

Local-first constraint, consistent with Modules 2–9: flat local JSON. This module reads a static seed `Vacancy[]` dataset and Module 3's `PROFIndexSnapshot`/`CompetencyResult`; it writes only `MatchResult` (computed, not persisted long-term — recompute-on-read, same convention as Modules 3–6).

### 4.1 `Vacancy` (static seed data, pre-processed — not live-parsed in this phase)
```json
{
  "id": "vac_001",
  "title_ru": "Backend-разработчик (Python)",
  "company_label": "string",
  "stated_level": "Middle | Senior",
  "filter_a_grade": "management | executive",
  "role_breadth": "high | medium | low",
  "functional_clusters": [
    { "cluster_label_ru": "Backend-разработка", "reference_profile_id": "ref_backend_fullstack_python_go_middle" }
  ],
  "requirements": [
    {
      "id": "req_001",
      "competency_id": "rest_api_design",
      "label_ru": "Проектирование REST API",
      "criticality": "mandatory | nice_to_have"
    },
    {
      "id": "req_002",
      "competency_id": null,
      "label_ru": "Опыт с ClickHouse",
      "criticality": "mandatory"
    }
  ],
  "industry_context": "string | null",
  "ai_leverage_flag": "boolean | null",
  "source_channel": "string",
  "created_at": "ISO8601"
}
```
- `requirements[].competency_id` is `null` for a vacancy-only requirement not present in any existing `ReferenceProfile` (Match-divergence mechanism #1, e.g. ClickHouse) — this is the field that drives the routing decision in US4/FR4.1.
- `functional_clusters` is only meaningfully populated when `role_breadth: "high"` (or `"medium"`) — for `"low"`, a single implicit cluster mapping to the candidate's declared role is assumed.
- This dataset is hand-curated/seeded for MVP-0, the same convention already used for `ReferenceProfile` (Module 3) and `MirrorTaskScenario` (Module 5) — no live parsing pipeline writes to it in this phase.

### 4.2 `MatchResult` (computed, per candidate × vacancy, recompute-on-read)
```json
{
  "vacancy_id": "vac_001",
  "overall_match_score": 62,
  "covered_requirements": [
    { "requirement_id": "req_001", "status": "medium", "explanation_ru": "Подтверждено 2 независимыми источниками." }
  ],
  "uncovered_requirements": [
    { "requirement_id": "req_002", "explanation_ru": "ClickHouse — в вашем профиле нет ни одного независимого подтверждения.", "recommended_action": "add_evidence | answer_existing_probe" }
  ],
  "unevaluated_clusters": ["cluster_label_ru strings for role_breadth clusters with no matching reference profile"],
  "computed_at": "ISO8601"
}
```
- **One-directional data flow, hard constraint:** this module reads from Module 3's `PROFIndexSnapshot`; it never writes back to it. A low `overall_match_score` against one vacancy must never be mistaken for, or leak into, the candidate's actual PROF.Index or Trust Score — those remain exactly what Modules 3/6 already computed, independent of any specific vacancy's weighting quirks.
- `uncovered_requirements[].recommended_action` is always one of exactly two values (§5, US4) — never a placeholder for a not-yet-built third mechanism.

---

## 5. Functional Requirements

### US1 — See relevant vacancies as a reason to use PurpJob before a recruiter market exists

| ID | Requirement |
|---|---|
| FR1.1 | The candidate can browse a feed of `Vacancy` records (§4.1), sourced from the static seed dataset in this phase, standing in for the future live parsing pipeline. |
| FR1.2 | The feed is filtered to the candidate's declared segment/level using `filter_a_grade`/`stated_level` — a Backend/Fullstack Middle candidate should never see a wildly mismatched posting (e.g. an entry-level sales role) cluttering the feed; this reuses Filter А's already-decided purpose, just applied to pre-processed seed data rather than live text. |
| FR1.3 | Browsing is **pull-based**: the candidate visits the feed voluntarily. This module does **not** implement a push notification for "new matching vacancy found" — that's Module 8's `ReturnTrigger`, already explicitly scoped to MVP-1 there; don't rebuild it here under a different name. |
| FR1.4 | Duplicate postings sourced from multiple channels merge into a single card retaining all source references — a data-hygiene requirement, not a separate product mechanic; the seed dataset can model this directly (e.g. a `source_channel` array) rather than needing live dedup logic in this phase. |

**Acceptance criteria:** the candidate sees a feed of only segment/level-appropriate vacancies, browsable at will, with no automatic notification behavior implemented in this module.

---

### US2 — See how well the current profile matches a vacancy

| ID | Requirement |
|---|---|
| FR2.1 | `overall_match_score` is computed exactly as `f(PROF.Index, vacancy-specific critical-requirement weights)` — a **projection** of the existing `PROFIndexSnapshot` onto this vacancy's `requirements`, never an independently-derived score with its own separate logic. |
| FR2.2 | All five documented divergence mechanisms must be reflected in how the score is built, not simplified away: (1) a requirement with no matching reference-profile competency contributes according to its own weight, generally starting from unconfirmed; (2) a requirement that exists in the reference profile but is reweighted by this vacancy's `criticality` must use the **vacancy's** weight for this calculation, not the reference profile's default weight; (3) narrower-specialization requirements are modeled the same way as mechanism (1); (4) Role-Breadth-High vacancies are scored per functional cluster against each cluster's own reference profile, never one blended profile (FR2.4); (5) a mismatch between `stated_level` and the actual weight/criticality of extracted requirements is a property of the **vacancy**, not the candidate's PROF.Index — do not let a vacancy that overstates its level drag down how the candidate's own profile is displayed elsewhere. |
| FR2.3 | **Hard one-directional constraint:** computing a `MatchResult` must never write to, mutate, or otherwise affect `PROFIndexSnapshot`, `TrustScoreSnapshot`, or any `Statement`. Match Score is read-only with respect to everything upstream of it. |
| FR2.4 | For `role_breadth: "high"` vacancies, compute a sub-score per `functional_clusters` entry against its own `reference_profile_id` where one exists; for clusters with no matching reference profile in this MVP's single-segment library, mark them explicitly in `unevaluated_clusters` (§4.2) rather than folding them into the overall score as zero or silently excluding them — same "don't stretch onto an unsuitable profile" principle Module 3 already established for its own reference-profile matching. |

**Acceptance criteria:** for any vacancy, the candidate sees one overall Match Score number that visibly derives from their existing PROF.Index plus this vacancy's specific weights — and confirming this never alters the candidate's actual PROF.Index or Trust Score anywhere else in the product.

---

### US3 — See which vacancy requirements are confirmed vs. which are white spots

| ID | Requirement |
|---|---|
| FR3.1 | Every vacancy's requirement list is split into exactly three categories, never blended: **covered** (candidate's global `Statement` already `medium`/`strong` for that `competency_id`), **uncovered / vacancy-specific white spot** (unconfirmed, or a `competency_id: null` requirement with no matching global Evidence), and **unevaluated** (Role-Breadth cluster with no matching reference profile, FR2.4). |
| FR3.2 | Every item in every category carries a factual, checkable explanation (reusing the exact XAI pattern established in Modules 6/7) — never a bare label. A covered item explains *why* it's covered (e.g. which/how many independent sources); an uncovered item explains *why* it isn't (e.g. no evidence at all, vs. evidence exists but below this vacancy's bar). |
| FR3.3 | This breakdown must never re-use or reinvent vocabulary — "covered"/"uncovered"/"unevaluated" map directly onto Module 3's existing `medium`/`strong` vs. `not_started`/`limited` status vocabulary plus the Role-Breadth "not evaluated" concept; no new parallel status taxonomy for this module. |

**Acceptance criteria:** opening any vacancy shows a clear three-way split of its requirements with a factual reason attached to every single item, no exceptions.

---

### US4 — Get a recommendation on what to strengthen for this specific vacancy

| ID | Requirement |
|---|---|
| FR4.1 | Every `uncovered_requirements` entry's `recommended_action` (§4.2) is exactly one of two values, routed by whether `competency_id` is set on the underlying `Vacancy.requirements` entry: **(a) `answer_existing_probe`** — if the requirement maps to an existing reference-profile `competency_id` that's already a White Spot there, recommend Module 4's existing Contextual Probe path (or Module 2 evidence-adding) for that same competency — this module surfaces it with vacancy framing, it does not generate a new question; **(b) `add_evidence`** — if the requirement has no matching `competency_id` at all (a vacancy-only requirement, e.g. ClickHouse), the only available closing path in this MVP is Module 2's free-form evidence-adding — there is no probe-question path for this case, per the Vacancy-Specific Probe deferral (§2.2). |
| FR4.2 | Recommendations are prioritized by `criticality` (`mandatory` before `nice_to_have`) — reuse the same highest-impact-first convention already established for White Spots (Module 3) and Trust Score next-best-actions (Module 6), not a third, divergent ranking rule. |
| FR4.3 | Acting on a recommendation (adding Evidence via Module 2, or answering a probe via Module 4) must cause the `MatchResult` for this vacancy to recompute on next view — consistent with the recompute-on-read convention already established across Modules 3, 4, and 6; no manual "recheck match" action should be needed. |
| FR4.4 | This module must not present the candidate with a fabricated "vacancy-specific case" or generate any new question template — every recommendation resolves to an existing, already-built mechanism (Module 2 or Module 4), full stop. |

**Acceptance criteria:** for any uncovered requirement, the candidate sees exactly one clear, correctly-routed next action (never a vague "improve your profile"), and completing that action updates this vacancy's Match Score without any manual refresh step.

---

## 6. Cross-cutting constraint: this is not a spray-and-apply tool

This isn't tied to one single user story, but binds the whole module's UX, per the source spec's explicit framing:

| ID | Requirement |
|---|---|
| FR-Constraint.1 | **No apply/quick-apply action exists anywhere in this module.** There is no application flow in the product at all yet (no module built so far implements one) — this module must not be the place where one gets casually introduced as a side effect of showing a vacancy feed. |
| FR-Constraint.2 | No application-count, streak, or "you've viewed N vacancies" gamification — the module's success signal is a strengthened profile (an `add_evidence`/probe action taken, per FR4.3), never volume of vacancies browsed or "applied to." |
| FR-Constraint.3 | Every vacancy detail view must lead with the profile-to-opportunity relationship (Match Score, breakdown, recommendation) — not a call-to-action styled around urgency or volume ("Apply now before it's gone!"). The tone throughout should read as "here's how your accumulated profile relates to this one opportunity," not "here's another listing to react to." |
| FR-Constraint.4 | Feed size in this MVP should stay deliberately small and curated (reflecting the hand-seeded `Vacancy[]` dataset, §2.2) rather than simulating a large-scale feed — a small, well-matched set demonstrates the "depth over volume" principle better than a padded one. |

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication:** same single implicit local session as Modules 2–9.
- **Static seed dataset, not a live pipeline:** `Vacancy[]` ships as version-controlled JSON, same convention as Module 3's `ReferenceProfile` and Module 5's `MirrorTaskScenario` — hand-curated to look like real, Filter-А/Б-processed postings, not literal scraped output.
- **Recompute-on-read for `MatchResult`:** consistent with Modules 3/4/6, given local-only data volumes — no caching/event pipeline needed yet.
- **Read-only boundary enforcement (FR2.3):** worth a code-review checklist item specifically, given how tempting it would be to "just quickly" let a bad vacancy match nudge a PROF.Index number — this must not be possible architecturally, not just avoided by convention.

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| Live Telegram/career-page parsing pipeline (Filters А/Б extraction from raw text) | Infrastructure/ops task (channel list curation, Telethon/Scrapy), not candidate-facing application logic — this module consumes pre-processed seed data instead. |
| Filter В (junk-vacancy detection) | [V2] — feed quality in MVP-0 relies on curated seed data instead. |
| Full AI Leverage Requirement scoring in Match Score, and its recruiter-confirmation loop | [V2] for scoring; the human-in-the-loop confirmation additionally needs a recruiter side that doesn't exist yet — this module only displays a pre-computed tag. |
| Vacancy-Specific Probe (new questions generated per-vacancy, with evidence accumulation feeding Match Score) | [V2] per Backlog #31's explicit resolution — this module's US4 only routes to existing mechanisms. |
| Automatic "new matching vacancy" push trigger | Already deferred to MVP-1 in Module 8; this module is pull-based browsing only. |
| Reverse Matching / Crowdsourced source discovery | [V2] — needs an accumulated verified-profile base this MVP doesn't have. |
| Fixed taxonomy of functional clusters for Role Breadth (Backlog #33) | Explicitly open in the source material — not a documentation gap here, a genuinely unresolved technical/product question. |

---

**H1 hypothesis this module feeds (per Ch.15's Cold Start framing, not a guarantee):**
- A curated, relevant vacancy feed gives candidates a reason to visit the platform even with zero recruiters present yet — the real test is whether candidates browse *and* act on a recommendation (close a gap) rather than just window-shop the feed, which would be the same "spray and forget" pattern this module is explicitly designed to avoid becoming.
