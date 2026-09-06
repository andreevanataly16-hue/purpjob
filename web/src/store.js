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
let nda = null
let trust = null
let disputes = null
let moderation = null
let growth = null
let vacancies = null
let retention = null
const listeners = new Set()

function snapshot() {
  return {
    ...profile, prof, probe, nda, trust, disputes, moderation, growth, vacancies, retention
  }
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
  nda = null
  trust = null
  disputes = null
  moderation = null
  growth = null
  vacancies = null
  retention = null
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

function isNda(payload) {
  return Boolean(payload && payload.disclaimer && Array.isArray(payload.cases))
}

async function refreshProbe() {
  const result = await api('/api/probe')
  if (result.ok && isProbe(result.payload)) probe = result.payload
}

async function refreshNda() {
  const result = await api('/api/nda')
  if (result.ok && isNda(result.payload)) nda = result.payload
}

function isTrust(payload) {
  return Boolean(payload && 'overall_score' in payload && payload.components)
}

async function refreshTrust() {
  const result = await api('/api/trust')
  if (result.ok && isTrust(result.payload)) trust = result.payload
}

function isDisputes(payload) {
  return Boolean(payload && payload.dispute_label_ru && Array.isArray(payload.cases))
}

function isQueue(payload) {
  return Boolean(payload && payload.not_production_safe_ru && Array.isArray(payload.cases))
}

/* Споры и очередь модератора: модуль 7 ничего не считает сам, но правка
   модератора меняет и индекс, и Trust - поэтому они всегда перечитываются
   вместе с остальным, а не живут отдельной жизнью. */
async function refreshDisputes() {
  const result = await api('/api/disputes')
  if (result.ok && isDisputes(result.payload)) disputes = result.payload
}

async function refreshModeration() {
  if (!stages.moderator) return
  const result = await api('/api/moderation/queue')
  if (result.ok && isQueue(result.payload)) moderation = result.payload
}

function isVacancies(payload) {
  return Boolean(payload && payload.note_ru && Array.isArray(payload.vacancies))
}

/* Лента пересчитывается вместе со всем остальным: совпадение - проекция
   PROF.индекса, и после закрытого пробела оно обязано измениться само. */
/* Какие этапы продукта включены. Ставится один раз при запуске экрана из
   ответа сервера: без этого выключенный модуль давал бы 404 на каждой
   загрузке страницы — не поломка, но ровно тот мусор в консоли, который через
   месяц принимают за настоящую ошибку. */
const stages = { vacancies: true, recruiter: true, moderator: true }

export function setStages(value) {
  Object.assign(stages, value)
}

async function refreshVacancies() {
  if (!stages.vacancies) return
  const result = await api('/api/vacancies')
  if (result.ok && isVacancies(result.payload)) vacancies = result.payload
}

function isRetention(payload) {
  return Boolean(payload && payload.note_ru && Array.isArray(payload.triggers))
}

async function refreshRetention() {
  if (!stages.vacancies) return
  const result = await api('/api/retention')
  if (result.ok && isRetention(result.payload)) retention = result.payload
}

/* Повод «появилась вакансия» - единственное, что может отметиться
   сработавшим, поэтому после него перечитывается вся лента и история. */
export async function mutateRetention(path, options = {}) {
  const result = await api(path, options)
  if (result.ok && isRetention(result.payload)) {
    retention = result.payload
    await Promise.all([refreshVacancies(), refreshGrowth()])
    publish()
  }
  return result
}

function isGrowth(payload) {
  return Boolean(payload && payload.note_ru && Array.isArray(payload.periods))
}

/* История роста читается после всего остального: она наблюдает за тем, что
   уже посчитали другие модули, и должна видеть их последнее состояние. */
async function refreshGrowth() {
  const result = await api('/api/growth')
  if (result.ok && isGrowth(result.payload)) growth = result.payload
}

async function refreshProf() {
  const result = await api('/api/prof')
  if (result.ok && isProf(result.payload)) prof = result.payload
}

export async function loadProfile() {
  const [profileResult] = await Promise.all([
    api('/api/profile'),
    refreshProf(),
    refreshProbe(),
    refreshNda(),
    refreshTrust(),
    refreshDisputes(),
    refreshModeration()
  ])
  await Promise.all([refreshGrowth(), refreshVacancies(), refreshRetention()])
  if (profileResult.ok && isProfile(profileResult.payload)) profile = profileResult.payload
  publish()
  return profileResult
}

/* Изменения в модуле 2: ответ - профиль, индекс перечитываем следом. */
export async function mutate(path, options = {}) {
  const result = await api(path, options)
  if (result.ok && isProfile(result.payload)) {
    profile = result.payload
    await Promise.all([
      refreshProf(), refreshProbe(), refreshNda(), refreshTrust(),
      refreshDisputes(), refreshModeration()
    ])
    await Promise.all([refreshGrowth(), refreshVacancies(), refreshRetention()])
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
    await Promise.all([
      refreshProf(), refreshNda(), refreshTrust(), refreshDisputes(), refreshModeration()
    ])
    await Promise.all([refreshGrowth(), refreshVacancies(), refreshRetention()])
    publish()
  }
  return result
}

/* Подтверждение под NDA меняет доказательства и индекс - перечитываем всё. */
export async function mutateNda(path, options = {}) {
  const result = await api(path, options)
  if (result.ok && isNda(result.payload)) {
    nda = result.payload
    const profileResult = await api('/api/profile')
    if (profileResult.ok && isProfile(profileResult.payload)) profile = profileResult.payload
    await Promise.all([
      refreshProf(), refreshProbe(), refreshTrust(), refreshDisputes(), refreshModeration()
    ])
    await Promise.all([refreshGrowth(), refreshVacancies(), refreshRetention()])
    publish()
  }
  return result
}

/* Разбор нестыковки и ответ про источник меняют профиль - перечитываем всё. */
export async function mutateTrust(path, options = {}) {
  const result = await api(path, options)
  if (result.ok && isTrust(result.payload)) {
    trust = result.payload
    const profileResult = await api('/api/profile')
    if (profileResult.ok && isProfile(profileResult.payload)) profile = profileResult.payload
    await Promise.all([
      refreshProf(), refreshProbe(), refreshNda(), refreshDisputes(), refreshModeration()
    ])
    await Promise.all([refreshGrowth(), refreshVacancies(), refreshRetention()])
    publish()
  }
  return result
}

/* Спор кандидата: ответ - список споров. Балл при этом не меняется, но точка
   входа рядом с выводом должна сразу показать, что спор открыт. */
export async function mutateDisputes(path, options = {}) {
  const result = await api(path, options)
  if (result.ok && isDisputes(result.payload)) {
    disputes = result.payload
    await refreshModeration()
    publish()
  }
  return result
}

/* Решение модератора: единственное, что вообще может изменить балл помимо
   расчёта, - поэтому перечитывается всё. */
export async function mutateModeration(path, options = {}) {
  const result = await api(path, options)
  if (result.ok && isQueue(result.payload)) {
    moderation = result.payload
    await Promise.all([refreshProf(), refreshTrust(), refreshProbe(), refreshDisputes()])
    await Promise.all([refreshGrowth(), refreshVacancies(), refreshRetention()])
    publish()
  }
  return result
}

/* Актуализация компетенции меняет индекс - перечитываем его следом. */
export async function mutateGrowth(path, options = {}) {
  const result = await api(path, options)
  if (result.ok && isGrowth(result.payload)) {
    growth = result.payload
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
    await Promise.all([refreshGrowth(), refreshVacancies(), refreshRetention()])
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
