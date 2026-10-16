"""Step 17: the Alembic chain is the schema source of truth.

* A fresh database upgrades to a single head.
* The migrated schema matches the ORM models (no drift: a model change without
  a migration, or the reverse, fails here).
* Every migration downgrades cleanly and re-applies.
"""
import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from metadata_store.db import Base
from metadata_store import models  # noqa: F401  (registers every table)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config(connection):
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    cfg.attributes["connection"] = connection
    return cfg


@pytest.fixture()
def connection(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migrate.db'}")
    with engine.connect() as conn:
        yield conn
    engine.dispose()


def test_single_head():
    script = ScriptDirectory.from_config(_config(None))
    assert len(script.get_heads()) == 1, script.get_heads()


def _ignored(diff):
    """Differences SQLite cannot express or that are deliberately not migrated."""
    kind = diff[0] if isinstance(diff, tuple) else diff[0][0]
    # SQLite reports no server-side type changes reliably for these; keep the check structural.
    return kind in {"modify_type", "modify_default", "modify_comment"}


def test_fresh_upgrade_matches_models(connection):
    command.upgrade(_config(connection), "head")
    connection.commit()
    ctx = MigrationContext.configure(connection)
    diffs = [d for d in compare_metadata(ctx, Base.metadata) if not _ignored(d)]
    assert diffs == [], "Models and migrations disagree:\n" + "\n".join(map(str, diffs))


def test_full_downgrade_and_reupgrade(connection):
    cfg = _config(connection)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    connection.commit()
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert MigrationContext.configure(connection).get_current_revision() == head
