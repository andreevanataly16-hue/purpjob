/* Очередь модератора (модуль 7).

   Роль модератора здесь — режим экрана, а не вход и не права доступа: в этой
   фазе продукта настоящих ролей нет вообще. Предупреждение об этом стоит прямо
   в очереди, а не только в README: включать такое в многопользовательской среде
   нельзя, и это должно быть видно тому, кто открыл экран.

   Смысл экрана — проверять одно фактическое утверждение, а не расследовать
   профиль заново: модератор видит ровно то, что видел кандидат. */

import './moderation.css'
import { mutateModeration } from './store.js'

const ui = { on: false, open: null, action: null }

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

const TARGET_RU = {
  prof_competency_status: 'Статус компетенции в PROF.индексе',
  trust_component_score: 'Балл компонента Trust Score',
  contradiction_case_resolution: 'Разбор нестыковки'
}

const ORIGIN_RU = {
  candidate_escalation: 'кандидат не согласен',
  anomaly_flag: 'сигнал детектора',
  sampled_audit: 'выборочная проверка'
}

export const MODERATION_SKELETON = `
  <section class="block" id="moderation-block">
    <div class="mod-head">
      <div>
        <h2>Режим модератора</h2>
        <p class="sub" style="margin-bottom:0">
          Разбор одного конкретного вывода, а не профиля целиком.
        </p>
      </div>
      <button type="button" class="ghost" data-act="mod-toggle" id="mod-toggle">Открыть очередь</button>
    </div>
    <div id="moderation-body" hidden></div>
    <p class="msg" id="mod-msg"></p>
  </section>
`

/* ---------- карточка спора ---------- */

function evidenceRow(item) {
  if (!item.resolved) {
    return `<li class="mod-ev broken">${escape(item.title_ru)}</li>`
  }
  return `
    <li class="mod-ev">
      <b>${escape(item.title_ru)}</b> <span class="chip grey">${escape(item.ref)}</span>
      ${item.detail_ru ? `<p>${escape(item.detail_ru)}</p>` : ''}
    </li>`
}

function actionForm(item, targets) {
  if (ui.open !== item.id) return ''

  if (ui.action === 'uphold') {
    return `
      <div class="mod-form">
        <label>Почему вывод остаётся в силе</label>
        <textarea class="probe-input" id="mod-rationale"
          placeholder="Что именно проверено. Кандидат это увидит."></textarea>
        <button type="button" class="action" data-act="mod-uphold" data-case="${escape(item.id)}">
          Оставить вывод
        </button>
      </div>`
  }

  if (ui.action === 'info') {
    return `
      <div class="mod-form">
        <label>Конкретный вопрос кандидату</label>
        <textarea class="probe-input" id="mod-question"
          placeholder="Например: из какого репозитория ссылка ev_002?"></textarea>
        <button type="button" class="action" data-act="mod-info" data-case="${escape(item.id)}">
          Запросить подробности
        </button>
      </div>`
  }

  if (ui.action === 'override') {
    const options = Object.entries(targets)
      .flatMap(([type, ids]) => ids.map(id => (
        `<option value="${escape(type)}|${escape(id)}">${escape(TARGET_RU[type] || type)}: ${escape(id)}</option>`
      )))
      .join('')

    return `
      <div class="mod-form">
        <label>Что именно правим — одно поле одного объекта</label>
        <select id="mod-target">${options}</select>

        <label>Новое значение</label>
        <input type="text" id="mod-value" placeholder="strong / 80 / explain">

        <label>Причина правки — обязательно</label>
        <textarea class="probe-input" id="mod-rationale"
          placeholder="Правка без причины — тот же неоспоримый судья, только человек."></textarea>

        <button type="button" class="action" data-act="mod-override" data-case="${escape(item.id)}">
          Исправить вывод
        </button>
      </div>`
  }

  return ''
}

function caseCard(item, targets) {
  return `
    <div class="mod-case">
      <div class="mod-case-head">
        <span class="chip grey">${escape(item.id)}</span>
        <span class="chip grey">${escape(ORIGIN_RU[item.origin] || item.origin)}</span>
        <span class="mod-status">${escape(item.status_ru)}</span>
        <span class="mod-who">${escape(item.candidate_email)}</span>
      </div>

      <p class="mod-subject">${escape(item.subject_type_ru)} · ${escape(item.subject_id)}</p>
      <p class="mod-conclusion">${escape(item.conclusion_ru)}</p>

      ${item.candidate_statement
        ? `<p class="mod-said">Кандидат: ${escape(item.candidate_statement)}</p>`
        : '<p class="mod-said muted">Кандидат не стал объяснять — это его право.</p>'}

      <h4 class="mod-h">То же, что видел кандидат</h4>
      <ul class="mod-evidence">
        ${item.resolved_evidence.length
          ? item.resolved_evidence.map(evidenceRow).join('')
          : '<li class="mod-ev muted">Доказательств за выводом нет.</li>'}
      </ul>

      <div class="mod-actions">
        <button type="button" class="ghost" data-act="mod-take" data-case="${escape(item.id)}">
          Взять в работу
        </button>
        <button type="button" class="ghost" data-act="mod-pick" data-case="${escape(item.id)}"
          data-action="uphold">Оставить вывод</button>
        <button type="button" class="ghost" data-act="mod-pick" data-case="${escape(item.id)}"
          data-action="info">Запросить подробности</button>
        <button type="button" class="ghost" data-act="mod-pick" data-case="${escape(item.id)}"
          data-action="override">Исправить</button>
      </div>

      ${actionForm(item, targets)}

      <details class="mod-history">
        <summary>Журнал (${item.history.length})</summary>
        <ul>
          ${item.history.map(entry => `
            <li>
              ${new Date(entry.timestamp).toLocaleString('ru-RU')} —
              <b>${escape(entry.event_ru)}</b> (${escape(entry.actor_ru)})
              ${entry.before_value || entry.after_value
                ? `<span class="chip grey">${escape(entry.before_value ?? '—')} → ${escape(entry.after_value ?? '—')}</span>`
                : ''}
              ${entry.note_ru ? `<p>${escape(entry.note_ru)}</p>` : ''}
            </li>`).join('')}
        </ul>
      </details>
    </div>`
}

