import { useEffect, useState } from 'react'

/** Fetch helper behind every section. Data and error belong to the deps they were fetched for,
 *  so while a request for new deps is in flight the caller sees null/null and can show a loading state. */
export function useAsync<T>(promise: Promise<T>, deps: unknown[]) {
  const [result, setResult] = useState<{ data: T | null; error: string | null; deps: unknown[] }>({ data: null, error: null, deps: [] })
  useEffect(() => {
    let alive = true
    promise.then(
      (value) => alive && setResult({ data: value, error: null, deps }),
      (e) => alive && setResult({ data: null, error: String(e), deps }),
    )
    return () => {
      alive = false
    }
  }, deps)
  const current = result.deps.length === deps.length && result.deps.every((v, i) => Object.is(v, deps[i]))
  return { data: current ? result.data : null, error: current ? result.error : null }
}
