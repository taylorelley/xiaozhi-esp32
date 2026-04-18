#!/usr/bin/env python3
"""Regenerate scripts/server_providers.snapshot.yaml from a xiaozhi-esp32-server checkout.

The wizard (`scripts/setup_and_flash.py`) offers provider selections even when
the user has no local server checkout on disk. It does that by loading a
snapshot of the server's `config.yaml` that we ship inside the wizard. This
script rebuilds that snapshot so it tracks upstream provider changes.

Usage:
    python scripts/update_provider_snapshot.py                      # defaults to ../xiaozhi-esp32-server
    python scripts/update_provider_snapshot.py /path/to/server-repo
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError as e:
    sys.exit(f"PyYAML is required: {e}")


PROVIDER_KEYS = ["selected_module", "VAD", "ASR", "LLM", "VLLM", "TTS", "Memory", "Intent"]
HEADER = (
    "# Snapshot of the provider sections of xiaozhi-esp32-server/main/xiaozhi-server/config.yaml.\n"
    "# Consumed by scripts/setup_and_flash.py when no local server checkout is supplied.\n"
    "# Regenerate by running scripts/update_provider_snapshot.py after the server's config.yaml changes.\n"
)


def main(argv: list[str]) -> int:
    script_dir = Path(__file__).resolve().parent
    firmware_root = script_dir.parent
    default_server_repo = (firmware_root.parent / "xiaozhi-esp32-server").resolve()
    server_repo = Path(argv[1]).expanduser().resolve() if len(argv) > 1 else default_server_repo

    cfg_path = server_repo / "main" / "xiaozhi-server" / "config.yaml"
    if not cfg_path.exists():
        sys.exit(f"Could not find server config at {cfg_path}")

    src = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    snapshot = {k: src[k] for k in PROVIDER_KEYS if k in src}

    rendered = HEADER + yaml.safe_dump(
        snapshot, sort_keys=False, allow_unicode=True, width=200
    )
    out_path = script_dir / "server_providers.snapshot.yaml"
    out_path.write_text(rendered, encoding="utf-8")
    print(f"Wrote {out_path} ({out_path.stat().st_size} bytes) from {cfg_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
