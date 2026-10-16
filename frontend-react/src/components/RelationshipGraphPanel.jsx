import { useState } from "react";
import { api } from "../api.js";

function Suggestions({ domain, onAccepted }) {
  const [list, setList] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function find() {
    setBusy(true);
    setMsg("");
    try {
      const data = await api.getRelationshipSuggestions(domain);
      setList(data.suggestions);
      if (data.suggestions.length === 0) setMsg("No undeclared relationships found.");
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function accept(s) {
    try {
      await api.addRelationship({
        child_table: s.child_table, child_column: s.child_column,
        parent_table: s.parent_table, parent_column: s.parent_column,
      });
      setList((l) => l.filter((x) => x !== s));
      onAccepted();
    } catch (err) {
      setMsg(err.message);
    }
  }

  return (
    <div>
      <h3>Undeclared relationships</h3>
      <p className="subtitle">
        Many databases don't declare all of their foreign keys (legacy cores, warehouses, optional
        references, role-named columns such as <code>settlement_account_id</code>). This looks for columns
        whose name follows a key convention and whose values match another table's key. Nothing is
        saved until you accept it; accepted links are treated exactly like declared ones when data is generated.
      </p>
      <div className="controls">
        <button onClick={find} disabled={busy}>{busy ? "Looking..." : "Find undeclared relationships"}</button>
        {msg && <span className="subtitle">{msg}</span>}
      </div>
      {list && list.length > 0 && (
        <div className="previewWrap">
          <table>
            <thead>
              <tr><th>Child column</th><th></th><th>Parent column</th><th>Why suggested</th><th>Values found in parent</th><th>Orphans</th><th></th></tr>
            </thead>
            <tbody>
              {list.map((s) => (
                <tr key={`${s.child_table}.${s.child_column}`}>
                  <td><code>{s.child_table}.{s.child_column}</code></td>
                  <td>&rarr;</td>
                  <td><code>{s.parent_table}.{s.parent_column}</code></td>
                  <td>{s.reason}</td>
                  <td>{s.match_percent}% of {s.distinct_values}</td>
                  <td>{s.orphan_values}</td>
                  <td><button onClick={() => accept(s)}>Accept</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function RelationshipGraphPanel({ domain, overview, busy, onRefresh }) {
  const relationships = overview ? overview.relationships : [];
  const order = overview ? overview.generation_order : [];

  return (
    <section>
      <div className="pageIntroTop">
        <h2>Relationship graph</h2>
        <button onClick={onRefresh} disabled={busy}>
          {busy ? "Discovering..." : "Re-discover from source"}
        </button>
      </div>
      <p className="subtitle">
        Relationships between tables, stored as metadata (no row values are read) and used to decide
        which table is generated first. <strong>Declared</strong> relationships are foreign keys read from the
        database schema; <strong>undeclared</strong> ones are logical links you confirmed below.
        {overview && overview.summary && (
          <> Currently {overview.summary.declared} declared and {overview.summary.undeclared} undeclared.</>
        )}
      </p>

      {overview && overview.cycle_error && (
        <div className="infoBanner error">
          <span className="infoBannerIcon">&#9888;</span>
          <div>
            <strong>Circular relationship</strong>
            <p>{overview.cycle_error}</p>
          </div>
        </div>
      )}

      <h3>Generation order (parents first)</h3>
      <div className="chipRow">
        {order.length === 0 && <span className="cardHint">No tables found yet.</span>}
        {order.map((t, i) => (
          <span key={t} className="chipStep">
            <span className="chip">{i + 1}. {t}</span>
            {i < order.length - 1 && <span className="chipArrow">&rarr;</span>}
          </span>
        ))}
      </div>

      <div className="previewWrap">
        <table>
          <thead>
            <tr>
              <th>Child column</th>
              <th></th>
              <th>Parent column</th>
              <th>Type</th>
              <th>Nullable</th>
            </tr>
          </thead>
          <tbody>
            {relationships.length === 0 ? (
              <tr><td colSpan={5}>No relationships found yet. Declared foreign keys appear here after discovery; use the section below to find undeclared ones.</td></tr>
            ) : (
              relationships.map((r) => (
                <tr key={r.id}>
                  <td><code>{r.child_table}.{r.child_column}</code></td>
                  <td>&rarr;</td>
                  <td><code>{r.parent_table}.{r.parent_column}</code></td>
                  <td>
                    <span className={`badge ${r.kind === "undeclared" ? "review" : "high"}`}>
                      {r.kind === "undeclared" ? "Undeclared (logical)" : "Declared (database FK)"}
                    </span>
                  </td>
                  <td>{r.nullable ? "yes" : "no"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <Suggestions domain={domain} onAccepted={onRefresh ? () => onRefresh(false) : () => {}} />

      {overview && overview.skipped.length > 0 && (
        <p className="cardHint">
          Skipped: {overview.skipped.map((s) => `${s.table} (${s.reason})`).join("; ")}
        </p>
      )}

      {overview && relationships.length > 0 && (
        <details className="metaDetails">
          <summary>Stored metadata graph (JSON)</summary>
          <pre>{JSON.stringify(overview.metadata_graph, null, 2)}</pre>
        </details>
      )}
    </section>
  );
}
