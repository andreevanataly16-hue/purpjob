# PurpJob — Module 15: Recruiter Plugin
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-1 — per the master document's own tag summary, Ch.19 is explicitly MVP-1 in its entirety, same sequencing tier as Modules 12–14]
**Phase:** Local prototype (no authentication layer — reuses the recruiter-mode session construct already established in Modules 12–14, just via a different entry surface: an embedded widget rather than a native dashboard)
**Depends on:** Module 3 (`PROFIndexSnapshot`), Module 6 (`TrustScoreSnapshot`), Module 10 (`Vacancy`/Filter Б requirement extraction — reused, not reinvented), Module 12 (candidate rendering for registered/verified candidates)
**Does not depend on / does not build:** Progressive Reveal (Module 13) — explicitly doesn't apply to this flow, see §5 FR4.4 for why

---

## 1. Purpose

This module is PurpJob's "parasite on someone else's infrastructure" growth mechanism, in the master document's own framing: instead of asking a recruiter to change their workflow, it drops PurpJob's analysis directly into the tool they're already using (hh.ru, LinkedIn, Habr Career, an ATS like Huntflow) — and the entry point into the recruiter side of the product isn't a sales conversation, it's a candidate's own PDF resume carrying an invitation.

**Hard constraint, stated directly in your framing and binding on every requirement below: the plugin must never automatically scrape a page.** MVP is manual text selection only. This isn't a temporary technical limitation to work around later — per the master document, it's the actual legal/reputational strategy: no auto-scraping means no risk of the recruiter's account being banned for violating a job board's terms of service, and no personal data leaves the browser without an explicit, single-purpose action.

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| P4 — Privacy/NDA respect | No text is sent to a server until the recruiter takes an explicit "Найти в базе" action; even then, only a hashed contact identifier is transmitted, never raw PII, until the candidate's own consent is established. |
| P1 — Evidence-Based Hiring | The "Честный светофор" (Honest Traffic Light) exists specifically to prevent a text-based guess from ever being mistaken for a real, evidence-backed PROF.Index (US4). |
| Automation, without violating platform ToS | Structured analysis replaces manual resume-reading (US1/US2), but the *mechanism* of getting the text stays manual and recruiter-initiated, by design. |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- **Manual text capture only**: `window.getSelection`-based manual highlighting, plus an optional one-click PDF download path where a page already exposes a direct download button (US1)
- **100% client-side express analysis** of captured text: a generic (non-personal-baseline) AI-text-likelihood heuristic, logical date-consistency checks, and a fact-density ratio — computed locally, never sent to a server at this stage (US1)
- **Vacancy requirement extraction**, reusing Module 10's existing Filter Б logic/schema applied to ad-hoc pasted text instead of the parsed vacancy feed, plus a lightweight "what kind of Evidence would verify this" hint per requirement (US2)
- **Verification invite generation**: a unique link the recruiter must manually copy and send through their own channel — no automatic dispatch (US3)
- **Widget overlay** (conceptually a Shadow-DOM-style injected panel) showing the "Честный светофор" three-tier trust status, reusing Module 12's existing candidate-rendering for genuinely registered/verified candidates (US4)
- **"Найти в базе" (Matching API) lookup**: the one explicit action that transmits anything to a server — a hashed contact identifier only, to check registration status

### 2.2 Out of scope (explicitly deferred)
- Any form of automatic page scraping/DOM-reading beyond what the recruiter has manually selected and explicitly triggered the plugin on — not a missing feature, a **hard prohibition** stated directly in your framing
- Full automated candidate outreach/Reverse Matching — [V2], unrelated to this manual, recruiter-initiated flow
- The actual browser-extension packaging/Shadow DOM engineering (manifest, content-script injection mechanics) — an implementation detail of *how* the widget gets onto the page, not a functional requirement this FRD needs to specify
- Recruiter subscription/trial-period billing logic ("пробный период" as a commercial concept) — Ch.11 concern; this FRD only reuses the *name* "Вариант А" for the underlying matching mechanic (Filter Б applied to pasted text), not any pricing/trial-limit logic
- Module 6's personal-baseline Authenticity detector (comparison against a registered candidate's own Raw Input) — doesn't apply here; an unregistered candidate whose resume was just pasted has no baseline to compare against, hence the need for a separate, necessarily less precise, generic heuristic (§4.2)
- Progressive Reveal (Module 13) — see §5, FR4.4 for the explicit reasoning on why this module doesn't apply it

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values (`verified`, `preliminary`, `needs_verification`, `date_overlap`) | English |
| All UI copy | **Russian**, matching the register already established across Modules 2–14, plus the specific copy already drafted for this exact feature in the source material |

