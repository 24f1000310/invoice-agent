
from fastapi import Request, HTTPException


A2A_VERSION = "1.0"
A2A_MEDIA_TYPE = "application/a2a+json"


def validate_protocol(request: Request):

    # Validate A2A protocol version.
    version = request.headers.get("A2A-Version")

    if version != A2A_VERSION:

        raise HTTPException(
            status_code=400,
            detail="Unsupported A2A version"
        )

    # Validate POST content type.
    if request.method == "POST":

        content_type = request.headers.get(
            "Content-Type",
            ""
        )

        media_type = (
            content_type
            .split(";", 1)[0]
            .strip()
            .lower()
        )

        if media_type != A2A_MEDIA_TYPE:

            raise HTTPException(
                status_code=415,
                detail="Unsupported media type"
            )
