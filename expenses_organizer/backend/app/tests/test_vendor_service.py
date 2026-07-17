from app.db.seed import seed_test_company_and_user
from app.db.session import SessionLocal
from app.models.vendor import Vendor
from app.services.vendor_service import create_vendor, get_or_create_vendor, list_vendors, update_vendor


def test_get_or_create_vendor_matches_existing_by_case_insensitive_name():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)

        first = get_or_create_vendor(db, company_id=company.id, name="Panaderia El Trigo")
        db.commit()
        vendor_id = first.id

        second = get_or_create_vendor(db, company_id=company.id, name="  panaderia el trigo  ")
        db.commit()

        assert second.id == vendor_id

        db.query(Vendor).filter(Vendor.id == vendor_id).delete()
        db.commit()


def test_get_or_create_vendor_matches_by_tax_id_over_name():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)

        original = get_or_create_vendor(db, company_id=company.id, name="Distribuidora ABC", tax_id="900123456-7")
        db.commit()
        vendor_id = original.id

        renamed_match = get_or_create_vendor(db, company_id=company.id, name="Distribuidora ABC S.A.S", tax_id="900123456-7")
        db.commit()

        assert renamed_match.id == vendor_id

        db.query(Vendor).filter(Vendor.id == vendor_id).delete()
        db.commit()


def test_create_and_update_and_list_vendors():
    with SessionLocal() as db:
        company, _ = seed_test_company_and_user(db)

        vendor = create_vendor(db, company_id=company.id, name="Tienda de Pruebas")
        assert vendor.name == "Tienda de Pruebas"

        updated = update_vendor(db, vendor_id=vendor.id, company_id=company.id, name="Tienda de Pruebas Actualizada")
        assert updated.name == "Tienda de Pruebas Actualizada"

        vendors = list_vendors(db, company_id=company.id)
        assert any(v.id == vendor.id for v in vendors)

        db.query(Vendor).filter(Vendor.id == vendor.id).delete()
        db.commit()
