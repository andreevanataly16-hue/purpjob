/* Contextual Probe: один вопрос по неподтверждённой компетенции (модуль 4).

   Экран ничего не решает сам: какой вопрос задать, почему именно его и что
   значит ответ - приходит с сервера. Здесь только показать вопрос вместе с
   объяснением, не дать вставить ответ из буфера и отправить написанное. */

import './probe.css'
import { api } from './api.js'
import { mutateProbe } from './store.js'
import { whyButton } from './xai.js'

const TRIGGER_RU = {
  too_generic: 'нужна конкретика',
  jargon_trap: 'не хватает детали'
}

const ui = {
  feedbackOpen: false,
  historyOpen: false,
  history: null,
  // Замеряем, сколько человек писал ответ, и сколько раз пытался вставить
  // текст. Это сырые данные для будущего модуля доверия, не оценка.
  typingStartedAt: null,
  pasteBlocked: 0,
  keystrokes: null
}

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

export const PROBE_SKELETON = `
  <section class="block" id="probe-block">
    <h2>Contextual Probe</h2>
    <p class="sub">
      Вопрос по компетенции, которой ещё не хватает подтверждений, — из ваших же
      материалов. Правильного ответа нет: важно, как вы объясняете решения.
      Пропустить можно всегда и без последствий.
    </p>
    <div id="probe-body"></div>
    <p class="msg" id="probe-msg"></p>
    <div class="history" id="probe-history"></div>
  </section>
`

/* ---------- вопрос ---------- */

function questionCard(question) {
  const origin = question.nda_abstract
    ? '<span class="chip nda">без привязки к проекту</span>'
    : question.grounded
      ? '<span class="chip">по вашему материалу</span>'
      : '<span class="chip grey">общий вопрос: подходящего материала не нашлось</span>'

  return `
    <article class="question">
      <p class="q-why">${escape(question.reason_ru)}</p>
      <p class="q-text">${escape(question.text_ru)}</p>
      <div class="q-meta">${origin} ${whyButton(question.explanation_id)}</div>

      <textarea class="probe-input" id="probe-answer"
        placeholder="Своими словами: что решали, почему именно так, что в итоге получилось"></textarea>
      <p class="probe-hint">
        Вставка из буфера отключена — нам важны ваши формулировки, а не найденный текст.
      </p>

      <div class="probe-actions">
        <button type="button" class="action" data-act="answer" data-q="${question.id}">Ответить</button>
        <button type="button" class="ghost" data-act="skip" data-q="${question.id}">Пропустить</button>
        <span class="spacer"></span>
        <button type="button" class="link-btn nda" data-act="nda" data-q="${question.id}">
          Это касается NDA
        </button>
        <button type="button" class="link-btn" data-act="open-feedback" data-q="${question.id}">
          Вопрос не подходит
        </button>
      </div>
    </article>
  `
}

function followUpCard(followUp) {
  return `
    <article class="question follow-up">
      <p class="q-why">
        ${escape(followUp.reason_ru)}
        <span class="chip grey">${TRIGGER_RU[followUp.trigger_reason] || followUp.trigger_reason}</span>
      </p>
      <p class="q-text">${escape(followUp.text_ru)}</p>

      <textarea class="probe-input" id="follow-up-answer"
        placeholder="Один-два конкретных примера: инструмент, решение, числа"></textarea>
      <p class="probe-hint">Это последнее уточнение по этой компетенции — дальше вопрос закроется.</p>

      <div class="probe-actions">
        <button type="button" class="action" data-act="answer-follow-up" data-fu="${followUp.id}">
          Ответить
        </button>
      </div>
    </article>
  `
}

function feedbackForm(state) {
  return `
    <div class="feedback-form">
      <h4>Что не так с вопросом?</h4>
      ${state.feedback_reasons.map((reason, index) => `
        <label>
          <input type="radio" name="probe-reason" value="${reason.value}" ${index === 0 ? 'checked' : ''}>
          ${escape(reason.label)}
        </label>`).join('')}
      <input type="text" id="probe-comment" placeholder="Комментарий — необязательно"
        style="width:100%;margin-top:8px">
      <div class="probe-actions">
        <button type="button" class="action" data-act="send-feedback" data-q="${state.question.id}">
          Отправить и получить другой
        </button>
        <button type="button" class="ghost" data-act="close-feedback">Отмена</button>
      </div>
    </div>
  `
}

