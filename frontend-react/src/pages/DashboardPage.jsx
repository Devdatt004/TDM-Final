import SummaryCards from "../components/SummaryCards.jsx";
import LiveStatus from "../components/LiveStatus.jsx";
import { statusTone } from "../statusTone.js";

// The feature tiles that used to live here were removed - they duplicated
// the top navigation tabs one-for-one (Profiling, Synthetic Data
// Generation, Masking, ...). The top nav is now the single, bigger place
// to switch tabs; this page stays focused on live numbers and activity.

export default function DashboardPage({ summary, previousSummary, runs, apiStatus, lastUpdated, onNavigate }) {
  const recentRuns = (runs || []).slice(0, 3);

  return (
    <>
      <div className="pageIntro">
        <div className="pageIntroTop">
          <h1>TDM Platform</h1>
          <LiveStatus status={apiStatus} lastUpdated={lastUpdated} />
        </div>
        <p className="subtitle">
          Test Data Management for sensitive data: discover, classify, mask, and generate synthetic
          substitutes for production data - without exposing the real thing.
        </p>
      </div>

      <SummaryCards summary={summary} previousSummary={previousSummary} />


      <section>
        <h2>Recent activity</h2>
        {recentRuns.length === 0 ? (
          <div className="emptyState">
            <div className="emptyIcon">{"\u{1F4CA}"}</div>
            <p>No activity yet</p>
            <span className="subtitle">Open Profiling to run one against a table or an uploaded file.</span>
            <button className="emptyCta" onClick={() => onNavigate("profiling")}>
              Run Profiling
            </button>
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Activity</th>
                <th>User</th>
                <th>Source</th>
                <th>Fields</th>
                <th>Status</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {recentRuns.map((r, i) => (
                <tr key={i}>
                  <td><span className="activityTag">{r.activity}</span></td>
                  <td><span className="userTag">{r.user ?? "-"}</span></td>
                  <td>{r.source}</td>
                  <td>{r.fields ?? "-"}</td>
                  <td>
                    <span className={`badge ${statusTone(r.status)}`}>{r.status}</span>
                  </td>
                  <td>{new Date(r.run_timestamp).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
