import { useEffect, useState } from "react";
import { api } from "../api.js";
import SourceSelect from "./SourceSelect.jsx";
import UploadPanel from "./UploadPanel.jsx";
import RegisteredSourcePicker from "./RegisteredSourcePicker.jsx";

// The Data Source Connector, made explicit: pick which connector to use
// (Database or Flat File), then the format / database type, then the source.
//
//   Database  -> SQLite (Demo) | Oracle | MSSQL | PostgreSQL | MySQL
//                SQLite shows its tables straight away; the others ask for a
//                host + credentials, then show the tables of THAT database.
//   Flat File -> CSV | XML | Text
//   Registered Source -> a source from the Source Registry, then one of ITS
//                tables (the source id is kept separate from the table name)
//
// This mirrors the two backend connectors (Connectors/db_connector.py and
// Connectors/file_connector.py); the UI just surfaces the choice.
const FILE_TYPES = [
  { id: "CSV", label: "CSV", ext: ".csv" },
  { id: "XML", label: "XML", ext: ".xml" },
  { id: "TXT", label: "Text (.txt)", ext: ".txt" },
];

// Shown until /connectors/db-types answers (or if the API is unreachable).
const FALLBACK_DB_TYPES = [
  { id: "sqlite", label: "SQLite (Demo)", demo: true, driver_installed: true },
  { id: "oracle", label: "Oracle", default_port: 1521, database_label: "Service name", driver_installed: true, pip_package: "oracledb" },
  { id: "mssql", label: "MSSQL", default_port: 1433, database_label: "Database", driver_installed: true, pip_package: "pymssql" },
  { id: "postgresql", label: "PostgreSQL", default_port: 5432, database_label: "Database", driver_installed: true, pip_package: "psycopg2-binary" },
  { id: "mysql", label: "MySQL", default_port: 3306, database_label: "Database", driver_installed: true, pip_package: "pymysql" },
];

const EMPTY_FORM = { host: "", port: "", database: "", username: "", password: "", schema_name: "" };

