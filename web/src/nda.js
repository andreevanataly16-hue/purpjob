/* Подтверждение под NDA: Слепой свидетель и зеркальная задача (модуль 5).

   Экран ведёт кандидата ровно по одному правилу: сначала он видит, чего у него
   не спросят никогда, и только потом выбирает способ. Оба способа показаны как
   равные, отказаться можно на любом шаге и без объяснений. */

import './nda.css'
import { mutateNda } from './store.js'

const METHOD_ICON = { blind_witness: '🗣', mirror_task: '🧩' }

/* Что открыто и что кандидат уже расставил - данные тут не хранятся. */
const ui = {
  openCaseId: null,
  placed: [],   // [{node_id, order, role_ru}]
  roles: {},
  // Черновик объяснения держим здесь: расстановка узлов перерисовывает блок,
  // и набранный текст иначе пропадал бы на каждом клике.
  explanation: ''
}

const $ = id => document.getElementById(id)
const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
))

export const NDA_SKELETON = `
  <section class="block" id="nda-block">
    <h2>Подтверждение под NDA</h2>
    <p class="sub">
      Закрытый проект — не повод остаться без подтверждения. Ни файла, ни названия
      клиента, ни коммерческих цифр здесь не спрашивают: подтверждается владение
      логикой, а не сам материал.
    </p>
    <div id="nda-body"></div>
    <p class="msg" id="nda-msg"></p>
  </section>
`

/* ---------- дисклеймер ---------- */

function disclaimerCard(disclaimer, caseId) {
  return `
    <div class="disclaimer-card">
      <p>${escape(disclaimer.intro_ru)}</p>
      <div class="disclaimer-lists">
        <div class="ok">
          <h4>Чем можно поделиться</h4>
          <ul>${disclaimer.allowed_ru.map(item => `<li>${escape(item)}</li>`).join('')}</ul>
        </div>
        <div class="never">
          <h4>Что мы не спрашиваем никогда</h4>
          <ul>${disclaimer.never_asked_ru.map(item => `<li>${escape(item)}</li>`).join('')}</ul>
        </div>
      </div>
      <p class="legal-note">${escape(disclaimer.legal_review_note_ru)}</p>
      <button type="button" class="action" data-act="ack" data-case="${caseId}">
        Понятно, продолжить
      </button>
    </div>`
}

/* ---------- выбор способа ---------- */

function methodCards(item) {
  return `
    <div class="methods">
      ${item.methods.map(method => `
        <button type="button" class="method-card" data-act="method"
          data-case="${item.id}" data-method="${method.value}"
          aria-pressed="${item.chosen_method === method.value}"
          ${method.available ? '' : 'disabled'}>
          <b>${METHOD_ICON[method.value] || ''} ${escape(method.label_ru)}</b>
          <span>${escape(method.unavailable_reason_ru || method.description_ru)}</span>
          ${method.value === item.suggested_method && method.available
            ? '<span class="suggested">можно начать с этого</span>' : ''}
        </button>`).join('')}
    </div>
    <div class="nda-actions">
      <span class="spacer"></span>
      <button type="button" class="link-btn" data-act="decline-all" data-case="${item.id}">
        Не подходит ни один способ
      </button>
    </div>`
}

/* ---------- Слепой свидетель ---------- */

function blindWitness(item) {
  const questions = item.blind_witness.map((question, index) => {
    const openFollowUp = question.follow_up_ru && question.follow_up_answer === null
    const waiting = question.answer === null || openFollowUp

    return `
      <div class="bw-question">
        <p class="q-why">${escape(openFollowUp ? question.follow_up_reason_ru : question.reason_ru)}</p>
        <p class="q-text">${escape(openFollowUp ? question.follow_up_ru : question.prompt_ru)}</p>
        ${question.answer !== null ? `<p class="bw-answered">${escape(question.answer)}</p>` : ''}
        ${question.follow_up_answer ? `<p class="bw-answered">${escape(question.follow_up_answer)}</p>` : ''}
        ${waiting ? `
          <textarea class="probe-input" id="bw-input-${index}"
            placeholder="Структура и логика: узлы, границы, критические точки"></textarea>
          <p class="probe-hint">Вставка отключена — нам важны ваши формулировки.</p>
          <div class="nda-actions">
            <button type="button" class="action" data-act="bw-answer"
              data-question="${question.id}" data-input="bw-input-${index}">Ответить</button>
          </div>` : ''}
      </div>`
  }).join('')

  return questions || '<div class="empty">Вопросы готовятся.</div>'
}

/* ---------- зеркальная задача ---------- */

