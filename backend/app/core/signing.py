"""Signed, expiring URLs for stored files (PRD section 27).

Section 27 requires signed URLs for files, and requires that a user only reaches
their own project. A plain ``/static`` mount satisfies neither: the URL is the
only capability, so anyone who sees it -- or guesses it -- can read another
user's generated images forever.

The scheme here is deliberately small: an HMAC over ``<key>:<expires>`` keyed by
``SECRET_KEY``. It needs no extra infrastructure (no S3, no signing service),
works identically for the local filesystem and for a future object store, and
gives exactly the two properties section 27 asks for:

* **expiring** -- a leaked URL stops working after ``ASSET_URL_TTL_SECONDS``;
* **unforgeable** -- the path cannot be tweaked without the key.

Scope note: this authorises *access to a file*, not *ownership of a project*.
Project-scoped authorisation still happens in the API layer (every endpoint
checks ``user_id``); the signature is what stops a URL from being a permanent
bearer token.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

from app.core.config import settings

# Default lifetime of a handed-out file URL. Long enough to render a page and
# follow a download, short enough that a pasted URL is not a permanent leak.
DEFAULT_TTL_SECONDS = 3600


def _signature(storage_key: str, expires_at: int) -> str:
    payload = f"{storage_key}:{expires_at}".encode()
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


def sign_storage_url(
    storage_key: str,
    *,
    ttl_seconds: int | None = None,
    base_url: str | None = None,
) -> str:
    """Return a signed, expiring URL for ``storage_key``.

    ``storage_key`` is the path relative to the storage root, e.g.
    ``project/<pid>/shots/<sid>.png``.
    """
    ttl = DEFAULT_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    expires_at = int(time.time()) + ttl
    base = (base_url or settings.storage_public_base_url).rstrip("/")
    query = urlencode({"expires": expires_at, "sig": _signature(storage_key, expires_at)})
    return f"{base}/{storage_key}?{query}"


def verify_storage_signature(storage_key: str, expires: str | int | None, sig: str | None) -> bool:
    """True when ``sig`` is a valid, unexpired signature for ``storage_key``."""
    if not sig or expires is None:
        return False
    try:
        expires_at = int(expires)
    except (TypeError, ValueError):
        return False
    if expires_at < int(time.time()):
        return False
    return hmac.compare_digest(sig, _signature(storage_key, expires_at))


def storage_key_from_url(url: str, *, base_url: str | None = None) -> str | None:
    """Recover the storage key from a URL this service previously produced.

    Returns ``None`` when the URL is not one of ours (a foreign host, no path, or
    a prefix that does not match the configured base) -- the caller then leaves
    the value alone rather than mangling data it does not understand.
    """
    if not url:
        return None
    base = (base_url or settings.storage_public_base_url).rstrip("/")
    if not url.startswith(f"{base}/"):
        return None
    remainder = url[len(base) + 1 :]
    # Drop the query (``?expires=..&sig=..``) but keep any inner ``?``.
    remainder = remainder.split("#", 1)[0].split("?", 1)[0]
    return remainder or None


def resign_storage_url(
    stored_url: str | None,
    *,
    ttl_seconds: int | None = None,
    base_url: str | None = None,
) -> str | None:
    """Re-sign a URL that was persisted earlier, refreshing its expiry.

    Needed because a signed URL is *not* a durable value: writing one to the
    database (``characters.reference_image_url``, PRD section 17) would otherwise
    bake in a one-hour expiry and turn a working reference image into a dead link
    the moment that hour passes. Reading re-signs from the storage key instead, so
    the column stays a URL and every response carries a live one.
    """
    if not stored_url:
        return None
    key = storage_key_from_url(stored_url, base_url=base_url)
    if key is None:
        # Not a URL we minted (external image, or an older value): leave it be.
        return stored_url
    return sign_storage_url(key, ttl_seconds=ttl_seconds, base_url=base_url)
