# apcget 設計書

## 1. 概要

### 1.1 目的

apcget は、APC PowerChute Serial Shutdown for Business の Web UI から UPS ステータス情報をスクレイピングし、コマンドラインでの確認・JSON 出力・MQTT 送信・Zabbix 送信を行う Python スクリプトである。

### 1.2 背景

APC PowerChute Serial Shutdown for Business は SNMP インターフェースを提供しないため、標準的な監視プロトコルでの UPS 情報取得が困難である。本ツールは Web UI の HTML をパースすることでこの制約を回避し、Home Assistant や Zabbix などの監視システムとの連携を実現する。

### 1.3 対象環境

| 項目 | 値 |
|---|---|
| 対象ソフトウェア | APC PowerChute Serial Shutdown for Business v1.4.0 |
| Web UI ポート | TCP 6547 (HTTPS) |
| 対応言語 | Python 3.6+ |
| 外部依存 | 標準ライブラリのみ（MQTT/Zabbix 送信時は別途記載） |
| ライセンス | MIT License |

---

## 2. アーキテクチャ

### 2.1 処理フロー

```
┌─────────────┐
│  引数解析     │
│  認証情報解決  │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌──────────────────┐
│   ログイン    │────▶│ 既存セッション検出  │
│              │◀────│ → ログオフ → 再取得 │
└──────┬──────┘     └──────────────────┘
       │
       ▼
┌─────────────┐
│ 言語検出      │  ← <html lang="..."> を確認
│ 英語切替      │  ← 英語以外なら /setLocale で切替
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ ステータス取得 │  ← /status ページの HTML パース
│ 値抽出        │  ← HTML 要素 ID による値抽出
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  出力処理     │  ← 標準出力 / JSON / MQTT / Zabbix
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 言語復元      │  ← 元のロケールに戻す
│ ログオフ      │
└─────────────┘
```

### 2.2 出力モード

| モード | トリガー | 出力先 | 説明 |
|---|---|---|---|
| 通常モード | オプション未指定 or `--load` 等 | stdout | 指定項目をスペース区切りで出力 |
| JSON モード | `--json` | stdout | 全項目を JSON 形式で出力 |
| MQTT 送信 | `--mqtt-send` | MQTT ブローカー | 全項目を JSON ペイロードで Publish |
| Zabbix 送信 | `--zabbix-send` | Zabbix サーバー | 全項目をトラッパーアイテムとして送信 |

JSON / MQTT / Zabbix は同時指定可能（独立した `if` 文で処理）。

---

## 3. モジュール構成

### 3.1 ファイル構成

```
apcget.py          ← 単一ファイル構成（外部モジュール依存なし）
```

### 3.2 定数

| 定数名 | 型 | 説明 |
|---|---|---|
| `ITEMS` | dict | 取得項目名 → HTML 要素 ID のマッピング |
| `ZABBIX_KEYS` | dict | 取得項目名 → Zabbix トラッパーアイテムキーのマッピング |
| `DEFAULT_CONFIG_PATH` | str | 設定ファイルのデフォルトパス (`~/.apcget.conf`) |
| `HTTP_TIMEOUT` | int | HTTP リクエストタイムアウト（30 秒） |

### 3.3 取得項目一覧

| 項目名 | HTML 要素 ID | Zabbix キー | 単位 |
|---|---|---|---|
| `status` | `value_DeviceStatus` | `apc.status` | - (文字列) |
| `load` | `value_RealPowerPct` | `apc.load` | % |
| `runtime` | `value_RuntimeRemaining` | `apc.runtime` | 分 |
| `voltage` | `value_InputVoltage` | `apc.voltage` | VAC |
| `battery` | `value_BatteryCharge` | `apc.battery` | % |
| `batteryvoltage` | `value_VoltageDC` | `apc.batteryvoltage` | VDC |

---

## 4. 関数設計

### 4.1 認証情報管理

#### `load_config(config_path) → dict`

- 設定ファイル（INI 形式）から `[powerchute]` セクションの `ip`, `username`, `password` を読み込む
- ファイルが存在しない場合は空辞書を返す

#### `resolve_credential(args_value, env_name, config_value, label) → str`

