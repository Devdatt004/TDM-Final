import { useEffect, useState } from "react";
import { api } from "../api.js";
import { DATA_RELATIONSHIP_VALIDATION } from "../featureNames.js";
import RelationshipGraphPanel from "../components/RelationshipGraphPanel.jsx";
import RelatedGenerationPanel from "../components/RelatedGenerationPanel.jsx";
import IntegrityReport from "../components/IntegrityReport.jsx";

export default function DataRelationshipValidationPage({ onGenerated }) {
  const [domains, setDomains] = useState([]);
  const [domain, setDomain] = useState("");
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [refreshMessage, setRefreshMessage] = useState("");

  async function load(refresh = false, key = domain) {
    if (!key) return;

    setBusy(true);
    setError("");
    setRefreshMessage("");

    try {
      const data = refresh
        ? await api.refreshRelationships(key)
        : await api.getRelationships(key);

      setOverview(data);

      if (refresh) {
        const tableCount = data.tables?.length ?? 0;
        const declaredCount = data.summary?.declared ?? 0;
        const undeclaredCount = data.summary?.undeclared ?? 0;

        setRefreshMessage(
          `Discovery completed successfully: ${tableCount} tables, ` +
          `${declaredCount} declared and ${undeclaredCount} undeclared relationships.`
        );
      }
    } catch (err) {
      setError(err.message || "An unexpected error occurred.");

      if (refresh) {
        setRefreshMessage("");
      }
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    api.getDomains()
      .then((d) => {
        setDomains(d.domains);
        setDomain(d.default);
      })
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    setOverview(null);
    setReport(null);
    setRefreshMessage("");
    load(false, domain);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domain]);

  function handleGenerated(result) {
    setReport(result);
    if (onGenerated) onGenerated();
  }

  return (
    <>
      <div className="pageIntro">
        <h1>{DATA_RELATIONSHIP_VALIDATION}</h1>

        <p className="subtitle">
          Relationship mapping &rarr; relationship graph &rarr; parent-first generation &rarr;
          identifier registry &rarr; validation &rarr; publish. Relationships come from two places:
          <strong> declared</strong> foreign keys in the database, and <strong>undeclared</strong> logical
          links that you confirm. Generated tables keep every relationship valid, so joins work and
          there are no orphan records.
        </p>

        {domains.length > 1 && (
          <div className="controls">
            <label>
              Source domain{" "}
              <select
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                disabled={busy}
              >
                {domains.map((d) => (
                  <option key={d.key} value={d.key}>
                    {d.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
      </div>

      {error && (
        <div className="infoBanner error">
          <span className="infoBannerIcon">&#9888;</span>
          <div>
            <strong>Could not load relationships</strong>
            <p>{error}</p>
          </div>
        </div>
      )}

      <RelationshipGraphPanel
        key={`graph-${domain}`}
        domain={domain}
        overview={overview}
        busy={busy}
        onRefresh={() => load(true)}
      />

      {refreshMessage && (
        <div className="infoBanner" role="status">
          <p>{refreshMessage}</p>
        </div>
      )}

      <RelatedGenerationPanel
        key={`gen-${domain}`}
        overview={overview}
        onGenerated={handleGenerated}
      />

      {report && <IntegrityReport report={report} />}
    </>
  );
}
