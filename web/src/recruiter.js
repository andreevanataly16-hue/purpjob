/* Рекрутерская сторона: поиск, карточка, сравнение (модуль 12).

   Первый экран продукта с другим читателем. Тон здесь другой — деловой, без
   мягкости кандидатской части, — но правило то же: никаких «сильный» и
   «слабый», только что подтверждено и чем.

   Роль рекрутера — режим экрана, а не вход: настоящих прав доступа в продукте
   нет, и предупреждение об этом стоит прямо в блоке. */

import './recruiter.css'
import { api } from './api.js'

const ui = {
  on: false,
  vacancyId: 'vac_001',
  sortBy: 'match_score',
  minTrust: 0,
  level: '',
  data: null,
  open: null,
  detail: null,
  selected: new Set(),
  compare: null
}

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

const SORT_RU = {
  match_score: 'по совпадению',
  trust_score: 'по достоверности',
  prof_index: 'по индексу'
}

const STATUS_RU = {
  not_started: 'нет подтверждений',
  limited: 'ограниченно',
  medium: 'подтверждено',
  strong: 'подтверждено независимо'
}

export const RECRUITER_SKELETON = `
  <section class="block" id="recruiter-block">
    <div class="rec-head">
      <div>
        <h2>Режим рекрутера</h2>
        <p class="sub" style="margin-bottom:0">
          Поиск по уже подтверждённым профилям вместо стопки резюме.
        </p>
      </div>
      <button type="button" class="ghost" data-act="rec-toggle" id="rec-toggle">Открыть поиск</button>
    </div>
    <div id="recruiter-body" hidden></div>
    <p class="msg" id="rec-msg"></p>
  </section>
`

/* ---------- карточка в списке ---------- */

function candidateRow(item) {
  const selected = ui.selected.has(item.candidate_id)
  return `
    <div class="rec-card ${ui.open === item.candidate_id ? 'open' : ''}">
      <div class="rec-card-head">
        <span class="rec-avatar">${escape(item.photo_label)}</span>
        <div class="rec-who">
          <b>${escape(item.display_name)}</b>
          <span>${item.levels.map(escape).join(', ')}</span>
        </div>
        <div class="rec-numbers">
          <span><b>${item.match_score}</b> совпадение</span>
          <span><b>${item.prof_index}</b> индекс</span>
          <span><b>${item.trust_score}</b> достоверность</span>
        </div>
      </div>

      <div class="rec-card-actions">
        <span class="rec-counts">
          закрыто требований: ${item.covered_count}, требует проверки: ${item.uncovered_count}
        </span>
        ${item.consent_for_recruiter_view
          ? ''
          : '<span class="chip grey">доказательства не раскрыты</span>'}
        <label class="rec-pick">
          <input type="checkbox" data-act="rec-pick" data-id="${escape(item.candidate_id)}"
            ${selected ? 'checked' : ''}> в сравнение
        </label>
        <button type="button" class="link-btn" data-act="rec-open"
          data-id="${escape(item.candidate_id)}">
          ${ui.open === item.candidate_id ? 'Свернуть' : 'Открыть профиль'}
        </button>
      </div>

      <div id="rec-detail-${escape(item.candidate_id)}" class="rec-detail"></div>
    </div>`
}

/* ---------- подробности ---------- */

