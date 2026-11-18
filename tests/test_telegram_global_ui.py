"""Global Telegram settings are independent of the existence of profiles."""
import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QListWidget, QLineEdit, QPushButton

from app.desktop.telegram_global_ui import TelegramGlobalPanel


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
