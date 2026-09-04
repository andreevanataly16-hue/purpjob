# PurpJob — Module 4: Contextual Probe
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-0]
**Phase:** Local prototype (no authentication layer, no persistent backend, single local candidate session)
**Depends on:** Module 2 (Evidence — RAG source, and the NDA/right-to-decline mechanism this module reuses), Module 3 (PROF.Index — White Spot source and competency-score consumer)
**Feeds into:** Module 3 (new competencies discovered mid-answer), Module 6/Trust Score (Understanding component — out of scope here, this module only emits the signal), Module 9/XAI-Anti-Cheat (stylometry, tab-switching, Anomaly flag — separate module, out of scope here)

---

## 1. Purpose

Contextual Probe is PurpJob's core technological moat: instead of a generic skills test, it generates unique questions at the intersection of one specific unconfirmed competency and one specific artifact the candidate themselves provided. It exists to check **understanding, not memory** — whether the candidate genuinely grasps the logic of what they claimed, not whether they can produce a plausible-sounding answer (which any LLM assistant can already do for a generic question bank).

**Result this module is responsible for (per the source spec):** the system doesn't just collect information — it **surgically closes gaps in the evidence base**. This is one of Chapter 7's central principles and the standard against which every requirement below should be judged: if a requirement doesn't serve targeted gap-closing, it doesn't belong in this module.

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| P1 — Evidence-Based Hiring | A probe answer becomes new Evidence in its own right (Module 2 data shape), not a separate unverifiable claim. |
| P2 — Automation / Logic over Memory | The system never asks about something already confirmed — it only asks about the specific next gap (US1). |
| P3 (implicit) — Understanding over memory | Questions are open-ended and reasoning-based, never multiple-choice or fact-recall (US3); generated from the candidate's own artifacts, not a job-title question bank (US2). |
| P4 — Privacy/NDA respect | Candidate can decline a specific probe question as NDA-sensitive without penalty, routed into the same right-to-decline mechanism as Module 2 (US5). |
| P5 — Dynamic Trust / non-punitive rule | Skipping, declining, or "failing" a probe never produces a negative score — only "unconfirmed" (0), never punished retroactively. |
| XAI (Ch.9, cross-cutting) | Every question must be traceable to the specific competency and reason it was asked (US4) — no question is ever a black box. |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- Question targeting: select which competency/gap to probe next, sourced exclusively from Module 3 White Spots (US1)
- Question generation: parametrized templates + RAG against the candidate's own Module 2 artifacts (US2)
- Open-form answer format only — no multiple-choice, no single-correct-answer grading (US3)
- Per-question transparency: which competency, and why this question was asked (US4)
- Per-question NDA decline: candidate can flag a specific question as touching confidential information, without penalty, routed to the existing right-to-decline / Blind-Witness-style alternative (US5)
- Semantic Depth follow-up ("Drill-Down"): one clarifying question when an answer is too generic to verify
- Jargon Trap: an insider-terminology check woven into a probe template, not a separate question type
- Copy-paste ban on the answer input (client-side enforcement)
- Keystroke Dynamics: raw typing-metadata **capture** only (timing, pauses, corrections) — behind an explicit feature flag, off by default (see §8, legal blocker)
- Question-quality feedback loop ("this question doesn't fit") — capture only, not the reward/calibration mechanic itself (that's Ch.13/ops, out of scope)
- Dual-signal routing of a given answer's content to both downstream consumers where applicable (§5.6) — this module classifies and emits, it does not compute either score itself

### 2.2 Out of scope (explicitly deferred)
- Trust Score computation (Understanding component scoring) — Module 6, this module only emits the raw signal
- Stylometric/psycholinguistic AI-text detection (Perplexity/Burstiness), tab-switching detector, "Anomaly" flag — Module 9 (XAI/Anti-Cheat), separate module; this module only guarantees the raw answer text and typing metadata are available for that module to consume
- Digital Echo cross-verification and contradiction-sourced White Spots — Module 8/9 dependency; this module only needs to accept a contradiction-type target once that module exists (see §4.1)
- Reward mechanism for confirmed question-quality bugs (Ch.13, Backlog #25) — ops/calibration process, not application logic
- Local-vs-API inference decision for the generation model (Backlog #11, open, needs CTO input) — this module must be built against a pluggable interface so either backend can be swapped in without a rewrite (§8)
- Voice-log analysis, Liveness Check / gaze tracking — [V4], not this module
- Local on-device code/document analyzer producing a "competency hash" instead of raw text — [V3], not this module; NDA handling in this MVP is fully covered by US5's decline-and-reroute mechanism plus Module 2's Blind Witness/Mirror Tasks, without needing this heavier plugin

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values, template IDs | English |
| All UI copy: question text, follow-up prompts, feedback-reason labels, skip/decline/answer buttons, "why this question" explanations | **Russian**, matching the register already established in `purpjob-wireframe-v3.jsx` |

Reuse existing strings verbatim wherever the screen already exists:
- `"Какой инструмент использовали для профилирования узких мест?"` — example probe question pattern
- `"Вопрос не подходит"` — feedback trigger link
- Feedback reason set (reuse exactly): `"Не относится к моему проекту"`, `"Не понимаю вопрос"`, `"Слишком узкий/специфичный фреймворк"`, `"Ошибка в контексте"`, `"Другое"`
- `"Пропустить"` — generic skip action, always present (non-punitive rule)
- `"Contextual Probe пройден"` / `"Независимо подтверждено через Contextual Probe, проверка на шаблонность пройдена"` — existing confirmation-state copy patterns from Evidence Map

**New copy needed for this rewrite (US4/US5), author in the same register, do not invent a different tone:**
- "Why this question" explanation line (US4) — short, one sentence, e.g. pattern: *"Этот вопрос проверяет: [компетенция] — по этой теме пока недостаточно независимых подтверждений."* for a White Spot target.
- NDA decline action (US5) — must sit next to the generic skip, but be a visibly distinct choice, not the same button, e.g. pattern: *"Это касается NDA"* as a secondary link alongside *"Пропустить"*.

**Generated question text itself is a special case:** the LLM generation prompt (§5.2) must produce **Russian** output directly — do not generate in English and translate, since translation would strip the natural, colloquial "practitioner-to-practitioner" register the Jargon Trap and Semantic Depth mechanics depend on. Prompt-engineer the generation call with Russian few-shot examples from the master document (e.g. *"В твоём проекте X на 45-й строке использован паттерн Observer. Почему не Factory?"*).

---

## 4. Data Model

Local-first constraint, consistent with Modules 2–3: flat local JSON per candidate session. This module reads Module 3's `white_spots` and Module 2's `Evidence[]`, and reuses Module 2's `DeclineRecord` shape for US5; it writes its own `Question[]`/`Answer[]`/`QuestionFeedback[]`, and emits routing results Module 3 must be able to ingest (per that module's FR1.6 contract).

### 4.1 `ProbeTarget` (what to ask about — read from Module 3, not owned here)
```json
{
  "competency_id": "rest_api_design",
  "target_type": "white_spot | contradiction",
  "source_statement_ids": ["stmt_001"],
  "priority_weight": 0.15
}
```
- `white_spot` targets come directly from Module 3's White Spot list.
- `contradiction` targets depend on Digital Echo (Module 8/9, not yet built) — this module must accept this `target_type` value structurally without a producer existing yet.

### 4.2 `Question`
```json
{
  "id": "q_001",
  "competency_id": "rest_api_design",
  "target_type": "white_spot",
  "artifact_evidence_id": "ev_003",
  "template_id": "drilldown_pattern_choice",
  "text_ru": "В твоём проекте X на 45-й строке использован паттерн Observer. Почему не Factory?",
  "reason_ru": "Этот вопрос проверяет: проектирование REST API — по этой теме пока недостаточно независимых подтверждений.",
  "status": "pending | answered | skipped | declined_nda | flagged_bad",
  "created_at": "ISO8601"
}
```
- `reason_ru` is **mandatory**, not optional metadata — it is the direct data source for US4's "why this question" requirement (FR4.1) and must be generated alongside the question, not backfilled separately.
- `artifact_evidence_id` is mandatory for any `white_spot`-targeted question sourced from a code/file artifact; a question with no bound artifact is a **generic** fallback question and must be flagged as such internally (FR2.4).
- `status: "declined_nda"` is distinct from `"skipped"` — see §4.6.

### 4.3 `Answer`
```json
{
  "question_id": "q_001",
  "text": "string",
  "format": "free_text",
  "typed_duration_ms": 45210,
  "paste_attempts_blocked": 0,
  "keystroke_meta": "object | null",
  "submitted_at": "ISO8601",
  "routing": {
    "understanding_signal": true,
    "new_competency_signal": false
  }
}
```
- `format` is fixed to `"free_text"` in this module — no other value is valid (US3, FR3.1). This field exists specifically to make the constraint machine-checkable in code review/tests, not just a UI convention.
- `keystroke_meta` is `null` unless the feature flag in §8 is explicitly enabled.

### 4.4 `FollowUpQuestion` (Semantic Depth drill-down)
```json
{
  "parent_answer_id": "a_001",
  "trigger_reason": "too_generic | jargon_trap",
  "text_ru": "Впечатляет. За счёт чего именно: расширение воронки, рост среднего чека или работа с возвратами?",
  "answer": "string | null"
}
```

### 4.5 `QuestionFeedback`
```json
{
  "question_id": "q_001",
  "reason": "not_related_to_project | dont_understand | too_narrow_framework | context_error | other",
  "comment": "string | null",
  "screenshot_ref": "string | null",
  "timestamp": "ISO8601"
}
```
- Reason enum values map 1:1 to the Russian labels fixed in §3.
- Submitting feedback must regenerate/replace the current question, not leave the candidate stuck.

### 4.6 NDA decline (US5) — reuses Module 2's `DeclineRecord`, extended `target_type`
```json
{
  "id": "dec_010",
  "target_type": "question",
  "target_id": "q_001",
  "reason": "string | null",
  "timestamp": "ISO8601"
}
```
- Declining a `Question` as NDA must **not** simply leave it `skipped` — on decline, the system offers the same alternative already built in Module 2 (Blind Witness-style rephrasing: ask about the reasoning/logic in the abstract, not the specific confidential artifact), reusing the shared generation capability (FR2.5). If the candidate also declines the rephrased version, it is then treated as a normal skip (§5.5) — the competency remains unconfirmed, no penalty either way.
- Exactly like Module 2's `DeclineRecord`: never requires a `reason`, never lowers any score, always reversible.

---

## 5. Functional Requirements

### US1 — Only questions on insufficiently-confirmed competencies

| ID | Requirement |
|---|---|
| FR1.1 | Before generating any question, the system selects a `ProbeTarget` exclusively from Module 3's current White Spot list (`status` = `not_started` or `limited`) — competencies already `medium`/`strong` are never probed. |
| FR1.2 | Target selection follows the same priority order Module 3 already establishes for White Spots (highest `weight`/impact first) — no second, divergent prioritization rule. |
| FR1.3 | Once a competency reaches `medium`/`strong` status (via this module's own answer or any other Module 2 Evidence added concurrently), any `pending` `Question` still targeting it is retired without penalty. |
| FR1.4 | The system never re-asks a competency that has already reached `strong`, even in a later session ("Logic over Memory"). |
| FR1.5 | If no White Spot exists (fully confirmed profile, or Module 3 not yet run), the probe flow has nothing to offer and must say so explicitly rather than falling back to a generic question. |

**Acceptance criteria:** across a full session, every `Question` presented maps to a White Spot competency that was `not_started`/`limited` at generation time — never an already-strong one, never outside the current `ReferenceProfile`.

---

### US2 — Questions built from the candidate's own profile, Evidence, and White Spots

| ID | Requirement |
|---|---|
| FR2.1 | Question generation method: **parametrized template per competency + RAG over the candidate's own Module 2 artifacts** — never a static job-title question bank. This is the moat; do not substitute a simpler "pick from N canned questions per skill" implementation even as a temporary shortcut. |
| FR2.2 | Generation flow, in order: (1) take `competency_id` from the selected `ProbeTarget`; (2) retrieve the candidate's own linked artifacts for that competency (code, project description, task log — Module 2 `Evidence.raw_text`/`file_ref`/`url` content); (3) generate a question at the intersection of the competency and a specific, retrieved detail from that artifact. |
| FR2.3 | A correctly generated question must reference something only findable in the candidate's own material (a specific choice, a specific line, a specific described decision) — not a competency-generic prompt applicable to any candidate with that skill listed. |
| FR2.4 | **Fallback path:** if no usable artifact exists for a targeted competency, the system may fall back to a template-only, non-RAG question — tagged distinctly so it's traceable from the primary artifact-grounded path in analytics/calibration. |
| FR2.5 | The same underlying question-generation engine (template + RAG) must be reusable by Module 2's Blind Witness/Mirror Task flow, and by this module's own US5 NDA-rephrase path (§4.6) — build as a shared internal capability, not a Module-4-only silo. |

**Acceptance criteria:** for a competency backed by a concrete artifact, the generated question text contains a specific detail traceable to that artifact — not a paraphrase of the competency label itself.

---

### US3 — Free-form answers explaining decision logic, not guessing the right option

| ID | Requirement |
|---|---|
| FR3.1 | Every `Question` is answered via a single open-text field (`Answer.format: "free_text"`, §4.3, hard constraint). No multiple-choice, true/false, or single-correct-answer input type may ever be generated by this module. |
| FR3.2 | Question templates must be phrased to elicit reasoning ("why," "how," "what would you do if") rather than a single verifiable fact with one correct string answer — this is what makes the format resistant to lookup/guessing and consistent with Principle 3 ("Проверяй понимание, а не память"). |
| FR3.3 | There is no single canonical "correct answer" string this module checks the reply against. Evaluation of the answer (understanding quality, genericness triggering Semantic Depth, jargon-trap pass/fail) is judged by the generation/evaluation model against the bound artifact's actual content, not string-matched against a stored key. |
| FR3.4 | If an answer is judged too generic to demonstrate genuine reasoning, the system does not mark it "wrong" — it triggers one Semantic Depth follow-up (§5.4 below) asking for the specific mechanism, before any status is finalized. |

**Acceptance criteria:** no code path in this module can render a question with predefined answer options; every submitted `Answer.text` is free-form, and no answer is scored via exact-match comparison to a stored "correct" value.

---

### US4 — Transparency: which competency, and why, per question

| ID | Requirement |
|---|---|
| FR4.1 | Every `Question` rendered to the candidate must display its `reason_ru` (§4.2) alongside the question text — which competency it targets and why it was asked (e.g., insufficient independent confirmation on a specific White Spot). No question may ever appear without this explanation, matching the same XAI rule already established for Evidence Map / PROF.Index status labels (never a bare status/question without a "why"). |
| FR4.2 | The explanation must name the actual `target_type` driving the question: for `white_spot`, reference the specific competency gap; for `contradiction` (once Module 8/9 exists), reference the specific inconsistency being checked — do not use a single generic phrase for both cases. |
| FR4.3 | This transparency requirement also applies to Semantic Depth follow-ups (§4.4) and Jargon Trap-augmented questions — a follow-up must make clear it's a clarification of the same competency check, not an unrelated new question appearing out of nowhere. |
| FR4.4 | Historical transparency: once answered, a `Question` and its `reason_ru` must remain visible/reviewable from the Evidence Map or equivalent history view (Module 3) — the candidate can always look back and see what was asked and why, not just in the moment of answering. |

**Acceptance criteria:** for any question the candidate has ever seen (pending, answered, skipped, or declined), they can find the competency it targeted and the one-sentence reason it was asked, both during the session and afterward.

---

### US5 — Decline to answer or flag NDA-sensitive content, without penalty

| ID | Requirement |
|---|---|
| FR5.1 | Alongside the generic `"Пропустить"` skip action (always available, non-punitive per Ch.6), every question must offer a visibly distinct **"Это касается NDA"** action. |
| FR5.2 | Choosing the NDA action creates a `DeclineRecord` with `target_type: "question"` (§4.6) and immediately triggers the system to offer a **Blind Witness-style rephrase** of the same competency check — abstract reasoning/logic question instead of one anchored to the specific confidential artifact — using the shared generation capability from FR2.5. |
| FR5.3 | The candidate is never forced through the rephrase — declining the rephrase too simply leaves the competency `not_started`/`limited`, same as any other skip. No reason/justification is ever required for either decline. |
| FR5.4 | Declining a question, with or without accepting the rephrase, never reduces any score anywhere and is fully reversible — the candidate can return to a declined competency later via Module 2 or a future probe session. |
| FR5.5 | This module must not duplicate Module 2's right-to-decline logic with a second implementation — `DeclineRecord` creation, non-punitive guarantee, and reversibility must be the exact same code path/contract, only the `target_type` differs. |

**Acceptance criteria:** a candidate can flag any live question as NDA-sensitive, receive an abstracted alternative version of the same check, decline that too if still uncomfortable, and see zero negative effect on any score in either case.

---

### 5.4 Supporting Integrity Mechanics (Ch.7 MVP scope, required for this module, not tied to one single user story)

| ID | Requirement |
|---|---|
| FR-Int.1 — Semantic Depth ("Drill-Down") | If a submitted `Answer.text` is judged too generic to verify anything, the system issues one `FollowUpQuestion` asking for the specific mechanism/tooling behind the claim (§4.4), rendered inline on the same screen, with its own `reason_ru`-equivalent transparency (FR4.3). |
| FR-Int.2 — Jargon Trap | For select competencies, the generation template can weave in a domain-insider terminology check without flagging it to the candidate as a "trap." This is a template-authoring pattern in the template library, not a separate scoring algorithm to build. |
| FR-Int.3 — Copy-paste ban | The answer `<textarea>` must block paste (Ctrl/Cmd+V), the browser context menu, and drag-drop text insertion. Log `paste_attempts_blocked` on `Answer` — prevent silently, no punitive error message. |
| FR-Int.4 — Keystroke capture (flagged, off by default) | If the feature flag is enabled (§8), capture typing timing/pauses/corrections during answer entry as `keystroke_meta`. This module only captures and stores the raw signal — scoring/comparison is Module 6's job. |

---

### 5.6 Dual-signal routing (US1+US2+US3 combined mechanism, corrected per master doc Ch.5/7)

| ID | Requirement |
|---|---|
| FR6.1 | Every submitted `Answer` is classified for two independent signals, stored in `Answer.routing` (§4.3). The routing table below is authoritative — do not simplify it to a single score: |

| Answer content | PROF.Index signal (new `Statement`) | Trust Score Understanding signal |
|---|---|---|
| Confirms an already-claimed competency, demonstrates genuine understanding | No — already counted in PROF.Index | **Yes** |
| Reveals a competency not originally claimed anywhere in the profile | **Yes** — new `Statement`/`Evidence(type: "probe_answer")` created | **Yes** — the fact that it surfaced under live, unprepared questioning is itself a confirmation signal, not merely a new declaration |
| Fails Semantic Depth even after one follow-up, or is declined/skipped | No | No — remains `not_started`/`limited` (0, never negative) |

| ID | Requirement |
|---|---|
| FR6.2 | These two signals are not mutually exclusive and not derived from a single "answer quality" score — implement them as two independent boolean evaluations against the same answer content, not one score thresholded twice. |
| FR6.3 | When `new_competency_signal` is true, this module creates/updates a Module 2 `Statement` and an `Evidence(type: "probe_answer")` pair so it flows into Module 3's next `PROFIndexSnapshot` recompute without any manual step. |
| FR6.4 | **Non-punitive rule (hard constraint, carried from Ch.6):** an unanswered, skipped, declined, or "failed" probe never produces a negative score anywhere — only `not_started`/`limited` status persists. Nothing in this module may implement a penalty path. |

---

## 6. UI Flow (already substantially prototyped — extend these screens, don't redesign)

1. `minicaseQuestion` → primary probe screen: question text + `reason_ru` (US4, new — not yet in wireframe, see gap below), answer textarea (US3), `"Ответить"` / `"Пропустить"` / new `"Это касается NDA"` (US5), plus `"Вопрос не подходит"` feedback trigger.
2. `questionFeedback` → satisfies §4.5 directly, reason set already matches verbatim. On submit, regenerates the question (back to `minicaseQuestion`).
3. `targetedEvidence` → the point where a probe question is presented alongside Module 2's link/file alternatives — concrete evidence that Contextual Probe and One-Click Enrichment are one integrated evidence-gathering surface, not two flows the candidate must reconcile.
4. `evidenceMap` → downstream display only; must surface `reason_ru`/question history per FR4.4, through Module 3's existing status computation.

**Gaps vs. current wireframe (must be added, not new screens — extend `minicaseQuestion`):**
- The "why this question" explanation line (US4/FR4.1) is not currently rendered anywhere in the probe screen — add it directly under the question text.
- The `"Это касается NDA"` action (US5/FR5.1) does not exist yet — add as a secondary action next to `"Пропустить"`, distinct from it.
- The Semantic Depth follow-up (FR-Int.1) has no current screen state — render inline on `minicaseQuestion` after submission, not as a new route.

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication:** same single implicit local session as Modules 2–3.
- **Pluggable generation backend:** implement question generation behind a single interface (`generateQuestion(competency, artifacts, mode: "artifact_grounded" | "ndaAbstract" | "fallback_template") → Question`) so the still-open local-inference-vs-API decision (Backlog #11) can be resolved later without touching calling code. The `ndaAbstract` mode is what FR5.2 invokes.
- **Keystroke Dynamics feature flag:** ship the capture hook disabled by default. Keystroke Dynamics requires legal review before launch (Ch.12) — a launch blocker for MVP-0, not just later versions. Treat "off" as the only safe default until legal sign-off is confirmed in writing.
- **Recompute-on-read for downstream signals:** `Answer.routing` outputs written immediately on submission, so Module 3's next PROF.Index view reflects a new competency signal without any manual sync step.

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| Local vs. API inference for question generation (Backlog #11) | Decision rule already fixed in the CTO brief: if a local open-weight model (Qwen2.5/3, Mistral Small, or current-gen Llama at evaluation time) matches GPT-4o-mini-level question quality within a 3–4 week setup window, ship local and budget GPU infra up front; otherwise external API is the fallback, gated on explicit candidate consent to third-party data transfer before launch, not retroactively. Build against the pluggable interface (§7) regardless of which side this resolves to. |
| Reward mechanic for confirmed question-quality bugs (Backlog #25) | Ops/calibration process (Ch.13) — this module only captures the raw `QuestionFeedback` data. |
| Digital Echo-sourced contradiction targets | Depends on Module 8/9 (not built); this module accepts the `target_type: "contradiction"` shape but has no producer yet. |
| Keystroke Dynamics scoring/comparison against baseline | Module 6 (Trust Score) — this module only captures the raw signal, behind a flag, pending legal clearance. |
| Jargon Trap template authoring at scale | MVP ships a small hand-authored set for the Backend/Fullstack segment; broader authoring tooling is future scope. |
| Local on-device competency-hash analyzer as an NDA alternative | [V3] — not needed for MVP since US5 + Module 2's Blind Witness/Mirror Tasks already fully close the NDA gap without it. |

---

**H1 hypotheses this module should let you test (not guarantees):**
- H1 (Understanding signal validity): artifact-grounded questions (FR2.2 primary path) produce answers harder to game with a generic AI assistant than the template-only fallback path (FR2.4) — instrument both paths separately from the start so this is measurable, not assumed.
- H1 (Question quality): `"Вопрос не подходит"` feedback rate per `template_id` is trackable, giving a concrete signal for which templates need revision before wider rollout (Ch.13 feedback loop).
- H1 (NDA path adoption): rate at which candidates choose `"Это касается NDA"` vs. plain skip, and whether they subsequently accept the rephrased question — a low acceptance rate on the rephrase would suggest the abstraction isn't reading as genuinely NDA-safe.