function mirrorTask(item) {
  const mirror = item.mirror_task
  if (!mirror) return '<div class="empty">Сценарий готовится.</div>'

  const placed = ui.openCaseId === item.id ? ui.placed : []
  const placedIds = new Set(placed.map(node => node.node_id))
  const byId = Object.fromEntries(mirror.scenario.nodes.map(node => [node.id, node]))

  if (mirror.status === 'submitted' && !mirror.follow_up_ru) {
    return `
      <p class="mirror-framing">${escape(mirror.scenario.framing_ru)}</p>
      <p class="bw-answered">${escape(mirror.logic_explanation || '')}</p>`
  }

  if (mirror.follow_up_ru && mirror.follow_up_answer === null) {
    return `
      <p class="q-why">${escape(mirror.follow_up_reason_ru)}</p>
      <p class="q-text">${escape(mirror.follow_up_ru)}</p>
      <textarea class="probe-input" id="mirror-follow-up"></textarea>
      <div class="nda-actions">
        <button type="button" class="action" data-act="mirror-follow-up" data-case="${item.id}">
          Ответить
        </button>
      </div>`
  }

  return `
    <p class="mirror-framing">${escape(mirror.scenario.framing_ru)}</p>
    <p class="mirror-instructions">${escape(mirror.scenario.instructions_ru)}</p>

    <div class="nodes">
      ${mirror.scenario.nodes.map(node => `
        <button type="button" class="node-chip" data-act="place" data-case="${item.id}"
          data-node="${node.id}" ${placedIds.has(node.id) ? 'disabled' : ''}>
          ${escape(node.label_ru)}
        </button>`).join('')}
    </div>

    ${placed.length ? `
      <div class="placed">
        ${placed.map(node => `
          <div class="placed-row">
            <span class="order">${node.order}</span>
            <span class="label">${escape(byId[node.node_id]?.label_ru || node.node_id)}</span>
            <input type="text" data-act="role" data-node="${node.node_id}"
              value="${escape(ui.roles[node.node_id] || '')}" placeholder="Роль этого узла в вашей схеме">
          </div>`).join('')}
      </div>` : '<p class="sub">Нажимайте узлы в том порядке, в каком через них идёт работа.</p>'}

    <textarea class="probe-input" id="mirror-explanation"
      placeholder="Почему узлы стоят именно так и что сломается, если поменять их местами">${escape(ui.explanation)}</textarea>
    <p class="probe-hint">Вставка отключена. Одной схемы без объяснения недостаточно.</p>

    <div class="nda-actions">
      <button type="button" class="action" data-act="mirror-submit" data-case="${item.id}">
        Отправить решение
      </button>
      <button type="button" class="ghost" data-act="reset-nodes">Собрать схему заново</button>
    </div>`
}

/* ---------- случай целиком ---------- */

function caseCard(item, disclaimer, active) {
  let body = ''

  if (!item.disclaimer_acknowledged) {
    body = disclaimerCard(disclaimer, item.id)
  } else if (item.status === 'declined_all') {
    body = `
      <div class="empty">
        Вы отказались от обоих способов — статус компетенции от этого не изменился.
        Вернуться можно в любой момент.
      </div>
      <div class="nda-actions">
        <button type="button" class="ghost" data-act="revoke-decline" data-case="${item.id}">
          Всё-таки попробовать
        </button>
      </div>`
  } else if (item.status === 'confirmed') {
    body = `<div class="empty">Компетенция подтверждена — материалы остались закрытыми.</div>`
  } else if (!item.chosen_method) {
    body = methodCards(item)
  } else {
    body = (item.chosen_method === 'blind_witness' ? blindWitness(item) : mirrorTask(item)) + `
      <div class="nda-actions">
        <span class="spacer"></span>
        <button type="button" class="link-btn" data-act="switch" data-case="${item.id}"
          data-method="${item.chosen_method === 'blind_witness' ? 'mirror_task' : 'blind_witness'}">
          Выбрать другой способ
        </button>
        <button type="button" class="link-btn nda" data-act="decline-all" data-case="${item.id}">
          Не подходит ни один
        </button>
      </div>`
  }

  return `
    <article class="nda-case ${active ? 'active' : ''}">
      <div class="nda-head">
        <span class="name">${escape(item.competency_name_ru)}</span>
        <span class="chip grey">${escape(item.status_ru)}</span>
        ${item.origin === 'probe' ? '<span class="chip nda">из вопроса Contextual Probe</span>' : ''}
      </div>
      ${body}
    </article>`
}

export function renderNda(state) {
  if (!state.nda || !$('nda-body')) return

  const box = $('nda-body')
  const { cases, disclaimer, active_case_id: activeId } = state.nda

  if (!cases.length) {
    box.innerHTML = `
      <div class="empty">
        Пока таких случаев нет. Если вопрос задевает NDA — нажмите «Это касается NDA»
        в Contextual Probe, или откройте этот путь прямо из белого пятна.
      </div>`
    return
  }

  box.innerHTML = cases
    .map(item => caseCard(item, disclaimer, item.id === activeId))
    .join('')
}

