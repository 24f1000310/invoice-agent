
import hashlib

from fastapi import Request, HTTPException


def authenticate(request: Request) -> str:

    authorization = request.headers.get(
        "Authorization",
        ""
    )

    if not authorization:

        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )

    # Split scheme and token.
    parts = authorization.split(None, 1)

    if len(parts) != 2:

        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header"
        )

    scheme, token = parts

    # HTTP authentication scheme names are case-insensitive.
    if scheme.lower() != "bearer":

        raise HTTPException(
            status_code=401,
            detail="Bearer authentication required"
        )

    # Reject empty or whitespace-padded tokens.
    if not token or token != token.strip():

        raise HTTPException(
            status_code=401,
            detail="Invalid bearer token"
        )

    # Never store the raw bearer token.
    principal = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    return principal
