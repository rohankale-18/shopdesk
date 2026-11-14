import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Filters stored in the URL query string. Changing any filter resets to page 1.
 * Returns plain string values ('' = unset).
 */
export function useUrlFilters<K extends string>(keys: readonly K[]) {
  const [params, setParams] = useSearchParams()

  const values = Object.fromEntries(keys.map((k) => [k, params.get(k) ?? ''])) as Record<K, string>
  const page = Math.max(1, Number(params.get('page') ?? 1) || 1)

  const set = useCallback(
    (key: K, value: string) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (value) next.set(key, value)
          else next.delete(key)
          next.delete('page')
          return next
        },
        { replace: true },
      ),
    [setParams],
  )

  const setPage = useCallback(
    (p: number) =>
      setParams((prev) => {
        const next = new URLSearchParams(prev)
        if (p > 1) next.set('page', String(p))
        else next.delete('page')
        return next
      }),
    [setParams],
  )

  return { values, page, set, setPage }
}

/** Debounce a fast-changing value (e.g. a search box) before it hits the API. */
export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}
