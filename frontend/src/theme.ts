/** Tiny theme switcher: the system setting by default, a manual choice stored in localStorage. */

export type Theme = 'light' | 'dark'

export const THEME_KEY = 'theme'

export function initialTheme(): Theme {
  const saved = localStorage.getItem(THEME_KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
}
