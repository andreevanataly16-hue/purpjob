/* Модуль 2: One-Click Enrichment и Evidence.

   Экран собирается один раз, а всё, что зависит от данных, перерисовывается из
   store при каждом ответе сервера. Поэтому после любого действия - добавили
   ссылку, отказались от источника, ответили Слепому свидетелю - карта
   доказательств обновляется сама, без перезагрузки страницы. */

import './profile.css'
import { api, apiUpload, errorText } from './api.js'
import { applyProfile, clearProfile, getState, loadProfile, mutate, subscribe } from './store.js'
import { PROF_SKELETON, initProf, renderProf, resetProf } from './prof.js'
import { PROBE_SKELETON, askAbout, initProbe, renderProbe, resetProbe } from './probe.js'

/* ---------- словари: в коде английские значения, на экране русские ---------- */

const STATUS = {
  not_started: { ru: 'Нет подтверждений', term: 'Not started' },
  limited: { ru: 'Ограниченно', term: 'Limited' },
  medium: { ru: 'Средне', term: 'Medium' },
  strong: { ru: 'Сильно', term: 'Strong' }
}

const CATEGORY_RU = {
  'Hard Skill': 'Технические навыки',
  'Practical Understanding': 'Практическое понимание',
  'Complexity of Solved Tasks': 'Сложность решённых задач',
  'Professional Footprint': 'Профессиональный след'
}

const CATEGORY_ORDER = [
  'Hard Skill',
  'Practical Understanding',
  'Complexity of Solved Tasks',
  'Professional Footprint'
]

const EVIDENCE_RU = {
  link: 'Ссылка',
  file: 'Файл',
  free_text: 'Ваше описание',
  blind_witness_answer: 'Слепой свидетель'
}

const SOURCE_RU = {
  github: 'GitHub',
  gitlab: 'GitLab',
  linkedin: 'LinkedIn',
  portfolio: 'Портфолио',
  article: 'Статья',
  video: 'Видео',
  other: 'Другой источник'
}

const CONFIDENCE_RU = { high: 'уверенно', medium: 'вероятно', low: 'упоминание' }

const BLIND_WITNESS_QUESTION =
  'Какие 2–3 решения в этом проекте были критическими и почему вы выбрали именно так?'

/* ---------- временное состояние экрана (не данные, а что открыто) ---------- */

const ui = {
  parsed: null,
  rawInputId: null,
  expanded: new Set(),
  target: null,
  unsubscribe: null
}

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

