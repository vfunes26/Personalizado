"""Comprobacion previa de un proxy: alcanzable, credenciales validas y tunel hacia el sitio.

Sin Qt y sin dependencias externas. Se ejecuta en un hilo auxiliar antes de lanzar
el trabajador, de modo que un proxy caido nunca afecta a los demas trabajadores.
"""
import base64
import socket
import ssl
from contextlib import suppress
from urllib.parse import urlsplit

TARGET_HOST = 'icp.administracionelectronica.gob.es'
TARGET_PORT = 443


def normalize_proxy(server, username='', password=''):
    """Acepta host:puerto, host:puerto:usuario:clave, usuario:clave@host:puerto y esquema opcional.

    Devuelve (servidor_con_esquema, usuario, clave). Sin esquema se asume http://.
    Los campos usuario/clave ya escritos tienen prioridad sobre los pegados en el servidor.
    """
    text = (server or '').strip()
    username, password = (username or '').strip(), password or ''
    if not text:
        return '', username, password
    scheme = 'http'
    if '://' in text:
        scheme, text = text.split('://', 1)
        scheme = scheme.strip().lower() or 'http'
    text = text.strip().rstrip('/')
    if '@' in text:
        credentials, text = text.rsplit('@', 1)
        user_part, _, pass_part = credentials.partition(':')
        username, password = username or user_part, password or pass_part
    else:
        parts = text.split(':')
        if len(parts) == 4:
            text = ':'.join(parts[:2])
            username, password = username or parts[2], password or parts[3]
    return f'{scheme}://{text}', username, password


def _read_exact(sock, size):
    data = b''
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError('El proxy cerro la conexion')
        data += chunk
    return data


def _http_connect(sock, username, password):
    request = f'CONNECT {TARGET_HOST}:{TARGET_PORT} HTTP/1.1\r\nHost: {TARGET_HOST}:{TARGET_PORT}\r\n'
    if username:
        token = base64.b64encode(f'{username}:{password}'.encode('utf-8')).decode('ascii')
        request += f'Proxy-Authorization: Basic {token}\r\n'
    sock.sendall((request + '\r\n').encode('ascii'))
    data = b''
    while b'\r\n\r\n' not in data and len(data) < 8192:
        chunk = sock.recv(1024)
        if not chunk:
            break
        data += chunk
    line = data.split(b'\r\n', 1)[0].decode('latin-1').strip()
    parts = line.split()
    code = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
    if code == 200:
        return True, 'Proxy operativo'
    if code == 407:
        return False, 'Credenciales del proxy rechazadas (407)'
    if code == 403:
        return False, 'El proxy no permite el acceso al sitio (403)'
    return False, 'Respuesta inesperada del proxy: ' + (line or 'vacia')


def _socks5(sock, username, password):
    sock.sendall(b'\x05\x02\x00\x02' if username else b'\x05\x01\x00')
    reply = _read_exact(sock, 2)
    if reply[0] != 5:
        return False, 'El servidor no responde como SOCKS5'
    if reply[1] == 0xFF:
        return False, 'El proxy SOCKS5 no acepta el metodo de autenticacion'
    if reply[1] == 2:
        if not username:
            return False, 'El proxy SOCKS5 exige usuario y contrasena'
        user, secret = username.encode('utf-8'), password.encode('utf-8')
        sock.sendall(b'\x01' + bytes([len(user)]) + user + bytes([len(secret)]) + secret)
        if _read_exact(sock, 2)[1] != 0:
            return False, 'Credenciales del proxy SOCKS5 rechazadas'
    host = TARGET_HOST.encode('ascii')
    sock.sendall(b'\x05\x01\x00\x03' + bytes([len(host)]) + host + TARGET_PORT.to_bytes(2, 'big'))
    answer = _read_exact(sock, 4)
    if answer[1] != 0:
        return False, f'El proxy SOCKS5 no pudo abrir el tunel (codigo {answer[1]})'
    return True, 'Proxy operativo'


def check_proxy(server, username='', password='', timeout=8.0):
    """Devuelve (ok, detalle). Nunca lanza excepciones."""
    try:
        parts = urlsplit(server)
        scheme, host, port = parts.scheme.lower(), parts.hostname, parts.port
    except ValueError:
        return False, 'Direccion de proxy invalida'
    if not host or not port:
        return False, 'El proxy debe incluir servidor y puerto'
    try:
        raw = socket.create_connection((host, port), timeout=timeout)
    except socket.timeout:
        return False, f'Sin respuesta de {host}:{port} (tiempo agotado)'
    except socket.gaierror:
        return False, f'No se pudo resolver el servidor {host}'
    except ConnectionRefusedError:
        return False, f'Conexion rechazada por {host}:{port}'
    except OSError as exc:
        return False, f'No se pudo conectar a {host}:{port}: {exc}'
    sock = raw
    try:
        raw.settimeout(timeout)
        if scheme == 'socks5':
            return _socks5(raw, username or '', password or '')
        if scheme == 'https':
            sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        return _http_connect(sock, username or '', password or '')
    except socket.timeout:
        return False, f'El proxy {host}:{port} no respondio a tiempo'
    except (OSError, ssl.SSLError, ValueError) as exc:
        return False, f'Error del proxy {host}:{port}: {exc}'
    finally:
        with suppress(OSError):
            sock.close()
        if sock is not raw:
            with suppress(OSError):
                raw.close()