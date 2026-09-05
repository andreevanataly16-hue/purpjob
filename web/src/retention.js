/* Поводы вернуться: появилась подходящая вакансия (модуль 11).

   Уведомление здесь — не «мы кое-что нашли», а совпадение с числом и точным
   списком того, чего не хватает. Кандидат должен понимать, ради чего он
   возвращается, до того как нажмёт.

   Отдельно важно, что показ уведомления нигде не считается успехом: на экране
   видно и сколько показали, и сколько привело к действию. Много показов при
   нулевом действии — это провал гипотезы, а не работающая функция. */

import './retention.css'
import { mutateRetention } from './store.js'
import { whyButton } from './xai.js'

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

export const RETENTION_SKELETON = `
  <section class="block" id="retention-block">
    <h2>Ради чего вернуться</h2>
    <p class="sub" id="retention-note"></p>
    <div id="retention-body"></div>
    <p class="msg" id="retention-msg"></p>
  </section>
`

function triggerCard(item) {
  const moved = item.match_score_now !== item.match_score_at_detection
    ? `<span class="ret-moved">сейчас ${item.match_score_now}</span>`
    : ''

  return `
    <div class="ret-trigger">
      <div class="ret-head">
        <div>
          <b>${escape(item.vacancy_title_ru)}</b>
          <span class="ret-company">${escape(item.company_label)}</span>
        </div>
        <div class="ret-score">
          <span class="ret-value">${item.match_score_at_detection}</span>
          ${moved}
        </div>
      </div>

      <p class="ret-why">${escape(item.explanation_ru)}</p>

      <div class="ret-actions">
        <button type="button" class="action" data-act="ret-open" data-id="${escape(item.id)}"
          data-vacancy="${escape(item.vacancy_id)}">
          Посмотреть, чего не хватает
        </button>
        ${whyButton(item.explanation_id)}
        <button type="button" class="link-btn" data-act="ret-dismiss" data-id="${escape(item.id)}">
          Скрыть
        </button>
      </div>
    </div>`
}

export function renderRetention(state) {
  const box = $('retention-body')
  if (!box || !state.retention) return

  const data = state.retention
  $('retention-note').textContent = data.note_ru

  box.innerHTML = `
    ${data.triggers.length
      ? data.triggers.map(triggerCard).join('')
      : `<div class="empty">
           Новых подходящих вакансий пока нет. Мы сообщаем только про те, где совпадение
           уже не ниже ${data.min_match_score_to_notify}%.
         </div>`}

    ${data.cross_vacancy_events.length ? `
      <div class="ret-cross">
        ${data.cross_vacancy_events.map(item => `
          <p>${escape(item.description_ru)}</p>`).join('')}
      </div>` : ''}

    <div class="ret-stats">
      <span title="Показ уведомления успехом не считается — считается действие после него">
        Поводов показано: <b>${data.stats.sent}</b>, привели к делу: <b>${data.stats.acted_upon}</b>
      </span>
      <button type="button" class="link-btn" data-act="ret-check">Проверить новые вакансии</button>
    </div>
  `
}

/* ---------- действия ---------- */

function message(text, kind = 'error') {
  const box = $('retention-msg')
  if (!box) return
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

async function onClick(event) {
  const trigger = event.target.closest('#retention-block [data-act]')
  if (!trigger) return

  const { act, id, vacancy } = trigger.dataset
  message('')

  if (act === 'ret-check') {
    // Расписания в прототипе негде держать, поэтому проход обнаружения —
    // видимое действие. Так же понятно, что именно сработало.
    const result = await mutateRetention('/api/retention/check', { method: 'POST' })
    if (result.ok && !result.payload.triggers.length) {
      message('Новых подходящих вакансий нет.', 'ok')
    }
    return
  }

  if (act === 'ret-dismiss') {
    await mutateRetention(`/api/retention/triggers/${id}/dismiss`, { method: 'POST' })
    return
  }

  if (act === 'ret-open') {
    await mutateRetention(`/api/retention/triggers/${id}/open`, { method: 'POST' })

    // Ведём на разбор требований этой вакансии, а не на общий экран профиля:
    // возвращаться нужно ради конкретного дела.
    const open = document.querySelector(`[data-act="vac-open"][data-id="${vacancy}"]`)
    if (open) {
      if (open.textContent.trim().startsWith('Разобрать')) open.click()
      open.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }
}

export function initRetention({ root }) {
  root.addEventListener('click', onClick)
}
