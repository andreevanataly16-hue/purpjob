/* Кто интересуется вашим профилем (модуль 13, сторона кандидата).

   Это прозрачность, а не право вето: кандидат видит, до какого этапа дошёл
   каждый рекрутер, но уже наступивший этап не отменяет. Сама поэтапность —
   защита от предвзятости, и возможность произвольно её переключать по одному
   рекрутеру эту защиту бы и разобрала.

   Два переключателя здесь независимы, и это важно проговорить на экране:
   разрешить сразу показывать имя — не то же самое, что открыть доказательства
   или отдать контакты. */

import './reveal.css'
import { api } from './api.js'

const ui = { data: null }

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

export const REVEAL_SKELETON = `
  <section class="block" id="reveal-block">
    <h2>Кто интересуется профилем</h2>
    <p class="sub" id="reveal-note"></p>
    <div id="reveal-body"></div>
    <p class="msg" id="reveal-msg"></p>
  </section>
`

function interestRow(item) {
  const contacts = item.contact_requested && !item.contact_opt_in
    ? `<button type="button" class="ghost" data-act="reveal-share"
         data-recruiter="${item.recruiter_label.replace(/\D/g, '')}">
         Открыть контакты этому рекрутеру
       </button>`
    : item.contact_opt_in
      ? '<span class="chip">контакты открыты вами</span>'
      : ''

  return `
    <div class="reveal-item">
      <span class="reveal-who">${escape(item.recruiter_label)}</span>
      <span class="reveal-stage">${escape(item.stage_ru)}</span>
      ${contacts}
    </div>`
}

export function renderReveal() {
  const box = $('reveal-body')
  if (!box || !ui.data) return

  const data = ui.data
  $('reveal-note').textContent = data.note_ru

  box.innerHTML = `
    ${data.interests.length
      ? data.interests.map(interestRow).join('')
      : '<div class="empty">Пока никто не открывал ваш профиль.</div>'}

    <div class="reveal-settings">
      <label>
        <input type="checkbox" id="reveal-immediate"
          ${data.allow_immediate_identity_reveal ? 'checked' : ''}>
        ${escape(data.opt_out_label_ru)}
      </label>
      <p class="sub">
        По умолчанию выключено: сначала рекрутер видит только подтверждённый опыт. Это защита
        от предвзятости, а не скрытность — включать стоит, если у вас есть своя причина.
      </p>

      <label>
        <input type="checkbox" id="reveal-consent"
          ${data.consent_for_recruiter_view ? 'checked' : ''}>
        Разрешить рекрутерам открывать сами доказательства
      </label>
      <p class="sub">
        Это отдельное решение: оно про глубину, а не про имя и не про контакты. Контакты
        открываются только вами и только конкретному рекрутеру.
      </p>
    </div>
  `
}

async function load() {
  const result = await api('/api/reveal')
  if (result.ok) {
    ui.data = result.payload
    renderReveal()
  }
}

async function onEvent(event) {
  const target = event.target

  if (target.id === 'reveal-immediate' || target.id === 'reveal-consent') {
    const body = target.id === 'reveal-immediate'
      ? { allow_immediate_identity_reveal: target.checked }
      : { consent_for_recruiter_view: target.checked }

    const result = await api('/api/reveal/settings', {
      method: 'PUT',
      body: JSON.stringify(body)
    })
    if (result.ok) {
      ui.data = result.payload
      renderReveal()
    }
    return
  }

  const trigger = target.closest('#reveal-block [data-act="reveal-share"]')
  if (!trigger) return

  const result = await api(
    `/api/reveal/interests/${trigger.dataset.recruiter}/share-contacts`,
    { method: 'POST' }
  )
  if (result.ok) {
    ui.data = result.payload
    renderReveal()
  }
}

export function initReveal({ root }) {
  root.addEventListener('click', onEvent)
  root.addEventListener('change', onEvent)
  load()
}

export function resetReveal() {
  ui.data = null
}
