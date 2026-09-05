/* Лента вакансий и Match Score (модуль 10).

   Экран построен вокруг одной мысли: вот как накопленный профиль относится к
   этой конкретной возможности. Поэтому здесь нет кнопки отклика, нет счётчика
   просмотренных вакансий и нет «осталось два дня» — всё это превращало бы
   продукт в ленту, на которую реагируют, а не в связь профиля с работой.

   Совпадение экран не считает: оно приходит с сервера как проекция PROF.индекса
   и пересчитывается на каждый запрос. */

import './vacancies.css'
import { api } from './api.js'
import { mutateProbe } from './store.js'

const ui = { open: null, detail: null, onAddEvidence: () => {} }

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

const ACTION_RU = {
  answer_existing_probe: 'Ответить на вопрос по этой компетенции',
  add_evidence: 'Добавить доказательство'
}

export const VACANCIES_SKELETON = `
  <section class="block" id="vacancies-block">
    <h2>Подходящие вакансии</h2>
    <p class="sub" id="vacancies-note"></p>
    <div id="vacancies-body"></div>
    <p class="msg" id="vacancies-msg"></p>
  </section>
`

/* ---------- карточка ---------- */

function card(item) {
  const gaps = item.mandatory_gaps
    ? `<span class="vac-gap">не закрыто обязательных: ${item.mandatory_gaps}</span>`
    : '<span class="vac-ok">обязательные требования закрыты</span>'

  return `
    <div class="vacancy ${ui.open === item.id ? 'open' : ''}">
      <div class="vac-head">
        <div class="vac-title">
          <b>${escape(item.title_ru)}</b>
          <span class="vac-company">${escape(item.company_label)}</span>
        </div>
        <div class="vac-score">
          <span class="vac-value">${item.overall_match_score}</span>
          <span class="vac-of">совпадение</span>
        </div>
      </div>

      <div class="vac-meta">
        <span class="chip grey">${escape(item.stated_level)}</span>
        ${item.industry_context ? `<span class="chip grey">${escape(item.industry_context)}</span>` : ''}
        ${item.role_breadth !== 'low'
          ? `<span class="chip nda">${escape(item.role_breadth_ru)}</span>`
          : ''}
        ${gaps}
        <button type="button" class="link-btn" data-act="vac-open" data-id="${escape(item.id)}">
          ${ui.open === item.id ? 'Свернуть' : 'Разобрать требования'}
        </button>
      </div>

      <div class="vac-sources">
        Источники: ${item.source_channels.map(escape).join(', ')}
      </div>

      <div id="vac-detail-${escape(item.id)}" class="vac-detail"></div>
    </div>`
}

/* ---------- разбор требований ---------- */

function requirementRow(item, covered) {
  const action = !covered && item.recommended_action
    ? `<button type="button" class="ghost" data-act="vac-act"
         data-action="${escape(item.recommended_action)}"
         data-competency="${escape(item.competency_id ?? '')}"
         data-label="${escape(item.label_ru)}">
         ${escape(ACTION_RU[item.recommended_action])}
       </button>`
    : ''

  return `
    <div class="req ${covered ? 'covered' : 'uncovered'}">
      <div class="req-head">
        <span class="req-label">${escape(item.label_ru)}</span>
        <span class="chip ${item.criticality === 'mandatory' ? '' : 'grey'}">
          ${escape(item.criticality_ru)}
        </span>
      </div>
      <p class="req-why">${escape(item.explanation_ru)}</p>
      ${action}
    </div>`
}

export function renderVacancyDetail(detail) {
  const box = $(`vac-detail-${detail.id}`)
  if (!box) return

  box.innerHTML = `
    ${detail.note_ru ? `<p class="vac-breadth">${escape(detail.note_ru)}</p>` : ''}

    ${detail.cluster_scores.length > 1 ? `
      <div class="vac-clusters">
        ${detail.cluster_scores.map(item => `
          <span>${escape(item.cluster_label_ru)}: <b>${item.score}</b></span>`).join('')}
      </div>` : ''}

    ${detail.uncovered.length ? `
      <h4 class="vac-h">Чего не хватает</h4>
      ${detail.uncovered.map(item => requirementRow(item, false)).join('')}` : ''}

    ${detail.covered.length ? `
      <h4 class="vac-h">Уже подтверждено</h4>
      ${detail.covered.map(item => requirementRow(item, true)).join('')}` : ''}

    ${detail.unevaluated_clusters.length ? `
      <div class="vac-unevaluated">
        <b>${detail.unevaluated_clusters.map(escape).join(', ')}</b>
        <p>${escape(detail.unevaluated_note_ru)}</p>
      </div>` : ''}
  `
}

export function renderVacancies(state) {
  const box = $('vacancies-body')
  if (!box || !state.vacancies) return

  const data = state.vacancies
  $('vacancies-note').textContent = data.note_ru

  box.innerHTML = data.vacancies.length
    ? data.vacancies.map(card).join('')
    : '<div class="empty">Пока нечего показать.</div>'

  // Раскрытая вакансия перерисовывается вместе с лентой: совпадение могло
  // измениться, пока кандидат закрывал пробел.
  if (ui.open) refreshDetail(ui.open)
}

async function refreshDetail(id) {
  const result = await api(`/api/vacancies/${id}`)
  if (!result.ok) {
    message('Не удалось открыть разбор требований.')
    return
  }
  ui.detail = result.payload
  renderVacancyDetail(result.payload)
}

/* ---------- действия ---------- */

function message(text, kind = 'error') {
  const box = $('vacancies-msg')
  if (!box) return
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

async function onClick(event, state) {
  const trigger = event.target.closest('#vacancies-block [data-act]')
  if (!trigger) return

  const { act, id, action, competency, label } = trigger.dataset

  if (act === 'vac-open') {
    ui.open = ui.open === id ? null : id
    ui.detail = null
    renderVacancies(state)
    if (ui.open) await refreshDetail(ui.open)
    return
  }

  if (act !== 'vac-act') return

  // Своего механизма закрытия пробела у модуля нет: он только приводит
  // кандидата к уже существующим — вопросу модуля 4 или доказательству
  // модуля 2. Третьего пути тут не появляется.
  message('')

  if (action === 'answer_existing_probe') {
    const result = await mutateProbe('/api/probe/next', {
      method: 'POST',
      body: JSON.stringify({ competency_id: competency })
    })
    if (!result.ok) {
      message(result.payload?.detail || 'Не удалось подобрать вопрос.')
      return
    }
    document.getElementById('probe-block')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }

  // Требования, которого нет ни в одном эталоне, вопросом не закрыть:
  // генерировать вопрос под вакансию — это Vacancy-Specific Probe, он отложен.
  ui.onAddEvidence(label)
}

export function initVacancies({ getState, root, onAddEvidence }) {
  ui.onAddEvidence = onAddEvidence
  root.addEventListener('click', event => onClick(event, getState()))
}

export function resetVacancies() {
  ui.open = null
  ui.detail = null
}
