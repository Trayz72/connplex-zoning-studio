"""
AI-assisted obstacle classification — a dedicated, explicit enhancement to the
default layer-name/shape heuristic in cad_extraction.py, for the real closed
shapes that heuristic can't confidently place.

Found via real testing (not assumed): across the three real reference files
this pipeline has been tested against, 41-6,622 obstacle candidates per file
(up to 36% of all obstacles on one real file) land as UNCLASSIFIED_OBSTACLE
purely because their layer name doesn't match any of the fixed AIA-style
substrings cad_extraction.py's heuristic knows — despite many of those layer
names being completely unambiguous to a human/LLM reader ("CHAIRS", "bike",
both fixed programmatically once found — see OBSTACLE_LAYER_HINTS) or clearly
non-physical annotation/reference content ("F.S.I." — floor space index area
calculation, "BUILT UP" — built-up area annotation, "title block").

Never asked to invent geometry or guess a shape's position/size — every
coordinate stays exactly what cad_extraction.py already extracted; this
module only ever assigns a `classification` (or IGNORED status) to a shape
that already exists. Claude's only job is the same judgment call an architect
skimming a layer list would make: given a layer name and its real aggregate
shape statistics (count, average area, how squarish the shapes are), decide
whether that layer most plausibly holds a real physical obstacle (and which
kind) or non-physical annotation/reference content. This is a smarter
*initial guess*, never an automatic confirmation — every result still lands
as PROPOSED (or, for a layer AI is confident is non-physical, pre-set to
IGNORED, always visible and reversible) and still goes through the existing
Confirm/Ignore review before it can drive a zoning run (spec Sec 11).
"""
import json
import os

from dotenv import load_dotenv

load_dotenv()

MODEL_ID = "claude-opus-5"

PHYSICAL_CLASSIFICATIONS = ["COLUMN", "WALL", "DOOR", "WINDOW", "STAIRCASE", "WASHROOM_FIXTURE", "FURNITURE"]


class AiClassifyError(Exception):
    pass


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AiClassifyError(
            "AI obstacle classification is not configured on this server — ANTHROPIC_API_KEY is not set. "
            "Set it in services/zoning-engine/.env (local) or the service's environment variables (deployed)."
        )
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _layer_stats(geometry: dict) -> dict:
    """Real aggregate evidence per layer among this geometry's unclassified
    obstacles — count, average area, and how squarish the shapes are (a
    compact/squarish shape is much more likely to be a column or fixture
    than an elongated one). Computed once over every region already in
    memory, not a fresh CAD read."""
    by_layer = {}
    for region in geometry.get("regions", []):
        for o in region.get("obstacles", []):
            if o["classification"] != "UNCLASSIFIED_OBSTACLE" or o["status"] != "PROPOSED":
                continue
            rec = by_layer.setdefault(o["layer"], {"count": 0, "total_area": 0.0, "squarish_sum": 0.0})
            rec["count"] += 1
            rec["total_area"] += o["area_sqft"]
            pts = o["points_ft"]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            w, h = max(xs) - min(xs), max(ys) - min(ys)
            rec["squarish_sum"] += (min(w, h) / max(w, h) if max(w, h) > 0 else 0)

    return {
        layer: {
            "layer": layer,
            "shape_count": rec["count"],
            "avg_area_sqft": round(rec["total_area"] / rec["count"], 2),
            "avg_squarish_ratio": round(rec["squarish_sum"] / rec["count"], 2),
        }
        for layer, rec in by_layer.items()
    }


CLASSIFY_TOOL = {
    "name": "classify_obstacle_layers",
    "description": (
        "For each given CAD layer (holding shapes the deterministic heuristic couldn't confidently place), "
        "decide whether it most plausibly holds a real physical obstacle (and which kind) or non-physical "
        "annotation/reference content."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "layers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "layer": {"type": "string"},
                        "classification": {
                            "type": "string",
                            "enum": PHYSICAL_CLASSIFICATIONS + ["NOT_PHYSICAL", "UNSURE"],
                            "description": (
                                "One of the fixed physical types if the layer name + shape stats clearly point to "
                                "it; NOT_PHYSICAL if this is annotation/reference content (an area-calculation "
                                "boundary, a title block, a dimension helper shape) rather than a real object; "
                                "UNSURE if there isn't enough evidence either way — never guess a physical type "
                                "without real support from the layer name or shape stats."
                            ),
                        },
                        "reasoning": {"type": "string", "description": "One short sentence citing the specific layer-name/stat evidence used."},
                    },
                    "required": ["layer", "classification", "reasoning"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["layers"],
        "additionalProperties": False,
    },
}