function renderBody(state) {
  const box = $('probe-body')

  if (state.follow_up) {
    box.innerHTML = followUpCard(state.follow_up)
    return
  }

  if (state.question) {
    box.innerHTML = questionCard(state.question) + (ui.feedbackOpen ? feedbackForm(state) : '')
    return
  }

  if (state.next_target) {
    box.innerHTML = `
      <div class="probe-idle">
        <span>Следующий вопрос — про <b>${escape(state.next_target.name_ru)}</b>.</span>
        <button type="button" class="action" data-act="next">Задать вопрос</button>
      </div>`
    return
  }

  box.innerHTML = `<div class="empty">${escape(state.unavailable_reason || 'Сейчас спрашивать нечего.')}</div>`
}

/* ---------- история (FR4.4) ---------- */

function renderHistory(state) {
  const box = $('probe-history')
  const total = state.answered_count + state.skipped_count + state.declined_count

  if (!total && !ui.historyOpen) {
    box.innerHTML = ''
    return
  }

  const head = `
    <div class="history-head">
      <h3>История вопросов</h3>
      <span class="chip grey">отвечено: ${state.answered_count}</span>
      <span class="chip grey">пропущено: ${state.skipped_count}</span>
      <span class="chip nda">отклонено по NDA: ${state.declined_count}</span>
      <button type="button" class="link-btn" data-act="toggle-history">
        ${ui.historyOpen ? 'Свернуть' : 'Показать'}
      </button>
    </div>`

  if (!ui.historyOpen) {
    box.innerHTML = head
    return
  }

  const items = ui.history || []
  box.innerHTML = head + (items.length
    ? items.map(item => `
        <div class="history-item">
          <p class="q-why">${escape(item.reason_ru)}</p>
          <p class="q-text">${escape(item.text_ru)}</p>
          <div class="q-meta">
            <span class="chip grey">${escape(item.status_ru)}</span>
            ${whyButton(item.explanation_id)}
            ${item.understanding_signal ? '<span class="chip">понимание подтверждено</span>' : ''}
            ${item.new_competency_signal ? '<span class="chip">открыл новую компетенцию</span>' : ''}
          </div>
          ${item.answer_text ? `<p class="answer">${escape(item.answer_text)}</p>` : ''}
          ${item.follow_ups.map(followUp => `
            <p class="answer"><b>${escape(followUp.text_ru)}</b>${
              followUp.answer ? `\n${escape(followUp.answer)}` : ''
            }</p>`).join('')}
        </div>`).join('')
    : '<div class="empty">Вопросов пока не было.</div>')
}

export function renderProbe(state) {
  if (!state.probe || !$('probe-body')) return
  renderBody(state.probe)
  renderHistory(state.probe)
}

/* ---------- действия ---------- */

function message(text, kind = 'error') {
  const box = $('probe-msg')
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

function resetInputMetrics() {
  ui.typingStartedAt = null
  ui.pasteBlocked = 0
  ui.keystrokes = null
}

async function loadHistory() {
  const result = await api('/api/probe/history')
  ui.history = result.ok ? result.payload : []
}

async function sendAnswer(questionId, state) {
  const field = $('probe-answer')
  const text = field.value.trim()
  message('')

  if (text.length < 10) {
    message('Напишите ответ своими словами — хотя бы пару фраз.')
    return
  }

  const payload = {
    text,
    typed_duration_ms: ui.typingStartedAt ? Date.now() - ui.typingStartedAt : 0,
    paste_attempts_blocked: ui.pasteBlocked
  }
  // Клавиатурный почерк собирается только если сервер прямо разрешил.
  if (state.probe.keystroke_capture && ui.keystrokes) {
    payload.keystroke_meta = JSON.stringify(ui.keystrokes)
  }

  const result = await mutateProbe(`/api/probe/questions/${questionId}/answer`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })

  resetInputMetrics()
  if (!result.ok) {
    message('Не удалось отправить ответ. Попробуйте ещё раз.')
    return
  }
  if (ui.historyOpen) await loadHistory()
  message('Ответ сохранён.', 'ok')
}

