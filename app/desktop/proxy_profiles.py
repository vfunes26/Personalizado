"""Proxy profile storage and request-profile bindings.

This module is intentionally independent from the desktop UI and browser
launching code. It stores fixed proxy endpoints and their profile bindings.
"""
import copy
import json
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .notification_store import NotificationVault
from ..notifications import NotificationError


class ProxyCredentialVault(NotificationVault):
    """Native OS credential manager; never falls back to a local secret file."""
    SERVICE = "Cita Extranjeria Helper proxy credentials"

    def put(self, credentials):
        reference = None
        try:
            reference = super().put(credentials)
            if self.get(reference) != credentials:
                raise ProxyProfileError("No se verificaron las credenciales guardadas.")
            return reference
        except (NotificationError, ProxyProfileError):
            if reference:
                self.delete(reference)
            raise ProxyProfileError(
                "No se pudo guardar el proxy en el gestor de credenciales del sistema."
            ) from None

    def get(self, reference):
        try:
            credentials = super().get(reference)
        except NotificationError:
            raise ProxyProfileError(
                "No se pudieron leer las credenciales del proxy. "
                "Comprueba el gestor de credenciales de Windows."
            ) from None
        if not isinstance(credentials, dict):
            raise ProxyProfileError("Las credenciales del proxy no son validas.")
        username = credentials.get("username")
        password = credentials.get("password")
        if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
            raise ProxyProfileError("Las credenciales del proxy guardadas son invalidas.")
        return {"username": username, "password": password}



class ProxyProfileError(ValueError):
    """Invalid proxy profile configuration."""


