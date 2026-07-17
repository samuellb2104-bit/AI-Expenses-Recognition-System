"""Interactive one-off script to provision the single login this app supports.

Creates the user directly in Supabase Auth (so the password is set/hashed by Supabase,
never touching our database or this terminal's scrollback beyond the getpass prompt),
then links that same user id into our local users/companies/company_members tables so
the rest of the app (which is keyed on our own schema) recognizes them.

Run with: .venv/Scripts/python.exe -m app.db.create_admin_user
"""
from __future__ import annotations

import getpass
import json
import sys
from urllib import error, request

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.company import Company
from app.models.company_member import CompanyMember
from app.models.user import User


def _create_supabase_auth_user(email: str, password: str) -> dict:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not configured in .env.", file=sys.stderr)
        sys.exit(1)

    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users"
    payload = json.dumps({"email": email, "password": password, "email_confirm": True}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "apikey": settings.supabase_service_role_key,
        "Content-Type": "application/json",
    }
    req = request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with request.urlopen(req) as resp:
            return json.loads(resp.read())
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        print(f"Supabase Auth rejected the new user (HTTP {exc.code}): {body}", file=sys.stderr)
        sys.exit(1)
    except error.URLError as exc:
        print(f"Could not reach Supabase Auth: {exc.reason}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    print("=== Provisionar usuario administrador (Supabase Auth) ===")
    email = input("Email: ").strip()
    full_name = input("Nombre completo: ").strip()
    company_name = input("Nombre de la empresa: ").strip()

    password = getpass.getpass("Password: ")
    password_confirm = getpass.getpass("Confirmar password: ")
    if password != password_confirm:
        print("Las contrasenas no coinciden.", file=sys.stderr)
        sys.exit(1)
    if len(password) < 8:
        print("La contrasena debe tener al menos 8 caracteres.", file=sys.stderr)
        sys.exit(1)

    supabase_user = _create_supabase_auth_user(email, password)
    user_id = supabase_user.get("id")
    if not user_id:
        print(f"Respuesta inesperada de Supabase Auth: {supabase_user}", file=sys.stderr)
        sys.exit(1)

    with SessionLocal() as db:
        company = db.query(Company).filter(Company.name == company_name).first()
        if company is None:
            company = Company(name=company_name, contact_email=email)
            db.add(company)
            db.flush()

        user = User(
            id=user_id,
            full_name=full_name,
            email=email,
            password_hash="managed-by-supabase-auth",
            role="admin",
        )
        db.add(user)
        db.flush()

        db.add(CompanyMember(company_id=company.id, user_id=user.id, member_role="owner"))
        db.commit()

    print("\nListo. El usuario ya puede iniciar sesion en el frontend con ese email y password.")
    print(f"user_id={user_id}")
    print(f"company_id={company.id}")


if __name__ == "__main__":
    main()
