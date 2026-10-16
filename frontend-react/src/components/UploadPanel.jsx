import { useRef, useState } from "react";
import { api } from "../api.js";

const MAX_BYTES = 5 * 1024 * 1024; // matches the backend's ~5 MB limit
const ALL_EXTENSIONS = [".csv", ".xml", ".txt"];

// Upload a CSV / XML / text file as a data source. The browser reads the
// file and sends its text to POST /upload; on success the file appears in
// every source dropdown and is selected, ready to profile.
//
// `accept` restricts the file picker/drop to one extension (e.g. ".csv") -
// used when the connector's "Flat File" format has already been chosen.
// Leaving it unset accepts any of the three supported types.
export default function UploadPanel({ onUploaded, accept, typeLabel }) {
  const inputRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState(null); // { tone: "ok" | "error", text }

  const extensions = accept ? [accept] : ALL_EXTENSIONS;
  const formatWord = typeLabel ? `a .${accept.replace(".", "")} (${typeLabel})` : "a .csv, .xml or .txt";

  async function handleFile(file) {
    if (!file) return;
    const lower = file.name.toLowerCase();
    if (!extensions.some((ext) => lower.endsWith(ext))) {
      setMessage({ tone: "error", text: `Unsupported file type. Choose ${formatWord} file.` });
      return;
    }
    if (file.size > MAX_BYTES) {
      setMessage({ tone: "error", text: "File is larger than 5 MB." });
      return;
    }

    setBusy(true);
    setMessage(null);
    try {
      const content = await file.text();
      const result = await api.uploadFile(file.name, content);
      setMessage({
        tone: "ok",
        text: `${result.replaced ? "Replaced" : "Uploaded"} ${result.name} — ${result.rows} rows, ${result.columns} columns. Selected as the source.`,
      });
      onUploaded(result.name);
    } catch (err) {
      setMessage({ tone: "error", text: err.message });
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div>
      <div
        className={`dropZone ${dragging ? "dragging" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFile(e.dataTransfer.files[0]);
        }}
      >
        <div className="dropText">
          <strong>Drag a file here</strong> or choose one — {formatWord} (max 5 MB)
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={extensions.join(",")}
          style={{ display: "none" }}
          onChange={(e) => handleFile(e.target.files[0])}
        />
        <button onClick={() => inputRef.current && inputRef.current.click()} disabled={busy}>
          {busy ? "Uploading..." : "Choose file"}
        </button>
      </div>
      {message && (
        <div className={`uploadMsg ${message.tone}`}>{message.text}</div>
      )}
    </div>
  );
}
