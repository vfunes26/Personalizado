"""Proxy secrets must be native-only and legacy migration must not lose data."""
import json
from pathlib import Path

import pytest

from app.desktop.proxy_profiles import (
    ProxyCredentialVault, ProxyProfileError, ProxyProfileStore,
)


class FakeKeyring:
    def __init__(self):
        self.secrets = {}
        self.unavailable = False

    def get_password(self, service, key):
        return self.secrets.get((service, key))

    def set_password(self, service, key, value):
        if self.unavailable:
            raise RuntimeError("credential manager offline")
        self.secrets[(service, key)] = value

    def delete_password(self, service, key):
        self.secrets.pop((service, key), None)


def store_at(path: Path, backend: FakeKeyring):
    return ProxyProfileStore(path, vault=ProxyCredentialVault(backend=backend))


def profile(password="s3cret"):
    return dict(label="Proxy uno", server="http://127.0.0.1:8080",
                username="nombre", password=password)


def raw_record(path):
    return json.loads(path.read_text(encoding="utf-8"))["proxy_profiles"][0]


def test_new_proxy_never_writes_plain_credentials(tmp_path):
    backend = FakeKeyring()
    path = tmp_path / "data" / "proxy-profiles.json"
    store = store_at(path, backend)
    proxy_id = store.save_proxy_profile(None, profile())
    on_disk = raw_record(path)
    assert "username" not in on_disk
    assert "password" not in on_disk
    assert on_disk["secret_ref"]
    assert "nombre" not in path.read_text(encoding="utf-8")
    assert "s3cret" not in path.read_text(encoding="utf-8")
    store.bind_request_profile("solicitud", proxy_id, enabled=True)
    bound = store.proxy_for_request("solicitud")
    assert bound["username"] == "nombre"
    assert bound["password"] == "s3cret"
    assert "password" not in raw_record(path)


def test_old_plain_json_migrates_atomically_with_assignments_preserved(tmp_path):
    backend = FakeKeyring()
    path = tmp_path / "proxy-profiles.json"
    legacy = {"proxy_profiles": [dict(id="proxy_old", **profile())],
              "assignments": {"request_a": {"proxy_profile_id": "proxy_old", "enabled": True}}}
    path.write_text(json.dumps(legacy), encoding="utf-8")
    store = store_at(path, backend)
    result = store.load()
    assert result["proxy_profiles"][0]["username"] == "nombre"
    assert result["proxy_profiles"][0]["password"] == "s3cret"
    assert store.proxy_for_request("request_a")["password"] == "s3cret"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["assignments"] == legacy["assignments"]
    assert persisted["proxy_profiles"][0]["id"] == "proxy_old"
    assert "username" not in persisted["proxy_profiles"][0]
    assert "password" not in persisted["proxy_profiles"][0]
    assert persisted["proxy_profiles"][0]["secret_ref"]


def test_legacy_plain_json_not_edited_if_vault_unavailable(tmp_path):
    backend = FakeKeyring()
    backend.unavailable = True
    path = tmp_path / "proxy-profiles.json"
    before = json.dumps({"proxy_profiles": [dict(id="proxy_old", **profile())],
                         "assignments": {}}, ensure_ascii=False)
    path.write_text(before, encoding="utf-8")
    with pytest.raises(ProxyProfileError):
        store_at(path, backend).load()
    assert path.read_text(encoding="utf-8") == before


def test_reloading_backup_keeps_reference_same_windows_account(tmp_path):
    backend = FakeKeyring()
    current = tmp_path / "current" / "proxy-profiles.json"
    backup = tmp_path / "other" / "proxy-profiles.json"
    store = store_at(current, backend)
    key = store.save_proxy_profile(None, profile())
    backup.parent.mkdir()
    backup.write_bytes(current.read_bytes())
    assert store_at(backup, backend).load()["proxy_profiles"][0]["password"] == "s3cret"
    store.save_proxy_profile(key, profile(password="changed"))
    assert store_at(backup, backend).load()["proxy_profiles"][0]["password"] == "s3cret"
    assert store.load()["proxy_profiles"][0]["password"] == "changed"
    assert "changed" not in current.read_text(encoding="utf-8")


def test_missing_native_secret_fails_closed_without_plaintext_fallback(tmp_path):
    backend = FakeKeyring()
    path = tmp_path / "proxy-profiles.json"
    store = store_at(path, backend)
    proxy_id = store.save_proxy_profile(None, profile())
    store.bind_request_profile("request_a", proxy_id, enabled=True)
    backend.secrets.clear()
    visible = store.load()["proxy_profiles"][0]
    assert visible["credentials_unavailable"] is True
    assert visible["username"] == ""
    assert visible["password"] == ""
    with pytest.raises(ProxyProfileError, match="credenciales no disponibles"):
        store.proxy_for_request("request_a")
    assert "password" not in raw_record(path)


def test_missing_native_secret_can_be_reauthorized_without_recreating_profile(tmp_path):
    backend = FakeKeyring()
    path = tmp_path / "proxy-profiles.json"
    store = store_at(path, backend)
    proxy_id = store.save_proxy_profile(None, profile())
    store.bind_request_profile("request_a", proxy_id, enabled=True)
    backend.secrets.clear()
    assert store.load()["proxy_profiles"][0]["credentials_unavailable"]
    assert store.save_proxy_profile(proxy_id, profile(password="new_secret")) == proxy_id
    assert store.proxy_for_request("request_a")["password"] == "new_secret"
    assert "new_secret" not in path.read_text(encoding="utf-8")


def test_failed_new_secret_does_not_write_plaintext_json(tmp_path):
    backend = FakeKeyring()
    backend.unavailable = True
    path = tmp_path / "proxy-profiles.json"
    with pytest.raises(ProxyProfileError):
        store_at(path, backend).save_proxy_profile(None, profile())
    assert not path.exists()


def test_unauthenticated_proxy_does_not_need_keyring(tmp_path):
    backend = FakeKeyring()
    backend.unavailable = True
    path = tmp_path / "proxy-profiles.json"
    store = store_at(path, backend)
    key = store.save_proxy_profile(None, {"label": "Local", "server": "socks5://127.0.0.1:1080"})
    assert store.load()["proxy_profiles"][0]["id"] == key
    assert "username" not in raw_record(path)
    assert "password" not in raw_record(path)



def test_missing_win_vault_secret_cannot_be_silently_removed_by_edit(tmp_path):
    backend = FakeKeyring()
    path = tmp_path / 'proxy-profiles.json'
    store = store_at(path, backend)
    proxy_id = store.save_proxy_profile(None, profile())
    before = path.read_bytes()
    backend.secrets.clear()
    with pytest.raises(ProxyProfileError, match='credenciales'):
        store.save_proxy_profile(proxy_id, {
            'label': 'Cambio de nombre', 'server': 'http://127.0.0.1:8080',
            'username': '', 'password': '',
        })
    assert path.read_bytes() == before
    assert raw_record(path)['secret_ref']


def test_windows_selects_native_winvault_keyring(monkeypatch):
    import sys
    from types import ModuleType

    windows_backend = ModuleType('keyring.backends.Windows')
    windows_backend.WinVaultKeyring = FakeKeyring
    monkeypatch.setitem(sys.modules, 'keyring.backends.Windows', windows_backend)
    monkeypatch.setattr('app.desktop.notification_store.sys.platform', 'win32')
    vault = ProxyCredentialVault()
    reference = vault.put({'username': 'usuario', 'password': 'secreto'})
    assert isinstance(vault.backend(), FakeKeyring)
    assert vault.get(reference) == {'username': 'usuario', 'password': 'secreto'}
