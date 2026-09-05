# PurpJob — Module 12: Recruiter Profile / Candidate View
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-1, not MVP-0 — see §0]
**Phase:** Local prototype (no authentication layer, no persistent multi-tenant backend — see §0/§7 for how a second persona is handled here)
**Depends on:** Module 3 (`PROFIndexSnapshot`), Module 6 (`TrustScoreSnapshot`), Module 7 (canonical `Explanation`, `candidate_consent_for_recruiter_view` — now actually consumed, not just reserved), Module 10 (`Vacancy`, `MatchResult`)
**This module builds no new scoring engine** — it's the first module in this series to render already-existing candidate-side data to a second persona, with the privacy/consent gates that implies.

---

## ⚠️ 0. Sequencing and scope note — read before estimating this

**You already flagged the right instinct in your own framing: this module should be built only after the candidate core is validated, not alongside it.** This isn't just a project-management preference — it matches what the master document itself says explicitly about MVP-0's actual scope: *"все компоненты MVP-0 - без единого recruiter-facing элемента, кроме пассивного приглашения в PDF"* (Module 9). Every one of the previous 11 modules was deliberately built around **not** needing a recruiter side to exist. This module is the first one that genuinely can't avoid it — it's the first crossing from "local, single-candidate-session prototype" into "second side of a marketplace."

**Three things this module is explicitly *not*, so it doesn't get conflated with similarly-named features already documented elsewhere:**

| This is not... | Why |
|---|---|
| The Ch.19 browser plugin (Shadow DOM injection onto hh.ru/LinkedIn/Habr Career, Copy-Paste Assist, "Honest Traffic Light" for *unregistered* candidates) | That's a different surface entirely (a browser extension overlaying third-party sites) for a different audience (candidates not yet in PurpJob's database at all). Per the master document's own tag summary, Ch.19 is **MVP-1 in its entirety**. This module is a native, in-platform recruiter view over candidates **already** fully registered and verified in PurpJob — a materially simpler, narrower thing. |
| Reverse Matching (Ch.15, [V2]) | Reverse Matching is described as an *automated, proactive outreach* mechanism — the system contacting candidates on the recruiter's behalf when a new vacancy is parsed. US1 here ("find candidates without manually reading dozens of resumes") is satisfied by a **recruiter-initiated, manual search/filter/rank** interface using Module 10's already-existing single-direction Match computation, run once per candidate in a pool — not an automated distribution engine. Don't build the V2 mechanism under this module's name. |
| A full recruiter accounts/subscription/monetization system | Ch.11's SaaS/Pay-per-Verified-Match business model is a separate concern; this FRD only needs a way to *represent* a recruiter using the product, not bill them. |

**Given there's no recruiter-side auth or multi-candidate backend anywhere in this series, this FRD applies the same pattern already established for Module 7's moderator role**: a distinct local UI mode, not a real login, explicitly flagged as not production-safe (§7). And since a real candidate pool doesn't exist yet either, this FRD applies the same pattern already established for Modules 3/5/10's reference content: **a small, hand-seeded pool of synthetic `CandidateProfile` records**, each internally consistent with the exact data shapes Modules 2/3/6/7 already define — enough to build and demo real search/filter/compare logic without needing actual registered candidates.

---

## 1. Purpose

This module answers the recruiter's version of the question Trust Score already answers for the candidate: not "read this candidate's story and judge it yourself," but "here is a structured, evidence-backed, comparable view of what's actually confirmed." It exists to replace manually reading dozens of resumes with a structured search over already-verified data — but it must not become a black-box ranking either; every principle already built candidate-side (XAI, non-punitive framing, factual explanation) applies just as strictly when the audience is a recruiter.

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| P1 — Evidence-Based Hiring | The recruiter sees the same evidence-backed structure the candidate does, not a re-summarized "recruiter-friendly" simplification that loses the underlying facts. |
| XAI, both directions, with candidate consent (Ch.9) | This is the module where Module 7's `candidate_consent_for_recruiter_view` field — reserved but unused until now — actually gets enforced (US3). |
| P4 — Privacy/NDA respect | Only candidates who have opted into `visible` (Module 3) ever appear here at all; declined findings (Module 6) never surface here under any circumstance. |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- Recruiter-side search: select a `Vacancy` (Module 10) as criteria, rank/filter candidates from a seed pool by `MatchResult.overall_match_score`, with basic filters (segment, level, minimum Trust Score) (US1)
- Candidate detail view for the recruiter: `PROFIndexSnapshot` + `MatchResult` breakdown against the selected vacancy (US2)
- Trust Score display with its canonical `Explanation`, gated by candidate consent (US3)
- Per-competency and per-requirement status breakdown (confirmed vs. needs-further-verification), never collapsed into a single opaque score (US4)
- Side-by-side candidate comparison using one identical data structure across candidates (US5)
- A seed pool of synthetic `CandidateProfile` records for local demoability (§0)
- Local, non-authenticated "recruiter mode" toggle, same pattern as Module 7's moderator mode

