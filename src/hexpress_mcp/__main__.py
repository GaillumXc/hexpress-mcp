"""Entry point: ``python -m hexpress_mcp`` serves the MCP over stdio.

``python -m hexpress_mcp --selftest`` instead runs a non-destructive probe of
the local HEXPRESS installation and prints a JSON report (exit code 0 = usable).
"""

from __future__ import annotations

import json
import sys


def _selftest() -> int:
    from .batch import build_conf, parse_script_return
    from .config import get_paths, platform_notes

    report: dict = {"platform_notes": platform_notes()}
    paths = get_paths()
    report["install_dir"] = str(paths.install_dir)
    report["executables"] = {k: str(v) for k, v in sorted(paths.exes.items())}
    report["license_server_running"] = paths.license_running
    if not paths.exes:
        report["error"] = "HEXPRESS install not found"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    conf = build_conf(input_files=["/tmp/geometry.stl"], output_mesh="out.msh",
                      base_h=0.1, num_boundary_layers=3,
                      refinements={"wing": [1, 1]}, boundary_conditions={"inlet": "INL"})
    report["conf_generation"] = "ok" if conf.rstrip().endswith("END") else "bad"
    report["script_return_parse"] = parse_script_return('xx\nSCRIPT_RETURN_VALUE 0\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    from .server import main as serve

    serve()


if __name__ == "__main__":
    main()