def _ask_claude(layer_stats: dict) -> dict:
    client = _client()
    prompt = f"""A CAD floor-plan extractor found real closed shapes on the CAD layers below, but its layer-name \
heuristic (which only matches fixed English architectural substrings like "wall"/"col"/"door") couldn't confidently \
classify them. Real client files often use non-standard, abbreviated, or non-English layer names for real physical \
elements, and also often put non-physical annotation/reference shapes (area-calculation boundaries, title blocks, \
dimension helper geometry) in the same closed-shape pool.

Per-layer stats (only layers with unclassified shapes):
{json.dumps(list(layer_stats.values()), indent=2)}

For each layer, decide: does its name (plus shape count/avg area/squarish ratio) point clearly to a real physical \
obstacle — and if so, which kind (COLUMN, WALL, DOOR, WINDOW, STAIRCASE, WASHROOM_FIXTURE, FURNITURE) — or is it \
non-physical annotation/reference content (NOT_PHYSICAL)? If there's genuinely not enough evidence, say UNSURE \
rather than guessing. A compact, squarish shape under ~20 sqft repeated many times is a strong column signal; a \
name referencing area/index/calculation/title/format/dimension terms is a strong NOT_PHYSICAL signal."""

    try:
        response = client.messages.create(
            model=MODEL_ID, max_tokens=4000,
            thinking={"type": "adaptive"}, output_config={"effort": "medium"},
            tools=[CLASSIFY_TOOL], tool_choice={"type": "tool", "name": "classify_obstacle_layers"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise AiClassifyError(f"AI obstacle classification request failed: {e}")

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        raise AiClassifyError("Claude did not return a classification proposal.")

    return {item["layer"]: item for item in tool_use.input.get("layers", [])}


def classify_unclassified_obstacles(geometry: dict) -> dict:
    """Mutates and returns `geometry`: every UNCLASSIFIED_OBSTACLE/PROPOSED
    obstacle whose layer Claude confidently placed gets a real classification
    (confidence 'medium' — an inference, not literal layer-name evidence,
    so never 'high') and an ai_note explaining why; a layer Claude judged
    NOT_PHYSICAL gets its obstacles pre-set to IGNORED (still visible, still
    reversible) with an ai_note explaining why. UNSURE layers are left
    exactly as they were — an honest 'couldn't tell' is not silently
    resolved into a guess."""
    layer_stats = _layer_stats(geometry)
    if not layer_stats:
        return geometry

    results = _ask_claude(layer_stats)

    applied_count = 0
    ignored_count = 0
    for region in geometry.get("regions", []):
        for o in region.get("obstacles", []):
            if o["classification"] != "UNCLASSIFIED_OBSTACLE" or o["status"] != "PROPOSED":
                continue
            result = results.get(o["layer"])
            if not result:
                continue
            cls = result["classification"]
            reasoning = result.get("reasoning", "")
            if cls in PHYSICAL_CLASSIFICATIONS:
                o["classification"] = cls
                o["confidence"] = "medium"
                o["ai_note"] = f"AI-suggested from layer \"{o['layer']}\" — {reasoning} Verify before confirming."
                applied_count += 1
            elif cls == "NOT_PHYSICAL":
                o["status"] = "IGNORED"
                o["ai_note"] = f"AI pre-ignored — layer \"{o['layer']}\" looks like non-physical annotation: {reasoning} Un-ignore if this is wrong."
                ignored_count += 1
            # UNSURE: leave untouched, honestly.

    geometry["ai_classification_note"] = (
        f"AI-assisted classification: {applied_count} obstacle(s) reclassified, "
        f"{ignored_count} pre-ignored as likely non-physical. Review both before confirming."
    )
    return geometry