Reuse existing drafted copy verbatim — this module has more pre-written UI text than most in this series, don't rephrase it:
- Traffic-light card pattern: *"🔍 PROF.индекс: 85/100 (Предварительный — на основе резюме) Для точной оценки запросите верификацию у кандидата → [Запросить кейс]"*
- Tier descriptions: **Верифицирован** (green) — *"Кандидат прошел микро-кейсы, артефакты проверены. Максимальное доверие"*; **Предварительный** (yellow) — *"Кандидат не проходил верификацию. Это оценка текста, а не доказательство. Рекрутер видит, что цифра может измениться"*; **Требует верификации** (grey) — *"Кандидат не зарегистрирован"*, showing only basic risk flags.
- Key framing line (must ship exactly, it's the module's own stated ethical position): *"Мы не обманываем рекрутера. Мы даем честную оценку с указанием степени достоверности."*
- Plugin-as-lens framing (useful as an internal design principle as much as UI copy): *"Плагин — это не «шпион». Это «линза», через которую рекрутер видит больше информации, но только с согласия кандидата."*

---

## 4. Data Model

Local-first, consistent with Modules 2–14 — with the added nuance that "local" here means the recruiter's own browser session for the client-side analysis (§4.2), distinct from the local prototype's usual single-candidate-session framing.

### 4.1 `PastedContent`
```json
{
  "id": "pc_001",
  "content_type": "vacancy | resume",
  "raw_text": "string",
  "captured_via": "manual_selection | pdf_one_click",
  "captured_at": "ISO8601"
}
```
- `raw_text` exists **only in the recruiter's local browser session** at this stage — nothing here is transmitted anywhere until an explicit `MatchingLookup` action (§4.4).
- `captured_via: "manual_selection"` is the primary, required path (`window.getSelection`); `"pdf_one_click"` is a secondary convenience path for pages that already expose a direct download button — both are recruiter-triggered, never automatic.

### 4.2 `ResumeExpressAnalysis` (US1 — new, generic, non-personal-baseline detector)
```json
{
  "pasted_content_id": "pc_002",
  "ai_text_likelihood_pct": 70,
  "logical_anomalies": [
    { "type": "date_overlap", "description_ru": "Указано 3 года работы в компании, зарегистрированной 2 года назад." }
  ],
  "fact_density_score": 0.4,
  "computed_locally": true
}
```
- **This is explicitly distinct from Module 6's Authenticity component** (§2.2) — it has no candidate-specific Raw Input baseline to compare against, since it may run against a completely unregistered person's pasted resume text. It's a cruder, generic heuristic (population-level stylometric expectations, not personal ones), and must be labeled to the recruiter as such — never presented with the same confidence framing as Module 6's real Authenticity score.
- `logical_anomalies.type: "date_overlap"` reuses the same *concept* Module 6 established for local Consistency checks (§5.1 there), applied here to raw unstructured text instead of a registered candidate's structured `Statement` data — same idea, different, necessarily less precise input.

