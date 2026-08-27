"""The one placeholder authenticated route this shell exposes. Item Code Studio's actual
item-code generation/registry endpoints do not exist yet — this only proves the auth seam
end to end (valid token in, signed-in identity out) so the frontend has something real to
render and later routes have a place to land.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..mmos_seam import CurrentUser, get_current_user

router = APIRouter(tags=["api"])


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
    }
