"""Dev convenience: create the schema if it does not exist yet. Not a data seed — Service
Desk starts empty (docs/07 has no fixture data of its own; org-chart people are MM OS's, not
this service's). Run migrations with Alembic for anything beyond local dev/test — see
README.md.
"""
from __future__ import annotations

from .db import engine
from .models import Base


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("servicedesk: schema ensured")


if __name__ == "__main__":
    main()
