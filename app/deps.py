from fastapi import Depends, Header, HTTPException

import firebase_admin.auth as firebase_auth


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization.split(" ", 1)[1].strip()


def verify_firebase_token(token: str) -> dict:
    try:
        return firebase_auth.verify_id_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


async def get_current_user(authorization: str | None = Header(None)) -> dict:
    token = _bearer_token(authorization)
    decoded = verify_firebase_token(token)
    uid = decoded.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return {
        "uid": uid,
        "email": decoded.get("email"),
        "token": token,
    }


def is_admin_uid(uid: str, admin_uids: frozenset[str]) -> bool:
    return uid in admin_uids
