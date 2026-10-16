// Maps an activity status string to a badge color class
// (.badge.high = green, .badge.review = amber, .badge.running = blue).
export function statusTone(status) {
  const s = (status || "").toLowerCase();
  if (s === "running") return "running";
  if (s.includes("fail") || s.includes("error") || s === "interrupted") return "review";
  return "high";
}
