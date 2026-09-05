/* Плагин рекрутера — витрина виджета (модуль 15).

   Настоящий плагин живёт в чужой вкладке поверх hh.ru или LinkedIn. Упаковка
   расширения (манифест, Shadow DOM, внедрение скрипта) — это про то, как
   виджет попадает на страницу, и вынесена из объёма модуля. Здесь работает всё
   остальное, и работает по-настоящему: выделение текста читается через
   `window.getSelection`, разбор резюме идёт в браузере, а на сервер уходит
   ровно один хеш — и только по нажатию «Найти в базе».

   Ничего со страницы само не читается. Это не временное ограничение, а
   заявленная позиция: аккаунт рекрутера не должен попасть под блокировку
   площадки из-за нашего удобства, а чужие персональные данные не должны
   покидать браузер без ведома человека. */

import './plugin.css'
import { api } from './api.js'
import { analyse } from './express.js'

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

const ui = {
  open: false,
  info: null,
  kind: 'resume',
  text: '',
  analysis: null,
  extraction: null,
  lookup: null,
  invite: null
}

export const PLUGIN_SKELETON = `
  <section class="block" id="plugin-block">
    <div class="plug-head">
      <div>
        <h2>Плагин рекрутера</h2>
        <p class="sub" style="margin-bottom:0">
          Разбор резюме и вакансии там, где рекрутер уже работает.
        </p>
      </div>
      <button type="button" class="ghost" data-act="plug-toggle" id="plug-toggle">Открыть</button>
    </div>
    <div id="plugin-body" hidden></div>
    <p class="msg" id="plug-msg"></p>
  </section>
`

/* ---------- светофор ---------- */

function trafficLight() {
  if (!ui.info) return ''

  const tier = ui.lookup
    ? ui.lookup.tier
    : ui.analysis && ui.kind === 'resume'
      ? 'preliminary'
      : null

  if (!tier) return ''
  const meta = ui.info.tiers.find(item => item.tier === tier)

  return `
    <div class="traffic ${escape(tier)}">
      <div class="traffic-head">
        <span class="traffic-dot"></span>
        <b>${escape(meta.label_ru)}</b>
        ${tier === 'preliminary' && ui.analysis?.ai_text_likelihood_pct !== null
          ? `<span class="traffic-note">на основе резюме</span>`
          : ''}
      </div>
      <p>${escape(meta.note_ru)}</p>
      ${tier === 'verified' && ui.lookup?.candidate_id
        ? `<p class="traffic-link">
             Профиль в базе: ${escape(ui.lookup.candidate_id)} — откройте его в режиме рекрутера,
             там настоящие PROF.индекс, Trust Score и артефакты.
           </p>`
        : ''}
    </div>`
}

/* ---------- разбор резюме ---------- */

function analysisBody() {
  const data = ui.analysis
  if (!data) return ''

  return `
    <div class="plug-analysis">
      <div class="plug-metric">
        <span class="plug-value">${
          data.ai_text_likelihood_pct === null ? '—' : `${data.ai_text_likelihood_pct}%`
        }</span>
        <span class="plug-of">похоже на шаблонный или сгенерированный текст</span>
      </div>
      <ul class="plug-reasons">
        ${data.ai_reasons.map(item => `<li>${escape(item)}</li>`).join('')}
      </ul>

      <div class="plug-metric small">
        <span class="plug-value">${Math.round(data.fact_density_score * 1000) / 10}%</span>
        <span class="plug-of">плотность фактов — доля чисел в тексте</span>
      </div>

      ${data.logical_anomalies.length ? `
        <h4 class="plug-h">Нестыковки в датах</h4>
        ${data.logical_anomalies.map(item => `
          <p class="plug-anomaly">${escape(item.description_ru)}</p>`).join('')}`
        : '<p class="plug-none">Нестыковок в датах не нашли.</p>'}

      <p class="plug-caveat">
        Это грубая прикидка по тексту, а не оценка человека. У незарегистрированного кандидата
        нет контрольного образца собственных слов, с которым сравнивается Самостоятельность
        у наших кандидатов, — поэтому и точность здесь принципиально ниже.
        Посчитано в вашем браузере: текст резюме на сервер не уходил.
      </p>
    </div>`
}

/* ---------- разбор вакансии ---------- */

function extractionBody() {
  const data = ui.extraction
  if (!data) return ''

  return `
    <div class="plug-requirements">
      ${data.requirements.map(item => `
        <div class="plug-req ${item.criticality}">
          <div class="plug-req-head">
            <b>${escape(item.label_ru)}</b>
            <span class="chip ${item.criticality === 'mandatory' ? '' : 'grey'}">
              ${escape(item.criticality_ru)}
            </span>
            ${item.in_reference_profile ? '' : '<span class="chip nda">вне эталонов</span>'}
          </div>
          <p class="plug-hint">Чем подтверждается: ${escape(item.evidence_hint_ru)}</p>
          <p class="plug-basis">Из текста: «${escape(item.matched_text)}»</p>
        </div>`).join('')}
      ${data.unknown_count
        ? `<p class="plug-caveat">${escape(data.unknown_note_ru)}</p>`
        : ''}
    </div>`
}

/* ---------- приглашение ---------- */

function inviteBody() {
  if (!ui.invite) return ''
  return `
    <div class="plug-invite">
      <h4 class="plug-h">Приглашение на верификацию</h4>
      <textarea class="probe-input" id="plug-invite-text" readonly>${escape(ui.invite.message_ru)}</textarea>
      <p class="plug-caveat">${escape(ui.invite.send_note_ru)}</p>
    </div>`
}

