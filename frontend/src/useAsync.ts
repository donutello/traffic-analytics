import { useEffect, useState } from 'react'

export function useAsync<T>(promise: Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    promise.then(
      (value) => alive && setData(value),
      (e) => alive && setError(String(e)),
    )
    return () => {
      alive = false
    }
  }, deps)
  return { data, error }
}
