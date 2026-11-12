"""Normalizacion y comprobacion de proxies (sin Qt, solo sockets locales)."""
import socket
import threading
import time

from app.desktop.proxy_check import check_proxy, normalize_proxy


def serve(handler):
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(5)

    def loop():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=handler, args=(conn,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return server, server.getsockname()[1]


def test_server_without_scheme_gets_http_and_pasted_credentials_are_split():
    assert normalize_proxy('64.137.96.74:6014') == ('http://64.137.96.74:6014', '', '')
    assert normalize_proxy('64.137.96.74:6014:usuario:clave') == ('http://64.137.96.74:6014', 'usuario', 'clave')
    assert normalize_proxy('socks5://u:p@1.2.3.4:1080') == ('socks5://1.2.3.4:1080', 'u', 'p')
    assert normalize_proxy('HTTPS://host.example:8080/') == ('https://host.example:8080', '', '')
    assert normalize_proxy('1.2.3.4:80:a:b', 'mio', 'pw') == ('http://1.2.3.4:80', 'mio', 'pw')
    assert normalize_proxy('  ') == ('', '', '')


def test_http_proxy_results_are_reported_with_a_reason():
    def ok(conn):
        conn.recv(4096)
        conn.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
        time.sleep(0.2)
        conn.close()

    def denied(conn):
        conn.recv(4096)
        conn.sendall(b'HTTP/1.1 407 Proxy Authentication Required\r\n\r\n')
        conn.close()

    good, good_port = serve(ok)
    bad, bad_port = serve(denied)
    try:
        assert check_proxy(f'http://127.0.0.1:{good_port}', 'u', 'p')[0] is True
        accepted, reason = check_proxy(f'http://127.0.0.1:{bad_port}', 'u', 'p')
        assert accepted is False and '407' in reason
    finally:
        good.close()
        bad.close()


def test_closed_port_and_missing_port_fail_without_raising():
    closed = socket.socket()
    closed.bind(('127.0.0.1', 0))
    port = closed.getsockname()[1]
    closed.close()
    assert check_proxy(f'http://127.0.0.1:{port}', timeout=2)[0] is False
    assert check_proxy('http://127.0.0.1')[0] is False