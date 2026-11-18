"""Verbatim Extranjería selectors; only TIE and Regreso are automated."""
from app.desktop.appointment_catalog import AppointmentCatalog
from app.config import TIE_PROCEDURE, REGRESO_PROCEDURE


def test_full_supplied_catalog_is_packaged_as_data():
    catalog = AppointmentCatalog()
    assert catalog.available
    assert len(catalog.provinces) == 52
    assert sum(len(p["procedures"]) for p in catalog.provinces.values()) == 824
    assert len(list(catalog.offices("Alicante"))) >= 10


def test_province_procedure_office_are_linked_by_original_ids():
    catalog = AppointmentCatalog()
    offices = list(catalog.offices("Alicante"))
    tie_office = next(item for item in offices if item[1] ==
        "CNP Alicante TIE, Campo de Mirra, 6, Alicante")
    tie = list(catalog.procedures("Alicante", tie_office))
    assert any(name == "POLICÍA-TOMA DE HUELLAS (EXPEDICIÓN DE TARJETA) INICIAL, RENOVACIÓN, DUPLICADO Y LEY 14/2013"
               and value == TIE_PROCEDURE and id_ == "4010" for name, value, id_ in tie)
    assert not any(value == REGRESO_PROCEDURE for _name, value, _id in tie)


def test_original_case_accents_punctuation_and_office_names_untouched():
    catalog = AppointmentCatalog()
    all_rows = list(catalog.procedures("Barcelona"))
    assert any(label.startswith("POLICÍA-TOMA DE HUELLAS")
               and value == TIE_PROCEDURE for label, value, _ in all_rows)
    assert any("CNP COMISARIA GRANOLLERS, RICOMA, 65, GRANOLLERS" == name
               for _id, name in catalog.offices("Barcelona"))
    assert "A Coruña" in catalog.province_names()
    assert "Ávila" in catalog.province_names()
