import { useState } from "react";
import { api } from "../api.js";

// The requested tables plus every table they depend on (walks the `parents` lists).
function withParents(selected, byName) {
  const out = new Set(selected);
  const stack = [...selected];
  while (stack.length) {
    const t = stack.pop();
    for (const p of (byName[t] && byName[t].parents) || []) {
      if (!out.has(p)) {
        out.add(p);
        stack.push(p);
      }
    }
  }
  return out;
}

export default function RelatedGenerationPanel({ overview, onGenerated }) {
  const tables = overview ? overview.tables : [];
  const byName = Object.fromEntries(tables.map((t) => [t.name, t]));

  const [selected, setSelected] = useState(new Set());
  const [rows, setRows] = useState({});
  const [coverage, setCoverage] = useState(true);
  const [seed, setSeed] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  const required = withParents(selected, byName);

  function toggle(name) {
    const next = new Set(selected);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setSelected(next);
  }

  function rowsFor(t) {
    return rows[t.name] !== undefined ? rows[t.name] : t.default_rows;
  }

  async function handleGenerate() {
    if (selected.size === 0) {
      setStatus("Select at least one table.");
      return;
    }
    const rowCounts = {};
    for (const name of required) rowCounts[name] = Number(rowsFor(byName[name]));

    setBusy(true);
    setStatus("Generating and validating...");
    try {
      const result = await api.generateRelated({
        tables: [...selected],
        rowCounts,
        ensureParentCoverage: coverage,
        seed,
      });
      onGenerated(result);
      setStatus("");
    } catch (err) {
      setStatus("Error: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Generate related tables</h2>
      <p className="subtitle">
        Tick the tables you need. Their parent tables are added automatically, generated first, and
        every foreign key is filled from keys that really exist. Tables are published only if
        validation passes.
      </p>

      <div className="previewWrap">
        <table>
          <thead>
            <tr>
              <th>Generate</th>
              <th>Table</th>
              <th>Depends on</th>
              <th>Source rows</th>
              <th>Rows to generate</th>
            </tr>
          </thead>
          <tbody>
            {tables.length === 0 ? (
              <tr><td colSpan={5}>Loading tables...</td></tr>
            ) : (
              tables.map((t) => {
                const isSelected = selected.has(t.name);
                const isRequired = required.has(t.name) && !isSelected;
                return (
                  <tr key={t.name}>
                    <td>
                      <input
                        type="checkbox"
                        checked={isSelected || isRequired}
                        disabled={isRequired}
                        onChange={() => toggle(t.name)}
                      />
                    </td>
                    <td>
                      <strong>{t.name}</strong>
                      {isRequired && <span className="cardHint"> (added: parent of a selected table)</span>}
                    </td>
                    <td>{t.parents.length ? t.parents.join(", ") : "-"}</td>
                    <td>{t.row_count == null ? "-" : t.row_count}</td>
                    <td>
                      <input
                        type="number"
                        min={1}
                        max={1000}
                        style={{ width: 90 }}
                        value={rowsFor(t)}
                        disabled={!required.has(t.name)}
                        onChange={(e) => setRows({ ...rows, [t.name]: e.target.value })}
                      />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="genControls" style={{ marginTop: 16 }}>
        <label className="inlineCheck">
          <input type="checkbox" checked={coverage} onChange={(e) => setCoverage(e.target.checked)} />
          Every parent gets at least one child
        </label>
        <input
          type="number"
          placeholder="Seed (optional)"
          value={seed}
          style={{ width: 140 }}
          onChange={(e) => setSeed(e.target.value)}
        />
        <button onClick={handleGenerate} disabled={busy || tables.length === 0}>
          {busy ? "Working..." : "Generate & validate"}
        </button>
        <span className="status">{status}</span>
      </div>
    </section>
  );
}
