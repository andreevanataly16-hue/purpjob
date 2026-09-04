/* PROF.индекс: проекция подтверждённого опыта на эталон роли (модуль 3).

   Экран ничего не считает сам - весь расчёт приходит с сервера и пересчитывается
   там на каждый запрос. Задача этого файла: показать индекс, радар, статусы с
   объяснениями и белые пятна, а действия по их закрытию отдать модулю 2. */

import './prof.css'
import { mutate, mutateProf } from './store.js'

const STATUS_RU = {
  not_started: { ru: 'Нет подтверждений', term: 'Not started' },
  limited: { ru: 'Ограниченно', term: 'Limited' },
  medium: { ru: 'Средне', term: 'Medium' },
  strong: { ru: 'Сильно', term: 'Strong' }
}

const CATEGORY_RU = {
  hard_skill: 'Технические навыки',
  task_complexity: 'Сложность решённых задач'
}

const DEPTH_RU = { basic: 'базово', working: 'уверенно', deep: 'глубоко' }

const WHITE_SPOT_STATUSES = ['not_started', 'limited']
const SPOTS_SHOWN = 5

/* Что открыто на экране: данные тут не хранятся. */
const ui = {
  level: null,
  filter: 'all',
  allSpots: false,
  onStrengthen: () => {},
  getState: () => ({})
}

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

export const PROF_SKELETON = `
  <section class="block prof">
    <div class="prof-head">
      <div>
        <h2>PROF.индекс</h2>
        <p class="sub" style="margin-bottom:0">
          Не пересказ резюме, а измеримые характеристики: насколько требования
          эталона роли закрыты вашими доказательствами.
        </p>
      </div>
    </div>
    <div id="prof-body"></div>
    <p class="msg" id="prof-msg"></p>
  </section>

  <section class="block" id="white-spots-block">
    <h2>Белые пятна</h2>
    <p class="sub">
      Что стоит подтвердить в первую очередь — по влиянию на индекс, а не списком
      всего подряд.
    </p>
    <div id="white-spots"></div>
  </section>

  <section class="block">
    <h2>Видимость профиля</h2>
    <p class="sub">
      Индекс работает одинаково в обоих режимах: скрытый профиль — это тот же
      Self-Audit, а не урезанная версия.
    </p>
    <div class="visibility" id="visibility"></div>
    <p class="sub" style="margin:12px 0 0">
      Рекрутерской стороны в продукте пока нет, поэтому «Полная видимость» ничего
      никуда не публикует — режим сохраняется на будущее. Профиль никогда не
      открывается сам: это всегда ваше решение.
    </p>
  </section>
`

/* ---------- радар (FR1.4) ---------- */

function radarSvg(points) {
  const size = 520
  const center = size / 2
  const radius = 148
  const count = points.length
  const angle = index => (Math.PI * 2 * index) / count - Math.PI / 2
  const at = (index, value) => [
    center + Math.cos(angle(index)) * radius * value,
    center + Math.sin(angle(index)) * radius * value
  ]
  const polygon = values => values.map((value, index) => at(index, value).join(',')).join(' ')

  const rings = [0.25, 0.5, 0.75, 1]
    .map(step => `<polygon class="grid" points="${polygon(points.map(() => step))}"/>`)
    .join('')

  const axes = points
    .map((_, index) => {
      const [x, y] = at(index, 1)
      return `<line class="axis" x1="${center}" y1="${center}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}"/>`
    })
    .join('')

  const labels = points
    .map((point, index) => {
      // Подписи чередуют радиус: 17 осей иначе наезжают друг на друга.
      const [x, y] = at(index, index % 2 ? 1.24 : 1.13)
      const cos = Math.cos(angle(index))
      const anchor = Math.abs(cos) < 0.25 ? 'middle' : cos > 0 ? 'start' : 'end'
      const gap = point.candidate_value < point.reference_value ? ' gap' : ''
      return `<text class="axis-label${gap}" x="${x.toFixed(1)}" y="${y.toFixed(1)}"
        text-anchor="${anchor}" dominant-baseline="middle">${escape(point.short_ru)}</text>`
    })
    .join('')

  const dots = points
    .map((point, index) => {
      const [x, y] = at(index, point.candidate_value)
      return `<circle class="me-dot" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3"/>`
    })
    .join('')

  // Поле шире холста радара: подписи осей уезжают за круг и слева обрезались бы.
  // По вертикали, наоборот, подрезаем пустоту - иначе диаграмма тонет в полях.
  const pad = 78
  const top = 46
  return `
    <svg viewBox="${-pad} ${top} ${size + pad * 2} ${size - top * 2}" role="img"
         aria-label="Радар компетенций: требования эталона и подтверждённый опыт">
      ${rings}
      ${axes}
      <polygon class="ref-shape" points="${polygon(points.map(p => p.reference_value))}"/>
      <polygon class="me-shape" points="${polygon(points.map(p => p.candidate_value))}"/>
      ${dots}
      ${labels}
    </svg>
  `
}

