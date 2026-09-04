/* Состояние экрана кандидата: профиль (модуль 2) и PROF.индекс (модуль 3).

   Правило одно: страница никогда не додумывает результат сама. Любой запрос,
   меняющий данные, возвращает профиль целиком, и мы просто кладём его сюда -
   поэтому на экране всегда то же, что в базе, без ручного обновления.

   Индекс на сервере не хранится, а считается на каждый запрос, поэтому после
   любого изменения в модуле 2 он перечитывается: иначе радар и белые пятна
   отстали бы от только что добавленного доказательства. */

import { api } from './api.js'

const EMPTY = { statements: [], evidence: [], declines: [] }

let profile = EMPTY
let prof = null
let probe = null
const listeners = new Set()

function snapshot() {
  return { ...profile, prof, probe }
}

export function getState() {
  return snapshot()
}

export function subscribe(listener) {
  listeners.add(listener)
  listener(snapshot())
  return () => listeners.delete(listener)
}

function publish() {
  const current = snapshot()
  for (const listener of listeners) listener(current)
}

export function clearProfile() {
  profile = EMPTY
  prof = null
  probe = null
  publish()
}

/* Ответ профиля узнаём по форме: у него всегда есть все три списка. */
function isProfile(payload) {
  return Boolean(payload && payload.statements && payload.evidence && payload.declines)
}

function isProf(payload) {
  return Boolean(payload && payload.snapshots && payload.visibility)
}

function isProbe(payload) {
  return Boolean(payload && 'available' in payload && 'feedback_reasons' in payload)
}

async function refreshProbe() {
  const result = await api('/api/probe')
  if (result.ok && isProbe(result.payload)) probe = result.payload
}

async function refreshProf() {
  const result = await api('/api/prof')
  if (result.ok && isProf(result.payload)) prof = result.payload
}

export async function loadProfile() {
  const [profileResult] = await Promise.all([
    api('/api/profile'),
    refreshProf(),
    refreshProbe()
  ])
  if (profileResult.ok && isProfile(profileResult.payload)) profile = profileResult.payload
  publish()
  return profileResult
}

/* Изменения в модуле 2: ответ - профиль, индекс перечитываем следом. */
export async function mutate(path, options = {}) {
  const result = await api(path, options)
  if (result.ok && isProfile(result.payload)) {
    profile = result.payload
    await Promise.all([refreshProf(), refreshProbe()])
    publish()
  }
  return result
}

/* Вопрос Contextual Probe: ответ меняет и доказательства, и индекс, поэтому
   после него перечитываем весь профиль - белые пятна должны сойтись. */
export async function mutateProbe(path, options = {}) {
  const result = await api(path, options)
  if (result.ok && isProbe(result.payload)) {
    probe = result.payload
    const profileResult = await api('/api/profile')
    if (profileResult.ok && isProfile(profileResult.payload)) profile = profileResult.payload
    await refreshProf()
    publish()
  }
  return result
}

/* Изменения в модуле 3: ответ - уже сам индекс, профиль трогать незачем. */
export async function mutateProf(path, options = {}) {
  const result = await api(path, options)
  if (result.ok && isProf(result.payload)) {
    prof = result.payload
    publish()
  }
  return result
}

/* Загрузка файла отвечает профилем в обход mutate - индекс всё равно обновляем. */
export async function applyProfile(payload) {
  if (!isProfile(payload)) return
  profile = payload
  await Promise.all([refreshProf(), refreshProbe()])
  publish()
}
