from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

from app.db.models import Base

API_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    return config


def test_single_migration_head() -> None:
    script = ScriptDirectory.from_config(_alembic_config("postgresql+psycopg://unused"))
    assert len(script.get_heads()) == 1, "migration history must not branch"


def test_upgrade_downgrade_roundtrip_and_no_model_drift(db_engine: Engine) -> None:
    url = db_engine.url.render_as_string(hide_password=False)
    config = _alembic_config(url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    assert set(inspect(db_engine).get_table_names()) <= {"alembic_version"}

    command.upgrade(config, "head")
    with db_engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], f"models and migrations are out of sync: {diff}"


def test_every_migration_steps_down_and_up_again(db_engine: Engine) -> None:
    """Each revision's downgrade works on its own, not only as part of a full teardown."""
    url = db_engine.url.render_as_string(hide_password=False)
    config = _alembic_config(url)
    script = ScriptDirectory.from_config(config)
    revisions = [rev.revision for rev in reversed(list(script.walk_revisions()))]
    assert len(revisions) >= 9

    command.downgrade(config, "base")
    try:
        for revision in revisions:
            command.upgrade(config, revision)
            command.downgrade(config, "-1")
            command.upgrade(config, revision)
    finally:
        command.upgrade(config, "head")
    with db_engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == revisions[-1]
