from hexpress_mcp.batch import build_conf, parse_script_return


def test_build_conf_basic():
    conf = build_conf(
        input_files=["C:/tmp/geom.stl"],
        output_mesh="out.msh",
        base_h=0.2,
        num_boundary_layers=1,
        refinements={"wing": [0, 1], "body": [1, 2, 3]},
        boundary_conditions={"inlet": "INL", "wall": "SOL"},
        mark_all_outer=True,
    )
    lines = conf.splitlines()
    assert lines[0].startswith("#File generated")
    assert "INFILENAMES" in lines
    i = lines.index("INFILENAMES")
    assert lines[i + 1] == "1"
    assert lines[i + 2] == "C:/tmp/geom.stl"
    assert "OUTFILENAME" in lines
    assert lines[lines.index("OUTFILENAME") + 1] == "out.msh"
    assert "SUPPRESSPREFIX" in lines
    assert "MARKALLOUTER" in lines
    assert "BASEH 0.2" in lines
    assert "NUMBNDLAYERS 1" in lines
    assert "LOCALREFINEMENTDEFINITION wing 0 1" in lines
    assert "LOCALREFINEMENTDEFINITION body 1 2" in lines  # extras ignored beyond 2
    assert "BCDEFINITION inlet INL" in lines
    assert "BCDEFINITION wall SOL" in lines
    assert lines[-1] == "END"


def test_build_conf_multi_input_and_s2v():
    conf = build_conf(
        input_files=["a.stl", "b.stl"],
        output_mesh="out.spb.gz",
        s2v_mesh=True,
        s2v_surface_only=True,
        exact_meshing=True,
        extra_lines=["USEBINFILEVERSION 11"],
    )
    lines = conf.splitlines()
    i = lines.index("INFILENAMES")
    assert lines[i + 1] == "2"
    assert lines[i + 2] == "a.stl"
    assert lines[i + 3] == "b.stl"
    assert "GENERATES2VMESH" in lines
    assert "S2VPARAM GENERATESURFACEMESH MIXED" in lines
    assert "EXACTMESHING" in lines
    assert "USEBINFILEVERSION 11" in lines


def test_build_conf_no_optional_keywords():
    conf = build_conf(input_files=["a.stl"], output_mesh="o.msh")
    for kw in ("BASEH", "NUMBNDLAYERS", "LOCALREFINEMENTDEFINITION", "BCDEFINITION"):
        assert kw not in conf
    assert "SUPPRESSPREFIX" in conf  # on by default


def test_parse_script_return():
    assert parse_script_return("noise\nSCRIPT_RETURN_VALUE 1\n") == 1
    assert parse_script_return("SCRIPT_RETURN_VALUE -3") == -3
    assert parse_script_return("nothing here") is None
    assert parse_script_return(None) is None


SAMPLE_LOG = """
Number of tetrahedrons    950
Number of prisms          1440
Number of cells           4924
Number of vertices        3636
  Minimal edge-length:                      0.0025459
  Average edge-length:                      0.145391
  Maximal edge-length:                      0.492074
  Max equiangular skewness:                 0.997885
  Max adjacent volume ratio:                23.695
  Max expansion ratio:                      19.2242
Overall time 7.822 sec
Overall cpu time 106.266 sec
"""


def test_parse_mesh_stats():
    from hexpress_mcp.batch import parse_mesh_stats

    stats = parse_mesh_stats(SAMPLE_LOG)
    assert stats["counts"]["cells"] == 4924
    assert stats["counts"]["vertices"] == 3636
    assert stats["counts"]["prisms"] == 1440
    assert stats["quality"]["minimal_edge_length"] == 0.0025459
    assert stats["quality"]["max_equiangular_skewness"] == 0.997885
    assert stats["quality"]["overall_time"] == 7.822
    assert parse_mesh_stats("") == {"counts": {}, "quality": {}}


def test_script_wrapper_contains_result_channel():
    from pathlib import Path

    from hexpress_mcp.batch import build_script_wrapper

    w = build_script_wrapper(Path("s.py"), Path("l.log"), Path("r.txt"))
    assert "execfile" in w and "SCRIPT_RETURN_VALUE" in w
    assert "s.py" in w and "l.log" in w and "r.txt" in w
