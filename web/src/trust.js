/* Trust Score: насколько достоверно то, что написано в профиле (модуль 6).

   Экран показывает не только число, но и то, из чего оно сложилось: у каждого
   компонента — проверяемый факт, а не оценка. Ничто здесь не отнимает баллов:
   пропуск, отказ и нерешённая нестыковка просто не добавляют. */

import './trust.css'
import { mutateTrust } from './store.js'

const PATHS = {
  delete_artifact: 'Удалить артефакт',
  explain: 'Пояснить',
  correct_claim: 'Поправить заявление'
}

const ui = { openCase: null, path: null }

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

export const TRUST_SKELETON = `
  <section class="block" id="trust-block">
    <h2>Trust Score</h2>
    <p class="sub">
      Не «насколько вы хороший специалист», а «насколько можно верить тому, что
      написано в профиле». Балл не падает ни от одного вашего действия: пропуск и
      отказ просто ничего не добавляют.
    </p>
    <div id="trust-body"></div>
    <p class="msg" id="trust-msg"></p>
  </section>
`

/* ---------- компоненты ---------- */

function componentCard(item) {
  return `
    <div class="trust-component">
      <div class="top">
        <span class="name">${escape(item.name_ru)}</span>
        <span class="score">${item.score}</span>
      </div>
      <div class="trust-bar"><i style="width:${item.score}%"></i></div>
      <p class="why">${escape(item.explanation_ru)}</p>
      ${item.notes_ru.map(note => `<p class="note">${escape(note)}</p>`).join('')}
      ${item.contributing_evidence_ids.length
        ? `<p class="trust-sources">Считались доказательства: ${
            item.contributing_evidence_ids.map(id => escape(id)).join(', ')
          }</p>`
        : ''}
    </div>`
}

/* ---------- нестыковки ---------- */

function contradictionCard(item) {
  if (item.status === 'resolved') {
    return `
      <div class="contradiction resolved">
        <p class="detail">${escape(item.detail_ru)}</p>
        <div class="chips">
          <span class="chip grey">разобрано: ${escape(PATHS[item.resolution_path] || item.resolution_path)}</span>
        </div>
        ${item.explanation_text ? `<p class="bw-answered">${escape(item.explanation_text)}</p>` : ''}
        ${item.corrected_value ? `<p class="bw-answered">Поправлено на: ${escape(item.corrected_value)}</p>` : ''}
      </div>`
  }

  const open = ui.openCase === item.id
  const form = open && ui.path === 'explain'
    ? `<textarea class="probe-input" id="cc-explanation"
         placeholder="Что тут на самом деле — пары фраз достаточно"></textarea>
       <div class="nda-actions">
         <button type="button" class="action" data-act="cc-send" data-case="${item.id}"
           data-path="explain">Сохранить пояснение</button>
       </div>`
    : open && ui.path === 'correct_claim'
      ? `<input type="text" id="cc-correction" placeholder="Как правильно — например, Middle">
         <div class="nda-actions">
           <button type="button" class="action" data-act="cc-send" data-case="${item.id}"
             data-path="correct_claim">Поправить</button>
         </div>`
      : ''

  return `
    <div class="contradiction">
      <p class="detail">${escape(item.detail_ru)}</p>
      <div class="paths">
        <button type="button" class="ghost" data-act="cc-send" data-case="${item.id}"
          data-path="delete_artifact">${PATHS.delete_artifact}</button>
        <button type="button" class="ghost" data-act="cc-open" data-case="${item.id}"
          data-path="explain">${PATHS.explain}</button>
        <button type="button" class="ghost" data-act="cc-open" data-case="${item.id}"
          data-path="correct_claim">${PATHS.correct_claim}</button>
      </div>
      ${form}
      <p class="sub" style="margin:10px 0 0">
        Можно и не разбирать сейчас — компетенция просто останется неподтверждённой.
      </p>
    </div>`
}

/* ---------- весь блок ---------- */

export function renderTrust(state) {
  if (!state.trust || !$('trust-body')) return

  const trust = state.trust
  const box = $('trust-body')

  box.innerHTML = `
    <div class="trust-head">
      <span class="trust-value">${trust.overall_score}</span>
      <span class="trust-of">из 100 — достоверность сведений профиля</span>
    </div>

    <div class="trust-components">
      ${trust.components.map(componentCard).join('')}
    </div>

    ${trust.next_actions.length ? `
      <h3 style="margin:22px 0 10px;font-size:15px">Следующее лучшее действие</h3>
      ${trust.next_actions.slice(0, 3).map(action => `
        <div class="trust-action">
          <span>${escape(action.text_ru)}</span>
        </div>`).join('')}` : ''}

    ${trust.findings.length ? `
      <h3 style="margin:22px 0 10px;font-size:15px">Это ваши источники?</h3>
      ${trust.findings.map(finding => `
        <div class="finding">
          <span>${escape(finding.finding_text_ru)}</span>
          <button type="button" class="ghost" data-act="finding" data-id="${finding.id}"
            data-response="confirmed">Подтвердить</button>
          <button type="button" class="link-btn" data-act="finding" data-id="${finding.id}"
            data-response="not_me_or_outdated">Это не я / не актуально</button>
        </div>`).join('')}` : ''}

    ${trust.contradictions.length ? `
      <h3 style="margin:22px 0 10px;font-size:15px">Нестыковки в профиле</h3>
      ${trust.contradictions.map(contradictionCard).join('')}` : ''}

    <p class="trust-legend">${escape(trust.legend_ru)}</p>
  `
}

/* ---------- действия ---------- */

function message(text, kind = 'error') {
  const box = $('trust-msg')
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

async function onTrustClick(event, state) {
  const trigger = event.target.closest('#trust-block [data-act]')
  if (!trigger) return

  const { act, id, response, case: caseId, path } = trigger.dataset

  if (act === 'finding') {
    message('')
    const result = await mutateTrust(`/api/trust/findings/${id}/respond`, {
      method: 'POST',
      body: JSON.stringify({ response })
    })
    if (result.ok && response === 'not_me_or_outdated') {
      message('Убрали. На балл это никак не влияет.', 'ok')
    }
    return
  }

  if (act === 'cc-open') {
    ui.openCase = caseId
    ui.path = path
    renderTrust(state)
    return
  }

  if (act === 'cc-send') {
    const body = { path }
    if (path === 'explain') {
      const text = $('cc-explanation')?.value.trim() || ''
      if (text.length < 5) {
        message('Напишите пару слов — что тут на самом деле.')
        return
      }
      body.explanation_text = text
    }
    if (path === 'correct_claim') {
      const value = $('cc-correction')?.value.trim() || ''
      if (!value) {
        message('Укажите, как правильно.')
        return
      }
      body.corrected_value = value
    }

    message('')
    const result = await mutateTrust(`/api/trust/contradictions/${caseId}/resolve`, {
      method: 'POST',
      body: JSON.stringify(body)
    })
    ui.openCase = null
    ui.path = null
    if (!result.ok) message(result.payload?.detail || 'Не удалось сохранить.')
  }
}

export function initTrust({ getState, root }) {
  root.addEventListener('click', event => onTrustClick(event, getState()))
}

export function resetTrust() {
  ui.openCase = null
  ui.path = null
}
