import { sensitivityTone } from "../sensitivity.js";

export default function DataDictionaryTable({ entries, error }) {
  return (
    <section>
      <h2>Data Dictionary — Business Glossary</h2>
      <p className="subtitle">
        One row per pattern type the Pattern Analyzer can produce, with its business-friendly name,
        plain description, and default sensitivity level — the shared reference every other feature
        (Schema Catalog, Query Agent, Synthetic Data Generation, Masking) reuses instead of redefining.
      </p>

      {error ? (
        <div className="infoBanner error">
          <span className="infoBannerIcon">{"\u26A0"}</span>
          <div>
            <strong>Could not load data dictionary</strong>
            <p>{error}</p>
          </div>
        </div>
      ) : !entries || entries.length === 0 ? (
        <div className="infoBanner">
          <span className="infoBannerIcon">{"\u23F3"}</span>
          <div>
            <strong>Loading data dictionary…</strong>
          </div>
        </div>
      ) : (
        <div className="previewWrap">
          <table>
            <thead>
              <tr>
                <th>Pattern Type</th>
                <th>Business Name</th>
                <th>Description</th>
                <th>Sensitivity</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.pattern_type}>
                  <td><code>{e.pattern_type}</code></td>
                  <td>{e.business_name}</td>
                  <td>{e.description}</td>
                  <td>
                    <span className={`sensBadge ${sensitivityTone(e.sensitivity_level)}`}>
                      {e.sensitivity_level}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
