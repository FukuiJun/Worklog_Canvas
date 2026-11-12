# Worklog Canvas

タスク一覧と、1日の作業時間を記録する作業バーを管理し、タスク別の作業時間と進捗を可視化するWindows用デスクトップアプリ。仕様は [SPEC.md](SPEC.md) を参照。

> 開発中（M1: データ処理の骨格まで実装済み）。画面・exe化・予定表ファイルの取り込み手順は後続のマイルストーンで追記する。

## 開発環境

- Python 3.12

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## テスト

```bat
python -m pytest
```

データ処理（`worklog_canvas/core/`）は画面に依存せず、PySide6 なしでテストできる。

## ソースの構成

| パス | 内容 |
|---|---|
| `worklog_canvas/core/models.py` | タスク・作業バー・週次メモ・カテゴリのデータ定義と入力検証 |
| `worklog_canvas/core/timeutil.py` | 時刻の変換、15分吸着 |
| `worklog_canvas/core/overlap.py` | 作業バーの重なり判定（作業バー同士は重ねられない） |
| `worklog_canvas/core/colors.py` | 作業バーの表示色 |
| `worklog_canvas/core/aggregate.py` | 集計（メイン時間・サブ時間、稼働時間、カテゴリ別） |
| `worklog_canvas/core/storage.py` | JSONの読み書き（一時ファイル経由の安全な保存） |
| `worklog_canvas/core/repository.py` | データフォルダと利用者ごとのデータの操作 |
| `scripts/make_sample_data.py` | サンプルデータの生成 |
| `sample_data/` | サンプルデータ（3名分） |

## データフォルダの構成

```
<データフォルダ>/
├─ categories.json          全員共通のカテゴリ
└─ users/
   └─ <Windowsのユーザー名>/
      ├─ profile.json        表示名
      ├─ tasks.json          タスク
      ├─ worklogs.json       作業バー
      └─ weekly_notes.json   週次メモ
```

JSONは UTF-8（BOMなし）・LF。各ファイルの項目名は SPEC.md 5.2 の項目名をそのまま使い、
`{"version": 1, "next_id": 4, "tasks": [...]}` のように形式の版と次の採番を持つ。

作業バーはメイン（タスクまたは単発作業）1つと、サブタスク（タスクまたは単発作業）を3つまで持てる。
作業バー同士は重ねられず、並行作業はサブタスクで記録する。

```json
{"id": "W-000001", "日付": "2026-11-10", "開始時刻": "10:00", "終了時刻": "11:30",
 "種別": "タスク", "タスクid": "T-0001", "タイトル": "",
 "サブタスク": [{"種別": "タスク", "タスクid": "T-0002", "タイトル": ""},
                {"種別": "単発作業", "タスクid": null, "タイトル": "打合せ"}],
 "メモ": "", "取込元": "手動"}
```

集計では、メインの時間（タスク別時間・稼働時間・カテゴリ別）と、サブタスクの時間（サブ時間）を分けて数える。

## サンプルデータ

`sample_data/` は次のコマンドで作り直せる。

```bat
python scripts\make_sample_data.py
```

3名（福井・佐藤・鈴木）、各自タスク8件、2026-11-02〜11-13 の作業バー（サブタスクと単発作業を含む）。
