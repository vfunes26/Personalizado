"""Bloque de datos del perfil que encabeza los reportes de Telegram."""
from app.notifications import profile_data_text


def raw():
    return dict(label='Perfil demo',
                request=dict(province='Sevilla', procedure='huellas', access_mode='without_clave', office=''),
                applicant=dict(document_type='NIE', document_number='X1234567L', full_name='MARIA LOPEZ',
                               nationality='PERU', contact=dict(phone='600123456', email='maria@correo.com')))


def test_block_lists_every_stored_value_in_plain_text():
    text = profile_data_text(raw())
    assert text.startswith('📋 Datos del perfil') and text.endswith('\n\n')
    for expected in ('Perfil demo', 'Sevilla', 'Sin Cl@ve', 'cualquiera', 'NIE X1234567L', 'MARIA LOPEZ',
                     'PERU', '600123456', 'maria@correo.com'):
        assert expected in text


def test_missing_data_never_breaks_the_message():
    assert profile_data_text({}) == ''
    assert profile_data_text(None) == ''
    assert profile_data_text({'label': 'Solo nombre'}) == ''