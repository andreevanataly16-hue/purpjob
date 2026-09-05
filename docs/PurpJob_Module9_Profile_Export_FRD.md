# PurpJob — Module 9: Professional Profile Export
## Functional Requirements Document (FRD) — Local MVP, No-Auth Phase

**Status:** [MVP-0]
**Phase:** Local prototype (no authentication layer, no persistent backend, single local candidate session)
**Depends on:** Module 2 (`Evidence`/`Statement` content), Module 3 (`PROFIndexSnapshot`, `VisibilityState`), Module 6 (`TrustScoreSnapshot`, positioning constraint)
**Does not depend on / does not build:** the recruiter-side browser plugin and its widget overlay (Ch.19) — that's a materially different, MVP-1-tagged feature; do not conflate it with this module (see §0)

---

## ⚠️ 0. Discrepancy flag — scope of export needs an explicit decision before building

Two source documents describe export at very different levels of ambition, and I'm flagging this the same way I did for Module 5's NDA-flow discrepancy — don't let it get silently resolved by whichever developer builds it first.

| Source | What it describes |
|---|---|
| Master document's own MVP tag summary (Ch.5) | *"экспорт резюме с Trust Score **(1 формат)**"* — singular, one format only. |
| `Новый_документ.md` | A much richer export UX: **3 length variants** (Короткое/Стандартное/Подробное) × **4 file types** (PDF/DOCX/JSON/public Link), plus a full visibility-mode selection flow bundled into the same screen. |

`Новый_документ.md` also describes the **recruiter-side plugin's** floating widget, "honest traffic light" verification-status indicator, and the "Запросить верификацию" invite-link mechanism — all of which the master document's own tag summary places under **Ch.19, explicitly MVP-1 in its entirety**, not this module.

**This FRD builds to the narrower, explicitly-MVP-0-tagged reading: one file format, one length variant.** I'm treating `Новый_документ.md`'s fuller matrix as a V1.5/V2 candidate design, not a contradicted-but-still-current MVP-0 spec — but this is exactly the kind of scope call that should come from you, not get assumed. If the richer matrix was actually meant for MVP-0, this FRD needs a rewrite before development starts, and it's a meaningfully bigger build (template system for 3 lengths, plus DOCX/JSON generation, plus public link hosting — the last of which doesn't have a home yet in a no-auth local phase, see §2.2).

---

## 1. Purpose

The exported profile is the concrete, portable proof of everything Modules 2–8 accumulate — it's what makes the whole system's output *usable* the moment the candidate steps outside PurpJob, without which all the accumulated Evidence and Trust would be trapped inside a platform a recruiter has no reason to visit yet. Per the master document's own framing of this as a Cold Start driver: this is "proof you can take with you," not a locked-in platform feature.

**Product principle mapping:**

| Principle | How this module implements it |
|---|---|
| P2 — Automation | The export is generated from accumulated structured data, never a manual rewrite exercise per vacancy (US2). |
| P1 — Evidence-Based Hiring | Trust Score and its legend travel with the document, so the "why believe this" context isn't lost outside the platform (US3). |
| Data ownership (cross-cutting, established in Modules 2/5/8) | The candidate is the only one who ever sends this document anywhere — the platform never distributes on their behalf (US4). |

---

## 2. Scope

### 2.1 In scope (this module, local MVP)
- Export to exactly **one file format: PDF** (US1) — matching the master document's own "1 формат" tag
- Automatic, template-driven generation from the candidate's current `Statement`/`Evidence`/`PROFIndexSnapshot`/`TrustScoreSnapshot` data — no manual text-editing step inside this module (US2)
- Trust Score number **and** the already-established static legend paragraph included in every export (US3)
- Hard guarantee that this module never transmits the exported document anywhere on the candidate's behalf — output is a local, downloadable file only (US4)

