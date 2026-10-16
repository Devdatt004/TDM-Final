import os
from sqlalchemy.orm import Session
from Connectors.db_connector import DBConnector, DB_TYPES, EXTERNAL_DB_TYPES
from Connectors import connection_registry
from Connectors.file_connector import parse_file
from metadata_store.models import UploadedSource
from sample_domains import registry as domains

SYSTEM_USER = "system"
SOURCE_DB_CONNECTION_STRING = domains.connection_string(domains.DEFAULT_DOMAIN)   # kept for older imports

def _external_db_type(name: str):
    prefix = name.split(".", 1)[0] if "." in name else None
    return prefix if prefix in EXTERNAL_DB_TYPES else None

def get_source_kind(db: Session, name: str, username: str = None):
    upload = db.query(UploadedSource).filter(UploadedSource.name == name).first()
    if upload:
        return f"{upload.file_type} File", upload
    db_type = _external_db_type(name)
    if db_type:
        info = connection_registry.get_active(username)
        label = info["label"] if info and info["db_type"] == db_type else DB_TYPES[db_type]["label"]
        return f"{label} Table", None
    return "DB Table", None

def get_external_table(username: str, name: str):
    db_type = _external_db_type(name)
    if not db_type:
        return None, None
    info = connection_registry.get_active(username)
    if info is None or info["db_type"] != db_type:
        raise ValueError(
            f"Not connected to {DB_TYPES[db_type]['label']} any more - open the Data Source "
            f"Connector, choose {DB_TYPES[db_type]['label']} and click Connect again.")
    return info, name[len(db_type) + 1:]

def list_all_sources(db: Session, username: str = SYSTEM_USER):
    uploads = db.query(UploadedSource).order_by(UploadedSource.uploaded_at.desc()).all()
    sources = []
    for entry in domains.available_domains():          # every built-in domain: healthcare, banking, ...
        connector = DBConnector(domains.connection_string(entry["key"]))
        connector.connect()
        sources += [{"name": e["table_name"], "kind": "table", "domain": entry["key"], "domain_label": entry["label"]}
                    for e in connector.list_entities()]
    info = connection_registry.get_active(username)
    if info:
        sources += [{"name": f"{info['db_type']}.{t}", "kind": "external",
                     "db_type": info["db_type"], "table": t} for t in info["tables"]]
    sources += [{"name": u.name, "kind": "file", "file_type": u.file_type} for u in uploads]
    return sources

def load_source_data(db: Session, name: str, limit: int, username: str = None):
    _, upload = get_source_kind(db, name, username)
    if upload:
        with open(upload.file_path, encoding="utf-8", newline="") as f:
            parsed = parse_file(upload.name, f.read())
        return parsed["rows"][:limit], parsed["columns"]

    info, table = get_external_table(username, name)
    if info:
        connector = DBConnector(info["url"], connect_args=info["connect_args"])
        try:
            connector.connect()
            rows = connector.sample(table, limit=limit, schema=info["schema"])
            return rows, connector.describe_table(table, schema=info["schema"])
        finally:
            connector.close()

    connector = DBConnector(domains.connection_string(domains.domain_of_table(name) or domains.DEFAULT_DOMAIN))
    connector.connect()
    rows = connector.sample(name, limit=limit)
    entities = connector.list_entities()
    entity = next((e for e in entities if e["table_name"] == name), None)
    return rows, (entity["columns"] if entity else [])