function message(id, text, kind = 'error') {
  const box = $(id)
  if (!box) return
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

function busy(button, state, pendingText) {
  if (!button) return
  if (state) {
    button.dataset.idle = button.textContent
    button.textContent = pendingText || button.textContent
  } else if (button.dataset.idle) {
    button.textContent = button.dataset.idle
  }
  button.disabled = state
}

/* ---------- разметка экрана ---------- */

const SKELETON = `
  <div class="counters" id="counters"></div>

  ${PROF_SKELETON}

  ${PROBE_SKELETON}

  <section class="block">
    <h2>Расскажите о проекте</h2>
    <p class="sub">
      Одним куском текста, как рассказали бы коллеге: что делали, что было сложно,
      чем закончилось. Разберём на компетенции — что оставить, решаете вы.
    </p>

    <label class="nda-toggle">
      <input type="checkbox" id="nda-toggle">
      <span>
        Проект под NDA
        <small>Тогда мы не попросим ни описание, ни файлы — вместо этого один вопрос про логику решений.</small>
      </span>
    </label>

    <div id="intake-open">
      <textarea id="case-text"
        placeholder="Например: переписал биллинг с нуля на Python, вынес в отдельный сервис. Под нагрузкой старая схема не держала, добавили кеш и переработали индексы…"></textarea>
      <div class="row" style="margin-top:12px">
        <button type="button" class="action" id="parse-btn">Разобрать на компетенции</button>
      </div>
    </div>

    <div id="intake-nda" hidden>
      <p class="notice">
        Описание проекта, файлы и название клиента у вас не спрашивают и никуда не отправляют.
        Сохраняется только ваш ответ ниже.
      </p>
      <p class="question">${BLIND_WITNESS_QUESTION}</p>
      <textarea id="bw-answer" placeholder="Развилки и логика выбора — без названий, кода и коммерческих деталей"></textarea>
      <div class="row" style="margin-top:12px">
        <button type="button" class="action" id="bw-btn">Подтвердить без раскрытия</button>
        <button type="button" class="ghost" id="mirror-btn" disabled
          title="Появится вместе с Contextual Probe">Зеркальная задача — скоро</button>
      </div>
      <p class="sub" style="margin:10px 0 0">
        Отказ ничего не отнимает: статус компетенции от него не падает, объяснять причину не нужно.
      </p>
    </div>

    <div id="parse-results" class="parsed"></div>
    <p class="msg" id="intake-msg"></p>
  </section>

  <section class="block" id="artifacts">
    <h2>Ссылки и файлы</h2>
    <p class="sub">
      Всё, что существует отдельно от ваших слов: репозиторий, статья, сертификат, презентация.
      Добавлять можно сколько угодно и когда угодно — это никогда не обязательный шаг.
    </p>

    <div id="target-banner"></div>

    <div class="row">
      <input type="url" id="link-url" placeholder="https://github.com/…">
      <button type="button" class="action" id="link-btn">Добавить ссылку</button>
    </div>

    <div class="row" style="margin-top:12px">
      <input type="file" id="file-input" accept=".pdf,.docx,.png,.jpg,.jpeg" hidden>
      <button type="button" class="ghost" id="file-btn">Загрузить файл</button>
      <button type="button" class="ghost" disabled title="Появится в следующей версии">
        Подключить GitHub — скоро
      </button>
      <span class="sub" style="margin:0">PDF, DOCX, PNG или JPG до 10 МБ</span>
    </div>

    <p class="msg" id="artifact-msg"></p>
    <div id="evidence-list" style="margin-top:18px"></div>
  </section>

  <section class="block">
    <h2>Карта доказательств</h2>
    <p class="sub">
      Что чем подтверждено. У каждой компетенции — статус, причина именно такого
      статуса и одно понятное действие, которое его усилит.
    </p>
    <div id="evidence-map"></div>

    <div class="row" style="margin-top:18px">
      <input type="text" id="manual-name" placeholder="Добавить компетенцию вручную">
      <button type="button" class="ghost" id="manual-btn">Добавить</button>
    </div>
    <p class="msg" id="map-msg"></p>
  </section>
`

/* ---------- отрисовка данных ---------- */

function renderCounters(state) {
  const active = state.evidence.filter(item => item.status !== 'declined')
  const strong = state.statements.filter(item => item.status === 'strong')
  const confirmed = state.statements.filter(item => item.status !== 'not_started')

  $('counters').innerHTML = `
    <div class="counter"><b>${state.statements.length}</b> компетенций</div>
    <div class="counter"><b>${active.length}</b> доказательств</div>
    <div class="counter"><b>${confirmed.length}</b> подтверждено хотя бы чем-то</div>
    <div class="counter"><b>${strong.length}</b> со статусом «Сильно»</div>
  `
}

function evidenceTitle(item) {
  if (item.type === 'link') {
    return `<a href="${escape(item.url)}" target="_blank" rel="noopener">${escape(item.url)}</a>`
  }
  if (item.type === 'file') {
    return `<a href="/api/profile/evidence/${item.id}/file" target="_blank" rel="noopener">${escape(item.file_name)}</a>`
  }
  return escape(item.raw_text)
}

function evidenceChips(item) {
  const chips = [`<span class="chip grey">${EVIDENCE_RU[item.type] || item.type}</span>`]
  if (item.type === 'link' && item.source_category) {
    chips.push(`<span class="chip">${SOURCE_RU[item.source_category] || item.source_category}</span>`)
  }
  if (item.nda) chips.push('<span class="chip nda">материалы не раскрывались</span>')
  if (item.status === 'declined') chips.push('<span class="chip off">скрыто из профиля</span>')
  return chips.join('')
}

function evidenceLine(item, { statementId = null } = {}) {
  const actions = []
  if (statementId) {
    actions.push(`<button type="button" class="link-btn" data-act="unlink"
      data-stmt="${statementId}" data-ev="${item.id}">Отвязать</button>`)
  }
  if (item.status === 'declined') {
    actions.push(`<button type="button" class="link-btn" data-act="restore" data-ev="${item.id}">Вернуть</button>`)
  } else {
    actions.push(`<button type="button" class="link-btn" data-act="decline" data-ev="${item.id}">Скрыть</button>`)
  }
  if (!statementId) {
    actions.push(`<button type="button" class="link-btn" data-act="remove" data-ev="${item.id}">Удалить</button>`)
  }

  const linked = item.linked_statement_ids.length
  const meta = statementId
    ? ''
    : `<div class="meta">${linked ? `подтверждает компетенций: ${linked}` : 'пока ни к чему не привязано'}</div>`

  return `
    <div class="ev-line ${item.status === 'declined' ? 'declined' : ''}">
      <div class="body">
        <div class="title">${evidenceTitle(item)}</div>
        <div class="chips" style="margin-top:7px">${evidenceChips(item)}</div>
        ${meta}
      </div>
      <div class="ev-actions">${actions.join('')}</div>
    </div>
  `
}

function renderEvidenceList(state) {
  const box = $('evidence-list')
  const items = state.evidence.filter(item => item.type === 'link' || item.type === 'file')

  box.innerHTML = items.length
    ? items.map(item => evidenceLine(item)).join('')
    : '<div class="empty">Ссылок и файлов пока нет. Это не мешает пользоваться профилем — добавьте, когда будет удобно.</div>'
}

function statementCard(statement, evidenceById) {
  const status = STATUS[statement.status] || { ru: statement.status, term: statement.status }
  const open = ui.expanded.has(statement.id)
  const items = statement.evidence_ids.map(id => evidenceById.get(id)).filter(Boolean)

  const evidenceBlock = open
    ? `<div class="stmt-evidence">${
        items.length
          ? items.map(item => evidenceLine(item, { statementId: statement.id })).join('')
          : '<div class="empty">Ни одного доказательства — пока это только заявление.</div>'
      }</div>`
    : ''

  const next = statement.next_action
    ? `<div class="next">
         <span>${escape(statement.next_action)}</span>
         <button type="button" class="ghost" data-act="strengthen"
           data-stmt="${statement.id}" data-kind="${statement.next_action_kind}">Усилить</button>
       </div>`
    : ''

  const declined = statement.declined
    ? `<span class="chip nda">источник закрыт</span>
       <button type="button" class="link-btn" data-act="undecline" data-stmt="${statement.id}">Раскрыть</button>`
    : `<button type="button" class="link-btn" data-act="decline-stmt" data-stmt="${statement.id}">Не раскрывать источник</button>`

  return `
    <article class="stmt" data-stmt="${statement.id}">
      <div class="stmt-head" data-act="toggle" data-stmt="${statement.id}">
        <span class="stmt-name">${escape(statement.skill_name_ru)}</span>
        <span class="pill st-${statement.status}" title="${status.term}">${status.ru}</span>
        <span class="caret">${open ? '▲' : '▼'} ${items.length}</span>
      </div>
      <p class="why">${escape(statement.status_reason)}</p>
      <div class="chips" style="margin-top:9px">${declined}</div>
      ${next}
      ${evidenceBlock}
    </article>
  `
}

function renderMap(state) {
  const box = $('evidence-map')
  if (!state.statements.length) {
    box.innerHTML =
      '<div class="empty">Здесь появятся ваши компетенции — после того как вы опишете проект или добавите источник.</div>'
    return
  }

  const evidenceById = new Map(state.evidence.map(item => [item.id, item]))
  const groups = CATEGORY_ORDER
    .map(category => [category, state.statements.filter(item => item.category === category)])
    .filter(([, items]) => items.length)

  box.innerHTML = groups
    .map(([category, items]) => `
      <div class="cat">
        <h3>${CATEGORY_RU[category] || category}</h3>
        ${items.map(item => statementCard(item, evidenceById)).join('')}
      </div>
    `)
    .join('')
}

function renderTarget() {
  const box = $('target-banner')
  if (!ui.target) {
    box.innerHTML = ''
    return
  }
  const statement = getState().statements.find(item => item.id === ui.target)
  if (!statement) {
    ui.target = null
    box.innerHTML = ''
    return
  }
  box.innerHTML = `
    <div class="target-banner">
      <span>Усиливаем: <b>${escape(statement.skill_name_ru)}</b> — то, что добавите, привяжется к ней.</span>
      <button type="button" class="link-btn" data-act="clear-target">Отменить</button>
    </div>
  `
}

function renderParsed() {
  const box = $('parse-results')
  if (!ui.parsed) {
    box.innerHTML = ''
    return
  }

  if (!ui.parsed.length) {
    box.innerHTML = `
      <div class="empty">
        В тексте не нашлось знакомых компетенций. Попробуйте добавить конкретики: технологии,
        объёмы, что именно пришлось решить.
      </div>`
    return
  }

  box.innerHTML = `
    <div class="parsed-head">
      <h3>Нашли ${ui.parsed.length} — проверьте</h3>
      <span class="sub" style="margin:0">Ничего не сохранено: в профиль попадёт только отмеченное.</span>
    </div>
    ${ui.parsed.map((item, index) => `
      <div class="parsed-item ${item.accepted ? '' : 'off'}" data-index="${index}">
        <input type="checkbox" data-act="toggle-parsed" data-index="${index}" ${item.accepted ? 'checked' : ''}>
        <div class="body">
          <input type="text" data-act="rename" data-index="${index}" value="${escape(item.skill_name_ru)}">
          <div class="chips" style="margin-top:8px">
            <span class="chip grey">${CATEGORY_RU[item.category] || item.category}</span>
            <span class="chip">${CONFIDENCE_RU[item.confidence] || item.confidence}</span>
          </div>
          <p class="quote">${escape(item.excerpt)}</p>
        </div>
      </div>
    `).join('')}
    <div class="row" style="margin-top:14px">
      <button type="button" class="action" data-act="accept-parsed">Добавить отмеченное в профиль</button>
      <button type="button" class="ghost" data-act="discard-parsed">Не добавлять ничего</button>
    </div>
  `
}

function render(state) {
  renderCounters(state)
  renderEvidenceList(state)
  renderMap(state)
  renderTarget()
  renderProf(state)
  renderProbe(state)
}

/* ---------- действия ---------- */

function targetIds() {
  return ui.target ? [ui.target] : []
}

async function runParse() {
  const text = $('case-text').value.trim()
  message('intake-msg', '')

  if (!text) {
    message('intake-msg', 'Сначала опишите проект — хотя бы парой предложений.')
    return
  }

  const button = $('parse-btn')
  busy(button, true, 'Разбираем…')
  const result = await api('/api/profile/parse', {
    method: 'POST',
    body: JSON.stringify({ raw_text: text })
  })
  busy(button, false)

  if (!result.ok) {
    message('intake-msg', errorText(result.payload, 'Не удалось разобрать текст. Попробуйте ещё раз.'))
    return
  }

  ui.rawInputId = result.payload.raw_input_id
  ui.parsed = result.payload.items.map(item => ({ ...item, accepted: true }))
  renderParsed()
}

async function acceptParsed() {
  const chosen = (ui.parsed || []).filter(item => item.accepted)
  if (!chosen.length) {
    message('intake-msg', 'Отметьте хотя бы одну компетенцию — или нажмите «Не добавлять ничего».')
    return
  }

  const result = await mutate('/api/profile/statements/accept', {
    method: 'POST',
    body: JSON.stringify({
      raw_input_id: ui.rawInputId,
      items: chosen.map(item => ({
        skill_name: item.skill_name,
        skill_name_ru: item.skill_name_ru,
        category: item.category,
        excerpt: item.excerpt
      }))
    })
  })

  if (!result.ok) {
    message('intake-msg', errorText(result.payload, 'Не удалось сохранить. Попробуйте ещё раз.'))
    return
  }

  ui.parsed = null
  ui.rawInputId = null
  $('case-text').value = ''
  renderParsed()
  message('intake-msg', `Добавлено компетенций: ${chosen.length}. Ваш текст сохранён целиком.`, 'ok')
}

async function sendBlindWitness() {
  const answer = $('bw-answer').value.trim()
  message('intake-msg', '')

  if (answer.length < 20) {
    message('intake-msg', 'Опишите логику решений чуть подробнее — по паре фраз на развилку.')
    return
  }

  const button = $('bw-btn')
  busy(button, true, 'Сохраняем…')
  const result = await mutate('/api/profile/evidence/blind-witness', {
    method: 'POST',
    body: JSON.stringify({ answer, statement_ids: targetIds() })
  })
  busy(button, false)

  if (!result.ok) {
    message('intake-msg', errorText(result.payload, 'Не удалось сохранить ответ.'))
    return
  }

  $('bw-answer').value = ''
  ui.target = null
  renderTarget()
  message('intake-msg', 'Готово. Компетенция подтверждена, материалы остались закрытыми.', 'ok')
}

async function addLink() {
  const input = $('link-url')
  const url = input.value.trim()
  message('artifact-msg', '')

  if (!/^https?:\/\/[^\s.]+\.[^\s]{2,}$/.test(url)) {
    message('artifact-msg', 'Нужна ссылка целиком, вместе с https://')
    return
  }

  const button = $('link-btn')
  busy(button, true, 'Добавляем…')
  const result = await mutate('/api/profile/evidence/link', {
    method: 'POST',
    body: JSON.stringify({ url, statement_ids: targetIds() })
  })
  busy(button, false)

  if (!result.ok) {
    message('artifact-msg', errorText(result.payload, 'Ссылку добавить не вышло.'))
    return
  }

  input.value = ''
  ui.target = null
  renderTarget()
  message('artifact-msg', 'Ссылка добавлена.', 'ok')
}

async function uploadFile(file) {
  if (!file) return
  message('artifact-msg', '')

  const form = new FormData()
  form.append('file', file)
  form.append('statement_ids', targetIds().join(','))

  const button = $('file-btn')
  busy(button, true, 'Загружаем…')
  const result = await apiUpload('/api/profile/evidence/file', form)
  busy(button, false)

  if (!result.ok) {
    message('artifact-msg', errorText(result.payload, 'Файл загрузить не вышло.'))
    return
  }

  applyProfile(result.payload)
  ui.target = null
  renderTarget()
  message('artifact-msg', `Файл «${file.name}» добавлен.`, 'ok')
}

async function addManualStatement() {
  const input = $('manual-name')
  const name = input.value.trim()
  message('map-msg', '')

  if (!name) {
    message('map-msg', 'Напишите, какую компетенцию добавить.')
    return
  }

  const result = await mutate('/api/profile/statements', {
    method: 'POST',
    body: JSON.stringify({ skill_name_ru: name })
  })

  if (!result.ok) {
    message('map-msg', errorText(result.payload, 'Не удалось добавить компетенцию.'))
    return
  }

  input.value = ''
  message('map-msg', 'Компетенция добавлена — теперь её можно подтвердить.', 'ok')
}

/* Кнопка «Усилить»: подсказанное действие ведёт к нужному полю. */
function strengthen(statementId, kind) {
  ui.target = statementId
  renderTarget()

  if (kind === 'blind_witness') {
    $('nda-toggle').checked = true
    toggleNda()
    $('bw-answer').focus()
    $('bw-answer').scrollIntoView({ behavior: 'smooth', block: 'center' })
    return
  }

  const field = kind === 'add_file' ? 'file-btn' : 'link-url'
  $('artifacts').scrollIntoView({ behavior: 'smooth', block: 'start' })
  $(field).focus({ preventScroll: true })
}

function toggleNda() {
  const on = $('nda-toggle').checked
  $('intake-open').hidden = on
  $('intake-nda').hidden = !on
  message('intake-msg', '')
  if (on) {
    // Текст закрытого проекта не должен уехать на сервер даже случайно.
    $('case-text').value = ''
    ui.parsed = null
    renderParsed()
  }
}

/* ---------- обработчики ---------- */

function onProfileClick(event) {
  const trigger = event.target.closest('[data-act]')
  if (!trigger) return

  const { act, stmt, ev, kind, index } = trigger.dataset

  const actions = {
    toggle: () => {
      ui.expanded.has(stmt) ? ui.expanded.delete(stmt) : ui.expanded.add(stmt)
      renderMap(getState())
    },
    strengthen: () => strengthen(stmt, kind),
    'clear-target': () => { ui.target = null; renderTarget() },
    unlink: () => mutate(`/api/profile/statements/${stmt}/evidence/${ev}`, { method: 'DELETE' }),
    decline: () => mutate(`/api/profile/evidence/${ev}/decline`, {
      method: 'POST',
      body: JSON.stringify({ reason: null })
    }),
    restore: () => mutate(`/api/profile/evidence/${ev}/decline`, { method: 'DELETE' }),
    remove: () => mutate(`/api/profile/evidence/${ev}`, { method: 'DELETE' }),
    'decline-stmt': () => mutate(`/api/profile/statements/${stmt}/decline`, {
      method: 'POST',
      body: JSON.stringify({ reason: null })
    }),
    undecline: () => mutate(`/api/profile/statements/${stmt}/decline`, { method: 'DELETE' }),
    'accept-parsed': acceptParsed,
    'discard-parsed': () => { ui.parsed = null; ui.rawInputId = null; renderParsed() },
    'toggle-parsed': () => {
      ui.parsed[index].accepted = trigger.checked
      trigger.closest('.parsed-item').classList.toggle('off', !trigger.checked)
    }
  }

  const handler = actions[act]
  if (handler) handler()
}

function onProfileInput(event) {
  const trigger = event.target.closest('[data-act="rename"]')
  if (trigger) ui.parsed[trigger.dataset.index].skill_name_ru = trigger.value
}

/* ---------- вход и выход с экрана ---------- */

export async function initProfile() {
  const root = $('profile-root')
  if (!root.dataset.ready) {
    root.innerHTML = SKELETON
    root.dataset.ready = '1'

    $('parse-btn').addEventListener('click', runParse)
    $('bw-btn').addEventListener('click', sendBlindWitness)
    $('link-btn').addEventListener('click', addLink)
    $('manual-btn').addEventListener('click', addManualStatement)
    $('nda-toggle').addEventListener('change', toggleNda)
    $('file-btn').addEventListener('click', () => $('file-input').click())
    $('file-input').addEventListener('change', event => {
      uploadFile(event.target.files[0])
      event.target.value = ''
    })
    $('link-url').addEventListener('keydown', event => {
      if (event.key === 'Enter') addLink()
    })
    $('manual-name').addEventListener('keydown', event => {
      if (event.key === 'Enter') addManualStatement()
    })

    root.addEventListener('click', onProfileClick)
    root.addEventListener('input', onProfileInput)

    // Белое пятно закрывается инструментами модуля 2, поэтому PROF.индекс
    // получает ту же точку входа, что и кнопка «Усилить» в карте доказательств.
    initProf({ onStrengthen: strengthen, onProbe: askAbout, getState, root })
    initProbe({ getState, root })
  }

  document.querySelector('.card').classList.add('wide')
  if (!ui.unsubscribe) ui.unsubscribe = subscribe(render)
  await loadProfile()
}

export function resetProfile() {
  resetProf()
  resetProbe()
  ui.parsed = null
  ui.rawInputId = null
  ui.target = null
  ui.expanded.clear()
  document.querySelector('.card').classList.remove('wide')
  clearProfile()
}
