# PurpJob — Module 5: NDA / Alternative Verification
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-0]
**Phase:** Local prototype (no authentication layer, no persistent backend, single local candidate session)
**Depends on:** Module 2 (Evidence/`Statement` data model, NDA flag, `DeclineRecord`), Module 3 (White Spot targeting), Module 4 (shared question/scenario-generation engine)
**Feeds into:** Module 2 (`Evidence`), Module 3 (`PROFIndexSnapshot` recompute), Module 6/Trust Score (Understanding signal — out of scope here, only emitted)

---

## ⚠️ 0. Discrepancy flag — read before building

**There are two conflicting decisions in the project's own materials about this exact module's scope, and this FRD needs your call before implementation starts.**

| Source | Decision |
|---|---|
| Master Document (Ch.8, v10.16) | Blind Witness Method and Mirror Tasks are **dedicated [MVP] mechanics** with their own dynamic, competency-driven question/scenario flow — this is the version these five user stories describe, and the version this FRD builds. |
| `Put_kandidata_MVP0_v2.md` + current `purpjob-wireframe-v3.jsx` (`ndaCheck` → `projectForm`) | Explicitly states Blind Witness/Mirror Tasks **"убраны из MVP-0 (зафиксировано, упрощено)"** — simplified away. The NDA-flagged project uses the **same generic form** as any other project (title, dates, role, what-you-did, stack, optional artifact) plus a disclaimer screen; detail confirmation happens later through the generic Drill-Down mechanism in Mini-cases (Module 4), not a dedicated NDA mechanic. |

These read like two decisions from different points in time, and I can't tell from the documents alone which one is the standing decision — the wireframe currently implements the *simplified* version, while the master document and your five user stories both describe the *dedicated-mechanic* version.

**I'm building this FRD to the dedicated-mechanic version**, because that's what your user stories explicitly ask for (US2/US3 name Mirror Task and Blind Witness Method as distinct capabilities, not "the same form with a disclaimer"). But before this goes to development:
1. Confirm this supersedes the simplification in `Put_kandidata_MVP0_v2.md`.
2. `purpjob-wireframe-v3.jsx`'s `ndaCheck`/`projectForm` screens will need to be updated to match (§6) — right now they implement the *other* decision.
3. If the simplification was actually the more recent, considered call (e.g. to reduce onboarding friction), say so and I'll rewrite this FRD around the generic-form-plus-disclaimer version instead — it's a materially smaller build.

---

## 1. Purpose

**Result this module owns:** absence of a public Digital Footprint must never, by itself, mean absence of the ability to build Trust. This is the direct product answer to "how does a candidate with NDA-heavy experience compete with one who has a public GitHub" — the mechanism, not just a policy statement.

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| P4 — Privacy/NDA respect | Direct implementation: prove ownership of knowledge, not the artifact itself (US1–US3). |
| P1 — Evidence-Based Hiring | Blind Witness/Mirror Task outputs become real `Evidence`, not an exemption from evidence requirements — NDA is a *different proof channel*, not a bypass. |
| P5 — Dynamic Trust / non-punitive rule | Declining a method, or declining all of them, never penalizes — it leaves the competency `not_started`/`limited`, same as any other unconfirmed gap. |
| XAI (cross-cutting) | Method choice is always visible and explained, never a silent system decision the candidate can't see or override (US4). |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- NDA disclaimer/consent screen: explicit statement of what is *never* requested (code, exact commercial figures, client names, internal documents) and what *is* fine to share (general logic, architecture, tools, personal role) — shown before any alternative-verification flow starts (US1)
- **Blind Witness Method**: structured, competency-driven questions asking for logic/decision structure in the abstract, no file ever requested (US3)
- **Mirror Task**: an abstract scenario with analogous inputs for the same competency; candidate arranges structural nodes and explains the logic — explicitly positioned as *not* a replacement for real experience nor "yet another test," reusing Module 4's generation engine (US2)
- Method selection and switching: candidate can decline a system-suggested method and pick an allowed alternative, fully non-punitively (US4)
- Routing of Blind Witness/Mirror Task outputs into Module 2's `Evidence` shape and Module 3's competency scoring, on the same dual-signal basis Module 4 already establishes

