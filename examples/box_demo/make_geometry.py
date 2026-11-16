"""Generate demo geometry: two named STL solids (wing + fuselage).

Run:  python make_geometry.py
Out:  wing_fuselage.stl  (ASCII STL, solids named 'wing' / 'fuselage')

HEXPRESS imports the solid names as selection names (import mode
STL_IMPORT_GROUP_BY_NAMES = 2), which is what BCDEFINITION and
LOCALREFINEMENTDEFINITION in a batch conf must reference.
"""

from pathlib import Path


def box(name: str, xmin, xmax, ymin, ymax, zmin, zmax) -> list[str]:
    v = {
        "a": (xmin, ymin, zmin), "b": (xmax, ymin, zmin),
        "c": (xmax, ymax, zmin), "d": (xmin, ymax, zmin),
        "e": (xmin, ymin, zmax), "f": (xmax, ymin, zmax),
        "g": (xmax, ymax, zmax), "h": (xmin, ymax, zmax),
    }
    quads = [  # (normal, 4 corner keys)
        ((0, 0, -1), "abcd"), ((0, 0, 1), "efgh"),
        ((-1, 0, 0), "daeh"), ((1, 0, 0), "bcgf"),
        ((0, -1, 0), "abfe"), ((0, 1, 0), "dcgh"),
    ]
    lines = [f"solid {name}"]
    for (nx, ny, nz), keys in quads:
        a, b, c, d = (v[k] for k in keys)
        for tri in ((a, b, c), (a, c, d)):
            lines.append(f" facet normal {nx} {ny} {nz}")
            lines.append("  outer loop")
            for x, y, z in tri:
                lines.append(f"   vertex {x} {y} {z}")
            lines.append("  endloop")
            lines.append(" endfacet")
    lines.append(f"endsolid {name}")
    return lines


def main() -> None:
    wing = box("wing", xmin=-1.0, xmax=1.0, ymin=-0.05, ymax=0.05, zmin=-0.3, zmax=0.3)
    fuselage = box("fuselage", xmin=-2.0, xmax=2.0, ymin=-0.2, ymax=0.2,
                   zmin=-0.2, zmax=0.2)
    out = Path(__file__).parent / "wing_fuselage.stl"
    out.write_text("\n".join(wing + fuselage) + "\n", encoding="ascii")
    print(f"wrote {out} ({len(wing + fuselage)} lines)")


if __name__ == "__main__":
    main()
