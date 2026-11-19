"""Private data must not be redirected through symbolic links or junctions."""
from pathlib import Path
import pytest
from app.locking import locked_file
from app.desktop.profiles import ProfileStore, ProfileValidationError
from app.desktop.proxy_profiles import ProxyProfileStore, ProxyProfileError


def link_or_skip(alias: Path, real: Path, *, directory=False):
    try:
        alias.symlink_to(real, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip('El sistema no permite crear enlaces simbolicos.')


def test_profile_file_symlink_never_reads_or_changes_external_data(tmp_path, catalog_path):
    real = tmp_path / 'external-tasks.yml'
    real.write_text('tasks: []\n', encoding='utf-8')
    alias = tmp_path / 'tasks.yml'
    link_or_skip(alias, real)
    store = ProfileStore(alias, catalog_path)
    with pytest.raises(ProfileValidationError, match='enlazada'):
        store.revision()
    with pytest.raises(ProfileValidationError, match='enlazada'):
        store.load()
    with pytest.raises(ProfileValidationError, match='enlazada'):
        store._write({'tasks': []}, 'revision-irrelevante')
    assert real.read_text(encoding='utf-8') == 'tasks: []\n'


def test_profile_folder_symlink_is_rejected(tmp_path, catalog_path):
    real = tmp_path / 'private'
    real.mkdir()
    (real / 'tasks.yml').write_text('tasks: []\n', encoding='utf-8')
    alias = tmp_path / 'linked'
    link_or_skip(alias, real, directory=True)
    with pytest.raises(ProfileValidationError, match='enlazada'):
        ProfileStore(alias / 'tasks.yml', catalog_path).load()


def test_proxy_file_symlink_cannot_access_external_data(tmp_path):
    real = tmp_path / 'real-proxies.json'
    contents = '{"proxy_profiles":[],"assignments":{}}'
    real.write_text(contents, encoding='utf-8')
    alias = tmp_path / 'proxy-profiles.json'
    link_or_skip(alias, real)
    store = ProxyProfileStore(alias)
    with pytest.raises(ProxyProfileError, match='enlazada'):
        store.load()
    with pytest.raises(ProxyProfileError, match='enlazada'):
        store._write({'proxy_profiles': [], 'assignments': {}})
    assert real.read_text(encoding='utf-8') == contents


def test_proxy_folder_symlink_is_rejected(tmp_path):
    real = tmp_path / 'real-data'
    real.mkdir()
    alias = tmp_path / 'linked-data'
    link_or_skip(alias, real, directory=True)
    store = ProxyProfileStore(alias / 'proxy-profiles.json')
    with pytest.raises(ProxyProfileError, match='enlazada'):
        store.load()
    assert not (real / 'proxy-profiles.json').exists()


def test_private_lock_refuses_symlink(tmp_path):
    real = tmp_path / 'external.lock'
    real.write_bytes(b'UNCHANGED')
    alias = tmp_path / 'profile.lock'
    link_or_skip(alias, real)
    with pytest.raises(OSError, match='enlace'):
        with locked_file(alias):
            pytest.fail('No se permite abrir enlaces.')
    assert real.read_bytes() == b'UNCHANGED'
