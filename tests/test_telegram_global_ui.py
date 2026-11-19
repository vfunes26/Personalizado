"""Global Telegram settings are independent of the existence of profiles."""
import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QListWidget, QLineEdit, QPushButton

from app.desktop.telegram_global_ui import TelegramGlobalPanel


@pytest.fixture
def window(tmp_path, catalog_path, qt_app):
    from PySide6.QtCore import QObject, Signal, QCoreApplication, QEvent
    from app.desktop.profiles import ProfileStore
    from app.desktop.window import DesktopWindow

    class Controller(QObject):
        state_changed = Signal(dict)
        failed = Signal(str)
        finished = Signal(int)
        active = False

        def start(self, profile_id): self.active = True
        def send(self, message): pass
        def shutdown(self, *, close_browser=False): self.active = False

    application = qt_app
    desktop = DesktopWindow(ProfileStore(tmp_path / 'tasks.yml', catalog_path), Controller())
    desktop.show()
    application.processEvents()
    yield desktop
    desktop.close()
    desktop.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def test_global_telegram_ui_has_owner_token_authorization_controls(window):
    panel=window.telegram_global_panel
    assert isinstance(panel, TelegramGlobalPanel)
    assert panel.findChild(QLineEdit,'globalTelegramOwner')
    assert panel.findChild(QLineEdit,'globalTelegramToken')
    assert panel.findChild(QListWidget,'globalTelegramAuthorized')
    assert panel.findChild(QPushButton,'authorizeTelegramId')
    assert panel.findChild(QPushButton,'revokeTelegramId')
    assert panel.findChild(QPushButton,'saveGlobalTelegram')


def test_global_telegram_ui_revoke_keeps_existing_profile(window):
    panel=window.telegram_global_panel
    panel.allowed.addItems(['11111', '22222'])
    panel.allowed.setCurrentRow(0)
    panel.revoke_chat()
    assert [panel.allowed.item(i).text() for i in range(panel.allowed.count())] == ['22222']



def test_invalid_administrator_is_rejected_before_stopping_bot(window):
    panel=window.telegram_global_panel
    panel.owner.setText('invalid')
    panel.token.setText('123456:ABCDEF')
    class DummyThread:
        def __init__(self): self.stopped=False
        def stop(self): self.stopped=True
        def join(self,timeout=None): raise AssertionError('No debe detener el bot')
        def is_alive(self): return True
    thread=DummyThread()
    window.inbox_thread=thread
    try:
        panel.save_settings()
        assert not thread.stopped
        assert 'principal' in panel.status.text()
        assert not panel.store.path.exists()
        assert panel.token.text()=='123456:ABCDEF'
    finally:
        window.inbox_thread=None
