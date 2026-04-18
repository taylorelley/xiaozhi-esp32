#!/usr/bin/env python3
"""Interactive wizard that builds and flashes the xiaozhi-esp32 firmware.

Optionally also writes a starter `data/.config.yaml` into a local checkout of
xiaozhi-esp32-server so the device boots straight into a working pipeline.

Usage:
    python scripts/setup_and_flash.py              # full interactive wizard
    python scripts/setup_and_flash.py --dry-run    # don't run idf.py / write files
    python scripts/setup_and_flash.py --resume     # prefill answers from last run

Requires:
    - ESP-IDF 5.4+ already installed and sourced (`. $IDF_PATH/export.sh`).
    - pip install -r scripts/requirements.txt    (questionary, pyserial, pyyaml)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


try:
    import questionary
    from questionary import Choice
except ImportError:
    _abort(
        "Missing dependency: questionary.\n"
        "Install with: pip install -r scripts/requirements.txt"
    )

try:
    import yaml
except ImportError:
    _abort(
        "Missing dependency: PyYAML.\n"
        "Install with: pip install pyyaml  (ESP-IDF ships PyYAML; source export.sh)"
    )

try:
    from serial.tools import list_ports as _serial_list_ports
except ImportError:
    _serial_list_ports = None


# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
BOARDS_DIR = ROOT / "main" / "boards"
KCONFIG_PATH = ROOT / "main" / "Kconfig.projbuild"
MAIN_CMAKE_PATH = ROOT / "main" / "CMakeLists.txt"
PARTITION_DIR = ROOT / "partitions" / "v2"
OVERRIDES_PATH = ROOT / "scripts" / ".wizard_overrides.sdkconfig"
STATE_PATH = ROOT / "scripts" / ".wizard_state.json"

TARGETS = ["esp32", "esp32s3", "esp32c3", "esp32c5", "esp32c6", "esp32p4"]

# Default version pin for auto-install — tracks what CI builds against.
DEFAULT_IDF_VERSION = "v5.5.2"
DEFAULT_IDF_INSTALL_PATH = Path.home() / "esp" / "esp-idf"
COMMON_IDF_LOCATIONS = [
    Path.home() / "esp" / "esp-idf",
    Path.home() / ".espressif" / "esp-idf",
    Path("/opt/esp-idf"),
    Path("/opt/esp/esp-idf"),
]

# Field names that should be entered as masked input.
SECRET_FIELD_RE = re.compile(
    r"(api_?key|access_token|personal_access_token|api_password|secret|password|authorization|app_?id|bot_id|user_id)$",
    re.IGNORECASE,
)
# String values that are obvious placeholders rather than real defaults.
PLACEHOLDER_VALUE_RE = re.compile(r"^(your[\s_].*|<.+>|none)$", re.IGNORECASE)

PROVIDER_KINDS = ["VAD", "ASR", "LLM", "VLLM", "TTS", "Memory", "Intent"]


# ---------------------------------------------------------------------------
# State (persisted across --resume runs)
# ---------------------------------------------------------------------------


@dataclass
class WizardState:
    target: Optional[str] = None
    board_dir: Optional[str] = None
    board_symbol: Optional[str] = None
    partition_csv: Optional[str] = None
    wake_word: Optional[str] = None
    custom_wake_word: Optional[str] = None
    custom_wake_word_display: Optional[str] = None
    custom_wake_word_threshold: Optional[int] = None
    language: Optional[str] = None
    wifi_provisioning: Optional[str] = None
    server_base_url: Optional[str] = None
    server_websocket: Optional[str] = None
    bootstrap_server: bool = False
    server_repo_path: Optional[str] = None
    selected_modules: dict[str, str] = field(default_factory=dict)
    provider_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    serial_port: Optional[str] = None

    def save(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "WizardState":
        if not STATE_PATH.exists():
            return cls()
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return cls()
        state = cls()
        for k, v in data.items():
            if hasattr(state, k):
                setattr(state, k, v)
        return state


# ===========================================================================
# Kconfig parser
# ===========================================================================
#
# Lightweight parser tuned to main/Kconfig.projbuild. We only need to
# enumerate `config <SYMBOL>` entries inside named `choice` / `menu` blocks
# and capture their friendly prompt text plus any `depends on IDF_TARGET_*`
# constraints. Full Kconfig is far richer; we deliberately implement just
# what we read here so the wizard never goes out of sync with the firmware.


@dataclass
class KconfigOption:
    symbol: str
    prompt: str
    depends_targets: set[str] = field(default_factory=set)
    requires_spiram: bool = False


@dataclass
class KconfigChoice:
    name: Optional[str]
    prompt: str
    options: list[KconfigOption] = field(default_factory=list)


_kconfig_cache: Optional[list[KconfigChoice]] = None


def _read_kconfig() -> list[KconfigChoice]:
    global _kconfig_cache
    if _kconfig_cache is not None:
        return _kconfig_cache

    if not KCONFIG_PATH.exists():
        _abort(f"Kconfig file not found: {KCONFIG_PATH}")

    lines = KCONFIG_PATH.read_text(encoding="utf-8").splitlines()
    choices: list[KconfigChoice] = []
    current_choice: Optional[KconfigChoice] = None
    current_option: Optional[KconfigOption] = None
    pending_choice_name: Optional[str] = None

    for raw in lines:
        line = raw.strip()

        if line.startswith("choice"):
            parts = line.split(maxsplit=1)
            pending_choice_name = parts[1].strip() if len(parts) > 1 else None
            current_choice = KconfigChoice(name=pending_choice_name, prompt="")
            current_option = None
            continue

        if line == "endchoice":
            if current_choice is not None:
                choices.append(current_choice)
            current_choice = None
            current_option = None
            pending_choice_name = None
            continue

        if current_choice is None:
            continue

        if line.startswith("prompt") and not current_choice.prompt:
            current_choice.prompt = _kconfig_string_arg(line)
            continue

        if line.startswith("config "):
            symbol = line.split("config ", 1)[1].strip()
            current_option = KconfigOption(symbol=symbol, prompt=symbol)
            current_choice.options.append(current_option)
            continue

        if current_option is None:
            continue

        if line.startswith("bool"):
            text = _kconfig_string_arg(line)
            if text:
                current_option.prompt = text
            continue

        if line.startswith("depends on"):
            for tok in re.findall(r"IDF_TARGET_[A-Z0-9]+", line):
                current_option.depends_targets.add(tok.replace("IDF_TARGET_", "").lower())
            if "SPIRAM" in line:
                current_option.requires_spiram = True
            continue

    _kconfig_cache = choices
    return choices


def _kconfig_string_arg(line: str) -> str:
    match = re.search(r'"([^"]*)"', line)
    return match.group(1) if match else ""


def _kconfig_choice_by_name(name: str) -> KconfigChoice:
    for choice in _read_kconfig():
        if choice.name == name:
            return choice
    _abort(f"Kconfig choice '{name}' not found in {KCONFIG_PATH.name}")
    return KconfigChoice(name=None, prompt="")  # unreachable


def _kconfig_choice_by_prompt(prompt_substring: str) -> KconfigChoice:
    for choice in _read_kconfig():
        if prompt_substring.lower() in (choice.prompt or "").lower():
            return choice
    _abort(f"Kconfig choice with prompt containing '{prompt_substring}' not found")
    return KconfigChoice(name=None, prompt="")  # unreachable


def _filter_options_for_target(options: list[KconfigOption], target: str) -> list[KconfigOption]:
    """Return the subset of options that allow `target` (or are target-agnostic)."""
    out: list[KconfigOption] = []
    for opt in options:
        if not opt.depends_targets or target in opt.depends_targets:
            out.append(opt)
    return out


# ===========================================================================
# Board catalog
# ===========================================================================
#
# A board "variant" is one entry in `main/boards/<board>/config.json :: builds[]`.
# For the wizard we present each variant as a pickable item, then resolve the
# Kconfig symbol that activates it (CONFIG_BOARD_TYPE_*). Resolution mirrors
# scripts/release.py: explicit override in sdkconfig_append wins, else look up
# main/CMakeLists.txt for the `set(BOARD_TYPE "<leaf>")` block.


@dataclass
class BoardVariant:
    board_dir: str          # e.g. "bread-compact-wifi" or "waveshare/esp32-p4-nano"
    name: str               # variant `name` from config.json
    full_name: str          # manufacturer-prefixed display name
    target: str             # e.g. "esp32s3"
    kconfig_symbol: str     # e.g. "CONFIG_BOARD_TYPE_BREAD_COMPACT_WIFI"
    sdkconfig_append: list[str] = field(default_factory=list)
    pinned_partition: Optional[str] = None  # absolute CONFIG value if pinned


_board_symbol_cache: Optional[dict[str, list[str]]] = None


def _load_board_symbols() -> dict[str, list[str]]:
    """Map board leaf-name → list of `CONFIG_BOARD_TYPE_*` candidates from main/CMakeLists.txt."""
    global _board_symbol_cache
    if _board_symbol_cache is not None:
        return _board_symbol_cache

    if not MAIN_CMAKE_PATH.exists():
        _abort(f"main/CMakeLists.txt not found: {MAIN_CMAKE_PATH}")

    lines = MAIN_CMAKE_PATH.read_text(encoding="utf-8").splitlines()
    mapping: dict[str, list[str]] = {}
    pattern = re.compile(r'set\(BOARD_TYPE\s+"([^"]+)"\)')
    guard_re = re.compile(r"if\(\s*(CONFIG_BOARD_TYPE_[A-Z0-9_]+)\s*\)|elseif\(\s*(CONFIG_BOARD_TYPE_[A-Z0-9_]+)\s*\)")

    for idx, line in enumerate(lines):
        m = pattern.search(line)
        if not m:
            continue
        leaf = m.group(1)
        for back in range(idx - 1, -1, -1):
            gm = guard_re.search(lines[back])
            if gm:
                symbol = gm.group(1) or gm.group(2)
                mapping.setdefault(leaf, []).append(symbol)
                break

    _board_symbol_cache = mapping
    return mapping


def _resolve_board_symbol(board_dir: str, target: str, sdkconfig_append: list[str]) -> Optional[str]:
    # Explicit override in config.json wins.
    explicit = re.compile(r"^(CONFIG_BOARD_TYPE_[A-Z0-9_]+)=y$")
    explicit_matches: list[str] = []
    for entry in sdkconfig_append:
        m = explicit.match(entry.strip())
        if m:
            explicit_matches.append(m.group(1))
    if explicit_matches:
        # Strip the leading "CONFIG_" because we store full names elsewhere; here we keep it.
        return explicit_matches[0]

    leaf = board_dir.split("/")[-1]
    candidates = _load_board_symbols().get(leaf, [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Disambiguate by target via Kconfig depends-on info.
    target_compatible: list[str] = []
    for cand in candidates:
        for choice in _read_kconfig():
            for opt in choice.options:
                if opt.symbol == cand:
                    if not opt.depends_targets or target in opt.depends_targets:
                        target_compatible.append(cand)
                    break
    if target_compatible:
        return target_compatible[0]
    return candidates[0]


def _extract_partition_from_append(sdkconfig_append: list[str]) -> Optional[str]:
    pat = re.compile(r'^CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="([^"]+)"$')
    for entry in sdkconfig_append:
        m = pat.match(entry.strip())
        if m:
            return m.group(1)
    return None


def _collect_board_variants() -> list[BoardVariant]:
    variants: list[BoardVariant] = []
    if not BOARDS_DIR.exists():
        _abort(f"Boards directory not found: {BOARDS_DIR}")

    for cfg_path in sorted(BOARDS_DIR.rglob("config.json")):
        board_dir_path = cfg_path.parent
        if board_dir_path.name == "common":
            continue
        board_dir = board_dir_path.relative_to(BOARDS_DIR).as_posix()

        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[warn] failed to parse {cfg_path}: {exc}", file=sys.stderr)
            continue

        target = cfg.get("target")
        if not target:
            continue
        manufacturer = cfg.get("manufacturer")

        for build in cfg.get("builds", []):
            name = build.get("name")
            if not name:
                continue
            sdk_append = list(build.get("sdkconfig_append", []))
            symbol = _resolve_board_symbol(board_dir, target, sdk_append)
            if symbol is None:
                continue
            full_name = f"{manufacturer}-{name}" if manufacturer else name
            variants.append(
                BoardVariant(
                    board_dir=board_dir,
                    name=name,
                    full_name=full_name,
                    target=target,
                    kconfig_symbol=symbol,
                    sdkconfig_append=sdk_append,
                    pinned_partition=_extract_partition_from_append(sdk_append),
                )
            )

    return variants


# ===========================================================================
# Server provider catalog
# ===========================================================================
#
# When the user opts to bootstrap a local xiaozhi-esp32-server checkout, we
# read its config.yaml as the source of truth: every key under `LLM:`, `ASR:`,
# etc. is a selectable provider, and the leaf string fields under each provider
# are the prompts we'll re-ask the user for. We never hardcode the catalog —
# that way new providers added to the server show up here automatically.


def _load_server_config(server_repo: Path) -> dict[str, Any]:
    cfg_path = server_repo / "main" / "xiaozhi-server" / "config.yaml"
    if not cfg_path.exists():
        _abort(
            f"Server config.yaml not found at {cfg_path}.\n"
            "Pass the path to a xiaozhi-esp32-server checkout."
        )
    return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}


def _list_providers(server_cfg: dict[str, Any], kind: str) -> list[str]:
    block = server_cfg.get(kind)
    if not isinstance(block, dict):
        return []
    return list(block.keys())


def _provider_default_block(server_cfg: dict[str, Any], kind: str, name: str) -> dict[str, Any]:
    block = server_cfg.get(kind, {}).get(name, {})
    return dict(block) if isinstance(block, dict) else {}


def _looks_like_secret(field_name: str) -> bool:
    return bool(SECRET_FIELD_RE.search(field_name))


def _looks_like_placeholder(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return bool(PLACEHOLDER_VALUE_RE.match(value.strip()))


def _ota_url(base: str) -> str:
    base = base.rstrip("/")
    if base.endswith("/xiaozhi/ota"):
        return base + "/"
    if "/xiaozhi/ota/" in base:
        return base if base.endswith("/") else base + "/"
    return f"{base}/xiaozhi/ota/"


def _websocket_url_from_base(base: str) -> str:
    """Best-effort derivation of the websocket URL from an HTTP(S) base."""
    base = base.rstrip("/")
    if base.startswith("https://"):
        host = base[len("https://"):]
        scheme = "wss"
    elif base.startswith("http://"):
        host = base[len("http://"):]
        scheme = "ws"
    else:
        host = base
        scheme = "ws"
    # Strip the simplified-deploy http_port (8003) and use the WS port (8000).
    if host.endswith(":8003"):
        host = host[: -len(":8003")] + ":8000"
    return f"{scheme}://{host}/xiaozhi/v1/"


def _ping_ota(url: str, timeout: float = 2.0) -> Optional[dict[str, Any]]:
    """GET the OTA endpoint and parse its JSON. Return None on any failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "xiaozhi-setup/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError):
        return None


