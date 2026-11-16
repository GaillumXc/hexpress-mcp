import struct

from hexpress_mcp.server import parse_stl_solid_names


def _ascii_stl(*solids: str) -> bytes:
    lines: list[str] = []
    for name in solids:
        lines.append(f"solid {name}")
        lines += [" facet normal 0 0 1", "  outer loop",
                  "   vertex 0 0 0", "   vertex 1 0 0", "   vertex 0 1 0",
                  "  endloop", " endfacet", f"endsolid {name}"]
    return ("\n".join(lines) + "\n").encode("ascii")


def test_parse_ascii_stl_named_solids(tmp_path):
    p = tmp_path / "geo.stl"
    p.write_bytes(_ascii_stl("wing", "fuselage"))
    info = parse_stl_solid_names(p)
    assert info["binary"] is False
    assert info["solid_count"] == 2
    assert info["solid_names"] == ["wing", "fuselage"]


def test_parse_ascii_stl_unnamed_solid(tmp_path):
    p = tmp_path / "geo.stl"
    p.write_bytes(_ascii_stl(""))
    info = parse_stl_solid_names(p)
    assert info["solid_names"] == [""]


def test_parse_binary_stl(tmp_path):
    p = tmp_path / "geo.stl"
    header = b"\x00" * 80
    tri = struct.pack("<12fH", *([0.0] * 12), 0)
    p.write_bytes(header + struct.pack("<I", 3) + tri * 3)
    info = parse_stl_solid_names(p)
    assert info["binary"] is True
    assert info["solid_count"] == 3
    assert info["solid_names"] == ["", "", ""]
