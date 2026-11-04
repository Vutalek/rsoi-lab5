import os
import jwt
from fastapi import HTTPException, Request


def authenticate(request: Request):
    path = request.url.path.rstrip("/")
    if not path.startswith("/api/") or path in {"/api/v1/authorize", "/api/v1/callback"}:
        return
    try:
        scheme, token = request.headers.get("Authorization", "").split()
        if scheme.lower() != "bearer":
            raise ValueError("Missing bearer token")
        key = jwt.PyJWKSet.from_json(os.environ["OIDC_JWKS"])[jwt.get_unverified_header(token)["kid"]]
        claims = jwt.decode(
            token, key.key, algorithms=["RS256"],
            issuer=os.environ["OIDC_ISSUER"], audience=os.environ.get("OIDC_AUDIENCE", "rsoi-api"),
            options={"require": ["exp", "sub", "preferred_username"]},
        )
        username = claims["preferred_username"]
        if not isinstance(username, str) or not username:
            raise ValueError("Missing username")
        return username
    except (jwt.PyJWTError, ValueError, KeyError, TypeError, OverflowError):
        raise HTTPException(401, "Invalid or missing access token", headers={"WWW-Authenticate": "Bearer"})
