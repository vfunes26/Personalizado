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



@pytest.mark.parametrize('state,expected', [
    ({'mode':'paused','paused':True,'stage':'server_error'}, 'Pausado por el usuario'),
    ({'mode':'waiting','next_action':'Пауза после cod. oper — рекомендуется не продолжать до 00:00 (Мадрид)'}, 'Restricción NIE (cod. oper)'),
    ({'mode':'recovery','stage':'server_error'}, 'Error del servidor — recuperando'),
    ({'mode':'waiting','stage':'server_error'}, 'Error temporal del servidor'),
    ({'mode':'manual','stage':'unknown'}, 'Pantalla desconocida — revisión manual'),
    ({'mode':'working','stage':'unknown'}, 'Pantalla desconocida — verificando'),
    ({'mode':'manual','stage':'auth_wait'}, 'Autenticación manual pendiente'),
    ({'mode':'waiting','stage':'blocked'}, 'Acceso limitado por el portal'),
    ({'mode':'working','connection_lost':True}, 'Sin comunicación con el trabajador'),
])
def test_worker_status_distinguishes_safe_pause_categories(state, expected):
    from app.desktop.worker_pool import worker_status_from_state
    status, tone = worker_status_from_state(state)
    assert status.startswith(expected)
    assert tone in {'attention', 'danger', 'muted'}
    assert 'PRIVATE-NIE' not in status


def test_state_transition_does_not_spam_duplicate_diagnostics(qt_app):
    pool = WorkerPool(SimpleNamespace(load=lambda: []), lambda: None, lambda: 'es')
    slot = pool.slot(0)
    messages = []
    slot.logged.connect(lambda _index, message: messages.append(message))
    state = {'mode': 'waiting', 'stage': 'server_error', 'screen': '', 'evidence': ''}
    slot.on_state(state)
    slot.on_state(state)
    assert sum('ESTADO:' in message for message in messages) == 1
    slot.on_state({'mode': 'paused', 'paused': True})
    assert sum('ESTADO:' in message for message in messages) == 2
    pool.executor.shutdown(wait=True)