- 認証情報を以下の優先順で解決する:
  1. コマンドライン引数
  2. 環境変数（`APCGET_IP`, `APCGET_USERNAME`, `APCGET_PASSWORD`）
  3. 設定ファイル
- いずれにも値がない場合はエラー終了

### 4.2 HTTP 通信

#### `create_openers() → (opener, opener_noredir)`

- SSL 証明書検証を無効化した 2 種類の urllib opener を返す
  - `opener`: リダイレクト追従あり（通常のページ取得用）
  - `opener_noredir`: リダイレクト追従なし（ログイン時のリダイレクト先判定用）
- Cookie は `CookieJar` で自動管理（セッション維持）

**設計判断**: PowerChute は自己署名証明書を使用するため、SSL 検証を無効化している。

### 4.3 ページ判定（言語非依存）

#### `_is_status_page(html) → bool`

- HTML 内に `value_DeviceStatus` が含まれるかで判定
- HTML 要素 ID は言語設定に依存しないため、どの表示言語でも正しく動作する

#### `_is_already_logged_on(html) → bool`

- `alreadyLoggedOn` (HTML 要素 ID) の存在と、メッセージテキスト（英語 or 日本語）の組み合わせで判定

### 4.4 言語制御

#### `_detect_locale(html) → str | None`

- `<html lang="...">` 属性からロケールコードを抽出（例: `"en"`, `"ja"`）

#### `_set_locale(opener, base_url, locale) → str`

- PowerChute の `/setLocale` エンドポイントに POST リクエストを送信
- パラメータ: `newLocale`（ロケールコード）, `targetURL`（リダイレクト先）

#### `ensure_english(opener, base_url) → str | None`

- ステータスページの言語を検出し、英語以外なら英語に切り替える
- 戻り値: 元のロケールコード（切替が行われた場合）、`None`（元から英語の場合）

#### `restore_locale(opener, base_url, original_locale)`

- `ensure_english` で記録した元のロケールに復元する
- 例外発生時は黙殺（ログオフ前の最善努力処理）

**設計判断**: ステータス値（特に `status` 項目）は表示言語に依存する（例: "On Line" vs "オンライン"）。出力値を統一するため、常に英語で取得し、処理完了後に元の言語に復元する。

### 4.5 認証

#### `login(opener, opener_noredir, base_url, username, password)`

**処理フロー:**

```
1. /status にアクセス → ログインページにリダイレクトされる
2. 「既にログオン中」の場合 → /logoff してから再試行
3. 既にステータスページが表示される場合 → ログイン不要（return）
4. formtoken / formtokenid をHTMLから抽出（CSRF対策トークン）
5. login ボタンの value 属性を動的に取得（言語対応）
6. /j_security_check に POST（Java EE form-based auth）
7. リダイレクト先で成否を判定:
   - /status へのリダイレクト → 成功
   - /logon へのリダイレクト → 認証失敗
```

**設計判断**:
- `opener_noredir`（リダイレクト非追従）を使用してログイン結果を `Location` ヘッダーから判定する
- ログインボタンの `value` 属性をページから動的に取得することで、表示言語に依存しないログイン処理を実現

#### `logoff(opener, base_url)`

- `/logoff` にアクセスしてセッションを終了
- 例外は黙殺（クリーンアップ処理のため）

### 4.6 データ取得

#### `get_status_page(opener, base_url) → str`

- `/status` ページの HTML を取得
- ログインページにリダイレクトされた場合はエラー終了

#### `extract_value(html, element_id) → str | None`

- 正規表現 `id="{element_id}"[^>]*>([^<]+)<` で HTML 要素の値を抽出
- 対象: `<span id="value_DeviceStatus" ...>On Line</span>` 等

### 4.7 外部送信

#### `zabbix_send(zabbix_server, zabbix_host, all_values, zabbix_port=10051)`

- `zabbix_sender` コマンドを `-i -`（標準入力モード）で実行
- 全項目を一括送信（1 回の `zabbix_sender` 呼び出し）
- ホスト名はバリデーション済み（`_sanitize_zabbix_host`）
- 値は改行除去済み（`_sanitize_zabbix_value`）

**前提**: `zabbix_sender` コマンドがインストールされていること

#### `mqtt_publish(mqtt_broker, mqtt_topic, all_values, mqtt_port, mqtt_user, mqtt_password)`

