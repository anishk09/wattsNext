"""
Shared (station, circuit) -> circuit_id crosswalk, built from the asset
tables that carry both fields. Used by build_data.py and
build_risk_model.py so the two scripts can't silently disagree about which
circuit labels are trustworthy.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _dbf import read_dbf

AEP = pathlib.Path(__file__).parent.parent / "aep-data" / "data" / "extracted"

RELIABLE_ASSET_TABLES = {
    "transformer": AEP / "Data2" / "Transformer_Clip.dbf",
    "primary": AEP / "Data1" / "Primary_ExportFeatures.dbf",
    "secondary": AEP / "Data2" / "Secondary_ExportFeatures.dbf",
    "fuse_bank": AEP / "Data1" / "Fuse_Bank_Clip.dbf",
    "recloser_bank": AEP / "Data2" / "Recloser_Bank_Clip.dbf",
    "switch": AEP / "Data2" / "Switch_Clip.dbf",
}


def build_circuit_crosswalk():
    """(station, circuit) -> circuit_id. Returns (crosswalk, ambiguous_pairs).
    A pair is ambiguous when different asset tables disagree on its circuit_id —
    excluded from the crosswalk rather than guessed at."""
    seen = {}
    for path in RELIABLE_ASSET_TABLES.values():
        _, records = read_dbf(path)
        for r in records:
            key = (r.get("aep_statio"), r.get("aep_circui"))
            cid = r.get("circuit_id")
            if not key[0] or not key[1] or not cid:
                continue
            seen.setdefault(key, set()).add(cid)

    crosswalk, ambiguous = {}, []
    for key, cids in seen.items():
        if len(cids) == 1:
            crosswalk[key] = next(iter(cids))
        else:
            ambiguous.append({"station": key[0], "circuit": key[1], "circuit_ids": sorted(cids)})
    return crosswalk, ambiguous
