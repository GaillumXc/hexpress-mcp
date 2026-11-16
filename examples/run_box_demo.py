"""Standalone demo of the hexpress-mcp tool chain (no MCP client needed).

Runs the same functions the MCP server exposes, end to end:

    get_status -> inspect_geometry -> generate_conf -> run_mesh

Prerequisites: HEXPRESS/Hybrid 10.1 installed (auto-discovered, or set
HEXPRESS_DIR) with a working license.

Usage:
    python examples/run_box_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hexpress_mcp.server import (
    generate_conf,
    get_status,
    inspect_geometry,
    run_mesh,
)

HERE = Path(__file__).resolve().parent
STL = HERE / "box_demo" / "wing_fuselage.stl"


def call(tool, **kw):
    fn = getattr(tool, "fn", None)
    return json.loads((fn or tool)(**kw))


def main() -> int:
    print("== get_status ==")
    status = call(get_status)
    print("install_dir:", status.get("install_dir"))
    print("license_server_running:", status.get("license_server_running"))
    if not status.get("executables"):
        print("HEXPRESS not found — set HEXPRESS_DIR and retry.")
        return 1

    print("\n== inspect_geometry ==")
    geom = call(inspect_geometry, input_file=str(STL))
    print("solid names:", geom.get("solid_names"))
    names = geom.get("solid_names") or []

    print("\n== generate_conf ==")
    conf = call(generate_conf,
                input_files=[str(STL)],
                output_mesh="demo_output.msh",
                base_h=0.15,
                refinements={"wing": [1, 1]},
                boundary_conditions={n: "SOL" for n in names if n},
                mark_all_outer=True,
                conf_name="box_demo.conf")
    print("conf:", conf["conf_file"])

    print("\n== run_mesh ==")
    result = call(run_mesh, conf_file=conf["conf_file"], timeout=1800)
    counts = result.get("mesh_stats", {}).get("counts", {})
    quality = result.get("mesh_stats", {}).get("quality", {})
    print("cells:", counts.get("cells"), "| vertices:", counts.get("vertices"))
    print("hex/tet/prism/pyramid:",
          counts.get("hexahedrons"), counts.get("tetrahedrons"),
          counts.get("prisms"), counts.get("pyramids"))
    print("max skewness:", quality.get("max_equiangular_skewness"),
          "| overall_time:", quality.get("overall_time"))
    if not counts.get("cells"):
        print("MESHING FAILED — log tail:")
        print(result.get("log_tail"))
        return 1
    print("\nDemo OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
