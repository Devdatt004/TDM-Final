"""Online backup / verified restore of the SQLite metadata store (Step 16).

    python scripts/backup_metadata.py backup  [--dest DIR]      -> metadata_store-<UTC timestamp>.db[.enc]
    python scripts/backup_metadata.py restore BACKUP_FILE        -> replaces metadata_store.db

Backups use SQLite's online backup API (consistent while the API is running)
and are encrypted with the artifact keys when TDM_ARTIFACT_KEYS is set.
Restore verifies `PRAGMA integrity_check` and the Alembic revision before it
replaces anything, and keeps the replaced file as metadata_store.db.pre-restore.
Stop the API before restoring.
"""
import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from security import artifact_store  # noqa: E402


def db_path() -> str:
    return os.path.join(os.getenv("TDM_DATA_DIR", ROOT), "metadata_store.db")


def backup(dest: str = None) -> str:
    dest = dest or os.getenv("TDM_BACKUP_DIR", os.path.join(os.getenv("TDM_DATA_DIR", ROOT), "backups"))
    os.makedirs(dest, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = os.path.join(tmp, "snapshot.db")
        src = sqlite3.connect(db_path())
        out = sqlite3.connect(snapshot)
        try:
            src.backup(out)
        finally:
            out.close()
            src.close()
        with open(snapshot, "rb") as f:
            data = f.read()
    encrypted = artifact_store.encryption_enabled()
    target = os.path.join(dest, f"metadata_store-{stamp}.db" + (".enc" if encrypted else ""))
    artifact_store.write_bytes(target, data)
    return target


def _verify(path: str) -> str:
    con = sqlite3.connect(path)
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("Backup failed integrity_check - not restoring.")
        row = con.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else "unknown"
    finally:
        con.close()


def restore(backup_file: str) -> str:
    data = artifact_store.read_bytes(backup_file)
    target = db_path()
    with tempfile.TemporaryDirectory() as tmp:
        candidate = os.path.join(tmp, "candidate.db")
        with open(candidate, "wb") as f:
            f.write(data)
        revision = _verify(candidate)
        if os.path.exists(target):
            shutil.copy2(target, target + ".pre-restore")
        shutil.copy2(candidate, target)
    return revision


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--dest")
    r = sub.add_parser("restore")
    r.add_argument("backup_file")
    args = parser.parse_args()
    if args.cmd == "backup":
        print(f"Backup written: {backup(args.dest)}")
    else:
        print(f"Restored (alembic revision {restore(args.backup_file)}). Previous file kept as .pre-restore.")
