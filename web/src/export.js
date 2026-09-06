/* Экспорт профиля в PDF (модуль 9).

   Одно действие и один осмысленный выбор — включать ли контакты. Мастера с
   выбором формата здесь нет намеренно: формат один, и лишний шаг только
   создавал бы видимость выбора.

   Перед скачиванием показываем, что окажется в файле. Человек отправляет этот
   документ живым людям — он вправе увидеть содержимое заранее, а не узнать
   его из скачанного файла.

   Отправлять документ платформа не умеет: она отдаёт файл, всё остальное
   делает кандидат сам. */

import './export.css'
import { api } from './api.js'

const ui = { includeContacts: true, preview: null, busy: false, signature: null }

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

export const EXPORT_SKELETON = `
  <section class="block" id="export-block">
    <h2>Скачать резюме (PDF)</h2>
    <p class="sub" id="export-note"></p>
    <div id="export-body"></div>
    <p class="msg" id="export-msg"></p>
  </section>
`

function previewBody(data) {
  return `
    <div class="export-actions">
      <label class="export-toggle">
        <input type="checkbox" id="export-contacts" ${ui.includeContacts ? 'checked' : ''}>
        Включить контакты (${escape(data.contact_email || 'почта')})
      </label>
      <button type="button" class="action" data-act="export-download" ${ui.busy ? 'disabled' : ''}>
        ${ui.busy ? 'Собираем…' : 'Скачать PDF'}
      </button>
    </div>

    <p class="sub" style="margin:10px 0 0">
      Показывать профиль на площадке и приложить контакты к этому файлу — разные решения.
      Переключатель видимости профиля этим не меняется.
    </p>

    ${data.font_available ? '' : `
      <p class="export-warning">${escape(data.font_hint_ru)}</p>`}

    <div class="export-paper">
      <h3>${escape(data.role_ru)}</h3>
      <p class="paper-sub">${escape(data.segment_ru)}</p>

      <div class="paper-scores">
        <span><b>PROF.индекс:</b> ${data.prof_score} из 100</span>
        <span><b>Trust Score:</b> ${
          data.trust_measured ? `${data.trust_score} из 100` : 'пока не рассчитан'
        }</span>
      </div>
      <p class="paper-legend">${escape(data.trust_legend_ru)}</p>

      ${data.skills.length ? `
        <h4>Компетенции</h4>
        <ul class="paper-list">
          ${data.skills.map(item => `
            <li>${escape(item.name_ru)} — <span>${escape(item.status_ru)}</span></li>`).join('')}
        </ul>` : ''}

      ${data.projects.length ? `
        <h4>Из опыта</h4>
        ${data.projects.map(item => `
          <div class="paper-project">
            <b>${escape(item.name_ru)}</b>
            <p>${escape(item.text)}</p>
          </div>`).join('')}` : ''}

      ${data.contact_email ? `
        <h4>Контакты</h4>
        <p class="paper-contact">${escape(data.contact_email)}</p>` : ''}
    </div>
  `
}

async function loadPreview(state) {
  const result = await api(`/api/export/preview?include_contacts=${ui.includeContacts}`)
  ui.preview = result.ok ? result.payload : null

  const box = $('export-body')
  if (!box) return
  const note = $('export-note')
  if (!ui.preview) {
    note.textContent = ''
    box.innerHTML = `<div class="empty">
      Сначала выберите целевую роль — без неё резюме собирать не из чего.
    </div>`
    return
  }
  note.textContent = ui.preview.note_ru
  box.innerHTML = previewBody(ui.preview)
}

/* Предпросмотр обязан показывать текущее состояние профиля, а не то, каким
   оно было при открытии страницы. Но перезапрашивать его на каждый чих тоже
   незачем — сравниваем короткую подпись состояния. */
function signatureOf(state) {
  const snapshot = state.prof?.snapshots?.[0]
  return [
    snapshot?.overall_score ?? '-',
    snapshot?.level ?? '-',
    state.trust?.overall_score ?? '-',
    state.statements?.length ?? 0,
    state.evidence?.length ?? 0,
    ui.includeContacts
  ].join('|')
}

export function renderExport(state) {
  const box = $('export-body')
  if (!box) return

  const signature = signatureOf(state)
  if (signature !== ui.signature) {
    ui.signature = signature
    loadPreview(state)
  }

  if (!ui.preview) {
    box.innerHTML = '<div class="empty">Собираем предпросмотр…</div>'
    return
  }

  $('export-note').textContent = ui.preview.note_ru
  box.innerHTML = previewBody(ui.preview)
}

function message(text, kind = 'error') {
  const box = $('export-msg')
  if (!box) return
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

async function download(state) {
  ui.busy = true
  renderExport(state)
  message('')

  const response = await fetch('/api/export/pdf', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ format: 'pdf', include_contacts: ui.includeContacts })
  })

  ui.busy = false

  if (!response.ok) {
    let detail = 'Не удалось собрать файл.'
    try {
      detail = (await response.json()).detail || detail
    } catch {
      // тело может быть не JSON — тогда останется общая формулировка
    }
    renderExport(state)
    message(detail)
    return
  }

  // Файл отдаётся браузеру и дальше живёт у кандидата. Никуда, кроме диска,
  // он отсюда не уходит.
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'purpjob-profile.pdf'
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)

  renderExport(state)
  message('Файл у вас. Куда его отправить — решаете только вы.', 'ok')
}

async function onEvent(event, state) {
  if (event.target.id === 'export-contacts') {
    ui.includeContacts = event.target.checked
    renderExport(state)
    return
  }

  const trigger = event.target.closest('#export-block [data-act]')
  if (trigger?.dataset.act === 'export-download') await download(state)
}

export function initExport({ getState, root }) {
  root.addEventListener('click', event => onEvent(event, getState()))
  root.addEventListener('change', event => onEvent(event, getState()))
}

export function resetExport() {
  ui.preview = null
  ui.includeContacts = true
  ui.busy = false
  ui.signature = null
}
