"""Global Telegram administrator and allowlisted private chats editor."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, QInputDialog, QMessageBox,
)

from .telegram_global import TelegramGlobalStore, TelegramGlobalError, valid_private_id


class TelegramGlobalPanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.store = TelegramGlobalStore(window.store.path.parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel('Administrador principal del bot de Telegram')
        layout.addWidget(title)
        hint = QLabel(
            'Configura el token y el Chat ID principal una sola vez, sin crear un perfil. '
            'El principal recibe los avisos de todos los perfiles; los otros ID solo '
            'pueden gestionar sus propios perfiles creados desde Telegram.'
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.token = QLineEdit()
        self.token.setObjectName('globalTelegramToken')
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText('Token del bot (vacío conserva el ya guardado)')
        self.token.setMaxLength(256)
        layout.addWidget(self.token)
        self.owner = QLineEdit()
        self.owner.setObjectName('globalTelegramOwner')
        self.owner.setPlaceholderText('Chat ID privado principal (números)')
        layout.addWidget(self.owner)
        layout.addWidget(QLabel('Otros Chat ID autorizados (crear y eliminar solo sus perfiles):'))
        self.allowed = QListWidget()
        self.allowed.setObjectName('globalTelegramAuthorized')
        self.allowed.setMaximumHeight(110)
        layout.addWidget(self.allowed)
        actions = QHBoxLayout()
        add = QPushButton('Autorizar ID')
        add.setObjectName('authorizeTelegramId')
        add.clicked.connect(self.add_chat)
        revoke = QPushButton('Revocar ID seleccionado')
        revoke.setObjectName('revokeTelegramId')
        revoke.clicked.connect(self.revoke_chat)
        actions.addWidget(add)
        actions.addWidget(revoke)
        actions.addStretch()
        layout.addLayout(actions)
        self.save_button = QPushButton('Guardar configuración principal de Telegram')
        self.save_button.setObjectName('saveGlobalTelegram')
        self.save_button.clicked.connect(self.save_settings)
        layout.addWidget(self.save_button)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.reload()

    def reload(self):
        try:
            raw = self.store.load()
        except TelegramGlobalError as exc:
            self.status.setText(str(exc))
            return
        self.owner.setText(raw['owner_chat_id'])
        self.allowed.clear()
        self.allowed.addItems(raw['authorized_chat_ids'])
        if raw['secret_ref']:
            self.token.setPlaceholderText('Token guardado en Windows; vacío = conservar')
        self.status.setText(
            'Administrador configurado. El token no se almacena en el JSON.'
            if raw['secret_ref'] else 'Configura el administrador principal para activar el bot global.'
        )

    def add_chat(self):
        value, ok = QInputDialog.getText(
            self, 'Autorizar Chat ID', 'Introduce un Chat ID privado de Telegram:')
        value = value.strip()
        if not ok:
            return
        if (not valid_private_id(value) or value == self.owner.text().strip()
                or any(self.allowed.item(i).text() == value for i in range(self.allowed.count()))):
            QMessageBox.warning(self, 'ID no válido', 'Introduce un ID privado nuevo, diferente del principal.')
            return
        if self.allowed.count() >= 30:
            QMessageBox.warning(self, 'Límite', 'Máximo 30 ID autorizados.')
            return
        self.allowed.addItem(value)
        self.status.setText('Pulsa Guardar para aplicar la nueva autorización.')

    def revoke_chat(self):
        row = self.allowed.currentRow()
        if row < 0:
            return
        self.allowed.takeItem(row)
        self.status.setText('Pulsa Guardar para revocar el acceso. Los perfiles existentes se conservan.')

    def save_settings(self):
        ids = [self.allowed.item(i).text() for i in range(self.allowed.count())]
        token = self.token.text().strip()
        # A rejected ID or token must never interrupt a working bot.
        try:
            self.store.validate(self.owner.text(), ids, token=token)
        except TelegramGlobalError as exc:
            self.status.setText(str(exc))
            return
        thread = getattr(self.window, 'inbox_thread', None)
        if thread is not None:
            thread.stop()
            thread.join(timeout=10.0)
            if thread.is_alive():
                QMessageBox.warning(
                    self, 'Telegram', 'El buzón todavía está procesando mensajes. '
                    'No se cambiaron los permisos. Vuelve a intentarlo.')
                return
            self.window.inbox_thread = None
        try:
            self.store.save(self.owner.text(), ids, token=token)
            self.token.clear()
            self.status.setText('Administrador y permisos guardados de forma segura.')
        except TelegramGlobalError as exc:
            self.status.setText(str(exc))
        finally:
            self.window.sync_telegram_inbox()
