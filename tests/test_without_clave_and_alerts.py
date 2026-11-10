"""'Sin Cl@ve' profiles and the new precise alerts (Cod. Oper / Cl@ve-only / preferred office)."""
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import TIE_PROCEDURE
from app.desktop.profiles import ProfileStore, ProfileValidationError
from app.notifications import (CLAVE_ONLY_EVIDENCE, EVENTS, RESTRICTION_ACTION, EventRouter, make_event,
                               madrid_until_midnight, state_event, telegram_message)

CATALOG = Path(__file__).resolve().parents[1] / 'catalogs' / 'snapshot-2026-08-12.json'


def profile(access_mode='without_clave', fill_mode='manual'):
    return dict(label='Sin clave', request=dict(access_mode=access_mode, clave_method='movil', no_slots_mode='salir',
                                                  applicant_no_slots_mode='wait', province='Barcelona',
                                                  procedure=TIE_PROCEDURE, subprocedure=None),
                applicant=dict(fill_mode=fill_mode, document_type='NIE', document_number='X1234567L',
                               full_name='ANA PEREZ', nationality='PERU', contact=dict(phone='600123456', email='a@b.com')))


def test_without_clave_profile_saves_loads_and_keeps_manual_data():
    with tempfile.TemporaryDirectory() as d:
        store = ProfileStore(Path(d) / 'p.yml', CATALOG)
        store.save_profile(None, profile(), revision=store.revision())
        task = store.load()[0]
        assert task.access_mode == 'without_clave' and not task.errors and task.applicant_fill_mode == 'manual'


def test_without_clave_cannot_copy_from_session():
    with tempfile.TemporaryDirectory() as d:
        store = ProfileStore(Path(d) / 'p.yml', CATALOG)
        try:
            store.save_profile(None, profile(fill_mode='copy'), revision=store.revision())
        except ProfileValidationError:
            return
        raise AssertionError('copy mode must be rejected for without_clave')


def test_gui_save_does_not_wipe_office_preference():
    with tempfile.TemporaryDirectory() as d:
        store = ProfileStore(Path(d) / 'p.yml', CATALOG)
        data = profile(); data['request']['office'] = 'CNP COMISARIA GRANOLLERS, RICOMA, 65, GRANOLLERS'
        pid = store.save_profile(None, data, revision=store.revision())
        edited = profile(); edited['label'] = 'Renombrado'  # the editor no longer sends request.office
        store.save_profile(pid, edited, revision=store.revision())
        assert store.raw_profile(pid)['request']['office'].startswith('CNP COMISARIA GRANOLLERS')


def test_telegram_inbox_switch_is_stored_and_survives_preference_saves():
    with tempfile.TemporaryDirectory() as d:
        store = ProfileStore(Path(d) / 'p.yml', CATALOG)
        assert store.telegram_inbox_enabled() is False
        store.save_telegram_inbox(True)
        store.save_preferences(dark=True, diagnostics=False, sound=True, language='es')
        assert store.telegram_inbox_enabled() is True
        assert 'telegram_profiles' not in store.preferences()  # existing preference contract unchanged


def test_restriction_and_clave_only_events():
    waiting = dict(mode='waiting', next_action=RESTRICTION_ACTION, evidence='x')
    assert state_event(waiting) == 'restriction'
    assert state_event(dict(mode='waiting', next_action='Пауза между попытками')) is None
    assert state_event(dict(mode='working', evidence=CLAVE_ONLY_EVIDENCE, next_action='x')) == 'clave_only'
    assert state_event(dict(waiting, paused=True)) is None
    assert {'restriction', 'clave_only'} <= set(EVENTS)


def test_informational_events_do_not_repeat_on_every_reload():
    router = EventRouter()
    waiting = dict(mode='waiting', next_action=RESTRICTION_ACTION, run_id='r1')
    idle = dict(mode='working', run_id='r1', screen='Проверяем страницу', next_action='x')
    sent = []
    for _ in range(5):
        sent.append(router.observe(waiting)); router.observe(idle)
    assert sent.count('restriction') == 1


def test_restriction_message_recommends_waiting_until_madrid_midnight():
    event = make_event('restriction', 'Mi perfil', 'Barcelona', 'es')
    assert 'cod. oper' in event['message'].lower() and '00:00' in event['message']
    clock, hours, minutes = madrid_until_midnight(datetime(2026, 11, 9, 22, 30, tzinfo=ZoneInfo('Europe/Madrid')))
    assert (clock, hours, minutes) == ('22:30', 1, 30)
    # same instant expressed in another timezone gives the same answer
    utc = datetime(2026, 11, 9, 21, 30, tzinfo=ZoneInfo('UTC'))
    assert madrid_until_midnight(utc) == ('22:30', 1, 30)


def test_preferred_office_is_starred_and_listed_first():
    event = make_event('office', 'P', 'Barcelona', 'es')
    offices = ['CNP COMISARIA BADALONA, AVDA. DELS VENTS, 9, BADALONA', 'CNP COMISARIA GRANOLLERS, RICOMA, 65, GRANOLLERS']
    text = telegram_message(event, 'es', offices=offices, preferred='granollers')
    lines = [l for l in text.splitlines() if 'CNP' in l]
    assert lines[0].startswith('⭐ ') and 'GRANOLLERS' in lines[0] and lines[1].startswith('• ')
    assert 'Tu oficina preferida' in text
    assert '⭐' not in telegram_message(event, 'es', offices=offices)
