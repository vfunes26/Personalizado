"""Final offline Windows-portable data-preservation and recovery contracts."""
import hashlib
import json
import shutil
import sqlite3

import pytest
import yaml

from app.desktop.private_backup import BackupError, export_backup, restore_backup
from scripts.verify_private_migration import MigrationError, verify_migration


PASSWORD = 'Respaldo seguro 16 ajustes'


def seeded_private_root(root):
    data = root / 'data'
    data.mkdir(parents=True)
    (root / 'tasks.yml').write_text(yaml.safe_dump({
        'tasks': [
            {'id': 'person_01', 'label': 'Perfil 1',
             'notifications': {'telegram': {
                 'enabled': True, 'secret_ref': 'notifications-impersonal',
             }}},
            {'id': 'person_02', 'label': 'A.B.',
             'notifications': {'telegram': {
                 'enabled': True, 'secret_ref': 'notifications-impersonal2',
             }}},
        ],
        'desktop': {'language': 'es', 'dark': True},
        'settings': {},
    }, allow_unicode=True), encoding='utf-8')
    (data / 'gmail-settings.json').write_text(json.dumps({
        'sender': 'sender@gmail.com',
        'recipients': ['authorized@example.com'],
        'secret_ref': 'notifications-' + 'a' * 32,
    }), encoding='utf-8')
    (data / 'proxy-profiles.json').write_text(json.dumps({
        'proxy_profiles': [{'id': 'proxy_a', 'label': 'proxy', 'server': 'http://proxy.invalid:8080'}],
        'assignments': {'person_02': {'proxy_profile_id': 'proxy_a', 'enabled': True}},
    }), encoding='utf-8')
    (data / 'workers-config.json').write_text(json.dumps({
        'rows': [{'profile_id': 'person_02', 'proxy_id': 'proxy_a', 'active': False}],
    }), encoding='utf-8')
    budget = data / 'appointment-budget'
    budget.mkdir()
    (budget / 'person_02.json').write_text('{"day":"2026-11-18","count":2}')
    with sqlite3.connect(data / 'state.db') as conn:
        conn.execute('CREATE TABLE appointment_test (value TEXT)')
        conn.execute('INSERT INTO appointment_test VALUES (?)', ('historical state',))
    return root


def test_final_backup_preserves_profiles_budget_proxy_workers_and_sqlite(tmp_path):
    original = seeded_private_root(tmp_path / 'original')
    archive = tmp_path / 'backup.cehbackup'
    assert export_backup(original, archive, PASSWORD) == 6
    before = {
        p.relative_to(original).as_posix(): hashlib.sha256(p.read_bytes()).digest()
        for p in original.rglob('*') if p.is_file()
    }
    target = tmp_path / 'nuevo-portable'
    (target / 'portable.flag').parent.mkdir(parents=True)
    (target / 'portable.flag').touch()
    assert restore_backup(target, archive, PASSWORD) == 6
    profiles = yaml.safe_load((target / 'tasks.yml').read_text(encoding='utf-8'))
    assert [p['label'] for p in profiles['tasks']] == ['Perfil 1', 'A.B.']
    assert profiles['desktop']['language'] == 'es'
    assert all(not t['notifications']['telegram']['enabled'] for t in profiles['tasks'])
    assert all(t['notifications']['telegram']['secret_ref'] == '' for t in profiles['tasks'])
    gmail = json.loads((target / 'data/gmail-settings.json').read_text(encoding='utf-8'))
    assert gmail['sender'] == 'sender@gmail.com'
    assert gmail['recipients'] == ['authorized@example.com']
    assert gmail['secret_ref'] == ''
    proxy = json.loads((target / 'data/proxy-profiles.json').read_text(encoding='utf-8'))
    assert proxy['assignments']['person_02']['proxy_profile_id'] == 'proxy_a'
    workers = json.loads((target / 'data/workers-config.json').read_text(encoding='utf-8'))
    assert workers['rows'][0]['profile_id'] == 'person_02'
    assert json.loads((target / 'data/appointment-budget/person_02.json').read_text())['count'] == 2
    with sqlite3.connect(target / 'data/state.db') as conn:
        assert conn.execute('SELECT value FROM appointment_test').fetchone()[0] == 'historical state'
    # The working original is untouched by both export and import.
    assert before == {
        p.relative_to(original).as_posix(): hashlib.sha256(p.read_bytes()).digest()
        for p in original.rglob('*') if p.is_file()
    }
    assert not (target / 'data/profile-deletions.jsonl').exists()


