"""Clearly-labelled demo data for local development. Refuses to run in production.

Everything created here carries "(Demo)" in its name and uses @example.com addresses
(RFC 2606 reserved domain) so it can never be mistaken for, or reach, real people.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password
from app.modules.audit import service as audit
from app.modules.clients.models import Client, ClientType
from app.modules.identity.models import Membership, Organization, User
from app.modules.identity.permissions import ROLE_LABELS, Role
from app.modules.numbering.service import format_number, next_value
from app.modules.projects.models import (
    Project,
    ProjectMember,
    ProjectMemberRole,
    ProjectStatus,
    ProjectType,
)

DEMO_ORG_NAME = "PT Demo RABmate (Demo)"
DEMO_EMAIL_DOMAIN = "example.com"


class DemoSeedError(Exception):
    pass


def demo_email(role: Role) -> str:
    return f"demo.{role.value.replace('_', '-')}@{DEMO_EMAIL_DOMAIN}"


def seed_demo(db: Session, *, password: str, settings: Settings) -> Organization:
    if settings.is_production:
        raise DemoSeedError("Data demo tidak boleh dibuat di lingkungan production.")
    if db.execute(select(Organization).where(Organization.name == DEMO_ORG_NAME)).first():
        raise DemoSeedError(f"Organisasi '{DEMO_ORG_NAME}' sudah ada; seed tidak diulang.")
    taken = (
        db.execute(select(User.email).where(User.email.in_([demo_email(r) for r in Role])))
        .scalars()
        .all()
    )
    if taken:
        raise DemoSeedError(f"Email demo sudah dipakai: {', '.join(taken)}")

    org = Organization(name=DEMO_ORG_NAME, city="Jakarta")
    db.add(org)
    db.flush()

    password_hash = hash_password(password)
    users: dict[Role, User] = {}
    for role in Role:
        user = User(
            email=demo_email(role),
            full_name=f"Demo {ROLE_LABELS[role]}",
            password_hash=password_hash,
        )
        db.add(user)
        db.flush()
        db.add(Membership(organization_id=org.id, user_id=user.id, role=role))
        users[role] = user

    clients = [
        Client(
            organization_id=org.id,
            code="DEMO-01",
            name="Dinas Pekerjaan Umum (Demo)",
            client_type=ClientType.GOVERNMENT,
            city="Bandung",
        ),
        Client(
            organization_id=org.id,
            code="DEMO-02",
            name="PT Manufaktur Sejahtera (Demo)",
            client_type=ClientType.COMPANY,
            city="Bekasi",
            contact_person="Bagian Pengadaan",
        ),
        Client(
            organization_id=org.id,
            code="DEMO-03",
            name="Klinik Sehat Bersama (Demo)",
            client_type=ClientType.COMPANY,
            city="Depok",
        ),
    ]
    db.add_all(clients)
    db.flush()

    today = date.today()
    year = today.year
    specs = [
        (
            "Renovasi Gedung Arsip (Demo)",
            ProjectType.CONSTRUCTION,
            ProjectStatus.ACTIVE,
            clients[0],
            Decimal("1250000000.00"),
            {"luas_bangunan_m2": 850, "jumlah_lantai": 3},
            "Gedung Arsip, Bandung (Demo)",
            True,
        ),
        (
            "Fabrikasi Rangka Baja Gudang (Demo)",
            ProjectType.FABRICATION,
            ProjectStatus.PROSPECT,
            clients[1],
            Decimal("480000000.00"),
            {"material_utama": "WF 300", "berat_ton": 42},
            "Kawasan industri, Bekasi (Demo)",
            True,
        ),
        (
            "Pengadaan Laptop Kantor (Demo)",
            ProjectType.PROCUREMENT,
            ProjectStatus.ACTIVE,
            clients[1],
            Decimal("320000000.00"),
            {"jumlah_unit": 25},
            "Kantor pusat, Bekasi (Demo)",
            True,
        ),
        (
            "Sistem Antrian Klinik (Demo)",
            ProjectType.IT,
            ProjectStatus.COMPLETED,
            clients[2],
            Decimal("75000000.00"),
            {},
            "Depok (Demo)",
            False,
        ),
    ]
    for name, ptype, status, client, budget, attributes, location, taxed in specs:
        project = Project(
            organization_id=org.id,
            number=format_number("PRJ", year, next_value(db, org.id, "project", year)),
            name=name,
            project_type=ptype,
            status=status,
            client_id=client.id,
            budget_amount=budget,
            attributes=attributes,
            location=location,
            start_date=today,
            end_date=today + timedelta(days=90),
            currency="IDR",
            tax_label="PPN" if taxed else None,
            tax_rate_percent=Decimal("11") if taxed else None,
            description="Proyek contoh untuk mencoba RABmate (Demo).",
            owner_id=users[Role.PROJECT_MANAGER].id,
            created_by_id=users[Role.OWNER].id,
        )
        db.add(project)
        db.flush()
        db.add_all(
            [
                ProjectMember(
                    project_id=project.id,
                    user_id=users[Role.PROJECT_MANAGER].id,
                    role=ProjectMemberRole.LEAD,
                ),
                ProjectMember(
                    project_id=project.id,
                    user_id=users[Role.ESTIMATOR].id,
                    role=ProjectMemberRole.MEMBER,
                ),
            ]
        )

    audit.record(
        db,
        organization_id=org.id,
        actor_user_id=None,
        action="organization.bootstrap",
        entity_type="organization",
        entity_id=org.id,
        summary=f"{org.name} (seed demo)",
    )
    db.commit()
    return org
