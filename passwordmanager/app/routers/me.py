"""The one placeholder authenticated route this shell has. No vault, no secret storage —
see SECURITY.md. `/api/me` exists only to prove the auth seam end-to-end (a valid token in,
the caller's own identity out); `GET /` uses the same dependency to render the placeholder
page described in the build brief.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..mmos_seam import CurrentUser, get_current_user

router = APIRouter(tags=["me"])


@router.get("/api/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return {
        "sub": user.sub,
        "employee_code": user.employee_code,
        "name": user.name,
        "email": user.email,
        "department": user.department,
        "division": user.division,
        "band": user.band,
        "roles": user.roles,
        "vault": {
            "status": "not_implemented",
            "message": "Your vault will live here.",
        },
    }
