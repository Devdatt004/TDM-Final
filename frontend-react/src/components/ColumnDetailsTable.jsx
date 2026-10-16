import VerdictBadge from "./VerdictBadge.jsx";
import { ConfidenceText, EvidenceList, ReviewState, SensitivityBadge } from "./SensitivityInfo.jsx";

export default function ColumnDetailsTable({ tableName, columns }) {
  return (
    <section>
      <h2>{tableName ? `Column details — ${tableName}` : "Column details"}</h2>
      <div className="legend">
        <p>
          <strong>Format verdict</strong> — does the column's value format clearly match one specific
          known ID type (SSN, MRN, phone, card number, …) in at least 90% of sampled rows?
          <em> High confidence</em> = yes; <em>Needs review</em> = the format is generic or mixed.
          It describes the <em>format only</em> and does not decide sensitivity or create Human Review items.
        </p>
        <p>
          <strong>Sensitivity</strong> — whether the column holds personal data, from the column name,
          value formats, check-digit tests and name/place detection. <strong>Confidence</strong> is a
          rule-based evidence score (not a probability). Results with some evidence but under 80%
          confidence go to <strong>Human Review</strong>; <em>Unknown</em> means no evidence was found,
          which is not proof that the column is safe.
        </p>
      </div>
      <div className="previewWrap">
        <table className="columnDetails">
          <thead>
            <tr>
              <th>Column</th>
              <th>Pattern Type</th>
              <th>Pattern</th>
              <th>Match %</th>
              <th>Null %</th>
              <th>Distinct</th>
              <th title="Does the value format clearly match a specific known ID type?">Format verdict</th>
              <th>Sensitivity</th>
              <th>Confidence</th>
              <th>Why</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {!columns || columns.length === 0 ? (
              <tr><td colSpan={11}>Run an analysis to see results.</td></tr>
            ) : (
              columns.map((c) => (
                <tr key={c.column_name}>
                  <td>{c.column_name}</td>
                  <td>{c.pattern_type}</td>
                  <td><code>{c.pattern}</code></td>
                  <td>{c.match_percentage}%</td>
                  <td>{c.null_percent}%</td>
                  <td>{c.distinct_count}</td>
                  <td><VerdictBadge verdict={c.verdict} /></td>
                  <td><SensitivityBadge info={c.sensitivity} /></td>
                  <td><ConfidenceText info={c.sensitivity} /></td>
                  <td><EvidenceList info={c.sensitivity} /></td>
                  <td><ReviewState info={c.sensitivity} /></td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
