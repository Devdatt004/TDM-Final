import { useState } from "react";
import { api } from "../api.js";
import SourceSelect from "../components/SourceSelect.jsx";
import MaskingRecommendationTable from "../components/MaskingRecommendationTable.jsx";

export default function MaskingPage({ sources, selectedTable, onSelectTable, selectedSourceId = null, selectedSourceName = "", catalogTable, catalogColumns, catalogError }) {
  const [numRows, setNumRows] = useState(10);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [preview, setPreview] = useState([]);
  const [previewColumns, setPreviewColumns] = useState([]);
  const [columnPlan, setColumnPlan] = useState([]);
  const [keyNote, setKeyNote] = useState("");

  async function handlePreview() {
    if (!selectedTable) {
      setStatus("Select a table first.");
      return;
    }
    setBusy(true);
    setStatus("Generating masked preview...");
    try {
      const data = await api.maskTable(selectedTable, numRows, selectedSourceId);
      setPreviewColumns(data.columns.map((c) => c.column));
      setColumnPlan(data.columns);
      setPreview(data.preview);
      setKeyNote(
        `Tokens use key "${data.key_id}"` +
          (data.ephemeral_key ? " (ephemeral development key - tokens change when the backend restarts)." : ".")
      );
      setStatus(`Masked ${data.row_count} rows (showing ${data.preview.length}). Saved as ${data.file_name}.`);
    } catch (err) {
      setStatus("Error: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="pageIntro">
        <h1>Masking</h1>
        <p className="subtitle">
          Recommends a masking technique per column from the Data Dictionary sensitivity level, and
          masks real source rows: join keys and direct identifiers become deterministic HMAC tokens
          (joins still work across masked tables), other sensitive values are substituted.
        </p>
      </div>

      <div className="controls">
        <SourceSelect
          sources={sources}
          value={selectedSourceId ? "" : selectedTable}
          onChange={onSelectTable}
          placeholder={selectedSourceId ? "Registered source selected..." : ""}
        />
        {selectedSourceId && selectedTable && (
          <span className="subtitle" style={{ margin: 0 }}>
            Using <strong>{selectedTable}</strong> from registered source{" "}
            <strong>{selectedSourceName || selectedSourceId}</strong> (change it on the Profiling tab).
          </span>
        )}
      </div>

      <MaskingRecommendationTable tableName={catalogTable} columns={catalogColumns} error={catalogError} />

      <section>
        <h2>Masked sample preview</h2>
        <p className="subtitle">
          Uses the latest profiling classifications. Columns with pending human review block masking.
        </p>
        <div className="genControls">
          <input
            type="number"
            value={numRows}
            min={1}
            max={200}
            style={{ width: 90 }}
            onChange={(e) => setNumRows(e.target.value)}
          />
          <button onClick={handlePreview} disabled={busy}>Generate Masked Preview</button>
          <span className="status">{status}</span>
        </div>
        {columnPlan.length > 0 && (
          <div className="previewWrap">
            <table>
              <thead><tr><th>Column</th><th>Action</th><th>Why</th></tr></thead>
              <tbody>
                {columnPlan.map((c) => (
                  <tr key={c.column}>
                    <td>{c.column}</td>
                    <td><span className={`badge ${c.action === "passthrough" ? "review" : "high"}`}>{c.action}</span></td>
                    <td>{c.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {keyNote && <p className="subtitle">{keyNote}</p>}
          </div>
        )}
        <div className="previewWrap">
          <table>
            <thead>
              {previewColumns.length > 0 && (
                <tr>{previewColumns.map((c) => <th key={c}>{c}</th>)}</tr>
              )}
            </thead>
            <tbody>
              {preview.length === 0 ? (
                <tr><td>Click "Generate Masked Preview" to see masked sample rows.</td></tr>
              ) : (
                preview.map((row, i) => (
                  <tr key={i}>
                    {previewColumns.map((c) => <td key={c}>{row[c]}</td>)}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
