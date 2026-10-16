import VerdictBadge from "./VerdictBadge.jsx";
import { sensitivityTone } from "../sensitivity.js";
import { ReviewState, SensitivityBadge } from "./SensitivityInfo.jsx";

export default function SchemaCatalogTable({ tableName, columns, error }) {
  return (
    <section>
      <h2>{tableName ? `Schema Catalog & Data Dictionary — ${tableName}` : "Schema Catalog & Data Dictionary"}</h2>
      <p className="subtitle">
        Native column types (Schema Catalog) joined with each column's classification and its
        business meaning (Data Dictionary) — run Profiling to populate this for a table.
        <em> Dictionary default</em> is the generic label for the column's format; <em>Detected
        sensitivity</em> is what profiling and human review concluded for this specific column.
      </p>

      {error ? (
        <div className="infoBanner error">
          <span className="infoBannerIcon">{"\u26A0"}</span>
          <div>
            <strong>Could not load schema catalog</strong>
            <p>{error}</p>
          </div>
        </div>
      ) : !columns || columns.length === 0 ? (
        <div className="infoBanner">
          <span className="infoBannerIcon">{"\u{1F4CB}"}</span>
          <div>
            <strong>No data yet for this table</strong>
            <p>Run Profiling (Profiling tab) to populate the schema catalog here.</p>
          </div>
        </div>
      ) : (
        <div className="previewWrap">
          <table>
            <thead>
              <tr>
                <th>Column</th>
                <th>Native Type</th>
                <th>Pattern Type</th>
                <th>Business Name</th>
                <th>Dictionary default</th>
                <th>Detected sensitivity</th>
                <th>Review</th>
                <th>Format verdict</th>
              </tr>
            </thead>
            <tbody>
              {columns.map((c) => (
                <tr key={c.column_name}>
                  <td>{c.column_name}</td>
                  <td><code>{c.data_type}</code></td>
                  <td>{c.pattern_type ?? "-"}</td>
                  <td>{c.business_name ?? "-"}</td>
                  <td>
                    {c.sensitivity_level ? (
                      <span className={`sensBadge ${sensitivityTone(c.sensitivity_level)}`}>
                        {c.sensitivity_level}
                      </span>
                    ) : "-"}
                  </td>
                  <td><SensitivityBadge info={c.sensitivity} /></td>
                  <td><ReviewState info={c.sensitivity} /></td>
                  <td><VerdictBadge verdict={c.verdict} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