/* ---------- действия ---------- */

function message(text, kind = 'error') {
  const box = $('nda-msg')
  box.textContent = text
  box.className = `msg ${text ? kind : ''}`
}

function resetNodes() {
  ui.placed = []
  ui.roles = {}
  ui.explanation = ''
}

async function submitMirror(caseId, state) {
  const explanation = $('mirror-explanation').value.trim()
  message('')

  if (!ui.placed.length) {
    message('Сначала расставьте узлы — хотя бы те, что считаете главными.')
    return
  }
  if (explanation.length < 20) {
    message('Одной схемы мало: объясните логику своими словами.')
    return
  }

  const result = await mutateNda(`/api/nda/cases/${caseId}/mirror-task`, {
    method: 'POST',
    body: JSON.stringify({
      node_arrangement: ui.placed.map(node => ({ ...node, role_ru: ui.roles[node.node_id] || '' })),
      logic_explanation: explanation
    })
  })

  if (!result.ok) {
    message(result.payload?.detail || 'Не удалось отправить решение.')
    return
  }
  resetNodes()
}

async function onNdaClick(event, state) {
  const trigger = event.target.closest('#nda-block [data-act], #white-spots [data-act="nda-spot"]')
  if (!trigger) return

  const { act, case: caseId, method, node, question, input, competency } = trigger.dataset

  const actions = {
    'nda-spot': () => openFor(competency),
    ack: () => mutateNda(`/api/nda/cases/${caseId}/acknowledge`, { method: 'POST' }),
    method: async () => {
      ui.openCaseId = caseId
      resetNodes()
      const result = await mutateNda(`/api/nda/cases/${caseId}/method`, {
        method: 'POST',
        body: JSON.stringify({ method })
      })
      if (!result.ok) message(result.payload?.detail || 'Не удалось выбрать способ.')
    },
    switch: async () => {
      ui.openCaseId = caseId
      resetNodes()
      await mutateNda(`/api/nda/cases/${caseId}/method`, {
        method: 'POST',
        body: JSON.stringify({ method })
      })
    },
    'decline-all': async () => {
      await mutateNda(`/api/nda/cases/${caseId}/decline`, {
        method: 'POST',
        body: JSON.stringify({ reason: null })
      })
      message('Хорошо. Статус компетенции не изменился — вернуться можно когда угодно.', 'ok')
    },
    'revoke-decline': () => mutateNda(`/api/nda/cases/${caseId}/decline`, { method: 'DELETE' }),
    'bw-answer': async () => {
      const text = $(input).value.trim()
      if (text.length < 15) {
        message('Опишите структуру чуть подробнее — пары фраз хватит.')
        return
      }
      message('')
      await mutateNda(`/api/nda/questions/${question}/answer`, {
        method: 'POST',
        body: JSON.stringify({ text })
      })
    },
    place: () => {
      ui.openCaseId = caseId
      ui.placed = [...ui.placed, { node_id: node, order: ui.placed.length + 1, role_ru: '' }]
      renderNda(state)
    },
    'reset-nodes': () => { resetNodes(); renderNda(state) },
    'mirror-submit': () => submitMirror(caseId, state),
    'mirror-follow-up': async () => {
      const text = $('mirror-follow-up').value.trim()
      if (text.length < 10) {
        message('Пара фраз про логику — и закончим.')
        return
      }
      const current = state.nda.cases.find(item => item.id === caseId)
      await mutateNda(`/api/nda/cases/${caseId}/mirror-task`, {
        method: 'POST',
        body: JSON.stringify({
          node_arrangement: current.mirror_task.node_arrangement,
          logic_explanation: text
        })
      })
    }
  }

  const handler = actions[act]
  if (handler) await handler()
}

function onNdaInput(event) {
  const role = event.target.closest('#nda-block [data-act="role"]')
  if (role) {
    ui.roles[role.dataset.node] = role.value
    return
  }
  if (event.target.id === 'mirror-explanation') ui.explanation = event.target.value
}

/* Открыть путь NDA по конкретной компетенции - вход из белых пятен. */
export async function openFor(competencyId) {
  message('')
  const result = await mutateNda('/api/nda/cases', {
    method: 'POST',
    body: JSON.stringify({ competency_id: competencyId })
  })

  if (!result.ok) {
    message(result.payload?.detail || 'Не удалось открыть путь подтверждения.')
    return
  }
  $('nda-block').scrollIntoView({ behavior: 'smooth', block: 'start' })
}

export function initNda({ getState, root }) {
  root.addEventListener('click', event => onNdaClick(event, getState()))
  root.addEventListener('input', onNdaInput)
}

export function resetNda() {
  ui.openCaseId = null
  resetNodes()
}
