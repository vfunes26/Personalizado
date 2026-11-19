"""Offline checks for owner-wide Telegram alerts and creator-only subscriptions."""
from types import SimpleNamespace

from app.desktop.notification_delivery import NotificationDelivery
from app.desktop.telegram_global import TelegramGlobalStore
from app.desktop import notification_delivery as delivery_module


class Vault:
    def __init__(self):
        self.items = {}

    def put(self, data):
        ref = 'notifications-' + str(len(self.items) + 1)
        self.items[ref] = dict(data)
        return ref

    def get(self, ref):
        return dict(self.items[ref])

    def delete(self, ref):
        self.items.pop(ref, None)


def test_admin_receives_all_profile_events_creator_receives_only_selected(qt_app, monkeypatch, tmp_path):
    vault = Vault()
    admin = '11111111'
    creator = '22222222'
    TelegramGlobalStore(tmp_path, vault=vault).save(
        admin, [creator], token='123456:ABCDEF'
    )
    recipient = {'id': creator, 'events': ['office', 'booking'], 'type': 'private'}
    class Store:
        path = tmp_path / 'tasks.yml'
        def raw_profile(self, profile):
            return {'label': 'Persona de prueba', 'request': {'province': 'Barcelona'},
                    'notifications': {'telegram': {'enabled': True, 'events': ['auth','office','booking','error'],
                                                   'secret_ref': 'legacy-not-needed',
                                                   'recipients': [recipient]}}}

    sent = []

    class Client:
        def __init__(self, token):
            assert token == '123456:ABCDEF'

        def send(self, chat, message, current):
            assert current()
            sent.append((chat, message))

    monkeypatch.setattr(delivery_module, 'Telegram', Client)
    delivery = NotificationDelivery(Store())
    delivery.vault = vault
    delivery.jobs.submit = lambda work, done: done(True, work())
    try:
        assert delivery.prepare('one')
        delivery.observe('one', {'screen':'Выбор офиса','stage':'office','mode':'manual',
                                 'document':'office-1','run_id':'run-1',
                                 'available_offices':['CNP TEST']}, 'es')
        assert [chat for chat, _ in sent] == [admin, creator]
        sent.clear()
        delivery.observe('one', {'screen':'Error de servidor', 'mode':'finished',
                                 'failed':True, 'run_id':'run-1'}, 'es')
        assert [chat for chat, _ in sent] == [admin]
    finally:
        delivery.stop()


def test_global_admin_receives_event_without_per_profile_telegram_enabled(qt_app, monkeypatch, tmp_path):
    vault = Vault()
    TelegramGlobalStore(tmp_path, vault=vault).save(
        '11111111', [], token='123456:ABCDEF'
    )

    class Store:
        path = tmp_path / 'tasks.yml'
        def raw_profile(self, profile):
            return {'label':'Sin notificaciones', 'request':{'province':'Barcelona'},
                    'notifications': {}}

    delivered = []

    class Client:
        def __init__(self, token):
            assert token == '123456:ABCDEF'
        def send(self, chat, message, current):
            delivered.append(chat)

    monkeypatch.setattr(delivery_module, 'Telegram', Client)
    delivery = NotificationDelivery(Store())
    delivery.vault = vault
    delivery.jobs.submit = lambda work, done: done(True, work())
    try:
        assert delivery.prepare('one')
        delivery.observe('one', {'booking_handoff':True, 'mode':'manual',
                                 'booking_details_pending':False,
                                 'run_id':'run-1'}, 'es')
        assert delivered == ['11111111']
    finally:
        delivery.stop()



def test_global_bot_filters_unapproved_private_recipients(qt_app, monkeypatch, tmp_path):
    vault = Vault()
    TelegramGlobalStore(tmp_path, vault=vault).save(
        '11111111', ['22222222'], token='123456:ABCDEF')

    class Store:
        path = tmp_path / 'tasks.yml'

        def raw_profile(self, profile):
            return {'notifications': {'telegram': {
                'enabled': True, 'events': ['booking'], 'secret_ref': 'unused',
                'recipients': [
                    {'id': '22222222', 'type': 'private'},
                    {'id': '33333333', 'type': 'private'},
                    {'id': '-44444444', 'type': 'group'},
                ],
            }}}

    sent = []

    class Client:
        def __init__(self, token):
            assert token == '123456:ABCDEF'

        def send(self, chat, message, current):
            sent.append(chat)

    monkeypatch.setattr(delivery_module, 'Telegram', Client)
    delivery = NotificationDelivery(Store())
    delivery.vault = vault
    delivery.jobs.submit = lambda work, done: done(True, work())
    try:
        assert delivery.prepare('one')
        delivery.observe('one', {'booking_handoff': True, 'mode': 'manual',
                                 'run_id': 'run'}, 'es')
        assert sent == ['11111111', '22222222']
    finally:
        delivery.stop()


def test_global_bot_revocation_applies_to_pending_delivery(qt_app, monkeypatch, tmp_path):
    vault = Vault()
    global_store = TelegramGlobalStore(tmp_path, vault=vault)
    global_store.save('11111111', ['22222222'], token='123456:ABCDEF')

    class Store:
        path = tmp_path / 'tasks.yml'

        def raw_profile(self, profile):
            return {'notifications': {'telegram': {
                'enabled': True, 'events': ['booking'],
                'recipients': [{'id': '22222222', 'type': 'private'}],
            }}}

    sent = []

    class Client:
        def __init__(self, token):
            pass

        def send(self, chat, message, current):
            sent.append(chat)

    monkeypatch.setattr(delivery_module, 'Telegram', Client)
    delivery = NotificationDelivery(Store())
    delivery.vault = vault
    pending = []
    delivery.jobs.submit = lambda work, done: pending.append(work)
    try:
        assert delivery.prepare('one')
        delivery.observe('one', {'booking_handoff': True, 'mode': 'manual',
                                 'run_id': 'run'}, 'es')
        assert len(pending) == 1
        global_store.save('11111111', [], token='')
        pending[0]()
        assert sent == ['11111111']
    finally:
        delivery.stop()


def test_global_bot_rotation_cancels_pending_delivery(qt_app, monkeypatch, tmp_path):
    import pytest
    from app.notifications import NotificationError

    vault = Vault()
    global_store = TelegramGlobalStore(tmp_path, vault=vault)
    global_store.save('11111111', [], token='123456:ABCDEF')

    class Store:
        path = tmp_path / 'tasks.yml'

        def raw_profile(self, profile):
            return {'notifications': {}}

    sent = []

    class Client:
        def __init__(self, token):
            pass

        def send(self, chat, message, current):
            sent.append(chat)

    monkeypatch.setattr(delivery_module, 'Telegram', Client)
    delivery = NotificationDelivery(Store())
    delivery.vault = vault
    pending = []
    delivery.jobs.submit = lambda work, done: pending.append(work)
    try:
        assert delivery.prepare('one')
        delivery.observe('one', {'booking_handoff': True, 'mode': 'manual',
                                 'run_id': 'run'}, 'es')
        global_store.save('11111111', [], token='999999:NEW_TOKEN')
        with pytest.raises(NotificationError, match='configuración global'):
            pending[0]()
        assert not sent
    finally:
        delivery.stop()
