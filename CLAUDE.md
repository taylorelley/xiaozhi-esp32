# CLAUDE.md — xiaozhi-esp32 firmware

Guide for AI assistants working on this repository.

## What this repo is

Open-source ESP32 firmware for the LittleWise / XiaoZhi AI voice chatbot. Supports 100+ hardware boards, streams audio to a backend over WebSocket or MQTT+UDP, runs offline wake-word detection via ESP-SR, and exposes device-side tools to the LLM through **MCP (Model Context Protocol)**.

Current release: v2.2.5 (see `CMakeLists.txt`). MIT licensed.

Part of a three-repo ecosystem:
- `xiaozhi-esp32` — **this repo** (device firmware)
- `xiaozhi-esp32-server` — Python/Java backend + admin consoles
- `xiaozhi-assets-generator` — browser tool that produces the `assets.bin` this firmware mounts

## Layout

```
main/                           # ESP-IDF component (the app)
├── main.cc                     # app_main() — C entry; calls Application::Run()
├── application.cc/.h           # Singleton; FreeRTOS event loop; state machine
├── device_state_machine.cc/.h  # Idle → Listening → Processing → Speaking
├── mcp_server.cc/.h            # Device-side MCP tools (LED, GPIO, servo, speaker, screen, …)
├── ota.cc/.h                   # OTA firmware updates
├── protocols/
│   ├── websocket_protocol.cc/.h
│   └── mqtt_protocol.cc/.h     # MQTT + UDP voice channel
├── audio/
│   ├── audio_service.cc/.h
│   ├── audio_codec.cc/.h
│   ├── codecs/                 # Opus + raw codecs
│   ├── processors/             # AEC, VAD, etc.
│   ├── demuxer/
│   └── wake_words/             # ESP-SR integration
├── display/lvgl_display/       # LVGL 9.5 UI, emoji, fonts
├── led/
├── assets/                     # Mounts assets partition (xiaozhi-assets-generator output)
├── boards/
│   ├── common/                 # Shared drivers (WiFi, ML307 4G, cameras, displays, power)
│   └── <board-name>/           # ~100 per-board configs (GPIO, codec, LCD controller)
├── Kconfig.projbuild           # CONFIG_BOARD_TYPE_* + feature flags
└── idf_component.yml           # 60+ component-manager deps (LVGL, esp_codec_dev, ESP-SR, …)
partitions/
├── v1/                         # Legacy (4m/8m/16m/32m)
└── v2/                         # Current — adds assets partition
    ├── README.md               # Partition layout reference
    └── 4m.csv / 8m.csv / 16m.csv / 16m_c3.csv / 32m.csv
scripts/
├── build_default_assets.py     # Build assets partition from presets
├── gen_lang.py                 # Generate language resource
└── release.py                  # Release automation
sdkconfig.defaults[.esp32(c3|c5|c6|p4|s3)]   # Per-target IDF defaults
CMakeLists.txt                  # Project root (v2.2.5)
.clang-format                   # Google C++ style
docs/                           # Protocol, custom-board guide, MCP docs
.github/workflows/              # CI
```

## Tech stack

- **MCU targets**: ESP32, ESP32-S3, ESP32-C3, ESP32-C5, ESP32-C6, ESP32-P4
- **Framework**: ESP-IDF ≥ **5.5.2** (CMake)
- **Language**: C++17, Google style (see `.clang-format`)
- **UI**: LVGL 9.5 (70+ LCD controllers driven through `esp_lcd_*`)
- **Audio**: ESP-SR (wake words + speaker recognition), Opus, `esp_codec_dev`
- **Networking**: WiFi or ML307 Cat.1 4G modem; WebSocket or MQTT+UDP transport
- **Storage**: NVS for config, SPIFFS for assets partition (mmap at runtime)
- **RTOS**: FreeRTOS — event groups, async `Schedule(callback)` pattern

## Build & flash

```bash
# one-time
. $IDF_PATH/export.sh
idf.py set-target esp32s3        # or esp32, esp32c3, esp32p4, …
idf.py menuconfig                # select CONFIG_BOARD_TYPE_* under "Xiaozhi Assistant"

idf.py build
idf.py -p /dev/ttyUSB0 flash monitor

# assets partition (themes, wake words, fonts)
python scripts/build_default_assets.py

# release helper
python scripts/release.py
```

Partition table is chosen via `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME`, default `partitions/v2/16m.csv`.

## Partitions

`partitions/v2/` layouts all reserve an **assets** partition so themes / wake-words can be updated OTA without reflashing:

| CSV | App (OTA_0+OTA_1) | Assets |
|-----|-------------------|--------|
| `4m.csv` | 3 MB + 3 MB | (see file) |
| `8m.csv` | 3 MB + 3 MB | 2 MB |
| `16m.csv` (default) | 4 MB + 4 MB | 8 MB |
| `16m_c3.csv` | 4 MB + 4 MB | 4 MB (C3 mmap cap) |
| `32m.csv` | 4 MB + 4 MB | 16 MB |

v1 → v2 requires a full reflash (incompatible layouts).

## Architecture highlights

- **Entry**: `main/main.cc` → `extern "C" app_main()` → `Application::GetInstance().Initialize(); app.Run()`.
- **State machine**: events flow through a FreeRTOS EventGroup — `WAKE_WORD_DETECTED`, `SEND_AUDIO`, `NETWORK_CONNECTED`, `STATE_CHANGED`, `CLOCK_TICK`. Async work is posted with `Application::Schedule(lambda)`.
- **Pipeline**: mic → VAD/AEC → Opus encode → `protocols/*_protocol` → server ASR → LLM → TTS → decode → speaker. MCP tool invocations run inline on the device event loop.
- **Board abstraction**: each `main/boards/<name>/` directory provides GPIO, codec, LCD, and power drivers; shared bits live under `main/boards/common/`. Selected via Kconfig.

## Conventions

- C++17, Google style, no namespaces (flat).
- Singletons via `Klass::GetInstance()` (e.g. `Application`, `AudioService`).
- Prefer `Schedule(...)` over blocking calls on the main loop.
- Match existing log tags (`ESP_LOGI(TAG, ...)`) and header guard / include patterns of neighboring files.
- Commit prefix style (see `git log`): `firmware: <description>` or `firmware(<area>): ...`.

## Working on this repo

- **Adding a board** → create `main/boards/<name>/`, add a `CMakeLists.txt`, implement the board class, add a `CONFIG_BOARD_TYPE_<NAME>` Kconfig option, update `main/Kconfig.projbuild`. Follow `docs/` custom-board guide.
- **Adding an MCP tool** → register it in `mcp_server.cc`; keep the tool name in sync with `xiaozhi-assets-generator/mcp_calls.log` / server-side consumers.
- **Assets partition format changes** must stay in lockstep with `xiaozhi-assets-generator` (SPIFFS layout, `index.json` schema, wake-word model packing).
- **Don't bump ESP-IDF or component versions** casually — many boards pin LCD/codec drivers.
- **No emojis in code or comments**; keep comments short and only where WHY is non-obvious.
- Chinese board READMEs live as `README_zh.md`; English stubs as `README.md`.

## Branch policy

- Develop on `claude/add-claude-documentation-D9b9t` (or the branch the task specifies).
- Never push to `main` directly.
- PRs only when explicitly requested.

## Useful docs

- `docs/` — protocol description, custom board guide, MCP usage
- `partitions/v2/README.md` — detailed partition layout and migration notes
- `.github/workflows/` — CI matrix for supported targets
