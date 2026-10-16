import AnimatedNumber from "./AnimatedNumber.jsx";
import { statusTone } from "../statusTone.js";
import { timeAgo } from "../timeAgo.js";

// The first card is the "Recent activity" card (what the platform is doing
// or did last); the other three are numeric classification totals.
const NUMERIC_CARDS = [
  { key: "fields_classified", label: "Fields classified", accent: "purple", icon: "\u{1F3F7}" },
  { key: "high_confidence", label: "High confidence", accent: "green", icon: "\u2705" },
  { key: "needs_review", label: "Needs review", accent: "amber", icon: "\u26A0" },
];

function RecentActivityCard({ latest }) {
  const running = latest && latest.status === "running";
  return (
    <div className="card accent-blue activityCard">
      <div className="cardTop">
        <div className="label">Recent activity</div>
        <span className="cardIcon">{running ? "\u23F3" : "\u26A1"}</span>
      </div>
      {latest ? (
        <>
          <div className="value activityValue">{latest.activity}</div>
          <div className="activityMeta">
            {latest.user && latest.user !== "-" && <span className="userTag">{latest.user}</span>}
            {latest.source && <span className="activitySource">{latest.source}</span>}
            <span className={`badge ${statusTone(latest.status)}`}>{latest.status}</span>
            <span className="activityWhen">{timeAgo(latest.at)}</span>
          </div>
        </>
      ) : (
        <div className="activityMeta">No activity yet - run profiling to get started.</div>
      )}
    </div>
  );
}

export default function SummaryCards({ summary, previousSummary }) {
  const s = summary || {};
  const prev = previousSummary || {};

  return (
    <div className="cards">
      <RecentActivityCard latest={s.latest_activity} />

      {NUMERIC_CARDS.map((c) => {
        const value = typeof s[c.key] === "number" ? s[c.key] : null;
        const prevValue = typeof prev[c.key] === "number" ? prev[c.key] : null;
        const delta = value !== null && prevValue !== null ? value - prevValue : 0;

        return (
          <div className={`card accent-${c.accent}`} key={c.key}>
            <div className="cardTop">
              <div className="label">{c.label}</div>
              <span className="cardIcon">{c.icon}</span>
            </div>
            <div className={`value ${c.accent === "green" ? "green" : c.accent === "amber" ? "amber" : ""}`}>
              {value !== null ? <AnimatedNumber value={value} /> : "-"}
            </div>
            {delta !== 0 && (
              <div className={`trend ${delta > 0 ? "up" : "down"}`}>
                {delta > 0 ? "\u2191" : "\u2193"} {Math.abs(delta)} since last check
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
