#!/usr/bin/env python3
# Copyright (c) 2026 Yoichi Takizawa / @yo1t
# Licensed under the MIT License. See LICENSE file for details.
# https://github.com/yo1t/apcget
"""APC PowerChute Serial Shutdown for Business - UPSステータス取得スクリプト"""

import argparse
import configparser
import http.cookiejar
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request

# 取得可能な項目: オプション名 → HTML要素ID
ITEMS = {
    "status":         "value_DeviceStatus",
    "load":           "value_RealPowerPct",
    "runtime":        "value_RuntimeRemaining",
    "voltage":        "value_InputVoltage",
    "battery":        "value_BatteryCharge",
    "batteryvoltage": "value_VoltageDC",
}

# Zabbixトラッパーアイテムキー
ZABBIX_KEYS = {
    "status":         "apc.status",
    "load":           "apc.load",
    "runtime":        "apc.runtime",
    "voltage":        "apc.voltage",
    "battery":        "apc.battery",
    "batteryvoltage": "apc.batteryvoltage",
}

# 設定ファイルのデフォルトパス
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.apcget.conf")

# HTTPリクエストのタイムアウト（秒）
HTTP_TIMEOUT = 30


def load_config(config_path):
    """設定ファイルから認証情報を読み込む"""
    if not os.path.exists(config_path):
        return {}
    config = configparser.ConfigParser()
    config.read(config_path)
    result = {}
    if config.has_section("powerchute"):
        section = config["powerchute"]
        for key in ("ip", "username", "password"):
            if key in section:
                result[key] = section[key]
    return result


def resolve_credential(args_value, env_name, config_value, label):
    """引数 → 環境変数 → 設定ファイルの優先順で認証情報を解決する"""
    if args_value:
        return args_value
    env_value = os.environ.get(env_name)
    if env_value:
        return env_value
    if config_value:
        return config_value
    print(f"Error: {label}が指定されていません。"
          f"引数、環境変数({env_name})、または設定ファイルで指定してください。", file=sys.stderr)
    sys.exit(1)


