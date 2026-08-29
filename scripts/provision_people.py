"""Provision specific named employees with a real one-time PIN (must-change on first login).

This is the real-rollout counterpart to the demo seed: instead of seeding 23 fixed demo
accounts, IT brings real people online a handful at a time, each with a one-time PIN they must
change on first login.

    PY = backend/.venv/Scripts/python.exe  (Windows)  |  backend/.venv/bin/python  (Linux VPS)

    # Dry run -- shows who would be provisioned, writes nothing, reveals no PIN:
    PY scripts/provision_people.py --codes MM05,MM81,MM88

    # Apply -- imports any of those not yet in the database from the sheet, then issues a
    # one-time PIN for each and prints code + PIN once:
    PY scripts/provision_people.py --codes MM05,MM81,MM88 --commit

    # Codes from a file (one per line), custom PIN length:
    PY scripts/provision_people.py --codes-file rollout-batch-1.txt --pin-length 6 --commit

The mapping spreadsheet is read IN PLACE (default: the path in app/seed.py). Nothing here
writes an employee name or email into the repo -- names are only ever printed to the terminal
you run this from. Capture the printed PINs, hand each to its person directly (in person or a
password-manager secure note, never a plain chat/email), then close the terminal.

The orchestrator runs this live once the owner names the batch; the mechanism itself is
parameterized and tested (backend/tests/test_provisioning.py) without any specific names.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# backend/ on sys.path so `import app...` resolves however this is invoked.
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(_BACKEND))

from app.db import SessionLocal  # noqa: E402
from app.models import Employee, User  # noqa: E402
from app.provision import provision_by_code  # noqa: E402
from app.seed import (  # noqa: E402
    DEFAULT_XLSX_PATH,
    apply_diff,
    compute_diff,
    load_sheet_rows,
    resolve_managers,
)
from sqlalchemy import select  # noqa: E402


def _read_codes(args) -> list[str]:
    codes: list[str] = []
    if args.codes:
        codes += [c.strip() for c in args.codes.split(",") if c.strip()]
    if args.codes_file:
        for line in Path(args.codes_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                codes.append(line)
    # de-dup, preserve order
    seen: set[str] = set()
    out = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xlsx", default=str(DEFAULT_XLSX_PATH), help="Path to the mapping spreadsheet (read in place)")
    parser.add_argument("--codes", help="Comma-separated employee codes, e.g. MM05,MM81")
    parser.add_argument("--codes-file", help="File with one employee code per line (# comments allowed)")
    parser.add_argument("--pin-length", type=int, default=6, help="Length of each generated PIN (4-8, default 6)")
    parser.add_argument(
        "--platform-admin", action="store_true",
        help="Management layer: grant each provisioned person FULL IT-admin-equivalent access "
             "(is_platform_admin -- act + approve + see everything), not a view-only role. Owner "
             "decision 28 Aug 2026. Requires each person to have a work_email on file (admins "
             "authenticate as google; see app/provision.py). Use only for named management heads.",
    )
    parser.add_argument("--commit", action="store_true", help="Apply. Default is a dry run that writes nothing and reveals no PIN.")
    args = parser.parse_args(argv)

    codes = _read_codes(args)
    if not codes:
        print("No employee codes given. Use --codes MM05,MM81 or --codes-file batch.txt.", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        existing = {
            e.employee_code
            for e in db.scalars(select(Employee).where(Employee.employee_code.in_(codes)))
        }
        missing = [c for c in codes if c not in existing]

        print(f"Requested {len(codes)} code(s). Already in database: {len(existing)}. "
              f"Not yet imported: {len(missing)}.")

        if missing:
            # Import just the requested-but-missing people from the sheet, so provisioning a
            # brand-new hire in one step works. Only the requested codes are touched.
            rows = [r for r in load_sheet_rows(args.xlsx) if r.employee_code in set(missing)]
            found_codes = {r.employee_code for r in rows}
            not_in_sheet = [c for c in missing if c not in found_codes]
            if not_in_sheet:
                print(f"  WARNING: not found in the sheet either (skipped): {', '.join(not_in_sheet)}")
            print(f"  Will import from the sheet: {', '.join(sorted(found_codes)) or '(none)'}")

            if args.commit and rows:
                diff = compute_diff(db, rows)
                apply_diff(db, diff)
                db.commit()
                resolve_managers(db)
                db.commit()
                print(f"  Imported {len(diff.new)} new employee/user row(s).")

        if not args.commit:
            print("\nDry run -- nothing written, no PIN issued. Re-run with --commit to apply.")
            return 0

        print("\n" + "=" * 66)
        print("ONE-TIME PINs -- shown ONCE. Hand each to its person directly.")
        print("Each holder MUST change their PIN on first login.")
        if args.platform_admin:
            print("PLATFORM ADMIN: each of these gets FULL IT-admin-equivalent access.")
        print("=" * 66)
        provisioned = 0
        for code in codes:
            pin, status = provision_by_code(db, code, length=args.pin_length, platform_admin=args.platform_admin)
            if status == "provisioned":
                provisioned += 1
                tag = " [platform admin]" if args.platform_admin else ""
                print(f"  {code:<12} PIN {pin}{tag}")
            else:
                print(f"  {code:<12} SKIPPED ({status})")
        db.commit()
        print("=" * 66)
        print(f"Provisioned {provisioned} of {len(codes)} requested. Committed.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
