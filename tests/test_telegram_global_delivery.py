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
