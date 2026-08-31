"""Loads the shared, versioned Rules/Config registry (Product Principle #1: config
over code — nothing in this service hardcodes a business/architectural number)."""
import json
import os

REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "rules-config", "registry", "rules_registry_v1.json"
)

_cache = None


def load():
    global _cache
    if _cache is None:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def seat_type(seat_type_id: str) -> dict:
    return next(s for s in load()["seat_types"] if s["id"] == seat_type_id)


def auditorium_presets() -> list:
    # Largest first, so the packer greedily tries to seat as many people as possible
    # per screen before falling back to a smaller preset — this is what operationalizes
    # the "maximize total seat count" objective at placement time, not just at scoring time.
    return sorted(load()["auditorium_presets"], key=lambda p: p["target_seats"], reverse=True)


def planning_norm(norm_id: str):
    n = next((x for x in load()["planning_norms"] if x["id"] == norm_id), None)
    return n["value"] if n else None


def viability_rules(property_type: str) -> list:
    return [r for r in load()["viability_rules"] if r["property_type_scope"] in (property_type, "ANY")]


def franchise_tier(tier_id: str):
    return next((t for t in load()["franchise_tiers"] if t["id"] == tier_id), None)
