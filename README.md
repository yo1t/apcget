# apcget

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub](https://img.shields.io/github/v/release/yo1t/apcget?label=GitHub)](https://github.com/yo1t/apcget)

APC PowerChute Serial Shutdown for Business の Web インターフェースから UPS ステータスを取得するスクリプト。

https://github.com/yo1t/apcget

Python 標準ライブラリのみで動作し、外部パッケージのインストールは不要。

## 必要環境

- Python 3.6+
- APC PowerChute Serial Shutdown for Business (ポート 6547)
- Zabbix連携を使う場合: `zabbix_sender`

### zabbix_sender のインストール

```bash
# RHEL / Amazon Linux
sudo dnf install zabbix-sender

# Ubuntu / Debian
sudo apt install zabbix-sender

# macOS (Homebrew)
brew install zabbix
```

## 使い方

```bash
python3 apcget.py [IPアドレス] [ユーザ名] [パスワード] [オプション]
```

認証情報はコマンドライン引数のほか、環境変数・設定ファイルでも指定できる（後述）。

### 基本（UPS負荷のみ取得）

```bash
python3 apcget.py 192.168.1.100 administrator password
# 出力例: 19.0
```

### 項目を指定して取得

```bash
# バッテリー充電率
python3 apcget.py 192.168.1.100 administrator password --battery

# 複数項目（スペース区切りで出力）
python3 apcget.py 192.168.1.100 administrator password --load --runtime --voltage
# 出力例: 19.0 29 102.0
```

### 取得可能な項目

| オプション | 内容 | 出力例 |
|---|---|---|
| `--status` | デバイスステータス | オンライン |
| `--load` | UPS負荷 (%) | 19.0 |
| `--runtime` | ランタイム残り時間 (分) | 29 |
| `--voltage` | 入力電圧 (VAC) | 102.0 |
| `--battery` | バッテリー充電 (%) | 100.0 |
| `--batteryvoltage` | バッテリー電圧 (VDC) | 13.7 |

オプション未指定の場合は `--load` がデフォルト。出力に単位（%, VAC等）は含まれない。

## Zabbix 連携

`--zabbix-send` オプションで全6項目を `zabbix_sender` 経由で一括送信できる。

```bash
python3 apcget.py 192.168.1.100 administrator password \
  --zabbix-send 10.0.0.1 \
  --zabbix-host MyUPS
```

| オプション | 説明 | デフォルト |
|---|---|---|
| `--zabbix-send` | Zabbixサーバーのアドレス | (なし) |
| `--zabbix-host` | Zabbix上のホスト名 | IPアドレス |
| `--zabbix-port` | Zabbixサーバーのポート | 10051 |

### Zabbix側の設定

対象ホストに以下の **Zabbix トラッパー** アイテムを作成する。

| キー | データ型 | 内容 |
|---|---|---|
| `apc.status` | 文字列 | デバイスステータス |
| `apc.load` | 数値(浮動小数) | UPS負荷 |
| `apc.runtime` | 数値(整数) | ランタイム残り時間 |
| `apc.voltage` | 数値(浮動小数) | 入力電圧 |
| `apc.battery` | 数値(浮動小数) | バッテリー充電 |
| `apc.batteryvoltage` | 数値(浮動小数) | バッテリー電圧 |

### cron 設定例

```cron
* * * * * /usr/bin/python3 /path/to/apcget.py --config /path/to/.apcget.conf --zabbix-send 127.0.0.1 --zabbix-host ups-host >/dev/null 2>&1
```

## 認証情報の管理

認証情報は以下の優先順で解決される。コマンドライン引数にパスワードを書かずに運用できる。

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

# パスを指定する場合
python3 apcget.py --config /etc/apcget.conf
```

設定ファイルのパーミッションは所有者のみ読み取り可にすることを推奨:

```bash
chmod 600 ~/.apcget.conf
```

### 環境変数

| 変数名 | 内容 |
|---|---|
| `APCGET_IP` | PowerChuteのIPアドレス |
| `APCGET_USERNAME` | ログインユーザ名 |
| `APCGET_PASSWORD` | ログインパスワード |

```bash
export APCGET_IP=192.168.1.100
export APCGET_USERNAME=administrator
export APCGET_PASSWORD='your_password'
python3 apcget.py
```

### セキュリティに関する注意

- コマンドライン引数にパスワードを直接指定すると `ps` コマンドやシェル履歴から閲覧される可能性がある。設定ファイルまたは環境変数の利用を推奨
- PowerChuteは自己署名証明書を使用するため、SSL証明書の検証を無効化している
- 設定ファイルには `chmod 600` を設定し、他ユーザーから読み取れないようにする

## 動作確認済み環境

- APC PowerChute Serial Shutdown for Business v1.4.0.601
- UPS: APC RS 550S
- Python 3.9 / 3.10
- Zabbix 7.4 (トラッパー連携)
- Amazon Linux 2023 / macOS
