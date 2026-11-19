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



def test_every_office_and_procedure_matches_the_original_source_exactly():
    import json

    catalog = AppointmentCatalog()
    source = json.loads(catalog.path.read_text(encoding='utf-8'))
    originals = source['provinces']
    assert catalog.province_names() == [province['name'] for province in originals]
    assert len({province['code'] for province in originals}) == 52
    procedures_seen = 0
    offices_seen = 0
    for province in originals:
        name = province['name']
        expected_offices = list(dict.fromkeys(
            (str(office['id']), office['name'])
            for procedure in province['procedures'] for office in procedure['offices']
        ))
        assert list(catalog.offices(name)) == expected_offices
        actual_procedures = list(catalog.procedures(name))
        assert [(label, code) for label, _value, code in actual_procedures] == [
            (procedure['name'], str(procedure['id'])) for procedure in province['procedures']
        ]
        for procedure in province['procedures']:
            code = str(procedure['id'])
            label = procedure['name']
            for office in procedure['offices']:
                office_key = str(office['id']), office['name']
                assert (label, code) in [
                    (text, item_code) for text, _value, item_code
                    in catalog.procedures(name, office_key)
                ]
                offices_seen += 1
            procedures_seen += 1
    assert procedures_seen == 824
    assert offices_seen == 1823


def test_unknown_office_never_returns_unfiltered_procedures():
    catalog = AppointmentCatalog()
    assert list(catalog.procedures('Alicante', ('not-an-id', 'not-an-office'))) == []
    assert list(catalog.procedures('Alicante', 'not-an-office')) == []
    assert list(catalog.offices('Provincia inventada')) == []
