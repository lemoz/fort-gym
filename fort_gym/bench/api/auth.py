"""Authentication helpers for admin endpoints.

Admin auth is optional for local development. If `FORT_GYM_ADMIN_PASSWORD` is set,
all admin routes require HTTP Basic auth.
"""

from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials


_basic_security = HTTPBasic(auto_error=False)


def require_admin(credentials: Optional[HTTPBasicCredentials] = Depends(_basic_security)) -> None:
    """Guard admin endpoints with Basic Auth when configured."""

    admin_password = os.getenv("FORT_GYM_ADMIN_PASSWORD")
    if admin_password is None or admin_password == "":
        if os.getenv("FORT_GYM_INSECURE_ADMIN", "0") == "1":
            return  # explicitly opt-in for local dev only
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints disabled. Set FORT_GYM_ADMIN_PASSWORD to enable.",
        )

    admin_user = os.getenv("FORT_GYM_ADMIN_USER", "admin")
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    valid = secrets.compare_digest(credentials.username, admin_user) and secrets.compare_digest(
        credentials.password, admin_password
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


__all__ = ["require_admin"]
