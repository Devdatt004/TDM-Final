import { statusTone } from "../statusTone.js";

export default function RecentRunsTable({ runs }) {
  return (
    <section>
      <h2>Recent runs</h2>
      <div className="previewWrap">
        <table>
          <thead>
            <tr>
              <th>Activity</th>
              <th>User</th>
              <th>Source</th>
              <th>Type</th>
              <th>Fields</th>
              <th>Status</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {!runs || runs.length === 0 ? (
              <tr><td colSpan={7}>No runs yet.</td></tr>
            ) : (
              runs.map((r, i) => (
                <tr key={r.log_id ?? i}>
                  <td><span className="activityTag">{r.activity}</span></td>
                  <td><span className="userTag">{r.user ?? "-"}</span></td>
                  <td>{r.source}</td>
                  <td>{r.type}</td>
                  <td>{r.fields ?? "-"}</td>
                  <td><span className={`badge ${statusTone(r.status)}`}>{r.status}</span></td>
                  <td>{new Date(r.run_timestamp).toLocaleString()}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
