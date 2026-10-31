# 改善計画（v2.3.1.2 以降）

v2.3.1.2 時点のコードを読んで洗い出した、新機能と改善の候補です。
「価値 ÷ 手間」の順に並べ、上から着手する想定です。各項目に触るファイルと
検証方法を書いてあるので、1項目＝1リリース（または1PR）で進められます。

優先度の目安: ★★★ 日常利用で毎回効く / ★★ 特定の用途で効く / ★ 開発・運用の快適さ

---

## フェーズ1: 日常利用の不満をなくす（v2.4.0）

### 1-1. 変換設定を記憶する ★★★

- 現状: 起動のたびに画質・用紙・余白・DPI・背景・自動回転・「完了後に開く」が初期値に戻る。
  README の「制限・運用」にも明記されている既知の制限。
- 内容: 終了時に `%LOCALAPPDATA%\ImageToPDF\settings.json` へ保存し、起動時に復元する。
  「フォルダー並び順」「リスト／グリッド」「前回の保存先フォルダー」「ウィンドウサイズ」も対象。
- 触る場所: `MainWindow.xaml.cs`（`_settingsReady` の前後）、新規 `Services/AppSettings.cs`。
- 注意: 壊れた JSON や範囲外の値は無視して初期値にする（DPI の 1〜10000 検査を流用）。
  アンインストール時に `%LOCALAPPDATA%\ImageToPDF` ごと消える設計なので、追加の作業は不要。
- 検証: 設定を変えて終了 → 再起動で復元されること。JSON を手で壊しても起動できること。

### 1-2. 一覧のドラッグで並べ替え ★★★

- 現状: 「先頭へ／上へ／下へ／末尾へ」ボタンだけ。50枚の中から1枚を途中へ動かすのが面倒。
- 内容: `ListView` の `CanReorderItems="True"` と `AllowDrop="True"` を有効にし、
  `VisibleItems` の並び替えを `_items` へ反映する。
- 注意: 検索で絞り込み中は `VisibleItems` と `_items` の添字がずれる。絞り込み中は
  ドラッグ並べ替えを無効にする（既存の「移動は全体順序を変更」の規則を守る）か、
  `VisibleItems` 上の前後関係を `_items` へ写す処理を書く。
  外部ファイルのドロップ（`Root_Drop`）とイベントが競合しないよう、ListView 側の
  `DragItemsStarting` で内部ドラッグかどうかを区別する。
- 触る場所: `MainWindow.xaml`（ListView）、`MainViewModel.cs`（`MoveTo(index)` 追加）。

### 1-3. 一覧の操作を増やす ★★

- Delete キーで選択削除、Ctrl+A で全選択、「すべて削除」ボタン。
- 右クリックメニュー: 「エクスプローラーで表示」「パスをコピー」「この画像から上を削除／下を削除」。
- 重複追加のときに「n 枚はすでに一覧にあります」と状態欄に出す（現在は黙ってスキップ）。
- 触る場所: `MainWindow.xaml`（`KeyboardAccelerator`、`MenuFlyout`）、`MainWindow.xaml.cs`。

### 1-4. 用紙サイズの追加とカスタム ★★

- 現状: A4 / A3 / Letter のみ。日本の文書で多い B5 / B4、写真向けの L判・2L判・はがきがない。
- 内容: `PAGE_SIZES_MM` に B5(182×257) / B4(257×364) / A5 / はがき(100×148) / L判(89×127) /
  2L判(127×178) / Legal を追加。さらに「カスタム（幅×高さ mm）」を UI とワーカープロトコルに追加。
- 触る場所: `image_processor.py`（`PAGE_SIZES_MM`、`validate`）、`conversion_worker.py`
  （`pageSize` に `[w, h]` も許可）、`WorkerProtocol.cs`、`MainWindow.xaml`（ComboBox + NumberBox×2）、
  `cli.py`（`--page B5` / `--page 100x148`）。
- 検証: `tests/test_image_processor.py` の用紙寸法テストに追加。

### 1-5. 余白まわりの選択肢 ★

- 「画像を用紙いっぱいに拡大」オプション。現在は「元の物理寸法より大きく拡大しない」
  仕様のため、小さな画像を A4 に置くと中央に小さく載る。拡大を許可する切り替えがあると
  スキャン写真のまとめに便利。実装は `page_geometry` の `min(1.0, ...)` の `1.0` を外すだけ。
- 配置を「中央」以外（上寄せ／左上）にも。
- 触る場所: `image_processor.py`（`ConversionOptions.fit_to_page`、`page_geometry`）、UI、CLI。

---

## フェーズ2: PDF としての完成度（v2.5.0）

### 2-1. PDF メタデータ ★★

- タイトル・作成者・件名・キーワードを保存先の横に入力できるようにする。
  未入力なら今までどおり `/Producer` だけ。
- 触る場所: `image_processor.py`（`writer.add_metadata`）、ワーカー・UI・CLI に `metadata` を追加。

### 2-2. しおり（アウトライン）とページラベル ★★

- 1画像＝1しおり（ファイル名）を付けるオプション。複数フレーム画像は「名前 (2/5)」。
- PDF ビューアのサイドバーで目的のページへ飛べる。
- 触る場所: `image_processor.py` の `writer.append` 後に `writer.add_outline_item`。

### 2-3. 既存 PDF への追記・結合 ★★

- 一覧に `.pdf` も受け付け、そのページをそのまま差し込む（`PdfWriter.append` で可能）。
  「スキャン PDF の途中に写真を1枚足す」用途に効く。
- 画像とは扱いが違う（フレーム数＝ページ数、DPI 情報なし）ので `ImageEntry` に種別を持たせる。
- 触る場所: `MainViewModel.cs`（拡張子）、`image_processor.py`（`_convert_file` の分岐）、
  `inspect` の応答（ページ数・用紙寸法）。

