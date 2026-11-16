"""MCP server exposing NUMECA HEXPRESS/Hybrid 10.1 to AI agents.

HEXPRESS ships three automation channels, all used here:

1. ``hexpresshybridx86_64.exe <conf> [-print]`` — headless batch mesher driven
   by a keyword .conf file (the same file the GUI exports as "batch
   configuration"),
2. ``hexpressx86_64.exe -batch -script <script.py>`` — headless Python 2.7
   scripting with the embedded ``HXP`` API (_python/_igg/HXP.py),
3. ``hexpressfileconvertx86_64.exe <in> <out> -print`` — format conversion.

Every tool call spawns a fresh subprocess: no persistent GUI, no license held
between calls. Run ``python -m hexpress_mcp --selftest`` to validate the chain
against your installation before wiring it into an MCP client.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from fastmcp import FastMCP

from .batch import build_conf, build_script_wrapper, parse_mesh_stats, run_exe
from .config import (
    CONF_DIR,
    ENV_VAR,
    LOG_DIR,
    SCRIPT_DIR,
    ensure_runtime_dirs,
    env_for_subprocess,
    get_paths,
    platform_notes,
)

mcp = FastMCP("hexpress-mcp", version="0.1.0")


def _ok(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _err(exc: Exception) -> str:
    return json.dumps({"error": type(exc).__name__, "message": str(exc)},
                      ensure_ascii=False, indent=2)


def _require(paths, key: str) -> Path:
    exe = paths.exes.get(key)
    if exe is None:
        raise FileNotFoundError(
            f"{key} executable not found under {paths.bin64} "
            f"(set {ENV_VAR} to the HEXPRESS install dir)")
    return exe


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@mcp.tool()
def get_status(install_dir: str | None = None) -> str:
    """Probe the environment: HEXPRESS install paths, executables, license
    server state, whether the GUI is running, and platform notes. Call first."""
    try:
        paths = get_paths(install_dir)
        payload = {
            "install_dir": str(paths.install_dir),
            "bin64": str(paths.bin64),
            "executables": {k: str(v) for k, v in sorted(paths.exes.items())},
            "admin_tool": str(paths.admin_tool),
            "license_info": str(paths.license_info),
            "license_server_running": paths.license_running,
            "hexpress_running": paths.running,
            "env_var": ENV_VAR,
            "runtime_dirs": {"confs": str(CONF_DIR), "scripts": str(SCRIPT_DIR),
                             "logs": str(LOG_DIR)},
            "platform_notes": platform_notes(),
        }
        # quick version probe via the viewer's batch mode (validates licensing too)
        if paths.exes:
            try:
                import time
                t0 = time.time()
                res = run_exe([str(paths.exes["view"]), "-batch", "-print"],
                              timeout=90, env=env_for_subprocess(paths))
                payload["version_probe"] = {
                    "elapsed_s": round(time.time() - t0, 1),
                    "returncode": res["returncode"],
                    "timed_out": res["timed_out"],
                    "output_head": "\n".join(res["log_tail"].splitlines()[:15]),
                }
            except Exception as exc:  # probe must never break status
                payload["version_probe"] = {"error": str(exc)}
        return _ok(payload)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# batch mesh generation (hexpresshybridx86_64.exe + .conf)
# ---------------------------------------------------------------------------

@mcp.tool()
def generate_conf(
    input_files: list[str],
    output_mesh: str,
    base_h: float | None = None,
    num_boundary_layers: int | None = None,
    boundary_layer_transition: int | None = None,
    refinements: dict[str, list[int]] | None = None,
    boundary_conditions: dict[str, str] | None = None,
    mark_all_outer: bool = False,
    suppress_prefix: bool = True,
    full_hexa: bool = False,
    exact_meshing: bool = False,
    s2v_mesh: bool = False,
    s2v_surface_only: bool = False,
    extra_lines: list[str] | None = None,
    conf_name: str | None = None,
) -> str:
    """Generate a HEXPRESS batch .conf file (without running it).

    input_files: geometry/mesh inputs (STL, .spb, .CATPart, .igs ...), absolute
    paths recommended.
    output_mesh: output file name, e.g. resultMesh.msh (FNMB mesh) or .spb.gz.
    base_h: base cell size for the octree mesher.
    refinements: {selection_name: [initial_level, min_level]} — LOCALREFINEMENTDEFINITION.
    boundary_conditions: {selection_name: bc_type} — BCDEFINITION (e.g. SOL, INL, OUT, SYM).
    num_boundary_layers: viscous layer count (NUMBNDLAYERS).
    s2v_mesh: surface-to-volume (tet-dominant) mode instead of octree hybrid.
    Returns the written path and the full conf content."""
    try:
        ensure_runtime_dirs()
        content = build_conf(
            input_files=input_files,
            output_mesh=output_mesh,
            base_h=base_h,
            num_boundary_layers=num_boundary_layers,
            boundary_layer_transition=boundary_layer_transition,
            refinements=refinements,
            boundary_conditions=boundary_conditions,
            mark_all_outer=mark_all_outer,
            suppress_prefix=suppress_prefix,
            full_hexa=full_hexa,
            exact_meshing=exact_meshing,
            s2v_mesh=s2v_mesh,
            s2v_surface_only=s2v_surface_only,
            extra_lines=extra_lines,
        )
        name = conf_name or f"mesh_{len(list(CONF_DIR.glob('*.conf'))) + 1}.conf"
        if not name.endswith(".conf"):
            name += ".conf"
        path = CONF_DIR / name
        # hexpresshybridx86_64 parses the conf with the system ANSI codepage
        # (GBK on this machine) — UTF-8 mangles any non-ASCII path inside.
        path.write_text(content, encoding="mbcs")
        return _ok({"conf_file": str(path), "content": content})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def run_mesh(
    conf_file: str,
    np: int = 1,
    timeout: int = 3600,
    install_dir: str | None = None,
) -> str:
    """Run hexpresshybridx86_64.exe on a .conf file (generate a mesh in batch).

    conf_file: path returned by generate_conf (or any HEXPRESS-exported conf).
    np: number of MPI processes (>1 adds -ompi -np N).
    timeout: seconds before the run is killed (default 1 h; big meshes need more).
    Returns returncode, elapsed time, output file info and the log tail."""
    try:
        paths = get_paths(install_dir)
        exe = _require(paths, "hybrid")
        conf = Path(conf_file)
        if not conf.is_file():
            raise FileNotFoundError(conf_file)
        cmd = [str(exe)]
        if np > 1:
            cmd += ["-ompi", "-np", str(np)]
        cmd += [str(conf), "-print"]
        result = run_exe(cmd, timeout=timeout, env=env_for_subprocess(paths),
                         cwd=conf.parent, keep_full_log=True)
        result["mesh_stats"] = parse_mesh_stats(result.pop("log_full", ""))
        out_files = sorted(conf.parent.glob("*.msh*"), key=os.path.getmtime)
        result["output_candidates"] = [
            {"path": str(p), "size_mb": round(p.stat().st_size / 1e6, 2)}
            for p in out_files[-3:]
        ]
        return _ok(result)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# batch Python scripting (hexpressx86_64.exe -batch -script)
# ---------------------------------------------------------------------------

@mcp.tool()
def run_script(
    script_text: str | None = None,
    script_file: str | None = None,
    timeout: int = 900,
    install_dir: str | None = None,
) -> str:
    """Run a Python 2 script inside headless HEXPRESS (-batch -script).

    The script executes with the embedded HXP API preloaded (HXP.open_project,
    HXP.generate_initial_mesh, HXP.insert_viscous_layers, ... — see
    _python/_igg/HXP.py in the install), wrapped so that its stdout (which
    HEXPRESS batch mode otherwise swallows) is captured, and a
    SCRIPT_RETURN_VALUE line — printed as ``print "SCRIPT_RETURN_VALUE", 0`` —
    or 0/1 on success/exception is read back from a result file.
    Provide exactly one of script_text (written to a temp file) or script_file.
    Returns returncode, script_return_value, captured script stdout and the
    process log tail."""
    try:
        if bool(script_text) == bool(script_file):
            raise ValueError("provide exactly one of script_text / script_file")
        paths = get_paths(install_dir)
        exe = _require(paths, "hexpress")
        ensure_runtime_dirs()
        n = len(list(SCRIPT_DIR.glob("*.py"))) + 1
        if script_file:
            script = Path(script_file)
            if not script.is_file():
                raise FileNotFoundError(script_file)
        else:
            script = SCRIPT_DIR / f"script_{n}.py"
            script.write_text("# -*- coding: utf-8 -*-\n" + (script_text or ""),
                              encoding="utf-8")
        log_file = SCRIPT_DIR / f"script_{n}.stdout.log"
        result_file = SCRIPT_DIR / f"script_{n}.return"
        wrapper = SCRIPT_DIR / f"wrapper_{n}.py"
        wrapper.write_text(
            build_script_wrapper(script.resolve(), log_file.resolve(), result_file.resolve()),
            encoding="utf-8",
        )
        result = run_exe([str(exe), "-batch", "-print", "-script", str(wrapper)],
                         timeout=timeout, env=env_for_subprocess(paths),
                         cwd=script.parent)
        result["script_stdout"] = (
            log_file.read_text(encoding="gbk", errors="replace")
            if log_file.is_file() else None)
        if result_file.is_file():
            result["script_return_value"] = int(result_file.read_text().strip())
        return _ok(result)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# file conversion (hexpressfileconvertx86_64.exe)
# ---------------------------------------------------------------------------

@mcp.tool()
def convert_file(
    input_file: str,
    output_file: str,
    timeout: int = 300,
    install_dir: str | None = None,
) -> str:
    """Convert between mesh/geometry formats (hexpressfileconvertx86_64.exe).

    e.g. .spb -> .msh, .spb.gz -> .cgns ... Formats are inferred from the
    extensions. Returns returncode and the log tail."""
    try:
        paths = get_paths(install_dir)
        exe = _require(paths, "fileconvert")
        src, dst = Path(input_file), Path(output_file)
        if not src.is_file():
            raise FileNotFoundError(input_file)
        result = run_exe([str(exe), str(src), str(dst), "-print"],
                         timeout=timeout, env=env_for_subprocess(paths),
                         cwd=src.parent)
        result["output"] = {
            "path": str(dst),
            "exists": dst.is_file(),
            "size_mb": round(dst.stat().st_size / 1e6, 2) if dst.is_file() else None,
        }
        return _ok(result)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# CAD conversion (workaround for hexpresshybridx86_64 crashing on newer
# Parasolid transmits — its CAD bridge is older than hexpressx86_64's)
# ---------------------------------------------------------------------------

CAD_CONVERT_TEMPLATE = """\
igg_script_version(2.1)
HXP.import_parasolid({src!r})
HXP.export_parasolid({dst!r})
print "SCRIPT_RETURN_VALUE", 0
"""


@mcp.tool()
def convert_cad(
    input_file: str,
    output_file: str | None = None,
    timeout: int = 600,
    install_dir: str | None = None,
) -> str:
    """Re-export a Parasolid CAD file through the HEXPRESS GUI kernel.

    hexpresshybridx86_64.exe (batch mesher) can segfault (0xC0000005) reading
    newer Parasolid transmits that hexpressx86_64.exe imports fine — passing
    the file through this converter (import + export) produces a byte-level
    V32-era transmit the batch mesher digests. Also useful to bake/validate
    any Parasolid .x_t/.x_b before meshing. Output defaults to
    <input>_v32.X_T next to the input. Returns the exported path."""
    try:
        src = Path(input_file)
        if not src.is_file():
            raise FileNotFoundError(input_file)
        if src.suffix.lower() not in (".x_t", ".x_b"):
            raise ValueError(f"unsupported extension {src.suffix!r} — "
                             "convert_cad handles Parasolid .x_t/.x_b")
        dst = Path(output_file) if output_file else src.with_name(src.stem + "_v32.X_T")
        script = CAD_CONVERT_TEMPLATE.format(src=str(src), dst=str(dst))
        result = json.loads(run_script(script_text=script, timeout=timeout,
                                       install_dir=install_dir))
        result["exported"] = {
            "path": str(dst),
            "exists": dst.is_file(),
            "size_kb": round(dst.stat().st_size / 1024, 1) if dst.is_file() else None,
        }
        return _ok(result)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# geometry inspection (find real selection names before writing a conf)
# ---------------------------------------------------------------------------

def parse_stl_solid_names(path: Path, encoding: str = "gbk") -> dict:
    """Extract solid names from an ASCII STL.

    hexpresshybridx86_64 groups STL triangles by the file's solid names and
    exposes those names as selections (LOCALREFINEMENTDEFINITION /
    BCDEFINITION). Binary STL stores no names — those report as "".
    """
    text = path.read_bytes().decode(encoding, errors="replace")
    names: list[str] = []
    binary = True
    if "facet" in text or "endsolid" in text:
        binary = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("solid "):
                names.append(stripped[len("solid "):].strip())
            elif stripped == "solid":
                names.append("")
    else:
        # binary STL: 80-byte header, uint32 triangle count, 50-byte records
        import struct

        data = path.read_bytes()
        if len(data) >= 84:
            count = struct.unpack("<I", data[80:84])[0]
            if 84 + 50 * count <= len(data):
                names = [""] * count
    return {"solid_names": names, "solid_count": len(names), "binary": binary}


@mcp.tool()
def inspect_geometry(
    input_file: str,
    import_mode: int = 2,
    timeout: int = 300,
    install_dir: str | None = None,
) -> str:
    """Report the selection names a geometry file will produce for
    BCDEFINITION / LOCALREFINEMENTDEFINITION in a batch conf.

    For .stl: reads the solid names directly (hexpresshybridx86_64 groups
    triangles by STL solid name — import_mode 2, the default). Empty-string
    names mean a binary STL (no names stored) — use feature grouping
    (import_mode 1) there and discover TMP-style names from the mesh log.
    For .spb/.igg project files the names live inside the project; open it in
    the GUI once or query via run_script. Non-STL inputs raise an error."""
    try:
        src = Path(input_file)
        if not src.is_file():
            raise FileNotFoundError(input_file)
        if src.suffix.lower() != ".stl":
            raise ValueError(f"unsupported extension {src.suffix!r} — "
                             "inspect_geometry currently handles .stl")
        return _ok({"input_file": str(src), "import_mode": import_mode,
                    **parse_stl_solid_names(src)})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# GUI launch
# ---------------------------------------------------------------------------

@mcp.tool()
def launch_gui(install_dir: str | None = None) -> str:
    """Start the interactive HEXPRESS GUI (hexpressx86_64.exe), detached."""
    try:
        paths = get_paths(install_dir)
        exe = _require(paths, "hexpress")
        subprocess.Popen([str(exe)], env=env_for_subprocess(paths), cwd=paths.bin64,
                         close_fds=True)
        return _ok({"launched": str(exe)})
    except Exception as exc:
        return _err(exc)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
