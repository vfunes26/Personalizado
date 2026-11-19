"""Telegram global owner is native-vault backed, with safe revocation."""
import json

import pytest

from app.desktop.telegram_global import TelegramGlobalError, TelegramGlobalStore


class Vault:
    def __init__(self):
        self.values = {}
        self.index = 0
        self.fail = False

    def put(self, value):
        if self.fail:
            raise RuntimeError('vault disabled')
        self.index += 1
        reference = 'secret-' + str(self.index)
        self.values[reference] = dict(value)
        return reference

    def get(self, reference):
        return dict(self.values[reference])

    def delete(self, reference):
        self.values.pop(reference, None)


def test_admin_token_stored_only_in_native_vault(tmp_path):
    vault = Vault()
    store = TelegramGlobalStore(tmp_path, vault=vault)
    store.save('8337898066', ['1337768888'], token='123456:ABCDEF')
    raw = (tmp_path/'data'/'telegram-global.json').read_text()
    assert '123456:ABCDEF' not in raw
    assert store.credentials()['token'] == '123456:ABCDEF'
    assert store.credentials()['authorized_chat_ids'] == ['1337768888']


def test_authorized_id_revocation_updates_only_permissions(tmp_path):
    store = TelegramGlobalStore(tmp_path, vault=Vault())
    original = store.save('8337898066', ['1337768888', '2448879999'], token='123456:ABCDEF')
    newer = store.save('8337898066', ['2448879999'])
    assert newer['secret_ref'] == original['secret_ref']
    assert newer['authorized_chat_ids'] == ['2448879999']
    assert store.credentials()['token'] == '123456:ABCDEF'


@pytest.mark.parametrize('owner,other', [
    ('@channel', []), ('11111', ['11111']), ('11111', ['@public']),
    ('11111', ['22222', '22222']),
])
def test_reject_invalid_authorizations(tmp_path, owner, other):
    store = TelegramGlobalStore(tmp_path, vault=Vault())
    with pytest.raises(TelegramGlobalError):
        store.save(owner, other, token='123456:ABCDEF')
    assert not store.path.exists()


def test_cannot_configure_global_without_token(tmp_path):
    with pytest.raises(TelegramGlobalError, match='token'):
        TelegramGlobalStore(tmp_path, vault=Vault()).save('11111', [])


def test_reject_corrupted_file_instead_of_silent_reset(tmp_path):
    store = TelegramGlobalStore(tmp_path, vault=Vault())
    store.path.parent.mkdir(parents=True)
    store.path.write_text('invalid')
    with pytest.raises(TelegramGlobalError):
        store.load()



def test_invalid_token_and_owner_never_change_existing_global_config(tmp_path):
    store=TelegramGlobalStore(tmp_path, vault=Vault())
    previous=store.save('8337898066', ['1337768888'], token='123456:ABCDEF')
    before=store.path.read_bytes()
    with pytest.raises(TelegramGlobalError):
        store.validate('invalid', ['1337768888'])
    with pytest.raises(TelegramGlobalError, match='Formato del token'):
        store.save('8337898066', [], token='not-a-token')
    assert store.load()=={key:previous[key] for key in
                          ('owner_chat_id','authorized_chat_ids','secret_ref','enabled')}
    assert store.path.read_bytes()==before


def test_vault_failure_does_not_replace_token_or_permission_list(tmp_path):
    vault=Vault()
    store=TelegramGlobalStore(tmp_path,vault=vault)
    original=store.save('8337898066',['1337768888'],token='123456:ABCDEF')
    before=store.path.read_bytes()
    vault.fail=True
    with pytest.raises(TelegramGlobalError,match='de forma segura'):
        store.save('8337898066',['2448879999'],token='987654:NewToken')
    assert store.path.read_bytes()==before
    assert store.load()['authorized_chat_ids']==['1337768888']
    assert store.credentials()['token']=='123456:ABCDEF'
    assert store.load()['secret_ref']==original['secret_ref']


def test_reject_duplicate_or_owner_id_in_edited_json(tmp_path):
    store=TelegramGlobalStore(tmp_path,vault=Vault())
    store.path.parent.mkdir(parents=True)
    for authorized in (['12345','12345'], ['8337898066']):
        store.path.write_text(json.dumps({
            'owner_chat_id':'8337898066','authorized_chat_ids':authorized,
            'secret_ref':'secret-test','enabled':True,
        }),encoding='utf-8')
        with pytest.raises(TelegramGlobalError,match='IDs'):
            store.load()


def test_telegram_global_rejects_linked_directory(tmp_path):
    target=tmp_path/'real'
    target.mkdir()
    alias=tmp_path/'alias'
    try:
        alias.symlink_to(target,target_is_directory=True)
    except (OSError,NotImplementedError):
        pytest.skip('No se permiten enlaces simbólicos en esta plataforma.')
    config=TelegramGlobalStore(alias,vault=Vault())
    with pytest.raises(TelegramGlobalError,match='enlace'):
        config.load()
    with pytest.raises(TelegramGlobalError,match='enlace'):
        config.save('8337898066',[],token='123456:ABCDEF')
    assert not (target/'data'/'telegram-global.json').exists()