### 2.2 Out of scope (explicitly deferred)
- Local on-device competency-hash analyzer ("Локальный анализатор") — [V3], optional future enhancement, not needed since this module already fully closes the NDA gap without file upload
- Zero-Knowledge Social Proof / Micro-Vouching (anonymous ex-colleague confirmation) — [Vision], not this module
- Trust Score / Understanding scoring itself — Module 6, this module only emits the signal (same boundary as Module 4)
- Legal review and final copy sign-off for the disclaimer text (§4.1) — product/legal process, this FRD only specifies the functional requirement that a disclaimer must exist and block progress until acknowledged
- Any recruiter-facing display of "this evidence came via Blind Witness/Mirror Task" — that's a Module 6+ display concern, out of scope for the candidate-side module here

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values (`blind_witness`, `mirror_task`, `method_selection`, etc.) | English |
| All UI copy: disclaimer text, Blind Witness prompts, Mirror Task instructions, method-switch UI | **Russian**, matching the register already established in the master document and `purpjob-wireframe-v3.jsx` |

**Disclaimer copy — reuse the already-drafted version from `Put_kandidata_MVP0_v2.md` verbatim (it's flagged `[Требует юр.проверки]` there — keep that flag visible in-product, don't silently drop it):**

> *"Вы можете поделиться с нами как любым проектом из своего портфолио, так и написать о проекте под NDA, не нарушая ваше соглашение."*
>
> *"Что обычно НЕ считается коммерческой тайной: общая логика и архитектура решения, используемые технологии и инструменты, ваша личная роль и зона ответственности. Мы не просим код, точные бизнес-показатели, имена клиентов или внутренние документы компании."*

**New copy needed (author in the same register):**
- Blind Witness prompt pattern (per master doc example, reuse near-verbatim as a template model): *"Опиши структуру процесса, который ты внедрил. Какие три критических узла ты там выделил?"*
- Mirror Task framing line (must always be shown, this is a positioning requirement, not decoration, FR2.4): *"Это не замена реальному опыту, а дополнительное подтверждение того, что вы способны воспроизвести профессиональную логику — не очередное тестовое задание."*
- Method-switch prompt (US4): *"Предпочитаете другой способ подтверждения?"* with the alternative(s) listed as clear, equally-weighted options — no visual hierarchy implying the system's suggestion is the "correct" or expected choice.

---

## 4. Data Model

Local-first constraint, consistent with Modules 2–4: flat local JSON per candidate session. This module reads Module 2's `Statement`/`Evidence` (specifically NDA-flagged items) and Module 3's White Spots for NDA-context competencies, reuses Module 2's `DeclineRecord` shape, and reuses Module 4's generation-engine interface with two new modes.

### 4.1 `NDACase`
```json
{
  "id": "ndacase_001",
  "statement_id": "stmt_001",
  "source_evidence_id": "ev_003",
  "disclaimer_ack_at": "ISO8601",
  "status": "method_selection | in_progress | confirmed | declined_all",
  "created_at": "ISO8601"
}
```
- Created whenever a candidate marks a `Statement`/`Evidence` as NDA-protected (Module 2) or declines a Contextual Probe question as NDA-sensitive (Module 4, FR5.2) — this module is the actual implementation behind that Module 4 hook, not a separate trigger path. **This supersedes Module 2's/Module 4's placeholder "Blind Witness-style rephrase" language — those should reference this module's `NDACase` flow directly once this ships** (flag for a small cross-reference patch to those two FRDs).
- `disclaimer_ack_at` is mandatory before `status` can move past `method_selection` (US1, hard gate).

### 4.2 `MethodOffer` (US4)
```json
{
  "case_id": "ndacase_001",
  "suggested_method": "blind_witness | mirror_task",
  "available_methods": ["blind_witness", "mirror_task"],
  "chosen_method": "blind_witness | mirror_task | null",
  "switch_log": [
    { "from": "blind_witness", "to": "mirror_task", "timestamp": "ISO8601" }
  ]
}
```
- `available_methods` is always both in this MVP (no competency-specific restriction has been defined) — if a future calibration finds one method unsuitable for a given competency type, that's a Ch.13 calibration input, not hardcoded here.
- Switching methods is unlimited and logged only for product analytics, never to penalize or flag the candidate.

