"""Offline HTTP Range regression tests: only authenticated packages become updates."""
import hashlib
import io
import json
import threading
from urllib.error import HTTPError

import pytest

from app.desktop import resumable_download as resumable
from app.desktop import updates


PAYLOAD = b'correct signed update archive - synthetic\n'
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


def item(size=len(PAYLOAD)):
    return updates.Release(
        version='0.9.1',
        name='extranjeria-cita-helper-0.9.1-windows-x64-portable.zip',
        url='https://github.com/vfunes26/Personalizado/releases/download/v0.9.1/synthetic.zip',
        sums_url='https://github.com/vfunes26/Personalizado/releases/download/v0.9.1/SHA256SUMS',
        size=size,
        attestation_url='https://github.com/vfunes26/Personalizado/releases/download/v0.9.1/synthetic.zip.sigstore.json',
    )


class Reply(io.BytesIO):
    def __init__(self, data, *, status=200, headers=None, fail_after_read=False,
                 after_read=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}
        self.fail_after_read = fail_after_read
        self.after_read = after_read
        self.reads = 0

    def read(self, size=-1):
        if self.fail_after_read and self.reads >= 1:
            raise ConnectionResetError('Mobile data connection interrupted')
        result = super().read(size)
        self.reads += 1
        if result and self.after_read:
            self.after_read()
        return result


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    # Network interruptions are simulated instantly in tests, without waiting.
    monkeypatch.setattr(resumable, '_pause',
                        lambda cancel, delay: (_ for _ in ()).throw(
                            InterruptedError('Download cancelled')) if cancel.is_set() else None)


def seed_interrupted(directory, cancel=None):
    release = item()
    progress = []
    requests = []

    def fetching(url, *, headers=None):
        requests.append(headers)
        return Reply(PAYLOAD[:10], headers={'ETag': '"release-091"'},
                     fail_after_read=True)
    with pytest.raises(resumable.DownloadNetworkError):
        resumable.fetch_package(
            release, directory, DIGEST, cancel or threading.Event(),
            fetch=fetching, progress=progress.append,
        )
    part = directory / (release.name + '.part')
    metadata = directory / (release.name + '.part.json')
    assert part.read_bytes() == PAYLOAD[:10]
    assert json.loads(metadata.read_text())['sha256'] == DIGEST
    return release, part, metadata, requests


def test_download_recovers_after_connection_failure_with_http_range(tmp_path):
    release, part, metadata, _ = seed_interrupted(tmp_path)
    calls = []

    def fetching(url, *, headers=None):
        calls.append(headers)
        assert headers == {'Range': 'bytes=10-', 'If-Range': '"release-091"'}
        return Reply(PAYLOAD[10:], status=206, headers={
            'Content-Range': f'bytes 10-{len(PAYLOAD)-1}/{len(PAYLOAD)}',
            'Content-Length': str(len(PAYLOAD)-10),
            'ETag': '"release-091"',
        })
    progress = []
    result = resumable.fetch_package(release, tmp_path, DIGEST,
                                     threading.Event(), fetch=fetching,
                                     progress=progress.append)
    assert result.read_bytes() == PAYLOAD
    assert calls == [{'Range':'bytes=10-', 'If-Range':'"release-091"'}]
    assert progress[0] == int(10 * 100 / len(PAYLOAD))
    assert progress[-1] == 100


def test_range_ignored_restores_from_zero_without_reusing_old_prefix(tmp_path):
    release, part, metadata, _ = seed_interrupted(tmp_path)
    calls = []

    def fetching(url, *, headers=None):
        calls.append(headers)
        assert headers and 'Range' in headers
        return Reply(PAYLOAD, status=200, headers={'Content-Length':str(len(PAYLOAD))})
    result = resumable.fetch_package(release, tmp_path, DIGEST,
                                     threading.Event(), fetch=fetching)
    assert result.read_bytes() == PAYLOAD
    assert len(calls) == 1


@pytest.mark.parametrize('content_range', ['bytes 0-9/40', 'bytes 10-39/40',
                                         'bytes 11-39/40', 'bytes wrong'])
def test_malformed_or_mismatched_content_range_removes_partial(tmp_path, content_range):
    release, part, meta, _ = seed_interrupted(tmp_path)

    def fetching(url, *, headers=None):
        return Reply(PAYLOAD[10:], status=206, headers={'Content-Range': content_range})
    with pytest.raises(ValueError):
        resumable.fetch_package(release, tmp_path, DIGEST, threading.Event(), fetch=fetching)
    assert not part.exists() and not meta.exists()


