import pytest

from app.desktop.proxy_profiles import ProxyProfileError, ProxyProfileStore


def test_proxy_is_fixed_per_request_profile(tmp_path):
    store=ProxyProfileStore(tmp_path/'data'/'proxy-profiles.json')

    first=store.save_proxy_profile(None,{
        'label':'Proxy principal',
        'server':'http://127.0.0.1:8080',
        'username':'user',
        'password':'secret',
    })
    second=store.save_proxy_profile(None,{
        'label':'Proxy secundario',
        'server':'socks5://127.0.0.1:1080',
        'username':'',
        'password':'',
    })

    store.bind_request_profile('request_a',first,enabled=True)
    store.bind_request_profile('request_b',second,enabled=True)

    assert store.proxy_for_request('request_a')['id']==first
    assert store.proxy_for_request('request_b')['id']==second
    assert store.proxy_for_request('request_a')['server']=='http://127.0.0.1:8080'


def test_disabled_or_unassigned_profile_uses_no_proxy(tmp_path):
    store=ProxyProfileStore(tmp_path/'proxy-profiles.json')
    proxy_id=store.save_proxy_profile(None,{
        'label':'Proxy',
        'server':'http://127.0.0.1:8080',
    })

    assert store.proxy_for_request('request_a') is None

    store.bind_request_profile('request_a',proxy_id,enabled=False)
    assert store.proxy_for_request('request_a') is None


def test_active_assignment_requires_existing_proxy(tmp_path):
    store=ProxyProfileStore(tmp_path/'proxy-profiles.json')

    with pytest.raises(ProxyProfileError):
        store.bind_request_profile('request_a',None,enabled=True)

    with pytest.raises(ProxyProfileError):
        store.bind_request_profile('request_a','missing',enabled=True)


def test_proxy_validation_rejects_invalid_endpoints(tmp_path):
    store=ProxyProfileStore(tmp_path/'proxy-profiles.json')

    for endpoint in (
        '127.0.0.1:8080',
        'ftp://127.0.0.1:21',
        'http://user:pass@127.0.0.1:8080',
        'http://127.0.0.1',
        'http://127.0.0.1:8080/path',
    ):
        with pytest.raises(ProxyProfileError):
            store.save_proxy_profile(None,{
                'label':'Invalid',
                'server':endpoint,
            })


def test_deleting_proxy_removes_its_assignments(tmp_path):
    store=ProxyProfileStore(tmp_path/'proxy-profiles.json')
    proxy_id=store.save_proxy_profile(None,{
        'label':'Proxy',
        'server':'http://127.0.0.1:8080',
    })
    store.bind_request_profile('request_a',proxy_id,enabled=True)

    store.delete_proxy_profile(proxy_id)

    assert store.assignment_for('request_a')['proxy_profile_id'] is None
    assert store.proxy_for_request('request_a') is None