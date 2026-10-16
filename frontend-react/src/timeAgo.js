// "just now" / "42s ago" / "5m ago" / "3h ago" / "2d ago" from a Date or ISO string.
export function timeAgo(input) {
  if (!input) return "never";
  const date = input instanceof Date ? input : new Date(input);
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
