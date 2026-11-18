"""Offline differential-release tests. A portable must remain intact on failure."""
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from app.desktop import portable_delta as delta

OLD = {
    'portable.flag': b'',
    'Cita Extranjeria Helper.exe': b'old-executable',
    '_internal/bundled-browser/camoufox.exe': b'B' * 8192,
    '_internal/bundled-browser/fonts/f1.ttf': b'F' * 4096,
    '_internal/PySide6/core.pyd': b'C' * 1024,
}
NEW = {
    **OLD,
    'Cita Extranjeria Helper.exe': b'new-executable',
    '_internal/PySide6/core.pyd': b'C' * 1024 + b'new-build',
    '_internal/app/desktop/window.pyc': b'added-module',
}


def full_zip(path, entries):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(entries.items()):
            archive.writestr(delta.ZIP_ROOT + name, content)
        archive.writestr(delta.ZIP_ROOT + 'data/', '')
    return path


def old_folder(folder):
    folder.mkdir(parents=True)
    for name, content in OLD.items():
        dest = folder / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    (folder / 'data').mkdir()
    (folder / 'data' / 'tasks.yml').write_text('tasks: private customer data')
    (folder / 'data' / 'state.db').write_bytes(b'secret database')
    return folder


def build_patches(tmp_path):
    old_path = full_zip(tmp_path / 'old.zip', OLD)
    new_path = full_zip(tmp_path / 'new.zip', NEW)
    old = delta.portable_manifest(old_path, '0.3.5')
    package = delta.create_delta(new_path, old, '0.3.5', '0.3.6',
                                 tmp_path / 'new-patch.delta.zip')
    return old_folder(tmp_path / 'old-portable'), package


def test_delta_reuses_unchanged_browser_but_replaces_new_files(tmp_path):
    old, package = build_patches(tmp_path)
    assert package.stat().st_size < (tmp_path / 'new.zip').stat().st_size
    with zipfile.ZipFile(package) as archive:
        manifest = json.loads(archive.read(delta.MANIFEST))
        files = manifest['files']
        assert files['_internal/bundled-browser/camoufox.exe']['action'] == 'reuse'
        assert files['_internal/bundled-browser/fonts/f1.ttf']['action'] == 'reuse'
        assert files['Cita Extranjeria Helper.exe']['action'] == 'replace'
        assert files['_internal/app/desktop/window.pyc']['action'] == 'replace'
        assert not any('bundled-browser/' in name for name in archive.namelist())
    assert delta.check_delta_base(old, package, '0.3.5', '0.3.6')


def test_stage_creates_new_verified_folder_without_touching_private_data(tmp_path):
    old, package = build_patches(tmp_path)
    old_exe = (old / 'Cita Extranjeria Helper.exe').read_bytes()
    candidate = delta.stage_delta(old, package, '0.3.5', '0.3.6',
                                  verifier=lambda _p: True)
    assert candidate.parent == old.parent and candidate != old
    assert candidate.name.endswith('0.3.6 (preparado)')
    for name, value in NEW.items():
        assert (candidate / name).read_bytes() == value
    assert (old / 'Cita Extranjeria Helper.exe').read_bytes() == old_exe
    assert (old / 'data' / 'tasks.yml').read_text() == 'tasks: private customer data'
    assert (old / 'data' / 'state.db').read_bytes() == b'secret database'
    assert list((candidate / 'data').iterdir()) == []
    with pytest.raises(delta.DeltaError):
        delta.stage_delta(old, package, '0.3.5', '0.3.6',
                          verifier=lambda _p: True)
    assert (candidate / 'Cita Extranjeria Helper.exe').read_bytes() == b'new-executable'


def test_signed_delta_rejects_changed_old_browser_without_overwriting(tmp_path):
    old, package = build_patches(tmp_path)
    (old / '_internal/bundled-browser/camoufox.exe').write_bytes(b'tampered')
    with pytest.raises(delta.DeltaIncompatible):
        delta.check_delta_base(old, package, '0.3.5', '0.3.6')
    with pytest.raises(delta.DeltaIncompatible):
        delta.stage_delta(old, package, '0.3.5', '0.3.6',
                          verifier=lambda _p: True)
    assert not any(p.name.endswith('(preparado)') for p in tmp_path.iterdir())


def test_bad_signature_blocks_staging_before_touching_files(tmp_path):
    old, package = build_patches(tmp_path)
    with pytest.raises(ValueError, match='rejected signature'):
        delta.stage_delta(old, package, '0.3.5', '0.3.6',
                          verifier=lambda _p: (_ for _ in ()).throw(
                              ValueError('rejected signature')))
    assert (old / 'data' / 'tasks.yml').is_file()


