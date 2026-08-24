"""Owned by the demo-seed batch work: backend/app/seed.py's employee/user portion (the
`select_demo_batch` / `_pick_demo_roles` / `clear_all_people` / `seed_demo_batch` /
`seed_from_fixture` block), not the service-registry block above it in that file.

Synthetic rows only, never the real spreadsheet -- same convention as
tests/test_identity.py's "seed importer" section, for the same reason: this suite must run
on any machine, not just one that happens to have
C:\\Users\\Anura\\OneDrive\\Desktop\\Erp Imp\\Employee_Role_Access_Mapping.xlsx.
"""
from __future__ import annotations

from sqlalchemy import select

from app import models
from app.seed import (
    DEMO_PIN,
    apply_diff,
    clear_all_people,
    compute_diff,
    load_sheet_rows,
    seed_demo_batch,
    seed_from_fixture,
    select_demo_batch,
    _pick_demo_roles,
)
from app.security import verify_pin

SHEET_HEADERS = [
    "Employee Code", "Full Name", "Work Email", "HR Department",
    "Division (Approval Matrix)", "Job Title (New Org Structure)", "Band",
    "Matched Approval-Matrix Role", "Match Status", "Approval Level",
    "ERP-Based System Access (assigned role)", "Extra / Cross-Dept Report Access",
    "Special Approver Override", "Category Overlay Notes", "Action Needed",
]


