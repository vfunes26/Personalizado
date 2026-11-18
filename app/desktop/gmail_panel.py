"""Gmail opt-in settings and background delivery test."""
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from .gmail_service import GmailError, GmailSettings
from .notification_jobs import NotificationJobs


class GmailPanel(QWidget):
    def __init__(self, settings_path, parent=None, service=None):
        super().__init__(parent)
        self.setObjectName('gmailSettingsPanel')
        self.service = service or GmailSettings(settings_path)
        self.jobs = NotificationJobs(self)
        self.sender = QLineEdit()
        self.sender.setObjectName('gmailSender')
        self.sender.setPlaceholderText('tu-cuenta@gmail.com')
        self.sender.setMaximumLength(254)
        self.recipients = QLineEdit()
        self.recipients.setObjectName('gmailRecipients')
        self.recipients.setPlaceholderText('destino1@example.com, destino2@example.com')
        self.password = QLineEdit()
        self.password.setObjectName('gmailAppPassword')
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText('Contraseña de aplicación (vacío = conservar)')
        self.password.setMaximumLength(128)
        self.save_button = QPushButton('Guardar Gmail')
        self.save_button.setObjectName('gmailSave')
        self.save_button.clicked.connect(self.save)
        self.test_button = QPushButton('Enviar correo de prueba')
        self.test_button.setObjectName('gmailTest')
        self.test_button.clicked.connect(self.test)
        self.status = QLabel()
        self.status.setObjectName('gmailStatus')
        self.status.setWordWrap(True)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(QLabel('Cuenta Gmail remitente'))
        column.addWidget(self.sender)
        column.addWidget(QLabel('Destinatarios autorizados (separados por coma)'))
        column.addWidget(self.recipients)
        column.addWidget(QLabel('Contraseña de aplicación de Google; no la contraseña habitual'))
        column.addWidget(self.password)
        actions = QHBoxLayout()
        actions.addWidget(self.save_button)
        actions.addWidget(self.test_button)
        actions.addStretch()
        column.addLayout(actions)
        column.addWidget(self.status)
        self.refresh()

    def refresh(self):
        try:
            config = self.service.read()
        except GmailError as exc:
            self.status.setText(str(exc))
            return
        self.sender.setText(config['sender'])
        self.recipients.setText(', '.join(config['recipients']))
        self.test_button.setEnabled(bool(config['secret_ref']))
        self.status.setText(
            'Configurado. El correo de prueba solo irá al primer destinatario autorizado.'
            if config['secret_ref'] else 'Gmail pendiente de configuración.'
        )

    def save(self):
        try:
            self.service.save(self.sender.text(), self.recipients.text(),
                              self.password.text() or None)
        except GmailError as exc:
            self.status.setText(str(exc))
            return
        finally:
            self.password.clear()
        self.test_button.setEnabled(True)
        self.status.setText('Gmail guardado en este equipo. Puedes probar el envío.')

    def test(self):
        self.test_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.status.setText('Probando envío SMTP seguro…')
        self.jobs.submit(self.service.test, self._test_finished)

    def _test_finished(self, ok, result):
        self.test_button.setEnabled(True)
        self.save_button.setEnabled(True)
        if ok:
            self.status.setText('Correo de prueba enviado al primer destinatario autorizado.')
        else:
            self.status.setText(str(result))
