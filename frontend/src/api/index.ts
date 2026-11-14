/** The single place the UI talks to the data: the FastAPI backend (`backend/`).
 *
 * The endpoints are those of issues #5 (series) and #6 (meta, sensors, anomalies),
 * served under /api and filtered by the query strings built below; in development
 * Vite forwards /api to the backend (API_URL), so the browser sees one address.
 * The prototypes in public/mock stay for offline work; the responses you get here
 * have exactly their shapes.
 */

export const urls = {
  meta: () => '/api/meta',
  sensors: (road: string, from: string, to: string) => `/api/sensors?road=${road}&from=${from}&to=${to}`,
  series: (sensor: string, from: string, to: string, granularity: string) => `/api/series?sensor=${sensor}&from=${from}&to=${to}&granularity=${granularity}`,
  anomalies: (road: string, from: string, to: string) => `/api/anomalies?road=${road}&from=${from}&to=${to}`,
  anomaly: (id: string) => `/api/anomalies/${id}`,
}

const cache = new Map<string, Promise<unknown>>()

export function get<T>(url: string): Promise<T> {
  let pending = cache.get(url)
  if (!pending) {
    pending = fetch(url).then((r) => {
      if (!r.ok) throw new Error(`${url}: ${r.status}`)
      return r.json() as Promise<T>
    })
    cache.set(url, pending)
  }
  return pending as Promise<T>
}
