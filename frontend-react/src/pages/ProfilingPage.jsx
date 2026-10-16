import ConnectorPicker from "../components/ConnectorPicker.jsx";
import AnalysisControls from "../components/AnalysisControls.jsx";
import ColumnDetailsTable from "../components/ColumnDetailsTable.jsx";
import RecentRunsTable from "../components/RecentRunsTable.jsx";

export default function ProfilingPage({
  sources,
  selectedTable,
  onSelectTable,
  selectedSourceId,
  selectedSourceName,
  onSelectRegistered,
  sampleSize,
  onChangeSampleSize,
  onRunAnalysis,
  onUploaded,
  busy,
  status,
  analyzedTable,
  columns,
  runs,
}) {
  return (
    <>
      <div className="pageIntro">
        <h1>Profiling</h1>
        <p className="subtitle">
          Choose a Data Source Connector - a database table, a table from a registered source, or a CSV / XML / text file - then run
          profiling: sample rows &rarr; Pattern Analyzer + Profiler &rarr; Classification. This
          populates the Knowledge Base layer for every other tab.
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

      <section>
        <h2>Run profiling</h2>
        <AnalysisControls
          selectedTable={selectedTable}
          sampleSize={sampleSize}
          onChangeSampleSize={onChangeSampleSize}
          onRunAnalysis={onRunAnalysis}
          busy={busy}
          status={status}
        />
      </section>

      <ColumnDetailsTable tableName={analyzedTable} columns={columns} />

      <RecentRunsTable runs={runs} />
    </>
  );
}
