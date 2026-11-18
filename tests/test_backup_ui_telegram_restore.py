"""Telegram must be quiescent before an encrypted private-data restore."""
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from app.desktop import backup_ui
from app.desktop.private_backup import BackupError


class FakeInboxThread:
    def __init__(self, events, *, blocked=False):
        self.events = events
        self.blocked = blocked

    def stop(self):
        self.events.append("stop")

    def join(self, timeout=None):
        self.events.append("join")
        assert timeout is not None and 0 < timeout <= 10

    def is_alive(self):
        self.events.append("is_alive")
        return self.blocked


def make_window(tmp_path, events, *, thread=None):
    window = SimpleNamespace(
        inbox_thread=thread,
        store=SimpleNamespace(path=tmp_path / "tasks.yml"),
    )

    def sync():
        events.append("resume")
        assert window.inbox_thread is None

    window.sync_telegram_inbox = sync
    return window


def test_inbox_stopped_and_joined_before_private_restore(monkeypatch, tmp_path):
    events = []
    thread = FakeInboxThread(events)
    window = make_window(tmp_path, events, thread=thread)

    def restore(root, source, password, *, allow_replace):
        assert events[:3] == ["stop", "join", "is_alive"]
        assert window.inbox_thread is None
        assert root == tmp_path
        assert source == tmp_path / "backup.cehbackup"
        assert allow_replace is True
        events.append("restore")
        return 3

    monkeypatch.setattr(backup_ui, "restore_backup", restore)
    assert backup_ui._restore_without_telegram_race(
        window, tmp_path / "backup.cehbackup", "test-password"
    ) == 3
    assert events == ["stop", "join", "is_alive", "restore", "resume"]


def test_inbox_restart_after_failed_restore(monkeypatch, tmp_path):
    events = []
    window = make_window(tmp_path, events, thread=FakeInboxThread(events))

    def fail(*args, **kwargs):
        events.append("failed_restore")
        raise BackupError("Contraseña incorrecta")

    monkeypatch.setattr(backup_ui, "restore_backup", fail)
    with pytest.raises(BackupError, match="Contraseña incorrecta"):
        backup_ui._restore_without_telegram_race(
            window, tmp_path / "backup.cehbackup", "test-password"
        )
    assert events == ["stop", "join", "is_alive", "failed_restore", "resume"]


def test_stuck_inbox_aborts_restore_before_touching_private_data(monkeypatch, tmp_path):
    events = []
    thread = FakeInboxThread(events, blocked=True)
    window = make_window(tmp_path, events, thread=thread)

    def should_never_restore(*args, **kwargs):
        raise AssertionError("No private data should be modified while Telegram is active")

    monkeypatch.setattr(backup_ui, "restore_backup", should_never_restore)
    with pytest.raises(BackupError, match="no terminó a tiempo"):
        backup_ui._restore_without_telegram_race(
            window, tmp_path / "backup.cehbackup", "test-password"
        )
    assert window.inbox_thread is thread
    assert events == ["stop", "join", "is_alive"]


def test_restore_without_running_inbox_does_not_start_one(monkeypatch, tmp_path):
    events = []
    window = make_window(tmp_path, events)
    monkeypatch.setattr(
        backup_ui, "restore_backup",
        lambda *args, **kwargs: events.append("restore") or 1,
    )
    assert backup_ui._restore_without_telegram_race(
        window, tmp_path / "backup.cehbackup", "test-password"
    ) == 1
    assert events == ["restore"]
