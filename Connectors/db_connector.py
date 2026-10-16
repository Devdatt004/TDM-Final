"""
db_connector.py

This is our FIRST connector - the very beginning of the TDM pipeline.
Its only job: connect to a database, tell us what's inside it, and pull a sample of rows.

We're using SQLAlchemy, which is a library that lets Python talk to ANY database
(SQLite, Postgres, Oracle, SQL Server, MySQL...) using the SAME code. The only things
that differ per database are the DRIVER and how the connection URL is built - those
live in DB_TYPES below, so adding another database later means adding one entry.
"""

import importlib.util

from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import URL


# ------------------------------------------------------------------
# Supported database types (what the "Database type" chips in the UI list).
#
#   drivername     SQLAlchemy dialect+driver used to build the URL
#   driver_module  Python module that must be importable on the server
#   pip_package    what to `pip install` if it isn't (see requirements-connectors.txt)
#   default_port   pre-filled in the connection form
#   database_label what the "database" box is called for that product
#   service_name   Oracle passes the database as ?service_name=... not as /database
#   connect_args   makes a wrong host fail in ~10s instead of hanging
#
# NOTE: only SQLite (the demo hospital.db) has been exercised so far. The other
# four are built the standard SQLAlchemy way but still need a real server to be
# checked against.
# ------------------------------------------------------------------
DB_TYPES = {
    "sqlite": {
        "label": "SQLite (Demo)", "demo": True,
    },
    "oracle": {
        "label": "Oracle", "drivername": "oracle+oracledb", "driver_module": "oracledb",
        "pip_package": "oracledb", "default_port": 1521, "database_label": "Service name",
        "service_name": True, "connect_args": {"tcp_connect_timeout": 10},
    },
    "mssql": {
        "label": "MSSQL", "drivername": "mssql+pymssql", "driver_module": "pymssql",
        "pip_package": "pymssql", "default_port": 1433, "database_label": "Database",
        "connect_args": {"login_timeout": 10},
    },
    "postgresql": {
        "label": "PostgreSQL", "drivername": "postgresql+psycopg2", "driver_module": "psycopg2",
        "pip_package": "psycopg2-binary", "default_port": 5432, "database_label": "Database",
        "connect_args": {"connect_timeout": 10},
    },
    "mysql": {
        "label": "MySQL", "drivername": "mysql+pymysql", "driver_module": "pymysql",
        "pip_package": "pymysql", "default_port": 3306, "database_label": "Database",
        "connect_args": {"connect_timeout": 10},
    },
}

# Everything except the bundled demo database needs a host + credentials.
EXTERNAL_DB_TYPES = [t for t, cfg in DB_TYPES.items() if not cfg.get("demo")]


def driver_installed(db_type: str) -> bool:
    """Is the Python driver for this database installed on the server?"""
    module = DB_TYPES[db_type].get("driver_module")
    return module is None or importlib.util.find_spec(module) is not None


def build_connection_url(db_type: str, host: str, port, database: str, username: str, password: str) -> URL:
    """Build the SQLAlchemy URL. URL.create() escapes special characters in the
    password (@, :, / ...) - hand-built strings would break on those."""
    cfg = DB_TYPES[db_type]
    return URL.create(
        cfg["drivername"],
        username=username or None,
        password=password or None,
        host=host,
        port=int(port) if port else cfg["default_port"],
        database=None if cfg.get("service_name") else (database or None),
        query={"service_name": database} if cfg.get("service_name") and database else {},
    )


def _plain(value):
    """Make driver-specific values (Oracle LOBs, raw bytes) printable - the
    profiler and pattern analyzer work on text."""
    if hasattr(value, "read"):                       # Oracle CLOB/BLOB handle
        value = value.read()
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return bytes(value).hex()
    return value


from .base import BaseConnector


class DBConnector(BaseConnector):
    """
    A connector wraps three things any data source needs to support:
      1. connect()       -> open a connection to the source
      2. list_entities() -> what tables/entities exist inside it
      3. sample()        -> pull a small sample of rows from one entity
    """

    def __init__(self, connection_string, connect_args: dict | None = None):
        """
        connection_string examples:
          SQLite:   "sqlite:///hospital.db"
          Postgres: "postgresql://user:password@localhost:5432/tdm_platform"
        """
        self.connection_string = connection_string
        self.connect_args = connect_args or {}
        self.engine = None

    def connect(self):
        """Open the connection. Returns True if successful."""
        self.engine = create_engine(
            self.connection_string,
            connect_args=self.connect_args
        )

        with self.engine.connect() as conn:
            probe = (
                "SELECT 1 FROM DUAL"
                if self.engine.dialect.name == "oracle"
                else "SELECT 1"
            )
            conn.execute(text(probe))

        shown = self.connection_string
        if hasattr(shown, "render_as_string"):
            shown = shown.render_as_string(hide_password=True)

        print(f"Connected to: {shown}")
        return True

    def validate(self):
        """Validate that the configured source can be reached."""
        return self.connect()

    def close(self):
        """Release the connection pool."""
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None

    def list_table_names(self, schema: str | None = None):
        """Return table names."""
        return sorted(
            inspect(self.engine).get_table_names(schema=schema)
        )

    def list_documents(self):
        """BaseConnector-compatible discovery method."""
        return self.list_table_names()

    def describe_table(
        self,
        table_name: str,
        schema: str | None = None
    ):
        """Column names + native types for one table."""
        columns = inspect(self.engine).get_columns(
            table_name,
            schema=schema
        )

        return [
            {
                "name": c["name"],
                "type": str(c["type"])
            }
            for c in columns
        ]

    def describe(self, document_name: str):
        """BaseConnector-compatible describe method."""
        return self.describe_table(document_name)

    def list_entities(self):
        """
        Return a list of table names with column names and types.
        """
        inspector = inspect(self.engine)
        entities = []

        for table_name in inspector.get_table_names():
            columns = inspector.get_columns(table_name)

            entities.append({
                "table_name": table_name,
                "columns": [
                    {
                        "name": col["name"],
                        "type": str(col["type"])
                    }
                    for col in columns
                ]
            })

        return entities

    def sample(
        self,
        table_name: str,
        limit: int = 10,
        schema: str | None = None
    ):
        """
        Pull a sample of rows from a table.
        """
        table = Table(
            table_name,
            MetaData(),
            autoload_with=self.engine,
            schema=schema
        )

        with self.engine.connect() as conn:
            result = conn.execute(
                select(table).limit(limit)
            )

            columns = list(result.keys())

            rows = [
                dict(
                    zip(
                        columns,
                        (_plain(v) for v in row)
                    )
                )
                for row in result.fetchall()
            ]

        return rows

# ------------------------------------------------------------------
# This block only runs when you execute this file directly
# (i.e. "python db_connector.py") - it will NOT run if this file
# is imported elsewhere. This is a standard Python pattern for
# writing a quick self-test / demo alongside your actual code.
# ------------------------------------------------------------------
if __name__ == "__main__":
    # Point this at wherever your hospital.db file lives on your machine
    connector = DBConnector("sqlite:///hospital.db")
    connector.connect()

    print("\n--- Tables found ---")
    entities = connector.list_entities()
    for entity in entities:
        print(f"\nTable: {entity['table_name']}")
        for col in entity["columns"]:
            print(f"   - {col['name']} ({col['type']})")

    print("\n--- Sample rows from 'patients' ---")
    sample_rows = connector.sample("patients", limit=3)
    for row in sample_rows:
        print(row)
