/* Состояние профиля.

   Правило одно: страница никогда не додумывает результат сама. Любой запрос,
   меняющий данные, возвращает профиль целиком, и мы просто кладём его сюда -
   поэтому на экране всегда то же, что в базе, без ручного обновления. */

import { api } from './api.js'

const EMPTY = { statements: [], evidence: [], declines: [] }

let state = EMPTY
const listeners = new Set()

export function getState() {
  return state
}

export function subscribe(listener) {
  listeners.add(listener)
  listener(state)
  return () => listeners.delete(listener)
}

function publish(next) {
  state = next
  for (const listener of listeners) listener(state)
}

export function clearProfile() {
  publish(EMPTY)
}

/* Ответ профиля узнаём по форме: у него всегда есть все три списка. */
function isProfile(payload) {
  return Boolean(payload && payload.statements && payload.evidence && payload.declines)
}

export async function loadProfile() {
  const result = await api('/api/profile')
  if (result.ok && isProfile(result.payload)) publish(result.payload)
  return result
}

/* Обёртка для всех изменяющих запросов: сам запрос, сам разбор ответа,
   сама перерисовка. Вызывающему остаётся только показать ошибку. */
export async function mutate(path, options = {}) {
  const result = await api(path, options)
  if (result.ok && isProfile(result.payload)) publish(result.payload)
  return result
}

export function applyProfile(payload) {
  if (isProfile(payload)) publish(payload)
}

export function statementById(id) {
  return state.statements.find(item => item.id === id) || null
}

export function evidenceById(id) {
  return state.evidence.find(item => item.id === id) || null
}
