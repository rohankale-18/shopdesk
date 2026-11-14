import type { ApiErrorBody } from './types'

// Empty base URL = same origin. Vite proxies /api to FastAPI in dev.
// Set VITE_API_URL (e.g. https://api.example.com) for a separate API host.
const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** Field-level messages from a validation_error, keyed by field name. */
  get fieldErrors(): Record<string, string> {
    const fields = this.details.fields as { field: string; message: string }[] | undefined
    return Object.fromEntries((fields ?? []).map((f) => [f.field, f.message]))
  }
}

type Query = Record<string, string | number | boolean | (string | number)[] | null | undefined>

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) value.forEach((v) => params.append(key, String(v)))
    else params.set(key, String(value))
  }
  const qs = params.toString()
  return `${BASE_URL}${path}${qs ? `?${qs}` : ''}`
}

async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown } = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      headers: opts.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'network_error', "Can't reach the API. Is the backend running on port 8000?")
  }

  if (res.status === 204) return undefined as T

  const data = await res.json().catch(() => null)
  if (!res.ok) throw toApiError(res.status, data)
  return data as T
}

function toApiError(status: number, data: unknown): ApiError {
  const err = (data as ApiErrorBody | null)?.error
  return new ApiError(
    status,
    err?.code ?? 'http_error',
    err?.message ?? `Request failed with status ${status}.`,
    err?.details ?? {},
  )
}

/**
 * POST and read the response as Server-Sent Events, calling `onEvent` for each one as it arrives.
 * Errors before the stream starts are thrown as ApiError, like `request`. Pass `signal` to cancel.
 */
async function stream(
  path: string,
  body: unknown,
  onEvent: (event: string, data: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(buildUrl(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if (signal?.aborted) throw e
    throw new ApiError(0, 'network_error', "Can't reach the API. Is the backend running on port 8000?")
  }
  if (!res.ok || !res.body) throw toApiError(res.status, await res.json().catch(() => null))

  // Events are separated by a blank line; each has an "event:" line and a "data:" line (JSON).
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  // Aborting the fetch doesn't always wake up a pending read(), so cancel the reader directly.
  const cancel = () => void reader.cancel().catch(() => {})
  signal?.addEventListener('abort', cancel, { once: true })
  try {
    await readEvents(reader, onEvent)
  } finally {
    signal?.removeEventListener('abort', cancel)
    cancel() // also closes the connection if onEvent threw
  }
  if (signal?.aborted) throw new DOMException('The request was stopped.', 'AbortError')
}

async function readEvents(
  reader: ReadableStreamDefaultReader<string>,
  onEvent: (event: string, data: unknown) => void,
): Promise<void> {
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += value.replaceAll('\r\n', '\n')
    let end: number
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      let event = 'message'
      let data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (data) onEvent(event, JSON.parse(data))
    }
  }
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>('GET', path, { query }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>('POST', path, { body, query }),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, { body }),
  delete: <T>(path: string) => request<T>('DELETE', path),
  stream,
}
