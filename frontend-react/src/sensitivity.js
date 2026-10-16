// src/sensitivity.js
//
// Single place that decides which color a sensitivity_level string
// (e.g. "PHI - High", "PII - Medium", "Non-sensitive (context-dependent)")
// should render as. Both SchemaCatalogTable and DataDictionaryTable use
// this so a "High" badge always looks the same everywhere, instead of
// each table guessing its own color logic.

export function sensitivityTone(level) {
  const l = (level || "").toLowerCase();
  if (l.includes("high")) return "high";
  if (l.includes("medium")) return "medium";
  if (l.includes("low")) return "low";
  if (l.includes("review") || l.includes("potentially")) return "review";
  if (l.includes("non-sensitive")) return "none";
  return "";
}