### 4.3 `BlindWitnessSession`
```json
{
  "case_id": "ndacase_001",
  "competency_id": "rest_api_design",
  "questions": [
    { "id": "bw_q1", "prompt_ru": "Опиши структуру процесса...", "answer": "string | null" }
  ],
  "status": "pending | answered | declined"
}
```
- Questions are generated via Module 4's shared engine in a new mode (§7) that does **not** RAG against a specific artifact (there is none to bind to) — instead parametrized purely by `competency_id`, asking for structural/logic description.
- Semantic Depth follow-up (Module 4, FR-Int.1) still applies here if an answer is too generic — reuse, don't reimplement.

### 4.4 `MirrorTaskScenario` (seed content, per competency)
```json
{
  "id": "mt_scenario_backend_caching_001",
  "competency_id": "caching_strategy",
  "instructions_ru": "Вот абстрактная схема с похожими вводными. Расставь узлы и опиши логику так, как ты сделал бы это на работе.",
  "nodes": [
    { "id": "n1", "label_ru": "Клиентский запрос" },
    { "id": "n2", "label_ru": "Кэш-слой" }
  ]
}
```
- Static seed content, same convention as Module 3's `ReferenceProfile`: version-controlled JSON, not database-editable in this phase. MVP ships a small hand-authored set per Backend/Fullstack competency, not full coverage — matches Module 4's precedent for the Jargon Trap template library (small hand-authored MVP set, broader authoring tooling deferred).

### 4.5 `MirrorTaskSolution`
```json
{
  "case_id": "ndacase_001",
  "scenario_id": "mt_scenario_backend_caching_001",
  "node_arrangement": [ { "node_id": "n1", "order": 1, "role_ru": "string" } ],
  "logic_explanation": "string",
  "status": "pending | submitted | declined"
}
```
- Both `node_arrangement` (structural placement) and `logic_explanation` (free text, same US3-style constraint as Module 4: open-ended, never multiple-choice) are required to count as a complete submission — a node arrangement alone, with no explanation, is not sufficient evidence of understanding.

---

## 5. Functional Requirements

### US1 — Confirm NDA-protected experience without disclosing client, code, or commercial details

| ID | Requirement |
|---|---|
| FR1.1 | Before any alternative-verification flow can start, the candidate must see and acknowledge the disclaimer (§3) — this is a hard gate: `NDACase.status` cannot leave `method_selection` without `disclaimer_ack_at` set. |
| FR1.2 | The disclaimer must explicitly enumerate both directions: what's fine to share (logic, architecture, tools, personal role) and what's never requested (code, exact business metrics, client names, internal docs) — a one-sided "don't worry, it's safe" message is not sufficient; specificity is what makes the guarantee credible. |
| FR1.3 | No screen or prompt in this module (Blind Witness questions, Mirror Task instructions) may ever ask for a client/company name, exact financial figures, or file upload. This is a hard content constraint on the template/seed library (§4.3, §4.4), not just a UI convention — template authoring for this module must be reviewed against this rule specifically. |
| FR1.4 | This module never requires an artifact. Every path here (Blind Witness, Mirror Task) produces `Evidence` from the candidate's own typed/structured input alone (§4.3–4.5), consistent with the master doc's framing: "докажи владение, не показывай артефакт." |

**Acceptance criteria:** a candidate can go from marking a project NDA to producing confirmed Evidence for at least one competency without ever being prompted for a file, a client name, or a specific monetary figure — and the disclaimer they saw actually matches what was subsequently asked.

---

### US2 — Mirror Task: verify competency through an analogous, new task

