from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import CliError, create_admin, set_password
from app.core.config import Environment, Settings
from app.demo_seed import DemoSeedError, seed_demo
from app.modules.identity.models import Membership
from app.modules.identity.permissions import Role
from tests.factories import login


def test_create_admin_bootstraps_org_and_owner(db_session: Session, app_client: TestClient) -> None:
    org, user = create_admin(
        db_session,
        email="Pemilik@Contoh.co.id",
        full_name="Pemilik",
        organization_name="PT Baru",
        password="sandi-pemilik-123",
    )

    membership = db_session.execute(
        select(Membership).where(Membership.user_id == user.id)
    ).scalar_one()
    assert membership.role is Role.OWNER and membership.organization_id == org.id
    assert user.email == "pemilik@contoh.co.id"
    assert login(app_client, "pemilik@contoh.co.id", "sandi-pemilik-123").status_code == 200


def test_create_admin_refuses_existing_email(db_session: Session) -> None:
    kwargs = {"email": "dup@contoh.co.id", "full_name": "A", "organization_name": "B"}
    create_admin(db_session, password="sandi-panjang-1", **kwargs)
    with pytest.raises(CliError, match="sudah ada"):
        create_admin(db_session, password="sandi-panjang-2", **kwargs)


def test_create_admin_validates_input(db_session: Session) -> None:
    with pytest.raises(CliError):
        create_admin(
            db_session, email="bukan-email", full_name="A", organization_name="B", password="x" * 12
        )
    with pytest.raises(CliError):
        create_admin(
            db_session,
            email="a@contoh.co.id",
            full_name=" ",
            organization_name="B",
            password="x" * 12,
        )


def test_set_password_revokes_sessions(db_session: Session, app_client: TestClient) -> None:
    create_admin(
        db_session,
        email="lupa@contoh.co.id",
        full_name="Lupa",
        organization_name="PT Lupa",
        password="sandi-lama-123",
    )
    assert login(app_client, "lupa@contoh.co.id", "sandi-lama-123").status_code == 200

    set_password(db_session, email="lupa@contoh.co.id", password="sandi-baru-456")

    assert app_client.get("/api/v1/auth/me").status_code == 401
    assert login(app_client, "lupa@contoh.co.id", "sandi-baru-456").status_code == 200
    with pytest.raises(CliError, match="tidak ditemukan"):
        set_password(db_session, email="siapa@contoh.co.id", password="sandi-baru-456")


def test_seed_demo_creates_labelled_data_once(db_session: Session, settings: Settings) -> None:
    org = seed_demo(db_session, password="sandi-demo-123", settings=settings)

    assert "(Demo)" in org.name
    members = (
        db_session.execute(select(Membership).where(Membership.organization_id == org.id))
        .scalars()
        .all()
    )
    assert {m.role for m in members} == set(Role)
    assert all(m.user.email.endswith("@example.com") for m in members)
    with pytest.raises(DemoSeedError, match="sudah ada"):
        seed_demo(db_session, password="sandi-demo-123", settings=settings)


def test_seed_demo_refuses_production(db_session: Session, settings: Settings) -> None:
    production = settings.model_copy(update={"app_env": Environment.PRODUCTION})
    with pytest.raises(DemoSeedError, match="production"):
        seed_demo(db_session, password="sandi-demo-123", settings=production)
