"""Telegram template parser: codes, normalisation, validation and privacy of the summary."""
from pathlib import Path

from app.config import _NIE_LETTERS, REGRESO_PROCEDURE, TIE_PROCEDURE
from app.profile_intake import Catalog, looks_like_submission, parse_submission, template_text

CATALOG = Catalog.load(Path(__file__).resolve().parents[1] / 'catalogs' / 'snapshot-2026-08-12.json')


def nie(n=1234567):
    number = f'{n:07d}'
    return 'X' + number + _NIE_LETTERS[int('0' + number) % 23]


def block(**over):
    values = dict(PERFIL='Prueba', TRAMITE='tie', PROVINCIA='08', OFICINA='cualquiera', ACCESO='certificado',
                  NIE=nie(), NOMBRE='María  López Ñandú', NACIONALIDAD='Perú', TELEFONO='+34 600-123-456',
                  EMAIL='Maria@Correo.COM')
    values.update(over)
    return '\n'.join(f'{k}: {v}' for k, v in values.items() if v is not None)


def test_template_is_itself_a_valid_submission_shape():
    assert looks_like_submission(template_text())


def test_codes_and_normalisation():
    result = parse_submission('/perfil\n' + block(), CATALOG)
    assert result.ok, result.errors
    f = result.fields
    assert f['request']['procedure'] == TIE_PROCEDURE and f['request']['province'] == 'Barcelona'
    assert f['request']['office'] == '' and f['request']['access_mode'] == 'certificate'
    assert f['applicant']['full_name'] == 'MARIA LOPEZ NANDU'
    assert f['applicant']['contact'] == dict(phone='34600123456', email='maria@correo.com')
    assert f['applicant']['nationality'] == 'PERU'


def test_every_access_code():
    for text, mode, method in [('CLAVE_MOVIL', 'clave', 'movil'), ('clave permanente', 'clave', 'permanente'),
                               ('SIN_CLAVE', 'without_clave', 'movil'), ('cert', 'certificate', 'movil')]:
        r = parse_submission(block(ACCESO=text), CATALOG)
        assert r.ok and (r.fields['request']['access_mode'], r.fields['request']['clave_method']) == (mode, method)
    assert not parse_submission(block(ACCESO='CLAVE'), CATALOG).ok  # ambiguous on purpose


def test_province_by_name_alias_and_code():
    for value in ('Barcelona', 'bcn', '08', '8'):
        assert parse_submission(block(PROVINCIA=value), CATALOG).fields['request']['province'] == 'Barcelona'
    assert parse_submission(block(PROVINCIA='Tenerife'), CATALOG).fields['request']['province'] == 'S.Cruz Tenerife'


def test_office_any_specific_number_and_other_provinces():
    assert parse_submission(block(OFICINA='granollers'), CATALOG).fields['request']['office'].startswith('CNP COMISARIA GRANOLLERS')
    assert 'BADALONA' in parse_submission(block(OFICINA='1'), CATALOG).fields['request']['office']
    bad = parse_submission(block(OFICINA='99'), CATALOG)
    assert not bad.ok
    madrid = parse_submission(block(PROVINCIA='Madrid', OFICINA='Aluche'), CATALOG)
    assert madrid.ok and madrid.fields['request']['office'] == 'ALUCHE' and madrid.warnings


def test_regreso_with_dni_and_tie_rejects_non_nie():
    ok = parse_submission(block(TRAMITE='REGRESO', NIE=None, DNI='12345678Z', NACIONALIDAD=None), CATALOG)
    assert ok.ok, ok.errors
    assert ok.fields['request']['procedure'] == REGRESO_PROCEDURE and ok.fields['applicant']['document_type'] == 'DNI'
    assert not parse_submission(block(NIE=None, DNI='12345678Z'), CATALOG).ok


def test_copy_mode_needs_no_identity_but_not_with_sin_clave():
    ok = parse_submission(block(RELLENO='ACCESO', NIE=None, NOMBRE=None), CATALOG)
    assert ok.ok and ok.fields['applicant']['fill_mode'] == 'copy'
    assert not parse_submission(block(RELLENO='ACCESO', ACCESO='SIN_CLAVE', NIE=None, NOMBRE=None), CATALOG).ok


def test_errors_are_collected_and_specific():
    r = parse_submission(block(NIE='X1234567A', NOMBRE='Ana2', NACIONALIDAD='Narnia', TELEFONO='12', EMAIL='x', FOO='1'), CATALOG)
    text = ' '.join(r.errors)
    assert not r.ok
    for word in ('NIE', 'NOMBRE', 'NACIONALIDAD', 'TELEFONO', 'EMAIL', 'Campo desconocido'):
        assert word in text


def test_summary_never_contains_full_personal_data():
    r = parse_submission(block(), CATALOG)
    assert nie() not in r.summary and '34600123456' not in r.summary and 'maria@' not in r.summary
    assert 'LOPEZ' not in r.summary.upper() and 'NANDU' not in r.summary.upper()
