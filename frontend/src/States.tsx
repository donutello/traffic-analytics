/** The three states every section renders while waiting: loading, nothing to show, request failed. */

export function Spinner({ label = 'Загрузка данных…' }: { label?: string }) {
  return (
    <div className="state" role="status">
      <span className="spinner" aria-hidden />
      <p>{label}</p>
    </div>
  )
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="state">
      <p>{message}</p>
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const reload = () => window.location.reload()
  return (
    <div className="state state-error" role="alert">
      <p>Не получилось загрузить данные: {message}</p>
      <button onClick={onRetry ?? reload}>Повторить</button>
    </div>
  )
}