# ===========================================================================
# Wizard steps
# ===========================================================================


@dataclass
class IdfEnv:
    root: Optional[Path] = None
    export_script: Optional[Path] = None
    already_sourced: bool = False

    def is_ready(self) -> bool:
        return self.already_sourced or (
            self.export_script is not None and self.export_script.exists()
        )


def _export_script_for(root: Path) -> Path:
    return root / ("export.bat" if os.name == "nt" else "export.sh")


def _install_script_for(root: Path) -> Path:
    return root / ("install.bat" if os.name == "nt" else "install.sh")


def _detect_idf_env() -> Optional[IdfEnv]:
    """Locate ESP-IDF without requiring the user to source anything."""
    # 1. Already sourced — idf.py is on PATH.
    if shutil.which("idf.py") is not None:
        idf_path = os.environ.get("IDF_PATH")
        root = Path(idf_path) if idf_path else None
        export = _export_script_for(root) if root else None
        return IdfEnv(root=root, export_script=export, already_sourced=True)

    # 2. $IDF_PATH points somewhere with a usable export script.
    idf_path = os.environ.get("IDF_PATH")
    if idf_path:
        root = Path(idf_path).expanduser()
        export = _export_script_for(root)
        if export.exists():
            return IdfEnv(root=root, export_script=export)

    # 3. Fall back to well-known install locations.
    for root in COMMON_IDF_LOCATIONS:
        export = _export_script_for(root)
        if export.exists():
            return IdfEnv(root=root, export_script=export)

    return None