async function sendFollowUp(followUpId) {
  const text = $('follow-up-answer').value.trim()
  message('')

  if (text.length < 5) {
    message('Пары слов хватит, но что-то написать нужно.')
    return
  }

  const result = await mutateProbe(`/api/probe/follow-ups/${followUpId}/answer`, {
    method: 'POST',
    body: JSON.stringify({ text })
  })

  resetInputMetrics()
  if (!result.ok) message('Не удалось отправить уточнение.')
  else if (ui.historyOpen) await loadHistory()
}

async function sendFeedback(questionId) {
  const chosen = document.querySelector('input[name="probe-reason"]:checked')
  const comment = $('probe-comment').value.trim()

  const result = await mutateProbe(`/api/probe/questions/${questionId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ reason: chosen.value, comment: comment || null })
  })

  ui.feedbackOpen = false
  if (!result.ok) message('Не удалось отправить. Попробуйте ещё раз.')
  else message('Спасибо — вопрос заменили.', 'ok')
}

async function onProbeClick(event, state) {
  const trigger = event.target.closest('#probe-block [data-act], #white-spots [data-act="probe-spot"]')
  if (!trigger) return

  const { act, q, fu, competency } = trigger.dataset

  const actions = {
    next: () => mutateProbe('/api/probe/next', { method: 'POST', body: JSON.stringify({}) }),
    'probe-spot': () => askAbout(competency),
    answer: () => sendAnswer(q, state),
    'answer-follow-up': () => sendFollowUp(fu),
    skip: () => mutateProbe(`/api/probe/questions/${q}/skip`, { method: 'POST' }),
    nda: async () => {
      await mutateProbe(`/api/probe/questions/${q}/decline`, {
        method: 'POST',
        body: JSON.stringify({ reason: null })
      })
      message('Материалы раскрывать не нужно — вот тот же вопрос в общем виде.', 'ok')
    },
    'open-feedback': () => { ui.feedbackOpen = true; renderProbe(state) },
    'close-feedback': () => { ui.feedbackOpen = false; renderProbe(state) },
    'send-feedback': () => sendFeedback(q),
    'toggle-history': async () => {
      ui.historyOpen = !ui.historyOpen
      if (ui.historyOpen && !ui.history) await loadHistory()
      renderProbe(state)
    }
  }

  const handler = actions[act]
  if (handler) await handler()
}

/* Вопрос по конкретному белому пятну - точка входа из модуля 3. */
export async function askAbout(competencyId) {
  message('')
  const result = await mutateProbe('/api/probe/next', {
    method: 'POST',
    body: JSON.stringify({ competency_id: competencyId })
  })

  if (!result.ok) {
    message(result.payload?.detail || 'Не удалось подобрать вопрос.')
    return
  }
  $('probe-block').scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/* ---------- запрет вставки (FR-Int.3) ---------- */

function guardInput(root) {
  const isProbeField = target => target instanceof HTMLElement && target.matches('.probe-input')

  for (const type of ['paste', 'drop']) {
    root.addEventListener(type, event => {
      if (!isProbeField(event.target)) return
      // Молча не даём вставить: ругаться на кандидата не за что.
      event.preventDefault()
      ui.pasteBlocked += 1
    })
  }

  root.addEventListener('contextmenu', event => {
    if (isProbeField(event.target)) event.preventDefault()
  })

  root.addEventListener('input', event => {
    if (isProbeField(event.target) && ui.typingStartedAt === null) {
      ui.typingStartedAt = Date.now()
    }
  })
}

export function initProbe({ getState, root }) {
  guardInput(root)
  root.addEventListener('click', event => onProbeClick(event, getState()))
}

export function resetProbe() {
  ui.feedbackOpen = false
  ui.historyOpen = false
  ui.history = null
  resetInputMetrics()
}
