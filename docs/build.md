# Build and Flash Guide

This guide covers building the XiaoZhi AI firmware from source and flashing it to a device. For end users who only need a pre-built binary, see the beginner flashing guide linked from the [README](../README.md).

## Quick start (guided)

If you'd rather not step through `menuconfig` by hand, run the interactive wizard. It picks the target, board, partition, wake-word, language, WiFi provisioning method, OTA URL, and serial port for you, then runs `idf.py set-target`, `build`, `flash`, and `monitor`. It can also write a starter `data/.config.yaml` into a local clone of [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) so the device boots straight into a working pipeline with your chosen LLM/ASR/TTS providers.

```bash
pip install -r scripts/requirements.txt
python scripts/setup_and_flash.py            # full wizard
python scripts/setup_and_flash.py --dry-run  # preview generated configs without writing
python scripts/setup_and_flash.py --resume   # prefill answers from the previous run
```

You do **not** need to source `export.sh` first. The wizard looks for an existing ESP-IDF checkout on `PATH`, in `$IDF_PATH`, or in common locations (`~/esp/esp-idf`, `~/.espressif/esp-idf`, `/opt/esp-idf`, `/opt/esp/esp-idf`). If none is found, it offers to git-clone the pinned release (`v5.5.2`) and run `install.sh` for your chosen target. All subsequent `idf.py` calls are wrapped in `bash -c '. export.sh && idf.py …'`, so nothing leaks outside the script. On native Windows, install ESP-IDF via Espressif's installer or use WSL/MSYS2.

The wizard composes its choices into a `SDKCONFIG_DEFAULTS` chain rather than mutating `sdkconfig`, so you can still run `idf.py menuconfig` afterward and your edits will stick. The rest of this document describes the manual flow, which the wizard wraps.

## Prerequisites

- **ESP-IDF 5.4 or newer.** The project is developed against ESP-IDF 5.5.x; CI builds with 5.5.2. Follow Espressif's [ESP-IDF Get Started](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/get-started/index.html) guide to install the toolchain.
- **Python 3.10+** (installed by ESP-IDF's installer on Windows; use the system Python on Linux/macOS).
- **Git** and a USB-serial driver for your board.
- **Supported MCU targets**: `esp32`, `esp32c3`, `esp32c5`, `esp32c6`, `esp32s3`, `esp32p4`.

Linux is recommended. Windows and macOS work; compilation is slower and driver setup is more involved.

## 1. Clone the Repository

```bash
git clone https://github.com/78/xiaozhi-esp32.git
cd xiaozhi-esp32
```

Activate the ESP-IDF environment in the shell you will build from:

```bash
. $IDF_PATH/export.sh          # Linux / macOS
%IDF_PATH%\export.bat          # Windows cmd
```

## 2. Select a Board

You have two options. Use path **A** for day-to-day development; use path **B** to produce a release-style flashable image of a known board.

### A. Manual (menuconfig)

Pick a target MCU, then select the board under `Xiaozhi Assistant`:

```bash
idf.py set-target esp32s3      # or esp32, esp32c3, esp32c5, esp32c6, esp32p4
idf.py menuconfig
```

In menuconfig:

- `Xiaozhi Assistant` -> `Board Type` - choose a board. Only boards compatible with the current target are listed (entries are gated by `IDF_TARGET_*`).
- `Partition Table` -> `Custom partition CSV file` - defaults to `partitions/v2/16m.csv`. Change it to match your flash size (see [partitions/v2/README.md](../partitions/v2/README.md)).

### B. Scripted (`scripts/release.py`)

The release script is what CI uses. It reads `main/boards/<board>/config.json`, sets the correct target, appends the board's `sdkconfig_append` entries, builds, and writes a zipped `merged-binary.bin` to `releases/`.

```bash
python scripts/release.py --list-boards                          # list every board and variant
python scripts/release.py waveshare/esp32-p4-wifi6-touch-lcd     # build all variants of a board
python scripts/release.py bread-compact-wifi --name bread-compact-wifi-ml307   # build a single variant
```

Output lands in `releases/v<version>_<name>.zip`. The script skips variants whose zip already exists; delete the zip to force a rebuild.

## 3. Build

```bash
idf.py build
```

Notes:

- The first build resolves ~60 managed components (LVGL, ESP-SR, `esp_codec_dev`, etc.) and may take several minutes.
- The assets partition (`assets.bin`) is built automatically from the wake-word, font, and emoji options selected in menuconfig. `scripts/build_default_assets.py` is invoked by the build system; you do not need to run it by hand for default setups.

## 4. Flash and Monitor

Connect the board and find its serial port (`/dev/ttyUSB0`, `/dev/ttyACM0`, `COM5`, etc.), then:

```bash
idf.py -p /dev/ttyUSB0 flash monitor
```

`Ctrl+]` exits the monitor.

### Flashing a pre-built release zip

If you have a `releases/v<version>_<name>.zip` from `scripts/release.py` or a GitHub Actions artifact, unzip it and flash the merged binary directly with `esptool.py`:

```bash
unzip v2.2.5_bread-compact-wifi.zip
esptool.py --chip esp32s3 -p /dev/ttyUSB0 write_flash 0x0 merged-binary.bin
```

The offset is `0x0` because `idf.py merge-bin` produces an absolute image containing the bootloader, partition table, app, and assets.

## 5. Custom Assets (optional)

The assets partition holds wake-word models, fonts, emojis, and themes. For most users the defaults selected in menuconfig are sufficient. To build fully custom assets, use the web tool at [78/xiaozhi-assets-generator](https://github.com/78/xiaozhi-assets-generator); the on-device packer is `scripts/build_default_assets.py` (see the script's own `--help` for arguments).

## Troubleshooting

- **`idf.py: command not found`** - re-source `export.sh` (or `export.bat` on Windows) in the current shell.
- **Wrong chip detected / link errors after switching MCUs** - run `idf.py set-target <chip>` before `idf.py build`; target changes do not take effect otherwise.
- **Stale `sdkconfig` after a `release.py` run** - `release.py` appends lines to `sdkconfig`. Delete `build/` and `sdkconfig`, then reconfigure, to return to a clean state.
- **Flash-size mismatch at boot** - the partition CSV must match the physical flash. Select the correct file from `partitions/v2/` under `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME`.
- **Upgrading from v1 to v2** - the partition layouts are incompatible. Full reflash is required; OTA cannot migrate (see [README](../README.md#version-notes)).

## See Also

- [Custom Board Guide](custom-board.md) - add a new board.
- [MCP Usage](mcp-usage.md), [MCP Protocol](mcp-protocol.md) - device-side tooling and protocol.
- [WebSocket Protocol](websocket.md), [MQTT + UDP Protocol](mqtt-udp.md) - transport options.
- [Partition Layouts](../partitions/v2/README.md) - sizing guidance for 4/8/16/32 MB flash.
