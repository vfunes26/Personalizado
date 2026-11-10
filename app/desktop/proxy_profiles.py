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


class ProxyProfileError(ValueError):
    """Invalid proxy profile configuration."""


class ProxyProfileStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    @staticmethod
    def _empty():
        return {
            "proxy_profiles": [],
            "assignments": {},
        }

    def _read(self):
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

        if not parsed.hostname or port is None:
            raise ProxyProfileError(
                "El proxy debe incluir servidor y puerto."
            )

        if parsed.username or parsed.password:
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
        return self._read()

    def save_proxy_profile(self, profile_id, fields):
        normalized = self._validate_profile(fields)

        if not normalized["label"]:
            raise ProxyProfileError("El nombre del proxy es obligatorio.")

        from ..locking import locked_file

        self.path.parent.mkdir(parents=True, exist_ok=True)

        with locked_file(self.path.with_name("." + self.path.name + ".lock")):
            raw = self._read()
            profiles = raw["proxy_profiles"]

            existing = next(
                (item for item in profiles if item.get("id") == profile_id),
                None,
            )

            profile_id = profile_id or "proxy_" + uuid.uuid4().hex[:12]

            normalized["id"] = profile_id

            if existing is None:
                if len(profiles) >= 10:
                    raise ProxyProfileError("Limite alcanzado: maximo 10 proxies.")
                profiles.append(normalized)
            else:
                profiles[profiles.index(existing)] = normalized

            self._write(raw)

        return profile_id

    def delete_proxy_profile(self, profile_id):
        from ..locking import locked_file

        self.path.parent.mkdir(parents=True, exist_ok=True)

        with locked_file(self.path.with_name("." + self.path.name + ".lock")):
            raw = self._read()

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

        self.path.parent.mkdir(parents=True, exist_ok=True)

        with locked_file(self.path.with_name("." + self.path.name + ".lock")):
            raw = self._read()

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

    def assignment_for(self, request_profile_id):
        raw = self._read()
        assignment = raw["assignments"].get(request_profile_id, {})

        return {
            "proxy_profile_id": assignment.get("proxy_profile_id"),
            "enabled": bool(assignment.get("enabled", False)),
        }

    def proxy_for_request(self, request_profile_id):
        raw = self._read()
        assignment = raw["assignments"].get(request_profile_id, {})

        if not assignment.get("enabled", False):
            return None

        proxy_profile_id = assignment.get("proxy_profile_id")

        return copy.deepcopy(
            next(
                (
                    item
                    for item in raw["proxy_profiles"]
                    if item.get("id") == proxy_profile_id
                ),
                None,
            )
        )

    def _write(self, raw):
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