"""GUI-side state routing. Delivery never drives or inspects the browser."""
import copy
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from .notification_jobs import NotificationJobs
from .notification_store import NotificationVault
from .telegram_global import TelegramGlobalStore, TelegramGlobalError
from ..notifications import settings,EventRouter,make_event,Telegram,webhook_request,send_request,state_event,NotificationError,telegram_message,profile_data_text


class NotificationDelivery(QObject):
    result=Signal(str,str)

    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.jobs=NotificationJobs(self);self.vault=NotificationVault()
        self.router=EventRouter();self.telegram_router=EventRouter();self.profile_id=None;self.generation=0;self.current_visit=None;self.closed=False
        self.prepared_profile=None;self.secrets={};self.global_telegram=None

    def prepare(self, profile_id):
        """Resolve native vault access before the browser starts searching."""
        previous = self.secrets if self.prepared_profile == profile_id else {}
        self.secrets = {}
        self.prepared_profile = profile_id
        ready = True
        try:
            raw = self.store.raw_profile(profile_id)
        except (ValueError, StopIteration):
            self.result.emit('profile', 'Не удалось прочитать выбранный профиль. Выберите профиль заново и повторите запуск.')
            return False
        config = settings(raw.get('notifications', {}))
        self.global_telegram = None
        if hasattr(self.store, 'path'):
            try:
                self.global_telegram = TelegramGlobalStore(
                    Path(self.store.path).parent, vault=self.vault).credentials()
            except TelegramGlobalError as exc:
                self.result.emit('telegram', str(exc))
                ready = False
        for channel in ('telegram', 'webhook'):
            connection = config[channel]
            if not connection['enabled'] or not connection.get('events'):
                continue
            if channel == 'telegram' and self.global_telegram:
                # Global bot uses its own native secret instead of a per-profile token.
                continue
            reference = connection.get('secret_ref', '')
            if reference in previous:
                self.secrets[reference] = previous[reference]
                continue
            try:
                self.secrets[reference] = self.vault.get(reference)
            except NotificationError as exc:
                ready = False
                self.result.emit(channel, str(exc))
        return ready

    def observe(self,profile_id,state,language):
        if not profile_id or self.closed:return
        if self.profile_id!=profile_id:
            self.router=EventRouter();self.telegram_router=EventRouter();self.profile_id=profile_id
        event=self.router.observe(state)
        kind=state_event(state)
        active=state_event(state,include_transient=True)
        if active is None and (state.get('paused') or state.get('connection_lost')):
            # Match the router's retained office visit through an interruption.
            resumed = dict(state, paused=False, connection_lost=False)
            if state_event(resumed, include_transient=True) == 'office':
                active = 'office'
        visit=(profile_id,state.get('run_id'),state.get('document') if active=='office' else None,active)
        if visit!=self.current_visit:
            self.generation+=1;self.current_visit=visit
        telegram_event=None if kind=='booking' and state.get('booking_details_pending') else self.telegram_router.observe(state)
        if not event and not telegram_event:return
        try:raw=self.store.raw_profile(profile_id)
        except (ValueError,StopIteration):return
        config=settings(raw.get('notifications',{}))
        payload=make_event(event or telegram_event,raw.get('label',''),raw.get('request',{}).get('province',''),language)
        generation=self.generation
        current=lambda:not self.closed and self.generation==generation and self.profile_id==profile_id
        message=telegram_message(payload,language,state.get('booking_details'),offices=state.get('available_offices'),preferred=raw.get('request',{}).get('office',''))
        message=profile_data_text(raw)+message
        for channel in ('telegram','webhook'):
            event_name = telegram_event if channel == 'telegram' else event
            if not event_name:
                continue
            connection = copy.deepcopy(config[channel])
            admin = (self.global_telegram if self.prepared_profile == profile_id
                     and channel == 'telegram' else None)
            if channel == 'telegram':
                recipients = []
                if admin:
                    recipients.append({'id': admin['owner_chat_id']})
                if connection['enabled'] and event_name in connection.get('events', []):
                    for recipient in connection.get('recipients', []):
                        allowed_events = recipient.get('events', connection.get('events', []))
                        if event_name in allowed_events:
                            recipients.append(recipient)
                recipients_by_id = {str(r['id']): r for r in recipients if r.get('id')}
                if not recipients_by_id:
                    continue
                connection['recipients'] = list(recipients_by_id.values())
                secret = ({'token': admin['token']} if admin else
                          copy.deepcopy(self.secrets.get(connection.get('secret_ref', '')))
                          if self.prepared_profile == profile_id else None)
            else:
                if not connection['enabled'] or event_name not in connection.get('events', []):
                    continue
                secret = (copy.deepcopy(self.secrets.get(connection.get('secret_ref', '')))
                          if self.prepared_profile == profile_id else None)
            def deliver(channel=channel,connection=connection,secret=secret):
                if not current():raise NotificationError('Уведомление устарело')
                if secret is None:raise NotificationError('Секреты уведомлений не подготовлены. Проверить настройки до запуска поиска.')
                if channel=='telegram':
                    client=Telegram(secret.get('token',''))
                    failures=0;accepted=0
                    for recipient in connection.get('recipients',[]):
                        if not current():raise NotificationError('Уведомление устарело')
                        try:client.send(recipient['id'],message,current);accepted+=1
                        except NotificationError:failures+=1
                    if failures:return 'Уведомление доставлено не всем получателям' if accepted else 'Не удалось доставить уведомление'
                    return 'Сообщение принято Telegram'
                code,_,elapsed=send_request(webhook_request(secret,payload),current=current)
                return f'HTTP {code} · {elapsed} ms'
            def done(ok,value,channel=channel):
                if current():self.result.emit(channel,value)
            self.jobs.submit(deliver,done)

    def reset(self):
        # Keep informational cooldowns when restarting the SAME profile.
        # This prevents duplicate NIE restriction alerts across worker runs,
        # without sharing a different applicant's cooldowns.
        webhook_sent = dict(self.router.sent)
        telegram_sent = dict(self.telegram_router.sent)
        self.generation += 1
        self.router = EventRouter(); self.router.sent.update(webhook_sent)
        self.telegram_router = EventRouter(); self.telegram_router.sent.update(telegram_sent)
        self.current_visit = None
        self.secrets = {}; self.prepared_profile = None; self.global_telegram = None

    def stop(self):self.closed=True;self.reset()
