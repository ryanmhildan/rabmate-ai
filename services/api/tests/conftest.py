from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Environment, Settings, get_settings
from app.core.security import set_password_hasher
from app.db.session import build_engine, get_db
from app.main import create_app
from app.modules.identity.models import User
from app.modules.identity.permissions import Role
from tests.factories import LoginAs, Tenant, login, make_org, make_user

API_ROOT = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # Tag every test whose fixture closure reaches PostgreSQL, so `-m "not db"` is DB-free.
    for item in items:
        if "db_engine" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.db)


@pytest.fixture(scope="session", autouse=True)
def fast_password_hashing() -> None:
    # Argon2id with production parameters costs ~50-100 ms per hash; tests create many users.
    set_password_hasher(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))


def _test_settings() -> Settings:
    base = get_settings()
    return base.model_copy(
        update={
            "app_env": Environment.TEST,
            "database_url": base.test_database_url,
            "log_level": "WARNING",
            # Tests never depend on a developer's local AI setup in .env; AI tests opt in.
            "ai_enabled": False,
            "hermes_api_key": SecretStr(""),
        }
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    return _test_settings()


def alembic_config(url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    return config


def _ensure_test_database(url: str) -> None:
    """Create the test database if missing. Refuses any name that is not *_test."""
    parsed = make_url(url)
    db_name = parsed.database or ""
    if not db_name.endswith("_test"):
        raise RuntimeError(
            f"Refusing to run DB tests against {db_name!r}: TEST_DATABASE_URL must end in _test."
        )
    admin = parsed.set(drivername="postgresql", database="postgres")
    conninfo = admin.render_as_string(hide_password=False)
    try:
        with psycopg.connect(conninfo, autocommit=True, connect_timeout=5) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)
            ).fetchone()
            if not exists:
                conn.execute(f'CREATE DATABASE "{db_name}"')
    except psycopg.OperationalError as exc:
        pytest.fail(
            "PostgreSQL test database unreachable. Start it with `docker compose up -d db` "
            f"or deselect DB tests with -m 'not db'. ({type(exc).__name__})",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def db_engine(settings: Settings) -> Iterator[Engine]:
    url = settings.database_url.get_secret_value()
    _ensure_test_database(url)
    command.upgrade(alembic_config(url), "head")
    engine = build_engine(url, pool_size=2)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """Session inside an outer transaction that is always rolled back.

    Application code may call commit()/rollback(); with create_savepoint those only act on a
    nested SAVEPOINT, so nothing a test writes survives the test.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def app(settings: Settings, db_session: Session) -> FastAPI:
    application = create_app(settings)

    def shared_session() -> Iterator[Session]:
        # Mirrors get_db: a failed request must not leave pending changes for the next one.
        try:
            yield db_session
        except Exception:
            db_session.rollback()
            raise

    application.dependency_overrides[get_db] = shared_session
    return application


@pytest.fixture
def client_factory(app: FastAPI) -> Iterator[Callable[[], TestClient]]:
    """Independent browsers (separate cookie jars) against the same app and DB session."""
    clients: list[TestClient] = []

    def make() -> TestClient:
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def app_client(client_factory: Callable[[], TestClient]) -> TestClient:
    return client_factory()


@pytest.fixture
def bare_client(settings: Settings) -> Iterator[TestClient]:
    """Client without a database; for tests that must not depend on PostgreSQL."""
    application = create_app(settings)
    with TestClient(application) as client:
        yield client


# --------------------------------------------------------------------------- tenants & logins


@pytest.fixture
def login_as(client_factory: Callable[[], TestClient]) -> LoginAs:
    def _login(user: User) -> TestClient:
        browser = client_factory()
        response = login(browser, user.email)
        assert response.status_code == 200, response.text
        return browser

    return _login


@pytest.fixture
def tenant(db_session: Session, login_as: LoginAs) -> Tenant:
    org = make_org(db_session, "PT Alfa Konstruksi")
    owner = make_user(db_session, org, Role.OWNER)
    return Tenant(org=org, owner=owner, browser=login_as(owner))


@pytest.fixture
def other_tenant(db_session: Session, login_as: LoginAs) -> Tenant:
    org = make_org(db_session, "CV Beta Teknik")
    owner = make_user(db_session, org, Role.OWNER)
    return Tenant(org=org, owner=owner, browser=login_as(owner))
