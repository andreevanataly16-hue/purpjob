/* Обратная связь рекрутера и панель калибровки (модуль 14).

   Две разные вещи на одном модуле, и путать их нельзя.

   Первая — лёгкое действие рекрутера: один вопрос, три кнопки. Оно ничего не
   меняет в профиле кандидата и так и написано на экране: иначе рекрутер будет
   думать, что нажатием «Нет» он кому-то портит жизнь, и перестанет отвечать.

   Вторая — экран оператора: что чаще всего вводило в заблуждение, насколько
   выводы вообще совпадают с реальностью, и журнал изменений калибруемых
   величин. Формулы сами не подстраиваются: запись фиксирует решение человека,
   а значение в коде меняется обычным коммитом с ревью. */

import './calibration.css'
import { api } from './api.js'

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

const ui = { open: false, data: null, feedback: null, candidateId: null, marks: {} }

/* ---------- отметка рекрутера на карточке кандидата ---------- */

export function feedbackBlock() {
  if (!ui.feedback) return ''

  const data = ui.feedback
  const submitted = data.submitted

  return `
    <div class="feedback-box">
      <p class="feedback-prompt">${escape(data.prompt_ru)}</p>
      <div class="feedback-options">
        ${data.options.map(option => `
          <button type="button" class="ghost ${submitted?.relevance_outcome === option.value ? 'chosen' : ''}"
            data-act="feedback" data-outcome="${escape(option.value)}">
            ${escape(option.label_ru)}
          </button>`).join('')}
      </div>
      <p class="feedback-note">${escape(data.note_ru)}</p>
      ${submitted ? `
        <p class="feedback-done">
          Записано: ${escape(submitted.relevance_outcome_ru)}. Балл кандидата это не изменило.
        </p>` : ''}
    </div>`
}

/* Микро-действие рядом с конкретным выводом — там же, где рекрутер его увидел.

   Адрес вывода передаётся явно, а не выводится из идентификатора объяснения:
   в сводке оператора группировка идёт по нему, и «authenticity» там читается,
   а «expl_trust_authenticity» — уже нет. */
export function verdictButtons(explanationId, subjectType, subjectId) {
  if (!ui.feedback || !explanationId) return ''
  const current = ui.feedback.component_verdicts[explanationId]

  return `
    <span class="verdict-row">
      ${ui.feedback.verdicts.map(item => `
        <button type="button" class="verdict ${current === item.value ? 'chosen' : ''}"
          data-act="verdict" data-explanation="${escape(explanationId)}"
          data-subject-type="${escape(subjectType)}" data-subject-id="${escape(subjectId)}"
          data-verdict="${escape(item.value)}" title="${escape(ui.feedback.component_prompt_ru)}">
          ${escape(item.label_ru)}
        </button>`).join('')}
    </span>`
}

export async function loadFeedback(candidateId) {
  ui.candidateId = candidateId
  if (!candidateId) {
    ui.feedback = null
    return
  }
  const result = await api(`/api/calibration/feedback/${candidateId}`)
  ui.feedback = result.ok ? result.payload : null
}

async function submit(outcome, marks = []) {
  const result = await api('/api/calibration/feedback', {
    method: 'POST',
    body: JSON.stringify({
      candidate_id: ui.candidateId,
      relevance_outcome: outcome,
      component_feedback: marks
    })
  })
  if (result.ok) ui.feedback = result.payload
  return result
}

/* ---------- панель оператора ---------- */

export const CALIBRATION_SKELETON = `
  <section class="block" id="calibration-block">
    <div class="cal-head">
      <div>
        <h2>Калибровка</h2>
        <p class="sub" style="margin-bottom:0">
          Сверка выводов системы с тем, что рекрутеры увидели вживую.
        </p>
      </div>
      <button type="button" class="ghost" data-act="cal-toggle" id="cal-toggle">Открыть</button>
    </div>
    <div id="calibration-body" hidden></div>
    <p class="msg" id="cal-msg"></p>
  </section>
`