### 4.3 `VacancyRequirementExtraction` (US2, reuses Module 10 Filter Б)
```json
{
  "pasted_content_id": "pc_001",
  "requirements": [
    { "label_ru": "Опыт с ClickHouse", "criticality": "mandatory | nice_to_have", "evidence_hint_ru": "Ссылка на репозиторий или описание кейса с этим стеком" }
  ]
}
```
- Directly reuses Module 10's `Vacancy.requirements` extraction logic and shape (§4.1 there) — this module is a second entry point into the same Filter Б mechanism, applied to ad-hoc pasted text rather than the parsed seed feed, not a parallel extraction implementation.
- `evidence_hint_ru` is new to this module: a short, generic suggestion of what kind of Evidence (per Module 2's existing type taxonomy — link, file, case description) would verify that specific requirement, shown to the recruiter as guidance, not generated as a live probe question (no Contextual Probe is triggered from within the plugin itself).

### 4.4 `MatchingLookup` (US4, the one point where anything reaches a server)
```json
{
  "pasted_content_id": "pc_002",
  "contact_hash": "sha256:...",
  "result": "registered_verified | not_registered",
  "candidate_id": "cand_001 | null"
}
```
- `contact_hash` (name + email, hashed) is the **only** data this module ever transmits before candidate consent is otherwise established — never the raw resume text, never unhashed contact details, consistent with the source material's own explicit safety table.
- If `result: "registered_verified"`, `candidate_id` links directly into Module 12's existing `CandidateProfile` rendering — this module does not re-implement PROF/Trust display, it reuses Module 12's exactly as built.

### 4.5 `VerificationInvite` (US3)
```json
{
  "id": "inv_001",
  "invite_link": "string",
  "created_by_recruiter_session_id": "string",
  "related_pasted_content_id": "pc_002 | null",
  "status": "generated | opened | completed",
  "created_at": "ISO8601"
}
```
- **Hard constraint, reused from Module 9's US4 principle, now applied recruiter-side:** no code path in this module sends this invite anywhere automatically. The recruiter copies the generated message/link themselves and pastes it into their own channel (ATS, messenger, email) — same "candidate/recruiter always sends themselves, the platform never distributes on their behalf" rule already established for candidate-side export.
- A candidate arriving via this link enters Module 2's standard onboarding flow, tagged with this invite as a referrer — this module introduces a new entry point, not a new onboarding path.

---

## 5. Functional Requirements

### US1 — Paste or select vacancy/resume text and get structured analysis without switching services

| ID | Requirement |
|---|---|
| FR1.1 | The **only** way text enters this module is manual: the recruiter highlights text on a page (`window.getSelection`) or clicks an explicit "download PDF" affordance already present on that page. **There is no automatic reading of page content the recruiter hasn't explicitly selected or clicked to capture.** This is a hard, non-negotiable constraint per your own framing, not a "nice to have for legal safety." |
| FR1.2 | `ResumeExpressAnalysis` (§4.2) runs entirely client-side, in the recruiter's own browser — `raw_text` is not transmitted to any PurpJob server for this analysis. This is the architectural cornerstone of the "no auto-scraping, no unconsented PII transfer" legal position and must be verifiable in code (no network call in this code path), not just asserted in the privacy copy. |
| FR1.3 | Results (AI-text-likelihood, date-logic anomalies, fact-density) render inline via the widget overlay on the **same page** the recruiter is already on — satisfying "no switching between services" directly; there is no required navigation to a separate PurpJob tab for this base level of analysis. |
| FR1.4 | This module's analysis is explicitly generic/population-level, not personalized — it must never be presented with the same visual confidence as Module 6's real, personal-baseline Authenticity score (§4.2, hard labeling requirement). |

**Acceptance criteria:** a recruiter can highlight resume or vacancy text on any supported page, see structured local analysis appear inline within seconds, with zero network transmission of the raw text and zero tab-switching required.

---

### US2 — See which vacancy requirements are key and what Evidence would verify them

| ID | Requirement |
|---|---|
| FR2.1 | When `PastedContent.content_type == "vacancy"`, run Module 10's existing Filter Б extraction against the pasted text, producing the same `requirements[]` shape (label, `criticality`) already established there — this module does not build a second, divergent extraction engine. |
| FR2.2 | Each extracted requirement is shown with a short `evidence_hint_ru` (§4.3) suggesting what kind of Evidence (link, file, case description — Module 2's existing taxonomy) would verify it — generic guidance, not a generated live question; this module never triggers Module 4's Contextual Probe directly from within the plugin context. |
| FR2.3 | Requirements are visually prioritized by `criticality` (`mandatory` before `nice_to_have`) — same convention already established for White Spots/Match recommendations (Modules 3/8/10), not a new ranking rule. |

**Acceptance criteria:** pasting a vacancy's text produces a structured, prioritized requirement list, each with a concrete hint about what evidence would confirm it — replacing the recruiter's own manual re-reading of the posting to figure this out themselves.

---

### US3 — Send a candidate an invitation to verify their profile on PurpJob

| ID | Requirement |
|---|---|
| FR3.1 | The recruiter can generate a `VerificationInvite` (§4.5) for a candidate — whether reached via a "not registered" `MatchingLookup` result or simply from a pasted resume with no lookup performed at all. |
| FR3.2 | **Hard constraint:** generating the invite never sends it anywhere — the recruiter must copy the provided message/link and paste it into their own communication channel of choice. No email/SMS/ATS-message auto-dispatch exists in this module, mirroring Module 9's export-side rule exactly. |
| FR3.3 | A candidate who arrives via this link goes through the standard Module 2 onboarding (One-Click Enrichment) — this module supplies a new referrer/entry point, not a different or shortened verification path; the candidate still builds a real, evidence-backed profile the normal way. |

**Acceptance criteria:** a recruiter can generate an invite link for any candidate they've encountered through this plugin, and the only way that invite reaches the candidate is through the recruiter's own manual action — never an automatic send by PurpJob.

---

### US4 — Use PurpJob's result directly inside an existing workflow

| ID | Requirement |
|---|---|
| FR4.1 | The widget overlay renders the **Честный светофор** (Honest Traffic Light) inline on the recruiter's current page, in exactly three states: **Верифицирован** (green, real `PROFIndexSnapshot`/`TrustScoreSnapshot` via Module 3/6, reusing Module 12's rendering), **Предварительный** (yellow, this module's own text-based estimate, §4.2, always captioned *"на основе резюме"*), **Требует верификации** (grey, no numeric estimate, only local risk flags plus the invite CTA, US3). |
| FR4.2 | **"Найти в базе" is the single explicit action that transmits anything to a server** (`MatchingLookup`, §4.4) — a hashed contact identifier only. Before this click, everything is local/client-side (US1). After this click: **Scenario A** (registered) pulls the candidate's real, verified data via Module 12's existing rendering — green tier; **Scenario B** (not registered) transmits nothing further and falls back to the yellow/grey local-analysis display plus the invite CTA. |
| FR4.3 | For a green-tier (verified) candidate, the widget also surfaces the *"Артефакты и подтверждения"* block — direct links to the candidate's actual confirmed Evidence (Module 2), reusing that data as-is, not summarizing or reprocessing it. |
| FR4.4 | **Module 13's Progressive Reveal does not apply to this module, and this is deliberate, not an oversight:** Progressive Reveal exists to prevent identity (name/photo) from biasing an *initial, anonymous* screening step (Module 12's native search flow). In this plugin's flow, the recruiter is, by construction, already looking at a specific, named resume/profile on an external site *before* the plugin ever activates — there is no anonymous screening moment to protect here. Forcing a staged-anonymization state onto an already-identified person would be both meaningless and confusing; do not attempt it. |

**Acceptance criteria:** the widget shows the correct one of three honest trust tiers inline on the page the recruiter is already using, with real verified data reused unmodified from Module 12 for registered candidates, and no attempt to apply Progressive Reveal's staged-anonymity logic anywhere in this flow.

---

## 6. Cross-cutting privacy/legal constraints (binding across all four user stories)

| ID | Requirement |
|---|---|
| FR-Priv.1 | No automatic scraping, ever — every piece of text this module analyzes was explicitly selected or explicitly downloaded by the recruiter's own action. |
| FR-Priv.2 | No PII leaves the recruiter's browser before the explicit "Найти в базе" action, and even then, only a hashed contact identifier — never raw resume text, never unhashed name/email. |
| FR-Priv.3 | No data is retained by PurpJob for candidates a recruiter merely browses without clicking "Найти в базе" — browsing-only sessions leave no server-side trace. |
| FR-Priv.4 | A candidate only ever enters PurpJob's system voluntarily, via their own click on an invite link (US3) — this module never registers or creates a profile on a candidate's behalf. |

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication:** reuses the recruiter-mode session construct already established in Modules 12–14 — same local, non-production-safe pattern, just accessed through an embedded widget rather than a native dashboard screen.
- **Client-side-only analysis boundary (FR1.2) deserves explicit code-review attention:** given how easy it would be to "just quickly" send the pasted text to a server for a better-quality analysis, this boundary should be enforced architecturally (e.g., the express-analysis module simply has no network client available to it), not left as a convention that's easy to accidentally violate later.
- **Reuse, don't re-implement:** Filter Б extraction (Module 10) and candidate rendering for verified candidates (Module 12) must be called as existing capabilities, not reimplemented inside this module's codebase — this module is fundamentally a new *entry surface* into already-built logic, plus one genuinely new capability (the generic express-analysis heuristic, §4.2).

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| Actual Shadow DOM/browser-extension packaging | Implementation detail of *how* the widget gets onto the page, not a functional requirement. |
| Full Reverse Matching / automated outreach | [V2], unrelated to this manual flow. |
| Recruiter subscription/trial-period billing ("пробный период" as a commercial term) | Ch.11 concern — this FRD reuses only the underlying matching mechanic's name, not any pricing logic. |
| Exact thresholds for the yellow-tier `ai_text_likelihood_pct` and what counts as a reportable date anomaly | Calibration-pending, same convention as every other placeholder constant in this series — do not present illustrative percentages as validated. |
| Whether `evidence_hint_ru` guidance should eventually link into a live Contextual Probe from within the plugin itself | Plausible future enhancement, explicitly not built now (FR2.2) — the plugin points the recruiter toward inviting the candidate to the full platform instead. |

---

**Business-value hypothesis this module feeds (per the master document's own framing, not a guarantee):**
- Each "Запросить верификацию" invite is a new candidate entering PurpJob's base through a recruiter-initiated channel, at near-zero CAC for the candidate side — the real test is whether recruiters actually click "Найти в базе"/generate invites often enough, and whether a meaningful share of those invited candidates complete verification, to make this a genuine second growth channel alongside the candidate-initiated Cold Start drivers already tested in earlier modules.
