"""Pestana «Trabajadores»: proxies (5 filas + Agregar hasta 10), trabajadores (5 filas + Agregar
hasta 10) y un registro compartido. Cada fila activa lanza 1 perfil + 1 proxy + 1 trabajador."""
import json
from datetime import datetime

from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .paths import runtime_root
from .proxy_profiles import ProxyProfileError
from .worker_pool import MAX_WORKERS, WorkerPool

MIN_ROWS = 5
TONES = {'danger': 'color:#D64545;font-weight:bold;', 'attention': 'color:#C98A00;font-weight:bold;'}


class WorkersPanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.main_window = window
        self.loaded = False
        self.proxy_rows, self.worker_rows = [], []
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
        layout.addWidget(self._note('Cada fila activa lanza su propio Camoufox con su perfil y su proxy, de forma '
                                    'independiente. Sin proxy solo se permite 1 trabajador (IP local).'))

        layout.addWidget(self._heading('1. Proxies (minimo 5 filas, hasta 10)'))
        self.proxy_grid = QGridLayout()
        self.proxy_grid.setHorizontalSpacing(8)
        for column, text in enumerate(('#', 'Nombre', 'Servidor (http://host:puerto)', 'Usuario', 'Contrasena')):
            self.proxy_grid.addWidget(QLabel(text), 0, column)
        self.proxy_grid.setColumnStretch(1, 2)
        self.proxy_grid.setColumnStretch(2, 3)
        self.proxy_grid.setColumnStretch(3, 2)
        self.proxy_grid.setColumnStretch(4, 2)
        layout.addLayout(self.proxy_grid)
        for _ in range(MIN_ROWS):
            self.add_proxy_row()
        buttons = QHBoxLayout()
        self.add_proxy_button = QPushButton('+ Agregar')
        self.add_proxy_button.clicked.connect(lambda: self.add_proxy_row())
        self.save_proxies_button = QPushButton('Guardar proxies')
        self.save_proxies_button.clicked.connect(self.save_proxies)
        buttons.addWidget(self.add_proxy_button)
        buttons.addWidget(self.save_proxies_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.proxy_note = self._note('')
        layout.addWidget(self.proxy_note)

        layout.addWidget(self._heading('2. Trabajadores (minimo 5 filas, hasta 10)'))
        self.worker_grid = QGridLayout()
        self.worker_grid.setHorizontalSpacing(8)
        for column, text in enumerate(('Activo', 'Trabajador', 'Perfil', 'Proxy', 'Estado')):
            self.worker_grid.addWidget(QLabel(text), 0, column)
        self.worker_grid.setColumnStretch(2, 2)
        self.worker_grid.setColumnStretch(3, 2)
        self.worker_grid.setColumnStretch(4, 2)
        layout.addLayout(self.worker_grid)
        for _ in range(MIN_ROWS):
            self.add_worker_row()
        buttons = QHBoxLayout()
        self.add_worker_button = QPushButton('+ Agregar')
        self.add_worker_button.clicked.connect(lambda: self.add_worker_row())
        self.start_button = QPushButton('Iniciar activos')
        self.start_button.clicked.connect(self.start_active)
        self.stop_all_button = QPushButton('Detener todos')
        self.stop_all_button.clicked.connect(self.pool.stop_all)
        buttons.addWidget(self.add_worker_button)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_all_button)
        buttons.addStretch()
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
        row = dict(id=values.get('id'), number=QLabel(str(len(self.proxy_rows) + 1)), label=QLineEdit(values.get('label', '')),
                   server=QLineEdit(values.get('server', '')), user=QLineEdit(values.get('username', '')),
                   password=QLineEdit(values.get('password', '')))
        row['password'].setEchoMode(QLineEdit.EchoMode.Password)
        row['server'].setPlaceholderText('http://host:puerto')
        position = len(self.proxy_rows) + 1
        for column, key in enumerate(('number', 'label', 'server', 'user', 'password')):
            self.proxy_grid.addWidget(row[key], position, column)
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

    def save_proxies(self):
        store = self.main_window._proxy_store()
        saved, errors = 0, []
        for number, row in enumerate(self.proxy_rows, 1):
            fields = dict(label=row['label'].text().strip(), server=row['server'].text().strip(),
                          username=row['user'].text(), password=row['password'].text())
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
        self.proxy_note.setText((f'{saved} proxy(s) guardado(s).' if not errors else '') + ' '.join(errors))
        self.refresh_combos()

    # ---------- trabajadores ----------
    def add_worker_row(self):
        if len(self.worker_rows) >= MAX_WORKERS:
            return None
        index = len(self.worker_rows)
        row = dict(active=QCheckBox(), name=QLabel(f'Trabajador {index + 1}'), profile=QComboBox(), proxy=QComboBox(),
                   status=QLabel('Detenido'), show=QPushButton('Camoufox'), stop=QPushButton('Detener'))
        row['profile'].setMinimumWidth(170)
        row['proxy'].setMinimumWidth(170)
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
        row['status'].setText(slot.status)
        row['status'].setStyleSheet(TONES.get(slot.tone, ''))
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
        self.stop_all_button.setEnabled(busy)

    def start_active(self):
        rows = [dict(index=index, profile_id=row['profile'].currentData(), proxy_id=row['proxy'].currentData())
                for index, row in enumerate(self.worker_rows) if row['active'].isChecked()]
        if not rows:
            self.append_log(None, 'Marca «Activo» en al menos un trabajador.')
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