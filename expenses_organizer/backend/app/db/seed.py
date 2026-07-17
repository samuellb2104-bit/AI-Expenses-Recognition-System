from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.company_member import CompanyMember
from app.models.user import User
from app.services.expense_category_service import seed_default_expense_categories

SEED_COMPANY_NAME = "Seed Test Company"
SEED_USER_EMAIL = "seed-user@expenses-organizer.local"


def seed_test_company_and_user(db: Session) -> tuple[Company, User]:
    """Ensure a minimal company/user/membership set exists for automated tests.

    This user isn't provisioned in Supabase Auth, so it can't log in through the real
    app -- it only exists so service-layer and API tests have a company_id/user_id to
    work with (API tests override the auth dependency rather than logging in for real).
    """
    company = db.query(Company).filter(Company.name == SEED_COMPANY_NAME).first()
    if company is None:
        company = Company(name=SEED_COMPANY_NAME, contact_email="seed-company@expenses-organizer.local")
        db.add(company)

    user = db.query(User).filter(User.email == SEED_USER_EMAIL).first()
    if user is None:
        user = User(
            full_name="Seed Test User",
            email=SEED_USER_EMAIL,
            password_hash="not-a-real-hash:no-local-login-for-this-user",
        )
        db.add(user)

    db.commit()
    db.refresh(company)
    db.refresh(user)

    membership = (
        db.query(CompanyMember)
        .filter(CompanyMember.company_id == company.id, CompanyMember.user_id == user.id)
        .first()
    )
    if membership is None:
        db.add(CompanyMember(company_id=company.id, user_id=user.id, member_role="owner"))

    seed_default_expense_categories(db, company.id)
    db.commit()
    db.refresh(company)
    db.refresh(user)

    return company, user


if __name__ == "__main__":
    with SessionLocal() as session:
        seeded_company, seeded_user = seed_test_company_and_user(session)
        print(f"company_id={seeded_company.id}")
        print(f"user_id={seeded_user.id}")