class ProxyProfileStore:
    def __init__(self, path: Path, vault=None):
        self.path = Path(path)
        self.vault = vault if vault is not None else ProxyCredentialVault()

    def _check_private_path(self):
        from ..locking import ensure_private_path
        try:
            ensure_private_path(self.path)
        except OSError:
            raise ProxyProfileError('La ruta de proxies está enlazada. Datos privados protegidos.') from None

    @staticmethod
    def _empty():
        return {
            "proxy_profiles": [],
            "assignments": {},
        }

    def _read(self):
        self._check_private_path()
        if not self.path.exists():
            return self._empty()

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise ProxyProfileError(
                "No se pudo leer el archivo de perfiles proxy."
            ) from None

        if not isinstance(raw, dict):
            raise ProxyProfileError("Estructura proxy inválida.")

        proxy_profiles = raw.get("proxy_profiles", [])
        assignments = raw.get("assignments", {})

        if not isinstance(proxy_profiles, list):
            raise ProxyProfileError("La lista de proxies es inválida.")

        if not isinstance(assignments, dict):
            raise ProxyProfileError("Las vinculaciones proxy son inválidas.")

        if any(not isinstance(item, dict) for item in proxy_profiles):
            raise ProxyProfileError("Hay un perfil proxy inválido.")

        if any(not isinstance(item, dict) for item in assignments.values()):
            raise ProxyProfileError("Hay una vinculación proxy inválida.")

        return {
            "proxy_profiles": copy.deepcopy(proxy_profiles),
            "assignments": copy.deepcopy(assignments),
        }


    def _migrate_legacy(self, raw):
        """Atomically migrate legacy plaintext to verified native secrets.

        If any vault write fails, the original JSON is left unchanged.
        """
        created = []
        changed = False
        try:
            for item in raw["proxy_profiles"]:
                if "username" not in item and "password" not in item:
                    continue
                username = str(item.get("username", "") or "")
                password = str(item.get("password", "") or "")
                if bool(username) != bool(password):
                    raise ProxyProfileError("Credenciales de proxy antiguas incompletas.")
                if username:
                    if item.get("secret_ref"):
                        # A partial migration is never treated as an unverified secret.
                        if self.vault.get(item["secret_ref"]) != {
                            "username": username, "password": password
                        }:
                            raise ProxyProfileError("Las credenciales proxy no coinciden.")
                    else:
                        reference = self.vault.put({"username": username, "password": password})
                        created.append(reference)
                        item["secret_ref"] = reference
                item.pop("username", None)
                item.pop("password", None)
                changed = True
            if changed:
                self._write(raw)
        except Exception:
            # The old plaintext file is still present when an atomic write fails.
            for reference in created:
                self.vault.delete(reference)
            raise

    def _hydrate(self, raw):
        """Return a memory-only copy for the existing GUI and worker interfaces."""
        hydrated = copy.deepcopy(raw)
        for item in hydrated["proxy_profiles"]:
            reference = item.get("secret_ref")
            if reference:
                try:
                    credentials = self.vault.get(reference)
                except ProxyProfileError:
                    item["username"] = ""
                    item["password"] = ""
                    item["credentials_unavailable"] = True
                else:
                    item.update(credentials)
            else:
                item["username"] = ""
                item["password"] = ""
        return hydrated

    def _locked_read(self):
        from ..locking import locked_file
        self._check_private_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._check_private_path()
        with locked_file(self.path.with_name("." + self.path.name + ".lock")):
            raw = self._read()
            self._migrate_legacy(raw)
            return self._hydrate(raw)

    @staticmethod
    def validate_endpoint(server):
        server = str(server or "").strip()

        try:
            parsed = urlsplit(server)
            port = parsed.port
        except ValueError:
            raise ProxyProfileError(
                "El servidor proxy o su puerto no son válidos."
            ) from None

        if parsed.scheme.lower() not in {"http", "https", "socks5"}:
            raise ProxyProfileError(
                "El proxy debe utilizar HTTP, HTTPS o SOCKS5."
            )

        if not parsed.hostname or port is None or not 1 <= port <= 65535:
            raise ProxyProfileError(
                "El proxy debe incluir servidor y puerto."
            )

        if '@' in parsed.netloc:
            raise ProxyProfileError(
                "Introduce las credenciales en sus campos separados."
            )

        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ProxyProfileError(
                "El servidor proxy no debe incluir rutas ni parámetros."
            )

        return server

    @staticmethod
    def _validate_profile(profile):
        if not isinstance(profile, dict):
            raise ProxyProfileError("El perfil proxy debe ser un objeto.")

        label = str(profile.get("label", "")).strip()
        server = ProxyProfileStore.validate_endpoint(
            profile.get("server", "")
        )

        username = str(profile.get("username", "") or "")
        password = str(profile.get("password", "") or "")

        if len(label) > 100:
            raise ProxyProfileError("El nombre del proxy es demasiado largo.")

        if len(username) > 256 or len(password) > 256:
            raise ProxyProfileError("Las credenciales son demasiado largas.")
        if any(char in username + password for char in '\r\n\0') or ':' in username:
            raise ProxyProfileError("Las credenciales contienen caracteres no admitidos.")
        if server.lower().startswith('socks5://') and (
                len(username.encode('utf-8')) > 255 or
                len(password.encode('utf-8')) > 255):
            raise ProxyProfileError("Las credenciales SOCKS5 exceden 255 bytes.")

        if bool(username) != bool(password):
            raise ProxyProfileError(
                "Debes proporcionar usuario y contraseña juntos."
            )

        return {
            "label": label,
            "server": server,
            "username": username,
            "password": password,
        }

    def load(self):
        return self._locked_read()

    def save_proxy_profile(self, profile_id, fields):
        normalized = self._validate_profile(fields)

        if not normalized["label"]:
            raise ProxyProfileError("El nombre del proxy es obligatorio.")

        from ..locking import locked_file

        self._check_private_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._check_private_path()

        with locked_file(self.path.with_name("." + self.path.name + ".lock")):
            raw = self._read()
            self._migrate_legacy(raw)
            profiles = raw["proxy_profiles"]

            existing = next(
                (item for item in profiles if item.get("id") == profile_id),
                None,
            )

            profile_id = profile_id or "proxy_" + uuid.uuid4().hex[:12]

            normalized["id"] = profile_id
            username = normalized.pop("username")
            password = normalized.pop("password")
            new_ref = None
            if existing and existing.get('secret_ref') and not username:
                # A missing WinVault secret must never become an anonymous proxy.
                self.vault.get(existing['secret_ref'])
            if username:
                old_ref = existing.get("secret_ref") if existing else None
                try:
                    old_credentials = self.vault.get(old_ref) if old_ref else None
                except ProxyProfileError:
                    # Backups moved to another PC can be reauthorized in the GUI.
                    old_credentials = None
                if old_credentials == {"username": username, "password": password}:
                    normalized["secret_ref"] = old_ref
                else:
                    new_ref = self.vault.put({"username": username, "password": password})
                    normalized["secret_ref"] = new_ref

            try:
                if existing is None:
                    if len(profiles) >= 10:
                        raise ProxyProfileError("Limite alcanzado: maximo 10 proxies.")
                    profiles.append(normalized)
                else:
                    profiles[profiles.index(existing)] = normalized
                self._write(raw)
            except Exception:
                if new_ref:
                    self.vault.delete(new_ref)
                raise
            # Old references are retained for previous portable backups.
        return profile_id

    def delete_proxy_profile(self, profile_id):
        from ..locking import locked_file

        self._check_private_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._check_private_path()

        with locked_file(self.path.with_name("." + self.path.name + ".lock")):
            raw = self._read()
            self._migrate_legacy(raw)

            raw["proxy_profiles"] = [
                item
                for item in raw["proxy_profiles"]
                if item.get("id") != profile_id
            ]

            for request_profile_id, assignment in list(
                raw["assignments"].items()
            ):
                if assignment.get("proxy_profile_id") == profile_id:
                    raw["assignments"].pop(request_profile_id, None)

            self._write(raw)

    def bind_request_profile(
        self,
        request_profile_id,
        proxy_profile_id,
        *,
        enabled,
    ):
        if not request_profile_id:
            raise ProxyProfileError(
                "Debes seleccionar un perfil de solicitud."
            )

        if not isinstance(enabled, bool):
            raise ProxyProfileError("El estado ACTIVO debe ser booleano.")

        from ..locking import locked_file

        self._check_private_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._check_private_path()

        with locked_file(self.path.with_name("." + self.path.name + ".lock")):
            raw = self._read()
            self._migrate_legacy(raw)

            known_proxy_ids = {
                item.get("id")
                for item in raw["proxy_profiles"]
            }

            if proxy_profile_id and proxy_profile_id not in known_proxy_ids:
                raise ProxyProfileError(
                    "El perfil proxy seleccionado ya no existe."
                )

            if enabled and not proxy_profile_id:
                raise ProxyProfileError(
                    "Selecciona un proxy antes de activar ACTIVO."
                )

            raw["assignments"][request_profile_id] = {
                "proxy_profile_id": proxy_profile_id or None,
                "enabled": enabled,
            }

            self._write(raw)

    def unbind_request_profile(self, request_profile_id):
        """Discard only this application's obsolete proxy binding."""
        from ..locking import locked_file
        self._check_private_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._check_private_path()
        with locked_file(self.path.with_name("." + self.path.name + ".lock")):
            raw = self._read()
            self._migrate_legacy(raw)
            if request_profile_id in raw['assignments']:
                raw['assignments'].pop(request_profile_id)
                self._write(raw)

    def assignment_for(self, request_profile_id):
        raw = self.load()
        assignment = raw["assignments"].get(request_profile_id, {})

        return {
            "proxy_profile_id": assignment.get("proxy_profile_id"),
            "enabled": bool(assignment.get("enabled", False)),
        }

    def proxy_for_request(self, request_profile_id):
        raw = self.load()
        assignment = raw["assignments"].get(request_profile_id, {})

        if not assignment.get("enabled", False):
            return None

        proxy_profile_id = assignment.get("proxy_profile_id")
        selected = next(
            (item for item in raw["proxy_profiles"] if item.get("id") == proxy_profile_id),
            None,
        )
        if selected and selected.get("credentials_unavailable"):
            raise ProxyProfileError(
                "El proxy tiene credenciales no disponibles en este equipo. "
                "Abre su configuracion e introduce usuario y contrasena de nuevo."
            )
        return copy.deepcopy(selected)

    def _write(self, raw):
        self._check_private_path()
        if any("username" in item or "password" in item
               for item in raw["proxy_profiles"]):
            raise ProxyProfileError("No se permite escribir credenciales proxy en JSON.")
        fd, temporary = tempfile.mkstemp(
            prefix=".proxy-profiles-",
            dir=self.path.parent,
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(
                    raw,
                    stream,
                    ensure_ascii=False,
                    indent=2,
                )
                stream.flush()
                os.fsync(stream.fileno())

            os.replace(temporary, self.path)

        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)