### 2.2 Out of scope (explicitly deferred)
- The Ch.19 browser plugin, its widget, Copy-Paste Assist, and "Honest Traffic Light" express-analysis for unregistered candidates — different surface, different audience, MVP-1 in its own right, not this module
- Reverse Matching / automated candidate outreach — [V2], this module is manual search only
- Real recruiter authentication, accounts, or multi-tenant candidate data access — local mode-switch only (§7), not production-safe
- Ad-hoc free-text requirement search not tied to an existing `Vacancy` record — a plausible enhancement, but this MVP scopes search to "pick a vacancy from Module 10's set," not a fully custom query builder
- Recruiter subscription/billing/entitlement gating — Ch.11 business-model concern, separate from this FRD
- Any candidate-outreach action initiated by the recruiter through this module (messaging, inviting to interview) — no such flow exists in this product yet, and this module doesn't introduce one

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values | English |
| All UI copy: search filters, candidate cards, comparison table headers | **Russian**, matching the register already established across Modules 2–11 |

Recruiter-facing copy has no established precedent yet in this product (this is the first recruiter-facing screen in the whole series) — author it in a clear, professional, evidence-anchored register, distinct from the candidate-facing warmth already established, but held to the exact same factual-explanation standard (§4.3 of Module 6, reused verbatim as the house style): never *"слабый кандидат"*, always something like *"не хватает независимого подтверждения по ClickHouse."*

---

## 4. Data Model

