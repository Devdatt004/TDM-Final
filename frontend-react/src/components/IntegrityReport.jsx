import { useState } from "react";
import { api } from "../api.js";

const STATUS_BADGE = { pass: "high", fail: "fail", warn: "review", info: "running" };

export default function IntegrityReport({ report }) {
  const [previewTable, setPreviewTable] = useState(report.tables[0] ? report.tables[0].name : "");
  const active = report.tables.find((t) => t.name === previewTable) || report.tables[0];

  return (
    <section>
      <h2>Validation report</h2>

      <div className="scoreRow">
        <div className={`scoreValue ${report.passed ? "ok" : "bad"}`}>{report.score}%</div>
        <div>
          <div>
            <span className={`badge ${report.passed ? "high" : "fail"}`}>
              {report.passed ? "Relationships validated - published" : "Validation failed - nothing published"}
            </span>
          </div>
          <p className="cardHint">
            {report.valid_references} of {report.total_references} foreign-key references point to an
            existing parent. Generated in order: {report.order.join(" \u2192 ")}.
            {report.auto_included.length > 0 &&
              ` Added automatically as parents: ${report.auto_included.join(", ")}.`}
          </p>
        </div>
      </div>

      {report.warnings.map((w) => (
        <div className="infoBanner" key={w}>
          <span className="infoBannerIcon">&#9432;</span>
          <div><p>{w}</p></div>
        </div>
      ))}

      <h3>Checks</h3>
      <div className="previewWrap">
        <table>
          <thead>
            <tr><th>Check</th><th>Result</th><th>Detail</th></tr>
          </thead>
          <tbody>
            {report.checks.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td><span className={`badge ${STATUS_BADGE[c.status] || "running"}`}>{c.status}</span></td>
                <td className="detailCell">{c.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Relationships</h3>
      <div className="previewWrap">
        <table>
          <thead>
            <tr>
              <th>Relationship</th><th>Child rows</th><th>Parent rows</th>
              <th>Valid refs</th><th>Orphans</th><th>Children per parent (min / avg / max)</th>
            </tr>
          </thead>
          <tbody>
            {report.relationships.map((r) => (
              <tr key={r.relationship}>
                <td><code>{r.relationship}</code></td>
                <td>{r.child_rows}</td>
                <td>{r.parent_rows}</td>
                <td>{r.valid_references} / {r.references}</td>
                <td>{r.orphans}</td>
                <td>
                  {r.children_per_parent.min} / {r.children_per_parent.avg} / {r.children_per_parent.max}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {report.shared_attributes && report.shared_attributes.length > 0 && (
        <p className="cardHint">
          Identifiers kept consistent with their parent record:{" "}
          {report.shared_attributes.map((a) => <code key={a}>{a} </code>)}
        </p>
      )}

      <h3>Generated tables</h3>
      <div className="previewWrap">
        <table>
          <thead>
            <tr><th>Table</th><th>Rows</th><th>File</th></tr>
          </thead>
          <tbody>
            {report.tables.map((t) => (
              <tr key={t.name}>
                <td>{t.name}{t.auto_included && <span className="cardHint"> (parent)</span>}</td>
                <td>{t.rows}</td>
                <td>
                  {t.dataset_id ? (
                    <a href={api.downloadUrl(t.dataset_id)} download>Download CSV</a>
                  ) : (
                    "not published"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {active && (
        <>
          <div className="genControls" style={{ marginTop: 16 }}>
            <span>Preview:</span>
            <select value={active.name} onChange={(e) => setPreviewTable(e.target.value)}>
              {report.tables.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
            </select>
          </div>
          <div className="previewWrap">
            <table>
              <thead>
                <tr>{active.columns.map((c) => <th key={c}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {active.preview.map((row, i) => (
                  <tr key={i}>
                    {active.columns.map((c) => <td key={c}>{row[c] == null ? "" : String(row[c])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
