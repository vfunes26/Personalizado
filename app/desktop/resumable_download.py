"""Bounded, resumable HTTPS downloads of immutable, checksum-pinned releases.

Only a matching .part and its identity sidecar may be resumed. A partial file
is never installable. Callers must still verify SHA-256 and Sigstore provenance.
"""
from contextlib import closing
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import ssl
import tempfile
from urllib.error import HTTPError, URLError

MAX_ATTEMPTS = 4
CHUNK_BYTES = 1024 * 1024
CONTENT_RANGE = re.compile(r'bytes ([0-9]+)-([0-9]+)/([0-9]+)\Z')
STRONG_ETAG = re.compile(r'"[\x21\x23-\x7e]{1,150}"\Z')


class DownloadNetworkError(OSError):
    """The valid partial remains on disk for the next attempt."""


def _remove(part, meta):
    part.unlink(missing_ok=True)
    meta.unlink(missing_ok=True)


def _safe_file(path):
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Unsafe download path')


def _metadata(release, checksum):
    return {
        'version': release.version,
        'name': release.name,
        'url': release.url,
        'size': release.size,
        'sha256': checksum,
    }


def _write_meta(path, value):
    fd, temporary = tempfile.mkstemp(prefix='.update-resume-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read_partial(part, meta, expected):
    _safe_file(part)
    _safe_file(meta)
    if not part.exists() or not meta.is_file():
        _remove(part, meta)
        return dict(expected)
    try:
        if meta.stat().st_size > 4096:
            raise ValueError()
        record = json.loads(meta.read_text(encoding='utf-8'))
        if not isinstance(record, dict) or any(record.get(k) != v for k, v in expected.items()):
            raise ValueError()
        if set(record) - (set(expected) | {'etag'}):
            raise ValueError()
        etag = record.get('etag', '')
        if not isinstance(etag, str) or (etag and not STRONG_ETAG.fullmatch(etag)):
            raise ValueError()
        if not 0 <= part.stat().st_size <= expected['size']:
            raise ValueError()
        return record
    except (ValueError, TypeError, OSError):
        _remove(part, meta)
        return dict(expected)


def _pause(cancel, seconds):
    if cancel.wait(seconds):
        raise InterruptedError('Download cancelled')


def _header(response, name):
    return (getattr(response, 'headers', None) or {}).get(name)


def _status(response):
    value = getattr(response, 'status', None)
    if value is None:
        value = 200  # In-memory tests without a HTTP response object.
    return value


def _download_once(release, part, meta, record, cancel, fetch, progress):
    offset = part.stat().st_size if part.exists() else 0
    headers = {}
    if offset:
        headers['Range'] = f'bytes={offset}-'
        if record.get('etag'):
            headers['If-Range'] = record['etag']
    with closing(fetch(release.url, headers=headers) if headers else fetch(release.url)) as response:
        status = _status(response)
        if status not in (200, 206):
            raise ValueError('Unexpected HTTP status for download')
        if offset and status == 200:
            # Range unsupported or If-Range validator changed: restart clean.
            offset = 0
            record.pop('etag', None)
            part.write_bytes(b'')
        end = release.size - 1
        if status == 206:
            match = CONTENT_RANGE.fullmatch(str(_header(response, 'Content-Range') or ''))
            if match is None:
                raise ValueError('Missing HTTP Content-Range')
            first, last, total = map(int, match.groups())
            if first != offset or total != release.size or last < first or last >= release.size:
                raise ValueError('Untrusted HTTP Content-Range')
            end = last
        elif offset:
            raise ValueError('Unexpected HTTP resume state')

        etag = _header(response, 'ETag')
        if etag and STRONG_ETAG.fullmatch(str(etag)):
            if status == 206 and record.get('etag') and record['etag'] != etag:
                raise ValueError('HTTP validator changed while resuming')
            record['etag'] = str(etag)
        elif status == 200:
            record.pop('etag', None)
        _write_meta(meta, record)

        length = _header(response, 'Content-Length')
        if length is not None:
            if (not str(length).isdecimal() or
                    int(length) != end - offset + 1):
                raise ValueError('Unexpected HTTP Content-Length')
        progress(int(offset * 100 / release.size))
        with part.open('ab') as output:
            while True:
                if cancel.is_set():
                    raise InterruptedError('Download cancelled')
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise ValueError('Invalid HTTP response body')
                if output.tell() + len(chunk) > end + 1:
                    raise ValueError('HTTP response exceeds promised range')
                output.write(chunk)
                progress(int(output.tell() * 100 / release.size))
            output.flush()
            os.fsync(output.fileno())
        return part.stat().st_size == end + 1


def fetch_package(release, directory, checksum, cancel, *, fetch, progress=lambda _p: None):
    """Return a complete SHA-256-valid .part; keep valid bytes on interruption."""
    if cancel.is_set():
        raise InterruptedError('Download cancelled')
    if (Path(release.name).name != release.name or not release.name or
            not re.fullmatch(r'[a-f0-9]{64}', checksum)):
        raise ValueError('Invalid download metadata')
    directory = Path(directory)
    _safe_file(directory / release.name)
    directory.mkdir(parents=True, exist_ok=True)
    part = directory / (release.name + '.part')
    meta = directory / (release.name + '.part.json')
    expected = _metadata(release, checksum)
    record = _read_partial(part, meta, expected)

    for attempt in range(MAX_ATTEMPTS):
        if cancel.is_set():
            raise InterruptedError('Download cancelled')
        count = part.stat().st_size if part.exists() else 0
        if count == release.size:
            # Local cache is never trusted until the entire file is re-hashed.
            with part.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != checksum:
                _remove(part, meta)
                if attempt == MAX_ATTEMPTS - 1:
                    raise ValueError('Downloaded package checksum mismatch')
                record = dict(expected)
                continue
            progress(100)
            return part
        try:
            reached_end = _download_once(release, part, meta, record, cancel, fetch, progress)
            if part.stat().st_size == release.size:
                with part.open('rb') as stream:
                    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
                if actual == checksum:
                    progress(100)
                    return part
                # A freshly downloaded, full-size file with the wrong hash
                # is corrupted. Do not download another full copy on metered
                # connections; an explicit later attempt may retry.
                _remove(part, meta)
                raise ValueError('Downloaded package checksum mismatch')
            if reached_end:
                # Some servers choose a shorter 206 range; request the remainder.
                continue
        except HTTPError as exc:
            if exc.code == 416 and count:
                _remove(part, meta)
                record = dict(expected)
                continue
            if exc.code not in (408, 425, 429, 500, 502, 503, 504):
                raise
        except (URLError, ConnectionError, TimeoutError, socket.timeout,
                http.client.IncompleteRead, ssl.SSLError):
            pass
        except ValueError:
            _remove(part, meta)
            raise
        if attempt != MAX_ATTEMPTS - 1:
            _pause(cancel, min(2 ** attempt, 4))
    raise DownloadNetworkError('Conexión interrumpida. La descarga parcial está guardada.')


def discard_partial(directory, name):
    directory = Path(directory)
    part = directory / (name + '.part')
    meta = directory / (name + '.part.json')
    _safe_file(part)
    _safe_file(meta)
    _remove(part, meta)
