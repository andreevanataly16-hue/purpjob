# PurpJob — Module 2: One-Click Enrichment & Evidence
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-0]
**Phase:** Local prototype (no authentication layer, no persistent backend, single local candidate session)
**Depends on:** Module 1 (Profile core / PROF.Index shell)
**Feeds into:** Module 3 (Contextual Probe engine — required for full Mirror Task support), Module 5 (Trust Score calculation)

---

## 1. Purpose

This module is the candidate-side intake and evidence layer. It replaces the "empty form" onboarding pattern with a lazy-entry, evidence-first model: the candidate declares as little as possible manually, and every substantive claim in the profile becomes traceable to a concrete, falsifiable source.

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| P1 — Evidence-Based Hiring | No competency is trusted on text alone; every Statement must carry an Evidence link or be explicitly marked unconfirmed. |
| P2 — Automation / Logic over Memory | Free-text and file input is parsed by AI into structured competencies; candidate edits, doesn't build from scratch. |
| P4 — Privacy / NDA respect | Blind Witness flow + right-to-decline let the candidate confirm expertise without disclosing confidential artifacts. |
| P5 — Dynamic Trust | Evidence status (Not started / Limited / Medium / Strong) feeds Trust Score in Module 5; this module only computes the status, not the score itself. |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- Manual addition of links to public professional sources (US1)
- File upload as evidence artifact (US1)
- Free-text project/case description parsed into structured competencies (US2)
- Statement ↔ Evidence traceability model and its UI surface ("Evidence Map") (US3)
- NDA flag per evidence/statement + right to decline disclosure of a specific fact/source (US4)
- Blind Witness structured-question flow as an NDA-safe evidence substitute (US4)
- Local persistence only (no user accounts, no server-side auth)

### 2.2 Out of scope (explicitly deferred)
- OAuth / direct API pull from GitHub, GitLab, LinkedIn (tagged [V2] in master doc — this MVP only accepts a pasted URL, not a live integration)
- Mirror Tasks execution (requires the Contextual Probe question-generation engine — Module 3; this module only stores the *result* of a Mirror Task as an Evidence item if/when Module 3 exists)
- Digital Echo cross-verification against public footprint (Module 9 / XAI)
- Trust Score numeric calculation (Module 5 consumes this module's output, doesn't live here)
- Any authentication, session persistence across devices, or multi-user storage

---

## 3. Localization

**This FRD is written in English for development purposes only. The candidate-facing product is Russian-first.**

