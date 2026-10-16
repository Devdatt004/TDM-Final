import ConnectorPicker from "../components/ConnectorPicker.jsx";
import SyntheticGenerationPanel from "../components/SyntheticGenerationPanel.jsx";

function ProfilingNote({ selectedTable, catalogTable, catalogColumns, catalogError }) {
  if (!selectedTable) return null;

  const isProfiled = catalogTable === selectedTable && catalogColumns && catalogColumns.length > 0;
  if (isProfiled) {
    return (
      <div className="noteBanner ok">
        <span className="noteIcon">{"\u2705"}</span>
        <span>The selected source has been profiled - synthetic data will be generated from its most recent Profiling run.</span>
      </div>
    );
  }
  return (
    <div className="noteBanner warn">
      <span className="noteIcon">{"\u26A0\uFE0F"}</span>
      <span>
        <strong>Run Profiling before generating synthetic data.</strong> Synthetic data is built from
        the results of a Profiling run, never from real values. {catalogError ? "" : "Checking... "}
        Open the Profiling tab, select this source, and click "Run Profiling" first.
      </span>
    </div>
  );
}

export default function SyntheticDataPage({
  sources,
  selectedTable,
  onSelectTable,
  selectedSourceId,
  selectedSourceName,
  onSelectRegistered,
  onUploaded,
  catalogTable,
  catalogColumns,
  catalogError,
}) {
  return (
    <>
      <div className="pageIntro">
        <h1>Synthetic Data Generation</h1>
        <p className="subtitle">
          Pick a database table, or upload a CSV / XML / text file right here, then generate
          synthetic rows from its most recent Profiling run - detailed previews and downloads live
          only in this tab, not on the Dashboard.
        </p>
      </div>

      <ConnectorPicker
        sources={sources}
        selectedTable={selectedTable}
        onSelectTable={onSelectTable}
        onUploaded={onUploaded}
        selectedSourceId={selectedSourceId}
        selectedSourceName={selectedSourceName}
        onSelectRegistered={onSelectRegistered}
      />

      <ProfilingNote
        selectedTable={selectedTable}
        catalogTable={catalogTable}
        catalogColumns={catalogColumns}
        catalogError={catalogError}
      />

      <SyntheticGenerationPanel selectedTable={selectedTable} selectedSourceId={selectedSourceId} />
    </>
  );
}
