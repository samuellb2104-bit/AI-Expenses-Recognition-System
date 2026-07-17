from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from urllib import error, request

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.company_member import CompanyMember
from app.models.user import User


class AuthError(RuntimeError):
    pass


@dataclass
class AuthContext:
    user_id: uuid.UUID
    company_id: uuid.UUID
    email: str


def _fetch_supabase_user(access_token: str) -> dict:
    """Validates the access token directly against Supabase Auth. This avoids needing
    a separate JWT secret in this backend and means a revoked/expired session is
    rejected immediately rather than only once a locally-verified token expires."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise AuthError("Supabase is not configured.")

    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/user"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "apikey": settings.supabase_service_role_key,
    }
    req = request.Request(url, headers=headers, method="GET")
    try:
        with request.urlopen(req) as resp:
            return json.loads(resp.read())
    except error.HTTPError as exc:
        raise AuthError("Invalid or expired session.") from exc
    except error.URLError as exc:
        raise AuthError(f"Could not reach Supabase Auth: {exc.reason}") from exc


def resolve_auth_context(db: Session, access_token: str) -> AuthContext:
    supabase_user = _fetch_supabase_user(access_token)
    raw_user_id = supabase_user.get("id")
    email = supabase_user.get("email")
    if not raw_user_id:
        raise AuthError("Invalid session payload.")

    try:
        user_id = uuid.UUID(raw_user_id)
    except ValueError as exc:
        raise AuthError("Invalid session payload.") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("No local account is provisioned for this login.")

    membership = db.query(CompanyMember).filter(CompanyMember.user_id == user.id).first()
    if membership is None:
        raise AuthError("This user is not a member of any company.")

    return AuthContext(user_id=user.id, company_id=membership.company_id, email=email or user.email)