| Layer | Language |
|---|---|
| Code: variable/field/entity names, `status` enum values (`not_started`, `limited`, `medium`, `strong`, `pending`, `confirmed`, `declined`, etc.), API/JSON keys | English (as specified in this document) |
| All UI copy: labels, prompts, buttons, hints, error messages, AI-generated explanations shown to candidate, Blind Witness questions, status "why" strings (FR3.4) | **Russian** — must match tone/register already used in `purpjob-wireframe-v3.jsx` (informal-professional "вы", no calques from this document's English phrasing) |
| AI parsing step (FR2.2) | Input text from candidate will be Russian; extraction/parsing prompt and output labels shown to candidate must be Russian. Internal `skill_name` values may be stored in English (canonical taxonomy) with a Russian display label, or stored directly in Russian — pick one convention before implementation and apply it consistently across all `Statement.skill_name` values (recommendation: store canonical English taxonomy key for future matching against the reference competency library, `Гл. 5`, plus a `skill_name_ru` display field). |
| Status explanation strings (FR3.4 example: *"Medium — Contextual Probe passed, no independent source connected yet"*) | Example given in English in this doc for spec clarity only. Shipped copy must read like the existing wireframe pattern, e.g. *"Подтверждено на основе Contextual Probe. Добавление независимого источника повысит статус до Strong"*. |

**Rule for implementation:** treat every UI string in this FRD as a placeholder for the underlying logic, not as copy to ship. Do not translate literally — reuse existing Russian strings from `purpjob-wireframe-v3.jsx` wherever an equivalent screen/state already exists there, and write new strings in the same register for new states (e.g. the Blind Witness screen, §5 gap).

---

## 4. Data Model

Local-first constraint: no backend DB in this phase. Persist as a single local JSON document (e.g. `localStorage` in a web prototype, or a flat JSON file if server-rendered) representing one candidate session. Schema below is storage-agnostic and should carry over unchanged once auth/DB is added.

### 3.1 `Statement` (competency claim)
```json
{
  "id": "stmt_001",
  "skill_name": "REST API design",
  "category": "Hard Skill | Practical Understanding | Professional Footprint | Complexity of Solved Tasks",
  "source_of_claim": "resume | free_text | manual",
  "status": "not_started | limited | medium | strong",
  "evidence_ids": ["ev_003", "ev_007"],
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

### 3.2 `Evidence`
```json
{
  "id": "ev_003",
  "type": "link | file | free_text | blind_witness_answer",
  "source_category": "github | gitlab | linkedin | portfolio | article | video | other",
  "url": "string | null",
  "file_ref": "string | null",
  "raw_text": "string | null",
  "nda": false,
  "status": "pending | confirmed | declined",
  "linked_statement_ids": ["stmt_001"],
  "created_at": "ISO8601"
}
```

### 3.3 `DeclineRecord`
```json
{
  "id": "dec_001",
  "target_type": "evidence | statement",
  "target_id": "ev_003",
  "reason": "string | null",
  "timestamp": "ISO8601"
}
```
**Rule:** a `DeclineRecord` never reduces any score and never requires `reason` to be filled. Its only function is to suppress a specific fact from being attributed to the candidate while keeping the parent `Statement` open for confirmation through another `Evidence` item.

### 3.4 Status computation rule (local, deterministic — not ML)
Applies per `Statement`, based on its linked, non-declined `Evidence`:

| Status | Condition |
|---|---|
| Not started | 0 evidence items linked |
| Limited | 1 evidence item, self-reported only (`free_text` or unverified `link`) |
| Medium | 1 independent evidence item (`link` to external verifiable source, `file`, or `blind_witness_answer`) OR 2+ self-reported items |
| Strong | 2+ evidence items from **distinct** `source_category` values, at least one independent |

This mirrors the wireframe's existing Evidence Map labels (`Hard Skills — Medium`, `Practical Understanding — Strong`, etc.) and must produce identical status logic to what's shown there.

---

## 5. Functional Requirements

### US1 — Add links to professional sources and artifacts

| ID | Requirement |
|---|---|
| FR1.1 | Candidate can add one or more links via a text field, minimum: URL format validation, no live verification required in this phase. |
| FR1.2 | Each link creates one `Evidence` record with `type: "link"` and a `source_category` inferred from domain (github.com → `github`, linkedin.com → `linkedin`, else `other`) or manually selectable. |
| FR1.3 | Candidate can upload one or more files (portfolio, certificate, presentation). MVP limit: 10 MB/file, formats: PDF, DOCX, PNG, JPG. |
| FR1.4 | Each file creates one `Evidence` record with `type: "file"`, `status: "pending"`. |
| FR1.5 | Adding a link/file is always optional and never blocks profile progression — candidate can skip and continue (matches "lazy entry" principle). |
| FR1.6 | Candidate can remove an added link/file before it is linked to any `Statement`; after linking, removal converts to a `DeclineRecord` (see US4), it is never hard-deleted from history. |
| FR1.7 | [V2 — not built now] Direct OAuth pull from GitHub/LinkedIn. Placeholder UI element may exist but action is disabled/stubbed. |

**Acceptance criteria:** candidate can add ≥1 link and ≥1 file in a single session, both appear as pending `Evidence` items visible in the Evidence Map (US3), with zero mandatory fields beyond the artifact itself.

---

### US2 — Free-form project/case description → structured competencies

| ID | Requirement |
|---|---|
| FR2.1 | Candidate is presented a free-text input (no rigid form fields) to describe a project or case, minimum guidance prompts only (e.g. "What did you build, what was hard about it"). |
| FR2.2 | On submit, the text is sent to an AI parsing step that extracts: (a) named competencies/skills, (b) a short evidentiary excerpt from the text supporting each, (c) an initial confidence label. |
| FR2.3 | Parsed output is shown to the candidate as an editable list before anything is saved — candidate can accept, edit the skill label, or discard each extracted item individually (never bulk-forced accept). |
| FR2.4 | Each accepted item creates a `Statement` (if new) or reinforces an existing one, plus one `Evidence` record with `type: "free_text"`, `raw_text` = the relevant excerpt, `source_of_claim: "free_text"`. |
| FR2.5 | The full original free-text submission is retained verbatim as a control sample (maps to master doc's "Raw Input" concept — do not discard after parsing, needed by Module 6/9 later, out of this module's processing scope but must not be lost). |
| FR2.6 | No AI-polishing or auto-correction of the candidate's original wording is applied before parsing — parse the raw input as typed. |

**Acceptance criteria:** candidate pastes/writes a free-form case description, receives a structured, editable competency list within the same flow, and can proceed with zero, some, or all items accepted.

---

### US3 — Evidence traceability per statement ("what proves what")

| ID | Requirement |
|---|---|
| FR3.1 | Every `Statement` displayed in the profile must expose its linked `Evidence` items (or explicitly show none) — no competency is ever shown without a way to inspect its backing. |
| FR3.2 | Evidence Map view lists each `Statement`/competency group with: current status label (Not started/Limited/Medium/Strong per §3.4), the evidence items backing it, and one clear next action to strengthen it (link a new source, add a project, answer a question). |
| FR3.3 | Clicking/expanding a `Statement` in the Evidence Map shows the underlying `Evidence` records (type, source, and — for `link`/`file` — the reference itself; for `free_text` — the excerpt; for `blind_witness_answer` — the answer). |
| FR3.4 | Status label and its explanation must always be paired (per XAI requirement from Ch.9): never show a bare status without one sentence of "why," e.g. "Medium — Contextual Probe passed, no independent source connected yet." |
| FR3.5 | Statement-to-Evidence linking is many-to-many: one Evidence item (e.g. a GitHub link) may back multiple Statements; one Statement may be backed by multiple Evidence items. |

**Acceptance criteria:** from any competency shown anywhere in the candidate profile, the candidate can reach the exact evidence item(s) that justify its current status in ≤2 clicks/taps.

---

### US4 — Right to decline disclosure without losing the competency

| ID | Requirement |
|---|---|
| FR4.1 | Any evidence-gathering step (link, file, free-text answer, targeted question) can be flagged by the candidate as **NDA-protected** before or instead of submitting the underlying artifact. |
| FR4.2 | When a source/fact is flagged NDA or the candidate explicitly declines to disclose it, the system creates a `DeclineRecord` and does **not** create a `pending`/`confirmed` `Evidence` linked to real content — no confidential artifact is ever stored, even temporarily. |
| FR4.3 | Declining never lowers Trust Score inputs and never requires a justification field to be filled (optional only). This must be explicit in the UI copy, matching Ch.8's "non-punitive" rule. |
| FR4.4 | **Blind Witness flow:** when a project/case is marked NDA, instead of requesting a file, the system asks for a structured description of the *logic*, not the artifact — minimum: 1 prompt such as "What were the 2–3 critical decision points in this process?" Answer is stored as `Evidence` with `type: "blind_witness_answer"`, `nda: true`. |
| FR4.5 | A `blind_witness_answer` is treated as an independent evidence source for status computation purposes (§3.4) — it can move a `Statement` to `Medium`, same tier as a verifiable link, since it required no artifact disclosure and is self-sufficient proof of reasoning. |
| FR4.6 | Mirror Tasks (abstract scenario substituted for a real NDA case) are **out of scope for this module** — UI may show an entry point ("Try a mirror task instead") but it stubs to a "coming soon" state until Module 3 (Contextual Probe engine) exists. Do not fake this with static content. |
| FR4.7 | Candidate can, at any later point, revisit a declined item and choose to confirm/disclose it — decline is reversible, not a one-way lock. |

**Acceptance criteria:** a candidate can mark a project NDA, go through the Blind Witness question, and see the related `Statement` reach at least `Medium` status — with zero file/text disclosure of the actual confidential material at any point in the flow or in storage.

---

## 6. UI Flow (maps to existing wireframe screens)

This module's requirements should slot into the existing candidate onboarding flow already prototyped (`purpjob-wireframe-v3.jsx`):

1. `enrichChoice` / `anchorQuestions` → satisfies US2 (free text intake, resume upload alternative)
2. `projectsIntro` → `ndaCheck` → satisfies US4 entry point (NDA toggle per project)
3. `ndaCheck` (NDA branch) → Blind Witness question screen → satisfies FR4.4 (new screen, not yet in wireframe — needs adding)
4. `artifactsStep` → satisfies US1 (links + files, "as many as you like")
5. `targetedEvidence` → satisfies US1/US3 combined (link, file, or answer against one specific gap)
6. `evidenceMap` → satisfies US3 in full (status per competency, "why," next action) and surfaces declined items distinctly from confirmed ones

**Gap vs. current wireframe:** no screen currently implements the Blind Witness structured-question flow (FR4.4) as a distinct step — `ndaCheck` today only sets a boolean flag. This needs a new screen state.

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication:** single implicit candidate session per browser/local instance; no login, no server-side user record. All data keyed to a local session identifier generated on first load.
- **Storage:** flat local JSON (e.g. `localStorage`, or a local file if desktop/CLI context) holding `Statement[]`, `Evidence[]`, `DeclineRecord[]`. Schema in §3 must be followed so migration to a real DB + auth (later phase) is a lift-and-shift, not a redesign.
- **AI parsing (FR2.2):** can call an LLM completion for text→competency extraction; must run client-side-triggered but does not require user identity — pass raw text only, no PII beyond what's in the text itself.
- **No file persistence beyond session** is required for MVP unless explicitly needed for demo continuity — but if implemented, files must never be sent anywhere when `nda: true` (FR4.2 is a hard constraint, not a UI suggestion).
- **Idempotency:** re-running the module (page reload) must reload the same local session data rather than resetting it, so the "profile is never lost" experience is testable even without accounts.

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| Auth / persistent accounts | Explicitly requested to defer — module must work fully local first. |
| GitHub/LinkedIn OAuth pull | Tagged [V2] in master doc; MVP only takes pasted links. |
| Mirror Tasks | Needs Contextual Probe engine (Module 3); this module only reserves the data slot. |
| Digital Echo (cross-verification vs public footprint) | Belongs to Module 9 (XAI/Anti-Cheat), consumes this module's Evidence but isn't built here. |
| Trust Score numeric formula | Owned by Module 5; this module only emits Statement status labels as input. |

---

**H1 hypotheses this module should let you test (not guarantees):**
- H1a (Activation): candidate completes at least one Evidence-adding action (link, file, free-text, or Blind Witness answer) in the first session.
- H1b (Compounding, later): on return, candidate closes a previously "Not started"/"Limited" Statement rather than only viewing the profile.
