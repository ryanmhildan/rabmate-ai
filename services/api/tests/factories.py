"""Test data builders.

Builders commit, which (with join_transaction_mode="create_savepoint") only releases a SAVEPOINT:
the data survives failed API requests in the same test but the outer transaction is still rolled
back afterwards, so nothing leaks between tests.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.clients.models import Client, ClientType
from app.modules.identity.models import Membership, Organization, User
from app.modules.identity.permissions import Role
from app.modules.projects.models import Project, ProjectStatus, ProjectType

DEFAULT_PASSWORD = "rahasia-uji-123"
_seq = itertools.count(1)


def make_org(db: Session, name: str | None = None) -> Organization:
    org = Organization(name=name or f"PT Uji {next(_seq)}")
    db.add(org)
    db.commit()  # durable for the test; the outer transaction still rolls back
    return org


def make_user(
    db: Session,
    org: Organization | None,
    role: Role = Role.OWNER,
    *,
    email: str | None = None,
    password: str = DEFAULT_PASSWORD,
    active: bool = True,
    membership_active: bool = True,
) -> User:
    n = next(_seq)
    user = User(
        email=email or f"user{n}@contoh.co.id",
        full_name=f"Pengguna {n}",
        password_hash=hash_password(password),
        is_active=active,
    )
    db.add(user)
    db.commit()  # durable for the test; the outer transaction still rolls back
    if org is not None:
        db.add(
            Membership(
                organization_id=org.id, user_id=user.id, role=role, is_active=membership_active
            )
        )
        db.commit()  # durable for the test; the outer transaction still rolls back
    return user


def make_client(db: Session, org: Organization, **overrides: Any) -> Client:
    client = Client(
        organization_id=org.id,
        name=overrides.pop("name", f"Klien {next(_seq)}"),
        client_type=overrides.pop("client_type", ClientType.COMPANY),
        **overrides,
    )
    db.add(client)
    db.commit()  # durable for the test; the outer transaction still rolls back
    return client


def make_project(db: Session, org: Organization, **overrides: Any) -> Project:
    n = next(_seq)
    project = Project(
        organization_id=org.id,
        number=overrides.pop("number", f"T-{n:05d}"),
        name=overrides.pop("name", f"Proyek {n}"),
        project_type=overrides.pop("project_type", ProjectType.OTHER),
        status=overrides.pop("status", ProjectStatus.PROSPECT),
        **overrides,
    )
    db.add(project)
    db.commit()  # durable for the test; the outer transaction still rolls back
    return project


def login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD) -> Response:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    if response.status_code == 200:
        # What the web app's JS does: echo the readable CSRF cookie in a header.
        client.headers["X-CSRF-Token"] = client.cookies["rabmate_csrf"]
    return response


@dataclass
class Tenant:
    org: Organization
    owner: User
    browser: TestClient  # logged in as owner


LoginAs = Callable[[User], TestClient]
