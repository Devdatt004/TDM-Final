
/**
 * src/api.js
 *
 * Centralized API wrapper for the FastAPI backend.
 * Handles the API base URL, development authentication headers,
 * and error responses.
 *
 * IMPORTANT:
 * Development headers are for local testing only.
 * Do not use them in production.
 */

export const API_BASE =
  import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function request(path, options = {}) {
  const headers = {
    "X-Dev-User": "developer",
    "X-Dev-Roles": "admin,steward",
    ...(options.headers || {}),
  };

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    let message = await res.text();

    try {
      const parsed = JSON.parse(message);
      const detail = parsed.detail;
      // FastAPI validation errors are arrays; release-gate rejections are objects.
      message = typeof detail === "string" ? detail
        : detail?.message || (detail ? JSON.stringify(detail) : message);
    } catch {
      // Keep the original response text if it is not JSON.
    }

    throw new Error(message || `Request failed: ${res.status}`);
  }

  return res.json();
}

export const api = {
  // Health and dashboard
  health: () => request("/api/v1/health"),
  getTables: () => request("/api/v1/tables"),
  getSummary: () => request("/api/v1/summary"),
  getRuns: () => request("/api/v1/runs"),

  // Source Registry (registered database sources)
  getRegisteredSources: () => request("/api/v1/sources"),

  getSourceTables: (sourceId) =>
    request(`/api/v1/sources/${encodeURIComponent(sourceId)}/tables`),

  // Analysis. sourceId is optional: when given, the table is profiled from
  // THAT registered source; without it the legacy demo/upload flow is used.
  runAnalysis: (table, sampleSize, sourceId = null) =>
    request(
      `/api/v1/analyze/${encodeURIComponent(table)}?sample_size=${sampleSize}` +
        (sourceId ? `&source_id=${encodeURIComponent(sourceId)}` : ""),
      { method: "POST" }
    ),

  getResults: (runId) => request(`/api/v1/results/${runId}`),

  getSchemaCatalog: (table, sourceId = null) =>
    request(
      `/api/v1/schema-catalog/${encodeURIComponent(table)}` +
        (sourceId ? `?source_id=${encodeURIComponent(sourceId)}` : "")
    ),

  getDataDictionary: () => request("/api/v1/data-dictionary"),

  // Synthetic data generation
  // purpose: "synthetic" (default) or "masking"
  maskTable: (table, rows, sourceId = null) =>
    request(
      `/api/v1/mask/${encodeURIComponent(table)}?rows=${rows}` +
        (sourceId ? `&source_id=${encodeURIComponent(sourceId)}` : ""),
      { method: "POST" }
    ),

  generateSynthetic: (table, rows, purpose = "synthetic", sourceId = null) =>
    request(
      `/api/v1/generate/${encodeURIComponent(table)}?rows=${rows}&purpose=${purpose}` +
        (sourceId ? `&source_id=${encodeURIComponent(sourceId)}` : ""),
      { method: "POST" }
    ),

  // File upload
  uploadFile: (filename, content) =>
    request("/api/v1/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, content }),
    }),

  // Human review workflow
  getReviews: (status = "PENDING", sourceId = null, tableName = null) => {
    const q = new URLSearchParams({ status });
    if (sourceId) q.set("source_id", sourceId);
    if (tableName) q.set("table_name", tableName);
    return request(`/api/v1/reviews?${q.toString()}`);
  },
  getReview: (reviewId) => request(`/api/v1/reviews/${reviewId}`),
  approveReview: (reviewId, payload) => request(`/api/v1/reviews/${reviewId}/approve`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }),
  rejectReview: (reviewId, payload) => request(`/api/v1/reviews/${reviewId}/reject`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  }),

  // Logs and audit
  getLogs: (activity, user) => {
    const q = new URLSearchParams();

    if (activity) q.set("activity", activity);
    if (user) q.set("user", user);

    const qs = q.toString();
    return request(`/api/v1/logs${qs ? `?${qs}` : ""}`);
  },

  getFiles: () => request("/api/v1/files"),
  getLogRetention: () => request("/api/v1/logs/retention"),
  getAudit: () => request("/api/v1/audit"),

  // Relationship suggestions
  getRelationshipSuggestions: (domain) =>
    request(`/api/v1/relationships/suggestions?domain=${encodeURIComponent(domain)}`),

  // Log management
  purgeLogs: () =>
    request("/api/v1/logs/purge", { method: "POST" }),

  // AI agent
  askAgent: (question, tableName) =>
    request("/api/v1/agent/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        table_name: tableName || null,
      }),
    }),

  // Data relationship validation (formerly "referential integrity")
  getDomains: () => request("/api/v1/domains"),

  getRelationships: (domain, refresh = false) =>
    request(`/api/v1/relationships?domain=${encodeURIComponent(domain)}${refresh ? "&refresh=true" : ""}`),

  refreshRelationships: (domain) =>
    request(`/api/v1/relationships/refresh?domain=${encodeURIComponent(domain)}`, { method: "POST" }),

  addRelationship: (rel) =>
    request("/api/v1/relationships", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rel),
    }),

  deleteRelationship: (id) =>
    request(`/api/v1/relationships/${id}`, { method: "DELETE" }),

  generateRelated: ({
    tables,
    rowCounts,
    ensureParentCoverage,
    seed,
  }) =>
    request("/api/v1/generate-related", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tables,
        row_counts: rowCounts,
        ensure_parent_coverage: ensureParentCoverage,
        seed: seed === "" || seed == null ? null : Number(seed),
      }),
    }),

  getIntegrityRuns: () => request("/api/v1/integrity/runs"),

  getIntegrityRun: (id) =>
    request(`/api/v1/integrity/runs/${id}`),

  downloadUrl: (datasetId) =>
    `${API_BASE}/api/v1/generate/download/${datasetId}`,

  // Database connectors
  getDbConnectors: () =>
    request("/api/v1/connectors/db-types"),

  connectDb: (payload) =>
    request("/api/v1/connectors/db/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  disconnectDb: () =>
    request("/api/v1/connectors/db/disconnect", { method: "POST" }),
};
