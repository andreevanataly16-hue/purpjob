/* Один способ ходить в API на всё приложение. */

export async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...options
  })

  let payload = null
  try {
    payload = response.status === 204 ? null : await response.json()
  } catch {
    payload = null
  }

  return { ok: response.ok, status: response.status, payload }
}

/* Загрузка файла. Content-Type здесь не ставим намеренно: браузер сам
   добавит его вместе с boundary, а свой заголовок этот boundary затрёт. */
export async function apiUpload(path, formData) {
  const response = await fetch(path, {
    method: 'POST',
    credentials: 'same-origin',
    body: formData
  })

  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  return { ok: response.ok, status: response.status, payload }
}

/* Ошибка от FastAPI бывает строкой, а бывает списком проверок. */
export function errorText(payload, fallback) {
  const detail = payload?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return fallback
  return fallback
}
