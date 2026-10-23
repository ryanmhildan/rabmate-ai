from __future__ import annotations

from sqlalchemy.orm import Session

from tests.factories import Tenant, make_client, make_project

URL = "/api/v1/clients"


def test_create_read_update_delete(tenant: Tenant) -> None:
    b = tenant.browser
    created = b.post(
        URL,
        json={
            "code": "CL-001",
            "name": "  PT Maju Jaya  ",
            "client_type": "company",
            "tax_id": "01.234.567.8-901.000",
            "email": "Finance@MajuJaya.co.id",
            "phone": "+62 21 555 1234",
            "city": "Jakarta",
            "notes": "",
        },
    )
    assert created.status_code == 201, created.text
    client = created.json()
    assert client["name"] == "PT Maju Jaya"
    assert client["email"] == "finance@majujaya.co.id"
    assert client["notes"] is None
    assert client["version"] == 1

    fetched = b.get(f"{URL}/{client['id']}").json()
    assert fetched == client

    updated = b.patch(f"{URL}/{client['id']}", json={"version": 1, "city": "Bekasi"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["city"] == "Bekasi"
    assert updated.json()["version"] == 2

    assert b.delete(f"{URL}/{client['id']}").status_code == 204
    assert b.get(f"{URL}/{client['id']}").status_code == 404


def test_validation_errors(tenant: Tenant) -> None:
    b = tenant.browser
    cases = [
        {"name": ""},
        {"name": "X", "tax_id": "123"},
        {"name": "X", "email": "bukan-email"},
        {"name": "X", "phone": "telepon<script>"},
        {"name": "X", "code": "kode dengan spasi"},
        {"name": "X", "client_type": "alien"},
        {"name": "X" * 201},
    ]
    for body in cases:
        response = b.post(URL, json=body)
        assert response.status_code == 422, body
        assert response.json()["error"]["code"] == "validation_error"


def test_duplicate_code_conflicts_within_org_only(
    db_session: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    assert tenant.browser.post(URL, json={"code": "A1", "name": "Satu"}).status_code == 201
    duplicate = tenant.browser.post(URL, json={"code": "A1", "name": "Dua"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["message"] == "Kode klien sudah dipakai."
    # Same code in another organization is fine.
    assert other_tenant.browser.post(URL, json={"code": "A1", "name": "Tiga"}).status_code == 201
    # Blank codes are stored as NULL and never collide.
    assert tenant.browser.post(URL, json={"code": "", "name": "Empat"}).status_code == 201
    assert tenant.browser.post(URL, json={"code": " ", "name": "Lima"}).status_code == 201


def test_stale_version_is_rejected(tenant: Tenant) -> None:
    client = tenant.browser.post(URL, json={"name": "Versi"}).json()
    first = tenant.browser.patch(f"{URL}/{client['id']}", json={"version": 1, "city": "A"})
    second = tenant.browser.patch(f"{URL}/{client['id']}", json={"version": 1, "city": "B"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "version_conflict"
    assert second.json()["error"]["details"] == {"current_version": 2}


def test_required_fields_cannot_be_nulled(tenant: Tenant) -> None:
    client = tenant.browser.post(URL, json={"name": "Wajib"}).json()
    response = tenant.browser.patch(f"{URL}/{client['id']}", json={"version": 1, "name": None})
    assert response.status_code == 422


def test_delete_refused_while_used_by_a_project(db_session: Session, tenant: Tenant) -> None:
    client = make_client(db_session, tenant.org)
    make_project(db_session, tenant.org, client_id=client.id)

    response = tenant.browser.delete(f"{URL}/{client.id}")

    assert response.status_code == 409
    assert "Nonaktifkan" in response.json()["error"]["message"]


def test_search_filter_sort_and_pagination(db_session: Session, tenant: Tenant) -> None:
    for name, city, active in [
        ("Bangun Persada", "Jakarta", True),
        ("Anugerah Teknik", "Surabaya", True),
        ("Cahaya 100% Abadi", "Jakarta", False),
        ("Delta_Mesin", "Medan", True),
    ]:
        make_client(db_session, tenant.org, name=name, city=city, is_active=active)
    b = tenant.browser

    by_city = b.get(URL, params={"q": "jakarta"}).json()
    assert {c["name"] for c in by_city["items"]} == {"Bangun Persada", "Cahaya 100% Abadi"}

    # LIKE wildcards in the search term are matched literally.
    assert [c["name"] for c in b.get(URL, params={"q": "100%"}).json()["items"]] == [
        "Cahaya 100% Abadi"
    ]
    assert [c["name"] for c in b.get(URL, params={"q": "a_m"}).json()["items"]] == ["Delta_Mesin"]

    active = b.get(URL, params={"is_active": "true"}).json()
    assert active["total"] == 3

    page = b.get(URL, params={"sort": "-name", "page": 2, "page_size": 2}).json()
    assert page["total"] == 4
    assert [c["name"] for c in page["items"]] == ["Bangun Persada", "Anugerah Teknik"]

    bad_sort = b.get(URL, params={"sort": "password"})
    assert bad_sort.status_code == 422
    assert b.get(URL, params={"page_size": 101}).status_code == 422
