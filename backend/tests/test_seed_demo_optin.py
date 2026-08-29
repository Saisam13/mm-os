"""Gap 2: the 23-name demo seed is OPT-IN. A normal boot (`python -m app.seed --demo` with no
opt-in flag) must create NO demo login accounts; only an explicit MMOS_ENABLE_DEMO_SEED=1 run
seeds them. The demo fixture is monkeypatched to synthetic codes here so this test never
depends on -- or reproduces -- the real employee names in app/demo_seed.py.
"""
from __future__ import annotations

from sqlalchemy import func, select

from app import demo_seed, seed
from app.db import SessionLocal
from app.models import Employee, User

# Synthetic stand-in for the committed fixture -- no real names.
_SYNTHETIC_PEOPLE = [
    demo_seed.DemoPerson("MM-D01", "Demo One", "QA/QC", "Ops", "Tester", "L2", "L2", None),
    demo_seed.DemoPerson("MM-D02", "Demo Two", "Projects", "Ops", "Engineer", "L3", "L3 (HOD)", None),
    demo_seed.DemoPerson("MM-D03", "Demo Three", "QA/QC", "Ops", "Tester", "L1J", "Operational", "MM-D01"),
    demo_seed.DemoPerson("MM-D04", "Demo Four", "N-Hub", "Ops", "Analyst", "L2", "L2", None),
]
_SYNTHETIC_ROLES = {
    "agent": "MM-D02",
    "approver": "MM-D01",
    "requester_1": "MM-D03",
    "requester_2": "MM-D04",
}


def _counts():
    s = SessionLocal()
    try:
        return (
            s.scalar(select(func.count()).select_from(Employee)) or 0,
            s.scalar(select(func.count()).select_from(User)) or 0,
        )
    finally:
        s.close()


def test_normal_boot_without_flag_seeds_no_demo_accounts(db, monkeypatch):
    monkeypatch.delenv("MMOS_ENABLE_DEMO_SEED", raising=False)

    rc = seed.main(["--demo"])
    assert rc == 0

    employees, users = _counts()
    assert employees == 0
    assert users == 0


def test_flagged_boot_seeds_the_demo_accounts(db, monkeypatch):
    monkeypatch.setenv("MMOS_ENABLE_DEMO_SEED", "1")
    monkeypatch.setattr(demo_seed, "DEMO_PEOPLE", _SYNTHETIC_PEOPLE)
    monkeypatch.setattr(demo_seed, "DEMO_LOGIN_ROLES", _SYNTHETIC_ROLES)

    rc = seed.main(["--demo"])
    assert rc == 0

    s = SessionLocal()
    try:
        employees = s.scalar(select(func.count()).select_from(Employee)) or 0
        # The four synthetic people plus the synthetic platform admin were created.
        assert employees >= 4
        head = s.scalar(
            select(User).join(Employee, User.employee_id == Employee.id).where(
                Employee.employee_code == "MM-D01"
            )
        )
        assert head is not None
        assert head.pin_set_at is not None  # a demo login PIN was issued
    finally:
        s.close()