### 2.2 Out of scope (explicitly deferred)
- Additional file types (DOCX, JSON, public shareable Link) and additional length variants (Короткое/Подробное) — per §0, treated as a later-phase richer export matrix, not confirmed MVP-0 scope
- The recruiter-side browser plugin, its floating widget, "honest traffic light" verification-status display, and "Запросить верификацию" invite mechanism — all Ch.19, explicitly MVP-1 in its entirety, a different module with a different (recruiter-facing) audience
- Public profile widget embed for LinkedIn/Telegram bios — requires public hosting/a stable public URL, which doesn't exist in this local, no-auth phase (no backend to host anything publicly from); the "Link" export type in §0's fuller matrix would depend on this same missing infrastructure
- Any "send via email"/"submit to job board" convenience action — deliberately excluded, not merely unbuilt (US4 makes this a hard constraint, not a backlog item)
- Analytics/read-tracking on the exported document (e.g. "recruiter opened your PDF") — would conflict with US4's data-ownership guarantee if built without separate, explicit candidate consent; not built here

---

## 3. Localization

**This FRD is in English for development purposes only. The product is fully Russian.**

| Layer | Language |
|---|---|
| Code: entity/field names, enum values (`format: "pdf"`, `include_contacts`) | English |
| All content inside the exported PDF, all UI copy for the export flow | **Russian**, matching the register already established across Modules 2–8 |

**Reuse the already-established static Trust Score legend verbatim — do not rewrite it, and do not personalize/dynamically generate it (it is explicitly a static paragraph per the source spec, not a per-candidate explanation):**

> *"Trust Score - показатель достоверности профессионального профиля, рассчитанный на основе анализа цифрового следа и подтверждения ключевых компетенций через контекстные микро-кейсы. Не заменяет интервью, но даёт дополнительный слой информации о том, что заявленные навыки подтверждены независимыми источниками."*

