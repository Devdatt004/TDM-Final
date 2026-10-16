import { useEffect, useState } from "react";

function timeAgo(date) {
  if (!date) return "never";
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ago`;
}

// Small pill shown on the dashboard: a pulsing dot for connection status
// plus a "last updated Xs ago" label that ticks on its own, independent of
// whether new data has actually arrived yet.
export default function LiveStatus({ status, lastUpdated }) {
  const [, forceTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const tone =
    status === "online" ? "online" : status === "offline" ? "offline" : "checking";
  const label =
    status === "online" ? "Live" : status === "offline" ? "Disconnected" : "Connecting…";

  return (
    <div className={`liveStatus ${tone}`}>
      <span className="liveDot" />
      <span className="liveLabel">{label}</span>
      <span className="liveSep">•</span>
      <span className="liveUpdated">Updated {timeAgo(lastUpdated)}</span>
    </div>
  );
}
