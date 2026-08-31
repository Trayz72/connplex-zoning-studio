"""Loads the shared, versioned Rules/Config registry (Product Principle #1: config
over code — nothing in this service hardcodes a business/architectural number).

Read-only from this service's side, deliberately — the admin-editable write
path (spec M2's admin UI) lives in services/project instead, because that's
the service with real users/sessions/admin auth. zoning-engine has no auth
model at all by design (see CLAUDE.md's module-boundary notes), so an edit
endpoint here would mean anyone who can reach this service could rewrite
business rules with zero authentication. Both services read the same file on
disk, so this only needs to notice when it changes underneath it."""
import json
import os

REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "rules-config", "registry", "rules_registry_v1.json"
)

_cache = None
_cache_mtime = None


def load():
    """Re-reads the file whenever its mtime has moved since the last load —
    a cheap stat() call, so an edit made through the admin UI (a separate
    process, services/project) takes effect on this service's very next
    request instead of needing a restart or an explicit cross-service
    reload call this service's own auth-less API surface shouldn't expose."""
    global _cache, _cache_mtime
    try:
        current_mtime = os.path.getmtime(REGISTRY_PATH)
    except OSError:
        current_mtime = None
    if _cache is None or current_mtime != _cache_mtime:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
        _cache_mtime = current_mtime
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