This legend must ship exactly as established in Module 6 — this module is simply its second consumer (the first being Module 6's own PDF-legend framing reference), not a place to draft a new variant.

Content structure can draw on the example format already sketched in `Новый_документ.md` for tone/density even though the fuller matrix itself is deferred (§0) — e.g. the short-format example (name, role, PROF.Index, Trust Score, key skills, 1–2 projects, contact block) is a reasonable content model for the single MVP-0 template, just not literally "the short one of three."

---

## 4. Data Model

Local-first constraint, consistent with Modules 2–8: this module reads other modules' data at generation time; it writes only a lightweight `ExportRequest` record for traceability, no export-specific business data of its own.

### 4.1 `ExportRequest`
```json
{
  "id": "exp_001",
  "format": "pdf",
  "include_contacts": true,
  "source_refs": {
    "prof_index_snapshot": { "segment": "Backend/Fullstack (Python/Go)", "level": "Middle" },
    "trust_score_version": 3
  },
  "generated_at": "ISO8601"
}
```
- `include_contacts` is a **candidate choice made at export time**, independent of Module 3's `VisibilityState` (`visible`/`hidden`) — exporting a document to send yourself directly is a different decision from opting into platform-wide search visibility; do not conflate the two toggles or let one silently control the other (see FR4.4).
- `source_refs` records which underlying snapshots fed this specific export, purely for the candidate's own later reference (e.g. "this PDF reflects my profile as of the version where Trust was 63") — this module does not need its own versioning scheme; it just points at Module 3/6's existing ones.
- No `sent_to`/`recipient`/delivery-status field exists anywhere in this model — deliberately, per US4 (§2.2, FR4.1–4.3).

---

## 5. Functional Requirements

### US1 — Export the profile in a familiar format for use outside PurpJob

| ID | Requirement |
|---|---|
| FR1.1 | This module supports exactly one export format in this phase: **PDF** — a plain, standard file openable in any conventional PDF viewer, with zero dependency on PurpJob to read it afterward. |
| FR1.2 | The PDF must look and read like a conventional professional resume/profile summary — not a raw data export or a screenshot of an in-app screen — since "familiar format" is explicitly the point of US1: a recruiter unfamiliar with PurpJob must be able to make sense of it without any platform context. |
| FR1.3 | No proprietary lock-in: the resulting file must be a genuinely portable artifact — nothing about its content or format requires PurpJob to interpret, verify, or "unlock" it later. |

**Acceptance criteria:** a candidate can produce a standard PDF file, save/open it with any generic PDF reader, and it reads as a coherent, self-contained professional profile with no broken references back to the platform.

---

### US2 — Get a PDF resume auto-generated from the profile, no manual rewriting per vacancy

| ID | Requirement |
|---|---|
| FR2.1 | Generation is fully automatic: given a candidate's current `Statement`/`Evidence`/`PROFIndexSnapshot`/`TrustScoreSnapshot` state, the system produces the PDF with **no manual text-entry step** inside this module — the candidate does not write or rewrite resume prose here; the system assembles it from already-structured profile data. |
| FR2.2 | Content selection for the single MVP-0 template is deterministic and rule-based, not left to a manual editor: name/declared role, overall PROF.Index and Trust Score numbers, the Trust Score legend (US3), a compact skills/competency list (from Module 3's `CompetencyResult`, ordered by `weight`), and a small number of key projects (from Module 2 `Statement`/`Evidence`, e.g. the strongest-evidenced ones) — pick and document a specific, simple selection rule rather than leaving "which projects" undefined. |
| FR2.3 | Re-exporting at any later point always reflects the **current, live** profile state (Module 8's persistence/live-read guarantee extends here) — there is no cached, stale copy retained by this module; every export is freshly generated from whatever is true right now. |
| FR2.4 | This module does not provide in-app resume editing (rewording a project description, reordering sections) — if the candidate wants a different narrative than the deterministic template produces, that's outside this module's scope in this phase (a DOCX-editable format would be the natural home for that, and is explicitly deferred per §2.2). |

**Acceptance criteria:** a candidate with an existing profile can generate a PDF with zero manual writing, and generating it again later (after adding new Evidence) produces an updated document reflecting the new state, not the old one.

---

### US3 — See Trust Score and a brief explanation of its meaning in the exported profile

| ID | Requirement |
|---|---|
| FR3.1 | Every generated PDF includes the current overall Trust Score number **and** the static legend paragraph (§3) verbatim — never the number alone. |
| FR3.2 | The legend text is fixed and static, not dynamically generated or personalized per candidate — this is a deliberate simplification already decided in the source material, not a gap to fill with a smarter per-profile explanation (that's Module 7's `Explanation` object, a different context serving a different, in-platform audience). |
| FR3.3 | The legend must preserve the exact positioning constraint already established in Module 6: Trust Score does not replace an interview, it adds a layer of information about how well the claimed skills are independently confirmed — do not let this get abbreviated or reworded down to just the number plus a generic "verified" badge, which would misrepresent what the score actually claims to do. |

**Acceptance criteria:** every export contains the same fixed legend text alongside the Trust Score number, unchanged across candidates and across repeated exports for the same candidate.

---

### US4 — Send the profile to an employer/recruiter without PurpJob auto-distributing it

| ID | Requirement |
|---|---|
| FR4.1 | **Hard constraint:** no code path in this module emails, uploads, submits, posts, or otherwise transmits the exported PDF to any third party (a specific recruiter, a job board, an ATS) on the candidate's behalf. The only artifact this module ever produces is a file made available for the candidate to download — distribution is entirely the candidate's own subsequent action, outside this module. |
| FR4.2 | Even a plausible future convenience feature ("email this to a recruiter directly from PurpJob") is explicitly out of scope here, not merely unbuilt — if it's ever added, it would need its own explicit, per-instance candidate confirmation before every single send, consistent with how the platform already treats any action that acts on the candidate's behalf elsewhere in the product; this module in its current form has no such feature at all. |
| FR4.3 | The exported PDF must not embed any tracking mechanism (read receipts, analytics pixels, unique per-recipient links) that would let PurpJob learn when/where the document was subsequently opened — building that without a separate, explicit consent flow would quietly violate the same data-ownership principle this requirement exists to protect, so it's simply not built here. |
| FR4.4 | `include_contacts` (§4.1) is a per-export candidate choice, entirely independent of Module 3's platform-search `VisibilityState` — a candidate in `hidden`/Self-Audit mode on the platform can still generate a full-contact-info export for their own direct, manual use, and a `visible`-mode candidate can still choose to omit contacts from a specific export. These two controls must never be wired together implicitly. |

**Acceptance criteria:** generating and downloading an export never results in any outbound transmission initiated by the system itself — the file exists locally, fully under the candidate's control, and nothing in the codebase can be traced to an automatic send.

---

## 6. UI Flow

No dedicated export screen exists yet in `purpjob-wireframe-v3.jsx` beyond the "Скачать резюме"-style intent referenced conceptually in the CJM. New, minimal UI needed for MVP-0's single-format scope:

1. **New screen/action: "Скачать резюме (PDF)"** — a single, low-ceremony action (not a multi-step format-selection wizard, since there's only one format and one length variant in this phase per §0) — a toggle for `include_contacts` is the only meaningful choice surfaced, everything else is automatic.
2. **Preview before download** — show what will be generated (reusing the master doc's own short-form example content shape for reference) before committing to the file, so the candidate isn't surprised by what's included.
3. **No separate "publish"/visibility-mode entanglement on this screen** — Module 3's visibility settings remain a separate, dedicated flow; this screen must not silently bundle a visibility-mode change into an export action (per FR4.4).

---

## 7. Non-Functional / Technical Constraints (local, no-auth phase)

- **No authentication:** same single implicit local session as Modules 2–8.
- **Local generation:** PDF generation can run entirely client-side or via a local process in this prototype — no need for a hosted rendering service given local-only data volumes and no multi-user concern yet.
- **No persistent "sent" state:** consistent with FR4.1–4.3, this module's data model (§4.1) intentionally has no field for delivery/recipient tracking — resist the urge to add one "just in case," since its presence would itself be an early step toward the auto-distribution this module explicitly rules out.
- **Template as a single, versionable asset:** the deterministic content-selection rule (FR2.2) should live in one clearly identified template definition, not scattered inline logic — makes it straightforward to extend into the fuller format matrix later (§0) without a rewrite, if that's the direction confirmed.

---

## 8. Explicitly Deferred / Open Questions

| Item | Why deferred |
|---|---|
| **§0 discrepancy resolution** (1 format vs. the fuller 3×4 matrix) | Needs an explicit founder confirmation of actual MVP-0 scope before the richer version is attempted — this FRD builds the narrower reading. |
| DOCX / JSON / public Link export formats | Per §0, treated as V1.5/V2 — Link format specifically also needs public hosting infrastructure this local phase doesn't have. |
| Recruiter-side plugin, widget, "honest traffic light," "Запросить верификацию" | Ch.19, explicitly MVP-1 in its entirety — a different module, different audience, not to be built alongside this one. |
| Public LinkedIn/Telegram profile widget embed | Depends on the same missing public-hosting infrastructure as the Link format. |
| Any recruiter-facing delivery/tracking feature | Deliberately excluded per US4, not a "not yet" item — would need a dedicated future decision and explicit consent design, not an incremental addition to this module. |

---

**H1 hypothesis this module feeds (per Ch.15's Cold Start framing, not a guarantee):**
- Self-Audit and export are meant to be valuable to the candidate on their own, with zero dependency on a recruiter existing on the platform yet — the real test is whether candidates actually generate and use this export (send it themselves, reference the Trust Score number in an outside conversation) rather than treating the whole profile as something that only matters inside PurpJob. Worth instrumenting export-generation and (candidate-reported, since delivery isn't tracked by design, FR4.3) downstream usage separately from in-platform engagement metrics.