/* ---------- блоки ---------- */

function statusPill(status) {
  const view = STATUS_RU[status] || { ru: status, term: status }
  return `<span class="pill st-${status}" title="${view.term}">${view.ru}</span>`
}

function rolesRow(prof) {
  const declared = prof.snapshots.map(item => item.level)
  const tabs = prof.snapshots
    .map(item => `
      <button type="button" class="role-tab" data-act="pick-role" data-level="${item.level}"
        aria-selected="${item.level === ui.level}">
        ${item.level} <b>${item.overall_score}</b>
      </button>`)
    .join('')

  const missing = prof.available_levels
    .filter(level => !declared.includes(level))
    .map(level => `
      <button type="button" class="role-tab add" data-act="add-role" data-level="${level}">
        + ${level}
      </button>`)
    .join('')

  return `<div class="roles">${tabs}${missing}</div>`
}

function competencyList(snapshot) {
  const visible = snapshot.components.filter(item => {
    if (ui.filter === 'gaps') return WHITE_SPOT_STATUSES.includes(item.status)
    if (ui.filter === 'confirmed') return !WHITE_SPOT_STATUSES.includes(item.status)
    return true
  })

  if (!visible.length) {
    return '<div class="empty">В этом срезе пусто — попробуйте другой фильтр.</div>'
  }

  return Object.entries(CATEGORY_RU)
    .map(([category, title]) => {
      const items = visible.filter(item => item.category === category)
      if (!items.length) return ''
      return `
        <div class="cat">
          <h3>${title}</h3>
          ${items.map(competencyRow).join('')}
        </div>`
    })
    .join('')
}

function competencyRow(item) {
  return `
    <div class="comp">
      <div class="body">
        <div class="name">
          ${escape(item.name_ru)}
          ${statusPill(item.status)}
          ${item.heuristic_applied ? '<span class="chip nda">эвристика</span>' : ''}
        </div>
        <p class="why">${escape(item.reason)}</p>
      </div>
      <div class="weight">
        вес ${Math.round(item.weight * 100)}%<br>нужно ${DEPTH_RU[item.required_depth]}
      </div>
    </div>`
}

function renderBody(prof) {
  const box = $('prof-body')

  if (!prof.snapshots.length) {
    box.innerHTML = `
      ${rolesRow(prof)}
      <div class="empty">
        Выберите целевой уровень — и увидите, насколько ваши доказательства закрывают
        требования эталона роли.
        Сегмент пока один: ${escape(prof.segment)}.
      </div>`
    return
  }

  const snapshot = prof.snapshots.find(item => item.level === ui.level) || prof.snapshots[0]
  ui.level = snapshot.level

  box.innerHTML = `
    ${rolesRow(prof)}

    <div class="score-line">
      <span class="score-value">${snapshot.overall_score}</span>
      <span class="score-of">из 100 — покрытие эталона доказательствами</span>
      <span class="score-role">${escape(snapshot.segment)} · ${escape(snapshot.level)}</span>
      <button type="button" class="link-btn" data-act="drop-role" data-level="${snapshot.level}">
        Убрать роль
      </button>
    </div>

    <div class="radar-wrap">
      <div class="radar">${radarSvg(snapshot.radar_points)}</div>
      <div class="legend">
        <div><i class="ref"></i> требование эталона</div>
        <div><i></i> ваш подтверждённый опыт</div>
        <div style="color:#ffc47a">жёлтая подпись — до требования не дотягивает</div>
      </div>
    </div>

    <div class="filters">
      <button type="button" class="filter" data-act="filter" data-value="all"
        aria-pressed="${ui.filter === 'all'}">Все компетенции</button>
      <button type="button" class="filter" data-act="filter" data-value="gaps"
        aria-pressed="${ui.filter === 'gaps'}">Слабые места</button>
      <button type="button" class="filter" data-act="filter" data-value="confirmed"
        aria-pressed="${ui.filter === 'confirmed'}">Подтверждённые</button>
    </div>

    ${competencyList(snapshot)}

    <p class="disclaimer">
      Индекс показывает, насколько требования эталона закрыты доказательствами, — это не
      оценка ваших знаний. «60» у компетенции значит «доказательная база тянет на 0,6 по
      текущей модели», а не «знаю на 60%». Требуемая глубина (базово, уверенно, глубоко) —
      ориентир эталона на радаре, в расчёт она пока не входит. Веса и перевод статуса в
      баллы — рабочая гипотеза первого сегмента, числа будут меняться после калибровки.
    </p>
  `
}

