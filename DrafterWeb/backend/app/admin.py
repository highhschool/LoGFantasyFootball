"""Who counts as the site owner.

The site is public and its sessions are scoped to whoever made them, so the
one view that crosses that boundary needs a real gate rather than a guessable
one.

Cloudflare Access supplies it. An Access application on the admin paths lets
only a listed email through and hands the app a verified address; nothing here
stores a password or a session. A token is accepted as well, so the admin view
works locally and before Access is configured.

**The Access application must cover both `/admin` and `/api/admin`.** Access
protects by path: guarding the page alone would leave the data it reads open,
which is worse than not guarding it at all, because it looks protected. The
email allowlist below is the second lock -- a forged header still has to name
an address that is on it.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException, Request

from . import config
from .owner import ACCESS_EMAIL_HEADER

logger = logging.getLogger(__name__)

ADMIN_TOKEN_HEADER = "x-admin-token"


def admin_email(request: Request) -> str | None:
    """The verified address of the admin making this request, if any."""
    raw = request.headers.get(ACCESS_EMAIL_HEADER)
    if not raw:
        return None

    email = raw.strip().lower()
    return email if email in config.ADMIN_EMAILS else None


def is_admin(request: Request) -> bool:
    if admin_email(request) is not None:
        return True

    token = request.headers.get(ADMIN_TOKEN_HEADER, "")
    return bool(config.ADMIN_TOKEN) and secrets.compare_digest(
        token, config.ADMIN_TOKEN
    )


def require_admin(request: Request) -> str:
    """Admit the owner, or 404.

    404 rather than 403 for the same reason the session routes use it: a
    distinct status confirms the route exists and invites someone to keep
    knocking.
    """
    if not config.ADMIN_EMAILS and not config.ADMIN_TOKEN:
        # Nothing configured, so there is no owner to be. Fails closed.
        raise HTTPException(status_code=404, detail="Not Found")

    if not is_admin(request):
        logger.warning(
            "refused an admin request from %s", request.client.host if request.client else "?"
        )
        raise HTTPException(status_code=404, detail="Not Found")

    return admin_email(request) or "token"
