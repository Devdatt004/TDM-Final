import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

// Pick a source from the Source Registry, then one of ITS tables.
//
// The registered source id and the table name are kept as two separate
// values: `selectedSourceId` identifies the source (and therefore which
// database every backend call talks to), `selectedTable` is only a table
// inside that source. Changing the source clears the table selection and
// reloads the table list, so a table is never carried over to a source
// that does not own it.
export default function RegisteredSourcePicker({ selectedSourceId, selectedTable, onSelect }) {
  const [sources, setSources] = useState([]);
  const [sourcesState, setSourcesState] = useState("loading"); // loading | ready | error
  const [sourcesError, setSourcesError] = useState("");

  const [sourceId, setSourceId] = useState(selectedSourceId || "");
  const [tables, setTables] = useState([]);
  const [tablesState, setTablesState] = useState("idle");      // idle | loading | ready | error
  const [tablesError, setTablesError] = useState("");
  const requestSeq = useRef(0);                                 // ignores out-of-order responses

  function loadSources() {
    setSourcesState("loading");
    api.getRegisteredSources()
      .then((data) => {
        const usable = (data.sources || []).filter((s) => s.status !== "DISABLED");
        setSources(usable);
        setSourcesState("ready");
      })
      .catch((err) => {
        setSourcesError(err.message);
        setSourcesState("error");
      });
  }

  useEffect(loadSources, []);

  // Keep the local dropdown in step with the app-level selection.
  useEffect(() => {
    setSourceId(selectedSourceId || "");
  }, [selectedSourceId]);

  // Refresh the table list whenever the chosen source changes.
  useEffect(() => {
    setTables([]);
    setTablesError("");
    if (!sourceId) {
      setTablesState("idle");
      return;
    }
    const seq = ++requestSeq.current;
    setTablesState("loading");
    api.getSourceTables(sourceId)
      .then((data) => {
        if (seq !== requestSeq.current) return;                 // a newer request superseded this one
        setTables(data.tables || []);
        setTablesState("ready");
      })
      .catch((err) => {
        if (seq !== requestSeq.current) return;
        setTablesError(err.message);
        setTablesState("error");
      });
  }, [sourceId]);

  const current = sources.find((s) => s.id === sourceId);

  function chooseSource(id) {
    setSourceId(id);
    // Drop any table chosen under the previous source.
    const src = sources.find((s) => s.id === id);
    onSelect(id || null, "", src ? src.name : "");
  }

  function chooseTable(table) {
    onSelect(sourceId, table, current ? current.name : "");
  }

  const tableValue = tables.includes(selectedTable) && selectedSourceId === sourceId ? selectedTable : "";

  return (
    <div className="fileConnector">
      <div className="controls" style={{ marginBottom: 0 }}>
        <label className="subtitle" style={{ margin: 0 }}>
          Registered source
          <select
            style={{ marginLeft: 8 }}
            value={sourceId}
            disabled={sourcesState !== "ready"}
            onChange={(e) => chooseSource(e.target.value)}
          >
            <option value="">
              {sourcesState === "loading" ? "Loading sources..." : "Select a source..."}
            </option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>{s.name} ({s.source_type})</option>
            ))}
          </select>
        </label>

        <label className="subtitle" style={{ margin: 0 }}>
          Table
          <select
            style={{ marginLeft: 8 }}
            value={tableValue}
            disabled={tablesState !== "ready" || tables.length === 0}
            onChange={(e) => chooseTable(e.target.value)}
          >
            <option value="">
              {!sourceId ? "Select a source first"
                : tablesState === "loading" ? "Loading tables..."
                : tablesState === "error" ? "Tables unavailable"
                : tables.length === 0 ? "No tables"
                : "Select a table..."}
            </option>
            {tables.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>

        <button type="button" className="ghostBtn" onClick={loadSources} disabled={sourcesState === "loading"}>
          Refresh sources
        </button>
        {tablesState === "ready" && (
          <span className="subtitle" style={{ margin: 0 }}>
            {tables.length} table{tables.length === 1 ? "" : "s"} in {current ? current.name : "this source"}
          </span>
        )}
      </div>

      {sourcesState === "error" && (
        <div className="uploadMsg error" style={{ marginTop: 0 }}>
          Could not load registered sources: {sourcesError}
        </div>
      )}
      {sourcesState === "ready" && sources.length === 0 && (
        <span className="subtitle">
          No sources are registered yet. Register one with <code>POST /api/v1/sources</code>.
        </span>
      )}
      {tablesState === "error" && (
        <div className="uploadMsg error" style={{ marginTop: 0 }}>
          Could not load tables for this source: {tablesError}
        </div>
      )}
      {tablesState === "ready" && tables.length === 0 && (
        <span className="subtitle">This source has no tables.</span>
      )}
    </div>
  );
}