function detailBody(detail) {
  const requirement = (item, covered) => `
    <div class="rec-req ${covered ? 'covered' : 'uncovered'}">
      <span class="rec-req-label">${escape(item.label_ru)}</span>
      <span class="chip grey">${escape(item.criticality_ru)}</span>
      <p>${escape(item.explanation_ru)}</p>
    </div>`

  return `
    <h4 class="rec-h">Требования вакансии «${escape(detail.vacancy_title_ru)}»</h4>
    ${detail.covered.map(item => requirement(item, true)).join('')}
    ${detail.uncovered.map(item => requirement(item, false)).join('')}
    ${detail.unevaluated_clusters.length ? `
      <div class="rec-unevaluated">
        <b>${detail.unevaluated_clusters.map(escape).join(', ')}</b>
        <p>${escape(detail.unevaluated_note_ru)}</p>
      </div>` : ''}

    <h4 class="rec-h">Достоверность профиля</h4>
    <p class="rec-consent">${escape(detail.consent_note_ru)}</p>
    ${detail.trust_components.map(item => `
      <div class="rec-trust">
        <div class="rec-trust-head">
          <span>${escape(item.name_ru)}</span>
          <b>${item.score}</b>
        </div>
        <p>${escape(item.explanation_ru)}</p>
        ${item.evidence_visible && item.evidence_refs.length
          ? `<p class="rec-refs">Доказательства: ${item.evidence_refs.map(escape).join(', ')}</p>`
          : ''}
      </div>`).join('')}
    ${detail.nda_note_ru
      ? `<p class="rec-nda">Часть подтверждений — ${escape(detail.nda_note_ru)}.</p>`
      : ''}

    <h4 class="rec-h">Компетенции</h4>
    <div class="rec-competencies">
      ${detail.prof_components.map(item => `
        <div class="rec-comp">
          <span class="rec-comp-name">${escape(item.name_ru)}</span>
          <span class="chip ${item.status === 'not_started' ? 'grey' : ''}">
            ${escape(STATUS_RU[item.status] ?? item.status)}
          </span>
          <p>${escape(item.reason)}</p>
        </div>`).join('')}
    </div>`
}

/* ---------- сравнение ---------- */

function compareTable(data) {
  const rows = [
    ['Совпадение с вакансией', item => item.match_score],
    ['PROF.индекс', item => item.prof_index],
    ['Достоверность', item => item.trust_score],
    ['Требований закрыто', item => item.covered_count],
    ['Требует проверки', item => item.uncovered_count],
    [
      'Не закрыто из обязательных',
      item => item.uncovered.filter(r => r.criticality_ru === 'обязательное').length
    ]
  ]

  return `
    <div class="rec-compare">
      <h4 class="rec-h">Сравнение — одни и те же поля у всех</h4>
      <div class="rec-table-wrap">
        <table class="rec-table">
          <thead>
            <tr>
              <th></th>
              ${data.candidates.map(item => `<th>${escape(item.display_name)}</th>`).join('')}
            </tr>
          </thead>
          <tbody>
            ${rows.map(([label, get]) => `
              <tr>
                <td>${label}</td>
                ${data.candidates.map(item => `<td>${get(item)}</td>`).join('')}
              </tr>`).join('')}
            <tr>
              <td>Требует дополнительной проверки</td>
              ${data.candidates.map(item => `
                <td class="rec-gaps">
                  ${item.uncovered.map(r => escape(r.label_ru)).join('<br>') || '—'}
                </td>`).join('')}
            </tr>
          </tbody>
        </table>
      </div>
    </div>`
}

/* ---------- сборка ---------- */

