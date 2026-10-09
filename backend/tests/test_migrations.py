"""The Alembic chain builds exactly the schema the models describe, so a
fresh production database gets every table and column. Runs the real
migrations into a throwaway SQLite file."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

BACKEND = Path(__file__).resolve().parents[1]


def test_upgrade_head_matches_the_models(tmp_path):
    db_file = tmp_path / "migrated.db"
    env = {"DATABASE_URL": f"sqlite+aiosqlite:///{db_file}", "PATH": "/usr/bin:/bin", "PYTHONPATH": str(BACKEND)}
    run = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-2000:]

    import db.models  # noqa: F401
    from db.base import Base

    engine = sa.create_engine(f"sqlite:///{db_file}")
    insp = sa.inspect(engine)
    tables = set(insp.get_table_names()) - {"alembic_version"}
    missing_tables = {t.name for t in Base.metadata.sorted_tables} - tables
    assert not missing_tables, f"tables in the models but not in the migrations: {sorted(missing_tables)}"
    drift = {}
    for table in Base.metadata.sorted_tables:
        have = {c["name"] for c in insp.get_columns(table.name)}
        want = {c.name for c in table.columns}
        if want - have:
            drift[table.name] = sorted(want - have)
    assert not drift, f"columns in the models but not in the migrations: {drift}"


def test_sync_missing_columns_default_is_valid_on_postgres_too():
    """A bare 1/0 integer literal is not a valid default for a Postgres BOOLEAN
    column (Postgres raised DatatypeMismatchError in production), even though
    SQLite accepts it. TRUE/FALSE keywords are valid on both."""
    import sqlalchemy as sa_mod
    import sys as sys_mod
    sys_mod.path.insert(0, str(BACKEND))
    from scripts.init_db import _sql_default

    col = sa_mod.Column("flag", sa_mod.Boolean, default=True)
    assert _sql_default(col).strip() == "DEFAULT TRUE"
    col = sa_mod.Column("flag", sa_mod.Boolean, default=False)
    assert _sql_default(col).strip() == "DEFAULT FALSE"


def test_audit_rows_cannot_be_changed_or_deleted(tmp_path):
    db_file = tmp_path / "migrated.db"
    env = {"DATABASE_URL": f"sqlite+aiosqlite:///{db_file}", "PATH": "/usr/bin:/bin", "PYTHONPATH": str(BACKEND)}
    assert subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env,
                          capture_output=True).returncode == 0
    engine = sa.create_engine(f"sqlite:///{db_file}")
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO organizations (id, name, slug) VALUES ('o', 'O', 'o')"))
        c.execute(sa.text("INSERT INTO audit_log (org_id, actor, action, entity_type) VALUES ('o', 'u', 'create', 'agent')"))
    for stmt in ("UPDATE audit_log SET actor = 'x'", "DELETE FROM audit_log"):
        try:
            with engine.begin() as c:
                c.execute(sa.text(stmt))
        except sa.exc.DatabaseError as exc:
            assert "audit_log rows cannot" in str(exc)
        else:
            raise AssertionError(f"{stmt} was allowed")
