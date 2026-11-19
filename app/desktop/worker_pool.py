"""Pool de trabajadores independientes: cada fila = 1 perfil + 1 proxy + 1 proceso Camoufox.

Cada trabajador es un DesktopController propio (proceso aparte, carpeta de navegador propia,
candado propio). Un fallo de proxy o de proceso solo afecta a su fila.
"""
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from .process import DesktopController
from .proxy_check import check_proxy
from .proxy_profiles import ProxyProfileError
from ..notifications import RESTRICTION_ACTION

MAX_WORKERS = 10
MODE_TEXT = {'working': 'Buscando', 'waiting': 'Esperando', 'paused': 'Pausado',
             'manual': 'CAPTCHA / intervencion manual', 'recovery': 'Recuperando', 'finished': 'Finalizado',
             'booking_handoff': 'CITA ENCONTRADA'}


def worker_status_from_state(state):
    """Safe, fixed status labels: no page data or personal details in the UI."""
    mode = state.get('mode')
    stage = state.get('stage')
    if state.get('connection_lost'):
        return 'Sin comunicación con el trabajador', 'danger'
    if state.get('failed'):
        return 'Error del trabajador — revisar diagnóstico', 'danger'
    if state.get('paused') or mode == 'paused':
        return 'Pausado por el usuario', 'muted'
    if mode == 'waiting' and str(state.get('next_action', '')).startswith(RESTRICTION_ACTION):
        return 'Restricción NIE (cod. oper) — esperando', 'attention'
    if stage == 'server_error':
        return ('Error del servidor — recuperando' if mode == 'recovery'
                else 'Error temporal del servidor — esperando'), 'attention'
    if stage == 'unknown':
        return ('Pantalla desconocida — revisión manual' if mode == 'manual'
                else 'Pantalla desconocida — verificando'), 'attention'
    if stage in {'blocked', 'rate_limited'}:
        return 'Acceso limitado por el portal — esperando', 'attention'
    if mode == 'manual' and stage == 'auth_wait':
        return 'Autenticación manual pendiente', 'attention'
    text = MODE_TEXT.get(mode, 'Iniciando')
    tone = ('success' if mode == 'booking_handoff'
            else 'attention' if mode == 'manual'
            else 'accent' if mode in {'working', 'waiting'}
            else 'danger' if mode == 'recovery'
            else 'muted')
    return text, tone


def short(text, limit=70):
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


class WorkerSlot(QObject):
    changed = Signal(int)
    logged = Signal(int, str)
    finished = Signal(int)

    def __init__(self, index, pool):
        super().__init__(pool)
        self.index, self.pool = index, pool
        self.controller = None
        self.notifier = None
        self.profile_id = None
        self.proxy_id = None
        self.proxy = None
        self.future = None
        self.cancelled = False
        self.status, self.tone, self.manual = 'Detenido', 'muted', False
        self._last_key = None
        self._seen_fatal = set()
        self.failed_text = ''
        self._last_status_reason = None

    @property
    def active(self):
        return self.future is not None or (self.controller is not None and self.controller.active)

    def log(self, text):
        self.logged.emit(self.index, text)

    def set_status(self, text, tone='muted', manual=False):
        self.status, self.tone, self.manual = text, tone, manual
        self.changed.emit(self.index)

    def refuse(self, reason):
        # Show the reason in the status tooltip, not only in the log beneath
        # the worker table. The panel elides long text but keeps this intact.
        reason = str(reason)
        self.set_status('No iniciado: ' + reason, 'danger')
        self.log('NO INICIADO: ' + reason)

    def on_state(self, state):
        if self.notifier is not None and self.profile_id:
            self.notifier.observe(self.profile_id, state, self.pool.language())
        mode = state.get('mode')
        text, tone = worker_status_from_state(state)
        was_manual = self.manual
        # Record only category transitions and never any raw server response.
        exceptional = (text if (tone in {'danger', 'attention'} and text != MODE_TEXT.get(mode))
                       or mode == 'paused' else None)
        if exceptional != self._last_status_reason:
            self._last_status_reason = exceptional
            if exceptional:
                self.log('ESTADO: ' + exceptional)
        key = (state.get('screen', ''), state.get('evidence', ''))
        if key != self._last_key and any(key):
            self._last_key = key
            self.log(' — '.join(part for part in key if part))
        if mode == 'booking_handoff' and self.status != text:
            self.log('CITA ENCONTRADA: elige oficina y hora y confirma en la ventana de Camoufox de este trabajador.')
        if mode == 'manual' and not was_manual:
            if state.get('stage') == 'unknown':
                self.log('Revisión manual: pantalla desconocida. Comprueba Camoufox antes de continuar.')
            elif state.get('stage') == 'auth_wait':
                self.log('Autenticación manual pendiente. Comprueba la ventana de Camoufox.')
            else:
                self.log('Se necesita intervención manual. Pulsa «Camoufox» para revisar esa ventana.')
        for row in state.get('journal', []):
            if row.get('event') == 'fatal_error' and row.get('id') not in self._seen_fatal:
                self._seen_fatal.add(row.get('id'))
                reason = str(row.get('message') or row.get('detail') or 'el trabajador termino por un error')
                self.log('ERROR: ' + reason)
                self.failed_text = 'Fallo: ' + short(reason, 55)
        if self.failed_text:
            text, tone = self.failed_text, 'danger'
        self.set_status(text, tone, mode == 'manual')

    def on_failed(self, message):
        self.log('ERROR: ' + str(message))
        self.failed_text = 'Fallo: ' + short(message, 55)
        self.set_status(self.failed_text, 'danger')

    def on_finished(self, code):
        self.log('Trabajador detenido.' if not code else f'Trabajador terminado con error (codigo {code}).')
        # Preserve a more useful error already received from the worker.
        status = self.failed_text if code and self.failed_text else ('Detenido' if not code else f'Fallo: codigo {code}')
        self.set_status(status, 'danger' if code else 'muted')
        self.finished.emit(self.index)

    def on_notification(self, channel, message):
        self.log(f'Notificacion {channel}: {message}')