@pytest.mark.parametrize('name', ['../outside.exe', 'data/tasks.yml',
                                   'folder/../../outside', 'CON.txt',
                                   'folder\\malicious', '_internal/a/./b'])
def test_untrusted_delta_paths_are_rejected(name):
    with pytest.raises(delta.DeltaError):
        delta._path(name)


def test_full_portable_cannot_contain_private_tasks(tmp_path):
    bad = full_zip(tmp_path / 'bad.zip', {**OLD, 'tasks.yml': b'customer info'})
    with pytest.raises(delta.DeltaError):
        delta.portable_manifest(bad, '0.3.6')


def test_duplicate_casefold_paths_in_full_archive_are_rejected(tmp_path):
    duplicate = full_zip(tmp_path / 'bad.zip', {**OLD, 'A/x.pyc': b'x', 'a/X.pyc': b'y'})
    with pytest.raises(delta.DeltaError):
        delta.portable_manifest(duplicate, '0.3.5')


def test_manifest_rejects_version_mismatch_and_prevents_staging(tmp_path):
    old, package = build_patches(tmp_path)
    with pytest.raises(delta.DeltaError):
        delta.check_delta_base(old, package, '0.3.4', '0.3.6')
    with pytest.raises(delta.DeltaError):
        delta.check_delta_base(old, package, '0.3.5', '0.3.7')


def test_missing_changed_payload_is_rejected(tmp_path):
    old, package = build_patches(tmp_path)
    bad = tmp_path / 'missing.delta.zip'
    with zipfile.ZipFile(package) as inp, zipfile.ZipFile(bad, 'w') as out:
        out.writestr(delta.MANIFEST, inp.read(delta.MANIFEST))
    with pytest.raises(delta.DeltaError):
        delta.check_delta_base(old, bad, '0.3.5', '0.3.6')


def test_changed_payload_hash_checked_before_folder_published(tmp_path):
    old, package = build_patches(tmp_path)
    altered = tmp_path / 'tampered.delta.zip'
    with zipfile.ZipFile(package) as inp, zipfile.ZipFile(altered, 'w') as out:
        for filename in inp.namelist():
            raw = inp.read(filename)
            if filename.endswith('Cita Extranjeria Helper.exe'):
                raw = b'evil-executable'
            out.writestr(filename, raw)
    with pytest.raises(delta.DeltaError):
        delta.stage_delta(old, altered, '0.3.5', '0.3.6',
                          verifier=lambda _p: True)
    assert (old / 'Cita Extranjeria Helper.exe').read_bytes() == b'old-executable'
    assert not any(p.name.endswith('(preparado)') for p in tmp_path.iterdir())


def test_only_manifest_is_needed_from_previous_release(tmp_path):
    old_zip = full_zip(tmp_path / 'old.zip', OLD)
    prior = delta.portable_manifest(old_zip, '0.3.5')
    manifest_path = tmp_path / 'old-files.json'
    manifest_path.write_text(json.dumps(prior))
    old_zip.unlink()  # build the patch with only the small previous manifest
    new_zip = full_zip(tmp_path / 'new.zip', NEW)
    patch = delta.create_delta(new_zip, manifest_path, '0.3.5', '0.3.6',
                               tmp_path / 'patch.delta.zip')
    assert patch.is_file()
    assert delta.delta_asset_name('extranjeria-cita-helper-0.3.6-windows-x64-portable.zip','0.3.5').endswith(
        'windows-x64-portable-from-0.3.5.delta.zip')


def test_offline_release_builder_needs_only_small_previous_manifest(tmp_path):
    from scripts.build_portable_delta import build
    from scripts.attest_release import packages
    old_zip = full_zip(tmp_path / 'old.zip', OLD)
    old_manifest = tmp_path / 'previous.json'
    old_manifest.write_text(json.dumps(delta.portable_manifest(old_zip, '0.3.5')))
    old_zip.unlink()
    new_name = 'extranjeria-cita-helper-0.3.6-windows-x64-portable.zip'
    new_zip = full_zip(tmp_path / new_name, NEW)
    manifest, patch = build(new_zip, '0.3.6', previous=('0.3.5', old_manifest))
    assert manifest.name == 'portable-manifest-0.3.6.json'
    assert patch is not None and patch.name.endswith('from-0.3.5.delta.zip')
    assert patch.stat().st_size < new_zip.stat().st_size
    assert manifest in packages(tmp_path)
    assert patch in packages(tmp_path)
    for path in (manifest, patch):
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream,'sha256').hexdigest()
        assert path.with_name(path.name+'.sha256').read_text() == (
            digest+'  '+path.name+'\n'
        )
