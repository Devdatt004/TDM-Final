import { recommendMaskingTechnique } from "../maskingRules.js";

export default function MaskingRecommendationTable({ tableName, columns, error }) {
  return (
    <section>
      <h2>{tableName ? `Masking Recommendations — ${tableName}` : "Masking Recommendations"}</h2>
      <p className="subtitle">
        Built from the Schema Catalog + Data Dictionary sensitivity level for the selected table.
        Run Profiling on this table first so a classification exists to base the recommendation on.
      </p>
      <div className="previewWrap">
        <table>
          <thead>
            <tr>
              <th>Column</th>
              <th>Pattern Type</th>
              <th>Sensitivity</th>
              <th>Recommended Technique</th>
            </tr>
          </thead>
          <tbody>
            {error ? (
              <tr><td colSpan={4}>Could not load masking recommendations: {error}</td></tr>
            ) : !columns || columns.length === 0 ? (
              <tr><td colSpan={4}>Select a source and run Profiling to see masking recommendations.</td></tr>
            ) : (
              columns.map((c) => {
                const rec = recommendMaskingTechnique(c.sensitivity_level, c.pattern_type);
                return (
                  <tr key={c.column_name}>
                    <td>{c.column_name}</td>
                    <td>{c.pattern_type ?? "-"}</td>
                    <td>{c.sensitivity_level ? <span className="sensBadge">{c.sensitivity_level}</span> : "-"}</td>
                    <td><span className={`maskPill ${rec.tone}`}>{rec.technique}</span></td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
