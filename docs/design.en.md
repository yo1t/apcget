# apcget Design Document

## 1. Overview

### 1.1 Purpose

apcget is a Python script that scrapes UPS status information from the APC PowerChute Serial Shutdown for Business Web UI, providing command-line output, JSON output, MQTT publishing, and Zabbix sender integration.

### 1.2 Background

APC PowerChute Serial Shutdown for Business does not provide an SNMP interface, making it difficult to retrieve UPS information through standard monitoring protocols. This tool bypasses that limitation by parsing the Web UI HTML, enabling integration with monitoring systems such as Home Assistant and Zabbix.

### 1.3 Target Environment

| Item | Value |
|---|---|
| Target Software | APC PowerChute Serial Shutdown for Business v1.4.0 |
| Web UI Port | TCP 6547 (HTTPS) |
| Language | Python 3.6+ |
| Dependencies | Standard library only (MQTT/Zabbix send requires additional tools) |
| License | MIT License |

---

## 2. Architecture

### 2.1 Processing Flow

```
┌──────────────────┐
│  Parse arguments  │
│  Resolve credentials │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐     ┌─────────────────────────┐
│      Login        │────▶│ Detect existing session  │
│                   │◀────│ → Log off → Retry        │
└────────┬─────────┘     └─────────────────────────┘
         │
         ▼
┌──────────────────┐
│ Detect locale     │  ← Check <html lang="...">
│ Switch to English │  ← POST /setLocale if non-English
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Get status page   │  ← Parse /status page HTML
│ Extract values    │  ← Extract by HTML element ID
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Output           │  ← stdout / JSON / MQTT / Zabbix
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Restore locale    │  ← Restore original locale
│ Log off           │
└──────────────────┘
```

### 2.2 Output Modes

| Mode | Trigger | Destination | Description |
|---|---|---|---|
| Normal | No option or `--load` etc. | stdout | Print selected items separated by spaces |
| JSON | `--json` | stdout | Print all items in JSON format |
| MQTT | `--mqtt-send` | MQTT broker | Publish all items as a JSON payload |
| Zabbix | `--zabbix-send` | Zabbix server | Send all items as trapper items |

JSON / MQTT / Zabbix can be used simultaneously (processed by independent `if` statements).

---

## 3. Module Structure

### 3.1 File Structure

```
apcget.py          ← Single-file design (no external module dependencies)
```

### 3.2 Constants

| Name | Type | Description |
|---|---|---|
| `ITEMS` | dict | Item name → HTML element ID mapping |
| `ZABBIX_KEYS` | dict | Item name → Zabbix trapper item key mapping |
| `DEFAULT_CONFIG_PATH` | str | Default config file path (`~/.apcget.conf`) |
| `HTTP_TIMEOUT` | int | HTTP request timeout (30 seconds) |

### 3.3 Retrievable Items

| Item Name | HTML Element ID | Zabbix Key | Unit |
|---|---|---|---|
| `status` | `value_DeviceStatus` | `apc.status` | - (string) |
| `load` | `value_RealPowerPct` | `apc.load` | % |
| `runtime` | `value_RuntimeRemaining` | `apc.runtime` | min |
| `voltage` | `value_InputVoltage` | `apc.voltage` | VAC |
| `battery` | `value_BatteryCharge` | `apc.battery` | % |
| `batteryvoltage` | `value_VoltageDC` | `apc.batteryvoltage` | VDC |

---

## 4. Function Design

### 4.1 Credential Management

#### `load_config(config_path) → dict`

- Reads `ip`, `username`, `password` from the `[powerchute]` section of an INI-format config file
- Returns an empty dict if the file does not exist

#### `resolve_credential(args_value, env_name, config_value, label) → str`

- Resolves credentials in the following priority order:
  1. Command-line arguments
  2. Environment variables (`APCGET_IP`, `APCGET_USERNAME`, `APCGET_PASSWORD`)
  3. Config file
- Exits with error if no value is found in any source

### 4.2 HTTP Communication

#### `create_openers() → (opener, opener_noredir)`

- Returns two urllib openers with SSL certificate verification disabled:
  - `opener`: Follows redirects (for normal page retrieval)
  - `opener_noredir`: Does not follow redirects (for login redirect detection)
- Cookies are automatically managed via `CookieJar` (session persistence)

**Design decision**: SSL verification is disabled because PowerChute uses self-signed certificates.

### 4.3 Page Detection (Language-Independent)

#### `_is_status_page(html) → bool`

- Determines whether the page is a status page by checking for the presence of `value_DeviceStatus`
- HTML element IDs are language-independent, so this works regardless of display language

#### `_is_already_logged_on(html) → bool`

- Detects the "already logged on" condition using the `alreadyLoggedOn` HTML element ID combined with message text matching (English or Japanese)

### 4.4 Locale Control

#### `_detect_locale(html) → str | None`

- Extracts the locale code from the `<html lang="...">` attribute (e.g., `"en"`, `"ja"`)

