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
