"""Offline Gmail contract tests: no actual network or secrets in source files."""
import json

import pytest

from app.desktop.gmail_service import GmailError, GmailSettings


class Vault:
    def __init__(self):
        self.rows = {}
        self.deleted = []
        self.index = 0

    def put(self, data):
        self.index += 1
        ref = 'notifications-' + format(self.index, '032x')
        self.rows[ref] = dict(data)
        return ref

    def get(self, ref):
        return dict(self.rows[ref])

    def delete(self, ref):
        self.rows.pop(ref, None)
        self.deleted.append(ref)


class SMTP:
    calls = []

    def __init__(self, host, port, *, timeout, context):
        assert host == 'smtp.gmail.com'
        assert port == 465
        assert timeout <= 20
        assert context.verify_mode.name == 'CERT_REQUIRED'
        self.calls.append(('connect', host, port))

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def login(self, sender, password):
        assert password == 'abcdefghijklmnop'
        self.calls.append(('login', sender))

    def send_message(self, message, *, from_addr, to_addrs):
        self.calls.append(('sent', from_addr, list(to_addrs), message['Subject'],
                           message.get_content()))


def test_save_keeps_password_only_in_native_vault(tmp_path):
    vault = Vault()
    settings = GmailSettings(tmp_path/'data'/'gmail-settings.json', vault=vault, smtp_factory=SMTP)
    config = settings.save(' Sender@gmail.com ', 'one@example.com, TWO@example.com;one@example.com',
                           'abcd efgh ijkl mnop')
    stored = (tmp_path/'data'/'gmail-settings.json').read_text()
    assert 'abcdefghijklmnop' not in stored
    assert 'abcd efgh' not in stored
    assert config['sender'] == 'sender@gmail.com'
    assert config['recipients'] == ['one@example.com', 'two@example.com']
    assert vault.get(config['secret_ref'])['gmail_app_password'] == 'abcdefghijklmnop'
    old_ref = config['secret_ref']
    config2 = settings.save('sender@gmail.com', 'new@example.com')
    assert config2['secret_ref'] == old_ref
    with pytest.raises(GmailError, match='Al cambiar la cuenta'):
        settings.save('different@gmail.com', 'new@example.com')
    config3 = settings.save('different@gmail.com', 'new@example.com',
                            'abcd efgh ijkl mnop')
    assert old_ref in vault.deleted
    assert config3['secret_ref'] != old_ref


def test_delivery_only_to_saved_recipients_and_safe_test_message(tmp_path):
    SMTP.calls = []
    service = GmailSettings(tmp_path/'gmail-settings.json', vault=Vault(), smtp_factory=SMTP)
    service.save('sender@gmail.com', 'one@example.com, two@example.com', 'abcdefghijklmnop')
    with pytest.raises(GmailError, match='no está autorizado'):
        service.send('Aviso', 'Contenido', ['unknown@example.com'])
    assert not SMTP.calls
    assert service.test() == 1
    assert SMTP.calls[0] == ('connect', 'smtp.gmail.com', 465)
    assert SMTP.calls[-1][0:3] == ('sent','sender@gmail.com',['one@example.com'])
    assert 'datos personales' in SMTP.calls[-1][-1]
    assert service.send('Aviso autorizado', 'Sin datos privados', ['two@example.com']) == 1


@pytest.mark.parametrize('recipients', [
    'not-an-email',
    'one@example.com\r\nBcc: attacker@example.com',
    'one@example..com',
    ','.join(f'a{i}@example.com' for i in range(11)),
])
def test_invalid_recipients_rejected(tmp_path, recipients):
    service = GmailSettings(tmp_path/'gmail-settings.json', vault=Vault())
    with pytest.raises(GmailError):
        service.save('sender@gmail.com', recipients, 'abcdefghijklmnop')


def test_smtp_failure_reports_no_private_credentials(tmp_path):
    class FailedSMTP:
        def __init__(self, *args, **kwargs):
            raise OSError('abcdefghijklmnop private-proxy@example.com')

    service = GmailSettings(tmp_path/'gmail-settings.json', vault=Vault(),
                            smtp_factory=FailedSMTP)
    service.save('sender@gmail.com', 'one@example.com', 'abcdefghijklmnop')
    with pytest.raises(GmailError) as caught:
        service.test()
    assert 'abcdefghijklmnop' not in str(caught.value)
    assert 'private-proxy@example.com' not in str(caught.value)


def test_gmail_panel_password_is_hidden_and_cleared_after_save(tmp_path, qt_app):
    from PySide6.QtWidgets import QLineEdit
    from app.desktop.gmail_panel import GmailPanel
    service = GmailSettings(tmp_path/'gmail-settings.json', vault=Vault(), smtp_factory=SMTP)
    panel = GmailPanel(tmp_path/'gmail-settings.json', service=service)
    panel.sender.setText('sender@gmail.com')
    panel.recipients.setText('one@example.com')
    panel.password.setText('abcdefghijklmnop')
    assert panel.password.echoMode() == QLineEdit.EchoMode.Password
    panel.save_button.click()
    assert not panel.password.text()
    assert panel.test_button.isEnabled()
    assert 'guardado' in panel.status.text().lower()
    panel.close()


def test_backup_never_reimports_old_gmail_vault_reference(tmp_path):
    from app.desktop.private_backup import export_backup, restore_backup
    source = tmp_path/'original'
    source.mkdir()
    (source/'tasks.yml').write_text('tasks: []\n', encoding='utf-8')
    config = source/'data'/'gmail-settings.json'
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({
        'sender': 'sender@gmail.com', 'recipients':['one@example.com'],
        'secret_ref':'notifications-' + 'f'*32,
    }))
    archive = tmp_path/'archive.cehbackup'
    export_backup(source, archive, 'safe password 12345')
    recovered = tmp_path/'destination'
    restore_backup(recovered, archive, 'safe password 12345')
    data = json.loads((recovered/'data'/'gmail-settings.json').read_text())
    assert data['sender'] == 'sender@gmail.com'
    assert data['recipients'] == ['one@example.com']
    assert data['secret_ref'] == ''



@pytest.mark.parametrize('parent_redirect', [False, True])
def test_gmail_rejects_symbolic_links_before_reading_or_saving(tmp_path, parent_redirect):
    outside = tmp_path / 'outside'
    outside.mkdir()
    target = outside / 'gmail-settings.json'
    target.write_text(json.dumps({
        'sender': 'external@gmail.com', 'recipients': ['unauthorized@example.com'],
        'secret_ref': 'notifications-' + 'a' * 32,
    }), encoding='utf-8')
    if parent_redirect:
        link = tmp_path / 'linked-data'
        path = link / 'gmail-settings.json'
        source = outside
    else:
        link = tmp_path / 'gmail-settings.json'
        path = link
        source = target
    try:
        link.symlink_to(source, target_is_directory=parent_redirect)
    except (NotImplementedError, OSError):
        pytest.skip('Este sistema no permite enlaces simbólicos.')
    vault = Vault()
    service = GmailSettings(path, vault=vault, smtp_factory=SMTP)
    with pytest.raises(GmailError, match='ruta de configuración'):
        service.read()
    with pytest.raises(GmailError, match='ruta de configuración'):
        service.save('sender@gmail.com', 'allowed@example.com', 'abcdefghijklmnop')
    assert not vault.rows
    assert 'unauthorized@example.com' in target.read_text(encoding='utf-8')
