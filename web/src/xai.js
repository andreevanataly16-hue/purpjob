/* «Почему такой вывод?» и спор с ним (модуль 7).

   Один экран объяснения на весь продукт. Откуда бы ни пришёл вывод — из
   PROF.индекса, из Trust Score, из нестыковки или из вопроса — кандидат
   нажимает одну и ту же ссылку и попадает в одно и то же место. Три разных
   способа спросить «почему» для трёх модулей были бы ровно той проблемой,
   ради которой этот модуль и делался.

   Второе здешнее правило: у объяснения всегда есть кнопка спора. Вывода,
   с которым нельзя не согласиться, в продукте нет. */

import './xai.css'
import { api } from './api.js'
import { mutateDisputes } from './store.js'

const ui = { open: null, detail: null, loading: false, error: '', showStatement: false }

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

const WHY_LABEL = 'Почему такой вывод?'

/* Единственная точка входа. Её вставляют рядом с баллом и модуль 3, и модуль 6,
   и модуль 4 — поэтому она живёт здесь, а не переписывается в каждом файле. */
export function whyButton(explanationId, extraClass = '') {
  if (!explanationId) return ''
  return `<button type="button" class="why-btn ${extraClass}" data-act="why"
    data-explanation="${escape(explanationId)}">${WHY_LABEL}</button>`
}

/* Панель объяснения живёт сверху страницы, список споров - внизу: это
   разные места на экране, поэтому и заготовки разные. */
export const WHY_PANEL_SKELETON = `
  <div class="why-panel" id="why-panel" hidden>
    <div class="why-card" role="dialog" aria-modal="true" aria-labelledby="why-title">
      <div class="why-top">
        <h3 id="why-title">${WHY_LABEL}</h3>
        <button type="button" class="link-btn" data-act="why-close">Закрыть</button>
      </div>
      <div id="why-body"></div>
    </div>
  </div>
`

export const DISPUTES_SKELETON = `
  <section class="block" id="disputes-block">
    <h2>Спорные выводы</h2>
    <p class="sub" id="disputes-note"></p>
    <div id="disputes-body"></div>
    <p class="msg" id="disputes-msg"></p>
  </section>
`

/* ---------- экран объяснения ---------- */

function evidenceRow(item) {
  if (!item.resolved) {
    return `
      <div class="why-ev broken">
        <span class="why-ev-title">${escape(item.title_ru)}</span>
        <p class="why-ev-detail">${escape(item.detail_ru)}</p>
      </div>`
  }

  const link = item.url
    ? `<a href="${escape(item.url)}" target="_blank" rel="noreferrer noopener">${escape(item.url)}</a>`
    : ''

  return `
    <div class="why-ev">
      <span class="why-ev-title">${escape(item.title_ru)}</span>
      <span class="chip grey">${escape(item.ref)}</span>
      ${link}
      ${item.detail_ru ? `<p class="why-ev-detail">${escape(item.detail_ru)}</p>` : ''}
    </div>`
}

function detailBody(detail) {
  const evidence = detail.resolved_evidence.length
    ? detail.resolved_evidence.map(evidenceRow).join('')
    : `<p class="why-none">
         Доказательств за этим выводом нет — и это сказано прямо в самом выводе,
         а не спрятано пустым списком.
       </p>`

  const problems = detail.problems.length
    ? `<div class="why-problems">
         <b>Само объяснение неисправно:</b> ${escape(detail.problems.join('; '))}.
       </div>`
    : ''

  const dispute = detail.open_dispute_id
    ? `<div class="why-disputed">
         Этот вывод уже на проверке (${escape(detail.open_dispute_id)}). Статус и ход разбора —
         в блоке «Спорные выводы» ниже.
       </div>`
    : `
      <div class="why-actions">
        <button type="button" class="action" data-act="dispute-open">
          ${escape(detail.dispute_label_ru)}
        </button>
        <span class="why-hint">Объяснять, почему вы не согласны, не обязательно.</span>
      </div>
      ${ui.showStatement ? `
        <textarea class="probe-input" id="dispute-statement"
          placeholder="Если хотите — напишите, в чём именно ошибка. Можно оставить пустым."></textarea>
        <div class="why-actions">
          <button type="button" class="action" data-act="dispute-send">Передать на модерацию</button>
          <button type="button" class="link-btn" data-act="dispute-cancel">Отмена</button>
        </div>` : ''}`

  return `
    <div class="why-subject">
      <span class="chip grey">${escape(detail.subject_type_ru)}</span>
      <span class="why-subject-name">${escape(detail.subject_label_ru)}</span>
      <span class="why-subject-value">${escape(detail.subject_value_ru)}</span>
    </div>

    <p class="why-conclusion">${escape(detail.conclusion_ru)}</p>
    ${problems}

    <h4 class="why-h">На чём это основано</h4>
    ${evidence}

    ${dispute}

    <p class="why-source">Вывод сделал ${escape(detail.generated_by)}.</p>
  `
}

function renderPanel() {
  const panel = $('why-panel')
  if (!panel) return

  panel.hidden = !ui.open
  if (!ui.open) return

  const box = $('why-body')
  if (ui.loading) {
    box.innerHTML = '<p class="why-none">Собираем объяснение…</p>'
    return
  }
  if (ui.error) {
    box.innerHTML = `<p class="why-none">${escape(ui.error)}</p>`
    return
  }
  if (ui.detail) box.innerHTML = detailBody(ui.detail)
}

