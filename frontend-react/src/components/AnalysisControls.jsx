// Sample size + Run button for whatever source the Connector Picker above
// has selected. No source dropdown here - that lives in ConnectorPicker so
// there is exactly one place to pick a source, not two.
export default function AnalysisControls({
  selectedTable,
  sampleSize,
  onChangeSampleSize,
  onRunAnalysis,
  busy,
  status,
}) {
  return (
    <div className="controls">
      <label className="subtitle" style={{ margin: 0 }}>
        Sample size
        <input
          type="number"
          value={sampleSize}
          min={10}
          max={200}
          style={{ width: 80, marginLeft: 8 }}
          title="Rows to sample"
          onChange={(e) => onChangeSampleSize(e.target.value)}
        />
      </label>
      <button onClick={onRunAnalysis} disabled={busy || !selectedTable}>Run Profiling</button>
      <span className="status">{status}</span>
    </div>
  );
}