export default function ConnectorPicker({
  sources,
  selectedTable,
  onSelectTable,
  onUploaded,
  selectedSourceId = null,
  selectedSourceName = "",
  onSelectRegistered,
}) {
  // When a registered source is selected, the table name must NOT be matched
  // against the legacy list (the same name can exist in both).
  const currentSource = selectedSourceId ? undefined : sources.find((s) => s.name === selectedTable);
  const [kind, setKind] = useState(
    selectedSourceId ? "registered" : currentSource?.kind === "file" ? "file" : "database"
  );
  const [fileType, setFileType] = useState("CSV");

  const [dbTypes, setDbTypes] = useState(FALLBACK_DB_TYPES);
  const [active, setActive] = useState(null);          // this user's connected external database, if any
  const [dbType, setDbType] = useState(currentSource?.kind === "external" ? currentSource.db_type : "sqlite");
  const [form, setForm] = useState(EMPTY_FORM);
  const [connecting, setConnecting] = useState(false);
  const [dbMessage, setDbMessage] = useState(null);    // { tone: "ok" | "error", text }

  // Learn which database types exist, whether their drivers are installed,
  // and whether this user is already connected to one.
  useEffect(() => {
    api.getDbConnectors()
      .then((data) => {
        setDbTypes(data.types);
        setActive(data.active);
      })
      .catch(() => { /* keep the fallback chips; the form will report any real error */ });
  }, []);

  // If the selected source changes from elsewhere (e.g. an upload made on
  // another tab, or the initial source picked on load), keep the toggles
  // pointed at whichever connector that source actually came from.
  useEffect(() => {
    if (selectedSourceId) {
      setKind("registered");
      return;
    }
    if (!currentSource) return;
    if (currentSource.kind === "file") {
      setKind("file");
    } else {
      setKind("database");
      setDbType(currentSource.kind === "external" ? currentSource.db_type : "sqlite");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTable, selectedSourceId]);

  const typeInfo = dbTypes.find((t) => t.id === dbType) || dbTypes[0];
  const isConnected = typeInfo.demo || (active && active.db_type === typeInfo.id);

  const tableSources = sources.filter((s) => s.kind === "table");
  const externalSources = sources.filter((s) => s.kind === "external" && s.db_type === dbType);
  const dbSources = typeInfo.demo ? tableSources : externalSources;
  const fileSources = sources.filter((s) => s.kind === "file");
  const activeFileType = FILE_TYPES.find((t) => t.id === fileType);

  function chooseDbType(id) {
    setDbType(id);
    setDbMessage(null);
    setForm(EMPTY_FORM);
    // Switching back to a database that already has tables: select its first
    // one, so the page never keeps pointing at a table from a different database.
    const own = id === "sqlite"
      ? sources.filter((s) => s.kind === "table")
      : sources.filter((s) => s.kind === "external" && s.db_type === id);
    if (own.length > 0 && !own.some((s) => s.name === selectedTable)) onSelectTable(own[0].name);
  }

  async function handleConnect(e) {
    e.preventDefault();
    setConnecting(true);
    setDbMessage(null);
    try {
      const result = await api.connectDb({
        db_type: dbType,
        host: form.host,
        port: form.port ? Number(form.port) : null,
        database: form.database,
        username: form.username,
        password: form.password,
        schema_name: form.schema_name || null,
      });
      setActive(result.active);
      setForm(EMPTY_FORM);                              // never keep the password in the page
      const first = result.active.tables[0];
      setDbMessage({
        tone: "ok",
        text: `Connected to ${result.active.label} - ${result.active.tables.length} tables found.`,
      });
      // Refresh the source list everywhere and select the first table.
      if (first) onUploaded(`${result.active.db_type}.${first}`);
    } catch (err) {
      setDbMessage({ tone: "error", text: err.message });
    } finally {
      setConnecting(false);
    }
  }

  async function handleDisconnect() {
    setDbMessage(null);
    try {
      await api.disconnectDb();
      setActive(null);
      // Fall back to a demo table so nothing keeps pointing at the closed connection.
      if (tableSources.length > 0) onUploaded(tableSources[0].name);
      setDbMessage({ tone: "ok", text: "Disconnected." });
    } catch (err) {
      setDbMessage({ tone: "error", text: err.message });
    }
  }

  const setField = (name) => (e) => setForm({ ...form, [name]: e.target.value });

  return (
    <div className="connectorPicker">
      <div className="connectorHeader">
        <span className="connectorLabel">Data Source Connector</span>
        <div className="segmented">
          <button type="button" className={kind === "database" ? "active" : ""} onClick={() => setKind("database")}>
            {"\u{1F5C4}\uFE0F"} Database
          </button>
          <button type="button" className={kind === "file" ? "active" : ""} onClick={() => setKind("file")}>
            {"\u{1F4C4}"} Flat File
          </button>
          {onSelectRegistered && (
            <button type="button" className={kind === "registered" ? "active" : ""} onClick={() => setKind("registered")}>
              {"\u{1F517}"} Registered Source
            </button>
          )}
        </div>
      </div>

      {selectedTable && (
        <div className="subtitle" style={{ margin: "0 0 8px" }}>
          Selected: <strong>{selectedTable}</strong>
          {selectedSourceId
            ? <> from registered source <strong>{selectedSourceName || selectedSourceId}</strong></>
            : " (demo / uploaded source)"}
        </div>
      )}

      {kind === "registered" && onSelectRegistered ? (
        <RegisteredSourcePicker
          selectedSourceId={selectedSourceId}
          selectedTable={selectedTable}
          onSelect={onSelectRegistered}
        />
      ) : kind === "database" ? (
        <div className="fileConnector">
          <div className="fileTypeRow">
            <span className="subtitle" style={{ margin: 0 }}>Database type:</span>
            {dbTypes.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`fileTypeChip ${dbType === t.id ? "active" : ""}`}
                onClick={() => chooseDbType(t.id)}
              >
                {t.label}
                {active && active.db_type === t.id && <span className="connDot" title="Connected" />}
              </button>
            ))}
          </div>

          {isConnected ? (
            <>
              <div className="controls" style={{ marginBottom: 0 }}>
                <SourceSelect
                  sources={dbSources}
                  value={dbSources.some((s) => s.name === selectedTable) ? selectedTable : ""}
                  onChange={onSelectTable}
                />
                <span className="subtitle" style={{ margin: 0 }}>
                  {typeInfo.demo
                    ? `${dbSources.length} tables in the demo database`
                    : `${dbSources.length} tables in ${active.database}${active.schema ? ` (${active.schema})` : ""} on ${active.host}`}
                </span>
                {!typeInfo.demo && (
                  <button type="button" className="ghostBtn" onClick={handleDisconnect}>Disconnect</button>
                )}
              </div>
              {!typeInfo.demo && dbSources.length === 0 && (
                <span className="subtitle">No tables found in this database/schema.</span>
              )}
            </>
          ) : (
            <form className="dbForm" onSubmit={handleConnect}>
              {!typeInfo.driver_installed && (
                <div className="uploadMsg error" style={{ marginTop: 0 }}>
                  The {typeInfo.label} driver is not installed on the server. Run{" "}
                  <code>pip install {typeInfo.pip_package}</code> and restart the API.
                </div>
              )}
              <div className="dbFormGrid">
                <label>Host
                  <input value={form.host} onChange={setField("host")} placeholder="db.example.com" autoComplete="off" />
                </label>
                <label>Port
                  <input type="number" value={form.port} onChange={setField("port")} placeholder={String(typeInfo.default_port || "")} />
                </label>
                <label>{typeInfo.database_label || "Database"}
                  <input value={form.database} onChange={setField("database")} autoComplete="off" />
                </label>
                <label>Schema (optional)
                  <input value={form.schema_name} onChange={setField("schema_name")} placeholder="default schema" autoComplete="off" />
                </label>
                <label>Username
                  <input value={form.username} onChange={setField("username")} autoComplete="off" />
                </label>
                <label>Password
                  <input type="password" value={form.password} onChange={setField("password")} autoComplete="new-password" />
                </label>
              </div>
              <div className="controls" style={{ marginBottom: 0 }}>
                <button type="submit" disabled={connecting || !typeInfo.driver_installed}>
                  {connecting ? "Connecting..." : `Connect to ${typeInfo.label}`}
                </button>
                <span className="subtitle" style={{ margin: 0 }}>
                  After connecting, the tables of that database appear here. Connecting replaces any other database you are connected to.
                </span>
              </div>
            </form>
          )}
          {dbMessage && <div className={`uploadMsg ${dbMessage.tone}`} style={{ marginTop: 0 }}>{dbMessage.text}</div>}
        </div>
      ) : (
        <div className="fileConnector">
          <div className="fileTypeRow">
            <span className="subtitle" style={{ margin: 0 }}>File format:</span>
            {FILE_TYPES.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`fileTypeChip ${fileType === t.id ? "active" : ""}`}
                onClick={() => setFileType(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>

          <UploadPanel accept={activeFileType.ext} typeLabel={activeFileType.label} onUploaded={onUploaded} />

          {fileSources.length > 0 && (
            <div className="controls" style={{ marginBottom: 0 }}>
              <SourceSelect
                sources={fileSources}
                value={currentSource?.kind === "file" ? selectedTable : ""}
                onChange={onSelectTable}
              />
              <span className="subtitle" style={{ margin: 0 }}>or pick a previously uploaded file</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
