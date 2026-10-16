export default function VerdictBadge({ verdict }) {
  if (verdict === "high_confidence") {
    return <span className="badge high">High confidence</span>;
  }
  if (verdict === "needs_review") {
    return <span className="badge review">Needs review</span>;
  }
  return <>-</>;
}
