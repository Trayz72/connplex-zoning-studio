import { GeometryRegion } from '../types/live';

// A CAD file with multiple figures/floors (a ground + first floor plan
// drawn side by side in one DXF, or a multi-tenant sheet) produces one
// candidate region per closed shape with no inherent floor identity of its
// own — an architect picking between "Region 1 — 12,345 sqft" and "Region
// 2 — 11,980 sqft" has to guess which is which from area alone. Each
// region already carries the source drawing's own nearby text labels
// (region.text_labels, filtered server-side to that region's bounding
// box); real title blocks and plan captions almost always name the floor
// right there ("GROUND FLOOR PLAN", "1ST FLOOR", "LEVEL 2"), so matching
// against that text turns a guess into a real, drawing-sourced hint.
// Ordered most-specific first so a named floor ("GROUND FLOOR") wins over
// a bare ordinal-number match on the same label.
const FLOOR_LABEL_PATTERNS: RegExp[] = [
  /\b(GROUND|BASEMENT|LOWER GROUND|UPPER GROUND|MEZZANINE|PODIUM|TERRACE|ROOF|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)\s+FLOOR\b/,
  /\b\d+\s*(ST|ND|RD|TH)\s+FLOOR\b/,
  /\bFLOOR\s*[-#]?\s*\d+\b/,
  /\bLEVEL\s*[-#]?\s*\d+\b/,
];

export function floorLabelFor(region: GeometryRegion): string | null {
  for (const label of region.text_labels) {
    const text = label.text.toUpperCase();
    for (const pattern of FLOOR_LABEL_PATTERNS) {
      const match = text.match(pattern);
      if (match) return match[0].replace(/\s+/g, ' ').trim();
    }
  }
  return null;
}

// Same real signal cad_extraction._form_match_info already applies to the
// automatic region-candidate ranking (a region's own computed area vs. the
// intake form's carpet_area_sqft, within a 15% tolerance — matches
// FORM_MATCH_AREA_TOLERANCE_FRACTION server-side) and the Clean CAD area-
// suggestion feature, applied here to the Boundary/Geometry-Review region
// picker instead — "form drives boundary detection," extended to whichever
// step a multi-region CAD file first needs the architect to choose one on.
const AREA_MATCH_TOLERANCE_FRACTION = 0.15;

/** Loose text match between this region's own detected floor label and the
 * intake form's free-text Offered Floor field ("3rd Floor, Shop 12") — a
 * simple substring check in either direction handles the common real case
 * ("3RD FLOOR" is a substring of "3RD FLOOR, SHOP 12") without needing a
 * full NLP match. Returns false (not a mismatch signal, just "no floor
 * evidence") when either side is missing. */
export function floorLabelMatchesHint(region: GeometryRegion, floorShopHint: string | null | undefined): boolean {
  const regionLabel = floorLabelFor(region);
  if (!regionLabel || !floorShopHint) return false;
  const norm = (s: string) => s.toUpperCase().replace(/\s+/g, ' ').trim();
  const a = norm(regionLabel), b = norm(floorShopHint);
  return a.length > 0 && b.length > 0 && (b.includes(a) || a.includes(b));
}

export function areaMatchesCarpetArea(region: GeometryRegion, carpetAreaSqft: number | null | undefined): boolean {
  if (!carpetAreaSqft || carpetAreaSqft <= 0) return false;
  const relError = Math.abs(region.boundary.area_sqft - carpetAreaSqft) / carpetAreaSqft;
  return relError <= AREA_MATCH_TOLERANCE_FRACTION;
}

/** Ranks candidate regions against the project's own intake form data and
 * returns the single best-matching region_id, or null when nothing clears
 * the bar — never picks one just because it's "least bad." A region only
 * qualifies when its area matches; among qualifiers, one whose detected
 * floor label also matches the Offered Floor hint outranks one that
 * doesn't, and closer area wins ties. Purely a suggestion for a "Best
 * match for your intake form" badge — never auto-selects a region, same
 * "uncertain detection stays proposed until a human clicks" convention as
 * every other suggestion feature in this app. */
export function bestMatchRegionId(
  regions: GeometryRegion[], carpetAreaSqft: number | null | undefined, floorShopHint: string | null | undefined
): string | null {
  const qualifying = regions.filter(r => areaMatchesCarpetArea(r, carpetAreaSqft));
  if (qualifying.length === 0) return null;
  const ranked = [...qualifying].sort((a, b) => {
    const aFloorMatch = floorLabelMatchesHint(a, floorShopHint) ? 1 : 0;
    const bFloorMatch = floorLabelMatchesHint(b, floorShopHint) ? 1 : 0;
    if (aFloorMatch !== bFloorMatch) return bFloorMatch - aFloorMatch;
    const aErr = Math.abs(a.boundary.area_sqft - (carpetAreaSqft || 0));
    const bErr = Math.abs(b.boundary.area_sqft - (carpetAreaSqft || 0));
    return aErr - bErr;
  });
  return ranked[0].region_id;
}
