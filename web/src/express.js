/* Экспресс-разбор резюме — целиком в браузере рекрутера (модуль 15).

   ЭТОТ ФАЙЛ НЕ ХОДИТ В СЕТЬ. Ни одного импорта с доступом к сети, ни одного
   fetch. Это не аккуратность, а архитектурная граница: текст чужого резюме не
   должен уходить на сервер PurpJob до того, как человек об этом узнал и
   согласился. Соблазн «быстренько отправить на сервер, там разбор лучше»
   слишком велик, поэтому у файла просто нет такой возможности — и на это есть
   тест, который читает исходник.

   Что здесь считается — грубая, популяционная прикидка, а не персональная
   оценка. У незарегистрированного человека нет и не может быть контрольного
   образца собственного текста, с которым модуль 6 сравнивает своих кандидатов.
   Поэтому и подаётся это как «предварительно, по тексту», и никогда — с той же
   уверенностью, что настоящая Самостоятельность.

   Все пороги — неоткалиброванные величины. Числа ниже иллюстративные. */

/* --- калибруемые константы ---------------------------------------------- */

export const LONG_SENTENCE_WORDS = 22
export const LOW_VARIETY_RATIO = 0.45
export const LOW_FACT_DENSITY = 0.03

/* Обороты, которые в резюме почти ничего не сообщают. Список короткий и
   буквальный: угадывать «машинность» текста тоньше этого честнее не браться. */
export const EMPTY_PHRASES = [
  'коммуникабельн',
  'стрессоустойчив',
  'ответственн',
  'обучаем',
  'нацелен на результат',
  'динамично развивающ',
  'работа в команде',
  'широкий кругозор',
  'высокая мотивация',
  'системный подход',
  'многозадачн'
]

const NUMBER = /\d+(?:[.,]\d+)?/g
const YEAR_RANGE = /(20\d{2})\s*[-–—]\s*(20\d{2}|наст\w*|сейчас|present)/gi
const YEARS_CLAIM = /(\d{1,2})\s*(?:\+\s*)?(?:год|года|лет)/gi

const words = text => (text.match(/[\p{L}\p{N}]+/gu) || [])

/* --- составляющие прикидки ---------------------------------------------- */

function lexicalVariety(list) {
  if (list.length < 20) return 1
  const unique = new Set(list.map(word => word.toLowerCase()))
  return unique.size / list.length
}

function averageSentenceLength(text) {
  const sentences = text.split(/[.!?\n]+/).map(s => s.trim()).filter(Boolean)
  if (!sentences.length) return 0
  return words(text).length / sentences.length
}

export function factDensity(text) {
  const list = words(text)
  if (!list.length) return 0
  const numbers = (text.match(NUMBER) || []).length
  return Math.min(1, numbers / list.length)
}

export function emptyPhraseHits(text) {
  const lower = text.toLowerCase()
  return EMPTY_PHRASES.filter(phrase => lower.includes(phrase))
}

/* Прикидка «похоже на сгенерированный или шаблонный текст».

   Складывается из трёх независимых признаков, и ни один из них сам по себе
   ничего не доказывает: длинные ровные предложения, бедный словарь и обороты,
   которые ничего не сообщают. Именно поэтому результат называется прикидкой и
   показывается с оговоркой. */
export function aiTextLikelihood(text) {
  const list = words(text)
  if (list.length < 30) return { pct: null, reasons: ['Текста слишком мало, чтобы что-то сказать.'] }

  const reasons = []
  let score = 0

  const average = averageSentenceLength(text)
  if (average > LONG_SENTENCE_WORDS) {
    score += 25
    reasons.push(`Средняя длина предложения — ${Math.round(average)} слов, необычно ровная.`)
  }

  const variety = lexicalVariety(list)
  if (variety < LOW_VARIETY_RATIO) {
    score += 25
    reasons.push(`Словарь бедный: ${Math.round(variety * 100)}% слов уникальны.`)
  }

  const empty = emptyPhraseHits(text)
  if (empty.length) {
    score += Math.min(35, empty.length * 12)
    reasons.push(`Оборотов, которые ничего не сообщают: ${empty.length}.`)
  }

  const density = factDensity(text)
  if (density < LOW_FACT_DENSITY) {
    score += 15
    reasons.push('Почти нет чисел: масштаб и результат работы не названы.')
  }

  if (!reasons.length) reasons.push('Явных признаков шаблонности не видно.')
  return { pct: Math.min(100, score), reasons }
}

/* --- логика дат ---------------------------------------------------------- */

/* Те же по смыслу проверки, что делает модуль 6 для своих кандидатов, но по
   сырому тексту вместо структурных данных — и потому заведомо грубее. */
export function dateAnomalies(text) {
  const found = []
  const spans = []

  for (const match of text.matchAll(YEAR_RANGE)) {
    const from = Number(match[1])
    const to = /^\d{4}$/.test(match[2]) ? Number(match[2]) : new Date().getFullYear()
    if (to < from) {
      found.push({
        type: 'date_overlap',
        description_ru: `Период ${match[0]} идёт в обратную сторону.`
      })
    }
    spans.push([from, to])
  }

  spans.sort((a, b) => a[0] - b[0])
  for (let i = 1; i < spans.length; i += 1) {
    if (spans[i][0] < spans[i - 1][1]) {
      found.push({
        type: 'date_overlap',
        description_ru: `Периоды ${spans[i - 1][0]}–${spans[i - 1][1]} и ${spans[i][0]}–${spans[i][1]} пересекаются.`
      })
      break
    }
  }

  const totalYears = spans.reduce((sum, [from, to]) => sum + Math.max(0, to - from), 0)
  for (const match of text.matchAll(YEARS_CLAIM)) {
    const claimed = Number(match[1])
    if (spans.length && claimed > totalYears + 1) {
      found.push({
        type: 'date_overlap',
        description_ru: `Заявлено ${claimed} лет опыта, а перечисленные периоды дают ${totalYears}.`
      })
      break
    }
  }

  return found
}

/* --- итог ---------------------------------------------------------------- */

export function analyse(text) {
  const likelihood = aiTextLikelihood(text)
  return {
    ai_text_likelihood_pct: likelihood.pct,
    ai_reasons: likelihood.reasons,
    logical_anomalies: dateAnomalies(text),
    fact_density_score: Number(factDensity(text).toFixed(3)),
    computed_locally: true
  }
}