### 2-4. 軽量化モードの調整 ★

- 現状は 150dpi / JPEG 品質 85 固定。「DPI」「品質」のスライダーを「詳細設定」展開に置く。
  エンジン側は `compact_dpi` / `jpeg_quality` がすでにパラメータ化されており、UI とプロトコルを
  通すだけで済む。
- 変換前に「推定サイズ」を出すのは画像ごとのデコードが要るのでやらない。代わりに完了後の
  状態欄に「n ページ / 12.3 MB（元画像 45.6 MB）」を出す。

### 2-5. PDF/A-1b 出力（任意） ★

- 長期保存向けの要求があるときだけ。sRGB の OutputIntent と XMP メタデータを足す必要があり、
  `pypdf` だけでは厳密な準拠が難しいので、要望が出てから着手する。

---

## フェーズ3: 安心して使える・配れる（v2.5.x〜）

### 3-1. コード署名（Authenticode） ★★★（費用が要る）

- SmartScreen 警告は一般ユーザー向け配布の最大の障壁。`RELEASING.md` でも未対応と明記。
- 選択肢: (a) OV/EV 証明書の購入（年数万円）、(b) Azure Trusted Signing（月額、個人は本人確認が要る）、
  (c) SignPath Foundation（OSS 向け無償、審査あり）。
- 署名は `build_winui.ps1` のインストーラー生成後に `signtool` を1行足すだけ。CI では鍵を
  Secret に置くか、Trusted Signing の GitHub Action を使う。
- 自動更新で取得したファイルにも署名が付くため、「Mark of the Web なしでサイレント実行」の
  残リスク（README「アップデート」節）も同時に下がる。

### 3-2. 変換ワーカーの古いフォルダーを掃除 ★

- `%LOCALAPPDATA%\ImageToPDF\worker` に古いバージョンの展開物が残り続ける（README 既知）。
  起動時に現在のバージョン以外のフォルダーを削除する。`UpdateDownloader.CleanUpCompletedDownloads`
  と同じタイミングで良い。
- 触る場所: `Services/EmbeddedWorker.cs`。

### 3-3. 大量画像でのメモリ上限 ★

- `PdfWriter` が全ページのオブジェクトを保持するため、数百枚の大きな PNG で膨らむ（README 既知）。
- 対策: N 枚ごとに中間 PDF をディスクへ書き出し、最後に結合する。`writer.append` の対象を
  中間ファイルにするだけで、画像ごとの処理は変わらない。しきい値は 100 枚または累計 500MB。
- 検証: `tests/test_conversion_worker.py` に「中間ファイルが作られる」「結合後のページ数が一致」を追加。

### 3-4. 失敗したサムネイルの再試行 ★

- グリッドで一度失敗したタイルはアイコンのまま二度と取りに行かない。ネットワークドライブの
  一時的なエラーで困るので、タイルの右クリックに「再読み込み」を置く。

---

## フェーズ4: 使い勝手の底上げ（随時）

### 4-1. 多言語（英語 UI） ★★

- 文言はすべて XAML と C# に直書き。`.resw` に移して `x:Uid` で参照する作業が主。
  Python ワーカーのエラー文言（日本語）も `conversion_worker.py` でキー化して UI 側で訳す。
- 先に 4-2 の整理を済ませてから着手すると二度手間がない。

### 4-2. 古いコメントの整理 ★

- `MainWindow.xaml.cs` に「Tkinter版と同じ」が多数残る（Tkinter 版は v2.2.0.0 で削除済み）。
  `image_processor.make_thumbnail` の docstring「only the UI thread creates Tk objects」も同様。
- README「制限・運用」の 1 行目「更新は現在の EXE を置き換えません」は v2.3.1.0 以降の
  上書きインストールと矛盾しているので削除。
- `IMPROVEMENTS.md` と `CHANGELOG.md` の役割が重なっている。`IMPROVEMENTS.md` は
  「設計メモ」に絞るか、`CHANGELOG.md` に統合する。

### 4-3. 右クリック／「送る」からの起動 ★

- エクスプローラーで画像を選んで右クリック →「PDF にまとめる」で起動し、一覧に入った状態にする。
  インストーラー（`ImageToPDF.iss`）で `HKCU\Software\Classes\*\shell` にコマンドを登録し、
  `App.xaml.cs` でコマンドライン引数を `AddPaths` に渡すだけ。アンインストール時に削除する。

### 4-4. ドラッグ＆ドロップ時のサブフォルダー ★

- フォルダーをドロップしたとき「サブフォルダーも含める」チェック。`Directory.EnumerateFiles`
  に `SearchOption.AllDirectories` を渡し、並び順は「フォルダーパス → ファイル名」。
  無限に深い階層や数万ファイルの保護に上限（例: 5,000 枚）を置く。

---

## 進め方の提案

1. **v2.4.0** = 1-1 + 1-2 + 1-3。UI だけで完結し、Python 側のテストに影響しない。
2. **v2.4.1** = 1-4 + 1-5。エンジン・CLI・UI をまたぐので、`tests/` の用紙寸法テストを先に書く。
3. **v2.5.0** = 2-1 + 2-2 + 2-3。PDF 機能のまとまり。
4. 3-1（コード署名）は費用判断が要るので、並行して検討。他の項目と独立。
5. 4-2 はいつでも良いが、4-1（多言語）に入る前には済ませる。

各リリースは今回と同じ手順（`app_config.py` 等 5 箇所のバージョン更新 → `CHANGELOG.md` に
`## v<バージョン> — タイトル` → タグ push → `release` environment で承認）で出せます。
