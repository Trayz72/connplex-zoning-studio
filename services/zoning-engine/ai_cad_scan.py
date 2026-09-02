"""
AI-assisted CAD geometry scan — a dedicated, explicit alternative to the
default deterministic extraction in cad_extraction.py, for the real files
that pass never found any usable boundary on (confirmed against a batch of
16 real client DXFs: 5 found zero regions on the default pass; layer noise
— dimension marks, hatching, furniture blocks sharing the drawing with the
real wall/floor geometry — was the common thread).

This does NOT ask an LLM to invent or trace raw geometry from pixel/text
data — that would be exactly the kind of hallucination-risk shortcut this
project's own anti-hallucination rule (CLAUDE.md) rules out, and coordinate
data is precisely the thing an LLM is worst at reproducing exactly. Instead:
every real coordinate always comes from cad_extraction.py's own proven,
deterministic ezdxf-based reader — Claude's only job is to look at a compact
summary of the drawing's layers (names, entity counts, how much of the
drawing's own bounding box each layer's geometry actually covers) and decide
which layer(s) most plausibly hold the real wall/floor boundary, the same
judgment call an architect skimming a layer list would make. That choice is
then handed straight back into cad_extraction.extract()'s own existing,
already-tested pipeline — this is a smarter *input* to the same trusted
extractor, not a separate/less-trustworthy one.
"""
import json
import os

from dotenv import load_dotenv

import cad_extraction

load_dotenv()

MODEL_ID = "claude-opus-5"


class AiCadScanError(Exception):
    pass


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AiCadScanError(
            "AI CAD scan is not configured on this server — ANTHROPIC_API_KEY is not set. "
            "Set it in services/zoning-engine/.env (local) or the service's environment variables (deployed)."
        )
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _layer_stats(dxf_path: str) -> dict:
    """Per-layer entity counts + how much of the overall drawing bounding box
    that layer's own geometry spans — a real wall/boundary layer almost
    always covers close to the full extent; furniture/dimension/hatch layers
    are usually localized or scattered. Computed once via a single pass over
    modelspace, not per-entity bbox lookups against the whole drawing."""
    resolved_path, _ = cad_extraction.resolve_dxf_path(dxf_path)
    doc, _ = cad_extraction._read_dxf_with_recovery(resolved_path)
    msp = doc.modelspace()
    units = cad_extraction._get_units(doc)

    overall = {"minx": None, "miny": None, "maxx": None, "maxy": None}
    per_layer = {}

    def _bounds_of(e):
        try:
            path = cad_extraction.ezdxf.path.make_path(e)
            pts = list(path.control_vertices()) or list(path.flattening(1.0, 4))
            if not pts:
                return None
            xs = [p.x for p in pts]
            ys = [p.y for p in pts]
            return min(xs), min(ys), max(xs), max(ys)
        except Exception:
            return None

    for e in msp:
        t = e.dxftype()
        layer = str(e.dxf.layer)
        rec = per_layer.setdefault(layer, {"entity_counts": {}, "minx": None, "miny": None, "maxx": None, "maxy": None})
        rec["entity_counts"][t] = rec["entity_counts"].get(t, 0) + 1

        b = _bounds_of(e) if t in ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "SPLINE", "ELLIPSE", "CIRCLE", "INSERT") else None
        if b:
            x0, y0, x1, y1 = b
            for key, val, cmp in (("minx", x0, min), ("miny", y0, min), ("maxx", x1, max), ("maxy", y1, max)):
                rec[key] = val if rec[key] is None else cmp(rec[key], val)
                overall[key] = val if overall[key] is None else cmp(overall[key], val)

    scale = cad_extraction.working_scale(units)
    overall_w = (overall["maxx"] - overall["minx"]) if overall["minx"] is not None else 0
    overall_h = (overall["maxy"] - overall["miny"]) if overall["miny"] is not None else 0

    layers_out = []
    for name, rec in per_layer.items():
        if rec["minx"] is None:
            coverage_pct = 0.0
        else:
            lw, lh = rec["maxx"] - rec["minx"], rec["maxy"] - rec["miny"]
            coverage_pct = round(100 * max(lw / overall_w if overall_w else 0, lh / overall_h if overall_h else 0), 1)
        layers_out.append({
            "layer": name,
            "entity_counts": rec["entity_counts"],
            "bbox_coverage_pct_of_drawing": coverage_pct,
        })
    layers_out.sort(key=lambda r: -sum(r["entity_counts"].values()))

    return {
        "units": units,
        "drawing_bbox_ft": {
            "width": round(overall_w * scale, 1), "height": round(overall_h * scale, 1),
        } if overall["minx"] is not None else None,
        "layers": layers_out[:60],  # cap — a real file can have hundreds of layers, only the biggest matter
    }


