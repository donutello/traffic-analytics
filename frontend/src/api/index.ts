/** The single place the UI talks to the data.
 *
 * Every URL and response shape mirrors the API of issues #5 (series) and #6 (sensors,
 * anomalies) with the same names and parameters, but served as static files from
 * public/mock (the same names as the real endpoints, only under /mock and without
 * query strings: static files cannot filter). When the FastAPI endpoints exist,
 * swapping means changing these builders to /api/... and adding the query strings
 * back; nothing else has to change.
 *
 * The static files ignore the query parameters. They exist to document which
 * filters the real endpoint will apply; the example data covers one road and one
 * period, so all data shown is already inside every file.
 */

export const urls = {
  meta: () => '/mock/meta.json',
  sensors: (road: string, from: string, to: string) => `/mock/sensors.geojson?road=${road}&from=${from}&to=${to}`,
  series: (sensor: string, from: string, to: string, granularity: string) => `/mock/series/${sensor}.${granularity}.json?from=${from}&to=${to}`,
  anomalies: (sensor: string, from: string, to: string) => `/mock/anomalies/${sensor}.json?from=${from}&to=${to}`,
  anomaly: (id: string) => `/mock/anomalies/${id.slice(0, id.indexOf('-'))}/${id}.json`,
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