def _run_shell(cmd: list[str], dry_run: bool, cwd: Optional[Path] = None) -> None:
    pretty = " ".join(shlex.quote(c) for c in cmd)
    print(f"\n$ {pretty}")
    if dry_run:
        return
    completed = subprocess.run(cmd, cwd=cwd)
    if completed.returncode != 0:
        _abort(f"Command failed (exit {completed.returncode}): {pretty}")


def _install_idf(dry_run: bool, default_target: Optional[str]) -> IdfEnv:
    """Interactively clone ESP-IDF and run install.sh, returning a ready IdfEnv."""
    path_str = _ask_text(
        "Install ESP-IDF to",
        default=str(DEFAULT_IDF_INSTALL_PATH),
        validate=lambda v: len(v.strip()) > 0 or "Required",
    )
    version = _ask_text("ESP-IDF version tag", default=DEFAULT_IDF_VERSION)
    default_targets = default_target if default_target else "all"
    targets = _ask_text(
        "Install toolchains for which targets (comma-separated, or 'all')",
        default=default_targets,
    ).strip() or "all"

    root = Path(path_str).expanduser().resolve()
    export = _export_script_for(root)

    if not (root / ".git").exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        _run_shell(
            [
                "git",
                "clone",
                "--branch",
                version,
                "--recursive",
                "--shallow-submodules",
                "--depth",
                "1",
                "https://github.com/espressif/esp-idf.git",
                str(root),
            ],
            dry_run=dry_run,
        )
    else:
        print(f"[info] ESP-IDF already present at {root}, skipping clone.")

    install_script = _install_script_for(root)
    if install_script.exists() or dry_run:
        _run_shell([str(install_script), targets], dry_run=dry_run, cwd=root)
    else:
        _abort(f"Install script not found at {install_script}")

    if not dry_run and not export.exists():
        _abort(f"Expected export script not found at {export} after install.")

    return IdfEnv(root=root, export_script=export)


