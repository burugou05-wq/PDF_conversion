# リリース署名鍵（秘密鍵は Git に含めない）

このフォルダーには **ローカルで生成した ECDSA P-256 の秘密鍵** を置きます。`.gitignore`
により `*.key` / `*.key.b64` / `*.pem` / `*.der` はコミットされません。公開鍵だけが
`winui/ImageToPDF.WinUI/Services/ReleaseSignature.cs` に埋め込まれています。

## このリポジトリで生成済みの鍵

エージェントが初回セットアップ用に鍵ペアを生成しました。

| ファイル | 内容 | 扱い |
| --- | --- | --- |
| `release-p256.key` | 秘密鍵（PEM, PKCS#8） | **秘密**。GitHub の `release` environment のシークレット `RELEASE_SIGNING_KEY_B64` に登録したら、安全な保管庫（パスワードマネージャー等）へ移し、作業ツリーから削除してください。 |
| `release-p256.key.b64` | ↑ の Base64（`RELEASE_SIGNING_KEY_B64` の値） | **秘密**。↑ と同じ扱い。 |
| `README.md` | このファイル | 公開 |

> 2026-10-26 更新: Agent のワークスペース復元時に gitignore 済みの初回鍵が失われたため、
> v2.3.1.1 の公開前に鍵ペアを再生成し、`sync-public-key` で埋め込み公開鍵を差し替えました。
> 旧公開鍵は一度も Release に含まれていないため、利用者への影響はありません。

- 埋め込み公開鍵（SPKI / Base64）: `python scripts/release_signing.py public-key --private-key release-keys/release-p256.key`
- 一致確認: `python scripts/release_signing.py check --private-key release-keys/release-p256.key`

> **重要**: この鍵は Agent のサンドボックス内で生成しました。本番運用では、可能であれば
> 管理者の手元で `python scripts/release_signing.py generate --out-dir release-keys` を
> 実行し、`sync-public-key` で公開鍵を差し替えてから、新しい秘密鍵を GitHub シークレットに
> 登録してください。鍵を差し替えた場合は [RELEASING.md](../RELEASING.md) の
> 「鍵のローテーション」を読んでください。

## コマンド

```bash
# 新しい鍵ペアを作る（既存ファイルがあるときは上書きしません）
python scripts/release_signing.py generate --out-dir release-keys

# 公開鍵をアプリの ReleaseSignature.cs に埋め込む
python scripts/release_signing.py sync-public-key --private-key release-keys/release-p256.key

# SHA256SUMS.txt に署名（鍵の一致と署名の検証まで行います）
python scripts/release_signing.py sign \
    --private-key release-keys/release-p256.key \
    --checksums dist/SHA256SUMS.txt \
    --output dist/SHA256SUMS.txt.sig

# 署名を検証
python scripts/release_signing.py verify \
    --checksums dist/SHA256SUMS.txt --signature dist/SHA256SUMS.txt.sig
```

CI は秘密鍵を直接読みません。`publish-release` ジョブが `release` environment の
シークレット `RELEASE_SIGNING_KEY_B64` を一時ファイルに復元し、同じ `sign` コマンドで
署名した後、その一時ファイルを削除します。詳細は [RELEASING.md](../RELEASING.md)。
