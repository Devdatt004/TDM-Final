import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

const STATUS_OPTIONS = ["PENDING", "APPROVED", "REJECTED", "ALL"];

// What the reviewer's choice does downstream (masking_service.plan_columns).
const SENSITIVITY_LABELS = {
  sensitive: "Sensitive",
  unknown: "Unknown — requires caution",
  not_sensitive: "Not sensitive",
};
const SENSITIVITY_HINTS = {
  sensitive: "Masking will disguise this column.",
  unknown: "Masking will still disguise this column, to be safe.",
  not_sensitive: "Masking will copy this column unchanged.",
};

export default function HumanReviewPage() {
  const [statusFilter, setStatusFilter] = useState("PENDING");
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reasons, setReasons] = useState({});
  const [corrections, setCorrections] = useState({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.getReviews(statusFilter);
      setData(result);
      setError("");
    } catch (e) {
      setError(e.message || "Unable to load review queue.");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  async function decide(item, decision) {
    const reason = (reasons[item.id] || "").trim();
    if (!reason) {
      setError("Enter a decision reason before approving or rejecting a classification.");
      return;
    }
    setBusyId(item.id);
    setError("");
    setMessage("");
    try {
      const correction = corrections[item.id] || {};
      const payload = { reason };
      if (decision === "approve") {
        if (correction.pattern_type?.trim()) payload.pattern_type = correction.pattern_type.trim();
        if (correction.sensitivity) payload.sensitivity = correction.sensitivity;
      }
      if (decision === "approve") await api.approveReview(item.id, payload);
      else await api.rejectReview(item.id, payload);
      setMessage(`Review #${item.id} ${decision === "approve" ? "approved" : "rejected"}.`);
      await load();
    } catch (e) {
      setError(e.message || "The review decision could not be saved.");
    } finally {
      setBusyId(null);
    }
  }

  function setCorrection(id, field, value) {
    setCorrections((prev) => ({ ...prev, [id]: { ...(prev[id] || {}), [field]: value } }));
  }

  return (
    <section>
      <div className="pageIntro">
        <h1>Human Review</h1>
        <p className="subtitle">Review uncertain sensitivity classifications, record a reason, and approve or reject them. Only authorized reviewer roles can make decisions.</p>
      </div>
      <div className="scoreRow">
        <div><div className="locLabel">Review requests</div><div className="scoreValue">{data.total ?? 0}</div></div>
        <label className="reviewFilter">Status
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{status}</option>)}
          </select>
        </label>
        <button onClick={load} disabled={loading}>Refresh</button>
      </div>
      {error && <div className="uploadMsg error">{error}</div>}
      {message && <div className="uploadMsg ok">{message}</div>}
      {loading ? <p>Loading review requests…</p> : data.items.length === 0 ? (
        <div className="noteBanner ok"><span className="noteIcon">✓</span><div>No review requests found for this status.</div></div>
      ) : (
        <div className="reviewList">
          {data.items.map((item) => {
            const editable = item.status === "PENDING";
            const correction = corrections[item.id] || {};
            return <article className="reviewCard" key={item.id}>
              <div className="reviewCardHeader">
                <div><h2>{item.table_name}.{item.column_name}</h2><p>Review #{item.id} · Run #{item.run_id} · {item.source_id || "Legacy/demo source"}</p></div>
                <span className={`reviewStatus ${item.status.toLowerCase()}`}>{item.status}</span>
              </div>
              <div className="reviewFacts">
                <div><span>Proposed pattern</span><strong>{item.proposed_pattern_type || "Unknown"}</strong></div>
                <div><span>Sensitivity</span><strong>{item.proposed_sensitivity || "unknown"}</strong></div>
                <div><span>Confidence</span><strong>{item.sensitivity_confidence == null ? "—" : `${Math.round(item.sensitivity_confidence * 100)}%`}</strong></div>
                <div><span>Created</span><strong>{item.created_at ? new Date(item.created_at).toLocaleString() : "—"}</strong></div>
              </div>
              {Array.isArray(item.evidence) && item.evidence.length > 0 && <div className="reviewEvidence"><span>Evidence</span><div>{item.evidence.map((e) => <code key={e}>{e}</code>)}</div></div>}
              {editable ? <>
                <label className="reviewField">Correct pattern type (optional)
                  <input value={correction.pattern_type ?? item.proposed_pattern_type ?? ""} onChange={(e) => setCorrection(item.id, "pattern_type", e.target.value)} maxLength={100} />
                </label>
                <label className="reviewField">Final sensitivity
                  <select value={correction.sensitivity ?? item.proposed_sensitivity ?? "unknown"} onChange={(e) => setCorrection(item.id, "sensitivity", e.target.value)}>
                    {Object.entries(SENSITIVITY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                  <small className="reviewHint">{SENSITIVITY_HINTS[correction.sensitivity ?? item.proposed_sensitivity ?? "unknown"]}</small>
                </label>
                <label className="reviewField">Decision reason (required)
                  <textarea value={reasons[item.id] || ""} onChange={(e) => setReasons((prev) => ({ ...prev, [item.id]: e.target.value }))} rows={2} maxLength={1000} placeholder="Explain why this classification is accepted or rejected." />
                </label>
                <div className="reviewActions">
                  <button disabled={busyId === item.id} onClick={() => decide(item, "approve")}>{busyId === item.id ? "Saving…" : "Approve"}</button>
                  <button className="secondaryButton" disabled={busyId === item.id} onClick={() => decide(item, "reject")}>Reject</button>
                </div>
              </> : <div className="reviewDecision"><strong>Decision by {item.reviewer_username || "unknown reviewer"}</strong>{item.final_sensitivity && <p>Final sensitivity: <strong>{SENSITIVITY_LABELS[item.final_sensitivity] || item.final_sensitivity}</strong></p>}<p>{item.decision_reason || "No reason recorded."}</p>{item.reviewed_at && <small>{new Date(item.reviewed_at).toLocaleString()}</small>}</div>}
            </article>;
          })}
        </div>
      )}
    </section>
  );
}
