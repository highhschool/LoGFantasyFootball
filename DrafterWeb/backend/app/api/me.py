"""Who you are, and what you look like.

Identity started inside the keeper tool because that is where the codes came
from. It is not the keeper tool's any more -- contracts asks the same question,
and telling somebody to visit a different tool in order to sign in for this one
was the tell. So it lives here, under a name that does not belong to a feature.

Pictures are free by default. Everyone in the league already has a Sleeper
avatar, so a face appears without anybody uploading anything, and an upload is
an override rather than a chore.

An uploaded picture is a data URL, and the browser redraws it through a canvas
before sending. That does two jobs at once: it caps the size regardless of what
was chosen, and it turns the file into plain raster pixels -- so an SVG with a
script in it arrives as a rectangle of colours. The checks here are the second
line rather than the first, because a client-side guard is a courtesy and not a
control.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..owner import resolve as resolve_owner
from ..store import SessionStore

router = APIRouter(prefix="/api/me", tags=["me"])

SLEEPER_AVATAR = "https://sleepercdn.com/avatars/thumbs/{}"

# Raster only, and only the three formats a canvas will produce. Anything that
# can carry markup -- SVG above all -- is not an image as far as this is
# concerned.
PHOTO = re.compile(r"^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$")

# Roughly 200KB of base64, which is about 150KB of picture. A 256px square
# lands far under this; anything above it did not come from our canvas.
MAX_PHOTO = 200_000


class PhotoIn(BaseModel):
    photo: str


def get_store() -> SessionStore:
    from ..main import get_session_store

    return get_session_store()


def get_owner(request: Request, response: Response) -> str:
    return resolve_owner(request, response)


def require_manager(store: SessionStore, owner: str) -> dict:
    manager = store.claimed_manager(owner)
    if manager is None:
        raise HTTPException(status_code=403, detail="sign in with your manager code first")
    return manager


def as_profile(manager: dict | None) -> dict | None:
    """A manager plus the picture to draw, whichever source it came from."""
    if manager is None:
        return None

    avatar = manager.get("avatar")
    return {
        "user_id": manager["user_id"],
        "display_name": manager["display_name"],
        "team_name": manager["team_name"],
        "draft_slot": manager.get("draft_slot"),
        # The uploaded one wins; Sleeper's is the fallback; neither is fine and
        # the page draws initials.
        "photo": manager.get("photo"),
        "avatar_url": SLEEPER_AVATAR.format(avatar) if avatar else None,
        "custom": bool(manager.get("photo")),
    }


@router.get("")
def me(
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    """Never 403s. Signed out is an answer, not an error."""
    return {"you": as_profile(store.claimed_manager(owner))}


@router.put("/photo")
def set_photo(
    body: PhotoIn,
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    manager = require_manager(store, owner)
    photo = body.photo.strip()

    if len(photo) > MAX_PHOTO:
        raise HTTPException(
            status_code=413,
            detail="that picture is too large; try a smaller one",
        )
    if not PHOTO.match(photo):
        raise HTTPException(
            status_code=422,
            detail="that is not a PNG, JPEG or WebP image",
        )

    store.set_photo(manager["user_id"], photo)
    return {"you": as_profile(store.claimed_manager(owner))}


@router.delete("/photo")
def clear_photo(
    store: SessionStore = Depends(get_store),
    owner: str = Depends(get_owner),
) -> dict:
    """Back to the Sleeper avatar, which is what most people will want."""
    manager = require_manager(store, owner)
    store.set_photo(manager["user_id"], None)
    return {"you": as_profile(store.claimed_manager(owner))}