| ID | Requirement |
|---|---|
| FR2.1 | The system selects a `MirrorTaskScenario` matching the `NDACase`'s target `competency_id` (§4.4) — never a generic, competency-unlinked puzzle. If no scenario exists for that competency, Mirror Task is not offered as an option for that case (§4.2 `available_methods` narrows accordingly — do not fake a scenario). |
| FR2.2 | The candidate interacts with the scenario in two parts: (a) structural — assign/order the given abstract nodes (§4.5 `node_arrangement`); (b) explanatory — free-text description of the reasoning, same open-form constraint as Module 4 US3 (no multiple-choice, no single canonical answer to match against). |
| FR2.3 | Question/scenario generation reuses Module 4's shared engine (per Module 4 FR2.5) via a new mode — parametrized by competency, not RAG-grounded on a candidate artifact (there is none), but otherwise the same underlying capability, not a separate one built from scratch. |
| FR2.4 | **Positioning requirement (hard constraint, not optional copy):** the Mirror Task framing line (§3) must always be shown before the task starts — "this is not a replacement for real experience, not another test assignment." This directly reflects an explicit master-doc caveat about how this feature must never be marketed or presented. |
| FR2.5 | A submitted `MirrorTaskSolution` is evaluated the same way Module 4 evaluates probe answers: Semantic Depth applies (if the explanation is too generic, one follow-up is issued before finalizing), and the result routes through the same dual-signal logic (§5.6 of Module 4) — this module does not invent a separate scoring approach. |

**Acceptance criteria:** for an NDA-flagged competency with an available Mirror Task scenario, the candidate can complete both the structural and explanatory parts and see the resulting Evidence appear against the correct competency in Module 3's Evidence Map, without any file ever being involved.

---

### US3 — Blind Witness Method: confirm a professional fact without disclosing confidential information

| ID | Requirement |
|---|---|
| FR3.1 | Blind Witness questions ask for a **structural description of logic/decisions** (e.g. "which three critical nodes did you identify"), never for the underlying document/code/regulation itself. |
| FR3.2 | Question generation is competency-parametrized (§4.3), reusing Module 4's template mechanism in a no-artifact mode — a small hand-authored set per competency is acceptable for MVP, matching the precedent already set for Mirror Task scenarios and Jargon Trap templates. |
| FR3.3 | If the candidate's answer is judged too generic (e.g. restates the competency label without real structural detail), the system issues a Semantic Depth follow-up (reused from Module 4), same as any other probe answer — do not silently accept a low-effort answer just because it's in the NDA-safe path. |
| FR3.4 | A completed Blind Witness answer produces `Evidence(type: "blind_witness_answer", nda: true)` in Module 2's shape (this type already exists in Module 2's data model — this module is its actual producer, no new Evidence type needed here). |

**Acceptance criteria:** a candidate can complete a Blind Witness session for an NDA-flagged competency using only typed structural answers, and the resulting Evidence is indistinguishable in shape from any other Evidence in Module 2/3, just tagged `nda: true`.

---

### US4 — Decline the suggested method and choose another allowed alternative

| ID | Requirement |
|---|---|
| FR4.1 | When an `NDACase` reaches `method_selection`, the system presents a `suggested_method` but always shows all `available_methods` (§4.2) as equally legitimate, clearly labeled choices — never a single forced path with switching buried behind an obscure link. |
| FR4.2 | Choosing a different method than suggested is a normal, expected action, not a special "decline" flow requiring justification — no reason field, no confirmation friction beyond the click itself. |
| FR4.3 | Switching is allowed at any point, including mid-flow (candidate starts Blind Witness, decides Mirror Task fits better, switches without losing overall progress on the `NDACase` — only the specific in-progress session for the abandoned method is discarded). |
| FR4.4 | If the candidate declines **all** available methods for a given case, `NDACase.status` becomes `declined_all` — the competency simply remains at its current status (`not_started`/`limited`), with zero penalty, fully consistent with the non-punitive rule already established in Modules 2 and 4. This is not a dead end: the candidate can return to this `NDACase` later and pick a method at any time. |
| FR4.5 | This module must reuse Module 2's `DeclineRecord` mechanics for the "decline all" case specifically (`target_type: "ndacase"`) — do not build a third parallel decline implementation; Module 2, Module 4, and this module should all resolve to the same underlying non-punitive decline contract. |