def _ensure_idf_env(dry_run: bool, default_target: Optional[str]) -> IdfEnv:
    env = _detect_idf_env()

    if env is not None and env.is_ready():
        source = (
            "idf.py on PATH (already sourced)"
            if env.already_sourced
            else f"auto-detected at {env.root}"
        )
        print(f"[info] ESP-IDF: {source}")
        return env

    print(
        "ESP-IDF was not found on PATH, in $IDF_PATH, or in any of:\n  "
        + "\n  ".join(str(p) for p in COMMON_IDF_LOCATIONS)
    )

    if os.name == "nt":
        print(
            "Automated install is not supported on native Windows yet. "
            "Use the ESP-IDF installer (https://dl.espressif.com/dl/esp-idf/) "
            "or run the wizard from MSYS2/WSL.",
            file=sys.stderr,
        )
        _abort("Cannot continue without ESP-IDF.")

    if dry_run:
        print("[dry-run] would offer to install ESP-IDF into "
              f"{DEFAULT_IDF_INSTALL_PATH} (version {DEFAULT_IDF_VERSION})")
        return IdfEnv()

    if not _ask_confirm("Install ESP-IDF now?", default=True):
        _abort(
            "Cannot continue without ESP-IDF. Install manually and retry:\n"
            "  https://docs.espressif.com/projects/esp-idf/en/stable/esp32/get-started/"
        )

    return _install_idf(dry_run=dry_run, default_target=default_target)


