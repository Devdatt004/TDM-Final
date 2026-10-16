import { useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import Nav from "./components/Nav.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import ProfilingPage from "./pages/ProfilingPage.jsx";
import SyntheticDataPage from "./pages/SyntheticDataPage.jsx";
import DataRelationshipValidationPage from "./pages/DataRelationshipValidationPage.jsx";
import { DATA_RELATIONSHIP_TAB_ID } from "./featureNames.js";
import MaskingPage from "./pages/MaskingPage.jsx";
import KnowledgeBasePage from "./pages/KnowledgeBasePage.jsx";
import QueryAgentPage from "./pages/QueryAgentPage.jsx";
import LogsPage from "./pages/LogsPage.jsx";
import HumanReviewPage from "./pages/HumanReviewPage.jsx";

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");

  const [sources, setSources] = useState([]);
  const [selectedTable, setSelectedTable] = useState("");
  // Registered Source (Source Registry) selection. The source id and the table
  // name are separate values; selectedSourceId === null means the legacy
  // demo / uploaded-file flow.
  const [selectedSourceId, setSelectedSourceId] = useState(null);
  const [selectedSourceName, setSelectedSourceName] = useState("");
  const catalogSeq = useRef(0);
  const [sampleSize, setSampleSize] = useState(50);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  const [summary, setSummary] = useState(null);
  const [previousSummary, setPreviousSummary] = useState(null);
  const [runs, setRuns] = useState([]);
  const [apiStatus, setApiStatus] = useState("checking"); // "checking" | "online" | "offline"
  const [lastUpdated, setLastUpdated] = useState(null);

  const [analyzedTable, setAnalyzedTable] = useState("");
  const [columns, setColumns] = useState([]);

  const [catalogTable, setCatalogTable] = useState("");
  const [catalogColumns, setCatalogColumns] = useState([]);
  const [catalogError, setCatalogError] = useState("");

  // ---- Initial load: tables, summary, and runs ----
  useEffect(() => {
    checkBackend();
    loadSources();
    loadSummary();
    loadRuns();

    // Keep the dashboard live with lightweight polling.
    const POLL_MS = 12000;
    const id = setInterval(() => {
      loadSummary();
      loadRuns();
    }, POLL_MS);
    return () => clearInterval(id);
  }, []);

  async function checkBackend() {
    try {
      const data = await api.health();
      if (data?.status === "ok") {
        setApiStatus("online");
        setLastUpdated(new Date());
      } else {
        setApiStatus("offline");
      }
    } catch {
      setApiStatus("offline");
    }
  }

  async function loadSources() {
    try {
      const data = await api.getTables();
      const normalizedSources = Array.isArray(data.sources)
        ? data.sources
        : (Array.isArray(data.tables) ? data.tables.map((name) => ({ name, kind: "table" })) : []);
      setSources(normalizedSources);
      if (normalizedSources.length > 0) setSelectedTable((prev) => prev || data.sources[0].name);
    } catch (err) {
      setStatus("Could not load data sources - verify the FastAPI backend is running on port 8000.");
    }
  }

  async function loadSummary() {
    try {
      const data = await api.getSummary();
      setSummary((prev) => {
        setPreviousSummary(prev);
        return data;
      });
      setApiStatus("online");
      setLastUpdated(new Date());
    } catch {
      // summary cards just stay at "-" if this fails
      setApiStatus("offline");
    }
  }

  async function loadRuns() {
    try {
      const data = await api.getRuns();
      setRuns(data);
    } catch {
      // recent runs table just stays empty if this fails
    }
  }

  async function loadResults(runId, tableName) {
    const data = await api.getResults(runId);
    setAnalyzedTable(tableName);
    setColumns(data.columns);
  }

  async function loadSchemaCatalog(tableName, sourceId = selectedSourceId) {
    const seq = ++catalogSeq.current;
    try {
      const data = await api.getSchemaCatalog(tableName, sourceId);
      if (seq !== catalogSeq.current) return;
      setCatalogTable(tableName);
      setCatalogColumns(data.columns);
      setCatalogError("");
    } catch (err) {
      if (seq !== catalogSeq.current) return;
      setCatalogTable("");
      setCatalogColumns([]);
      setCatalogError(err.message);
    }
  }

  // Legacy (demo database / uploaded file / connected database) selection.
  function handleSelectTable(name) {
    setSelectedSourceId(null);
    setSelectedSourceName("");
    setSelectedTable(name);
  }

  // Registered-source selection: source id and table are stored separately.
  function handleSelectRegistered(sourceId, table, sourceName = "") {
    setSelectedSourceId(sourceId || null);
    setSelectedSourceName(sourceName || "");
    setSelectedTable(table || "");
  }

  // After a file upload: refresh the source list, select the new file,
  // and refresh the dashboard numbers so the upload shows up as activity.
  async function handleUploaded(name) {
    await loadSources();
    handleSelectTable(name);
    loadSummary();
    loadRuns();
  }

  async function handleRunAnalysis() {
    if (!selectedTable) return;
    setBusy(true);
    setStatus("Running...");

    try {
      const analyzeData = await api.runAnalysis(selectedTable, sampleSize, selectedSourceId);
      await Promise.all([
        loadResults(analyzeData.run_id, selectedTable),
        loadSummary(),
        loadRuns(),
        loadSchemaCatalog(selectedTable, selectedSourceId),
      ]);
      setStatus("");
    } catch (err) {
      setStatus("Error: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  // Whenever the selected table changes, keep the Knowledge Base / Masking
  // tabs' schema catalog view in sync with it (if that table has already
  // been analyzed at least once).
  useEffect(() => {
    setCatalogTable("");
    setCatalogColumns([]);
    setCatalogError("");
    if (selectedTable) loadSchemaCatalog(selectedTable, selectedSourceId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTable, selectedSourceId]);

  function renderPage() {
    switch (activeTab) {
      case "profiling":
        return (
          <ProfilingPage
            sources={sources}
            selectedTable={selectedTable}
            onSelectTable={handleSelectTable}
            selectedSourceId={selectedSourceId}
            selectedSourceName={selectedSourceName}
            onSelectRegistered={handleSelectRegistered}
            sampleSize={sampleSize}
            onChangeSampleSize={setSampleSize}
            onRunAnalysis={handleRunAnalysis}
            onUploaded={handleUploaded}
            busy={busy}
            status={status}
            analyzedTable={analyzedTable}
            columns={columns}
            runs={runs}
          />
        );
      case "human-review":
        return <HumanReviewPage />;
      case "synthetic-data":
        return (
          <SyntheticDataPage
            sources={sources}
            selectedTable={selectedTable}
            onSelectTable={handleSelectTable}
            selectedSourceId={selectedSourceId}
            selectedSourceName={selectedSourceName}
            onSelectRegistered={handleSelectRegistered}
            onUploaded={handleUploaded}
            catalogTable={catalogTable}
            catalogColumns={catalogColumns}
            catalogError={catalogError}
          />
        );
      case DATA_RELATIONSHIP_TAB_ID:
        return <DataRelationshipValidationPage onGenerated={() => { loadSummary(); loadRuns(); }} />;
      case "masking":
        return (
          <MaskingPage
            sources={sources}
            selectedTable={selectedTable}
            onSelectTable={handleSelectTable}
            selectedSourceId={selectedSourceId}
            selectedSourceName={selectedSourceName}
            onSelectRegistered={handleSelectRegistered}
            catalogTable={catalogTable}
            catalogColumns={catalogColumns}
            catalogError={catalogError}
          />
        );
      case "knowledge-base":
        return (
          <KnowledgeBasePage
            sources={sources}
            selectedTable={selectedTable}
            onSelectTable={handleSelectTable}
            selectedSourceId={selectedSourceId}
            selectedSourceName={selectedSourceName}
            onSelectRegistered={handleSelectRegistered}
            catalogTable={catalogTable}
            catalogColumns={catalogColumns}
            catalogError={catalogError}
          />
        );
      case "query-agent":
        return <QueryAgentPage selectedTable={selectedTable} />;
      case "logs":
        return <LogsPage />;
      case "dashboard":
      default:
        return (
          <DashboardPage
            summary={summary}
            previousSummary={previousSummary}
            runs={runs}
            apiStatus={apiStatus}
            lastUpdated={lastUpdated}
            onNavigate={setActiveTab}
          />
        );
    }
  }

  return (
    <div className="appShell">
      <Nav activeTab={activeTab} onSelectTab={setActiveTab} />
      <main className="pageContent">{renderPage()}</main>
    </div>
  );
}
