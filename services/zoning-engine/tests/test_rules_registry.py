"""Regression coverage for Phase 1 of the Cinema_Layout_Notes.pdf work
(2026-09-10): the client's own per-support-zone minimum area figures and
30-40% aggregate support-zone-area target, moved into rules_registry_v1.json
(support_zone_defaults) instead of staying hardcoded in layout_engine.py
(Product Principle #1 — config over code), plus the new
VR_SUPPORT_ZONE_AREA_SHARE viability rule that checks the aggregate figure."""
import feasibility_engine
import layout_engine
import main
import rules_registry

# The client's own hard-limit table, mapped onto the POST-swap room type
# names (FOYER is now the manually-placed room, PASSAGE is now the derived
# leftover-remainder room — see rules_registry_v1.json's support_zone_defaults
# entries for the full 2026-09-10 terminology-swap history).
EXPECTED_MIN_AREAS = {
    "BOX_OFFICE": 50.0,
    "FOYER": 600.0,
    "FNB": 200.0,
    "WASHROOM": 500.0,
    "ELECTRICAL": 100.0,
    "MANAGER_ROOM": 100.0,
    "PROJECTOR": 150.0,
    "STORE_ROOM": 90.0,
    "PASSAGE": 170.0,
}


def test_support_zone_defaults_returns_every_client_sourced_minimum():
    defaults = rules_registry.support_zone_defaults()
    ids = {d["id"] for d in defaults}
    assert set(EXPECTED_MIN_AREAS) <= ids, f"missing ids: {set(EXPECTED_MIN_AREAS) - ids}"
    for room_type, expected_min in EXPECTED_MIN_AREAS.items():
        entry = rules_registry.support_zone_default(room_type)
        assert entry is not None, f"no support_zone_defaults entry for {room_type}"
        assert entry["min_area_sqft"] == expected_min, (
            f"{room_type}: expected min_area_sqft {expected_min}, got {entry['min_area_sqft']}"
        )


def test_support_zone_default_returns_none_for_an_unknown_type():
    assert rules_registry.support_zone_default("NOT_A_REAL_ROOM_TYPE") is None


def test_layout_engine_reads_support_zone_defaults_from_the_registry_not_a_hardcoded_constant():
    """Product Principle #1 (config over code): layout_engine.py must not
    hardcode these figures — _support_zone_default is a thin wrapper over
    rules_registry.support_zone_default, so a registry-only change (no code
    change) must be reflected immediately."""
    entry = layout_engine._support_zone_default("FOYER")
    assert entry is not None
    room_type, display_name, target_area, min_area, note = entry
    assert room_type == "FOYER"
    assert min_area == 600.0


def test_store_room_is_excluded_from_auto_placement_like_electrical_and_projector():
    """STORE_ROOM is new this round (split out of BOH's prior combined
    description) — it should behave like ELECTRICAL/PROJECTOR: a real,
    registry-backed support zone available via manual Add Zone, but not
    auto-placed by the deterministic packer (SUPPORT_ZONE_AUTO_ORDER is
    unchanged by this round — see rules_registry_v1.json's own note on why)."""
    assert "STORE_ROOM" not in layout_engine.SUPPORT_ZONE_AUTO_ORDER
    entry = rules_registry.support_zone_default("STORE_ROOM")
    assert entry is not None
    assert entry["min_area_sqft"] == 90.0


def test_support_zone_area_share_viability_rule_exists_and_is_a_between_operator():
    rules = rules_registry.viability_rules("EXISTING_BUILDING")
    rule = next((r for r in rules if r["rule_id"] == "VR_SUPPORT_ZONE_AREA_SHARE"), None)
    assert rule is not None, "expected VR_SUPPORT_ZONE_AREA_SHARE in the registry's viability_rules"
    assert rule["operator"] == "between"
    assert rule["threshold_min"] == 30
    assert rule["threshold_max"] == 40
    assert rule["metric"] == "support_zone_area_pct_of_carpet"


def _room(room_type, area_sqft):
    return {"room_type": room_type, "area_sqft": area_sqft, "geometry_points_ft": [[0, 0], [1, 0], [1, 1], [0, 1]]}


def test_build_measurements_computes_support_zone_area_pct_of_carpet():
    rooms = [
        _room("AUDITORIUM_1", 2000.0),
        _room("AUDITORIUM_2", 2000.0),
        _room("BOX_OFFICE", 60.0),
        _room("FNB", 200.0),
        _room("WASHROOM", 500.0),
        _room("PASSAGE", 240.0),  # derived remainder — still a non-auditorium room
    ]
    # carpet/boundary area chosen so the non-auditorium total (1000) is a clean 20%
    measurements = main._build_measurements({}, [], boundary_area_sqft=5000.0, total_seats=0, screen_count=2, rooms=rooms)
    assert measurements["support_zone_area_pct_of_carpet"] == 20.0


def test_support_zone_area_share_rule_flags_a_share_below_30_percent():
    rule = next(r for r in rules_registry.viability_rules("ANY") if r["rule_id"] == "VR_SUPPORT_ZONE_AREA_SHARE")
    result = feasibility_engine.evaluate_rule(rule, {"support_zone_area_pct_of_carpet": 20.0})
    assert result["result"] == "FAIL"
    assert result["severity"] == "WARNING"


def test_support_zone_area_share_rule_passes_within_30_to_40_percent():
    rule = next(r for r in rules_registry.viability_rules("ANY") if r["rule_id"] == "VR_SUPPORT_ZONE_AREA_SHARE")
    result = feasibility_engine.evaluate_rule(rule, {"support_zone_area_pct_of_carpet": 35.0})
    assert result["result"] == "PASS"
