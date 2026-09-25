# Role files

One JSON file per service: its permissions, its roles, what each role may do, and
(optionally) who gets which role. The format and every rule are documented at the top of
`backend/app/roles_io.py`.

Use them from **Admin → Roles** in MM OS: pick the service, *Import role file*, review the
dry run, then apply. *Export* gives you the current state as a file to edit.

Or from a shell inside the MM OS container:

    python -m app.roles_cli itemcode            # dry run
    python -m app.roles_cli itemcode --apply

Keep named people out of the committed files: `assign.people` is for a file you upload once,
not for git. Rules (`platform_admin`, `is_approver`, `band`, `department`) and `default` are
fine to commit.