#### `_set_locale(opener, base_url, locale) → str`

- Sends a POST request to the PowerChute `/setLocale` endpoint
- Parameters: `newLocale` (locale code), `targetURL` (redirect destination)

#### `ensure_english(opener, base_url) → str | None`

- Detects the current language of the status page and switches to English if not already English
- Returns: the original locale code (if switched), `None` (if already English)

#### `restore_locale(opener, base_url, original_locale)`

- Restores the locale recorded by `ensure_english`
- Exceptions are silently ignored (best-effort cleanup before logoff)

**Design decision**: Status values (especially `status`) are language-dependent (e.g., "On Line" vs "オンライン"). To ensure consistent output, data is always retrieved in English, and the original language is restored after processing.

### 4.5 Authentication

#### `login(opener, opener_noredir, base_url, username, password)`

**Processing flow:**

```
1. Access /status → Redirected to login page
2. If "already logged on" → Log off via /logoff and retry
3. If status page is already displayed → No login needed (return)
4. Extract formtoken / formtokenid from HTML (CSRF protection tokens)
5. Dynamically read the login button's value attribute (language-aware)
6. POST to /j_security_check (Java EE form-based auth)
7. Determine success/failure by redirect destination:
   - Redirect to /status → Success
   - Redirect to /logon → Authentication failure
```

**Design decisions**:
- Uses `opener_noredir` (no redirect following) to determine login result from the `Location` header
- The login button's `value` attribute is dynamically read from the page, enabling language-independent login

#### `logoff(opener, base_url)`

- Accesses `/logoff` to terminate the session
- Exceptions are silently ignored (cleanup processing)

### 4.6 Data Retrieval

#### `get_status_page(opener, base_url) → str`

- Retrieves the HTML of the `/status` page
- Exits with error if redirected to the login page

#### `extract_value(html, element_id) → str | None`

- Extracts element values using the regex `id="{element_id}"[^>]*>([^<]+)<`
- Target: `<span id="value_DeviceStatus" ...>On Line</span>` etc.

### 4.7 External Integration

#### `zabbix_send(zabbix_server, zabbix_host, all_values, zabbix_port=10051)`

- Executes the `zabbix_sender` command with `-i -` (stdin mode)
- Sends all items in a single `zabbix_sender` invocation
- Hostname is validated (`_sanitize_zabbix_host`)
- Values are sanitized with newlines removed (`_sanitize_zabbix_value`)

**Prerequisite**: `zabbix_sender` command must be installed

#### `mqtt_publish(mqtt_broker, mqtt_topic, all_values, mqtt_port, mqtt_user, mqtt_password)`

- Tool selection:
  1. If `mosquitto_pub` is found in PATH → Use `mosquitto_pub`
  2. Otherwise → Fall back to `paho-mqtt` Python package
- Payload is a JSON string containing all items

#### `_mqtt_publish_paho(...)`

- Publishes via `paho.mqtt.publish.single()`
- Import is deferred (prevents startup errors when `paho-mqtt` is not installed)

**Prerequisite**: Either `mosquitto_pub` or `paho-mqtt` must be installed

---

## 5. Credential Management

### 5.1 Methods and Priority

```
High priority
  │  1. Command-line arguments    apcget.py <IP> <USER> <PASS>
  │  2. Environment variables     APCGET_IP, APCGET_USERNAME, APCGET_PASSWORD
  ▼  3. Config file               ~/.apcget.conf (changeable with --config)
Low priority
```

### 5.2 Config File Format

```ini
[powerchute]
ip = 192.168.1.100
username = your_username
password = your_password
```

---

## 6. Command-Line Arguments

### 6.1 Positional Arguments

| Argument | Required | Description |
|---|---|---|
| `ip` | Conditional | PowerChute IP address |
| `username` | Conditional | Login username |
| `password` | Conditional | Login password |

*Can be omitted if specified via config file or environment variables.

### 6.2 Item Selection Options

| Option | Description |
|---|---|
| `--status` | Device status |
| `--load` | UPS load (%) |
| `--runtime` | Runtime remaining (min) |
| `--voltage` | Input voltage (VAC) |
| `--battery` | Battery charge (%) |
| `--batteryvoltage` | Battery voltage (VDC) |

Defaults to `--load` if no item is specified.

### 6.3 Output Options

| Option | Argument | Default | Description |
|---|---|---|---|
| `--json` | None | - | Print all items in JSON to stdout |
| `--mqtt-send` | MQTT_BROKER | - | MQTT broker address |
| `--mqtt-topic` | TOPIC | `apcget/ups` | MQTT topic name |
| `--mqtt-port` | PORT | `1883` | MQTT broker port |
| `--mqtt-user` | USERNAME | - | MQTT auth username |
| `--mqtt-password` | PASSWORD | - | MQTT auth password |
| `--zabbix-send` | ZABBIX_SERVER | - | Zabbix server address |
| `--zabbix-host` | HOSTNAME | IP address | Zabbix host name |
| `--zabbix-port` | PORT | `10051` | Zabbix server port |

