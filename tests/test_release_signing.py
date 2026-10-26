"""Tests for the offline release-signing helpers (A-2)."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "release_signing.py"
spec = importlib.util.spec_from_file_location("release_signing", MODULE_PATH)
assert spec is not None and spec.loader is not None
release_signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_signing)

HASH = "a" * 64
CHECKSUMS = f"# tag: v9.9.9.0\n{HASH}  ImageToPDF-Setup-v9.9.9.0-Windows-x64.exe\n"
KEY_SOURCE = 'internal const string SubjectPublicKeyInfoBase64 =\n        "";\n'


@pytest.fixture(scope="module")
def requires_openssl():
    if shutil.which("openssl") is None:
        pytest.skip("openssl is required for release signing tests")


@pytest.fixture
def signing_material(tmp_path, requires_openssl):
    key, _ = release_signing.generate_key(tmp_path / "keys")
    source = tmp_path / "ReleaseSignature.cs"
    source.write_text(KEY_SOURCE, encoding="utf-8")
    release_signing.write_embedded_public_key(
        release_signing.public_key_from_private(key), source
    )
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(CHECKSUMS, encoding="ascii")
    return key, source, checksums


def test_roundtrip_sign_and_verify(signing_material, tmp_path):
    key, source, checksums = signing_material
    signature = tmp_path / "SHA256SUMS.txt.sig"

    release_signing.sign(key, checksums, signature, source)
    assert signature.is_file() and signature.stat().st_size > 0

    public_key = release_signing.read_embedded_public_key(source)
    release_signing.verify_signature(checksums, signature, public_key)
    assert release_signing.check_key(key, source) == public_key


def test_tampered_checksums_fail(signing_material, tmp_path):
    key, source, checksums = signing_material
    signature = tmp_path / "SHA256SUMS.txt.sig"
    release_signing.sign(key, checksums, signature, source)
    checksums.write_text(CHECKSUMS.replace(HASH, "b" * 64), encoding="ascii")

    with pytest.raises(release_signing.SigningError):
        release_signing.verify_signature(
            checksums,
            signature,
            release_signing.read_embedded_public_key(source),
            validate_checksums=False,
        )


def test_tampered_signature_fails(signing_material, tmp_path):
    key, source, checksums = signing_material
    signature = tmp_path / "SHA256SUMS.txt.sig"
    release_signing.sign(key, checksums, signature, source)
    data = bytearray(signature.read_bytes())
    data[-1] ^= 0x01
    signature.write_bytes(data)

    with pytest.raises(release_signing.SigningError):
        release_signing.verify_signature(
            checksums, signature, release_signing.read_embedded_public_key(source)
        )


def test_wrong_key_fails(signing_material, tmp_path):
    key, source, _ = signing_material
    other_key, _ = release_signing.generate_key(tmp_path / "other-keys")
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(CHECKSUMS, encoding="ascii")
    signature = tmp_path / "SHA256SUMS.txt.sig"

    with pytest.raises(release_signing.SigningError, match="一致しません"):
        release_signing.sign(other_key, checksums, signature, source)

    # The correct key still works after the failed attempt.
    assert not signature.exists()
    release_signing.sign(key, checksums, signature, source)
    release_signing.verify_signature(
        checksums, signature, release_signing.read_embedded_public_key(source)
    )


def test_sync_public_key_and_check(tmp_path, requires_openssl):
    key, _ = release_signing.generate_key(tmp_path / "keys")
    source = tmp_path / "ReleaseSignature.cs"
    source.write_text(KEY_SOURCE, encoding="utf-8")

    assert release_signing.read_embedded_public_key(source) == ""
    with pytest.raises(release_signing.SigningError, match="埋め込まれていません"):
        release_signing.check_key(key, source)

    release_signing.write_embedded_public_key(
        release_signing.public_key_from_private(key), source
    )
    assert release_signing.check_key(key, source).startswith("MFkw")
    assert KEY_SOURCE.split('"";')[0] in source.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "content",
    [
        f"{HASH}  installer.exe\n",  # missing tag header
        "# tag: v1.0.0.0\nnot-a-hash  installer.exe\n",  # invalid hash
        "",  # empty file
    ],
)
def test_sign_rejects_bad_checksums(signing_material, tmp_path, content):
    key, source, _ = signing_material
    checksums = tmp_path / "bad.txt"
    checksums.write_text(content, encoding="ascii")
    with pytest.raises(release_signing.SigningError):
        release_signing.sign(key, checksums, tmp_path / "bad.sig", source)


def test_generate_refuses_overwrite(tmp_path, requires_openssl):
    out_dir = tmp_path / "keys"
    release_signing.generate_key(out_dir)
    with pytest.raises(release_signing.SigningError, match="上書きしません"):
        release_signing.generate_key(out_dir)


def test_cli_verify_command(monkeypatch, signing_material, tmp_path):
    key, source, checksums = signing_material
    signature = tmp_path / "SHA256SUMS.txt.sig"
    release_signing.sign(key, checksums, signature, source)
    monkeypatch.setattr(release_signing, "PUBLIC_KEY_SOURCE", source)

    assert release_signing.main(
        [
            "verify",
            "--checksums",
            str(checksums),
            "--signature",
            str(signature),
        ]
    ) == 0
