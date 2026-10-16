import VerdictBadge from "./VerdictBadge.jsx";

export default function ColumnDetailsTable({ tableName, columns }) {
  return (
    <section>
      <h2>{tableName ? `Column details — ${tableName}` : "Column details"}</h2>
      <table>
        <thead>
          <tr>
            <th>Column</th>
            <th>Pattern Type</th>
            <th>Pattern</th>
            <th>Match %</th>
            <th>Null %</th>
            <th>Distinct</th>
            <th>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {!columns || columns.length === 0 ? (
            <tr><td colSpan={7}>Run an analysis to see results.</td></tr>
          ) : (
            columns.map((c) => (
              <tr key={c.column_name}>
                <td>{c.column_name}</td>
                <td>{c.pattern_type}</td>
                <td><code>{c.pattern}</code></td>
                <td>{c.match_percentage}%</td>
                <td>{c.null_percent}%</td>
                <td>{c.distinct_count}</td>
                <td><VerdictBadge verdict={c.verdict} /></td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}
