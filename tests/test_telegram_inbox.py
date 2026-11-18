"""Telegram inbox: authorisation, profile creation, privacy and pairing safety. No network."""
import tempfile
from pathlib import Path

from app.config import _NIE_LETTERS
from app.desktop.profiles import ProfileStore
from app.notifications import EVENTS
from app.telegram_inbox import MAX_CREATED_PER_HOUR, TelegramInbox

CATALOG = Path(__file__).resolve().parents[1] / 'catalogs' / 'snapshot-2026-08-12.json'
ALLOWED, STRANGER = 111, 999


def nie(n):
    number = f'{n:07d}'
    return 'X' + number + _NIE_LETTERS[int('0' + number) % 23]


class FakeVault:
    def __init__(self): self.data = {}; self.count = 0
    def put(self, data): self.count += 1; ref = f'notifications-{self.count}'; self.data[ref] = dict(data); return ref
    def get(self, ref): return dict(self.data[ref])
    def delete(self, ref): self.data.pop(ref, None)


class FakeClient:
    def __init__(self): self.updates = []; self.sent = []; self.calls = []; self.webhook = ''
    def call(self, method, data=None):
        self.calls.append((method, data))
        if method == 'getWebhookInfo': return {'url': self.webhook}
        if method == 'getUpdates':
            offset = (data or {}).get('offset')
            return [u for u in self.updates if offset is None or u['update_id'] >= offset]
        if method == 'sendMessage':
            self.sent.append((str(data['chat_id']), data['text']))
            return {'message_id': 9000 + len(self.sent)}
        return True
    def send(self, chat_id, text, current=lambda: True): self.sent.append((str(chat_id), text))


def message(uid, text, chat=ALLOWED, kind='private'):
    return {'update_id': uid, 'message': {'message_id': uid * 10, 'text': text, 'chat': {'id': chat, 'type': kind}}}


def submission(n=1234567, **over):
    values = dict(TRAMITE='TIE', PROVINCIA='08', OFICINA='GRANOLLERS', ACCESO='SIN_CLAVE', NIE=nie(n),
                  NOMBRE='Ana Perez', NACIONALIDAD='PERU', TELEFONO='600123456', EMAIL='ana@correo.com')
    values.update(over)
    return '\n'.join(f'{k}: {v}' for k, v in values.items())


def setup(directory):
    vault, client = FakeVault(), FakeClient()
    store = ProfileStore(Path(directory) / 'profiles.yml', CATALOG)
    ref = vault.put({'token': '123456:ABCDEF'})
    store.save_profile(None, dict(
        label='Base', request=dict(access_mode='certificate', clave_method='movil', no_slots_mode='salir',
                                   applicant_no_slots_mode='wait', province='Madrid', office='',
                                   procedure=__import__('app.config', fromlist=['x']).TIE_PROCEDURE, subprocedure=None),
        applicant=dict(fill_mode='manual', document_type='NIE', document_number=nie(7654321), full_name='BASE USER',
                       nationality='PERU', contact=dict(phone='600000000', email='b@b.com')),
        notifications={'telegram': {'enabled': True, 'events': ['booking'], 'secret_ref': ref,
                                    'recipients': [{'id': str(ALLOWED), 'label': 'Yo', 'type': 'private', 'username': ''}]}},
    ), revision=store.revision())
    clock = [0.0]
    inbox = TelegramInbox(store, vault, client=client, now=lambda: clock[0])
    return store, vault, client, inbox, clock


def test_start_replies_with_template_only_to_allowed_private_chat():
    with tempfile.TemporaryDirectory() as d:
        store, vault, client, inbox, _ = setup(d)
        client.updates = [message(1, '/start'), message(2, '/start', chat=STRANGER), message(3, 'hola', kind='group')]
        inbox.poll_once()
        assert [c for c, _ in client.sent] == [str(ALLOWED)]
        assert 'TRAMITE: TIE' in client.sent[0][1] and 'CUALQUIERA' in client.sent[0][1]