export function renderModeration(state) {
  const box = $('moderation-body')
  const toggle = $('mod-toggle')
  if (!box || !toggle) return

  box.hidden = !ui.on
  toggle.textContent = ui.on ? 'Закрыть очередь' : 'Открыть очередь'
  if (!ui.on || !state.moderation) return

  const queue = state.moderation
  const stats = queue.stats

  box.innerHTML = `
    <div class="mod-warning">${escape(queue.not_production_safe_ru)}</div>

    <div class="mod-stats">
      <span>Открытых споров: <b>${queue.open_count}</b></span>
      <span>Разобрано: <b>${stats.resolved_count}</b></span>
      <span>Медиана разбора: <b>${
        stats.median_minutes_to_resolve === null ? '—' : `${stats.median_minutes_to_resolve} мин`
      }</b></span>
      <span>По видам: ${
        Object.entries(stats.disputes_by_subject_type)
          .map(([key, count]) => `${escape(key)} — ${count}`)
          .join(', ') || '—'
      }</span>
    </div>

    ${queue.cases.length
      ? queue.cases.map(item => caseCard(item, queue.override_targets)).join('')
      : '<div class="empty">Очередь пуста — открытых споров нет.</div>'}
  `
}

/* ---------- действия ---------- */

function message(text, kind = 'error') {
  const box = $('mod-msg')
  if (!box) return
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

async function send(path, body) {
  message('')
  const result = await mutateModeration(path, {
    method: 'POST',
    body: JSON.stringify(body)
  })
  if (!result.ok) message(result.payload?.detail || 'Не удалось сохранить решение.')
  else {
    ui.open = null
    ui.action = null
  }
  return result
}

async function onClick(event, state) {
  const trigger = event.target.closest('#moderation-block [data-act]')
  if (!trigger) return

  const { act, case: caseId, action } = trigger.dataset

  if (act === 'mod-toggle') {
    ui.on = !ui.on
    renderModeration(state)
    return
  }

  if (act === 'mod-pick') {
    ui.open = ui.open === caseId && ui.action === action ? null : caseId
    ui.action = ui.open ? action : null
    renderModeration(state)
    return
  }

  if (act === 'mod-take') {
    await send(`/api/moderation/cases/${caseId}/take`, {})
    return
  }

  if (act === 'mod-uphold') {
    const rationale = $('mod-rationale')?.value.trim() || ''
    if (rationale.length < 5) {
      message('Напишите, что именно проверено — кандидат это увидит.')
      return
    }
    await send(`/api/moderation/cases/${caseId}/uphold`, { rationale_ru: rationale })
    return
  }

  if (act === 'mod-info') {
    const question = $('mod-question')?.value.trim() || ''
    if (question.length < 5) {
      message('Вопрос должен быть конкретным, иначе кандидату нечего отвечать.')
      return
    }
    await send(`/api/moderation/cases/${caseId}/request-info`, { question_ru: question })
    return
  }

  if (act === 'mod-override') {
    const target = $('mod-target')?.value || ''
    const [targetType, targetId] = target.split('|')
    const value = $('mod-value')?.value.trim() || ''
    const rationale = $('mod-rationale')?.value.trim() || ''

    if (!targetType || !targetId) {
      message('Выберите, что именно правится.')
      return
    }
    if (!value) {
      message('Укажите новое значение.')
      return
    }
    if (rationale.length < 5) {
      message('Причина обязательна: правка без объяснения — тот же чёрный ящик.')
      return
    }

    await send(`/api/moderation/cases/${caseId}/override`, {
      target_type: targetType,
      target_id: targetId,
      new_value: value,
      rationale_ru: rationale
    })
  }
}

export function initModeration({ getState, root }) {
  root.addEventListener('click', event => onClick(event, getState()))
}

export function resetModeration() {
  ui.on = false
  ui.open = null
  ui.action = null
}