async function openExplanation(explanationId) {
  ui.open = explanationId
  ui.detail = null
  ui.error = ''
  ui.showStatement = false
  ui.loading = true
  renderPanel()

  const result = await api(`/api/explanations/${encodeURIComponent(explanationId)}`)
  ui.loading = false
  if (result.ok) ui.detail = result.payload
  else ui.error = result.payload?.detail || 'Не удалось открыть объяснение.'
  renderPanel()
}

/* ---------- список споров ---------- */

function historyRow(entry) {
  const change = entry.before_value || entry.after_value
    ? `<span class="dispute-change">${escape(entry.before_value ?? '—')} → ${escape(entry.after_value ?? '—')}</span>`
    : ''

  return `
    <li>
      <span class="dispute-when">${new Date(entry.timestamp).toLocaleString('ru-RU')}</span>
      <b>${escape(entry.event_ru)}</b>
      <span class="chip grey">${escape(entry.actor_ru)}</span>
      ${change}
      ${entry.note_ru ? `<p class="dispute-note">${escape(entry.note_ru)}</p>` : ''}
    </li>`
}

function disputeCard(item) {
  const answer = item.status === 'needs_more_info'
    ? `
      <div class="dispute-ask">
        <p class="dispute-question">${escape(item.info_request_ru)}</p>
        <textarea class="probe-input" id="reply-${escape(item.id)}"
          placeholder="Ответьте на этот вопрос — так модератору не придётся гадать"></textarea>
        <button type="button" class="action" data-act="dispute-reply" data-case="${escape(item.id)}">
          Ответить модератору
        </button>
      </div>`
    : ''

  const override = item.override
    ? `<div class="dispute-override">
         Исправлено: ${escape(item.override.target_id)} — было ${escape(item.override.previous_value)},
         стало ${escape(item.override.new_value)}. Причина: ${escape(item.override.rationale_ru)}
       </div>`
    : ''

  return `
    <div class="dispute">
      <div class="dispute-head">
        <span class="chip grey">${escape(item.subject_type_ru)}</span>
        <span class="dispute-status ${escape(item.status)}">${escape(item.status_ru)}</span>
        <button type="button" class="link-btn" data-act="why"
          data-explanation="${escape(item.explanation_id)}">${WHY_LABEL}</button>
      </div>
      <p class="dispute-conclusion">${escape(item.conclusion_ru)}</p>
      ${item.candidate_statement
        ? `<p class="dispute-note">Вы написали: ${escape(item.candidate_statement)}</p>`
        : ''}
      ${override}
      ${answer}
      <details class="dispute-history">
        <summary>Ход разбора (${item.history.length})</summary>
        <ul>${item.history.map(historyRow).join('')}</ul>
      </details>
    </div>`
}

export function renderXai(state) {
  renderPanel()

  const box = $('disputes-body')
  if (!box || !state.disputes) return

  $('disputes-note').textContent = state.disputes.note_ru

  box.innerHTML = state.disputes.cases.length
    ? state.disputes.cases.map(disputeCard).join('')
    : `<div class="empty">
         Пока ничего не оспорено. Кнопка «${WHY_LABEL}» есть рядом с каждым баллом и статусом —
         с любым выводом можно не согласиться.
       </div>`
}

/* ---------- действия ---------- */

function message(text, kind = 'error') {
  const box = $('disputes-msg')
  if (!box) return
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

async function onClick(event) {
  const trigger = event.target.closest('[data-act]')
  if (!trigger) return

  const { act, explanation, case: caseId } = trigger.dataset

  if (act === 'why') {
    await openExplanation(explanation)
    return
  }

  if (act === 'why-close') {
    ui.open = null
    ui.detail = null
    ui.showStatement = false
    renderPanel()
    return
  }

  if (act === 'dispute-open') {
    ui.showStatement = true
    renderPanel()
    return
  }

  if (act === 'dispute-cancel') {
    ui.showStatement = false
    renderPanel()
    return
  }

  if (act === 'dispute-send') {
    const text = $('dispute-statement')?.value.trim() || ''
    const result = await mutateDisputes('/api/disputes', {
      method: 'POST',
      body: JSON.stringify({
        explanation_id: ui.open,
        // Пустое поле остаётся пустым: обоснование необязательно.
        candidate_statement: text || null
      })
    })

    if (result.ok) {
      ui.open = null
      ui.detail = null
      ui.showStatement = false
      renderPanel()
      message('Передали на проверку. Балл и статус при этом не изменились.', 'ok')
    } else {
      ui.error = result.payload?.detail || 'Не удалось передать на модерацию.'
      renderPanel()
    }
    return
  }

  if (act === 'dispute-reply') {
    const field = $(`reply-${caseId}`)
    const text = field?.value.trim() || ''
    if (text.length < 2) {
      message('Напишите ответ — пары слов достаточно.')
      return
    }
    message('')
    const result = await mutateDisputes(`/api/disputes/${caseId}/reply`, {
      method: 'POST',
      body: JSON.stringify({ text })
    })
    if (!result.ok) message(result.payload?.detail || 'Не удалось отправить ответ.')
  }
}

export function initXai({ root }) {
  root.addEventListener('click', onClick)

  // Панель закрывается кликом по подложке и клавишей Esc: модальное окно,
  // из которого нельзя выйти привычным способом, раздражает сильнее,
  // чем помогает.
  root.addEventListener('click', event => {
    if (event.target.id === 'why-panel') {
      ui.open = null
      renderPanel()
    }
  })
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && ui.open) {
      ui.open = null
      renderPanel()
    }
  })
}

export function resetXai() {
  ui.open = null
  ui.detail = null
  ui.showStatement = false
  ui.error = ''
}