def test_submission_creates_profile_with_own_token_copy_and_masks_reply():
    with tempfile.TemporaryDirectory() as d:
        store, vault, client, inbox, _ = setup(d)
        client.updates = [message(1, '/perfil\n' + submission())]
        inbox.poll_once()
        tasks = {t.label: t for t in store.load()}
        task = tasks['Telegram · Barcelona · TIE']
        assert not task.errors and task.access_mode == 'without_clave' and task.document_number == nie(1234567)
        raw = store.raw_profile(task.id)
        telegram = raw['notifications']['telegram']
        base_ref = store.raw_profile([t for t in store.load() if t.label == 'Base'][0].id)['notifications']['telegram']['secret_ref']
        assert telegram['secret_ref'] != base_ref and vault.get(telegram['secret_ref']) == {'token': '123456:ABCDEF'}
        assert set(telegram['events']) == set(EVENTS) and telegram['recipients'][0]['id'] == str(ALLOWED)
        assert raw['request']['office'].startswith('CNP COMISARIA GRANOLLERS')
        reply = client.sent[-1][1]
        assert reply.startswith('✅') and nie(1234567) in reply and 'ana@correo.com' in reply
        assert ('deleteMessage', {'chat_id': str(ALLOWED), 'message_id': 10}) in client.calls  # data removed from chat


def test_invalid_and_duplicate_submissions_create_nothing():
    with tempfile.TemporaryDirectory() as d:
        store, vault, client, inbox, _ = setup(d)
        client.updates = [message(1, submission(NIE='X1234567A')), message(2, submission()), message(3, submission())]
        inbox.poll_once()
        assert 'NIE' in client.sent[0][1] and client.sent[0][1].startswith('⚠')
        assert client.sent[1][1].startswith('✅') and client.sent[2][1].startswith('ℹ')
        assert len(store.load()) == 2  # Base + one
        assert len(vault.data) == 2    # no leaked secret from the rejected/duplicate ones


def test_hourly_limit():
    with tempfile.TemporaryDirectory() as d:
        store, vault, client, inbox, clock = setup(d)
        client.updates = [message(i, submission(1000 + i)) for i in range(1, MAX_CREATED_PER_HOUR + 2)]
        inbox.poll_once()
        assert client.sent[-1][1].startswith('⛔') and len(store.load()) == 1 + MAX_CREATED_PER_HOUR
        clock[0] = 3601
        client.updates = [message(99, submission(5000))]
        inbox.poll_once()
        assert client.sent[-1][1].startswith('✅')


def test_pairing_start_message_is_never_confirmed():
    with tempfile.TemporaryDirectory() as d:
        store, vault, client, inbox, clock = setup(d)
        client.updates = [message(5, '/start abcDEF123'), message(6, '/start')]
        inbox.poll_once()
        assert len(client.sent) == 1  # only the plain /start was answered
        inbox.poll_once()
        assert client.calls[-1][1]['offset'] == 5  # still pending for the pairing dialog
        clock[0] = 10_000  # pairing window over
        inbox.poll_once(); inbox.poll_once()
        assert client.calls[-1][1]['offset'] == 7


def test_webhook_or_missing_recipient_disables_inbox():
    with tempfile.TemporaryDirectory() as d:
        store, vault, client, inbox, _ = setup(d)
        client.webhook = 'https://example.org/hook'
        assert inbox.poll_once() == 0 and 'webhook' in inbox.disabled_reason
    with tempfile.TemporaryDirectory() as d:
        store = ProfileStore(Path(d) / 'profiles.yml', CATALOG)
        inbox = TelegramInbox(store, FakeVault(), client=FakeClient())
        assert not inbox.prepare() and 'destinatario' in inbox.disabled_reason

class FakeMail:
    def __init__(self):
        self.sent = []
        self.enabled = True

    def read(self):
        return {'secret_ref': 'fake-key' if self.enabled else '',
                'recipients': ['authorized@example.com']}

    def send(self, subject, body):
        self.sent.append((subject, body))
        return 1


def callback(uid, action_data, *, chat=ALLOWED, author=None, message_id=None):
    return {
        'update_id': uid,
        'callback_query': {
            'id': 'answer-' + str(uid),
            'from': {'id': chat if author is None else author},
            'data': action_data,
            'message': {
                'message_id': message_id,
                'chat': {'id': chat, 'type': 'private'},
            },
        },
    }


def _created_for_deletion(directory):
    store, vault, client, inbox, clock = setup(directory)
    mail = FakeMail()
    inbox.deletion_service.mail = mail
    client.updates = [message(1, '/perfil\n' + submission(PERFIL='A.B.'))]
    inbox.poll_once()
    assert [t.label for t in store.load()] == ['Base', 'A.B.']
    client.updates = [message(2, '/perfiles')]
    inbox.poll_once()
    assert '1. Base' in client.sent[-1][1] and '2. A.B.' in client.sent[-1][1]
    return store, client, inbox, mail, clock


