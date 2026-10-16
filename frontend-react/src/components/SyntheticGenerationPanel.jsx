import { useState } from "react";
import { api } from "../api.js";

export default function SyntheticGenerationPanel({ selectedTable, selectedSourceId = null }) {
  const [numRows, setNumRows] = useState(20);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [preview, setPreview] = useState([]);
  const [columns, setColumns] = useState([]);
  const [downloadHref, setDownloadHref] = useState(null);

  async function handleGenerate() {
    if (!selectedTable) {
      setStatus("Select a table first.");
      return;
    }
    setBusy(true);
    setDownloadHref(null);
    setStatus("Generating...");

    try {
      const data = await api.generateSynthetic(selectedTable, numRows, "synthetic", selectedSourceId);
      const cols = data.preview.length ? Object.keys(data.preview[0]) : [];
      setColumns(cols);
      setPreview(data.preview);
      setDownloadHref(api.downloadUrl(data.dataset_id));
      setStatus(`Generated ${data.row_count} rows (preview shows first ${data.preview.length}).`);
    } catch (err) {
      setStatus("Error: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Synthetic Data Generation</h2>
      <p className="subtitle">
        Generates synthetic rows for the table selected above, based on its most recent analysis —
        nothing here reads real values from the source.
      </p>
      <div className="genControls">
        <input
          type="number"
          value={numRows}
          min={1}
          max={1000}
          style={{ width: 90 }}
          onChange={(e) => setNumRows(e.target.value)}
        />
        <button onClick={handleGenerate} disabled={busy}>Generate &amp; Preview</button>
        {downloadHref && (
          <a href={downloadHref} download>Download CSV</a>
        )}
        <span className="status">{status}</span>
      </div>
      <div className="previewWrap">
        <table>
          <thead>
            {columns.length > 0 && (
              <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
            )}
          </thead>
          <tbody>
            {preview.length === 0 ? (
              <tr><td>Click "Generate &amp; Preview" to create a synthetic sample.</td></tr>
            ) : (
              preview.map((row, i) => (
                <tr key={i}>
                  {columns.map((c) => <td key={c}>{row[c]}</td>)}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
