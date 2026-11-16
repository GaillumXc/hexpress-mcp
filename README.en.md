# hexpress-mcp

[中文 README](README.md) | English

An MCP (Model Context Protocol) server that exposes **NUMECA HEXPRESS/Hybrid 10.1**
mesh generation to AI agents (Kimi Code, Claude, Cursor, ...).

HEXPRESS ships no modern automation API, so this server drives the three batch
channels the installer actually contains — **no GUI automation, no display
dependency, no license seat held between calls**:

1. **Batch mesher** — `hexpresshybridx86_64.exe <conf> [-print]`, driven by a
   keyword `.conf` file (the same file the GUI exports as "batch
   configuration"): octree hybrid / S2V surface meshes, MPI parallel;
2. **Batch Python** — `hexpressx86_64.exe -batch -script <script.py>`: headless
   Python 2.7 with the embedded `HXP` API (CAD import/export, geometry
   queries, booleans, full mesh-generation chain);
3. **File converter** — `hexpressfileconvertx86_64.exe <in> <out> -print`.

> [!IMPORTANT]
> **Unofficial project, not affiliated with Siemens Digital Industries Software
> (formerly NUMECA).** This repository contains and distributes **no** HEXPRESS
> software, libraries or data. A **legally installed** HEXPRESS/Hybrid 10.1 with
> a working license on the same machine is required at runtime; please comply
> with your license agreement.

## Features

- 8 MCP tools covering the whole meshing workflow: probe → inspect → CAD
  convert → conf → mesh (with MPI) → statistics
- `run_mesh` parses **cell counts and quality metrics** (negative Jacobians,
  skewness, edge lengths, timings) from the log into structured JSON
- One subprocess per tool call: crashes don't propagate, nothing stays resident
- Tools never raise — all errors return as JSON the agent can read and act on
- Battle-tested: box STL, a two-solid wing+fuselage (named selections + BCs
  verified in the Fluent output), and a **3.6 m fixed-wing UAV (SolidWorks 2023,
  Parasolid V34) meshed to 46,489 hybrid cells**

## Install

```bash
uv venv --python 3.11 .venv
uv pip install -e .          # or: uv pip install .
python -m hexpress_mcp --selftest   # probe the local HEXPRESS install + license
```

Requires: Python ≥ 3.11, [FastMCP](https://github.com/jlowin/fastmcp) ≥ 2.0,
Windows (tested on Windows 10/11; HEXPRESS itself ships Win/Linux x86_64).

## Wiring into MCP clients

### Kimi Code (`~/.kimi-code/mcp.json`, user level)

```json
"hexpress": {
  "command": "D:\\path\\to\\hexpress-mcp\\.venv\\Scripts\\python.exe",
  "args": ["-m", "hexpress_mcp"],
  "cwd": "D:\\path\\to\\hexpress-mcp",
  "env": {
    "PYTHONPATH": "D:\\path\\to\\hexpress-mcp\\src",
    "PYTHONUTF8": "1",
    "HEXPRESS_DIR": "C:\\NUMECA_SOFTWARE\\hexpress101"
  }
}
```

`HEXPRESS_DIR` is optional — the server auto-discovers
`C:\NUMECA_SOFTWARE\hexpress*\bin64\hexpressx86_64.exe` and caches it in
`%APPDATA%\hexpress-mcp\config.json`.

### Claude Desktop / any stdio MCP client

```json
{
  "mcpServers": {
    "hexpress": {
      "command": "D:\\path\\to\\hexpress-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "hexpress_mcp"],
      "env": { "PYTHONPATH": "D:\\path\\to\\hexpress-mcp\\src", "HEXPRESS_DIR": "C:\\NUMECA_SOFTWARE\\hexpress101" }
    }
  }
}
```

## Tools

| Tool | What it does |
| --- | --- |
| `get_status` | install paths, the 6 executables, license-server state, version probe (`hexpressview -batch -print`), whether the GUI is running |
| `inspect_geometry` | parse solid names from an STL (== the selection names the batch mesher will create) — look up real names **before** writing a conf |
| `convert_cad` | re-export `.x_t`/`.x_b` through the GUI kernel's Parasolid bridge — **fixes the batch mesher segfaulting (0xC0000005) on newer Parasolid transmits** |
| `generate_conf` | write a batch `.conf` (BASEH, refinement, BCs, viscous layers, S2V; written in the system ANSI codepage so Chinese paths survive) |
| `run_mesh` | run `hexpresshybridx86_64.exe` on a conf, optional MPI via `np`; returns structured `mesh_stats` + log tail |
| `run_script` | run a Python 2 script under `-batch -script` (full `HXP` API); a wrapper captures the stdout HEXPRESS swallows and returns `SCRIPT_RETURN_VALUE` |
| `convert_file` | mesh/geometry format conversion (`hexpressfileconvertx86_64.exe`) |
| `launch_gui` | start the interactive GUI, detached |

Typical flow: `get_status` → `inspect_geometry` / `convert_cad` → `generate_conf`
→ `run_mesh` → read `mesh_stats`.

> [!WARNING]
> `returncode: 0` from `run_mesh` is **not** proof of success — NUMECA's
> `commAbort` still exits 0. Judge by a non-empty `mesh_stats.counts.cells`
> and the absence of `Error:` lines in the log tail. The tools cannot judge
> whether a mesh meets your engineering requirements; that responsibility
> stays with you.

## Worked examples

### 1. STL with named solids + boundary conditions

```python
inspect_geometry(input_file=r"D:\geo\wing_fuselage.stl")
# → {"solid_names": ["wing", "fuselage"], ...}

generate_conf(
    input_files=[r"D:\geo\wing_fuselage.stl"],
    output_mesh="wingFuselageMesh.msh",
    base_h=0.15,
    refinements={"wing": [1, 1]},
    boundary_conditions={"wing": "SOL", "fuselage": "SOL"},
    mark_all_outer=True)

run_mesh(conf_file=r"...\confs\wing_fuselage.conf")
```

The exported Fluent mesh contains `wall wing` / `wall fuselage` zones — the
BCs really land in the output. A complete runnable demo lives in
[`examples/box_demo/`](examples/box_demo) (geometry generator included).

### 2. Parasolid full-aircraft model from SolidWorks/CATIA

```python
# 0. If the raw x_t segfaults the batch mesher (common with V33+ transmits), re-export
convert_cad(input_file=r"D:\cad\uav.x_t")   # → uav_v32.X_T

# 1. pick base_h from the smallest feature (see Troubleshooting: Surface Smoother
#    failure almost always means base_h is too coarse)
generate_conf(input_files=[r"D:\cad\uav_v32.X_T"],
              output_mesh="uav.msh", base_h=0.02, mark_all_outer=True)
run_mesh(conf_file=r"...\confs\mesh.conf", np=8)   # MPI on 8 ranks
```

Measured on a 3.6 m fixed-wing with 2 mm thin features: `base_h=0.02` →
46,489 cells (64% hexahedra), max skewness 0.91, 14 s wall.

### 3. HXP API scripts (Python 2 syntax!)

Scripts passed to `run_script` execute on HEXPRESS's embedded **Python 2.7**
with the `HXP` module preloaded:

```python
igg_script_version(2.1)
HXP.import_parasolid(r"C:\work\geom.x_t")
for b in get_all_bodies():
    print b.get_name(), "faces:", b.num_faces(), "healthy:", b.check()
HXP.export_parasolid(r"C:\work\geom_reexported.x_t")
print "SCRIPT_RETURN_VALUE", 0
```

- stdout/stderr are captured by the wrapper and returned (HEXPRESS batch mode
  swallows them otherwise)
- `print "SCRIPT_RETURN_VALUE", 0` is the explicit success signal; when absent
  the exit value is 0 on clean run / 1 on exception

## .conf keyword reference (from the installer's own test suite)

```
INFILENAMES            <count>, then one path per line
OUTFILENAME            <name>          (resultMesh.msh / out.spb.gz ...)
BASEH                  <cell size>     (octree base — MUST resolve the smallest feature!)
SUPPRESSPREFIX / MARKALLOUTER / EXACTMESHING / GENERATEFULLHEXAMESH
NUMBNDLAYERS           <n>             (viscous layers)
BNDLAYERTRANSITION     <0|1>
LOCALREFINEMENTDEFINITION <name> <initial_level> <min_level>
BCDEFINITION           <name> <type>   (SOL / INL / OUT / SYM ...)
GENERATES2VMESH                        (surface-to-volume mode)
S2VPARAM GENERATESURFACEMESH MIXED     (surface mesh only)
CADIMPORTPARAM MEDIUM                  (COARSE/FINE are rejected by 10.1)
CREATEALLEDGESFROMMODEL NOPREFIX
USEBINFILEVERSION 11
END
```

Anything not listed goes through `extra_lines` verbatim. More sample confs ship
with the installer under
`C:\NUMECA_SOFTWARE\hexpress101\_python\_tests_db\_installations\hexpress\`.

## Troubleshooting (every row is a real hit from testing)

| Symptom | Cause & fix |
| --- | --- |
| `returncode 3221225477` (0xC0000005) | batch mesher crashes on newer Parasolid transmits → run `convert_cad` first |
| `Surface Smoother failed ... geometry might be open` | almost always **base_h too coarse** for thin features. Use ~1/5–1/10 of the smallest feature; 0.02 is a good first guess for small-UAV geometry |
| `Warning: ... does not contain any selection which corresponds to: X` | conf references a name the geometry doesn't have → `inspect_geometry` (STL) or check face names in your CAD tool (Parasolid) |
| batch script "fails silently", zero output | Py2 encoding: non-ASCII content (e.g. Chinese paths) needs `# -*- coding: utf-8 -*-` (`run_script` adds it automatically); syntax must be Python 2 |
| Chinese paths garbled in conf, "file not present" | `hexpresshybridx86_64` parses the conf with the system ANSI codepage — `generate_conf` already writes `mbcs`; when hand-editing, save as ANSI/GBK |
| license errors from `run_mesh` | FLEXlm service not running: as admin run `C:\NUMECA_SOFTWARE\NUMECA_License_Server*\server_install.bat` |
| MPI (`np>1`) misbehaves | check the `pvm/` dir in the install; `-ompi -np N` needs working host name resolution |

## Development

```bash
uv pip install pytest ruff
ruff check src tests
pytest
python -m hexpress_mcp --selftest
```

- `tests/` never touch a HEXPRESS install (pure functions + error paths) and
  run on any machine
- runtime data (confs / scripts / logs) lives in `%APPDATA%\hexpress-mcp\`,
  never in the repo
- after adding a tool: edit `server.py` → ruff → pytest → restart the MCP
  client session (stdio servers don't hot-reload)

## Disclaimer

- Independent open-source work, **not affiliated with, endorsed by, or
  supported by** Siemens/NUMECA
- HEXPRESS, FINE, NUMECA and their logos are trademarks of their respective
  owners
- Released under the MIT License; the terms of your commercial HEXPRESS
  license remain between you and the software vendor

## Sister projects

- `xflr5-mcp` — MCP server for XFLR5 airfoil/wing analysis (same author)
- `profili-mcp` — MCP server for the Profili airfoil library