def _ask_select(message: str, choices: list[Any], default: Any = None) -> Any:
    answer = questionary.select(message, choices=choices, default=default).ask()
    if answer is None:
        _abort("Aborted.", code=130)
    return answer


def _ask_text(message: str, default: str = "", validate=None) -> str:
    answer = questionary.text(message, default=default or "", validate=validate).ask()
    if answer is None:
        _abort("Aborted.", code=130)
    return answer


def _ask_password(message: str) -> str:
    answer = questionary.password(message).ask()
    if answer is None:
        _abort("Aborted.", code=130)
    return answer


def _ask_confirm(message: str, default: bool = True) -> bool:
    answer = questionary.confirm(message, default=default).ask()
    if answer is None:
        _abort("Aborted.", code=130)
    return answer


def _step_pick_target(state: WizardState) -> None:
    state.target = _ask_select(
        "MCU target",
        choices=TARGETS,
        default=state.target if state.target in TARGETS else "esp32s3",
    )


def _step_pick_board(state: WizardState) -> None:
    assert state.target is not None
    variants = [v for v in _collect_board_variants() if v.target == state.target]
    if not variants:
        _abort(f"No boards registered for target {state.target}.")

    choices = [
        Choice(title=f"{v.full_name}  [{v.board_dir}]", value=v.full_name)
        for v in variants
    ]
    default = state.board_dir if any(v.full_name == state.board_dir for v in variants) else None
    pick = _ask_select(f"Board ({len(variants)} compatible with {state.target})", choices=choices, default=default)
    chosen = next(v for v in variants if v.full_name == pick)
    state.board_dir = chosen.full_name
    state.board_symbol = chosen.kconfig_symbol
    if chosen.pinned_partition and not state.partition_csv:
        state.partition_csv = chosen.pinned_partition


def _step_pick_partition(state: WizardState) -> None:
    csvs = sorted(p.name for p in PARTITION_DIR.glob("*.csv"))
    if not csvs:
        _abort(f"No partition CSVs found under {PARTITION_DIR}")

    pretty = [f"partitions/v2/{name}" for name in csvs]
    default = state.partition_csv if state.partition_csv in pretty else "partitions/v2/16m.csv"
    state.partition_csv = _ask_select(
        "Partition table (must match physical flash size)",
        choices=pretty,
        default=default if default in pretty else pretty[0],
    )


def _step_pick_wake_word(state: WizardState) -> None:
    choice = _kconfig_choice_by_name("WAKE_WORD_TYPE")
    options = _filter_options_for_target(choice.options, state.target or "")
    if not options:
        options = choice.options
    pretty = [Choice(title=f"{o.prompt}  [{o.symbol}]", value=o.symbol) for o in options]
    default = state.wake_word if any(o.symbol == state.wake_word for o in options) else None
    state.wake_word = _ask_select("Wake-word implementation", choices=pretty, default=default)

    if state.wake_word == "USE_CUSTOM_WAKE_WORD":
        state.custom_wake_word = _ask_text(
            "Custom wake word (English phrase or pinyin, space-separated)",
            default=state.custom_wake_word or "hi esp",
        )
        state.custom_wake_word_display = _ask_text(
            "Wake-word display text (greeting sent to server)",
            default=state.custom_wake_word_display or "Hi, ESP",
        )
        threshold = _ask_text(
            "Wake-word threshold (1-99, lower = more sensitive)",
            default=str(state.custom_wake_word_threshold or 20),
            validate=lambda v: v.isdigit() and 1 <= int(v) <= 99 or "Enter an integer 1-99",
        )
        state.custom_wake_word_threshold = int(threshold)
    else:
        state.custom_wake_word = None
        state.custom_wake_word_display = None
        state.custom_wake_word_threshold = None


def _step_pick_language(state: WizardState) -> None:
    choice = _kconfig_choice_by_prompt("Default Language")
    pretty = [Choice(title=f"{o.prompt}  [{o.symbol}]", value=o.symbol) for o in choice.options]
    default = state.language if any(o.symbol == state.language for o in choice.options) else "LANGUAGE_EN_US"
    state.language = _ask_select("Device UI language", choices=pretty, default=default)


def _step_pick_wifi_provisioning(state: WizardState) -> None:
    # The provisioning menu is a `menu`, not a `choice`, so the existing
    # parser doesn't return it directly. Hardcode the three known options.
    options = [
        ("USE_HOTSPOT_WIFI_PROVISIONING", "Hotspot (recommended)"),
        ("USE_ACOUSTIC_WIFI_PROVISIONING", "Acoustic (audio signal)"),
        ("USE_ESP_BLUFI_WIFI_PROVISIONING", "ESP BluFi (BLE)"),
    ]
    pretty = [Choice(title=label, value=sym) for sym, label in options]
    default = state.wifi_provisioning if any(s == state.wifi_provisioning for s, _ in options) else "USE_HOTSPOT_WIFI_PROVISIONING"
    state.wifi_provisioning = _ask_select("WiFi provisioning method", choices=pretty, default=default)