export function renderRecruiter() {
  const box = $('recruiter-body')
  const toggle = $('rec-toggle')
  if (!box || !toggle) return

  box.hidden = !ui.on
  toggle.textContent = ui.on ? 'Закрыть поиск' : 'Открыть поиск'
  if (!ui.on || !ui.data) return

  const data = ui.data
  box.innerHTML = `
    <div class="rec-warning">${escape(data.not_production_safe_ru)}</div>
    <p class="sub">${escape(data.note_ru)}</p>

    <div class="rec-filters">
      <label>Вакансия
        <select id="rec-vacancy">
          ${data.available_vacancies.map(item => `
            <option value="${escape(item.id)}" ${item.id === ui.vacancyId ? 'selected' : ''}>
              ${escape(item.title_ru)} (${escape(item.stated_level)})
            </option>`).join('')}
        </select>
      </label>
      <label>Порядок
        <select id="rec-sort">
          ${Object.entries(SORT_RU).map(([value, label]) => `
            <option value="${value}" ${value === ui.sortBy ? 'selected' : ''}>${label}</option>`).join('')}
        </select>
      </label>
      <label>Уровень
        <select id="rec-level">
          <option value="" ${ui.level === '' ? 'selected' : ''}>любой</option>
          <option value="Middle" ${ui.level === 'Middle' ? 'selected' : ''}>Middle</option>
          <option value="Senior" ${ui.level === 'Senior' ? 'selected' : ''}>Senior</option>
        </select>
      </label>
      <label>Достоверность не ниже
        <input type="number" id="rec-trust" min="0" max="100" value="${ui.minTrust}">
      </label>
    </div>

    ${data.candidates.length
      ? data.candidates.map(candidateRow).join('')
      : '<div class="empty">Под эти условия никто не подошёл.</div>'}

    ${ui.selected.size > 1
      ? `<button type="button" class="action" data-act="rec-compare">
           Сравнить выбранных (${ui.selected.size})
         </button>`
      : ''}

    ${ui.compare ? compareTable(ui.compare) : ''}
  `

  if (ui.open && ui.detail?.candidate_id === ui.open) {
    const target = $(`rec-detail-${ui.open}`)
    if (target) target.innerHTML = detailBody(ui.detail)
  }
}

/* ---------- действия ---------- */

function message(text, kind = 'error') {
  const box = $('rec-msg')
  if (!box) return
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

async function load() {
  const params = new URLSearchParams({
    vacancy_id: ui.vacancyId,
    sort_by: ui.sortBy,
    min_trust_score: String(ui.minTrust)
  })
  if (ui.level) params.set('level', ui.level)

  const result = await api(`/api/recruiter/search?${params}`)
  if (!result.ok) {
    message('Не удалось выполнить поиск.')
    return
  }
  ui.data = result.payload
  renderRecruiter()
}

async function loadDetail(id) {
  const result = await api(
    `/api/recruiter/candidates/${id}?vacancy_id=${encodeURIComponent(ui.vacancyId)}`
  )
  if (!result.ok) {
    message('Профиль недоступен.')
    return
  }
  ui.detail = result.payload
  renderRecruiter()
}

async function onEvent(event) {
  const target = event.target

  if (['rec-vacancy', 'rec-sort', 'rec-level', 'rec-trust'].includes(target.id)) {
    if (target.id === 'rec-vacancy') {
      ui.vacancyId = target.value
      ui.detail = null
      ui.compare = null
    }
    if (target.id === 'rec-sort') ui.sortBy = target.value
    if (target.id === 'rec-level') ui.level = target.value
    if (target.id === 'rec-trust') ui.minTrust = Number(target.value) || 0
    await load()
    if (ui.open) await loadDetail(ui.open)
    return
  }

  const trigger = target.closest('#recruiter-block [data-act]')
  if (!trigger) return
  const { act, id } = trigger.dataset

  if (act === 'rec-toggle') {
    ui.on = !ui.on
    renderRecruiter()
    if (ui.on && !ui.data) await load()
    return
  }

  if (act === 'rec-pick') {
    if (trigger.checked) ui.selected.add(id)
    else ui.selected.delete(id)
    ui.compare = null
    renderRecruiter()
    return
  }

  if (act === 'rec-open') {
    ui.open = ui.open === id ? null : id
    ui.detail = null
    renderRecruiter()
    if (ui.open) await loadDetail(ui.open)
    return
  }

  if (act === 'rec-compare') {
    const ids = [...ui.selected].join(',')
    const result = await api(
      `/api/recruiter/compare?vacancy_id=${encodeURIComponent(ui.vacancyId)}&ids=${ids}`
    )
    if (!result.ok) {
      message('Не удалось собрать сравнение.')
      return
    }
    ui.compare = result.payload
    renderRecruiter()
  }
}

export function initRecruiter({ root }) {
  root.addEventListener('click', onEvent)
  root.addEventListener('change', onEvent)
}

export function resetRecruiter() {
  ui.on = false
  ui.data = null
  ui.open = null
  ui.detail = null
  ui.compare = null
  ui.selected.clear()
}