function renderWhiteSpots(prof) {
  const box = $('white-spots')
  const snapshot = prof.snapshots.find(item => item.level === ui.level)

  if (!snapshot) {
    box.innerHTML =
      '<div class="empty">Белые пятна появятся, когда вы выберете целевой уровень.</div>'
    return
  }

  const spots = snapshot.white_spots
    .map(id => snapshot.components.find(item => item.competency_id === id))
    .filter(Boolean)

  if (!spots.length) {
    box.innerHTML = `
      <div class="empty">
        Белых пятен нет: каждое требование эталона ${escape(snapshot.level)} чем-то подтверждено.
      </div>`
    return
  }

  const shown = ui.allSpots ? spots : spots.slice(0, SPOTS_SHOWN)

  box.innerHTML = `
    ${shown.map((item, index) => `
      <div class="spot">
        <div class="rank">${index + 1}</div>
        <div class="body">
          <div class="name">${escape(item.name_ru)} ${statusPill(item.status)}</div>
          <p class="why">${escape(item.reason)}</p>
        </div>
        <div class="ev-actions">
          <button type="button" class="ghost" data-act="close-spot"
            data-competency="${item.competency_id}">Подтвердить</button>
          <button type="button" class="ghost" data-act="probe-spot"
            data-competency="${item.competency_id}">Ответить на вопрос</button>
        </div>
      </div>`).join('')}
    ${spots.length > SPOTS_SHOWN ? `
      <button type="button" class="link-btn" data-act="toggle-spots">
        ${ui.allSpots ? 'Показать только главные' : `Показать все — ещё ${spots.length - SPOTS_SHOWN}`}
      </button>` : ''}
  `
}

function renderVisibility(prof) {
  const mode = prof.visibility.mode
  $('visibility').innerHTML = `
    <button type="button" class="vis-card" data-act="visibility" data-mode="hidden"
      aria-pressed="${mode === 'hidden'}">
      <b>Инкогнито</b>
      <span>Профиль видите только вы. Индекс, радар и белые пятна работают полностью.</span>
    </button>
    <button type="button" class="vis-card" data-act="visibility" data-mode="visible"
      aria-pressed="${mode === 'visible'}">
      <b>Полная видимость</b>
      <span>Профиль открыт — когда в продукте появится сторона рекрутера.</span>
    </button>
    <button type="button" class="vis-card" disabled>
      <b>Только для избранных — скоро</b>
      <span>Выбор компаний, которым открыт профиль, появится в следующей версии.</span>
    </button>
  `
}

export function renderProf(state) {
  if (!state.prof || !$('prof-body')) return
  renderBody(state.prof)
  renderWhiteSpots(state.prof)
  renderVisibility(state.prof)
}

/* ---------- действия ---------- */

function message(text, kind = 'error') {
  const box = $('prof-msg')
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

/* Закрыть белое пятно - это действие модуля 2, а не модуля 3: индекс только
   показывает пробел и отправляет туда, где доказательство добавляется. */
async function closeSpot(competencyId, state) {
  const snapshot = state.prof.snapshots.find(item => item.level === ui.level)
  const component = snapshot.components.find(item => item.competency_id === competencyId)
  message('')

  if (component.statement_ids.length) {
    ui.onStrengthen(component.statement_ids[0], 'add_link')
    return
  }

  // Компетенции ещё нет в профиле - заводим её через API модуля 2 под тем
  // именем, которое он понимает, и сразу ведём к добавлению доказательства.
  const result = await mutate('/api/profile/statements', {
    method: 'POST',
    body: JSON.stringify({ skill_name_ru: component.suggested_skill_ru })
  })

  if (!result.ok) {
    message('Не удалось добавить компетенцию в профиль. Попробуйте ещё раз.')
    return
  }

  const created = result.payload.statements.find(
    item => item.skill_name === component.suggested_skill_key
  )
  if (created) ui.onStrengthen(created.id, 'add_link')
}

function onProfClick(event, state) {
  const trigger = event.target.closest('[data-act]')
  if (!trigger) return

  const { act, level, value, mode, competency } = trigger.dataset

  const actions = {
    'pick-role': () => { ui.level = level; renderProf(state) },
    'add-role': async () => {
      const result = await mutateProf('/api/prof/roles', {
        method: 'POST',
        body: JSON.stringify({ level })
      })
      if (!result.ok) {
        message(result.payload?.detail || 'Не удалось добавить роль.')
        return
      }
      // Показываем сразу ту роль, которую только что завели: перерисовать
      // нужно после смены уровня, иначе на экране останется прежняя.
      ui.level = level
      renderProf(ui.getState())
    },
    'drop-role': async () => {
      ui.level = null
      await mutateProf(`/api/prof/roles/${level}`, { method: 'DELETE' })
    },
    filter: () => { ui.filter = value; renderProf(state) },
    'toggle-spots': () => { ui.allSpots = !ui.allSpots; renderProf(state) },
    visibility: () => mutateProf('/api/prof/visibility', {
      method: 'PUT',
      body: JSON.stringify({ mode })
    }),
    'close-spot': () => closeSpot(competency, state)
  }

  const handler = actions[act]
  if (handler) handler()
}

export function initProf({ onStrengthen, getState, root }) {
  ui.onStrengthen = onStrengthen
  ui.getState = getState
  root.addEventListener('click', event => onProfClick(event, getState()))
}

export function resetProf() {
  ui.level = null
  ui.filter = 'all'
  ui.allSpots = false
}