def test_changed_checksum_does_not_resume_stale_partial(tmp_path):
    release, part, meta, _ = seed_interrupted(tmp_path)
    new_payload = b'updated different bytes for different checksum'
    new_release = item(size=len(new_payload))
    new_digest = hashlib.sha256(new_payload).hexdigest()
    requests = []

    def fetching(url, *, headers=None):
        requests.append(headers)
        return Reply(new_payload)
    result = resumable.fetch_package(new_release, tmp_path, new_digest,
                                     threading.Event(), fetch=fetching)
    assert result.read_bytes() == new_payload
    assert requests == [None]


def test_cancellation_after_first_bytes_keeps_partial_and_resume_works(tmp_path):
    release = item()
    cancel = threading.Event()

    def fetching(url):
        return Reply(PAYLOAD[:10], after_read=cancel.set)
    with pytest.raises(InterruptedError):
        resumable.fetch_package(release, tmp_path, DIGEST, cancel, fetch=fetching)
    part = tmp_path / (release.name + '.part')
    assert part.read_bytes() == PAYLOAD[:10]
    cancel.clear()

    def next_fetch(url, *, headers=None):
        assert headers == {'Range': 'bytes=10-'}
        return Reply(PAYLOAD[10:], status=206, headers={
            'Content-Range':f'bytes 10-{len(PAYLOAD)-1}/{len(PAYLOAD)}'})
    assert resumable.fetch_package(release, tmp_path, DIGEST, cancel,
                                   fetch=next_fetch).read_bytes() == PAYLOAD


def test_tampered_complete_partial_is_rejected_and_fetched_again(tmp_path):
    release, part, meta, _ = seed_interrupted(tmp_path)
    part.write_bytes(b'x' * len(PAYLOAD))
    calls = []

    def fetching(url, *, headers=None):
        calls.append(headers)
        return Reply(PAYLOAD)
    result = resumable.fetch_package(release, tmp_path, DIGEST,
                                     threading.Event(), fetch=fetching)
    assert result.read_bytes() == PAYLOAD
    assert calls == [None]


def test_repeated_transient_http_503_preserves_existing_download(tmp_path):
    release, part, meta, _ = seed_interrupted(tmp_path)

    def fetching(url, *, headers=None):
        raise HTTPError(url, 503, 'Unavailable', {}, None)
    with pytest.raises(resumable.DownloadNetworkError):
        resumable.fetch_package(release, tmp_path, DIGEST,
                                threading.Event(), fetch=fetching)
    assert part.read_bytes() == PAYLOAD[:10]
    assert meta.exists()


def test_full_release_resumed_and_sigstore_verified_before_publication(tmp_path, monkeypatch):
    release, part, meta, _ = seed_interrupted(tmp_path)
    checked = []

    def signed_check(proof, name, digest, version, *, expected_commit):
        checked.append((name, digest, version, expected_commit))
        assert part.read_bytes() == PAYLOAD
        assert not (tmp_path/release.name).exists()
        return expected_commit
    monkeypatch.setattr(updates, 'verify_attestation', signed_check)

    def fetching(url, *, headers=None):
        if url == release.sums_url:
            return Reply((DIGEST + '  ' + release.name + '\n').encode())
        if url == release.url:
            assert headers == {'Range': 'bytes=10-', 'If-Range':'"release-091"'}
            return Reply(PAYLOAD[10:], status=206, headers={
                'Content-Range': f'bytes 10-{len(PAYLOAD)-1}/{len(PAYLOAD)}'})
        if url == release.attestation_url:
            return Reply(b'{}')
        if url.endswith('/git/ref/tags/v0.9.1'):
            return Reply(json.dumps({'object':{'type':'commit','sha':'b'*40}}).encode())
        raise AssertionError('Unexpected test URL')
    result = updates.download_release(release, tmp_path, threading.Event(), fetch=fetching)
    assert result.read_bytes() == PAYLOAD
    assert checked == [(release.name,DIGEST,release.version,'b'*40)]
    assert updates.checksum_for(result.with_name(result.name+'.sha256').read_bytes(),result.name)==DIGEST
    assert not part.exists() and not meta.exists()


def test_corrupt_completed_download_is_not_downloaded_twice(tmp_path):
    release = item()
    calls = []

    def fetching(url, *, headers=None):
        calls.append(headers)
        return Reply(b'X' * len(PAYLOAD))

    with pytest.raises(ValueError, match='checksum mismatch'):
        resumable.fetch_package(release, tmp_path, DIGEST,
                                threading.Event(), fetch=fetching)
    assert calls == [None]  # Do not waste another full download on mobile data.
    assert not (tmp_path / (release.name + '.part')).exists()
    assert not (tmp_path / (release.name + '.part.json')).exists()