def _step_pick_server_url(state: WizardState) -> None:
    base = _ask_text(
        "Server base URL (firmware will hit <base>/xiaozhi/ota/)",
        default=state.server_base_url or "http://192.168.1.10:8003",
    )
    state.server_base_url = base
    ota = _ota_url(base)
    print(f"  → OTA endpoint: {ota}")

    info = _ping_ota(ota)
    if info is None:
        print("  → could not reach OTA endpoint (that's OK if the server isn't running yet).")
    else:
        ws = info.get("websocket", {}).get("url") if isinstance(info.get("websocket"), dict) else info.get("websocket")
        if isinstance(ws, str):
            print(f"  → server reports websocket URL: {ws}")
            state.server_websocket = ws
    if not state.server_websocket:
        state.server_websocket = _websocket_url_from_base(base)
        print(f"  → using derived websocket URL: {state.server_websocket}")


def _step_bootstrap_server(state: WizardState) -> None:
    state.bootstrap_server = _ask_confirm(
        "Also bootstrap a local xiaozhi-esp32-server config (data/.config.yaml)?",
        default=state.bootstrap_server,
    )
    if not state.bootstrap_server:
        state.selected_modules = {}
        state.provider_overrides = {}
        return

    default_path = state.server_repo_path or str((ROOT.parent / "xiaozhi-esp32-server").resolve())
    state.server_repo_path = _ask_text(
        "Path to local xiaozhi-esp32-server checkout",
        default=default_path,
        validate=lambda v: Path(v).expanduser().is_dir() or "Path is not a directory",
    )

    server_cfg = _load_server_config(Path(state.server_repo_path).expanduser())

    state.selected_modules = dict(state.selected_modules)
    state.provider_overrides = dict(state.provider_overrides)

    for kind in PROVIDER_KINDS:
        providers = _list_providers(server_cfg, kind)
        if not providers:
            continue
        default = state.selected_modules.get(kind)
        if default not in providers:
            default = server_cfg.get("selected_module", {}).get(kind, providers[0])
            if default not in providers:
                default = providers[0]
        choice = _ask_select(f"{kind} provider", choices=providers, default=default)
        state.selected_modules[kind] = choice

        block = _provider_default_block(server_cfg, kind, choice)
        previous = state.provider_overrides.get(f"{kind}.{choice}", {})
        new_overrides: dict[str, Any] = {}
        for field_name, default_value in block.items():
            if field_name == "type":
                continue
            if not isinstance(default_value, (str, int, float, bool)) and default_value is not None:
                continue
            previous_value = previous.get(field_name)
            shown_default = previous_value if previous_value is not None else default_value
            needs_user_input = (
                _looks_like_placeholder(default_value)
                or default_value in (None, "")
                or previous_value is not None
            )

            if _looks_like_secret(field_name):
                if not needs_user_input and not _ask_confirm(
                    f"  {kind}.{choice}.{field_name} has a value already; override?", default=False
                ):
                    continue
                value = _ask_password(f"  {kind}.{choice}.{field_name} (input hidden)")
                if value:
                    new_overrides[field_name] = value
                continue

            if needs_user_input:
                value = _ask_text(
                    f"  {kind}.{choice}.{field_name}",
                    default="" if shown_default in (None,) else str(shown_default),
                )
                if value and value != str(default_value):
                    new_overrides[field_name] = _coerce_value(value, default_value)
            elif _ask_confirm(f"  override {kind}.{choice}.{field_name}={default_value!r}?", default=False):
                value = _ask_text(
                    f"  {kind}.{choice}.{field_name}",
                    default=str(default_value),
                )
                if value and value != str(default_value):
                    new_overrides[field_name] = _coerce_value(value, default_value)

        if new_overrides:
            state.provider_overrides[f"{kind}.{choice}"] = new_overrides


def _coerce_value(text: str, original: Any) -> Any:
    if isinstance(original, bool):
        return text.strip().lower() in ("true", "yes", "y", "1", "on")
    if isinstance(original, int):
        try:
            return int(text)
        except ValueError:
            return text
    if isinstance(original, float):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def _step_pick_serial_port(state: WizardState, dry_run: bool) -> None:
    detected: list[str] = []
    if _serial_list_ports is not None:
        detected = [p.device for p in _serial_list_ports.comports()]

    if dry_run and not detected:
        state.serial_port = state.serial_port or "/dev/ttyUSB0"
        return

    if detected:
        choices = [Choice(title=p, value=p) for p in detected] + [Choice(title="Enter manually…", value="__manual__")]
        default = state.serial_port if state.serial_port in detected else detected[0]
        pick = _ask_select("Serial port", choices=choices, default=default)
        if pick == "__manual__":
            state.serial_port = _ask_text("Serial port path", default=state.serial_port or "/dev/ttyUSB0")
        else:
            state.serial_port = pick
    else:
        state.serial_port = _ask_text("Serial port path", default=state.serial_port or "/dev/ttyUSB0")


