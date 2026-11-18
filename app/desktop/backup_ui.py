"""Explicit UI for encrypted local state export/import."""
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox

from .private_backup import BackupError, export_backup, restore_backup


def _password(window, *, confirm):
    phrase, accepted = QInputDialog.getText(
        window, 'Contraseña de respaldo',
        'Introduce la contraseña del archivo cifrado (mínimo 12 caracteres):',
        QLineEdit.EchoMode.Password,
    )
    if not accepted:
        return None
    if len(phrase) < 12:
        QMessageBox.warning(window, 'Contraseña', 'Usa al menos 12 caracteres.')
        return None
    if confirm:
        again, accepted = QInputDialog.getText(
            window, 'Confirmar contraseña',
            'Repite la contraseña. Si la pierdes, no se podrá recuperar el respaldo.',
            QLineEdit.EchoMode.Password,
        )
        if not accepted or phrase != again:
            QMessageBox.warning(window, 'Contraseña', 'Las contraseñas no coinciden.')
            return None
    return phrase


def _busy(window):
    pool = getattr(getattr(window, 'workers_panel', None), 'pool', None)
    return bool(window.controller.active or (pool is not None and pool.any_active()))


def export_from_window(window):
    if _busy(window):
        QMessageBox.warning(window, 'Respaldo', 'Detén las búsquedas antes de exportar los datos.')
        return
    filename = 'CitaHelper-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.cehbackup'
    destination, _ = QFileDialog.getSaveFileName(
        window, 'Guardar respaldo privado cifrado', filename,
        'Respaldo cifrado CitaHelper (*.cehbackup)',
    )
    if not destination:
        return
    if not destination.lower().endswith('.cehbackup'):
        destination += '.cehbackup'
    password = _password(window, confirm=True)
    if password is None:
        return
    try:
        count = export_backup(window.store.path.parent, Path(destination), password)
    except (BackupError, OSError) as exc:
        QMessageBox.warning(window, 'Respaldo', str(exc))
        return
    QMessageBox.information(
        window, 'Respaldo creado',
        f'{count} archivos protegidos con contraseña.\n'
        'Las claves de Telegram/webhook del almacén de Windows no están incluidas.',
    )


def _suspend_telegram_for_restore(window, *, timeout=10.0):
    """Stop and JOIN the inbox before changing any profile or database.

    A stop request alone is insufficient: a running Telegram poll may still
    write a profile. Never restore when its thread has not actually exited.
    """
    thread = getattr(window, 'inbox_thread', None)
    if thread is None:
        return False
    thread.stop()
    thread.join(timeout=timeout)
    if thread.is_alive():
        raise BackupError(
            'El buzón de Telegram no terminó a tiempo. No se modificó ningún dato. '
            'Cierra la aplicación y vuelve a intentar la restauración.'
        )
    window.inbox_thread = None
    return True


def _restore_without_telegram_race(window, source, password):
    """Restore with no concurrent Telegram writer, also on failure paths."""
    suspended = _suspend_telegram_for_restore(window)
    try:
        return restore_backup(
            window.store.path.parent, Path(source), password, allow_replace=True
        )
    finally:
        if suspended:
            # Create a NEW thread against the restored configuration. Never
            # restart a stopped threading.Thread instance.
            try:
                window.sync_telegram_inbox()
            except (OSError, ValueError, RuntimeError):
                QMessageBox.warning(
                    window, 'Telegram',
                    'Se detuvo Telegram durante la restauración, pero no se pudo '
                    'reactivar. Reinicia la aplicación antes de volver a usar el buzón.',
                )


def import_into_window(window):
    if _busy(window):
        QMessageBox.warning(window, 'Restauración', 'Detén las búsquedas antes de importar datos.')
        return
    source, _ = QFileDialog.getOpenFileName(
        window, 'Seleccionar respaldo privado', '',
        'Respaldo cifrado CitaHelper (*.cehbackup)',
    )
    if not source:
        return
    password = _password(window, confirm=False)
    if password is None:
        return
    response = QMessageBox.question(
        window, 'Confirmar restauración',
        'Esta operación sustituirá los perfiles y datos incluidos en el respaldo.\n'
        'Antes de cambiar nada se guardará una copia cifrada de la configuración actual.\n'
        'Las notificaciones con claves del almacén de Windows quedarán desactivadas '
        'hasta volver a configurar sus credenciales.\n\n¿Continuar?',
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if response != QMessageBox.StandardButton.Yes:
        return
    try:
        count = _restore_without_telegram_race(window, source, password)
    except (BackupError, OSError) as exc:
        QMessageBox.warning(window, 'Restauración', str(exc))
        return
    QMessageBox.information(
        window, 'Restauración completada',
        f'{count} archivos restaurados. Cierra y vuelve a abrir la aplicación '
        'antes de iniciar búsquedas o editar perfiles.',
    )
