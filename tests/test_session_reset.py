import os
from unittest.mock import AsyncMock
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from app.config import Settings
from app.main import build_parser
from app import site




def test_reset_deletes_current_profile_and_reuses_new_one(tmp_path):
    settings = Settings(browser_profile_directory=str(tmp_path), browser_engine='camoufox')
    current = site.browser_profile_path(settings, 'test')
    (current / 'cookies.sqlite').write_text('old session')
    other = site.browser_profile_path(settings, 'other')
    (other / 'cookies.sqlite').write_text('other task')
    assert site.reset_browser_profile(settings, 'test') is True
    assert not current.exists()
    assert set(current.parent.iterdir()) == {other}
    new = site.browser_profile_path(settings, 'test')
    assert new == current and list(new.iterdir()) == []
    (new / 'cookies.sqlite').write_text('new session')
    assert (site.browser_profile_path(settings, 'test') / 'cookies.sqlite').read_text() == 'new session'
    assert (other / 'cookies.sqlite').read_text() == 'other task'


def test_reset_without_existing_profile(tmp_path):
    settings = Settings(browser_profile_directory=str(tmp_path))
    assert site.reset_browser_profile(settings, 'test') is False
    assert site.browser_profile_path(settings, 'test').is_dir()


def test_reset_refuses_live_firefox_profile(tmp_path):
    settings = Settings(browser_profile_directory=str(tmp_path), browser_engine='camoufox')
    current = site.browser_profile_path(settings, 'test')
    try:
        (current / 'parent.lock').symlink_to(f'127.0.0.1:+{os.getpid()}')
    except OSError as exc:
        if os.name == 'nt' and exc.winerror == 1314:
            pytest.skip('Windows user has no symbolic-link privilege; native lock tested separately')
        raise
    with pytest.raises(site.SiteCheckError, match='BROWSER_PROFILE_IN_USE'):
        site.reset_browser_profile(settings, 'test')
    assert current.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="POSIX Firefox symlink PID semantics")
def test_reset_allows_stale_firefox_lock(tmp_path, monkeypatch):
    settings = Settings(browser_profile_directory=str(tmp_path), browser_engine='camoufox')
    current = site.browser_profile_path(settings, 'test')
    (current / 'parent.lock').symlink_to('127.0.0.1:+123456789')
    def missing(pid, sig):
        raise ProcessLookupError()
    monkeypatch.setattr(site.os, 'kill', missing)
    assert site.reset_browser_profile(settings, 'test') is True
    assert not current.exists()




def test_reset_refuses_symlink_profile(tmp_path):
    settings = Settings(browser_profile_directory=str(tmp_path))
    current = site.browser_profile_path(settings, 'test')
    current.rmdir()
    target = tmp_path / 'unrelated'
    target.mkdir()
    (target / 'keep').write_text('keep')
    try:
        current.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        if os.name == 'nt' and exc.winerror == 1314:
            pytest.skip('Windows user has no symbolic-link privilege')
        raise
    with pytest.raises(site.SiteCheckError, match='BROWSER_PROFILE_RESET_FAILED'):
        site.reset_browser_profile(settings, 'test')
    assert (target / 'keep').exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX Firefox record-lock regression")
def test_reset_refuses_posix_locked_profile(tmp_path):
    import subprocess
    import sys
    settings = Settings(browser_profile_directory=str(tmp_path))
    current = site.browser_profile_path(settings, 'test')
    lock = current / '.parentlock'
    lock.touch()
    code = 'import fcntl,sys; f=open(sys.argv[1],"r+b"); fcntl.lockf(f,fcntl.LOCK_EX); print("locked",flush=True); sys.stdin.read()'
    child = subprocess.Popen([sys.executable, '-c', code, str(lock)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'locked'
        with pytest.raises(site.SiteCheckError, match='BROWSER_PROFILE_IN_USE'):
            site.reset_browser_profile(settings, 'test')
        assert current.exists()
    finally:
        child.communicate('release', timeout=5)
    assert site.reset_browser_profile(settings, 'test') is True




@pytest.mark.skipif(os.name != "nt", reason="Windows native Firefox lock")
def test_reset_refuses_windows_exclusive_parent_lock(tmp_path):
    import ctypes
    from ctypes import wintypes
    settings = Settings(browser_profile_directory=str(tmp_path), browser_engine='camoufox')
    current = site.browser_profile_path(settings, 'test')
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    handle = api.CreateFileW(str(current/'parent.lock'), 0xC0000000, 0, None, 4, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    try:
        with pytest.raises(site.SiteCheckError, match='BROWSER_PROFILE_IN_USE'):
            site.reset_browser_profile(settings, 'test')
        assert current.is_dir()
    finally:
        api.CloseHandle(handle)
    assert site.reset_browser_profile(settings, 'test')


@pytest.mark.parametrize('task_id', ['../other', 'child/other', '', 'UPPER'])
def test_browser_profile_rejects_invalid_task_ids_without_creating_folders(tmp_path, task_id):
    settings = Settings(browser_profile_directory=str(tmp_path), browser_engine='camoufox')
    with pytest.raises(site.SiteCheckError, match='BROWSER_PROFILE_RESET_FAILED'):
        site.browser_profile_path(settings, task_id)
    with pytest.raises(site.SiteCheckError, match='BROWSER_PROFILE_RESET_FAILED'):
        site.reset_browser_profile(settings, task_id)
    assert list(tmp_path.iterdir()) == []


def test_browser_profile_rejects_symlinked_parent_without_touching_target(tmp_path):
    settings = Settings(browser_profile_directory=str(tmp_path/'profiles'),
                        browser_engine='camoufox')
    root = tmp_path/'profiles'
    root.mkdir()
    outside = tmp_path/'outside'
    outside.mkdir()
    (outside/'keep').write_text('private')
    try:
        (root/'camoufox').symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip('El sistema no permite symlinks: ' + type(exc).__name__)
    with pytest.raises(site.SiteCheckError, match='BROWSER_PROFILE_RESET_FAILED'):
        site.browser_profile_path(settings, 'client')
    with pytest.raises(site.SiteCheckError, match='BROWSER_PROFILE_RESET_FAILED'):
        site.reset_browser_profile(settings, 'client')
    assert (outside/'keep').read_text() == 'private'
    assert not (outside/'client').exists()


def test_browser_profile_rejects_redirected_existing_profile(tmp_path):
    settings = Settings(browser_profile_directory=str(tmp_path), browser_engine='camoufox')
    first = site.browser_profile_path(settings, 'client')
    first.rmdir()
    outside = tmp_path/'outside'
    outside.mkdir()
    try:
        first.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('Symlinks no disponibles en este sistema')
    with pytest.raises(site.SiteCheckError, match='BROWSER_PROFILE_RESET_FAILED'):
        site.browser_profile_path(settings, 'client')
    assert first.is_symlink() and outside.is_dir()