- 送信ツールの選択:
  1. `mosquitto_pub` が PATH に存在する場合 → `mosquitto_pub` を使用
  2. 存在しない場合 → `paho-mqtt` Python パッケージにフォールバック
- ペイロードは全項目を含む JSON 文字列

#### `_mqtt_publish_paho(...)`

- `paho.mqtt.publish.single()` による送信
- import は遅延実行（`paho-mqtt` 未インストール環境での起動エラーを防止）

**前提**: `mosquitto_pub` または `paho-mqtt` のいずれかがインストールされていること

---

## 5. 認証情報管理

### 5.1 指定方法と優先順位

```
優先度 高
  │  1. コマンドライン引数    apcget.py <IP> <USER> <PASS>
  │  2. 環境変数              APCGET_IP, APCGET_USERNAME, APCGET_PASSWORD
  ▼  3. 設定ファイル          ~/.apcget.conf（--config で変更可）
優先度 低
```

### 5.2 設定ファイル書式

```ini
[powerchute]
ip = 192.168.1.100
username = your_username
password = your_password
```

---

## 6. コマンドライン引数

### 6.1 位置引数

| 引数 | 必須 | 説明 |
|---|---|---|
| `ip` | 条件付き | PowerChute の IP アドレス |
| `username` | 条件付き | ログインユーザ名 |
| `password` | 条件付き | ログインパスワード |

※ 設定ファイルまたは環境変数で指定されている場合は省略可

### 6.2 取得項目オプション

| オプション | 説明 |
|---|---|
| `--status` | デバイスステータス |
| `--load` | UPS 負荷 (%) |
| `--runtime` | ランタイム残り時間 (分) |
| `--voltage` | 入力電圧 (VAC) |
| `--battery` | バッテリー充電 (%) |
| `--batteryvoltage` | バッテリー電圧 (VDC) |

未指定時は `--load` がデフォルト。

### 6.3 出力オプション

| オプション | 引数 | デフォルト | 説明 |
|---|---|---|---|
| `--json` | なし | - | 全項目を JSON 形式で標準出力 |
| `--mqtt-send` | MQTT_BROKER | - | MQTT ブローカーアドレス |
| `--mqtt-topic` | TOPIC | `apcget/ups` | MQTT トピック名 |
| `--mqtt-port` | PORT | `1883` | MQTT ブローカーポート |
| `--mqtt-user` | USERNAME | - | MQTT 認証ユーザ名 |
| `--mqtt-password` | PASSWORD | - | MQTT 認証パスワード |
| `--zabbix-send` | ZABBIX_SERVER | - | Zabbix サーバーアドレス |
| `--zabbix-host` | HOSTNAME | IP アドレス | Zabbix 上のホスト名 |
| `--zabbix-port` | PORT | `10051` | Zabbix サーバーポート |

### 6.4 その他

| オプション | 説明 |
|---|---|
| `--config` | 設定ファイルのパス（デフォルト: `~/.apcget.conf`） |
| `--help` | ヘルプ表示 |

---

## 7. エラー処理

### 7.1 エラー種別

| 状況 | 処理 | 終了コード |
|---|---|---|
| 認証情報未指定 | stderr にエラー出力 | 1 |
| ログイン失敗 | stderr にエラー出力 | 1 |
| セッション無効 | stderr にエラー出力 | 1 |
| 値取得失敗（通常モード） | stderr にエラー出力 | 1 |
| 値取得失敗（全項目モード） | stderr に Warning、スキップ | - |
| 全項目が取得不可 | stderr にエラー出力 | 1 |
| zabbix_sender 失敗 | stderr にエラー出力 | 1 |
| MQTT 送信失敗 | stderr にエラー出力 | 1 |
| MQTT ツール未インストール | stderr にエラー出力 | 1 |

### 7.2 クリーンアップ

`finally` ブロックで以下を保証:
1. 言語設定の復元（`restore_locale`）
2. セッションのログオフ（`logoff`）

いずれも例外を黙殺し、エラー時でも確実に実行される。

---

## 8. セキュリティ考慮事項

### 8.1 SSL 証明書検証

- PowerChute は自己署名証明書を使用するため、SSL 証明書検証を無効化している
- これは LAN 内での使用を前提とした設計判断

### 8.2 入力値サニタイズ

