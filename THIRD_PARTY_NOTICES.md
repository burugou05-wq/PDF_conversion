# 第三者ライセンス表記 (Third-Party Notices)

このプロジェクト自身は [LICENSE](LICENSE)（MIT License）の下で配布されます。
配布物には以下の第三者コンポーネントが含まれます。各コンポーネントの完全な
ライセンス文書はリンク先のリポジトリで確認してください。

## ソースコード実行時に直接依存するライブラリ（requirements.txt）

| ライブラリ | バージョン | ライセンス | 備考 |
| --- | --- | --- | --- |
| [Pillow](https://github.com/python-pillow/Pillow) | 11.1.0 | MIT-CMU（HPND系の許諾ライセンス） | Copyright © 1997-2011 Secret Labs AB, © 1995-2011 Fredrik Lundh, © 2010 Jeffrey A. Clark and contributors |
| [img2pdf](https://github.com/josch/img2pdf) | 0.6.0 | LGPL-3.0-or-later | Copyright © 2013-2024 Johannes Schauer Marin Rodrigues |
| [pypdf](https://github.com/py-pdf/pypdf) | 6.20.1 | BSD-3-Clause | Copyright (c) 2006-2008 Mathieu Fenniak, (c) 2022-2025 pypdf contributors |

### img2pdf（LGPL-3.0-or-later）に関する配布上の注意

EXEなどの結合配布物にLGPLライブラリを含める場合は、次の対応が必要です。

1. 配布物にLGPL-3.0のライセンス文書と（LGPLが参照する）GPL-3.0の文書を同梱、
   または読者宛てに提供すること。
2. img2pdfの対応するソースコードを入手可能にすること（本プロジェクトでは
   PyPIで配布されている `img2pdf==0.6.0` のsdistが該当します）。
3. LGPL第4条（Combined Works）に従い、利用者がLGPL部分を改変して再リンクできる
   形（オブジェクトコードやソースの入手手段の提供）を担保すること。
   必要に応じて法的確認を行ってください。

## 任意インストールの追加ライブラリ（requirements-optional.txt）

EXEビルドではこれらも配布物に含まれます。

| ライブラリ | バージョン | ライセンス | 備考 |
| --- | --- | --- | --- |
| [pillow-heif](https://github.com/bigcat88/pillow_heif) | 1.8.1 | ソース: BSD-3-Clause / **バイナリwheel: GPLv2** | wheelにlibheif v1.23.6・libde265 v1.1.3（LGPLv3）、x265 4.3（GPLv2）、MinGW-w64ランタイム（libgcc/libstdc++ は GPL-3.0-with-GCC-exception、libwinpthread は MIT/BSD）が同梱される。詳細はwheel内の `LICENSES_bundled.txt` 参照 |
| [pillow-avif-plugin](https://github.com/fdintino/pillow-avif-plugin) | 1.5.0 | MIT License | libaom（BSD-2 + AOM特許条項）を含む |

### 重要: pillow-heif のバイナリwheelはGPLv2です

pillow-heifのwheelは `libx265`（GPLv2）を含むため、**wheel本体は「GPLv2」**
として配布されています（同梱の `LICENSES_bundled.txt` 参照）。したがって、
pillow-heif入りでビルドしたEXEを配布する場合、配布物全体をGPLv2の条件の下に
置くか、pillow-heifを同梱しないビルドに変更する必要があります。

MIT Licenseのまま配布したい場合は、`requirements-optional.txt` から
`pillow-heif` を除外してビルドしてください（HEIF/HEIC読み込みは無効化されますが、
他の機能には影響しません）。

## ビルドツール（配布物には含まれません）

| ツール | ライセンス | 備考 |
| --- | --- | --- |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | GPL-2.0-or-later（bootloader例外付き） | bootloader例外により、PyInstallerで作成したアプリは任意のライセンスで配布可能 |
| pytest / ruff | MIT / MIT | 開発時のみ使用 |

## WinUI 3版の依存

| コンポーネント | ライセンス |
| --- | --- |
| [Windows App SDK](https://github.com/microsoft/WindowsAppSDK) | MIT License |
| .NET 8 ランタイム（自己完結配置のため配布物に含む） | MIT License |

## アイコン・テストデータ

- `app_icon.ico` は本プロジェクトの作成物です。
