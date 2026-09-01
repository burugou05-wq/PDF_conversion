# 画像→PDF 変換ツール

## 使い方（EXEを手に入れるまで）

### 必要なもの
- Windows 10 / 11
- Python 3.8 以上（https://www.python.org/downloads/）
  ※インストール時に「Add Python to PATH」にチェックを入れてください

### EXEのビルド手順
1. このフォルダを任意の場所に展開する
2. PowerShell を開く（フォルダ内で右クリック → PowerShell で開く）
3. `python build.py` を実行
4. 自動でライブラリのインストール＆ビルドが実行される
5. `dist\画像PDF変換ツール.exe` が完成 → 好きな場所にコピーしてOK

**注意**: `build_exe.bat` は古いため使用しないでください。`build.py` をご使用ください。

---

## 開発者向け情報

### 依存関係
`requirements.txt` に記載されています。手動インストール時は以下を実行：
```
pip install -r requirements.txt
```

### UPDATE_URL の設定（配布時）
`img2pdf_app.py` の以下の行を変更してください：
```python
UPDATE_URL = "https://example.com/version.json"  # 実際の URL に置き換える
```

version.json の形式例：
```json
{
  "version": "1.1",
  "url": "https://example.com/download/1.1",
  "release_notes": "新機能追加"
}
```

1. `画像PDF変換.exe` を起動
2. **「参照…」** ボタンで画像が入ったフォルダを選ぶ
   - 対応形式: JPEG / AVIF / WebP / PNG / BMP / GIF / TIFF
   - ファイル名の昇順（辞書順）で自動整列
3. **画質を選択する（変換ボタンの上）**
   - 標準：軽量・従来通り（150dpi JPEG）
   - 高画質：300dpi / JPEG品質95（ファイルサイズ大）
   - ★ 超高画質（劣化なし）：元画像バイトをそのままPDFに埋め込み
     ※ファイルサイズが非常に大きくなります
4. 必要に応じて出力先PDFパスを変更する
5. **「PDF に変換する」** ボタンを押す → 完了！

---

## 注意事項
- 同フォルダ内の対応画像ファイルをすべて結合します（サブフォルダは対象外）
- ファイル数が多い場合は変換に数十秒かかることがあります
- 超高画質モードは `img2pdf` ライブラリを使用します（build.py で自動インストール）
