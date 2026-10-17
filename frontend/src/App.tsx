import { useEffect, useState } from 'react'

type Health = { status: string }

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    fetch('/api/health')
      .then((response) => response.json() as Promise<Health>)
      .then(setHealth)
      .catch(() => setError(true))
  }, [])

  return (
    <main>
      <h1>Аномалии интенсивности движения</h1>
      <p>
        Сервер:{' '}
        {error ? 'недоступен' : health ? health.status : 'проверяем…'}
      </p>
    </main>
  )
}