def test_final_import_refuses_overwrite_or_wrong_password(tmp_path):
    original = seeded_private_root(tmp_path / 'original')
    archive = tmp_path / 'backup.cehbackup'
    export_backup(original, archive, PASSWORD)
    target = seeded_private_root(tmp_path / 'existing')
    before = (target / 'tasks.yml').read_bytes()
    with pytest.raises(BackupError, match='confirmar'):
        restore_backup(target, archive, PASSWORD)
    with pytest.raises(BackupError, match='Contraseña incorrecta'):
        restore_backup(target, archive, 'Another wrong 1234', allow_replace=True)
    assert (target / 'tasks.yml').read_bytes() == before


def test_recompiled_portable_data_is_byte_identical(tmp_path):
    old = tmp_path / 'old' / 'data'
    new = tmp_path / 'candidate' / 'data'
    old.mkdir(parents=True)
    (old / 'tasks.yml').write_bytes('nombre: Á.B.\n'.encode('utf-8'))
    (old / 'gmail-settings.json').write_text('{"secret_ref":"private"}')
    nested = old / 'appointment-budget'
    nested.mkdir()
    (nested / 'daily.json').write_bytes(b'{"remaining":12}')
    (old / 'state.db').write_bytes(b'SQLite example bytes')
    shutil.copytree(old, new)
    assert verify_migration(old, new) == 4
    assert verify_migration(old, old) == 4
    (new / 'tasks.yml').write_bytes(b'wrong content')
    with pytest.raises(MigrationError, match='no coinciden'):
        verify_migration(old, new)
    assert (old / 'tasks.yml').read_bytes() == 'nombre: Á.B.\n'.encode('utf-8')


def test_migration_refuses_live_sqlite_wal_and_unknown_extra_file(tmp_path):
    old = tmp_path / 'old'
    new = tmp_path / 'new'
    old.mkdir()
    new.mkdir()
    (old / 'tasks.yml').write_text('tasks: []\n')
    (new / 'tasks.yml').write_text('tasks: []\n')
    (old / 'state.db-wal').write_bytes(b'pending SQLite changes')
    with pytest.raises(MigrationError, match='SQLite'):
        verify_migration(old, new)
    (old / 'state.db-wal').unlink()
    (new / 'unknown.file').write_text('not in old data')
    with pytest.raises(MigrationError):
        verify_migration(old, new)


def test_migration_refuses_links_to_external_private_data(tmp_path):
    old = tmp_path / 'old'
    new = tmp_path / 'new'
    old.mkdir()
    new.mkdir()
    secret = tmp_path / 'secret.txt'
    secret.write_text('should never be followed')
    try:
        (old / 'external').symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip('La cuenta Windows no permite enlaces simbolicos.')
    with pytest.raises(MigrationError, match='enlazado'):
        verify_migration(old, new)


def test_local_compilation_has_verification_and_recovery_guards():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    control = (root / 'scripts/compilar_portable.ps1').read_text(encoding='utf-8')
    assert 'Get-CimInstance -ClassName Win32_Process' in control
    assert 'verify_private_migration.py' in control
    assert control.count('EjecutarPython $python @($migration,') == 2
    assert 'ComprobarPortable $candidate' in control
    assert 'Get-FileHash -Algorithm SHA256' in control
    assert control.index("ComprobarPortable $candidate") < control.index(
        'Move-Item -LiteralPath $ready -Destination $respaldo')
    assert 'Move-Item -LiteralPath $respaldo -Destination $ready' in control
    assert 'el portable original' in control.lower()
