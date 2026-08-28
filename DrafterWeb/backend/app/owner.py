"""Who owns a draft session.

The site is public and has no login, so this is **ownership, not
authorization**. It stops a friend from deleting your mock draft by accident;
it does not stop someone determined, because anything a browser sends can be
forged. Nothing sensitive is behind it, which is why that trade is acceptable.

The upgrade path is deliberate: put Cloudflare Access in front and the same
`owner_id` column holds a verified email from `Cf-Access-Authenticated-User-
Email` instead of a random token, and the check becomes genuinely enforceable
with no migration.
"""

from __future__ import annotations

import re
import secrets

from fastapi import Request, Response

COOKIE = "ngfl_owner"
# Long-lived on purpose: losing the cookie loses your drafts, and a draft you
# started in August should still be there in December.
MAX_AGE = 60 * 60 * 24 * 365

# Set by Cloudflare Access when it is in front of the app.
ACCESS_EMAIL_HEADER = "cf-access-authenticated-user-email"

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def _is_secure(request: Request) -> bool:
    """True when the browser reached us over HTTPS.

    Behind the tunnel the app itself is spoken to over plain HTTP, so the
    forwarded header is the only honest signal. Without this the cookie would
    either be dropped in local development or sent unprotected in production.
    """
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return forwarded == "https" or request.url.scheme == "https"


def resolve(request: Request, response: Response) -> str:
    """The caller's owner id, minting and setting one if they have none."""
    verified = request.headers.get(ACCESS_EMAIL_HEADER)
    if verified:
        # A real identity beats the cookie whenever Access is enabled.
        return f"email:{verified.strip().lower()}"

    existing = request.cookies.get(COOKIE)
    if existing and _TOKEN.match(existing):
        return existing

    minted = secrets.token_urlsafe(24)
    response.set_cookie(
        COOKIE,
        minted,
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_is_secure(request),
        path="/",
    )
    return minted
