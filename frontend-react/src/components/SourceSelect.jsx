// One dropdown used by every tab. Groups database tables and uploaded
// files so it's obvious where each source comes from.
export default function SourceSelect({ sources, value, onChange, placeholder = "" }) {
  const tables = sources.filter((s) => s.kind === "table");
  // one group per industry domain (Healthcare, Banking & Financial Services, ...)
  const tableGroups = {};
  for (const s of tables) (tableGroups[s.domain_label || "Database tables"] ||= []).push(s);
  const external = sources.filter((s) => s.kind === "external");
  const files = sources.filter((s) => s.kind === "file");

  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {placeholder && <option value="" disabled>{placeholder}</option>}
      {sources.length === 0 && !placeholder && <option>Loading sources...</option>}
      {Object.entries(tableGroups).map(([label, list]) => (
        <optgroup key={label} label={label === "Database tables" ? label : `${label} tables`}>
          {list.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </optgroup>
      ))}
      {external.length > 0 && (
        <optgroup label="Connected database tables">
          {external.map((s) => <option key={s.name} value={s.name}>{s.table || s.name}</option>)}
        </optgroup>
      )}
      {files.length > 0 && (
        <optgroup label="Uploaded files">
          {files.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </optgroup>
      )}
    </select>
  );
}