def _write_synthetic_sheet(tmp_path, rows):
    """Same shape _write_sheet in test_identity.py builds, kept as a local copy here so
    this file has no cross-file test dependency."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Employee Role & Access Map"
    ws.append(SHEET_HEADERS)
    for r in rows:
        ws.append([
            r["code"], r["name"], r.get("email"), r["dept"], r.get("division", r["dept"]),
            r.get("title", "Engineer"), r.get("band", "L1S"), None, None, r.get("approval"),
            r.get("erp_access"), r.get("extra_access"), r.get("override"), None, None,
        ])
    path = tmp_path / "synthetic.xlsx"
    wb.save(path)
    return path


def _synthetic_org_rows():
    """~9 departments big enough to be eligible (>=2 rows), sized so the real
    select_demo_batch defaults (target_depts=9, take 3 if a department has >=5 rows else
    2) land on exactly 20 people -- the low end of the owner's 20-25 target -- plus one
    1-person department that must be skipped entirely.

    Dept A and B (5 people each, one senior + juniors) get an approver-capable senior with
    a real approval level, sitting alongside plainer department-mates, so the
    approver/requester pairing has something real to pick from.
    """
    rows = []

    def add(dept, n, *, senior_band="L4", senior_approval="L3 (HOD)", junior_band="L1S", junior_approval="Operational"):
        rows.append({"code": f"{dept}-SR", "name": f"{dept} Senior", "email": f"{dept.lower()}sr@m-mines.com",
                     "dept": dept, "band": senior_band, "approval": senior_approval})
        for i in range(n - 1):
            rows.append({"code": f"{dept}-J{i}", "name": f"{dept} Junior {i}", "email": None,
                         "dept": dept, "band": junior_band, "approval": junior_approval})

    add("DeptA", 5)
    add("DeptB", 5)
    add("DeptC", 4)
    add("DeptD", 4)
    add("DeptE", 3)
    add("DeptF", 3)
    add("DeptG", 3)
    add("DeptH", 2)
    add("DeptI", 2)
    # A lone employee in a department of one -- select_demo_batch must skip this dept
    # entirely rather than "selecting" the whole (single-person) department.
    rows.append({"code": "LONER-1", "name": "Solo Employee", "email": None, "dept": "DeptLoner",
                 "band": "L5", "approval": "L5 (Apex)"})
    return rows


# ── selection logic ──────────────────────────────────────────────────────────────────────
def test_select_demo_batch_picks_2_or_3_per_department_skips_singletons(tmp_path):
    path = _write_synthetic_sheet(tmp_path, _synthetic_org_rows())
    rows = load_sheet_rows(path)

    selected = select_demo_batch(rows)

    assert len(selected) == 20  # 3+3+2*7, see _synthetic_org_rows' docstring
    depts = {r.hr_department for r in selected}
    assert len(depts) == 9
    assert "DeptLoner" not in depts  # the single-person department is never selected

    by_dept: dict[str, list] = {}
    for r in selected:
        by_dept.setdefault(r.hr_department, []).append(r)
    for dept, members in by_dept.items():
        assert 2 <= len(members) <= 3
        # The senior placeholder ("<Dept>-SR") is always the one picked first.
        assert any(m.employee_code.endswith("-SR") for m in members)


def test_pick_demo_roles_puts_approver_and_requester_1_in_the_same_department(tmp_path):
    path = _write_synthetic_sheet(tmp_path, _synthetic_org_rows())
    rows = load_sheet_rows(path)
    selected = select_demo_batch(rows)

    roles = _pick_demo_roles(selected)
    assert set(roles) == {"approver", "agent", "requester_1", "requester_2"}
    assert roles["approver"].hr_department == roles["requester_1"].hr_department
    assert roles["approver"].approval_level not in (None, "Operational")  # a REAL approval level
    # requester_1 must not already self-qualify as an approver, or the live "approve"
    # demo would short-circuit one hop too early.
    assert roles["requester_1"].approval_level in (None, "Operational")
    # Five distinct people play the five demo logins (admin is separate/synthetic).
    codes = {roles[r].employee_code for r in roles}
    assert len(codes) == 4


# ── full seed: counts, pins, grants ──────────────────────────────────────────────────────
def test_seed_demo_batch_creates_only_the_selected_batch(db, tmp_path):
    path = _write_synthetic_sheet(tmp_path, _synthetic_org_rows())
    rows = load_sheet_rows(path)
    expected = select_demo_batch(rows)

    seed_demo_batch(db, path)

    employees = list(db.scalars(select(models.Employee)))
    # Every selected person, plus the one synthetic platform-admin employee (MM-ITADMIN).
    non_admin = [e for e in employees if e.employee_code != "MM-ITADMIN"]
    assert len(non_admin) == len(expected) == 20
    assert {e.employee_code for e in non_admin} == {r.employee_code for r in expected}
    assert "DeptLoner" not in {e.hr_department for e in employees}


def test_seed_demo_batch_gives_exactly_five_usable_pins(db, tmp_path):
    path = _write_synthetic_sheet(tmp_path, _synthetic_org_rows())
    seed_demo_batch(db, path)

    users = list(db.scalars(select(models.User)))
    with_pin_set = [u for u in users if u.pin_set_at is not None]
    assert len(with_pin_set) == 5

    for u in with_pin_set:
        assert u.pin_hash is not None
        assert verify_pin(DEMO_PIN, u.pin_hash)  # the printed demo PIN actually works

    # Everyone else: the existing "PIN not yet issued by IT" convention -- placeholder
    # hash present (pin_required CHECK), pin_set_at still NULL.
    without_pin_set = [u for u in users if u.pin_set_at is None]
    assert len(without_pin_set) == len(users) - 5
    for u in without_pin_set:
        assert u.pin_hash is not None
        assert not verify_pin(DEMO_PIN, u.pin_hash)  # never the guessable demo PIN


def test_seed_demo_batch_platform_admin_satisfies_no_pin_admins_and_pin_login_works(db, client, tmp_path):
    path = _write_synthetic_sheet(tmp_path, _synthetic_org_rows())
    seed_demo_batch(db, path)

    admin_emp = db.scalar(select(models.Employee).where(models.Employee.employee_code == "MM-ITADMIN"))
    admin_user = db.scalar(select(models.User).where(models.User.employee_id == admin_emp.id))

    # The constraint itself: NOT (auth_type='local_pin' AND is_platform_admin). Satisfied
    # by construction (auth_type is 'google'), not by weakening the CHECK.
    assert admin_user.auth_type == "google"
    assert admin_user.is_platform_admin is True
    assert admin_user.login_email == "itadmin@m-mines.com"  # email_required CHECK
    assert admin_user.pin_hash is not None
    assert admin_user.pin_set_at is not None
    assert verify_pin(DEMO_PIN, admin_user.pin_hash)

    # And the real PIN-login route accepts it -- auth.py keys off pin_hash presence, not
    # auth_type=='local_pin' (see the comment at routers/auth.py:452-459).
    resp = client.post("/api/auth/pin", json={"employee_code": "MM-ITADMIN", "pin": DEMO_PIN})
    assert resp.status_code == 200
    assert resp.cookies.get("mmos_session") is not None


def test_seed_demo_batch_requester_1_reports_up_to_the_approver(db, tmp_path):
    path = _write_synthetic_sheet(tmp_path, _synthetic_org_rows())
    rows = load_sheet_rows(path)
    selected = select_demo_batch(rows)
    roles = _pick_demo_roles(selected)

    seed_demo_batch(db, path)

    approver_emp = db.scalar(select(models.Employee).where(models.Employee.employee_code == roles["approver"].employee_code))
    requester1_emp = db.scalar(select(models.Employee).where(models.Employee.employee_code == roles["requester_1"].employee_code))
    assert requester1_emp.manager_id == approver_emp.id


def test_seed_demo_batch_grants_are_uneven_admin_sees_the_most(db, tmp_path):
    path = _write_synthetic_sheet(tmp_path, _synthetic_org_rows())
    rows = load_sheet_rows(path)
    selected = select_demo_batch(rows)
    roles = _pick_demo_roles(selected)

    seed_demo_batch(db, path)

    def grant_count(code):
        user = db.scalar(
            select(models.User).join(models.Employee, models.User.employee_id == models.Employee.id)
            .where(models.Employee.employee_code == code)
        )
        return len(list(db.scalars(select(models.Grant).where(models.Grant.user_id == user.id))))

    admin_grants = grant_count("MM-ITADMIN")
    requester_1_grants = grant_count(roles["requester_1"].employee_code)
    role_codes = {r.employee_code for r in roles.values()}
    other_seeded = [r.employee_code for r in selected if r.employee_code not in role_codes]

    assert admin_grants > requester_1_grants  # admin "sees everything"
    assert requester_1_grants >= 1  # requesters still see at least something
    assert grant_count(other_seeded[0]) <= requester_1_grants  # non-demo-login people get the lightest spread


# ── destructive reset: explicit, guarded, no duplicates on re-run ────────────────────────
def test_clear_all_people_refuses_when_audit_log_has_real_rows(db):
    db.add(models.AuditLog(action="login.pin", metadata_={}))
    db.commit()

    try:
        clear_all_people(db)
        assert False, "expected clear_all_people to refuse"
    except RuntimeError as exc:
        assert "audit_log" in str(exc)

    # Forcing it through is still possible, deliberately.
    n = clear_all_people(db, force=True)
    assert n == 0  # no employees existed yet in this test, but the call itself must succeed


def test_seed_demo_batch_reruns_wipe_and_reseed_without_duplicates(db, tmp_path):
    path = _write_synthetic_sheet(tmp_path, _synthetic_org_rows())

    seed_demo_batch(db, path)
    first_employee_count = len(list(db.scalars(select(models.Employee))))
    first_user_count = len(list(db.scalars(select(models.User))))
    first_grant_count = len(list(db.scalars(select(models.Grant))))

    # Re-run exactly as the owner asked: the previous demo set is removed and replaced,
    # not merged with.
    seed_demo_batch(db, path)

    assert len(list(db.scalars(select(models.Employee)))) == first_employee_count
    assert len(list(db.scalars(select(models.User)))) == first_user_count
    assert len(list(db.scalars(select(models.Grant)))) == first_grant_count

    # And no duplicate employee_codes crept in.
    codes = [e.employee_code for e in db.scalars(select(models.Employee))]
    assert len(codes) == len(set(codes))

    with_pin_set = [u for u in db.scalars(select(models.User)) if u.pin_set_at is not None]
    assert len(with_pin_set) == 5


# ── fixture-driven path: the committed app/demo_seed.py, no spreadsheet ─────────────────
def test_seed_from_fixture_seeds_the_committed_fixture(db):
    from app import demo_seed

    logins = seed_from_fixture(db)

    assert len(logins) == 5
    employees = list(db.scalars(select(models.Employee)))
    non_admin = [e for e in employees if e.employee_code != "MM-ITADMIN"]
    assert len(non_admin) == len(demo_seed.DEMO_PEOPLE)
    assert {e.employee_code for e in non_admin} == {p.employee_code for p in demo_seed.DEMO_PEOPLE}

    # No email address ever entered the database from the fixture (the fixture itself
    # carries none -- this just proves seed_from_fixture didn't invent any).
    for e in non_admin:
        assert e.work_email is None

    with_pin_set = [u for u in db.scalars(select(models.User)) if u.pin_set_at is not None]
    assert len(with_pin_set) == 5
    for u in with_pin_set:
        assert verify_pin(DEMO_PIN, u.pin_hash)


def test_seed_from_fixture_never_wipes_and_is_idempotent(db):
    """The container-boot path must be safe to run on every restart, including after real
    logins have happened -- unlike --seed-demo, it must never call clear_all_people."""
    from app import demo_seed

    seed_from_fixture(db)

    # Simulate a real login having happened between container restarts.
    db.add(models.AuditLog(action="login.pin", metadata_={}))
    db.commit()

    # Must not raise, and must not wipe anything -- it never touches clear_all_people.
    seed_from_fixture(db)

    employees = [e for e in db.scalars(select(models.Employee)) if e.employee_code != "MM-ITADMIN"]
    assert len(employees) == len(demo_seed.DEMO_PEOPLE)
    codes = [e.employee_code for e in employees]
    assert len(codes) == len(set(codes))  # no duplicates

    grants = list(db.scalars(select(models.Grant)))
    grant_pairs = [(g.user_id, g.service_id) for g in grants]
    assert len(grant_pairs) == len(set(grant_pairs))  # uq_grant_user_service never violated

    # The audit row survived -- seed_from_fixture truly never wipes.
    assert db.scalar(select(models.AuditLog)) is not None