def create_openers():
    """SSL証明書検証を無効にしたopenerを作成（リダイレクト追従あり/なし）"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    cookie_jar = http.cookiejar.CookieJar()
    cookie_handler = urllib.request.HTTPCookieProcessor(cookie_jar)
    https_handler = urllib.request.HTTPSHandler(context=ctx)

    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(https_handler, cookie_handler)
    opener_noredir = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx), cookie_handler, NoRedirectHandler
    )
    return opener, opener_noredir


def login(opener, opener_noredir, base_url, username, password):
    """PowerChute Serial Shutdown for Businessにログイン（Java EE form-based auth）"""
    resp = opener.open(f"{base_url}/status", timeout=HTTP_TIMEOUT)
    html = resp.read().decode("utf-8", errors="replace")

    if "既にログオン" in html or "already logged" in html.lower():
        opener.open(f"{base_url}/logoff", timeout=HTTP_TIMEOUT)
        resp = opener.open(f"{base_url}/status", timeout=HTTP_TIMEOUT)
        html = resp.read().decode("utf-8", errors="replace")

    if "UPSステータス" in html or "UPS Status" in html:
        return

    ft_match = re.search(r'name="formtoken"[^>]*value="([^"]+)"', html)
    fti_match = re.search(r'name="formtokenid"[^>]*value="([^"]+)"', html)
    formtoken = ft_match.group(1) if ft_match else ""
    formtokenid = fti_match.group(1) if fti_match else ""

    data = urllib.parse.urlencode({
        "j_username": username,
        "j_password": password,
        "login": "ログオン",
        "formtoken": formtoken,
        "formtokenid": formtokenid,
    }).encode("utf-8")

    req = urllib.request.Request(f"{base_url}/j_security_check", data=data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        opener_noredir.open(req, timeout=HTTP_TIMEOUT)
    except urllib.error.HTTPError as e:
        location = e.headers.get("Location", "")
        e.read()
        if "/logon" in location and "/status" not in location:
            print("Error: ログインに失敗しました。ユーザ名またはパスワードを確認してください。", file=sys.stderr)
            sys.exit(1)


def get_status_page(opener, base_url):
    """statusページのHTMLを取得"""
    resp = opener.open(f"{base_url}/status", timeout=HTTP_TIMEOUT)
    html = resp.read().decode("utf-8", errors="replace")

    if "/logon" in resp.geturl() and "UPSステータス" not in html:
        print("Error: セッションが無効です。ログインに失敗した可能性があります。", file=sys.stderr)
        sys.exit(1)

    return html


def extract_value(html, element_id):
    """HTMLから指定IDの要素の値を取得"""
    match = re.search(rf'id="{element_id}"[^>]*>([^<]+)<', html)
    if match:
        return match.group(1).strip()
    return None


def logoff(opener, base_url):
    """PowerChuteからログオフ"""
    try:
        resp = opener.open(f"{base_url}/logoff", timeout=HTTP_TIMEOUT)
        resp.read()
    except Exception:
        pass


def _sanitize_zabbix_value(value):
    """zabbix_senderに渡す値から不正な文字を除去"""
    if not isinstance(value, str):
        value = str(value)
    value = value.replace("\n", "").replace("\r", "")
    if not value:
        return None
    return value


def _sanitize_zabbix_host(hostname):
    """zabbix_senderに渡すホスト名を検証"""
    if not re.match(r'^[\w.\-]+$', hostname):
        print(f"Error: 不正なZabbixホスト名です: {hostname}", file=sys.stderr)
        sys.exit(1)
    return hostname


def zabbix_send(zabbix_server, zabbix_host, all_values, zabbix_port=10051):
    """zabbix_senderで全項目を一括送信"""
    zabbix_host = _sanitize_zabbix_host(zabbix_host)
    lines = []
    for name, value in all_values.items():
        key = ZABBIX_KEYS[name]
        sanitized = _sanitize_zabbix_value(value)
        if sanitized is None:
            print(f"Warning: {name} の値が空です。スキップします。", file=sys.stderr)
            continue
        lines.append(f"{zabbix_host} {key} {sanitized}")

    if not lines:
        print("Error: 送信可能な項目がありません。", file=sys.stderr)
        sys.exit(1)

    sender_data = "\n".join(lines) + "\n"

    cmd = [
        "zabbix_sender",
        "-z", zabbix_server,
        "-p", str(zabbix_port),
        "-i", "-",
    ]

    result = subprocess.run(
        cmd, input=sender_data, capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"Error: zabbix_sender failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    print(result.stdout.strip(), file=sys.stderr)


def _mqtt_publish_paho(mqtt_broker, mqtt_topic, payload, mqtt_port, mqtt_user, mqtt_password):
    """paho-mqttライブラリでMQTT送信"""
    try:
        import paho.mqtt.publish as publish
    except ImportError:
        print("Error: mosquitto_pub コマンドも paho-mqtt パッケージも見つかりません。\n"
              "いずれかをインストールしてください:\n"
              "  mosquitto_pub: brew install mosquitto / sudo apt install mosquitto-clients\n"
              "  paho-mqtt:     pip3 install paho-mqtt", file=sys.stderr)
        sys.exit(1)

    auth = None
    if mqtt_user:
        auth = {"username": mqtt_user}
        if mqtt_password:
            auth["password"] = mqtt_password

    try:
        publish.single(mqtt_topic, payload, hostname=mqtt_broker, port=mqtt_port, auth=auth)
    except Exception as e:
        print(f"Error: MQTT publish failed: {e}", file=sys.stderr)
        sys.exit(1)


def mqtt_publish(mqtt_broker, mqtt_topic, all_values, mqtt_port=1883,
                 mqtt_user=None, mqtt_password=None):
    """MQTT送信（mosquitto_pub優先、なければpaho-mqttにフォールバック）"""
    payload = json.dumps(all_values)

    # mosquitto_pubが利用可能か確認
    import shutil
    if shutil.which("mosquitto_pub"):
        cmd = [
            "mosquitto_pub",
            "-h", mqtt_broker,
            "-p", str(mqtt_port),
            "-t", mqtt_topic,
            "-m", payload,
        ]

        if mqtt_user:
            cmd.extend(["-u", mqtt_user])
        if mqtt_password:
            cmd.extend(["-P", mqtt_password])

        result = subprocess.run(
            cmd, capture_output=True, text=True
        )

        if result.returncode != 0:
            print(f"Error: mosquitto_pub failed: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
    else:
        _mqtt_publish_paho(mqtt_broker, mqtt_topic, payload, mqtt_port, mqtt_user, mqtt_password)

    print(f"MQTT published to {mqtt_topic}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="APC PowerChute Serial Shutdown for Business からUPSステータスを取得",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""取得項目オプション:
  --status          デバイスステータス (オンライン等)
  --load            UPS負荷 (%%)
  --runtime         ランタイム残り時間 (分)
  --voltage         入力電圧 (VAC)
  --battery         バッテリー充電 (%%)
  --batteryvoltage  バッテリー電圧 (VDC)

オプション未指定の場合は --load がデフォルトです。
複数指定時はスペース区切りで出力します。

認証情報の指定方法 (優先順):
  1. コマンドライン引数
  2. 環境変数: APCGET_IP, APCGET_USERNAME, APCGET_PASSWORD
  3. 設定ファイル: ~/.apcget.conf

設定ファイルの書式 (~/.apcget.conf):
  [powerchute]
  ip = 192.168.1.100
  username = administrator
  password = your_password

Zabbix連携 (トラッパー):
  --zabbix-send ZABBIX_SERVER  全項目をzabbix_senderで一括送信
  --zabbix-host HOSTNAME       Zabbix上のホスト名 (デフォルト: IPアドレス)
  --zabbix-port PORT           Zabbixサーバーのポート (デフォルト: 10051)

  Zabbix側に以下のトラッパーアイテムを作成してください:
    apc.status          (文字列)  デバイスステータス
    apc.load            (数値)    UPS負荷
    apc.runtime         (数値)    ランタイム残り時間
    apc.voltage         (数値)    入力電圧
    apc.battery         (数値)    バッテリー充電
    apc.batteryvoltage  (数値)    バッテリー電圧

使用例:
  # コマンドライン引数で指定
  %(prog)s 192.168.1.100 admin password

  # 環境変数で指定
  export APCGET_PASSWORD='secret'
  %(prog)s 192.168.1.100 admin

  # 設定ファイルのみで実行
  %(prog)s

  # 全項目をZabbixに送信
  %(prog)s --zabbix-send 192.168.1.1 --zabbix-host MyUPS
""",
    )
    parser.add_argument("ip", nargs="?", default=None, help="PowerChuteのIPアドレス")
    parser.add_argument("username", nargs="?", default=None, help="ログインユーザ名")
    parser.add_argument("password", nargs="?", default=None, help="ログインパスワード")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH,
                        help=f"設定ファイルのパス（デフォルト: {DEFAULT_CONFIG_PATH}）")
    parser.add_argument("--status", action="store_true", help="デバイスステータス")
    parser.add_argument("--load", action="store_true", help="UPS負荷")
    parser.add_argument("--runtime", action="store_true", help="ランタイム残り時間")
    parser.add_argument("--voltage", action="store_true", help="入力電圧")
    parser.add_argument("--battery", action="store_true", help="バッテリー充電")
    parser.add_argument("--batteryvoltage", action="store_true", help="バッテリー電圧")
    parser.add_argument("--json", action="store_true",
                        help="全項目をJSON形式で出力")
    parser.add_argument("--mqtt-send", metavar="MQTT_BROKER",
                        help="MQTTブローカーのアドレス（指定すると全項目をmosquitto_pubで送信）")
    parser.add_argument("--mqtt-topic", metavar="TOPIC",
                        default="apcget/ups",
                        help="MQTTトピック（デフォルト: apcget/ups）")
    parser.add_argument("--mqtt-port", type=int, default=1883,
                        help="MQTTブローカーのポート（デフォルト: 1883）")
    parser.add_argument("--mqtt-user", metavar="USERNAME",
                        help="MQTT認証ユーザ名")
    parser.add_argument("--mqtt-password", metavar="PASSWORD",
                        help="MQTT認証パスワード")
    parser.add_argument("--zabbix-send", metavar="ZABBIX_SERVER",
                        help="Zabbixサーバーのアドレス（指定すると全項目をzabbix_senderで送信）")
    parser.add_argument("--zabbix-host", metavar="HOSTNAME",
                        help="Zabbix上のホスト名（デフォルト: IPアドレス）")
    parser.add_argument("--zabbix-port", type=int, default=10051,
                        help="Zabbixサーバーのポート（デフォルト: 10051）")
    args = parser.parse_args()

    # 設定ファイルの読み込み
    config = load_config(args.config)

    # 認証情報の解決: 引数 → 環境変数 → 設定ファイル
    ip = resolve_credential(args.ip, "APCGET_IP", config.get("ip"), "IPアドレス")
    username = resolve_credential(args.username, "APCGET_USERNAME", config.get("username"), "ユーザ名")
    password = resolve_credential(args.password, "APCGET_PASSWORD", config.get("password"), "パスワード")

    base_url = f"https://{ip}:6547"
    opener, opener_noredir = create_openers()

    try:
        login(opener, opener_noredir, base_url, username, password)
        html = get_status_page(opener, base_url)

        if args.zabbix_send or args.mqtt_send or args.json:
            # 全項目取得モード（Zabbix送信 / MQTT送信 / JSON出力）
            all_values = {}
            for name, element_id in ITEMS.items():
                value = extract_value(html, element_id)
                if value is None:
                    print(f"Warning: {name} の値を取得できませんでした。スキップします。", file=sys.stderr)
                    continue
                all_values[name] = value

            if not all_values:
                print("Error: 取得できた項目がありません。", file=sys.stderr)
                sys.exit(1)

            if args.json:
                print(json.dumps(all_values))
            elif args.mqtt_send:
                mqtt_publish(args.mqtt_send, args.mqtt_topic, all_values,
                             args.mqtt_port, args.mqtt_user, args.mqtt_password)
            else:
                zabbix_host = args.zabbix_host or ip
                zabbix_send(args.zabbix_send, zabbix_host, all_values, args.zabbix_port)
        else:
            # 通常モード: 指定された項目を標準出力
            selected = [name for name in ITEMS if getattr(args, name)]
            if not selected:
                selected = ["load"]

            values = []
            for name in selected:
                value = extract_value(html, ITEMS[name])
                if value is None:
                    print(f"Error: {name} の値を取得できませんでした。", file=sys.stderr)
                    sys.exit(1)
                values.append(value)

            print(" ".join(values))
    finally:
        logoff(opener, base_url)


if __name__ == "__main__":
    main()
