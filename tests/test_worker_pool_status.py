"""Worker startup diagnostics remain visible without running a browser."""
import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PySide6')

from types import SimpleNamespace

from app.desktop.worker_pool import WorkerPool


def test_busy_profile_shows_reason_in_worker_status(qt_app):
    store = SimpleNamespace(load=lambda: [SimpleNamespace(id='profile-2', label='Perfil 2', errors=[])])
    proxy_store = lambda: SimpleNamespace(load=lambda: {'proxy_profiles': []})
    pool = WorkerPool(store, proxy_store, lambda: 'es')
    slot = pool.slot(1)
    logs = []
    slot.logged.connect(lambda _index, message: logs.append(message))
    pool.start([{'index': 1, 'profile_id': 'profile-2', 'proxy_id': None}], busy_profile='profile-2')
    assert slot.status.startswith('No iniciado: ')
    assert 'pestana de trabajo' in slot.status
    assert any('NO INICIADO:' in item for item in logs)
    assert not slot.active
    pool.executor.shutdown(wait=True)


def test_worker_exit_keeps_explanatory_failure(qt_app):
    store = SimpleNamespace(load=lambda: [])
    pool = WorkerPool(store, lambda: None, lambda: 'es')
    slot = pool.slot(0)
    slot.on_failed('El navegador no pudo iniciar correctamente')
    slot.on_finished(1)
    assert slot.status == 'Fallo: El navegador no pudo iniciar correctamente'
    assert slot.tone == 'danger'
    pool.executor.shutdown(wait=True)
