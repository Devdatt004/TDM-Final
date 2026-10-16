import { useEffect, useState } from "react";
import { api } from "../api.js";
import SourceSelect from "../components/SourceSelect.jsx";
import SchemaCatalogTable from "../components/SchemaCatalogTable.jsx";
import DataDictionaryTable from "../components/DataDictionaryTable.jsx";

export default function KnowledgeBasePage({ sources, selectedTable, onSelectTable, selectedSourceId = null, selectedSourceName = "", catalogTable, catalogColumns, catalogError }) {
  const [dictionary, setDictionary] = useState([]);
  const [dictError, setDictError] = useState("");

  useEffect(() => {
    api.getDataDictionary().then(setDictionary).catch((err) => setDictError(err.message));
  }, []);

  return (
    <>
      <div className="pageIntro">
        <h1>Knowledge Base</h1>
        <p className="subtitle">
          Schema Catalog (native types from the source, per table) and the Data Dictionary
          (business glossary, per pattern type) - the Metadata &amp; Knowledge layer every other
          feature reuses.
        </p>
      </div>

      <div className="controls">
        <SourceSelect
          sources={sources}
          value={selectedSourceId ? "" : selectedTable}
          onChange={onSelectTable}
          placeholder={selectedSourceId ? "Registered source selected..." : ""}
        />
        {selectedSourceId && selectedTable && (
          <span className="subtitle" style={{ margin: 0 }}>
            Showing <strong>{selectedTable}</strong> from registered source{" "}
            <strong>{selectedSourceName || selectedSourceId}</strong> (change it on the Profiling tab).
          </span>
        )}
      </div>

      <SchemaCatalogTable tableName={catalogTable} columns={catalogColumns} error={catalogError} />

      <DataDictionaryTable entries={dictionary} error={dictError} />
    </>
  );
}
