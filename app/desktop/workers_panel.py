"""Pestana «Trabajadores»: proxies (con prueba individual), trabajadores y registro compartido.

Flujo: 1) el perfil solo lleva los datos de la solicitud; 2) aqui se definen los proxies y se
prueban; 3) cada fila de trabajador une 1 perfil + 1 proxy. Esa asignacion es la unica fuente
del proxy de un perfil (Seguimiento tambien la usa).
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .paths import runtime_root
from .proxy_check import check_proxy, normalize_proxy
from .proxy_profiles import ProxyProfileError
from .worker_pool import MAX_WORKERS, WorkerPool

MIN_ROWS = 5
TONES = {'danger': 'color:#D64545;font-weight:bold;', 'attention': 'color:#C98A00;font-weight:bold;',
         'success': 'color:#2E9E5B;font-weight:bold;'}
PROBE_OK = 'color:#2E9E5B;font-weight:bold;font-size:18px;'
PROBE_BAD = 'color:#D64545;font-weight:bold;font-size:18px;'
PROBE_WAIT = 'color:#C98A00;font-weight:bold;font-size:14px;'
STATUS_WIDTH = 270


class WorkersPanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.main_window = window
        self.loaded = False
        self.proxy_rows, self.worker_rows = [], []
        self.probe_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='proxy-probe')
        self.probe_timer = QTimer(self)
        self.probe_timer.setInterval(200)
        self.probe_timer.timeout.connect(self._poll_probes)
        self.pool = WorkerPool(window.store, window._proxy_store,
                               lambda: window.preferences.get('language', 'en'), self)
        self.pool.all_finished.connect(self._pool_finished)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 25, 28, 25)
        layout.setSpacing(12)

        title = QLabel('Trabajadores simultaneos')
        font = title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 3)
        title.setFont(font)
        layout.addWidget(title)
        layout.addWidget(self._note('Paso 1: crea el perfil (solo datos de la solicitud). Paso 2: define y prueba los proxies. '
                                    'Paso 3: une cada trabajador con su perfil y su proxy. Sin proxy solo se permite 1 trabajador (IP local).'))

        layout.addWidget(self._heading('1. Proxies (minimo 5 filas, hasta 10)'))
        self.proxy_grid = QGridLayout()
        self.proxy_grid.setHorizontalSpacing(8)
        for column, text in enumerate(('#', 'Nombre', 'Servidor (IP:puerto)', 'Usuario', 'Contrasena', '', 'Estado')):
            header = QLabel(text)
            self.proxy_grid.addWidget(header, 0, column, alignment=Qt.AlignmentFlag.AlignCenter if column == 6 else Qt.AlignmentFlag.AlignLeft)
        self.proxy_grid.setColumnStretch(7, 1)
        layout.addLayout(self.proxy_grid)
        for _ in range(MIN_ROWS):
            self.add_proxy_row()
        buttons = QHBoxLayout()
        self.add_proxy_button = QPushButton('+ Agregar')
        self.add_proxy_button.clicked.connect(lambda: self.add_proxy_row())
        self.save_proxies_button = QPushButton('Guardar proxies')
        self.save_proxies_button.clicked.connect(self.save_proxies)
        self.probe_all_button = QPushButton('Probar todos')
        self.probe_all_button.clicked.connect(self.probe_all)
        self.proxy_note = self._note('')
        for widget in (self.add_proxy_button, self.save_proxies_button, self.probe_all_button):
            buttons.addWidget(widget)
        buttons.addWidget(self.proxy_note, 1)
        layout.addLayout(buttons)

        layout.addWidget(self._heading('2. Trabajadores (minimo 5 filas, hasta 10)'))
        self.worker_grid = QGridLayout()
        self.worker_grid.setHorizontalSpacing(8)
        for column, text in enumerate(('Activo', 'Trabajador', 'Perfil', 'Proxy', 'Estado')):
            header = QLabel(text)
            self.worker_grid.addWidget(header, 0, column, alignment=Qt.AlignmentFlag.AlignCenter if column == 4 else Qt.AlignmentFlag.AlignLeft)
        self.worker_grid.setColumnStretch(7, 1)
        layout.addLayout(self.worker_grid)
        for _ in range(MIN_ROWS):
            self.add_worker_row()
        buttons = QHBoxLayout()
        self.add_worker_button = QPushButton('+ Agregar')
        self.add_worker_button.clicked.connect(lambda: self.add_worker_row())
        self.save_workers_button = QPushButton('Guardar')
        self.save_workers_button.clicked.connect(self.save_workers)
        self.start_button = QPushButton('Iniciar activos')
        self.start_button.clicked.connect(self.start_active)
        self.stop_all_button = QPushButton('Detener todos')
        self.stop_all_button.clicked.connect(self.pool.stop_all)
        self.worker_note = self._note('')
        for widget in (self.add_worker_button, self.save_workers_button, self.start_button, self.stop_all_button):
            buttons.addWidget(widget)
        buttons.addWidget(self.worker_note, 1)
        layout.addLayout(buttons)

        layout.addWidget(self._heading('Registro de trabajadores'))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setMinimumHeight(220)
        layout.addWidget(self.log)
        layout.addStretch()
        self.update_global()

    @staticmethod
    def _note(text):
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    @staticmethod
    def _heading(text):
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    # ---------- proxies ----------
    def add_proxy_row(self, values=None):
        if len(self.proxy_rows) >= MAX_WORKERS:
            return None
        values = values or {}
        row = dict(id=values.get('id'), future=None, number=QLabel(str(len(self.proxy_rows) + 1)),
                   label=QLineEdit(values.get('label', '')), server=QLineEdit(values.get('server', '')),
                   user=QLineEdit(values.get('username', '')), password=QLineEdit(values.get('password', '')),
                   probe=QPushButton('Probar'), status=QLabel('—'))
        row['password'].setEchoMode(QLineEdit.EchoMode.Password)
        row['server'].setPlaceholderText('64.137.96.74:6014')
        for key, width in (('label', 120), ('server', 175), ('user', 120), ('password', 120)):
            row[key].setFixedWidth(width)
        row['probe'].setFixedWidth(80)
        row['status'].setFixedWidth(60)
        row['status'].setAlignment(Qt.AlignmentFlag.AlignCenter)
        position = len(self.proxy_rows) + 1
        for column, key in enumerate(('number', 'label', 'server', 'user', 'password', 'probe', 'status')):
            self.proxy_grid.addWidget(row[key], position, column)
        row['probe'].clicked.connect(lambda _=False, r=row: self.probe_row(r))
        self.proxy_rows.append(row)
        if hasattr(self, 'add_proxy_button'):
            self.add_proxy_button.setEnabled(len(self.proxy_rows) < MAX_WORKERS)
        return row

    def load_proxies(self):
        try:
            items = self.main_window._proxy_store().load()['proxy_profiles']
        except ProxyProfileError as exc:
            self.proxy_note.setText(str(exc))
            return
        for position, item in enumerate(items[:MAX_WORKERS]):
            row = self.proxy_rows[position] if position < len(self.proxy_rows) else self.add_proxy_row()
            row['id'] = item.get('id')
            row['label'].setText(item.get('label', ''))
            row['server'].setText(item.get('server', ''))
            row['user'].setText(item.get('username', ''))
            row['password'].setText(item.get('password', ''))
        self.add_proxy_button.setEnabled(len(self.proxy_rows) < MAX_WORKERS)

    def _normalize_row(self, row):
        server, user, password = normalize_proxy(row['server'].text(), row['user'].text(), row['password'].text())
        row['server'].setText(server)
        row['user'].setText(user)
        row['password'].setText(password)
        return server, user, password

    def probe_row(self, row):
        server, user, password = self._normalize_row(row)
        if not server:
            self._set_probe(row, False, 'Escribe el servidor (IP:puerto).')
            return
        row['status'].setText('…')
        row['status'].setStyleSheet(PROBE_WAIT)
        row['status'].setToolTip('Probando…')
        row['future'] = self.probe_executor.submit(check_proxy, server, user, password)
        if not self.probe_timer.isActive():
            self.probe_timer.start()

    def probe_all(self):
        tested = 0
        for row in self.proxy_rows:
            if row['server'].text().strip():
                self.probe_row(row)
                tested += 1
        self.proxy_note.setText(f'Probando {tested} proxy(s)…' if tested else 'No hay proxies escritos para probar.')

    def _set_probe(self, row, ok, detail):
        row['status'].setText('✔' if ok else '✖')
        row['status'].setStyleSheet(PROBE_OK if ok else PROBE_BAD)
        row['status'].setToolTip(detail)
        name = row['label'].text().strip() or f'Proxy {self.proxy_rows.index(row) + 1}'
        self.append_log(None, f'Prueba de proxy «{name}»: ' + ('OK' if ok else 'FALLO') + f' — {detail}')

    def _poll_probes(self):
        pending = False
        for row in self.proxy_rows:
            future = row['future']
            if future is None:
                continue
            if not future.done():
                pending = True
                continue
            row['future'] = None
            try:
                ok, detail = future.result()
            except Exception as exc:
                ok, detail = False, f'Error inesperado: {exc}'
            self._set_probe(row, ok, detail)
        if not pending:
            self.probe_timer.stop()
            results = [row['status'].text() for row in self.proxy_rows if row['status'].text() in {'✔', '✖'}]
            if results:
                self.proxy_note.setText(f'Resultado: {results.count("✔")} correcto(s), {results.count("✖")} con fallo.')

    def save_proxies(self):
        store = self.main_window._proxy_store()
        saved, errors = 0, []
        for number, row in enumerate(self.proxy_rows, 1):
            server, user, password = self._normalize_row(row) if row['server'].text().strip() else ('', row['user'].text(), row['password'].text())
            fields = dict(label=row['label'].text().strip(), server=server, username=user, password=password)
            if not any(fields.values()):
                if row['id']:
                    try:
                        store.delete_proxy_profile(row['id'])
                        row['id'] = None
                    except ProxyProfileError as exc:
                        errors.append(f'Proxy {number}: {exc}')
                continue
            try:
                row['id'] = store.save_proxy_profile(row['id'], fields)
                saved += 1
            except ProxyProfileError as exc:
                errors.append(f'Proxy {number}: {exc}')
        self.proxy_note.setText((f'✔ {saved} proxy(s) guardado(s). ' if saved else '') + ' '.join(f'✖ {e}' for e in errors))
        self.refresh_combos()

    # ---------- trabajadores ----------
    def add_worker_row(self):
        if len(self.worker_rows) >= MAX_WORKERS:
            return None
        index = len(self.worker_rows)
        row = dict(active=QCheckBox(), name=QLabel(f'Trabajador {index + 1}'), profile=QComboBox(), proxy=QComboBox(),
                   status=QLabel('Detenido'), show=QPushButton('Camoufox'), stop=QPushButton('Detener'))
        row['profile'].setFixedWidth(170)
        row['proxy'].setFixedWidth(170)
        row['status'].setFixedWidth(STATUS_WIDTH)
        row['status'].setAlignment(Qt.AlignmentFlag.AlignCenter)
        row['show'].clicked.connect(lambda _=False, i=index: self.pool.show_browser(i))
        row['stop'].clicked.connect(lambda _=False, i=index: self.pool.stop(i))
        position = index + 1
        for column, key in enumerate(('active', 'name', 'profile', 'proxy', 'status', 'show', 'stop')):
            self.worker_grid.addWidget(row[key], position, column)
        slot = self.pool.slot(index)
        slot.logged.connect(self.append_log)
        slot.changed.connect(self.update_row)
        self.worker_rows.append(row)
        if hasattr(self, 'add_worker_button'):
            self.add_worker_button.setEnabled(len(self.worker_rows) < MAX_WORKERS)
            self.refresh_combos()
        self.update_row(index)
        return row

    def refresh_combos(self):
        try:
            tasks = self.main_window.store.load()
        except Exception as exc:
            self.append_log(None, f'No se pudieron leer los perfiles: {exc}')
            tasks = []
        try:
            proxies = self.main_window._proxy_store().load()['proxy_profiles']
        except ProxyProfileError as exc:
            self.append_log(None, str(exc))
            proxies = []
        for index, row in enumerate(self.worker_rows):
            if self.pool.slot(index).active:
                continue
            for combo, first, items in ((row['profile'], 'Selecciona un perfil', [(t.label, t.id) for t in tasks]),
                                        (row['proxy'], 'Sin proxy (IP local)', [(p['label'], p['id']) for p in proxies])):
                previous = combo.currentData()
                combo.blockSignals(True)
                combo.clear()
                combo.addItem(first, None)
                for text, value in items:
                    combo.addItem(text, value)
                combo.setCurrentIndex(max(0, combo.findData(previous)))
                combo.blockSignals(False)

    def update_row(self, index):
        if index >= len(self.worker_rows):
            return
        row, slot = self.worker_rows[index], self.pool.slot(index)
        label = row['status']
        label.setText(label.fontMetrics().elidedText(slot.status, Qt.TextElideMode.ElideRight, STATUS_WIDTH - 10))
        label.setToolTip(slot.status)
        label.setStyleSheet(TONES.get(slot.tone, ''))
        running = slot.active
        for key in ('active', 'profile', 'proxy'):
            row[key].setEnabled(not running)
        controller_active = slot.controller is not None and slot.controller.active
        row['show'].setEnabled(controller_active)
        row['stop'].setEnabled(running)
        if slot.manual:
            self.main_window.statusBar().showMessage(f'Trabajador {index + 1}: requiere intervencion (CAPTCHA).', 7000)
            QApplication.alert(self.main_window, 0)
        self.update_global()

    def update_global(self):
        if not hasattr(self, 'stop_all_button'):
            return
        busy = self.pool.any_active()
        self.save_proxies_button.setEnabled(not busy)
        self.save_workers_button.setEnabled(not busy)
        self.stop_all_button.setEnabled(busy)

    def _selected(self):
        return [dict(index=i, active=row['active'].isChecked(), profile_id=row['profile'].currentData(),
                     proxy_id=row['proxy'].currentData()) for i, row in enumerate(self.worker_rows)]

    def save_workers(self):
        """Guarda las selecciones y fija la asignacion perfil -> proxy (unica fuente del proxy de un perfil)."""
        rows, problems, seen_profiles, seen_proxies = self._selected(), [], {}, {}
        store = self.main_window._proxy_store()
        saved = 0
        for item in rows:
            profile_id, proxy_id, number = item['profile_id'], item['proxy_id'], item['index'] + 1
            if not profile_id:
                continue
            if profile_id in seen_profiles:
                problems.append(f'Trabajador {number}: el perfil ya esta en el Trabajador {seen_profiles[profile_id]}.')
                continue
            seen_profiles[profile_id] = number
            if proxy_id and proxy_id in seen_proxies:
                problems.append(f'Trabajador {number}: el proxy ya esta en el Trabajador {seen_proxies[proxy_id]}.')
                continue
            if proxy_id:
                seen_proxies[proxy_id] = number
            if self.pool.slot(item['index']).active:
                continue
            try:
                if proxy_id:
                    store.bind_request_profile(profile_id, proxy_id, enabled=True)
                else:
                    try:
                        previous = store.assignment_for(profile_id)['proxy_profile_id']
                        store.bind_request_profile(profile_id, previous, enabled=False)
                    except ProxyProfileError:
                        store.bind_request_profile(profile_id, None, enabled=False)
                saved += 1
            except (ProxyProfileError, OSError) as exc:
                problems.append(f'Trabajador {number}: {exc}')
        self.save_config()
        self.worker_note.setText((f'✔ Guardado ({saved} trabajador(es) con perfil). ' if not problems else '')
                                 + ' '.join(f'✖ {p}' for p in problems))

    def start_active(self):
        rows = [dict(index=i['index'], profile_id=i['profile_id'], proxy_id=i['proxy_id'])
                for i in self._selected() if i['active']]
        if not rows:
            self.append_log(None, 'Marca «Activo» en al menos un trabajador.')
            self.worker_note.setText('✖ Marca «Activo» en al menos un trabajador.')
            return
        self.save_config()
        controller = self.main_window.controller
        busy = getattr(controller, 'profile_id', None) if getattr(controller, 'active', False) else None
        self.pool.start(rows, busy)

    def append_log(self, index, text):
        prefix = 'GENERAL' if index is None else f'T{index + 1}'
        self.log.appendPlainText(f'{datetime.now():%H:%M:%S} [{prefix}] {text}')

    # ---------- persistencia ligera de las selecciones ----------
    def _config_path(self):
        return runtime_root() / 'data' / 'workers-config.json'

    def save_config(self):
        rows = [dict(active=row['active'].isChecked(), profile_id=row['profile'].currentData(),
                     proxy_id=row['proxy'].currentData()) for row in self.worker_rows]
        try:
            path = self._config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'rows': rows}), encoding='utf-8')
        except OSError:
            pass

    def restore_config(self):
        try:
            rows = json.loads(self._config_path().read_text(encoding='utf-8')).get('rows', [])
        except (OSError, ValueError, AttributeError):
            return
        for index, saved in enumerate(rows[:MAX_WORKERS]):
            if not isinstance(saved, dict):
                continue
            row = self.worker_rows[index] if index < len(self.worker_rows) else self.add_worker_row()
            for key, field in (('profile', 'profile_id'), ('proxy', 'proxy_id')):
                row[key].setCurrentIndex(max(0, row[key].findData(saved.get(field))))
            row['active'].setChecked(bool(saved.get('active')))

    def showEvent(self, event):
        super().showEvent(event)
        if not self.loaded:
            self.loaded = True
            self.load_proxies()
            self.refresh_combos()
            self.restore_config()
        else:
            self.refresh_combos()

    def _pool_finished(self):
        self.update_global()
        if getattr(self.main_window, 'closing', False):
            self.main_window.close()