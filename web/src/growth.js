/* История роста и актуальность (модуль 8).

   Экран отвечает на вопрос, ради которого этот продукт вообще отличается от
   тестового задания: что у вас накопилось и почему это не придётся доказывать
   заново. Поэтому лента ведёт итогом («подтверждена компетенция»), а не
   механизмом («добавлена запись»), и сгруппирована по месяцам — сплошной
   поток событий читается как выгрузка из базы.

   Понижение веса за давность здесь показано как повод вернуться, а не как
   потеря: само подтверждение никуда не девается, и одно нажатие возвращает
   полный вес. */

import './growth.css'
import { mutateGrowth } from './store.js'

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

const ICON = {
  evidence_added: '＋',
  competency_status_upgraded: '↑',
  trust_component_increased: '↑',
  role_added: '◎',
  dispute_resolved_in_favor: '✓',
  competency_reused_across_role: '⟳'
}

const ui = { showAll: false }
const SHOWN_PERIODS = 2

export const GROWTH_SKELETON = `
  <section class="block" id="growth-block">
    <h2>История роста</h2>
    <p class="sub" id="growth-note"></p>
    <div id="growth-body"></div>
    <p class="msg" id="growth-msg"></p>
  </section>
`

/* ---------- напоминания ---------- */

function triggerRow(item) {
  const action = item.trigger_type === 'competency_decay_warning'
    ? `<button type="button" class="action" data-act="growth-refresh"
         data-competency="${escape(item.related_ref)}">Актуализировать</button>`
    : ''

  return `
    <div class="growth-trigger">
      <span>${escape(item.text_ru)}</span>
      ${action}
      <button type="button" class="link-btn" data-act="growth-dismiss"
        data-trigger="${escape(item.id)}">Скрыть</button>
    </div>`
}

/* ---------- актуальность ---------- */

function freshnessRow(item) {
  const stale = item.market_weight_multiplier < 1
  return `
    <div class="freshness ${stale ? 'stale' : ''}">
      <span class="fresh-name">${escape(item.name_ru)}</span>
      <span class="chip ${stale ? 'nda' : 'grey'}">${escape(item.status_ru)}</span>
      <span class="fresh-weight">вес ${Math.round(item.market_weight_multiplier * 100)}%</span>
      ${stale
        ? `<button type="button" class="ghost" data-act="growth-refresh"
             data-competency="${escape(item.competency_id)}">Актуализировать</button>`
        : ''}
    </div>`
}

/* ---------- лента ---------- */

function eventRow(item) {
  return `
    <li class="growth-event ${escape(item.event_type)}">
      <span class="growth-icon">${ICON[item.event_type] || '·'}</span>
      <div>
        <p class="growth-text">${escape(item.description_ru)}</p>
        <span class="growth-when">${new Date(item.occurred_at).toLocaleDateString('ru-RU', {
          day: 'numeric', month: 'long'
        })}</span>
      </div>
    </li>`
}

function periodBlock(period) {
  return `
    <div class="growth-period">
      <h3>${escape(period.label_ru)}</h3>
      <ul>${period.events.map(eventRow).join('')}</ul>
    </div>`
}

export function renderGrowth(state) {
  const box = $('growth-body')
  if (!box || !state.growth) return

  const data = state.growth
  $('growth-note').textContent = data.note_ru

  const periods = ui.showAll ? data.periods : data.periods.slice(0, SHOWN_PERIODS)
  const hidden = data.periods.length - periods.length

  box.innerHTML = `
    ${data.triggers.length ? data.triggers.map(triggerRow).join('') : ''}

    <div class="growth-stats">
      <span>Подтверждено компетенций: <b>${data.stats.confirmed_competencies}</b></span>
      <span>Перенесено в другие роли без вопросов: <b>${data.stats.reused_across_roles}</b></span>
      <span title="Показ напоминания успехом не считается — считается только действие после него">
        Напоминаний сработало: <b>${data.stats.triggers_acted_upon}</b> из ${data.stats.triggers_sent}
      </span>
    </div>

    ${data.freshness.length ? `
      <h3 class="growth-h">Актуальность подтверждений</h3>
      <p class="sub" style="margin-bottom:12px">
        Влияет только на PROF.индекс — насколько компетенция считается сейчас для соответствия
        роли. Подтверждение остаётся подтверждённым, и на Trust Score это не влияет вообще.
      </p>
      ${data.freshness.map(freshnessRow).join('')}` : ''}

    <h3 class="growth-h">Что происходило</h3>
    ${periods.length
      ? periods.map(periodBlock).join('')
      : '<div class="empty">Пока ничего не накопилось — история появится с первым доказательством.</div>'}

    ${hidden > 0 && !ui.showAll
      ? `<button type="button" class="link-btn" data-act="growth-more">Показать раньше (${hidden})</button>`
      : ''}
  `
}

/* ---------- действия ---------- */

function message(text, kind = 'error') {
  const box = $('growth-msg')
  if (!box) return
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

async function onClick(event, state) {
  const trigger = event.target.closest('#growth-block [data-act]')
  if (!trigger) return

  const { act, competency, trigger: triggerId } = trigger.dataset

  if (act === 'growth-more') {
    ui.showAll = true
    renderGrowth(state)
    return
  }

  if (act === 'growth-refresh') {
    message('')
    const result = await mutateGrowth(`/api/growth/freshness/${competency}/refresh`, {
      method: 'POST'
    })
    if (result.ok) message('Готово. Доказывать заново ничего не нужно.', 'ok')
    else message(result.payload?.detail || 'Не удалось обновить.')
    return
  }

  if (act === 'growth-dismiss') {
    await mutateGrowth(`/api/growth/triggers/${triggerId}/dismiss`, { method: 'POST' })
  }
}

export function initGrowth({ getState, root }) {
  root.addEventListener('click', event => onClick(event, getState()))
}

export function resetGrowth() {
  ui.showAll = false
}
