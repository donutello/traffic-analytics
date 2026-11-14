/** What a section says before it is built, so the layout never pretends to be finished. */

export default function Placeholder({ title, text, issue }: { title: string; text: string; issue: number }) {
  return (
    <section className="placeholder">
      <div className="card">
        <h3>{title}</h3>
        <span className="wip">в разработке</span>
        <p>{text}</p>
        <p className="muted">
          Раздел появится в <a href={`https://github.com/donutello/traffic-analytics/issues/${issue}`}>issue #{issue}</a>.
        </p>
      </div>
    </section>
  )
}
