"""Apply a role file from a shell. Dry run unless --apply.

    python -m app.roles_cli itemcode                     # the committed app/role_files/itemcode.json
    python -m app.roles_cli path/to/file.json --apply
    python -m app.roles_cli itemcode --apply --assign-mode all

Same code path as Admin -> Roles -> Import in the UI (app/roles_io.py).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from .db import SessionLocal
from .models import Service
from .roles_io import RoleFileError, apply, committed, validate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="a service slug (uses the committed file) or a path to a role file")
    ap.add_argument("--apply", action="store_true", help="write the changes (default is a dry run)")
    ap.add_argument("--assign-mode", choices=("missing", "all"), help="override the file's assign.mode")
    args = ap.parse_args(argv)

    path = Path(args.file)
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else committed(args.file)
    if doc is None:
        print(f"no such file, and no committed role file for {args.file!r}", file=sys.stderr)
        return 2
    try:
        doc = validate(doc)
    except RoleFileError as e:
        for p in e.problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        service = db.scalar(select(Service).where(Service.slug == doc["service"]))
        if service is None:
            print(f"service {doc['service']!r} is not registered", file=sys.stderr)
            return 2
        plan = apply(db, service, doc, actor=None, dry_run=not args.apply, assign_mode=args.assign_mode)
        out = plan.as_dict()
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(("APPLIED" if args.apply else "DRY RUN") + f" -- {out['service']}")
    for k in ("roles_created", "roles_updated", "roles_removed"):
        print(f"  {k}: {', '.join(out[k]) or '-'}")
    print(f"  grants moved: {len(out['grants_moved'])}, created: {len(out['grants_created'])}, "
          f"changed: {len(out['grants_changed'])}, unchanged: {out['unchanged_people']}")
    for g in out["grants_created"] + out["grants_changed"]:
        print(f"    {g.get('employee_code')}: {g.get('role') or (g['from'] + ' -> ' + g['to'])}")
    for w in out["warnings"]:
        print(f"  warning: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
