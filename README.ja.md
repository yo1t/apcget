# apcget

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub](https://img.shields.io/github/v/release/yo1t/apcget?label=GitHub)](https://github.com/yo1t/apcget)

APC PowerChute Serial Shutdown for Business の Web インターフェースから UPS ステータスを取得する Python スクリプトです。

https://github.com/yo1t/apcget

[English README](README.md)

外部パッケージ不要 — Python 標準ライブラリのみで動作します。

## 動作要件

- Python 3.6+
- APC PowerChute Serial Shutdown for Business（ポート 6547）

### オプション

- `zabbix_sender` — `--zabbix-send` オプション使用時のみ必要
- `mosquitto_pub` — `--mqtt-send` オプション使用時のみ必要

### オプション依存パッケージのインストール

```bash
# zabbix_sender
sudo dnf install zabbix-sender      # RHEL / Amazon Linux
sudo apt install zabbix-sender       # Ubuntu / Debian
brew install zabbix                  # macOS (Homebrew)

# mosquitto_pub
sudo dnf install mosquitto           # RHEL / Amazon Linux
sudo apt install mosquitto-clients   # Ubuntu / Debian
brew install mosquitto               # macOS (Homebrew)
```

## 使い方

```bash
python3 apcget.py [IPアドレス] [ユーザ名] [パスワード] [オプション]
```

認証情報は環境変数や設定ファイルでも指定できます（後述）。

### 基本（UPS負荷のみ取得）

```bash
python3 apcget.py 192.168.1.100 administrator password
# 出力: 19.0
```

### 取得項目の指定

```bash
# バッテリー充電率
python3 apcget.py 192.168.1.100 administrator password --battery

# 複数項目（スペース区切りで出力）
python3 apcget.py 192.168.1.100 administrator password --load --runtime --voltage
# 出力: 19.0 29 102.0
```

### 取得可能な項目

| オプション | 説明 | 出力例 |
|---|---|---|
| `--status` | デバイスステータス | オンライン |
| `--load` | UPS負荷 (%) | 19.0 |
| `--runtime` | ランタイム残り時間 (分) | 29 |
| `--voltage` | 入力電圧 (VAC) | 102.0 |
| `--battery` | バッテリー充電 (%) | 100.0 |
| `--batteryvoltage` | バッテリー電圧 (VDC) | 13.7 |

オプション未指定の場合は `--load` がデフォルトです。単位（%、VAC 等）は出力に含まれません。

### JSON 出力

`--json` オプションで全項目を JSON 形式で出力します。Home Assistant やスクリプトとの連携に便利です。

```bash
python3 apcget.py 192.168.1.100 administrator password --json
# 出力: {"status": "オンライン", "load": "19.0", "runtime": "29", "voltage": "102.0", "battery": "100.0", "batteryvoltage": "13.7"}
```

## MQTT 連携

`--mqtt-send` オプションで全項目を JSON 形式で MQTT ブローカーに `mosquitto_pub` 経由で送信します。

```bash
python3 apcget.py 192.168.1.100 administrator password \
  --mqtt-send 192.168.1.200 \
  --mqtt-topic apcget/ups-living
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--mqtt-send` | MQTT ブローカーのアドレス | (なし) |
| `--mqtt-topic` | MQTT トピック | apcget/ups |
| `--mqtt-port` | MQTT ブローカーのポート | 1883 |
| `--mqtt-user` | MQTT 認証ユーザ名 | (なし) |
| `--mqtt-password` | MQTT 認証パスワード | (なし) |

### Home Assistant の設定

`configuration.yaml` に MQTT センサーを追加:

```yaml
mqtt:
  sensor:
    - name: "UPS負荷"
      state_topic: "apcget/ups-living"
      value_template: "{{ value_json.load }}"
      unit_of_measurement: "%"
    - name: "UPSバッテリー"
      state_topic: "apcget/ups-living"
      value_template: "{{ value_json.battery }}"
      unit_of_measurement: "%"
    - name: "UPSランタイム"
      state_topic: "apcget/ups-living"
      value_template: "{{ value_json.runtime }}"
      unit_of_measurement: "min"
    - name: "UPSステータス"
      state_topic: "apcget/ups-living"
      value_template: "{{ value_json.status }}"
    - name: "UPS入力電圧"
      state_topic: "apcget/ups-living"
      value_template: "{{ value_json.voltage }}"
      unit_of_measurement: "VAC"
    - name: "UPSバッテリー電圧"
      state_topic: "apcget/ups-living"
      value_template: "{{ value_json.batteryvoltage }}"
      unit_of_measurement: "VDC"
```

## Zabbix 連携

`--zabbix-send` オプションで全 6 項目を `zabbix_sender` で一括送信します。

```bash
python3 apcget.py 192.168.1.100 administrator password \
  --zabbix-send 10.0.0.1 \
  --zabbix-host MyUPS
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--zabbix-send` | Zabbix サーバーのアドレス | (なし) |
| `--zabbix-host` | Zabbix 上のホスト名 | IP アドレス |
| `--zabbix-port` | Zabbix サーバーのポート | 10051 |

### Zabbix の設定

対象ホストに以下の **Zabbix トラッパー** アイテムを作成してください:

| キー | タイプ | 説明 |
|---|---|---|
| `apc.status` | 文字列 | デバイスステータス |
| `apc.load` | 数値（浮動小数） | UPS負荷 |
| `apc.runtime` | 数値（整数） | ランタイム残り時間 |
| `apc.voltage` | 数値（浮動小数） | 入力電圧 |
| `apc.battery` | 数値（浮動小数） | バッテリー充電 |
| `apc.batteryvoltage` | 数値（浮動小数） | バッテリー電圧 |

### cron の設定例

```cron
* * * * * /usr/bin/python3 /path/to/apcget.py --config /path/to/.apcget.conf --zabbix-send 127.0.0.1 --zabbix-host ups-host >/dev/null 2>&1
```

## 認証情報の管理

認証情報は以下の優先順で解決されます。パスワードをコマンドラインに含めずに実行できます:

**優先順位**: コマンドライン引数 > 環境変数 > 設定ファイル

### 設定ファイル (`~/.apcget.conf`)

```ini
[powerchute]
ip = 192.168.1.100
username = administrator
password = your_password
```

```bash
# 設定ファイルのみで実行（引数不要）
python3 apcget.py

# 設定ファイルのパスを指定
python3 apcget.py --config /etc/apcget.conf
```

ファイルのパーミッションをオーナーのみ読み取り可能に設定してください:

```bash
chmod 600 ~/.apcget.conf
```

### 環境変数

| 変数名 | 説明 |
|---|---|
| `APCGET_IP` | PowerChute の IP アドレス |
| `APCGET_USERNAME` | ログインユーザ名 |
| `APCGET_PASSWORD` | ログインパスワード |

```bash
export APCGET_IP=192.168.1.100
export APCGET_USERNAME=administrator
export APCGET_PASSWORD='your_password'
python3 apcget.py
```

### セキュリティに関する注意

- コマンドライン引数でパスワードを渡すと `ps` やシェル履歴に表示されます。設定ファイルまたは環境変数を使用してください
- PowerChute が自己署名証明書を使用しているため、SSL 証明書の検証は無効にしています
- 設定ファイルには `chmod 600` を設定し、他のユーザーからの読み取りを防止してください

## 免責事項

本ソフトウェアは「現状のまま」提供され、いかなる保証もありません。使用は自己責任でお願いします。本ソフトウェアの使用により生じた損害、データ損失、その他の問題について、作者は一切の責任を負いません。本ツールは Schneider Electric および APC とは無関係であり、公式に認定されたものではありません。

## 動作確認環境

- APC PowerChute Serial Shutdown for Business v1.4.0.601
- UPS: APC RS 550S
- Python 3.9 / 3.10
- Zabbix 7.4（トラッパー連携）
- Amazon Linux 2023 / macOS
