import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { statusTone } from "../statusTone.js";
import { timeAgo } from "../timeAgo.js";

function formatBytes(n) {
  if (n === null || n === undefined) return "-";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function fileNameOf(path) {
  return path ? path.split(/[\\/]/).pop() : null;
}

const REFRESH_MS = 10000;

export default function LogsPage() {
  const [logs, setLogs] = useState({ entries: [], activities: [], total: 0 });
  const [files, setFiles] = useState({ locations: [], outputs: [], uploads: [] });
  const [retention, setRetention] = useState(null);
  const [audit, setAudit] = useState(null);     // admins only; null for everyone else
  const [filter, setFilter] = useState("");
  const [userFilter, setUserFilter] = useState("");
  const [error, setError] = useState("");
  const [purgeMsg, setPurgeMsg] = useState("");
  const [purging, setPurging] = useState(false);

  const load = useCallback(async () => {
    try {
      const [l, f, r] = await Promise.all([
        api.getLogs(filter, userFilter),
        api.getFiles(),
        api.getLogRetention(),
      ]);
      setLogs(l);
      setFiles(f);
      setRetention(r);
      api.getAudit().then(setAudit).catch(() => setAudit(null));   // 403 for non-admins
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, [filter, userFilter]);

  // Load now, then keep the page fresh while it is open.
  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  async function handlePurge() {
    setPurging(true);
    setPurgeMsg("");
    try {
      const result = await api.purgeLogs();
      setPurgeMsg(
        result.deleted > 0
          ? `Removed ${result.deleted} log ${result.deleted === 1 ? "entry" : "entries"} older than ${result.retention_days} days.`
          : `Nothing to remove - no entries are older than ${result.retention_days} days.`
      );
      await load();
    } catch (err) {
      setPurgeMsg("Cleanup failed: " + err.message);
    } finally {
      setPurging(false);
    }
  }

  return (
    <>
      <div className="pageIntro">
        <h1>Logs</h1>
      </div>

      {error && <div className="uploadMsg error">Could not load logs: {error}</div>}

      {/* ---- Retention ---- */}
      <section>
        <h2>Log retention</h2>
        <div className="retentionBox">
          <div className="retentionText">
            <strong>Automatic cleanup:</strong> log entries older than{" "}
            <strong>{retention ? retention.retention_days : 5} days</strong> are deleted
            automatically (checked at startup and then every hour). Uploaded files, generated
            output files and profiling results are not touched.
            <div className="retentionMeta">
              {retention && (
                <>
                  {retention.total_logs} {retention.total_logs === 1 ? "entry" : "entries"} stored
                  {retention.oldest_log_at && <> · oldest {timeAgo(retention.oldest_log_at)}</>}
                  {retention.last_purge_at && (
                    <> · last check {timeAgo(retention.last_purge_at)} (removed {retention.last_purge_deleted})</>
                  )}
                </>
              )}
            </div>
          </div>
          <div className="retentionActions">
            <button onClick={handlePurge} disabled={purging}>
              {purging ? "Cleaning..." : "Clean up now"}
            </button>
          </div>
        </div>
        {purgeMsg && <div className="uploadMsg ok">{purgeMsg}</div>}
      </section>

      {/* ---- Activity log ---- */}
      <section>
        <h2>Activity log</h2>
        <div className="controls">
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All activities</option>
            {logs.activities.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
          <select value={userFilter} onChange={(e) => setUserFilter(e.target.value)}>
            <option value="">All users</option>
            {(logs.users || []).map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
          <button onClick={load}>Refresh</button>
          <span className="subtitle logCount">
            Showing {logs.entries.length} of {logs.total}
          </span>
        </div>
        <div className="previewWrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>User</th>
                <th>Activity</th>
                <th>Source</th>
                <th>Type</th>
                <th>Status</th>
                <th>Details</th>
                <th>File</th>
              </tr>
            </thead>
            <tbody>
              {logs.entries.length === 0 ? (
                <tr><td colSpan={8}>No log entries yet.</td></tr>
              ) : (
                logs.entries.map((e) => (
                  <tr key={e.id}>
                    <td className="nowrap">{new Date(e.created_at).toLocaleString()}</td>
                    <td><span className="userTag">{e.user ?? "-"}</span></td>
                    <td><span className="activityTag">{e.activity}</span></td>
                    <td>{e.source || "-"}</td>
                    <td>{e.source_type || "-"}</td>
                    <td><span className={`badge ${statusTone(e.status)}`}>{e.status}</span></td>
                    <td className="detailCell">{e.message || "-"}</td>
                    <td>
                      {e.file_path ? <code title={e.file_path}>{fileNameOf(e.file_path)}</code> : "-"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* ---- Audit log (admins) ---- */}
      {audit && (
        <section>
          <div className="pageIntroTop">
            <h2>Audit log</h2>
            <span className={`badge ${audit.chain.intact ? "high" : "review"}`}>
              {audit.chain.intact ? "tamper check passed" : `tamper check FAILED at entry ${audit.chain.first_bad_id}`}
            </span>
          </div>
          <p className="subtitle">
            Database connections, file downloads, and other operational events. Read-only, never cleaned up.
          </p>
          <div className="previewWrap">
            <table>
              <thead>
                <tr><th>Time</th><th>User</th><th>Event</th><th>Target</th><th>Status</th><th>Details</th></tr>
              </thead>
              <tbody>
                {audit.entries.length === 0 ? (
                  <tr><td colSpan={6}>No audit entries yet.</td></tr>
                ) : (
                  audit.entries.map((e) => (
                    <tr key={e.id}>
                      <td className="nowrap">{new Date(e.created_at).toLocaleString()}</td>
                      <td><span className="userTag">{e.user}</span></td>
                      <td><span className="activityTag">{e.event}</span></td>
                      <td>{e.target || "-"}</td>
                      <td><span className={`badge ${statusTone(e.status)}`}>{e.status}</span></td>
                      <td className="detailCell">{e.detail || "-"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ---- File locations ---- */}
      <section>
        <h2>File locations</h2>
        <p className="subtitle">Where the platform reads and writes files on the machine running the API.</p>
        <div className="previewWrap">
          <table>
            <thead>
              <tr>
                <th>What</th>
                <th>Location</th>
                <th>Files</th>
                <th>Size</th>
              </tr>
            </thead>
            <tbody>
              {files.locations.length === 0 ? (
                <tr><td colSpan={4}>Loading...</td></tr>
              ) : (
                files.locations.map((l) => (
                  <tr key={l.label}>
                    <td>
                      <div className="locLabel">{l.label}</div>
                      <div className="locDesc">{l.description}</div>
                    </td>
                    <td><code className="pathCode">{l.path}</code>{!l.exists && <span className="badge review"> missing</span>}</td>
                    <td>{l.file_count}</td>
                    <td>{formatBytes(l.total_bytes)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* ---- File output generation ---- */}
      <section>
        <h2>File output generation</h2>
        <p className="subtitle">Files written by Synthetic Data Generation and Masking previews.</p>
        <div className="previewWrap">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Source</th>
                <th>Generated by</th>
                <th>User</th>
                <th>Rows</th>
                <th>Size</th>
                <th>Created</th>
                <th>Location</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {files.outputs.length === 0 ? (
                <tr><td colSpan={9}>No output files generated yet.</td></tr>
              ) : (
                files.outputs.map((o) => (
                  <tr key={o.dataset_id}>
                    <td><code>{o.file_name}</code></td>
                    <td>{o.source_table}</td>
                    <td>{o.generated_by !== "-" ? <span className="activityTag">{o.generated_by}</span> : "-"}</td>
                    <td><span className="userTag">{o.generated_by_user ?? "-"}</span></td>
                    <td>{o.row_count}</td>
                    <td>{formatBytes(o.size_bytes)}</td>
                    <td className="nowrap">{new Date(o.created_at).toLocaleString()}</td>
                    <td><code className="pathCode">{o.file_path}</code></td>
                    <td>
                      {o.exists ? (
                        <a href={api.downloadUrl(o.dataset_id)} download>Download</a>
                      ) : (
                        <span className="badge review">file missing</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* ---- Uploaded input files ---- */}
      <section>
        <h2>Uploaded input files</h2>
        <div className="previewWrap">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Type</th>
                <th>Rows</th>
                <th>Columns</th>
                <th>Size</th>
                <th>Uploaded</th>
                <th>Uploaded by</th>
                <th>Location</th>
              </tr>
            </thead>
            <tbody>
              {files.uploads.length === 0 ? (
                <tr><td colSpan={8}>No files uploaded yet - use the Profiling tab to upload a CSV, XML or text file.</td></tr>
              ) : (
                files.uploads.map((u) => (
                  <tr key={u.name}>
                    <td><code>{u.name}</code></td>
                    <td>{u.file_type}</td>
                    <td>{u.row_count}</td>
                    <td>{u.column_count}</td>
                    <td>{formatBytes(u.size_bytes)}</td>
                    <td className="nowrap">{new Date(u.uploaded_at).toLocaleString()}</td>
                    <td><span className="userTag">{u.uploaded_by ?? "-"}</span></td>
                    <td>
                      <code className="pathCode">{u.file_path}</code>
                      {!u.exists && <span className="badge review"> missing</span>}
                    </td>
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
