"""Locate the HEXPRESS installation and runtime directories.

Resolution order for the install dir:

* explicit argument > ``HEXPRESS_DIR`` env > cached config >
  shallow auto-discovery of ``C:/NUMECA_SOFTWARE/hexpress*/bin64``.

Runtime data (generated .conf files, batch scripts, logs) lives under
``%APPDATA%\\hexpress-mcp``.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "hexpress-mcp"
CONFIG_FILE = CONFIG_DIR / "config.json"
CONF_DIR = CONFIG_DIR / "confs"
SCRIPT_DIR = CONFIG_DIR / "scripts"
LOG_DIR = CONFIG_DIR / "logs"

ENV_VAR = "HEXPRESS_DIR"

EXE_NAMES = {
    "hexpress": "hexpressx86_64.exe",
    "hybrid": "hexpresshybridx86_64.exe",
    "fileconvert": "hexpressfileconvertx86_64.exe",
    "view": "hexpressviewx86_64.exe",
    "datamapper": "hexpressdatamapperx86_64.exe",
    "renderer": "hexpressrendererx86_64.exe",
}


@dataclass(frozen=True)
class HexpressPaths:
    install_dir: Path | None
    bin64: Path | None
    exes: dict[str, Path] = field(default_factory=dict)
    admin_tool: Path | None = None
    license_info: Path | None = None
    license_running: bool | None = None

    @property
    def running(self) -> bool:
        for name in ("hexpressx86_64.exe", "hexpresshybridx86_64.exe"):
            try:
                out = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {name}", "/nh"],
                    capture_output=True, timeout=15, check=False,
                )
                if name.lower() in out.stdout.decode("gbk", "replace").lower():
                    return True
            except Exception:
                continue
        return False


def _cache_read() -> Path | None:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        p = Path(data["install_dir"])
        return p if p.is_dir() else None
    except Exception:
        return None


def _cache_write(install_dir: Path) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps({"install_dir": str(install_dir)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        contextlib.suppress(Exception)  # caching is best-effort only


def _valid_install(p: Path) -> bool:
    return (p / "bin64" / EXE_NAMES["hexpress"]).is_file()


def _discover_install() -> Path | None:
    for root in (Path("C:/NUMECA_SOFTWARE"), Path("D:/NUMECA_SOFTWARE")):
        if not root.is_dir():
            continue
        try:
            for child in sorted(root.iterdir()):
                cand = child if (child / "bin64").is_dir() else child.parent
                if _valid_install(cand):
                    return cand
                # one level deeper, e.g. hexpress101/bin64
                if child.is_dir():
                    for grand in sorted(child.iterdir()):
                        cand2 = grand if (grand / "bin64").is_dir() else grand.parent
                        if _valid_install(cand2):
                            return cand2
        except OSError:
            continue
    return None


def resolve_install_dir(explicit: str | None = None) -> Path | None:
    for cand in (explicit, os.environ.get(ENV_VAR), _cache_read()):
        if cand:
            p = Path(cand)
            if _valid_install(p):
                _cache_write(p)
                return p
            # accept the NUMECA_SOFTWARE root as well
            for sub in sorted(p.glob("hexpress*/")):
                if _valid_install(sub):
                    _cache_write(sub)
                    return sub
    found = _discover_install()
    if found:
        _cache_write(found)
    return found


def get_paths(install_dir: str | None = None) -> HexpressPaths:
    root = resolve_install_dir(install_dir)
    if root is None:
        return HexpressPaths(
            install_dir=None, bin64=None, exes={}, admin_tool=None,
            license_info=None, license_running=None,
        )
    bin64 = root / "bin64"
    exes = {key: bin64 / name for key, name in EXE_NAMES.items() if (bin64 / name).is_file()}
    admin = root / "admin_tool.exe"
    lic = root.parent / "license.info"
    if not lic.is_file():
        lic = None
    return HexpressPaths(
        install_dir=root,
        bin64=bin64,
        exes=exes,
        admin_tool=admin if admin.is_file() else None,
        license_info=lic,
        license_running=_probe_license_server(),
    )


def _probe_license_server() -> bool | None:
    """True if at least one service matching NUMECA/FLEXlm is running."""
    # Windows console tools answer in the OEM/ANSI codepage (GBK here), which
    # breaks under PYTHONUTF8 — decode explicitly and tolerate garbage.
    try:
        out = subprocess.run(
            ["sc", "query", "type=", "service", "state=", "all"],
            capture_output=True, timeout=30, check=False,
        )
        text = out.stdout.decode("gbk", "replace")
        names = [line.split(":", 1)[1].strip() for line in text.splitlines()
                 if line.strip().startswith("SERVICE_NAME")]
        matches = [n for n in names if "numeca" in n.lower() or "flexlm" in n.lower()
                   or "license" in n.lower()]
        if not matches:
            return None
        out2 = subprocess.run(
            ["sc", "query", matches[0]],
            capture_output=True, timeout=15, check=False,
        )
        return "RUNNING" in out2.stdout.decode("gbk", "replace")
    except Exception:
        return None


def ensure_runtime_dirs() -> None:
    for d in (CONF_DIR, SCRIPT_DIR, LOG_DIR):
        with contextlib.suppress(OSError):
            d.mkdir(parents=True, exist_ok=True)


def env_for_subprocess(paths: HexpressPaths) -> dict[str, str]:
    """Environment for spawning NUMECA exes (mirrors what their shortcuts set)."""
    env = dict(os.environ)
    if paths.install_dir:
        env["NUMECA_DIR"] = str(paths.install_dir)
        env["NUMECA_BIN"] = str(paths.install_dir / "bin")
        env["PATH"] = str(paths.bin64) + os.pathsep + env.get("PATH", "")
    return env


def platform_notes() -> list[str]:
    notes = []
    if os.name == "nt":
        notes.append("Windows: exes are x86_64 GUI/batch binaries; batch mode "
                     "(-batch/-script/conf) needs no display interaction.")
        notes.append("The bundled python64/ is Python 2.7 — batch scripts passed "
                     "to -script must be Python 2 syntax.")
    return notes