SCAN_TOOL = {
    "name": "propose_extraction_layers",
    "description": "Choose which CAD layer(s) actually contain the real wall/floor-boundary geometry, so extraction can be re-run against just those layers instead of the whole noisy drawing.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string", "description": "1-3 sentences: which layer(s) you picked and why, in terms of the layer names/stats you were given."},
            "boundary_layers": {
                "type": "array", "items": {"type": "string"},
                "description": "Layer names most likely to contain the real wall/floor outline. Empty array if none look plausible."
            },
            "min_boundary_area_sqft": {
                "type": ["number", "null"],
                "description": "Suggested minimum area (sqft) for something to count as a real floor boundary on this drawing, or null to keep the default (150 sqft)."
            },
        },
        "required": ["reasoning", "boundary_layers", "min_boundary_area_sqft"],
        "additionalProperties": False,
    },
}


def ai_rescan(input_path: str) -> dict:
    """Returns the same GeometryResult shape as cad_extraction.extract().
    Always runs the real deterministic extractor — Claude only chooses which
    layers to point it at. If the AI-guided pass doesn't actually find more
    than the plain default pass, the default result is returned instead
    (never regresses relative to just uploading normally)."""
    default_result = cad_extraction.extract(input_path)

    stats = _layer_stats(input_path)
    client = _client()

    prompt = f"""A CAD floor-plan extractor found {default_result['region_count']} usable region(s) on its default \
pass over this drawing. Real client files often bury the actual wall/floor-boundary geometry among dozens of \
unrelated layers (dimensions, hatching, furniture, title blocks) that fragment or drown it out.

Per-layer stats for this drawing (top layers by entity count):
{json.dumps(stats, indent=2)}

Pick the layer(s) most likely to hold the real wall/floor-boundary geometry — usually a layer whose name suggests \
walls/outline/floor-plate (e.g. containing "wall", "outline", "fp", "boundary", "structure") AND whose \
bbox_coverage_pct_of_drawing is high (close to spanning the whole drawing, since a floor outline usually does). \
A layer with mostly TEXT/MTEXT/DIMENSION/HATCH entities and low coverage is almost never the boundary layer. If \
nothing looks plausible, return an empty boundary_layers array rather than guessing."""

    try:
        response = client.messages.create(
            model=MODEL_ID, max_tokens=2000,
            thinking={"type": "adaptive"}, output_config={"effort": "medium"},
            tools=[SCAN_TOOL], tool_choice={"type": "tool", "name": "propose_extraction_layers"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise AiCadScanError(f"AI CAD scan request failed: {e}")

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        raise AiCadScanError("Claude did not return a layer proposal.")

    layers = tool_use.input.get("boundary_layers") or None
    min_area = tool_use.input.get("min_boundary_area_sqft")
    reasoning = tool_use.input.get("reasoning", "")

    if not layers:
        default_result["conversion_note"] = (
            (default_result.get("conversion_note") or "")
            + f" AI CAD scan found no better layer subset to try — {reasoning}"
        ).strip()
        default_result["extraction_method"] = "deterministic (AI scan found no improvement)"
        return default_result

    try:
        ai_result = cad_extraction.extract(input_path, allowed_layers=layers, min_boundary_area_sqft=min_area)
    except Exception as e:
        raise AiCadScanError(f"Re-extraction against AI-selected layers failed: {e}")

    if ai_result["region_count"] <= default_result["region_count"]:
        default_result["conversion_note"] = (
            (default_result.get("conversion_note") or "")
            + f" AI CAD scan tried layers {layers} but found no improvement over the default pass — {reasoning}"
        ).strip()
        default_result["extraction_method"] = "deterministic (AI scan found no improvement)"
        return default_result

    ai_result["conversion_note"] = (
        (ai_result.get("conversion_note") or "")
        + f" AI-assisted scan restricted extraction to layer(s) {layers} — {reasoning}"
    ).strip()
    ai_result["extraction_method"] = "ai_assisted_layer_selection"
    return ai_result