### 6.4 Other

| Option | Description |
|---|---|
| `--config` | Config file path (default: `~/.apcget.conf`) |
| `--help` | Display help |

---

## 7. Error Handling

### 7.1 Error Types

| Situation | Action | Exit Code |
|---|---|---|
| Credentials not specified | Error output to stderr | 1 |
| Login failure | Error output to stderr | 1 |
| Invalid session | Error output to stderr | 1 |
| Value retrieval failed (normal mode) | Error output to stderr | 1 |
| Value retrieval failed (all-items mode) | Warning to stderr, skip | - |
| No items retrieved | Error output to stderr | 1 |
| zabbix_sender failure | Error output to stderr | 1 |
| MQTT publish failure | Error output to stderr | 1 |
| MQTT tools not installed | Error output to stderr | 1 |

### 7.2 Cleanup

The `finally` block guarantees:
1. Locale restoration (`restore_locale`)
2. Session logoff (`logoff`)

Both silently ignore exceptions, ensuring execution even during error conditions.

---

## 8. Security Considerations

### 8.1 SSL Certificate Verification

- SSL certificate verification is disabled because PowerChute uses self-signed certificates
- This is a design decision based on the assumption of LAN-only usage

### 8.2 Input Sanitization

- Zabbix hostname: Validated with the pattern `^[\w.\-]+$` (prevents command injection)
- Zabbix values: Newline characters removed
- External command invocation: Uses `subprocess.run` with list-form arguments (prevents shell injection)

### 8.3 Credential Protection

- Config file-based credential management is recommended (command-line arguments are visible in process listings)
- Environment variable specification is also supported

---

## 9. Multi-Language Support

### 9.1 Design Policy

The PowerChute Web UI supports multiple display languages (English, Japanese, etc.). Since UPS status values are language-dependent (e.g., "On Line" vs "オンライン"), the following approach was adopted to ensure data consistency.

### 9.2 Processing Method

```
Login
  │
  ▼
Detect current display language ← <html lang="..."> attribute
  │
  ├── English → Continue as is
  │
  └── Non-English
        │
        ▼
      POST /setLocale (newLocale=en) → Switch to English
        │
        ▼
      Retrieve data (in English for consistency)
        │
        ▼
      POST /setLocale (newLocale=original) → Restore original language
        │
        ▼
      Log off
```

### 9.3 Language-Independent Detection

The following detection logic uses HTML element IDs and is not dependent on display language:

| Detection | Method | Rationale |
|---|---|---|
| Status page detection | Presence of `value_DeviceStatus` | HTML element IDs are language-invariant |
| Existing session detection | Presence of `alreadyLoggedOn` | HTML element IDs are language-invariant |
| Value extraction | Regex on `id="value_..."` | HTML element IDs are language-invariant |
| Login button | Dynamic read of `name="login"` value attribute | Display value is language-dependent but dynamically read |

---

## 10. External Integration

### 10.1 MQTT Publishing

```
apcget.py ──▶ mosquitto_pub (preferred) ──▶ MQTT Broker ──▶ Home Assistant
                                                            Subscriber
         └──▶ paho-mqtt (fallback) ───────┘
```

- Topic: Customizable (default `apcget/ups`)
- Payload: JSON containing all items
- Authentication: Username/password (optional)

### 10.2 Zabbix Sender

```
apcget.py ──▶ zabbix_sender -i - ──▶ Zabbix Server
```

- Host name: Customizable (defaults to PowerChute IP address)
- Item type: Zabbix trapper
- Send method: Batch send via stdin

### 10.3 Home Assistant command_line Sensor

When not using MQTT, integration is also possible by combining the `--json` option with a Home Assistant `command_line` sensor.

---

## 11. Deployment Example

### 11.1 Scheduled Execution via cron

```cron
* * * * * /usr/bin/python3 /path/to/apcget.py \
  --config /path/to/.apcget.conf \
  --zabbix-send 127.0.0.1 --zabbix-host ups-living \
  --mqtt-send 192.168.1.9 --mqtt-topic apcget/ups-living \
  --mqtt-user mqtt --mqtt-password mqttpass \
  >/dev/null 2>&1
```

- Execution interval: Every 1 minute
- Zabbix and MQTT can be sent simultaneously (both handled in a single execution)
- For multiple UPS units, register separate cron entries with different config files and topic/host names

---

## 12. Known Limitations and Risks

| Item | Description |
|---|---|
| Single-session restriction | PowerChute allows only one session at a time. The Web UI is inaccessible while apcget is running |
| HTML structure dependency | If HTML element IDs change due to a PowerChute version upgrade, value extraction may fail |
| Language switch side effect | If another user is using the Web UI simultaneously, the display language may temporarily change |
| Session timeout | Processing must complete within the PowerChute session timeout (900 seconds) |
| HTTPS verification disabled | SSL verification is disabled to accommodate self-signed certificates, posing MITM risk (LAN-only usage assumed) |
