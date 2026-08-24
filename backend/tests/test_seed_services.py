"""Owned by A3-shell demo prep (see backend/app/seed.py SERVICES block).

Covers `seed_services`: the real Coolify-backed service registry seed. The one property that
matters for a repeatable demo run is idempotency -- re-running the seed (e.g. on every
container start) must never duplicate a row or clobber a URL an admin has since hand-edited.
"""
from __future__ import annotations

from sqlalchemy import select

from app import models
from app.seed import SERVICES, seed_services


def test_seed_services_creates_every_slug_once(db):
    created = seed_services(db)
    db.commit()

    assert set(created) == {s["slug"] for s in SERVICES}

    rows = list(db.scalars(select(models.Service)))
    assert len(rows) == len(SERVICES)
    assert {r.slug for r in rows} == {s["slug"] for s in SERVICES}


def test_seed_services_in_house_vs_third_party_launch_mode(db):
    seed_services(db)
    db.commit()

    by_slug = {s.slug: s for s in db.scalars(select(models.Service))}

    for slug in ("itemcode", "att", "ocr", "purchase", "servicedesk"):
        assert by_slug[slug].launch_mode in ("handoff", "embed"), slug

    for slug in ("erpnext", "twenty"):
        assert by_slug[slug].launch_mode == "external", slug


def test_seed_services_in_house_roles_have_descriptions(db):
    seed_services(db)
    db.commit()

    by_slug = {s.slug: s for s in db.scalars(select(models.Service))}

    for slug in ("itemcode", "att", "ocr", "purchase", "servicedesk"):
        svc = by_slug[slug]
        assert svc.roles, f"{slug} has no roles"
        role_keys = {r.key for r in svc.roles}
        assert {"viewer", "admin"} <= role_keys or {"requester", "agent", "admin"} <= role_keys
        for role in svc.roles:
            assert role.description, f"{slug}/{role.key} has no description"


def test_seed_services_servicedesk_is_placeholder_and_inactive(db):
    seed_services(db)
    db.commit()

    servicedesk = db.scalar(select(models.Service).where(models.Service.slug == "servicedesk"))
    assert servicedesk.is_active is False


def test_seed_services_is_idempotent_and_preserves_hand_edits(db):
    """Running the seed twice must not duplicate rows, and must not stomp on a base_url an
    admin has since edited by hand -- the seed only ever creates missing slugs."""
    seed_services(db)
    db.commit()

    before_count = len(list(db.scalars(select(models.Service))))

    # Simulate an admin hand-editing a URL after the first seed run.
    itemcode = db.scalar(select(models.Service).where(models.Service.slug == "itemcode"))
    edited_url = "https://itemcode-real-dns.m-mines.com"
    itemcode.base_url = edited_url
    db.commit()

    second_created = seed_services(db)
    db.commit()

    assert second_created == []  # nothing new to create, every slug already exists

    after_count = len(list(db.scalars(select(models.Service))))
    assert after_count == before_count  # no duplicates

    itemcode_after = db.scalar(select(models.Service).where(models.Service.slug == "itemcode"))
    assert itemcode_after.base_url == edited_url  # hand edit survived the re-run

    # And role rows weren't duplicated either.
    assert len(itemcode_after.roles) == 2