function insightRow(item) {
  return `
    <tr class="${item.flagged_for_review ? 'flagged' : ''}">
      <td>${escape(item.subject_type_ru)}</td>
      <td>${escape(item.subject_id)}</td>
      <td>${item.sample_size}</td>
      <td>${Math.round(item.misleading_rate * 100)}%</td>
      <td>${item.flagged_for_review ? 'стоит присмотреться' : '—'}</td>
    </tr>`
}

function changeRow(item) {
  return `
    <div class="cal-change">
      <div class="cal-change-head">
        <b>${escape(item.label_ru)}</b>
        <span class="chip grey">${escape(item.previous_value)} → ${escape(item.new_value)}</span>
        <span class="cal-when">${new Date(item.applied_at).toLocaleDateString('ru-RU')}</span>
      </div>
      <p>${escape(item.rationale_ru)}</p>
      <p class="cal-basis">
        Основано на ${item.based_on_feedback_count} отзывах${
          item.trust_accuracy_before === null
            ? ''
            : `, совпадение с реальностью на тот момент — ${item.trust_accuracy_before}%`
        }.
      </p>
    </div>`
}

function batchRow(item) {
  return `
    <div class="cal-batch">
      <div class="cal-change-head">
        <span class="chip grey">${escape(item.id)}</span>
        <b>${escape(item.selection_ru)}</b>
        <span class="cal-when">${item.candidate_ids.length} профилей</span>
      </div>
      <p>${escape(item.pattern_ru)}</p>
    </div>`
}

function body(data) {
  const accuracy = data.accuracy

  return `
    <div class="cal-warning access-note">${escape(data.access_note_ru)}</div>
    <p class="sub">${escape(data.note_ru)}</p>

    <div class="cal-accuracy">
      <span class="cal-value">${
        accuracy.trust_accuracy_pct === null ? '—' : `${accuracy.trust_accuracy_pct}%`
      }</span>
      <span class="cal-of">
        совпадение вывода с исходом собеседования · отзывов ${accuracy.total_feedback_count},
        сравнимых ${accuracy.comparable_count}
      </span>
    </div>
    <p class="sub" style="margin-top:0">
      Если это число держится около случайного даже на приличной выборке — дело не в
      коэффициентах, а в самой модели. Это разные выводы, и смешивать их не стоит.
    </p>

    <h3 class="cal-h">Что вводило в заблуждение</h3>
    ${data.insights.length ? `
      <table class="cal-table">
        <thead>
          <tr><th>Вид вывода</th><th>Что именно</th><th>Отзывов</th><th>Ввело в заблуждение</th><th>Флаг</th></tr>
        </thead>
        <tbody>${data.insights.map(insightRow).join('')}</tbody>
      </table>`
      : '<div class="empty">Пока никто не отмечал отдельные выводы.</div>'}

    <h3 class="cal-h">Калибруемые величины</h3>
    <div class="cal-form">
      <label>Что меняем</label>
      <select id="cal-constant">
        ${data.constants.map(item => `
          <option value="${escape(item.constant_ref)}">
            ${escape(item.label_ru)} — сейчас ${escape(item.current_value)}
          </option>`).join('')}
      </select>

      <label>Новое значение</label>
      <input type="text" id="cal-value" placeholder="например, 14">

      <label>Почему — обязательно</label>
      <textarea class="probe-input" id="cal-rationale"
        placeholder="На каких данных основано решение. Менять то, как система считает всех дальше, без объяснения нельзя."></textarea>

      <button type="button" class="action" data-act="cal-change">Записать решение</button>
      <p class="sub" style="margin:10px 0 0">
        Запись фиксирует решение, а не выполняет его: значение в коде меняет человек
        следующим коммитом — чтобы изменение прошло обычное ревью, а не случилось
        из формы на живой системе.
      </p>
    </div>

    ${data.changes.length ? `
      <h3 class="cal-h">История изменений</h3>
      ${data.changes.map(changeRow).join('')}` : ''}

    <h3 class="cal-h">Выборочный разбор</h3>
    <div class="cal-actions">
      <select id="cal-selection">
        ${data.selection_options.map(item => `
          <option value="${escape(item.value)}">${escape(item.label_ru)}</option>`).join('')}
      </select>
      <button type="button" class="ghost" data-act="cal-batch">Собрать партию</button>
    </div>
    <p class="sub" style="margin-top:10px">
      Отобранные профили уходят в очередь модератора как обычные споры — разбирает их
      модуль 7, а не отдельный второй экран.
    </p>
    ${data.batches.map(batchRow).join('')}
  `
}

