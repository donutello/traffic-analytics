/** One token reader for the canvas-drawn parts (ECharts options, Leaflet markers):
 *  colors live only in the CSS tokens of index.css, so both themes drive every visual. */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}
