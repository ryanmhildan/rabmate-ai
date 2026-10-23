"""Administrative commands.

    python -m app.cli create-admin --email a@contoh.co.id --name "Nama" --organization "PT X"
    python -m app.cli set-password --email a@contoh.co.id

Passwords are read from an interactive prompt (or stdin with --password-stdin), never from
command-line arguments, so they do not end up in shell history.
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from collections.abc import Sequence

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT, get_settings
from app.core.security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, hash_password
from app.db.session import get_sessionmaker
from app.demo_seed import DemoSeedError, demo_email, seed_demo
from app.modules.audit import service as audit
from app.modules.identity.models import Membership, Organization, User
from app.modules.identity.permissions import Role
from app.modules.identity.schemas import NormalizedEmail
from app.modules.identity.sessions import revoke_user_sessions


class CliError(Exception):
    pass


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Kata sandi: ")
        if getpass.getpass("Ulangi kata sandi: ") != password:
            raise CliError("Kata sandi tidak sama.")
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise CliError(f"Kata sandi harus {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} karakter.")
    return password


def _email(value: str) -> str:
    try:
        return str(TypeAdapter(NormalizedEmail).validate_python(value))
    except ValidationError:
        raise CliError(f"Email tidak valid: {value}") from None


def create_admin(
    db: Session, *, email: str, full_name: str, organization_name: str, password: str
) -> tuple[Organization, User]:
    email = _email(email)
    if not full_name.strip() or not organization_name.strip():
        raise CliError("Nama dan nama organisasi wajib diisi.")
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none() is not None:
        raise CliError(f"Pengguna {email} sudah ada. Gunakan set-password bila lupa kata sandi.")

    org = Organization(name=organization_name.strip())
    user = User(email=email, full_name=full_name.strip(), password_hash=hash_password(password))
    db.add_all([org, user])
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role=Role.OWNER))
    audit.record(
        db,
        organization_id=org.id,
        actor_user_id=None,
        action="organization.bootstrap",
        entity_type="organization",
        entity_id=org.id,
        summary=f"{org.name} / owner {user.email} (CLI)",
    )
    db.commit()
    return org, user


def set_password(db: Session, *, email: str, password: str) -> User:
    email = _email(email)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        raise CliError(f"Pengguna {email} tidak ditemukan.")
    user.password_hash = hash_password(password)
    revoke_user_sessions(db, user.id)
    for membership in db.execute(select(Membership).where(Membership.user_id == user.id)).scalars():
        audit.record(
            db,
            organization_id=membership.organization_id,
            actor_user_id=None,
            action="auth.password_reset_cli",
            entity_type="user",
            entity_id=user.id,
            summary=user.email,
        )
    db.commit()
    return user


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="RABmate admin CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="Buat organisasi baru beserta Owner/Admin pertama")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True, help="Nama lengkap admin")
    admin.add_argument("--organization", required=True, help="Nama organisasi/perusahaan")
    admin.add_argument("--password-stdin", action="store_true")

    reset = sub.add_parser("set-password", help="Setel ulang kata sandi pengguna")
    reset.add_argument("--email", required=True)
    reset.add_argument("--password-stdin", action="store_true")

    sub.add_parser(
        "seed-demo",
        help="Buat organisasi demo (development saja); kredensial ditulis ke var/",
    )

    args = parser.parse_args(argv)
    if args.command == "seed-demo":
        return _seed_demo_command()
    try:
        password = _read_password(args.password_stdin)
        with get_sessionmaker()() as db:
            if args.command == "create-admin":
                org, user = create_admin(
                    db,
                    email=args.email,
                    full_name=args.name,
                    organization_name=args.organization,
                    password=password,
                )
                print(f"Organisasi '{org.name}' dan Owner/Admin {user.email} dibuat.")
            else:
                user = set_password(db, email=args.email, password=password)
                print(f"Kata sandi {user.email} diperbarui; semua sesinya dicabut.")
    except CliError as exc:
        print(f"Gagal: {exc}", file=sys.stderr)
        return 1
    return 0


DEMO_CREDENTIALS_FILE = REPO_ROOT / "var" / "demo-credentials.txt"


def _seed_demo_command() -> int:
    password = secrets.token_urlsafe(12)
    settings = get_settings()
    try:
        with get_sessionmaker()() as db:
            org = seed_demo(db, password=password, settings=settings)
    except DemoSeedError as exc:
        print(f"Gagal: {exc}", file=sys.stderr)
        return 1
    DEMO_CREDENTIALS_FILE.parent.mkdir(exist_ok=True)
    emails = "\n".join(f"  {demo_email(role)}" for role in Role)
    # var/ is git-ignored; the password is not printed so it does not end up in terminal logs.
    DEMO_CREDENTIALS_FILE.write_text(
        f"Organisasi: {org.name}\nKata sandi (semua akun demo): {password}\nAkun:\n{emails}\n",
        encoding="utf-8",
    )
    print(f"Organisasi demo '{org.name}' dibuat dengan akun:\n{emails}")
    print(f"Kata sandi tersimpan di {DEMO_CREDENTIALS_FILE} (di-.gitignore).")
    try:
        # Imported here: the story drives the whole API in-process.
        from app.demo_story import build_demo_story
        from app.main import create_app

        build_demo_story(create_app(settings), password=password)
    except DemoSeedError as exc:
        print(f"Alur demo berhenti di tengah: {exc}", file=sys.stderr)
        return 1
    print(
        "Alur demo lengkap: katalog harga bersumber, RAB disetujui + dokumen terbit, penawaran "
        "diterima, SPK & BAST, invoice dibayar sebagian, satu RAB menunggu persetujuan."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
