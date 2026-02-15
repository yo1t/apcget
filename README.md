# apcget

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub](https://img.shields.io/github/v/release/yo1t/apcget?label=GitHub)](https://github.com/yo1t/apcget)

A Python script to retrieve UPS status from the APC PowerChute Serial Shutdown for Business web interface.

https://github.com/yo1t/apcget

[日本語版 README はこちら](README.ja.md)

No external packages required — runs on Python standard library only.

## Requirements

- Python 3.6+
- APC PowerChute Serial Shutdown for Business (port 6547)

### Optional

- `zabbix_sender` — required only when using the `--zabbix-send` option
- `mosquitto_pub` or `paho-mqtt` — required only when using the `--mqtt-send` option (either one)

### Installing optional dependencies

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

## Usage

```bash
python3 apcget.py [IP_ADDRESS] [USERNAME] [PASSWORD] [OPTIONS]
```

Credentials can also be provided via environment variables or a config file (see below).

### Basic (get UPS load only)

```bash
python3 apcget.py 192.168.1.100 administrator password
# Output: 19.0
```

### Specify items to retrieve

```bash
# Battery charge
python3 apcget.py 192.168.1.100 administrator password --battery

# Multiple items (space-separated output)
python3 apcget.py 192.168.1.100 administrator password --load --runtime --voltage
# Output: 19.0 29 102.0
```

### Available items

| Option | Description | Example |
|---|---|---|
| `--status` | Device status | Online |
| `--load` | UPS load (%) | 19.0 |
| `--runtime` | Runtime remaining (min) | 29 |
| `--voltage` | Input voltage (VAC) | 102.0 |
| `--battery` | Battery charge (%) | 100.0 |
| `--batteryvoltage` | Battery voltage (VDC) | 13.7 |

Defaults to `--load` if no option is specified. Units (%, VAC, etc.) are not included in the output.

### JSON Output

The `--json` option outputs all items as JSON. Useful for integration with Home Assistant, scripts, etc.

```bash
python3 apcget.py 192.168.1.100 administrator password --json
# Output: {"status": "Online", "load": "19.0", "runtime": "29", "voltage": "102.0", "battery": "100.0", "batteryvoltage": "13.7"}
```

## MQTT Integration

The `--mqtt-send` option publishes all items as JSON to an MQTT broker via `mosquitto_pub`. If `mosquitto_pub` is not available, it falls back to the `paho-mqtt` Python package (`pip3 install paho-mqtt`).

```bash
python3 apcget.py 192.168.1.100 administrator password \
  --mqtt-send 192.168.1.200 \
  --mqtt-topic apcget/ups-living
```

| Option | Description | Default |
|---|---|---|
| `--mqtt-send` | MQTT broker address | (none) |
| `--mqtt-topic` | MQTT topic | apcget/ups |
| `--mqtt-port` | MQTT broker port | 1883 |
| `--mqtt-user` | MQTT username | (none) |
| `--mqtt-password` | MQTT password | (none) |

### Home Assistant Configuration

Add MQTT sensors to `configuration.yaml`:

```yaml
mqtt:
  sensor:
    - name: "UPS Load"
      state_topic: "apcget/ups-living"
      value_template: "{{ value_json.load }}"
      unit_of_measurement: "%"
    - name: "UPS Battery"
      state_topic: "apcget/ups-living"
      value_template: "{{ value_json.battery }}"
      unit_of_measurement: "%"
    - name: "UPS Runtime"
      state_topic: "apcget/ups-living"
      value_template: "{{ value_json.runtime }}"
      unit_of_measurement: "min"
    - name: "UPS Status"
      state_topic: "apcget/ups-living"
      value_template: "{{ value_json.status }}"
    - name: "UPS Voltage"
      state_topic: "apcget/ups-living"
      value_template: "{{ value_json.voltage }}"
      unit_of_measurement: "VAC"
    - name: "UPS Battery Voltage"
      state_topic: "apcget/ups-living"
      value_template: "{{ value_json.batteryvoltage }}"
      unit_of_measurement: "VDC"
```

## Zabbix Integration

The `--zabbix-send` option sends all 6 items at once via `zabbix_sender`.

```bash
python3 apcget.py 192.168.1.100 administrator password \
  --zabbix-send 10.0.0.1 \
  --zabbix-host MyUPS
```

| Option | Description | Default |
|---|---|---|
| `--zabbix-send` | Zabbix server address | (none) |
| `--zabbix-host` | Host name in Zabbix | IP address |
| `--zabbix-port` | Zabbix server port | 10051 |

### Zabbix Configuration

Create the following **Zabbix trapper** items on the target host:

| Key | Type | Description |
|---|---|---|
| `apc.status` | Text | Device status |
| `apc.load` | Numeric (float) | UPS load |
| `apc.runtime` | Numeric (integer) | Runtime remaining |
| `apc.voltage` | Numeric (float) | Input voltage |
| `apc.battery` | Numeric (float) | Battery charge |
| `apc.batteryvoltage` | Numeric (float) | Battery voltage |

### cron Example

```cron
* * * * * /usr/bin/python3 /path/to/apcget.py --config /path/to/.apcget.conf --zabbix-send 127.0.0.1 --zabbix-host ups-host >/dev/null 2>&1
```

## Credential Management

Credentials are resolved in the following priority order, allowing password-free command lines:

**Priority**: Command-line arguments > Environment variables > Config file

### Config File (`~/.apcget.conf`)

```ini
[powerchute]
ip = 192.168.1.100
username = administrator
password = your_password
```

```bash
# Run with config file only (no arguments needed)
python3 apcget.py

# Specify a custom config path
python3 apcget.py --config /etc/apcget.conf
```

Set file permissions to owner-only read:

```bash
chmod 600 ~/.apcget.conf
```

### Environment Variables

| Variable | Description |
|---|---|
| `APCGET_IP` | PowerChute IP address |
| `APCGET_USERNAME` | Login username |
| `APCGET_PASSWORD` | Login password |

```bash
export APCGET_IP=192.168.1.100
export APCGET_USERNAME=administrator
export APCGET_PASSWORD='your_password'
python3 apcget.py
```

### Security Notes

- Passing passwords as command-line arguments exposes them via `ps` and shell history. Use a config file or environment variables instead
- SSL certificate verification is disabled because PowerChute uses a self-signed certificate
- Set `chmod 600` on config files to prevent other users from reading them

## Disclaimer

This software is provided "as is", without warranty of any kind. Use at your own risk. The authors are not responsible for any damage, data loss, or other issues arising from the use of this software. This tool is not affiliated with or endorsed by Schneider Electric or APC.

## Tested Environment

- APC PowerChute Serial Shutdown for Business v1.4.0.601
- UPS: APC RS 550S
- Python 3.9 / 3.10
- Zabbix 7.4 (trapper integration)
- Amazon Linux 2023 / macOS