- Zabbix ホスト名: `^[\w.\-]+$` のパターンで検証（コマンドインジェクション防止）
- Zabbix 送信値: 改行文字を除去
- 外部コマンド呼び出し: `subprocess.run` でリスト形式の引数を使用（シェルインジェクション防止）

### 8.3 認証情報の保護

- 設定ファイルによる認証情報管理を推奨（コマンドライン引数はプロセス一覧から可視）
- 環境変数による指定もサポート

---

## 9. 多言語対応

### 9.1 設計方針

PowerChute Web UI は複数の表示言語（英語、日本語等）をサポートしている。UPS ステータス値は表示言語に依存するため（例: "On Line" vs "オンライン"）、データの一貫性を確保するために以下の方式を採用した。

### 9.2 処理方式

```
ログイン
  │
  ▼
現在の表示言語を検出 ← <html lang="..."> 属性
  │
  ├── 英語の場合 → そのまま続行
  │
  └── 英語以外の場合
        │
        ▼
      POST /setLocale (newLocale=en) → 英語に切替
        │
        ▼
      データ取得（英語表記で統一）
        │
        ▼
      POST /setLocale (newLocale=元の値) → 元の言語に復元
        │
        ▼
      ログオフ
```

### 9.3 言語非依存の判定

以下の判定処理は HTML 要素 ID を使用しており、表示言語に依存しない:

| 判定内容 | 判定方法 | 根拠 |
|---|---|---|
| ステータスページ判定 | `value_DeviceStatus` の存在 | HTML 要素 ID は言語不変 |
| 既存セッション検出 | `alreadyLoggedOn` の存在 | HTML 要素 ID は言語不変 |
| 値抽出 | `id="value_..."` の正規表現 | HTML 要素 ID は言語不変 |
| ログインボタン | `name="login"` の value 属性を動的取得 | 表示値は言語依存だが動的取得で対応 |

---

## 10. 外部連携

### 10.1 MQTT 送信

```
apcget.py ──▶ mosquitto_pub (優先) ──▶ MQTT Broker ──▶ Home Assistant
                                                       Subscriber
         └──▶ paho-mqtt (フォールバック) ─┘
```

- トピック: 任意指定可（デフォルト `apcget/ups`）
- ペイロード: 全項目を含む JSON
- 認証: ユーザ名/パスワード（オプション）

### 10.2 Zabbix 送信

```
apcget.py ──▶ zabbix_sender -i - ──▶ Zabbix Server
```

- ホスト名: 任意指定可（デフォルトは PowerChute IP アドレス）
- アイテムタイプ: Zabbix トラッパー
- 送信方式: 標準入力による一括送信

### 10.3 Home Assistant command_line センサー

MQTT を使用しない場合、`--json` オプションと `command_line` センサーの組み合わせでも連携可能。

---

## 11. 運用構成例

### 11.1 cron による定期実行

```cron
* * * * * /usr/bin/python3 /path/to/apcget.py \
  --config /path/to/.apcget.conf \
  --zabbix-send 127.0.0.1 --zabbix-host ups-living \
  --mqtt-send 192.168.1.9 --mqtt-topic apcget/ups-living \
  --mqtt-user mqtt --mqtt-password mqttpass \
  >/dev/null 2>&1
```

- 実行間隔: 1 分ごと
- Zabbix と MQTT を同時送信可能（1 回の実行で両方処理）
- 複数 UPS の場合は設定ファイルとトピック/ホスト名を分けて個別に cron 登録

---

## 12. 既知の制約・リスク

| 項目 | 内容 |
|---|---|
| シングルセッション制限 | PowerChute は同時に 1 セッションのみ許可。apcget 実行中は Web UI にアクセスできない |
| HTML 構造依存 | PowerChute のバージョンアップで HTML 要素 ID が変更された場合、値抽出が失敗する可能性がある |
| 言語切替の副作用 | 他ユーザが同時に Web UI を使用している場合、表示言語が一時的に変更される |
| セッションタイムアウト | PowerChute のセッションタイムアウト（900 秒）内に処理が完了する前提 |
| HTTPS 検証無効化 | 自己署名証明書への対応として SSL 検証を無効化しており、MITM 攻撃のリスクがある（LAN 内使用前提） |