def test_delete_telegram_requires_confirmation_and_preserves_optional_name():
    with tempfile.TemporaryDirectory() as directory:
        store, client, inbox, mail, _ = _created_for_deletion(directory)
        original = {t.label: t.id for t in store.load()}
        client.updates = [message(3, '/borrar 2')]
        inbox.poll_once()
        assert len(store.load()) == 2
        request = next(data for method, data in reversed(client.calls) if method == 'sendMessage')
        assert '«A.B.»' in request['text']
        assert request['reply_markup']['inline_keyboard'][0][0]['text'].startswith('✅ Confirmar')
        token = request['reply_markup']['inline_keyboard'][0][0]['callback_data']
        client.updates = [callback(4, token, message_id=9000 + len(client.sent))]
        inbox.poll_once()
        assert [t.label for t in store.load()] == ['Base']
        assert store.load()[0].id == original['Base']
        assert len(mail.sent) == 1
        assert 'A.B.' in mail.sent[0][1] and 'documento' in mail.sent[0][1]
        assert len(list((Path(directory)/'data').glob('profile-deletions.jsonl'))) == 1
        audit = (Path(directory)/'data/profile-deletions.jsonl').read_text()
        assert 'gmail_sent' in audit and 'BASE USER' not in audit


def test_delete_telegram_cancel_keeps_every_profile():
    with tempfile.TemporaryDirectory() as directory:
        store, client, inbox, mail, _ = _created_for_deletion(directory)
        client.updates = [message(3, '/borrar 2')]
        inbox.poll_once()
        request = next(data for method, data in reversed(client.calls) if method == 'sendMessage')
        token = request['reply_markup']['inline_keyboard'][0][1]['callback_data']
        client.updates = [callback(4, token, message_id=9000 + len(client.sent))]
        inbox.poll_once()
        assert len(store.load()) == 2
        assert not mail.sent
        assert 'cancelada' in client.sent[-1][1]


def test_delete_telegram_different_chat_cannot_confirm():
    with tempfile.TemporaryDirectory() as directory:
        store, client, inbox, mail, _ = _created_for_deletion(directory)
        client.updates = [message(3, '/borrar 2')]
        inbox.poll_once()
        request = next(data for method, data in reversed(client.calls) if method == 'sendMessage')
        token = request['reply_markup']['inline_keyboard'][0][0]['callback_data']
        client.updates = [callback(4, token, chat=STRANGER, message_id=9000 + len(client.sent))]
        inbox.poll_once()
        assert len(store.load()) == 2
        assert not mail.sent


def test_delete_telegram_refuses_stale_profile_list_and_source():
    with tempfile.TemporaryDirectory() as directory:
        store, client, inbox, mail, _ = _created_for_deletion(directory)
        client.updates = [message(3, '/borrar 1')]
        inbox.poll_once()
        assert 'conectado' in client.sent[-1][1]
        store.save_last_profile(store.load()[1].id)
        client.updates = [message(4, '/borrar 2')]
        inbox.poll_once()
        assert 'lista cambió' in client.sent[-1][1]
        assert len(store.load()) == 2
        assert not mail.sent


def test_delete_telegram_refuses_running_profile():
    from app.state import StateStore
    with tempfile.TemporaryDirectory() as directory:
        store, client, inbox, mail, _ = _created_for_deletion(directory)
        profile_id = store.load()[1].id
        client.updates = [message(3, '/borrar 2')]
        inbox.poll_once()
        request = next(data for method, data in reversed(client.calls) if method == 'sendMessage')
        token = request['reply_markup']['inline_keyboard'][0][0]['callback_data']
        state = StateStore(Path(directory)/'data/state.db')
        with state.task_lock(profile_id) as acquired:
            assert acquired
            client.updates = [callback(4, token, message_id=9000 + len(client.sent))]
            inbox.poll_once()
        assert len(store.load()) == 2
        assert not mail.sent
        assert 'ejecución' in client.sent[-1][1]


def test_delete_telegram_needs_gmail_before_confirmation():
    with tempfile.TemporaryDirectory() as directory:
        store, client, inbox, mail, _ = _created_for_deletion(directory)
        mail.enabled = False
        client.updates = [message(3, '/borrar 2')]
        inbox.poll_once()
        assert 'Configura Gmail' in client.sent[-1][1]
        assert len(store.load()) == 2
        assert not any(method == 'sendMessage' for method, _ in client.calls)
