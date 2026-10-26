# リリースと署名の運用

自動更新の安全性は「Release の Assets を誰も後から差し替えられないこと」と
「アプリが署名を検証すること」の2段で担保します。このドキュメントはリリース担当者向けです。

## 仕組み（概要）

1. `v<バージョン>` タグを push したときだけ、`ci.yml` の `publish-release` ジョブが動きます。
   `workflow_dispatch` / `pull_request` / ブランチへの push では**公開しません**
   （テストとビルドだけ実行されます）。
2. ジョブは保護された GitHub environment `release` で動きます（承認者必須を設定）。
3. `SHA256SUMS.txt` に ECDSA P-256 の秘密鍵で署名し、`SHA256SUMS.txt.sig` を Assets に加えます。
   秘密鍵は `release` environment のシークレット `RELEASE_SIGNING_KEY_B64` にだけ置き、
   ジョブ内では一時ファイルに復元して署名後に削除します。
4. `actions/attest-build-provenance` でインストーラーとチェックサムの来歴証明を作成します。
5. 同名タグの Release が既に存在する場合は `--clobber` せず、**ジョブを失敗させます**。
   `gh release create --verify-tag` で、タグがリモートに実在することも確認します。
6. アプリは `SHA256SUMS.txt.sig` を内蔵公開鍵で検証し、チェックサム内の `# tag:` が
   Release のタグと一致すること、SHA-256 とサイズが一致することを確認してから
   インストーラーを起動します。

`SHA256SUMS.txt` の形式（`build_winui.ps1` が生成、CI が署名）:

```text
# tag: v2.3.2.0
<installer の SHA-256>  ImageToPDF-Setup-v2.3.2.0-Windows-x64.exe
```

`# tag:` 行も署名対象です。これがないファイルは `scripts/release_signing.py sign` が拒否し、
アプリも検証を通しません（正規の古い Assets を使い回すダウングレードを防ぐため）。

## 初回セットアップ（1回だけ）

### 1. 署名鍵を用意する

`release-keys/README.md` に、このリポジトリ用に生成済みの鍵があります。
本番運用では管理者の手元で作り直すことを推奨します。

```bash
python scripts/release_signing.py generate --out-dir release-keys
python scripts/release_signing.py sync-public-key --private-key release-keys/release-p256.key
python scripts/release_signing.py check --private-key release-keys/release-p256.key
```

- `sync-public-key` は `winui/ImageToPDF.WinUI/Services/ReleaseSignature.cs` の
  `SubjectPublicKeyInfoBase64` を書き換えます。**この変更はコミットしてください**
  （公開鍵なので秘匿情報ではありません）。
- 秘密鍵 `release-keys/*.key` / `*.key.b64` は `.gitignore` によりコミットされません。
  パスワードマネージャー等へ退避し、作業ツリーから削除してください。

### 2. GitHub 側を設定する

リポジトリの Settings で次を設定します。**これを怠ると `publish-release` は失敗します**
（＝署名なしの Release は作らない、というフェイルクローズ設計です）。

- **Settings → Environments → New environment: `release`**
  - 「Required reviewers」に自分（または複数人）を追加。
  - 必要なら「Deployment branches and tags」をタグ `v*` に限定。
  - Environment secrets に `RELEASE_SIGNING_KEY_B64` を追加。値は
    `release-keys/release-p256.key.b64` の中身（秘密鍵 PEM の Base64、改行なし）。
- **Settings → General → Releases → Immutable releases** を有効化
  （公開済み Release の Assets やタイトル/本文の変更を GitHub 側でも禁止）。
- **Settings → Code and automation → Tags → Protect tags**: `v*` を保護し、
  タグの作成・削除を管理者だけに限定。
- 可能なら `main` にもブランチ保護（PR 必須・force push 禁止）を設定。

> Immutable Releases / タグ保護は GitHub のプランや UI 変更で名称・場所が変わることがあります。
> 設定画面で見つからない場合は GitHub の最新ドキュメントを確認してください。

### 3. 動作確認（任意）

```bash
python scripts/release_signing.py verify \
    --checksums dist/SHA256SUMS.txt --signature dist/SHA256SUMS.txt.sig
gh attestation verify dist/ImageToPDF-Setup-v<version>-Windows-x64.exe \
    --owner burugou05-wq
```

## 通常のリリース手順

1. `app_config.py` の `VERSION`、`MainWindow.xaml` の表示、
   `ImageToPDF.WinUI.csproj` の `Version`、`CHANGELOG.md` の `## v<バージョン> <タイトル>`
   を一致させます（`build_winui.ps1` が整合を検査します）。
2. 変更をコミットして CI が緑になるのを待ちます（`workflow_dispatch` でビルドだけ確認できます）。
3. タグ `v<バージョン>` を push します。
4. `publish-release` ジョブが `release` environment の承認待ちになるので、内容を確認して承認します。
5. Release に次の5点が揃っていることを確認します。
   - `ImageToPDF-Setup-v<version>-Windows-x64.exe`
   - `SHA256SUMS.txt`
   - `SHA256SUMS.txt.sig`
   - `LICENSE`
   - `THIRD_PARTY_NOTICES.md`
6. 既存 Release を差し替えたい場合は**新しいバージョンを出してください**。
   `--clobber` による上書きは削除済みで、同名タグの再実行は失敗します。

## 鍵のローテーション

秘密鍵を漏えいした・定期更新したい場合は次の手順です。

1. 新しい鍵を `generate` し、`sync-public-key` で C# の公開鍵を差し替えます。
2. GitHub の `RELEASE_SIGNING_KEY_B64` を新しい値に更新します。
3. **注意**: 旧版のアプリは古い公開鍵しか持たないため、新しい鍵で署名された Release を
   自動更新で受け取れません。旧版を配布中の利用者には手動インストールを案内するか、
   新旧どちらの鍵も検証できる「橋渡しバージョン」を一度リリースしてください
   （`ReleaseSignature` の検証を複数鍵対応にする改修が必要です）。

## 残っているリスク（未対応）

- **コード署名（Authenticode）は未実装です。** 配布物は依然として未署名の PyInstaller 製
  EXE を含むため SmartScreen の警告や誤検知が発生します。さらに `HttpClient` で取得した
  ファイルには Mark of the Web が付かないため、自動更新は SmartScreen の確認を通らずに
  サイレントインストールされます。SignPath Foundation / Certum などの OSS 向け証明書を
  導入し、署名後に `WinVerifyTrust` で署名者の拇印まで確認する改修が次の一手です。
- **v2.3.1.0 以前のクライアントは署名を検証しません。** 過去に配布した版を回収することは
  できないため、GitHub 側の Immutable Releases・タグ保護・アカウントの MFA が重要です。
- **署名鍵は CI の environment シークレットにあります。** 承認者必須の environment と
  最小権限の `permissions` で保護していますが、リポジトリ管理者権限を持つ攻撃者には
  無力です。最も厳格にするなら、CI では署名せず、リリース担当者の手元で署名した
  `SHA256SUMS.txt.sig` を Release 作成時に添付する方式に変更してください。
- チェックサム照合と MZ ヘッダー確認は**破損の検出**です。真正性は署名検証が担います。