def _step_confirm(state: WizardState) -> bool:
    print("\n=== Summary ===")
    rows = [
        ("Target", state.target),
        ("Board", state.board_dir),
        ("Board symbol", state.board_symbol),
        ("Partition CSV", state.partition_csv),
        ("Wake word", state.wake_word),
    ]
    if state.wake_word == "USE_CUSTOM_WAKE_WORD":
        rows += [
            ("  custom phrase", state.custom_wake_word),
            ("  display text", state.custom_wake_word_display),
            ("  threshold", state.custom_wake_word_threshold),
        ]
    rows += [
        ("Language", state.language),
        ("WiFi provisioning", state.wifi_provisioning),
        ("Server OTA URL", _ota_url(state.server_base_url or "")),
        ("Server WebSocket", state.server_websocket),
        ("Bootstrap server", "yes" if state.bootstrap_server else "no"),
    ]
    if state.bootstrap_server:
        rows.append(("  server repo", state.server_repo_path))
        for kind, name in state.selected_modules.items():
            rows.append((f"  {kind}", name))
    rows.append(("Serial port", state.serial_port))

    width = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"  {k.ljust(width)} : {v}")
    print()
    return _ask_confirm("Proceed with build and flash?", default=True)


# ===========================================================================
# Executor
# ===========================================================================


def _build_overrides_text(state: WizardState) -> str:
    lines = [
        "# Generated by scripts/setup_and_flash.py — do not edit by hand.",
        "# Composed into SDKCONFIG_DEFAULTS so menuconfig edits still take precedence.",
        "",
    ]
    assert state.board_symbol and state.partition_csv and state.language and state.wake_word and state.wifi_provisioning
    lines.append(f"{state.board_symbol}=y")
    lines.append(f'CONFIG_OTA_URL="{_ota_url(state.server_base_url or "")}"')
    lines.append(f'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="{state.partition_csv}"')

    # Only one option per choice may be set; the others are implicitly =n by Kconfig.
    lines.append(f"CONFIG_{state.language}=y")
    lines.append(f"CONFIG_{state.wake_word}=y")
    lines.append(f"CONFIG_{state.wifi_provisioning}=y")

    if state.wake_word == "USE_CUSTOM_WAKE_WORD":
        if state.custom_wake_word:
            lines.append(f'CONFIG_CUSTOM_WAKE_WORD="{state.custom_wake_word}"')
        if state.custom_wake_word_display:
            lines.append(f'CONFIG_CUSTOM_WAKE_WORD_DISPLAY="{state.custom_wake_word_display}"')
        if state.custom_wake_word_threshold is not None:
            lines.append(f"CONFIG_CUSTOM_WAKE_WORD_THRESHOLD={state.custom_wake_word_threshold}")

    # BluFi requires a handful of selects that Kconfig won't auto-resolve when
    # we inject through SDKCONFIG_DEFAULTS. Mirror release.py's behaviour.
    if state.wifi_provisioning == "USE_ESP_BLUFI_WIFI_PROVISIONING":
        lines.extend(
            [
                "CONFIG_BT_ENABLED=y",
                "CONFIG_BT_BLUEDROID_ENABLED=y",
                "CONFIG_BT_BLE_42_FEATURES_SUPPORTED=y",
                "CONFIG_BT_BLE_50_FEATURES_SUPPORTED=n",
                "CONFIG_BT_BLE_BLUFI_ENABLE=y",
                "CONFIG_MBEDTLS_DHM_C=y",
            ]
        )

    return "\n".join(lines) + "\n"


def _sdkconfig_defaults_chain(target: str) -> str:
    parts = [str((ROOT / "sdkconfig.defaults").resolve())]
    target_specific = ROOT / f"sdkconfig.defaults.{target}"
    if target_specific.exists():
        parts.append(str(target_specific.resolve()))
    parts.append(str(OVERRIDES_PATH.resolve()))
    return ";".join(parts)


def _build_server_config_doc(state: WizardState) -> dict[str, Any]:
    doc: dict[str, Any] = {}
    if state.server_websocket:
        doc.setdefault("server", {})["websocket"] = state.server_websocket
    if state.selected_modules:
        doc["selected_module"] = dict(state.selected_modules)
    for key, overrides in state.provider_overrides.items():
        if not overrides:
            continue
        kind, name = key.split(".", 1)
        doc.setdefault(kind, {}).setdefault(name, {}).update(overrides)
    return doc


def _write_server_overrides(state: WizardState, dry_run: bool) -> Optional[Path]:
    if not state.bootstrap_server or not state.server_repo_path:
        return None

    out_path = (
        Path(state.server_repo_path).expanduser()
        / "main"
        / "xiaozhi-server"
        / "data"
        / ".config.yaml"
    )
    doc = _build_server_config_doc(state)
    rendered = (
        "# Written by xiaozhi-esp32/scripts/setup_and_flash.py.\n"
        "# This file is gitignored and overrides values in config.yaml.\n"
        + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    )

    if dry_run:
        print(f"\n--- would write {out_path} ---")
        print(rendered)
        print("--- end ---\n")
        return out_path

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        backup = out_path.with_suffix(".yaml.bak")
        shutil.copy2(out_path, backup)
        print(f"  → backed up existing config to {backup}")
    out_path.write_text(rendered, encoding="utf-8")
    print(f"  → wrote {out_path}")
    return out_path


