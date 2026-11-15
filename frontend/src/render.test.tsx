// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { RoadBar } from './Comparison'
import { EmptyState, ErrorState, Spinner } from './States'
import Toolbar from './Toolbar'
import { useUrlState } from './urlState'
import type { Period, Road } from './types'

afterEach(cleanup)

describe('States', () => {
  it('announces loading and errors, and offers a retry', () => {
    render(
      <>
        <Spinner label="Загрузка сравнения…" />
        <EmptyState message="нет данных" />
        <ErrorState message="boom" onRetry={() => {}} />
      </>,
    )
    expect(screen.getByRole('status').textContent).toContain('Загрузка сравнения…')
    expect(screen.getByText('нет данных')).toBeTruthy()
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain('boom')
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeTruthy()
  })
})

describe('RoadBar', () => {
  const totals = { ours: 12, corporate: 6, both: 4, only_ours: 8, only_corporate: 2 }

  it('sizes each segment proportional to its count', () => {
    const { container } = render(<RoadBar totals={totals} />)
    const segs = Array.from(container.querySelectorAll<HTMLElement>('.cmp-seg')).map((s) => s.style.flexGrow)
    expect(segs).toEqual(['4', '8', '2'])
  })
  it('names the counts in its accessible label, with agreed Russian', () => {
    render(<RoadBar totals={totals} />)
    expect(screen.getByRole('img').getAttribute('aria-label')).toBe('совпало 4 пары, только наш алгоритм 8, только корпоративная система 2')
  })
  it('says so honestly when the road has no findings at all', () => {
    render(<RoadBar totals={{ ours: 0, corporate: 0, both: 0, only_ours: 0, only_corporate: 0 }} />)
    expect(screen.getByText('за период нет ни одной находки')).toBeTruthy()
  })
})

const ROADS: Road[] = [
  { code: 'a133', name: 'А-133', sensors: 2 },
  { code: 'a134', name: 'А-134', sensors: 1 },
]
const PERIOD: Period = { from: '2023-01-01', to: '2026-10-01' }

function ToolbarInUrl() {
  const [state, patch] = useUrlState()
  return <Toolbar state={state} roads={ROADS} road={state.road || 'a133'} sensor={null} features={[]} typeLabels={{}} period={PERIOD} onPatch={patch} />
}

describe('Toolbar writes the URL state (issue #14 behavior, regression-tested here)', () => {
  beforeEach(() => window.history.replaceState(null, '', '/?section=compare'))

  it('offers «все дороги» in the comparison section', () => {
    render(<ToolbarInUrl />)
    expect((screen.getByLabelText('Дорога') as HTMLSelectElement).value).toBe('*')
  })

  it('writes the picked road into ?road=', () => {
    render(<ToolbarInUrl />)
    fireEvent.change(screen.getByLabelText('Дорога'), { target: { value: 'a134' } })
    expect(window.location.search).toContain('road=a134')
  })

  it('writes the picked source into ?source=', () => {
    render(<ToolbarInUrl />)
    fireEvent.click(screen.getByRole('button', { name: 'корпоративная система' }))
    expect(window.location.search).toContain('source=corporate')
  })
})
