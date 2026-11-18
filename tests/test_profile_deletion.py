"""Destructive profile actions require confirmation, locking and Gmail audit."""
import json
from pathlib import Path

import pytest
import yaml

from app.desktop.profile_deletion import ProfileDeletionError, ProfileDeletionService
from app.desktop.profiles import ProfileStore
from app.desktop.gmail_service import GmailError


class Mail:
    def __init__(self, enabled=True, failing=False):
        self.enabled = enabled
        self.failing = failing
        self.sent = []

    def read(self):
        return {
            'sender': 'sender@gmail.com',
            'recipients': ['allowed@example.com'],
            'secret_ref': 'fake-ref' if self.enabled else '',
        }

    def send(self, subject, body):
        if self.failing:
            raise GmailError('No se pudo entregar el correo.')
        self.sent.append((subject, body))
        return 1


class Vault:
    def __init__(self):
        self.deleted = []

    def delete(self, ref):
        self.deleted.append(ref)


def seeded(tmp_path):
    tasks = [
        {
            'id': 'profile-one', 'label': 'A.B.',
            'request': {'province': 'Barcelona', 'office': '', 'procedure': 'TEST',
                        'access_mode': 'without_clave'},
            'applicant': {'document_type': 'NIE', 'document_number': 'X0000000T',
                          'full_name': 'EXAMPLE TEST', 'nationality': 'PERU',
                          'contact': {'phone': '600000000', 'email': 'sample@example.com'}},
            'notifications': {'telegram': {'secret_ref': 'notifications-private-only',
                                           'enabled': True}},
        },
        {
            'id': 'profile-two', 'label': 'Perfil 2', 'request': {},
            'applicant': {},
            'notifications': {'telegram': {'secret_ref': 'notifications-shared-other'}},
        },
    ]
    root = Path(tmp_path)
    path = root/'tasks.yml'
    path.write_text(yaml.safe_dump({'tasks': tasks, 'desktop': {'last_profile_id': 'profile-one'}},
                                   allow_unicode=True), encoding='utf-8')
    data = root / 'data'
    data.mkdir(exist_ok=True)
    (data/'proxy-profiles.json').write_text(json.dumps({
        'proxy_profiles': [],
        'assignments': {'profile-one': {'proxy_profile_id': None, 'enabled': False},
                        'profile-two': {'proxy_profile_id': None, 'enabled': False}},
    }), encoding='utf-8')
    (data/'workers-config.json').write_text(json.dumps({
        'rows': [{'profile_id': 'profile-one', 'proxy_id': 'proxy_a', 'active': True},
                 {'profile_id': 'profile-two', 'proxy_id': 'proxy_b', 'active': True}],
    }), encoding='utf-8')
    return ProfileStore(path, root/'catalog.json')


def test_delete_removes_only_selected_profile_and_notifies_allowed_mail(tmp_path):
    store = seeded(tmp_path)
    mail, vault = Mail(), Vault()
    service = ProfileDeletionService(store, mail=mail, vault=vault)
    response = service.delete('profile-one', revision=store.revision(), origin='telegram',
                              protected_profile_id='profile-two')
    assert response['deleted'] and response['emailed']
    saved = yaml.safe_load(store.path.read_text())
    assert [t['id'] for t in saved['tasks']] == ['profile-two']
    assert 'last_profile_id' not in saved['desktop']
    assert 'notifications-private-only' in vault.deleted
    assert 'notifications-shared-other' not in vault.deleted
    assert 'A.B.' in mail.sent[0][1]
    assert 'sample@example.com' in mail.sent[0][1]
    assert 'notifications-private-only' not in mail.sent[0][1]
    audit = (tmp_path/'data/profile-deletions.jsonl').read_text()
    assert 'gmail_sent' in audit
    assert 'EXAMPLE TEST' not in audit
    assert 'X0000000T' not in audit
    workers = json.loads((tmp_path/'data/workers-config.json').read_text())['rows']
    assert not workers[0]['active'] and workers[0]['profile_id'] is None
    assert workers[1]['profile_id'] == 'profile-two'
    proxy = json.loads((tmp_path/'data/proxy-profiles.json').read_text())
    assert 'profile-one' not in proxy['assignments']
    assert 'profile-two' in proxy['assignments']


@pytest.mark.parametrize('condition', ['missing_gmail','busy','protected','stale'])
def test_delete_refuses_without_changing_data(tmp_path, condition):
    store = seeded(tmp_path)
    mail = Mail(enabled=condition != 'missing_gmail')
    service = ProfileDeletionService(
        store, mail=mail, busy_checker=(lambda profile_id: condition == 'busy'),
    )
    revision = store.revision()
    if condition == 'stale':
        store.save_last_profile('profile-two')
    with pytest.raises(ProfileDeletionError):
        service.delete('profile-one', revision=revision, origin='interfaz',
                       protected_profile_id=('profile-one' if condition == 'protected' else None))
    assert [r['id'] for r in store._read()['tasks']] == ['profile-one', 'profile-two']
    assert not mail.sent


def test_email_failure_is_reported_and_audited(tmp_path):
    store = seeded(tmp_path)
    mail = Mail(failing=True)
    service = ProfileDeletionService(store, mail=mail)
    result = service.delete('profile-one', revision=store.revision(), origin='telegram')
    assert result['deleted'] and not result['emailed']
    assert 'gmail_failed' in (tmp_path/'data/profile-deletions.jsonl').read_text()