def _maybe_clean_build_dir(state: WizardState, dry_run: bool) -> None:
    """ESP-IDF refuses to switch targets inside an existing build dir.

    If the user is reconfiguring for a different target than the previous run,
    delete `build/` (after asking) so set-target succeeds cleanly.
    """
    build_dir = ROOT / "build"
    sdkconfig_path = ROOT / "sdkconfig"
    if not build_dir.exists() and not sdkconfig_path.exists():
        return

    previous_target: Optional[str] = None
    if sdkconfig_path.exists():
        for line in sdkconfig_path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r'CONFIG_IDF_TARGET="?([^"]+)"?', line)
            if m:
                previous_target = m.group(1)
                break

    if previous_target and previous_target != state.target:
        msg = f"Existing build is for {previous_target}; switching to {state.target} requires deleting build/ and sdkconfig."
        print(msg)
        if dry_run:
            return
        if not _ask_confirm("Delete build/ and sdkconfig now?", default=True):
            _abort("Cannot continue with mismatched target.")
        if build_dir.exists():
            shutil.rmtree(build_dir)
        if sdkconfig_path.exists():
            sdkconfig_path.unlink()


def _run_idf(env: IdfEnv, idf_args: list[str], dry_run: bool) -> None:
    """Run `idf.py <args>` through the ESP-IDF environment.

    If ESP-IDF was already sourced into the current shell, invoke idf.py directly.
    Otherwise spawn `bash -c '. export.sh && idf.py …'` so no manual sourcing is needed.
    """
    if env.already_sourced:
        cmd = ["idf.py"] + idf_args
        pretty = " ".join(shlex.quote(c) for c in cmd)
        print(f"\n$ {pretty}")
        if dry_run:
            return
        completed = subprocess.run(cmd, cwd=ROOT)
    else:
        if env.export_script is None:
            if dry_run:
                print("\n$ [no IDF env available in dry-run — would run] idf.py " + " ".join(idf_args))
                return
            _abort("No ESP-IDF environment available — cannot run idf.py.")
        if os.name == "nt":
            inner = (
                f'call "{env.export_script}" && idf.py '
                + subprocess.list2cmdline(idf_args)
            )
            cmd = ["cmd.exe", "/c", inner]
            pretty = inner
        else:
            inner = (
                ". "
                + shlex.quote(str(env.export_script))
                + " && idf.py "
                + " ".join(shlex.quote(a) for a in idf_args)
            )
            cmd = ["bash", "-c", inner]
            pretty = f"bash -c {shlex.quote(inner)}"
        print(f"\n$ {pretty}")
        if dry_run:
            return
        completed = subprocess.run(cmd, cwd=ROOT)

    if completed.returncode != 0:
        _abort(f"idf.py command failed (exit {completed.returncode})")


def _execute(state: WizardState, env: IdfEnv, dry_run: bool) -> None:
    overrides_text = _build_overrides_text(state)
    if dry_run:
        print(f"\n--- would write {OVERRIDES_PATH} ---")
        print(overrides_text)
        print("--- end ---")
    else:
        OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
        OVERRIDES_PATH.write_text(overrides_text, encoding="utf-8")
        print(f"  → wrote {OVERRIDES_PATH}")

    _write_server_overrides(state, dry_run=dry_run)

    _maybe_clean_build_dir(state, dry_run=dry_run)

    chain = _sdkconfig_defaults_chain(state.target or "")
    print(f"\nSDKCONFIG_DEFAULTS chain:\n  {chain}")

    _run_idf(
        env,
        ["-D", f"SDKCONFIG_DEFAULTS={chain}", "set-target", state.target or ""],
        dry_run=dry_run,
    )
    _run_idf(env, ["build"], dry_run=dry_run)

    if state.serial_port:
        try:
            _run_idf(env, ["-p", state.serial_port, "flash", "monitor"], dry_run=dry_run)
        except SystemExit:
            raise
        except KeyboardInterrupt:
            print("\nMonitor exited.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive setup, build, and flash wizard for xiaozhi-esp32."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print all generated artifacts and the commands that would run, then exit.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Prefill prompts with answers from the previous run.",
    )
    args = parser.parse_args()

    state = WizardState.load() if args.resume else WizardState()

    _step_pick_target(state)
    env = _ensure_idf_env(dry_run=args.dry_run, default_target=state.target)

    _step_pick_board(state)
    _step_pick_partition(state)
    _step_pick_wake_word(state)
    _step_pick_language(state)
    _step_pick_wifi_provisioning(state)
    _step_pick_server_url(state)
    _step_bootstrap_server(state)
    _step_pick_serial_port(state, dry_run=args.dry_run)

    if not _step_confirm(state):
        print("Aborted by user.")
        sys.exit(0)

    state.save()
    _execute(state, env, dry_run=args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
