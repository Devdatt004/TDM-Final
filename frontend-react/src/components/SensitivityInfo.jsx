// Display helpers for the sensitivity classification of a column (Step 8/9):
// the result of name / value-pattern / checksum / name-detection evidence, plus
// its human-review state. Distinct from the format "verdict" and from the
// Data Dictionary's default label for a format.

const SENSITIVITY = {
  sensitive: { label: "Sensitive", tone: "fail" },
  not_sensitive: { label: "Not sensitive", tone: "high" },
  unknown: { label: "Unknown", tone: "neutral" },
};

const EVIDENCE = [
  [/^column_name_matches_(.+)$/, (t) => `Column name suggests ${t}`],
  [/^data_pattern_matches_(.+)$/, (t) => `Value format matches ${t}`],
  [/^sample_values_match_dictionary_(.+)$/, (t) => `Values found in the ${t} list`],
  [/^sample_values_match_(.+)$/, (t) => `Values look like ${t}`],
  [/^free_text_contains_person_entity$/, () => "Text mentions a person's name"],
  [/^free_text_contains_location_entity$/, () => "Text mentions a place"],
];

const pretty = (type) => type.replace(/_/g, " ").toUpperCase();

export function describeEvidence(code) {
  for (const [pattern, text] of EVIDENCE) {
    const m = code.match(pattern);
    if (m) return text(m[1] ? pretty(m[1]) : "");
  }
  return code;
}

export function SensitivityBadge({ info }) {
  if (!info) return <>-</>;
  const s = SENSITIVITY[info.sensitivity] || { label: info.sensitivity, tone: "neutral" };
  return <span className={`badge ${s.tone}`}>{s.label}</span>;
}

export function ConfidenceText({ info }) {
  if (!info || !info.evidence?.length) return <>-</>;
  return <>{Math.round((info.sensitivity_confidence || 0) * 100)}%</>;
}

export function EvidenceList({ info }) {
  if (!info) return <>-</>;
  if (!info.evidence?.length) return <span className="muted">No evidence found</span>;
  return (
    <ul className="evidenceList">
      {info.evidence.map((e) => <li key={e} title={e}>{describeEvidence(e)}</li>)}
    </ul>
  );
}

export function ReviewState({ info }) {
  if (!info) return <>-</>;
  if (info.review_status === "PENDING") return <span className="badge review">Waiting for review #{info.review_id}</span>;
  if (info.review_status === "APPROVED") return <span className="badge high">Approved{info.reviewer_username ? ` by ${info.reviewer_username}` : ""}</span>;
  if (info.review_status === "REJECTED") return <span className="badge fail">Rejected{info.reviewer_username ? ` by ${info.reviewer_username}` : ""}</span>;
  if (info.classification_status === "classified") return <span className="muted">Decided automatically</span>;
  return <span className="muted">Not needed</span>;
}
