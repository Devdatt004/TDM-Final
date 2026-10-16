"""
file_connector.py

Second Data Source Connector (after db_connector.py): turns an uploaded
CSV, XML, or plain-text file into the SAME shape the DB connector's
sample() returns - a list of row dictionaries - so the Pattern Analyzer,
Profiler, Schema Catalog, Synthetic Generation and Masking all work on a
file exactly as they do on a database table.

Supported:
  .csv  - delimiter auto-detected (, ; tab |), first row = header
  .xml  - the repeating element under the root is treated as one record;
          attributes and (nested) child elements become columns
  .txt  - if every line splits on the same delimiter it is read as a
          table (first line = header); otherwise each non-empty line
          becomes one row in a single "line" column

Only the standard library is used (no new dependencies).
"""

import csv
import io
import re
import xml.etree.ElementTree as ET
from collections import Counter

MAX_UPLOAD_CHARS = 5_000_000      # ~5 MB of text
MAX_COLUMNS = 200
ALLOWED_EXTENSIONS = {".csv": "CSV", ".xml": "XML", ".txt": "Text"}


def file_type_for(filename: str):
    """Return 'CSV' / 'XML' / 'Text' for a filename, or None if unsupported."""
    lower = (filename or "").lower()
    for ext, label in ALLOWED_EXTENSIONS.items():
        if lower.endswith(ext):
            return label
    return None


def safe_filename(filename: str) -> str:
    """Strip any path and replace unusual characters, so an uploaded name
    can never write outside the uploads folder."""
    base = (filename or "").replace("\\", "/").split("/")[-1].strip()
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base.lstrip(".") or "upload"


def _clean_headers(raw_headers):
    """Blank -> column_N, duplicates -> name_2, name_3 ..."""
    seen = Counter()
    headers = []
    for i, h in enumerate(raw_headers):
        name = (h or "").strip() or f"column_{i + 1}"
        seen[name] += 1
        headers.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return headers


def _rows_from_table(table):
    """table = list of lists (first row = header) -> list of dicts.
    Empty cells become None so null% is computed correctly."""
    if not table:
        raise ValueError("The file is empty.")
    headers = _clean_headers(table[0])[:MAX_COLUMNS]
    rows = []
    for raw in table[1:]:
        if not any((c or "").strip() for c in raw):
            continue  # skip fully blank lines
        padded = list(raw) + [""] * (len(headers) - len(raw))
        rows.append({
            h: (padded[i].strip() if padded[i].strip() != "" else None)
            for i, h in enumerate(headers)
        })
    if not rows:
        raise ValueError("The file has a header row but no data rows.")
    return headers, rows


def _parse_csv(text):
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return _rows_from_table(list(csv.reader(io.StringIO(text), dialect)))


def _parse_txt(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("The file is empty.")

    # Is it really a delimited table? Every sampled line must contain the
    # same (non-zero) number of one delimiter.
    for delim in (",", "\t", "|", ";"):
        counts = {ln.count(delim) for ln in lines[:50]}
        if len(counts) == 1 and counts.pop() >= 1:
            table = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
            return _rows_from_table(table)

    # Otherwise: free text, one row per line.
    return ["line"], [{"line": ln.strip()} for ln in lines]


def _flatten(el, prefix=""):
    """Flatten one XML record into {column: text}. Attributes use their own
    name, nested elements are joined with underscores."""
    out = {}
    for k, v in el.attrib.items():
        out[f"{prefix}{k}"] = v
    children = list(el)
    if not children:
        text = (el.text or "").strip()
        if text:
            out[prefix.rstrip("_") or el.tag] = text
        return out
    for child in children:
        out.update(_flatten(child, f"{prefix}{child.tag}_" if list(child) else f"{prefix}{child.tag}"))
    return out


def _find_records(root):
    """Breadth-first search for the first element whose children include a
    tag repeated 2+ times - that repeated tag is the 'record'."""
    queue = [root]
    while queue:
        node = queue.pop(0)
        counts = Counter(child.tag for child in node)
        if counts:
            tag, n = counts.most_common(1)[0]
            if n >= 2:
                return [c for c in node if c.tag == tag]
        queue.extend(list(node))
    # No repetition: treat the root's children as a single record.
    return [root] if len(root) else []


def _parse_xml(text):
    # ElementTree expands entities, which allows "billion laughs" style
    # attacks. A data file has no legitimate need for a DTD, so refuse it.
    head = text[:2000].upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in text.upper():
        raise ValueError("XML files with a DOCTYPE/ENTITY declaration are not accepted.")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"Could not parse XML: {e}")

    records = _find_records(root)
    if not records:
        raise ValueError("No repeating records found in the XML file.")

    flat = [_flatten(r) for r in records]
    headers = []
    for rec in flat:
        for k in rec:
            if k not in headers and len(headers) < MAX_COLUMNS:
                headers.append(k)
    if not headers:
        raise ValueError("The XML records contain no readable values.")
    rows = [{h: rec.get(h) for h in headers} for rec in flat]
    return headers, rows


def _infer_type(values):
    """Very small type inference for the Schema Catalog."""
    vals = [v for v in values if v is not None]
    if not vals:
        return "TEXT"
    try:
        for v in vals:
            int(v)
        return "INTEGER"
    except ValueError:
        pass
    try:
        for v in vals:
            float(v)
        return "FLOAT"
    except ValueError:
        return "TEXT"


def parse_file(filename: str, text: str) -> dict:
    """
    Parse an uploaded file's text. Returns:
      { "file_type": "CSV"|"XML"|"Text",
        "columns": [{"name":..., "type":...}, ...],
        "rows": [ {col: value, ...}, ... ] }
    Raises ValueError with a user-readable message on any problem.
    """
    file_type = file_type_for(filename)
    if file_type is None:
        raise ValueError("Unsupported file type. Upload a .csv, .xml or .txt file.")
    if len(text) > MAX_UPLOAD_CHARS:
        raise ValueError("File is too large (limit is about 5 MB).")
    if text.startswith("\ufeff"):
        text = text[1:]  # strip a UTF-8 BOM (common in Excel CSV exports)

    if file_type == "CSV":
        headers, rows = _parse_csv(text)
    elif file_type == "XML":
        headers, rows = _parse_xml(text)
    else:
        headers, rows = _parse_txt(text)

    columns = [{"name": h, "type": _infer_type([r[h] for r in rows])} for h in headers]
    return {"file_type": file_type, "columns": columns, "rows": rows}


if __name__ == "__main__":
    demo = "name,ssn\nAnn,123-45-6789\nBob,987-65-4321\n"
    print(parse_file("demo.csv", demo))