Local-first constraint, consistent with Modules 2–11, extended to a second persona. This module reads a seed `CandidateProfile[]` pool (each internally shaped exactly like a real candidate's Module 2/3/6/7 data would be) and Module 10's `Vacancy`/`MatchResult`; it writes only its own `SearchQuery`/session state, no candidate-side data.

### 4.1 `CandidateProfile` (seed data for this phase — see §0)
```json
{
  "id": "cand_001",
  "display_name": "string",
  "visibility_state": { "mode": "visible | hidden" },
  "prof_index_snapshots": [ "PROFIndexSnapshot per Module 3 §4.3" ],
  "trust_score_snapshot": "TrustScoreSnapshot per Module 6 §4.1",
  "consent_for_recruiter_view": true,
  "statements": [ "Statement[] per Module 2" ],
  "evidence": [ "Evidence[] per Module 2" ]
}
```
- **Hard gate, enforced at the data-read layer, not just the UI:** any `CandidateProfile` with `visibility_state.mode: "hidden"` must be structurally unreachable through this module's search/detail/comparison views — not filtered out cosmetically after being loaded, but never fetched into a recruiter-facing result set in the first place. Get this wrong once and the whole Self-Audit privacy guarantee from Module 3 is broken.
- `consent_for_recruiter_view` is the field Module 7 defined and left unused (§2.2 there) — this module is its first real consumer (§5, US3).
- Declined `AttributionFinding`s (Module 6 §4.3, Case 1) must never be included in this seed shape at all for `hidden`-equivalent reasoning — per Module 6's own rule, a declined finding "leaves no trace anywhere, including a future recruiter view." Enforce this by construction: the seed data generator (and, later, the real data layer) must never surface a declined finding's content into anything this module reads.

### 4.2 `SearchQuery`
```json
{
  "vacancy_id": "vac_001",
  "filters": { "min_trust_score": 50, "segment": "Backend/Fullstack (Python/Go)", "level": "Middle" },
  "sort_by": "match_score | trust_score | prof_index"
}
```
- `vacancy_id` is required in this MVP (§2.2 — no free-text ad-hoc query builder yet).

### 4.3 `SearchResult`
```json
{
  "candidate_id": "cand_001",
  "match_result": "MatchResult per Module 10 §4.2, computed against vacancy_id",
  "prof_index_summary": { "overall_score": 74 },
  "trust_score_summary": { "overall_score": 65 }
}
```
- Computed fresh per query (recompute-on-read, same convention as every prior module) — never cached against a stale candidate state.

---

## 5. Functional Requirements

### US1 — Find candidates matching vacancy requirements without manually reading dozens of resumes

| ID | Requirement |
|---|---|
| FR1.1 | Recruiter selects an existing `Vacancy` (Module 10) as search criteria — no separate requirement-authoring step in this module; it reuses the vacancy data Module 10 already structures. |
| FR1.2 | The system computes `MatchResult` (Module 10's existing, unmodified engine) for every `CandidateProfile` in the pool whose `visibility_state.mode == "visible"` — this is a manual, recruiter-triggered search over an already-existing pool, **not** an automated outreach/notification engine (that's Reverse Matching, explicitly deferred, §0). |
| FR1.3 | Results are ranked by `overall_match_score` descending by default, with basic filters (`min_trust_score`, `segment`, `level`) available to narrow the list — this is what actually replaces "reading dozens of resumes manually": a structured, sortable, evidence-backed list instead of an unstructured pile of documents. |
| FR1.4 | No candidate below the `visible` visibility gate ever appears in a result set, regardless of how well they'd score — there is no "show hidden candidates anyway for research purposes" override anywhere in this module. |

**Acceptance criteria:** selecting a vacancy returns a ranked, filterable list of only `visible`-mode candidates, with no manual resume-reading required to establish the initial ranking.

---

### US2 — See a candidate's PROF and their fit to the vacancy's requirements

| ID | Requirement |
|---|---|
| FR2.1 | Opening a candidate from the search results shows their current `PROFIndexSnapshot` (Module 3, including the radar breakdown already established there) alongside the `MatchResult` computed against the selected vacancy (Module 10) — the same two views the candidate themselves would see, not a recruiter-specific simplification that drops detail. |
| FR2.2 | This view reflects the candidate's **current, live** state — including any Module 7 moderator override already applied — never a stale or pre-correction number; there is exactly one truth for a given competency's status, and it's whatever the candidate-side modules currently say it is. |
| FR2.3 | This detail view is reachable only for `visible`-mode candidates — same hard gate as FR1.4, enforced again here, not assumed to already be handled by the search step alone (defense in depth, given this is a privacy-critical boundary). |

**Acceptance criteria:** for any candidate reached through search, the recruiter sees the same PROF.Index and Match breakdown data the candidate sees about themselves, current and correct as of the moment of viewing.

---

### US3 — See Trust Score together with an explanation of the Evidence that formed it

| ID | Requirement |
|---|---|
| FR3.1 | The candidate's `TrustScoreSnapshot.overall_score` and its per-component breakdown (Module 6) are shown, each carrying its canonical `Explanation` (Module 7) — never a bare number. |
| FR3.2 | **Consent gate (this is the actual, first real use of Module 7's `candidate_consent_for_recruiter_view` field):** if `consent_for_recruiter_view` is `true`, the recruiter can drill down to the specific `evidence_refs` behind each component, same as the candidate's own Module 7 US2 experience. If `false`, the recruiter sees the component scores and their factual `conclusion_ru` text, but **not** the underlying raw Evidence content/links — summary-level transparency, not full drill-down, until the candidate has explicitly agreed to that level of exposure. |
| FR3.3 | **Hard carry-over rule from Module 6, non-negotiable:** any declined `AttributionFinding` (Case 1) never appears here under any circumstance, regardless of `consent_for_recruiter_view` — that field governs *how much detail* is shown about confirmed evidence, it never overrides the separate, absolute "declined findings leave no trace" rule. |
| FR3.4 | NDA-sourced Evidence (`Evidence.nda: true`, Module 5) is shown with the same weight and no lesser visual treatment than any other Evidence — displayed with a neutral "подтверждено через альтернативный метод (NDA)" indicator, not flagged as suspicious or incomplete. |

**Acceptance criteria:** Trust Score is never shown without its component explanations; full Evidence drill-down is available only where the candidate has explicitly consented; declined findings never appear regardless of consent state.

---

### US4 — See specific confirmed areas and areas needing further verification, not just a final score

| ID | Requirement |
|---|---|
| FR4.1 | The candidate view must show **both** Module 3's per-competency breakdown (confirmed/`medium`/`strong` vs. White Spot) **and** Module 10's per-requirement breakdown for the selected vacancy (covered/uncovered/unevaluated) — never collapsed down to just `overall_score`/`overall_match_score` with no supporting detail. |
| FR4.2 | Every item in either breakdown uses the exact same factual, non-verdict register already established throughout this series (Modules 3/6/7/10) — *"требует дополнительной проверки"*, never *"слабое место"* or any language implying a final judgment about the candidate rather than a statement about current evidence. |
| FR4.3 | Unevaluated Role-Breadth clusters (Module 10 FR2.4) must be shown to the recruiter with the same explicit "not evaluated by the platform" framing used candidate-side — a recruiter must never mistake "not evaluated" for "confirmed absent." |

**Acceptance criteria:** for any candidate, the recruiter can identify specifically which requirements/competencies are confirmed and which need further verification, with no single aggregate number standing in for that detail.

---

### US5 — Compare candidates using the same structured data

| ID | Requirement |
|---|---|
| FR5.1 | The recruiter can select multiple candidates from a search result (all already `visible`-gated) and view them side-by-side using **one identical column structure** — PROF.Index overall score, Trust Score overall + component scores, Match Score against the selected vacancy, and top covered/uncovered requirements — the same fields in the same order for every candidate, no candidate-specific custom fields that would break comparability. |
| FR5.2 | The comparison view must include the confirmed-vs-needs-verification breakdown (US4) per candidate, not only the aggregate scores — a comparison of bare numbers alone would recreate exactly the opaque, unexplainable ranking this whole product's XAI principle exists to prevent. |
| FR5.3 | Comparison is scoped to candidates already surfaced through a `visible`-gated search (FR1.2/FR1.4) — this view introduces no separate path to reach a `hidden` candidate's data. |

**Acceptance criteria:** selecting any set of candidates from search results produces a side-by-side table with identical structure and the same level of factual detail as each candidate's individual detail view, not a stripped-down summary-only comparison.

---

## 6. Cross-cutting privacy/consent constraints (binding across all five user stories)

| ID | Requirement |
|---|---|
| FR-Priv.1 | `visibility_state.mode == "visible"` is a hard, structural gate on every read path in this module (search, detail, comparison) — enforce at the data-access layer, not as a UI filter applied after the fact. |
| FR-Priv.2 | `consent_for_recruiter_view` governs *depth of Evidence detail* only (full drill-down vs. summary-level) — it never governs whether a `hidden` candidate becomes visible; these are two independent gates, not one setting standing in for both. |
| FR-Priv.3 | Declined `AttributionFinding`s are absolutely excluded from recruiter-facing data, independent of both gates above — this is the strictest of the three rules and must never be relaxed by either visibility or consent settings. |

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication, including for the recruiter role:** same pattern already established for Module 7's moderator role — a distinct local UI mode (a mode toggle), not a real login. **Explicitly flagged as not production-safe**: real recruiter accounts, company-level access control, and audit of who searched/viewed which candidates are all required before any multi-user deployment — none of that exists here.
- **Seed `CandidateProfile` pool:** version-controlled JSON, same convention as Module 3's `ReferenceProfile`, Module 5's `MirrorTaskScenario`, and Module 10's `Vacancy` — hand-authored to be internally consistent with the real schemas those modules define, not a database of real people.
- **Privacy gates enforced in code, not just UI:** given this is the first module where a genuine privacy boundary (candidate vs. recruiter) exists in this whole series, the `visible`/consent/declined-finding rules (§6) deserve an explicit code-review checklist item and, ideally, tests — this is a materially higher-stakes category of bug than anything in the candidate-only modules so far.

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| Real recruiter authentication/accounts/company-level access control | Local mode-switch only in this phase, explicitly not production-safe. |
| Ch.19 browser plugin, widget, Honest Traffic Light, "Запросить верификацию" | Different surface/audience, MVP-1 in its own right — not this module. |
| Reverse Matching (automated candidate outreach) | [V2] — this module is manual, recruiter-initiated search only. |
| Free-text/ad-hoc requirement search not tied to an existing `Vacancy` | Plausible enhancement, not in this MVP's scope. |
| Exact granularity of `consent_for_recruiter_view` (all-or-nothing vs. per-component) | This FRD assumes a single profile-level boolean gating full drill-down; the master document doesn't fully specify the granularity — confirm before building if a finer-grained consent model is actually intended. |
| Recruiter subscription/billing/entitlement | Ch.11 concern, separate from this FRD entirely. |

---

**H3 hypothesis this module feeds (per the master document's own hypothesis ordering, not a guarantee — and notably, the one this whole module exists to test):**
- Recruiters use Trust Score/PROF.Index as an actual basis for candidate decisions and/or reduce redundant re-verification effort, compared to reading raw resumes — this is explicitly the hypothesis the master document says can't be tested until *after* H1a/H1b (candidate activation and compounding) are validated, which is exactly why this module belongs at the end of the sequence, matching your own instinct at the top of this request.
