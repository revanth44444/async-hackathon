import re

from fastapi import Header, HTTPException

_CLIENT_ID = re.compile(r"^[A-Za-z0-9-]{16,64}$")


def client_id(x_client_id: str | None = Header(None)) -> str:
    """Anonymous per-browser ID. Offers are only visible to the browser that created them."""
    if not x_client_id or not _CLIENT_ID.match(x_client_id):
        raise HTTPException(400, "Missing or invalid X-Client-Id header")
    return x_client_id