/* ---------- сборка ---------- */

function body() {
  const info = ui.info
  if (!info) return '<div class="empty">Загружаем…</div>'

  return `
    <div class="plug-privacy">${escape(info.privacy_ru)}</div>

    <div class="plug-kind">
      <label><input type="radio" name="plug-kind" value="resume"
        ${ui.kind === 'resume' ? 'checked' : ''}> Резюме</label>
      <label><input type="radio" name="plug-kind" value="vacancy"
        ${ui.kind === 'vacancy' ? 'checked' : ''}> Вакансия</label>
    </div>

    <textarea class="probe-input" id="plug-text"
      placeholder="Выделите текст на странице и нажмите «Взять выделенное» — или вставьте его сюда сами.">${escape(ui.text)}</textarea>

    <div class="plug-actions">
      <button type="button" class="ghost" data-act="plug-selection">Взять выделенное</button>
      <button type="button" class="action" data-act="plug-analyse">Разобрать</button>
      <button type="button" class="ghost" data-act="plug-lookup">Найти в базе</button>
      <button type="button" class="ghost" data-act="plug-invite">Запросить верификацию</button>
    </div>

    ${trafficLight()}
    ${ui.kind === 'resume' ? analysisBody() : extractionBody()}
    ${inviteBody()}

    <p class="plug-lens">${escape(info.lens_ru)}</p>
    <p class="plug-honesty">${escape(info.honesty_ru)}</p>
  `
}

export function renderPlugin() {
  const box = $('plugin-body')
  const toggle = $('plug-toggle')
  if (!box || !toggle) return

  box.hidden = !ui.open
  toggle.textContent = ui.open ? 'Закрыть' : 'Открыть'
  if (ui.open) box.innerHTML = body()
}

function message(text, kind = 'error') {
  const box = $('plug-msg')
  if (!box) return
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

/* Хеш контакта считается здесь же: на сервер уходит только он. */
async function contactHash(value) {
  const data = new TextEncoder().encode(value.trim().toLowerCase())
  const digest = await crypto.subtle.digest('SHA-256', data)
  const hex = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('')
  return `sha256:${hex}`
}

/* Из текста резюме берём первую строку — обычно там имя. Никакого разбора
   персональных данных сверх этого: нам нужен один идентификатор, а не досье. */
function contactFrom(text) {
  const email = text.match(/[\w.+-]+@[\w-]+\.[\w.]+/)
  if (email) return email[0]
  return (text.split('\n').find(line => line.trim()) || '').trim()
}

async function onEvent(event) {
  if (event.target.name === 'plug-kind') {
    ui.kind = event.target.value
    ui.analysis = null
    ui.extraction = null
    renderPlugin()
    return
  }

  const trigger = event.target.closest('#plugin-block [data-act]')
  if (!trigger) return
  const { act } = trigger.dataset

  if (act === 'plug-toggle') {
    ui.open = !ui.open
    renderPlugin()
    if (ui.open && !ui.info) {
      const result = await api('/api/plugin')
      ui.info = result.ok ? result.payload : null
      renderPlugin()
    }
    return
  }

  // Единственный способ, которым текст сюда попадает: то, что рекрутер выделил
  // сам. Со страницы ничего не читается.
  if (act === 'plug-selection') {
    const selected = String(window.getSelection() || '').trim()
    if (!selected) {
      message('Выделите текст на странице — сам плагин её не читает.')
      return
    }
    message('')
    ui.text = selected
    ui.analysis = null
    ui.extraction = null
    renderPlugin()
    return
  }

  if (act === 'plug-analyse') {
    ui.text = $('plug-text')?.value || ui.text
    if (!ui.text.trim()) {
      message('Сначала возьмите текст.')
      return
    }
    message('')

    if (ui.kind === 'resume') {
      // Никакого сетевого вызова: разбор резюме целиком в браузере.
      ui.analysis = analyse(ui.text)
      ui.extraction = null
    } else {
      const result = await api('/api/plugin/vacancy', {
        method: 'POST',
        body: JSON.stringify({ raw_text: ui.text })
      })
      ui.extraction = result.ok ? result.payload : null
      ui.analysis = null
      if (!result.ok) message(result.payload?.detail || 'Не удалось разобрать вакансию.')
    }
    renderPlugin()
    return
  }

  if (act === 'plug-lookup') {
    ui.text = $('plug-text')?.value || ui.text
    const contact = contactFrom(ui.text)
    if (!contact) {
      message('Не нашли, по чему искать: возьмите текст с именем или почтой.')
      return
    }
    message('')
    const result = await api('/api/plugin/lookup', {
      method: 'POST',
      body: JSON.stringify({ contact_hash: await contactHash(contact) })
    })
    ui.lookup = result.ok ? result.payload : null
    if (!result.ok) message(result.payload?.detail || 'Поиск не удался.')
    renderPlugin()
    return
  }

  if (act === 'plug-invite') {
    const result = await api('/api/plugin/invites', {
      method: 'POST',
      body: JSON.stringify({ note_ru: null })
    })
    ui.invite = result.ok ? result.payload : null
    if (result.ok) message('Скопируйте текст и отправьте сами — плагин никому не пишет.', 'ok')
    renderPlugin()
  }
}

export function initPlugin({ root }) {
  root.addEventListener('click', onEvent)
  root.addEventListener('change', onEvent)
}

export function resetPlugin() {
  ui.open = false
  ui.info = null
  ui.text = ''
  ui.analysis = null
  ui.extraction = null
  ui.lookup = null
  ui.invite = null
}