export function renderCalibration() {
  const box = $('calibration-body')
  const toggle = $('cal-toggle')
  if (!box || !toggle) return

  box.hidden = !ui.open
  toggle.textContent = ui.open ? 'Закрыть' : 'Открыть'
  if (!ui.open) return

  box.innerHTML = ui.data ? body(ui.data) : '<div class="empty">Загружаем…</div>'
}

async function load() {
  const result = await api('/api/calibration')
  ui.data = result.ok ? result.payload : null
  renderCalibration()
}

function message(text, kind = 'error') {
  const box = $('cal-msg')
  if (!box) return
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

/* ---------- действия ---------- */

async function onClick(event, rerender) {
  const trigger = event.target.closest('[data-act]')
  if (!trigger) return

  const { act, outcome, explanation, verdict: value } = trigger.dataset
  const subjectType = trigger.dataset.subjectType
  const subjectId = trigger.dataset.subjectId

  if (act === 'feedback') {
    const result = await submit(outcome)
    if (!result.ok) message(result.payload?.detail || 'Не удалось записать отзыв.')
    else message('')
    rerender()
    return
  }

  if (act === 'verdict') {
    // Отметка на выводе идёт вместе с базовым исходом: без него отзыв неполон,
    // а переспрашивать рекрутера ради одной галочки — лишний шаг.
    const outcomeValue = ui.feedback?.submitted?.relevance_outcome
    if (!outcomeValue) {
      message('Сначала ответьте, оказался ли кандидат релевантным.')
      return
    }
    message('')
    await submit(outcomeValue, [
      {
        explanation_id: explanation,
        subject_type: subjectType,
        subject_id: subjectId,
        verdict: value
      }
    ])
    rerender()
    return
  }

  if (act === 'cal-toggle') {
    ui.open = !ui.open
    renderCalibration()
    if (ui.open) await load()
    return
  }

  if (act === 'cal-change') {
    const rationale = $('cal-rationale')?.value.trim() || ''
    const newValue = $('cal-value')?.value.trim() || ''
    if (!newValue) {
      message('Укажите новое значение.')
      return
    }
    if (rationale.length < 10) {
      message('Причина обязательна: это меняет то, как система считает всех дальше.')
      return
    }
    const result = await api('/api/calibration/changes', {
      method: 'POST',
      body: JSON.stringify({
        constant_ref: $('cal-constant').value,
        new_value: newValue,
        rationale_ru: rationale
      })
    })
    if (result.ok) {
      ui.data = result.payload
      message('Решение записано. Значение в коде меняется отдельным коммитом.', 'ok')
      renderCalibration()
    } else message(result.payload?.detail || 'Не удалось записать.')
    return
  }

  if (act === 'cal-batch') {
    const result = await api('/api/calibration/batches', {
      method: 'POST',
      body: JSON.stringify({ selection_criteria: $('cal-selection').value, size: 3 })
    })
    if (result.ok) {
      ui.data = result.payload
      message('Партия собрана и ушла в очередь модератора.', 'ok')
      renderCalibration()
    } else message(result.payload?.detail || 'Не удалось собрать партию.')
  }
}

export function initCalibration({ root, rerender }) {
  root.addEventListener('click', event => onClick(event, rerender))
}

export function resetCalibration() {
  ui.open = false
  ui.data = null
  ui.feedback = null
  ui.candidateId = null
}
