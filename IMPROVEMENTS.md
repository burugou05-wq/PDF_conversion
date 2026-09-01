# PDF 変換ツール v1.0 - 改善記録

## 実施した改善

### 1️⃣ ビルド手段の統一
- **削除**: `build_exe.bat`（古い、シンプルな実装）
- **統一**: `build.py` をメインビルドツールに決定
- **更新**: README で `python build.py` 実行を推奨

**理由**: 
- PyInstaller の隠し依存関係が `build.py` でのみ完全対応
- EXE 名も統一（`画像PDF変換ツール.exe`）
- DPI 対応（manifest）が `build.py` でのみサポート

---

### 2️⃣ 依存関係の明示化
**新規作成**: `requirements.txt`

```
tkinterdnd2>=0.3.0          # UI ドラッグ&ドロップ
Pillow>=9.0.0               # 画像処理
pillow-avif-plugin>=1.0.0   # AVIF 対応
pillow-heif>=0.7.0          # HEIF/HEIC 対応
img2pdf>=0.4.4              # PDF 生成
PyTurboJPEG>=1.7.0          # JPEG 高速化（オプション）
numpy>=1.20.0               # JPEG 高速化の補助
PyInstaller>=5.0.0          # EXE ビルド
```

**改善**:
- `build.py` を `requirements.txt` から自動インストールするように修正
- PyInstaller の隠し依存関係が明示的にリスト化
- 開発者が依存関係の全体像を把握しやすく

---

### 3️⃣ コード分割（モジュール化）
**新規作成**:
- `image_processor.py` (9.8 KB)
  - 画像形式判定（JPEG/PNG/WebP/etc）
  - 一時ファイル生成（PNG/JPEG）
  - レイアウト計算（ページサイズ・余白）
  - マルチスレッド並列処理
  - PDF 変換エンジン（convert_to_pdf）

- `ui_theme.py` (5.4 KB)
  - Google Material Design カラーパレット
  - tkinter ttk スタイル定義
  - `apply_theme()` 関数

**メリット**:
- img2pdf_app.py の責務が明確に：UI ロジックのみ
- 関心の分離：UI / 画像処理 / テーマが独立
- テスト・保守が容易
- 再利用可能な image_processor モジュール

---

### 4️⃣ UPDATE_URL の明示化
**更新ファイル**:
1. `README.md` - 開発者向け情報セクション追加
   - UPDATE_URL 設定方法
   - version.json の形式例

2. `build.py` - コンソール出力に案内追加
   ```
   【配布・アップデート設定】
   このスクリプトの img2pdf_app.py 内 UPDATE_URL を設定してください：
   例) UPDATE_URL = 'https://example.com/version.json'
   ```

3. `img2pdf_app.py` - UPDATE_URL コメント拡充
   - 実際の URL 例示
   - build.py のコメント参照指示

---

## 効果

| 項目 | 改善前 | 改善後 |
|---|---|---|
| ビルド手段 | 2種類（混乱） | build.py のみ |
| 依存関係の可視化 | 隠し依存が混在 | requirements.txt で明示 |
| img2pdf_app.py | 69 KB（1296 行） | 継続して UI に特化 |
| UPDATE_URL | コメント曖昧 | 詳細なドキュメント |
| 保守性 | 低 | ↑ 向上 |
| 再利用性 | なし | image_processor.py は独立使用可能 |

---

## 今後の展開案

1. **unit test 追加**
   - `test_image_processor.py` - 画像形式判定・レイアウト計算テスト
   - `test_ui_theme.py` - スタイル適用テスト

2. **CLI モード追加**
   - `image_processor.py` のみ使用して、ヘッドレス変換対応

3. **ローカライゼーション**
   - 日本語固定 → 多言語対応（i18n）

4. **バージョン管理の自動化**
   - VERSION 定数を version.json から読み込み
   - アップデートエラーハンドリング充実