**Acceptance criteria:** a candidate can start with the system-suggested method, switch to the alternative at any point without friction or explanation, and — if neither works for them — decline both with zero effect on any score, while retaining the ability to come back later.

---

## 6. UI Flow

**Given the discrepancy flagged in §0, this section assumes the dedicated-mechanic version is confirmed as the standing decision.** If not, this entire section needs to be redesigned around the generic-form-plus-disclaimer approach instead.

1. **`ndaCheck` (existing screen, needs behavior change):** currently just a boolean flag feeding into a generic `projectForm`. Under this FRD, checking "Этот проект под NDA" must route to a **new** disclaimer screen (FR1.1) rather than straight into the standard project form.
2. **New screen: NDA disclaimer/consent** — renders §3's disclaimer copy, single acknowledgment action, gates `NDACase.status` past `method_selection`.
3. **New screen: method selection** — implements US4 (FR4.1): suggested method highlighted but not forced, alternative(s) visible and equally clickable.
4. **New screen: Blind Witness session** — question + answer textarea, same integrity mechanics as Module 4's `minicaseQuestion` (copy-paste ban, Semantic Depth follow-up inline), plus the "why this question" transparency pattern already established in Module 4 (US4 of that module) — reuse, don't rebuild.
5. **New screen: Mirror Task** — scenario instructions + framing line (FR2.4, always visible) + node-arrangement interaction + free-text explanation field.
6. **`evidenceMap` (existing, downstream only):** must display Blind Witness/Mirror Task-sourced Evidence identically to any other Evidence, with an `nda: true` indicator, no special "lesser" visual treatment — this NDA-sourced evidence carries the same weight in status computation as any other independent source.

**No screens in this list currently exist except `ndaCheck`.** This is a materially larger UI build than the "unified form + disclaimer" alternative in §0 — worth weighing explicitly against that simpler path before committing engineering time.

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication:** same single implicit local session as Modules 2–4.
- **Generation engine reuse:** extend Module 4's `generateQuestion(...)` interface with two new modes — `blind_witness_prompt` (competency-parametrized, no artifact) and `mirror_task_scenario` (returns a `MirrorTaskScenario` from the seed library, §4.4, not a freshly generated one in MVP — scenario *generation* on the fly is a plausible V2 enhancement, not required now). Do not implement these as a separate generation stack.
- **Seed content ownership:** `MirrorTaskScenario` library is static, version-controlled JSON, same convention as Module 3's `ReferenceProfile` — no admin UI to author it in this phase.
- **Data model note for Module 2:** confirm `Evidence.type` enum already includes (or is extended to include) `"mirror_task_solution"` alongside the existing `"blind_witness_answer"` — small addition needed to Module 2's schema, flagged here rather than silently assumed.

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| **§0 discrepancy resolution** | Blocks everything else in this document — needs an explicit founder decision on which version of the NDA flow stands, before UI work starts. |
| Local on-device competency-hash analyzer | [V3] — optional strengthening layer, not required since Blind Witness + Mirror Task already fully close the NDA gap per the master doc's own framing. |
| Zero-Knowledge Social Proof / Micro-Vouching | [Vision] — needs a mature verified-profile graph that doesn't exist yet. |
| On-the-fly Mirror Task scenario generation (vs. static seed library) | Plausible V2 — MVP ships a small hand-authored scenario set per competency, same precedent as Module 4's Jargon Trap templates. |
| Whether some competencies should restrict `available_methods` to just one (e.g. Mirror Task doesn't make sense for every skill type) | Calibration question (Ch.13), not resolved here — MVP offers both wherever a Mirror Task scenario happens to exist for that competency. |

---

**H1 hypotheses this module should let you test (not guarantees):**
- H1 (NDA path completion): candidates with NDA-flagged experience reach `medium`/`strong` status on those competencies at a comparable rate to candidates with publicly disclosable evidence — if this gap is large, the alternative-verification methods aren't actually closing the Digital Footprint gap they're meant to close.
- H1 (Method preference): distribution of `chosen_method` and `switch_log` activity (§4.2) tells you whether Blind Witness or Mirror Task is the path candidates actually find usable — informs which one to invest further template/scenario authoring effort into first.
