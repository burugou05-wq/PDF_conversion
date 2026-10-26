#!/usr/bin/env python3
"""Sign / verify ``SHA256SUMS.txt`` with an offline ECDSA P-256 key.

The WinUI updater downloads ``SHA256SUMS.txt`` and ``SHA256SUMS.txt.sig`` from
the same GitHub Release.  A SHA-256 match alone only detects corruption: an
attacker who can replace release assets can replace the checksum file too.
The detached signature closes that gap.  Only the *public* half of the key is
embedded in the application (``Services/ReleaseSignature.cs``); the private
half must stay out of Git (see ``release-keys/README.md``).

Signature format: ECDSA P-256 / SHA-256, DER encoded (the default of
``openssl dgst -sha256 -sign`` and of .NET's
``DSASignatureFormat.Rfc3279DerSequence``).

Typical use::

    python scripts/release_signing.py generate --out-dir release-keys
    python scripts/release_signing.py sync-public-key \\
        --private-key release-keys/release-p256.key
    python scripts/release_signing.py sign \\
        --private-key release-keys/release-p256.key \\
        --checksums dist/SHA256SUMS.txt \\
        --output dist/SHA256SUMS.txt.sig
    python scripts/release_signing.py verify \\
        --checksums dist/SHA256SUMS.txt \\
        --signature dist/SHA256SUMS.txt.sig

The ``sign`` command refuses to proceed when the private key does not match
the public key compiled into the app, when ``SHA256SUMS.txt`` lacks a
``# tag: vX.Y.Z.W`` header, or when the signature cannot be verified with the
embedded public key.  CI uses the same command with a key from the protected
``release`` environment.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_KEY_SOURCE = REPO_ROOT / "winui" / "ImageToPDF.WinUI" / "Services" / "ReleaseSignature.cs"
PUBLIC_KEY_PATTERN = re.compile(
    r'(SubjectPublicKeyInfoBase64\s*=\s*\n?\s*")([A-Za-z0-9+/=]*)(")'
)
TAG_LINE_PATTERN = re.compile(rb"^# tag: v[0-9]+(?:\.[0-9]+){1,3}\s*$", re.MULTILINE)
KEY_FILE_NAME = "release-p256.key"
KEY_B64_FILE_NAME = "release-p256.key.b64"


class SigningError(RuntimeError):
    """Raised for user-facing signing problems."""


def _openssl(*args: str, stdin: bytes | None = None) -> bytes:
    executable = shutil.which("openssl")
    if executable is None:
        raise SigningError("openssl が見つかりません。OpenSSL 3 以降をインストールしてください。")
    result = subprocess.run(  # noqa: S603 - fixed executable, fixed argument list
        [executable, *args],
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise SigningError(f"openssl {' '.join(args[:2])} に失敗しました: {detail}")
    return result.stdout


def read_embedded_public_key(source: Path | None = None) -> str:
    """Return the Base64 SPKI currently embedded in the application."""
    source = source or PUBLIC_KEY_SOURCE
    match = PUBLIC_KEY_PATTERN.search(source.read_text(encoding="utf-8"))
    if match is None:
        raise SigningError(f"公開鍵の定数が見つかりません: {source}")
    return match.group(2)


def write_embedded_public_key(value: str, source: Path | None = None) -> None:
    """Replace the embedded SPKI constant (used when rotating keys)."""
    source = source or PUBLIC_KEY_SOURCE
    text = source.read_text(encoding="utf-8")
    replacement, count = PUBLIC_KEY_PATTERN.subn(
        lambda match: match.group(1) + value + match.group(3), text, count=1
    )
    if count != 1:
        raise SigningError(f"公開鍵の定数が見つかりません: {source}")
    source.write_text(replacement, encoding="utf-8")


def public_key_from_private(private_key: Path) -> str:
    """Return the Base64 SubjectPublicKeyInfo for a P-256 private key."""
    if not private_key.is_file():
        raise SigningError(f"秘密鍵が見つかりません: {private_key}")
    der = _openssl("pkey", "-in", str(private_key), "-pubout", "-outform", "DER")
    if not der:
        raise SigningError("公開鍵を導出できませんでした。")
    return base64.b64encode(der).decode("ascii")


def check_key(private_key: Path, source: Path | None = None) -> str:
    """Fail when the private key does not match the key compiled into the app."""
    source = source or PUBLIC_KEY_SOURCE
    actual = public_key_from_private(private_key)
    expected = read_embedded_public_key(source)
    if not expected:
        raise SigningError(
            "アプリに公開鍵が埋め込まれていません。sync-public-key を実行してください。"
        )
    if actual != expected:
        raise SigningError(
            "秘密鍵がアプリに埋め込まれた公開鍵と一致しません。"
            "鍵をローテーションした場合は sync-public-key で公開鍵を更新してください。"
        )
    return actual


def _check_checksums(checksums: Path) -> None:
    data = checksums.read_bytes()
    if not data:
        raise SigningError("SHA256SUMS.txt が空です。")
    if not TAG_LINE_PATTERN.search(data):
        raise SigningError(
            "SHA256SUMS.txt に '# tag: v<バージョン>' がありません。"
            "build_winui.ps1 が生成したファイルを使ってください。"
        )
    for line in data.decode("utf-8", "replace").splitlines():
        stripped = line.strip().lstrip("\ufeff")
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) != 2 or len(parts[0]) != 64:
            raise SigningError(f"SHA256SUMS.txt の形式が正しくありません: {line!r}")
        try:
            bytes.fromhex(parts[0])
        except ValueError as error:
            raise SigningError(f"SHA256SUMS.txt のハッシュが16進数ではありません: {line!r}") from error


def verify_signature(
    checksums: Path,
    signature: Path,
    public_key: str,
    *,
    validate_checksums: bool = True,
) -> None:
    """Verify a detached DER signature with a Base64 SPKI public key."""
    if validate_checksums:
        _check_checksums(checksums)
    if not signature.is_file() or signature.stat().st_size == 0:
        raise SigningError(f"署名ファイルが見つからないか空です: {signature}")
    if not public_key:
        raise SigningError("検証用の公開鍵が指定されていません。")

    try:
        public_key_der = base64.b64decode(public_key, validate=True)
    except (ValueError, binascii.Error) as error:
        raise SigningError("検証用の公開鍵が Base64 として正しくありません。") from error
    if not public_key_der:
        raise SigningError("検証用の公開鍵が空です。")

    with tempfile.TemporaryDirectory(prefix="imagetopdf-sign-") as temporary:
        key_path = Path(temporary) / "public.der"
        key_path.write_bytes(public_key_der)
        pem_path = Path(temporary) / "public.pem"
        pem_path.write_bytes(
            _openssl("pkey", "-pubin", "-inform", "DER", "-in", str(key_path), "-pubout")
        )
        _openssl(
            "dgst",
            "-sha256",
            "-verify",
            str(pem_path),
            "-signature",
            str(signature),
            str(checksums),
        )


def generate_key(out_dir: Path) -> tuple[Path, Path]:
    """Generate a new P-256 key pair and the Base64 form for a CI secret."""
    out_dir.mkdir(parents=True, exist_ok=True)
    key_path = out_dir / KEY_FILE_NAME
    b64_path = out_dir / KEY_B64_FILE_NAME
    if key_path.exists() or b64_path.exists():
        raise SigningError(f"既存の鍵があるため上書きしません: {out_dir}")
    _openssl(
        "genpkey",
        "-algorithm",
        "EC",
        "-pkeyopt",
        "ec_paramgen_curve:P-256",
        "-out",
        str(key_path),
    )
    os.chmod(key_path, 0o600)
    b64_path.write_text(
        base64.b64encode(key_path.read_bytes()).decode("ascii"), encoding="ascii"
    )
    os.chmod(b64_path, 0o600)
    return key_path, b64_path


def sign(
    private_key: Path,
    checksums: Path,
    output: Path,
    source: Path | None = None,
) -> None:
    """Sign checksums, asserting that the key matches the app's public key."""
    source = source or PUBLIC_KEY_SOURCE
    public_key = check_key(private_key, source)
    _check_checksums(checksums)
    output.parent.mkdir(parents=True, exist_ok=True)
    _openssl(
        "dgst",
        "-sha256",
        "-sign",
        str(private_key),
        "-out",
        str(output),
        str(checksums),
    )
    verify_signature(checksums, output, public_key)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="generate a new private key (never commit it)")
    generate.add_argument("--out-dir", type=Path, default=REPO_ROOT / "release-keys")

    public = sub.add_parser("public-key", help="print the Base64 SPKI of a private key")
    public.add_argument("--private-key", type=Path, required=True)

    check = sub.add_parser("check", help="check that a private key matches the embedded key")
    check.add_argument("--private-key", type=Path, required=True)

    sync = sub.add_parser("sync-public-key", help="embed the public key in the C# source")
    sync.add_argument("--private-key", type=Path, required=True)

    sign_parser = sub.add_parser("sign", help="sign SHA256SUMS.txt (DER ECDSA signature)")
    sign_parser.add_argument("--private-key", type=Path, required=True)
    sign_parser.add_argument("--checksums", type=Path, required=True)
    sign_parser.add_argument("--output", type=Path, required=True)

    verify = sub.add_parser("verify", help="verify SHA256SUMS.txt against its signature")
    verify.add_argument("--checksums", type=Path, required=True)
    verify.add_argument("--signature", type=Path, required=True)
    verify.add_argument(
        "--public-key",
        default=None,
        help="Base64 SPKI (default: the key embedded in ReleaseSignature.cs)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "generate":
            key_path, b64_path = generate_key(args.out_dir)
            print(f"秘密鍵: {key_path}")
            print(f"GitHub シークレット RELEASE_SIGNING_KEY_B64 の値: {b64_path}")
            print("公開鍵 (SPKI Base64): " + public_key_from_private(key_path))
            print(
                "次に sync-public-key を実行し、秘密鍵を安全な場所へ移して"
                "作業ツリーから削除してください。"
            )
        elif args.command == "public-key":
            print(public_key_from_private(args.private_key))
        elif args.command == "check":
            print(check_key(args.private_key) + " (一致)")
        elif args.command == "sync-public-key":
            value = public_key_from_private(args.private_key)
            write_embedded_public_key(value)
            print(f"公開鍵を {PUBLIC_KEY_SOURCE} に埋め込みました: {value}")
        elif args.command == "sign":
            sign(args.private_key, args.checksums, args.output)
            print(f"署名を作成して検証しました: {args.output}")
        elif args.command == "verify":
            key = args.public_key or read_embedded_public_key()
            verify_signature(args.checksums, args.signature, key)
            print("署名は有効です。")
        else:  # pragma: no cover - argparse rejects unknown commands
            raise SigningError(f"不明なコマンド: {args.command}")
    except (SigningError, OSError, ValueError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
