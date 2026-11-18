"""Offline tests for encrypted portable state backups."""
import json
from pathlib import Path
import sqlite3

import pytest

from app.desktop.private_backup import BackupError, export_backup, restore_backup


def _fixture(root):
    (root / 'data' / 'appointment-budget').mkdir(parents=True, exist_ok=True)
    (root / 'tasks.yml').write_text(
        "tasks:\n"
        "  - id: person_test\n"
        "    label: Example\n"
        "    notifications:\n"
        "      telegram:\n"
        "        enabled: true\n"
        "        secret_ref: notifications-local-only\n"
        "settings: {}\n"
        "desktop: {language: es, dark: true}\n",
        encoding='utf-8',
    )
    (root / 'data' / 'proxy-profiles.json').write_text(
        json.dumps({'proxy_profiles': [{'id':'proxy_test', 'server':'http://test.example:8080',
                                       'label':'Test', 'username':'private-user', 'password':'private-pass'}],
                    'assignments': {}}),
        encoding='utf-8',
    )
    (root / 'data' / 'workers-config.json').write_text(
        json.dumps({'rows': [{'active': True, 'profile_id':'person_test','proxy_id':'proxy_test'}]}),
        encoding='utf-8',
    )
    (root / 'data' / 'appointment-budget' / 'person_test.json').write_text(
        '{"attempts":2}', encoding='utf-8',
    )
    db = root / 'data' / 'state.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS demo (message TEXT)')
        conn.execute('INSERT INTO demo VALUES (?)', ('private database state',))


def test_encrypted_backup_roundtrip_and_private_credentials(tmp_path):
    from yaml import safe_load
    root = tmp_path / 'original'
    _fixture(root)
    archive = tmp_path / 'backup.cehbackup'
    assert export_backup(root, archive, 'Safe password 123456') == 5
    data = archive.read_bytes()
    for text in [b'person_test', b'private-pass', b'private database state',
                 b'notifications-local-only']:
        assert text not in data
    restored = tmp_path / 'new'
    assert restore_backup(restored, archive, 'Safe password 123456') == 5
    profiles = safe_load((restored/'tasks.yml').read_text(encoding='utf-8'))
    assert profiles['desktop']['dark'] is True
    assert profiles['tasks'][0]['notifications']['telegram']['enabled'] is False
    assert profiles['tasks'][0]['notifications']['telegram']['secret_ref'] == ''
    restored_proxy = json.loads((restored/'data/proxy-profiles.json').read_text(encoding='utf-8'))
    assert restored_proxy['proxy_profiles'][0]['password'] == 'private-pass'
    assert json.loads((restored/'data/workers-config.json').read_text())['rows'][0]['active']
    assert (restored/'data/appointment-budget/person_test.json').exists()
    with sqlite3.connect(restored / 'data/state.db') as conn:
        assert conn.execute('SELECT message FROM demo').fetchone()[0] == 'private database state'


def test_wrong_password_and_tampering_never_write_profiles(tmp_path):
    root = tmp_path / 'original'
    _fixture(root)
    archive = tmp_path / 'state.cehbackup'
    export_backup(root, archive, 'Safe password 123456')
    target = tmp_path / 'destination'
    with pytest.raises(BackupError, match='Contraseña incorrecta'):
        restore_backup(target, archive, 'Wrong password 1234')
    assert not (target / 'tasks.yml').exists()
    corrupted = tmp_path / 'tampered.cehbackup'
    bits = bytearray(archive.read_bytes())
    bits[-1] ^= 1
    corrupted.write_bytes(bits)
    with pytest.raises(BackupError, match='respaldo alterado'):
        restore_backup(target, corrupted, 'Safe password 123456')
    assert not (target / 'tasks.yml').exists()


def test_restoration_needs_explicit_overwrite_and_creates_safety_copy(tmp_path):
    root = tmp_path / 'current'
    _fixture(root)
    archive = tmp_path / 'state.cehbackup'
    export_backup(root, archive, 'Safe password 123456')
    (root / 'tasks.yml').write_text('tasks: []\n', encoding='utf-8')
    with pytest.raises(BackupError, match='confirmar'):
        restore_backup(root, archive, 'Safe password 123456')
    assert (root / 'tasks.yml').read_text() == 'tasks: []\n'
    assert restore_backup(root, archive, 'Safe password 123456', allow_replace=True) == 5
    backups = list((root / 'data' / 'backups').glob('*.cehbackup'))
    assert len(backups) == 1
    recovered = tmp_path / 'before'
    restore_backup(recovered, backups[0], 'Safe password 123456')
    assert (recovered / 'tasks.yml').read_text().startswith('tasks: []')


def test_existing_archive_is_never_silently_replaced(tmp_path):
    root = tmp_path / 'root'
    _fixture(root)
    archive = tmp_path / 'state.cehbackup'
    export_backup(root, archive, 'Safe password 123456')
    before = archive.read_bytes()
    with pytest.raises(BackupError, match='Ya existe'):
        export_backup(root, archive, 'Another safe password 1234')
    assert archive.read_bytes() == before
