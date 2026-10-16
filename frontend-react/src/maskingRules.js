// src/maskingRules.js
//
// The backend does not yet have a dedicated masking engine (see TDD
// roadmap) - but the Masking tab still needs to show something useful
// today: a recommended masking TECHNIQUE per column, derived from the
// same Data Dictionary sensitivity_level the Schema Catalog and Query
// Agent already reuse. This keeps the recommendation consistent with
// the rest of the platform instead of inventing a separate rulebook.
//
// Once a real masking engine exists behind the API, this function is
// the one place that needs to change to call it instead.

export function recommendMaskingTechnique(sensitivityLevel, patternType) {
  const level = (sensitivityLevel || "").toLowerCase();

  if (level.includes("high")) {
    return { technique: "Full masking / tokenization", tone: "high" };
  }
  if (level.includes("medium")) {
    return { technique: "Partial masking (keep last 4 characters)", tone: "medium" };
  }
  if (patternType === "DATE") {
    return { technique: "Date shifting (preserve interval, not exact date)", tone: "medium" };
  }
  if (level.includes("low")) {
    return { technique: "Generalization (e.g. truncate ZIP to 3 digits)", tone: "low" };
  }
  if (level.includes("review") || level.includes("potentially")) {
    return { technique: "Manual review before masking", tone: "review" };
  }
  if (level.includes("non-sensitive")) {
    return { technique: "No masking required", tone: "none" };
  }
  return { technique: "Manual review before masking", tone: "review" };
}
