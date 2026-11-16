"""Error-path and boundary tests for the MCP tool layer.

These tests never touch a HEXPRESS installation: they exercise argument
validation, missing files, and the subprocess timeout logic only.
"""

import json
import sys

from hexpress_mcp.batch import run_exe
from hexpress_mcp.server import (
    convert_cad,
    convert_file,
    generate_conf,
    inspect_geometry,
    run_mesh,
    run_script,
)


def _call(tool, **kw):
    fn = getattr(tool, "fn", None)
    return json.loads((fn or tool)(**kw))


def test_inspect_geometry_missing_file(tmp_path):
    r = _call(inspect_geometry, input_file=str(tmp_path / "nope.stl"))
    assert r["error"] == "FileNotFoundError"


def test_inspect_geometry_bad_extension(tmp_path):
    p = tmp_path / "geo.step"
    p.write_text("dummy")
    r = _call(inspect_geometry, input_file=str(p))
    assert r["error"] == "ValueError"
    assert "unsupported extension" in r["message"]


def test_convert_cad_bad_extension(tmp_path):
    p = tmp_path / "geo.stl"
    p.write_text("dummy")
    r = _call(convert_cad, input_file=str(p))
    assert r["error"] == "ValueError"


def test_run_script_requires_exactly_one_source():
    r = _call(run_script)
    assert r["error"] == "ValueError"
    r = _call(run_script, script_text="x", script_file="y.py")
    assert r["error"] == "ValueError"


def test_run_script_missing_file():
    r = _call(run_script, script_file=r"C:\does\not\exist.py")
    assert r["error"] == "FileNotFoundError"


def test_run_mesh_missing_conf():
    r = _call(run_mesh, conf_file=r"C:\does\not\exist.conf")
    assert r["error"] == "FileNotFoundError"


def test_convert_file_missing_input():
    r = _call(convert_file, input_file=r"C:\does\not\exist.stl",
              output_file=r"C:\out.msh")
    assert r["error"] == "FileNotFoundError"


def test_generate_conf_roundtrip(tmp_path, monkeypatch):
    import hexpress_mcp.server as srv

    monkeypatch.setattr(srv, "CONF_DIR", tmp_path)
    r = _call(generate_conf, input_files=["a.stl"], output_mesh="o.msh",
              base_h=0.1, conf_name="t.conf")
    assert r["conf_file"] == str(tmp_path / "t.conf")
    written = (tmp_path / "t.conf").read_text(encoding="utf-8")
    assert "BASEH 0.1" in written and written.rstrip().endswith("END")


def test_run_exe_timeout():
    r = run_exe([sys.executable, "-c", "import time; time.sleep(10)"],
                timeout=1)
    assert r["timed_out"] is True
    assert r["returncode"] is None


def test_run_exe_captures_failure():
    r = run_exe([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=30)
    assert r["timed_out"] is False
    assert r["returncode"] == 3