class WorkerPool(QObject):
    all_finished = Signal()

    def __init__(self, store, proxy_store, language, parent=None):
        super().__init__(parent)
        self.store, self.proxy_store, self.language = store, proxy_store, language
        self.slots = {}
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='proxy-check')
        self.poll = QTimer(self)
        self.poll.setInterval(200)
        self.poll.timeout.connect(self._poll)

    def slot(self, index):
        if index not in self.slots:
            worker = WorkerSlot(index, self)
            worker.finished.connect(self._check_all_finished)
            self.slots[index] = worker
        return self.slots[index]

    def any_active(self):
        return any(slot.active for slot in self.slots.values())

    def start(self, rows, busy_profile=None):
        """rows: [{'index': int, 'profile_id': str, 'proxy_id': str|None}] solo de filas con Activo."""
        try:
            tasks = {task.id: task for task in self.store.load()}
        except Exception as exc:
            for row in rows:
                self.slot(row['index']).refuse(f'no se pudieron leer los perfiles: {exc}')
            return
        try:
            proxies = {item['id']: item for item in self.proxy_store().load()['proxy_profiles']}
            proxy_error = ''
        except ProxyProfileError as exc:
            proxies, proxy_error = {}, str(exc)
        used_profiles, used_proxies, local_owner = {}, {}, None
        for index, slot in self.slots.items():
            if slot.active:
                used_profiles[slot.profile_id] = index
                if slot.proxy_id:
                    used_proxies[slot.proxy_id] = index
                else:
                    local_owner = index
        for row in sorted(rows, key=lambda item: item['index']):
            slot = self.slot(row['index'])
            if slot.active:
                continue
            name = f'Trabajador {row["index"] + 1}'
            profile_id, proxy_id = row.get('profile_id'), row.get('proxy_id')
            task = tasks.get(profile_id)
            if not profile_id or task is None:
                slot.refuse(f'{name}: selecciona un perfil valido.')
                continue
            if task.errors:
                slot.refuse(f'{name}: el perfil «{task.label}» tiene datos incompletos o invalidos. Corrigelo en la configuracion.')
                continue
            if profile_id in used_profiles:
                slot.refuse(f'{name}: el perfil «{task.label}» ya lo usa el Trabajador {used_profiles[profile_id] + 1}.')
                continue
            if profile_id == busy_profile:
                slot.refuse(f'{name}: el perfil «{task.label}» ya esta en marcha en la pestana de trabajo.')
                continue
            proxy = None
            if proxy_id:
                proxy = proxies.get(proxy_id)
                if proxy is None:
                    slot.refuse(f'{name}: el proxy seleccionado no existe. {proxy_error}'.strip())
                    continue
                if proxy_id in used_proxies:
                    slot.refuse(f'{name}: el proxy «{proxy["label"]}» ya lo usa el Trabajador {used_proxies[proxy_id] + 1}.')
                    continue
            elif local_owner is not None:
                slot.refuse(f'{name}: sin proxy solo se permite 1 trabajador (IP local) y ya lo usa el Trabajador {local_owner + 1}.')
                continue
            used_profiles[profile_id] = row['index']
            if proxy_id:
                used_proxies[proxy_id] = row['index']
            else:
                local_owner = row['index']
            slot.profile_id, slot.proxy_id, slot.proxy, slot.cancelled = profile_id, proxy_id, proxy, False
            slot._last_key, slot._seen_fatal, slot.failed_text = None, set(), ''
            slot._last_status_reason = None
            if proxy:
                slot.set_status('Comprobando proxy', 'attention')
                slot.log(f'Comprobando proxy «{proxy["label"]}» ({proxy["server"]})...')
                slot.future = self.executor.submit(
                    check_proxy, proxy['server'], proxy.get('username', ''), proxy.get('password', ''))
                if not self.poll.isActive():
                    self.poll.start()
            else:
                self._launch(slot)

    def _poll(self):
        pending = False
        for slot in list(self.slots.values()):
            future = slot.future
            if future is None:
                continue
            if not future.done():
                pending = True
                continue
            slot.future = None
            if slot.cancelled:
                slot.cancelled = False
                slot.set_status('Detenido', 'muted')
                slot.log('Inicio cancelado.')
                continue
            try:
                ok, detail = future.result()
            except Exception as exc:
                ok, detail = False, 'error inesperado al comprobar el proxy'
            label = slot.proxy['label'] if slot.proxy else ''
            if not ok:
                slot.refuse(f'El proxy «{label}» falló: {detail}. No se utilizará la IP local.')
                continue
            slot.log(f'Proxy «{label}»: {detail}.')
            self._launch(slot)
        if not pending:
            self.poll.stop()
        self._check_all_finished()

    def _launch(self, slot):
        proxy = slot.proxy
        try:
            store = self.proxy_store()
            if proxy:
                store.bind_request_profile(slot.profile_id, proxy['id'], enabled=True)
                current = store.proxy_for_request(slot.profile_id)
                if not current or current.get('server') != proxy['server']:
                    raise ProxyProfileError('no se pudo fijar el proxy para este perfil')
            else:
                try:
                    store.bind_request_profile(slot.profile_id, store.assignment_for(slot.profile_id)['proxy_profile_id'], enabled=False)
                except ProxyProfileError:
                    store.bind_request_profile(slot.profile_id, None, enabled=False)
        except ProxyProfileError as exc:
            slot.refuse(f'{exc}. No se utilizará la IP local.')
            return
        if slot.controller is None:
            slot.controller = DesktopController(self.store)
            slot.controller.setParent(slot)
            slot.controller.state_changed.connect(slot.on_state)
            slot.controller.failed.connect(slot.on_failed)
            slot.controller.finished.connect(slot.on_finished)
        if slot.notifier is None:
            from .notification_delivery import NotificationDelivery
            slot.notifier = NotificationDelivery(self.store, slot)
            slot.notifier.result.connect(slot.on_notification)
        slot.notifier.reset()
        if not slot.notifier.prepare(slot.profile_id):
            slot.refuse('No se pudieron preparar los secretos de notificaciones del perfil.')
            return
        slot.controller.extra_env = {'CITA_REQUIRE_PROXY': '1'} if proxy else {}
        slot.log(f'Iniciando Camoufox con proxy «{proxy["label"]}».' if proxy
                 else 'Iniciando Camoufox con la IP local (sin proxy).')
        slot.set_status('Iniciando', 'accent')
        slot.controller.start(slot.profile_id)

    def stop(self, index):
        slot = self.slots.get(index)
        if slot is None:
            return
        if slot.future is not None:
            slot.cancelled = True
        if slot.controller is not None and slot.controller.active:
            slot.controller.shutdown(close_browser=True)

    def stop_all(self):
        for index in list(self.slots):
            self.stop(index)

    def show_browser(self, index):
        slot = self.slots.get(index)
        if slot is not None and slot.controller is not None and slot.controller.active:
            slot.controller.send({'command': 'show_browser'})

    def _check_all_finished(self, *_):
        if not self.any_active():
            self.all_finished.emit()