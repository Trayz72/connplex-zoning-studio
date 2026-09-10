import {
  GeometryResult, GeometryRegion, Requirements, ZoningRunResult, EditableLayout, ValidationError, SelectableSeatType, FranchiseTier
} from '../types/live';

// VITE_ZONING_API_BASE lets a production build point at a separately-hosted
// zoning-engine origin (e.g. Render) — unset, it falls back to the relative
// path the Vite dev proxy already handles.
const API_ROOT = import.meta.env.VITE_ZONING_API_BASE || '/api';
const BASE = `${API_ROOT}/projects`;

export async function getSeatTypes(): Promise<SelectableSeatType[]> {
  const res = await fetch(`${API_ROOT}/seat-types`);
  if (!res.ok) throw new Error('Failed to load seat types');
  const data = await res.json();
  return data.seat_types;
}

export async function getFranchiseTiers(): Promise<FranchiseTier[]> {
  const res = await fetch(`${API_ROOT}/franchise-tiers`);
  if (!res.ok) throw new Error('Failed to load franchise tiers');
  const data = await res.json();
  return data.franchise_tiers;
}

/** Removes this project's uploaded CAD/geometry/zoning-run/layout/export
 * files. Tolerant of a project that never had any zoning-engine data yet
 * (nothing was ever uploaded) — that's not a failure, just a no-op. */
export async function deleteProjectData(projectId: string): Promise<void> {
  try {
    await fetch(`${BASE}/${projectId}`, { method: 'DELETE' });
  } catch {
    // Best-effort cleanup: the project record itself (in the other service)
    // is the source of truth for whether the project still exists.
  }
}

export class ValidationRejectedError extends Error {
  errors: ValidationError[];
  constructor(message: string, errors: ValidationError[]) {
    super(message);
    this.errors = errors;
  }
}

export interface GapPair { a: [number, number]; b: [number, number]; distance_ft: number; }

/** Thrown by traceBoundary when a wall selection doesn't close — carries
 * the real dangling-endpoint locations (cad_extraction.py's
 * BoundaryTraceError) so the caller can mark exactly where the gap is on
 * the canvas instead of just showing text. gapPairsFt additionally pairs
 * those endpoints into probable gaps with real distances, so the caller can
 * offer a one-click "close this gap" action per pair — never computed or
 * applied here, this class just carries what the backend already decided
 * not to auto-apply (see BoundaryTraceError's own docstring). */
export class BoundaryGapError extends Error {
  gapPointsFt: [number, number][];
  gapPairsFt: GapPair[];
  constructor(message: string, gapPointsFt: [number, number][], gapPairsFt: GapPair[] = []) {
    super(message);
    this.gapPointsFt = gapPointsFt;
    this.gapPairsFt = gapPairsFt;
  }
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: any = null;
    try { detail = await res.json(); } catch { /* ignore */ }
    if (res.status === 422 && detail?.detail?.errors) {
      throw new ValidationRejectedError(detail.detail.message || 'Validation failed', detail.detail.errors);
    }
    if (res.status === 422 && detail?.detail?.gap_points_ft) {
      throw new BoundaryGapError(detail.detail.message || 'Selection does not close.', detail.detail.gap_points_ft, detail.detail.gap_pairs_ft || []);
    }
    const msg = detail?.detail ? (typeof detail.detail === 'string' ? detail.detail : JSON.stringify(detail.detail)) : `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return res.json();
}

/** Optional hints pulled straight from the project's own intake record
 * (Carpet Area / Floor-Shop-No) so the very first automatic candidate
 * ranking already reflects what a salesperson already told the app about
 * this property — see cad_extraction._form_match_info. Both undefined is
 * the same as omitting them entirely: ranking falls back to plain size. */
export interface BoundaryFormHints {
  targetAreaSqft?: number | null;
  labelHint?: string | null;
}

/** Real upload with real byte-level progress via XHR (fetch doesn't expose upload progress). */
export function uploadCad(
  projectId: string, file: File, onProgress: (pct: number) => void, hints?: BoundaryFormHints
): Promise<GeometryResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE}/${projectId}/cad`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        let msg = `Upload failed (${xhr.status})`;
        try { msg = JSON.parse(xhr.responseText).detail || msg; } catch { /* ignore */ }
        reject(new Error(msg));
      }
    };
    xhr.onerror = () => reject(new Error('Network error during upload.'));
    const form = new FormData();
    form.append('file', file);
    if (hints?.targetAreaSqft != null) form.append('target_area_sqft', String(hints.targetAreaSqft));
    if (hints?.labelHint) form.append('label_hint', hints.labelHint);
    xhr.send(form);
  });
}

export async function getGeometry(projectId: string): Promise<GeometryResult> {
  return asJson(await fetch(`${BASE}/${projectId}/geometry`));
}

/** Re-runs extraction on the file already uploaded via uploadCad, but with
 * Claude first picking which CAD layer(s) actually hold the wall/floor
 * geometry — for files where the default pass finds nothing (real,
 * dimension/hatch/furniture-heavy client drawings routinely bury the real
 * boundary among unrelated layers). A real, slower (~15-30s) Claude call,
 * not a retry of the same deterministic pass — only ever call this after a
 * normal upload, never instead of one. */
export async function aiScanCad(projectId: string, hints?: BoundaryFormHints): Promise<GeometryResult> {
  const params = new URLSearchParams();
  if (hints?.targetAreaSqft != null) params.set('target_area_sqft', String(hints.targetAreaSqft));
  if (hints?.labelHint) params.set('label_hint', hints.labelHint);
  const qs = params.toString();
  return asJson(await fetch(`${BASE}/${projectId}/cad/ai-scan${qs ? `?${qs}` : ''}`, { method: 'POST' }));
}

export async function updateGeometry(projectId: string, regions: GeometryRegion[]): Promise<GeometryResult> {
  return asJson(await fetch(`${BASE}/${projectId}/geometry`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ regions })
  }));
}

export async function aiClassifyGeometry(projectId: string): Promise<GeometryResult> {
  return asJson(await fetch(`${BASE}/${projectId}/geometry/ai-classify`, { method: 'POST' }));
}

export async function confirmUnits(projectId: string, unit: string): Promise<GeometryResult> {
  return asJson(await fetch(`${BASE}/${projectId}/cad/units`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ unit })
  }));
}

export async function traceBoundary(
  projectId: string, segmentIds: number[], customSegments: [number, number][][] = []
): Promise<{ points_ft: number[][]; area_sqft: number }> {
  return asJson(await fetch(`${BASE}/${projectId}/boundary/trace`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ segment_ids: segmentIds, custom_segments: customSegments })
  }));
}

export interface CleanLabelMatch {
  text: string;
  position_ft: [number, number];
  shape_handle: string | null;
  shape_area_sqft: number | null;
  shape_bounding_box_ft: { min_x: number; min_y: number; max_x: number; max_y: number } | null;
}

export interface CleanRegionPreview {
  region_id: string;
  source_handle: string;
  boundary_area_sqft: number;
  boundary_points_ft: number[][];
  kept_count: number;
  dropped_count: number;
  kept_by_classification: Record<string, number>;
  dropped_by_classification: Record<string, number>;
}

/** Form-based boundary selection for the Clean CAD stage: finds every text
 * label in the uploaded file matching `query`, each paired with its
 * smallest enclosing closed shape (most specific room first). */
export async function searchCleanLabel(projectId: string, query: string): Promise<CleanLabelMatch[]> {
  const data = await asJson<{ matches: CleanLabelMatch[] }>(await fetch(`${BASE}/${projectId}/clean/search-label`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query })
  }));
  return data.matches;
}

/** Live before/after readout for one or more selected closed shapes
 * (need not be adjacent/connected) — read-only, doesn't touch geometry.json. */
export async function previewClean(projectId: string, shapeHandles: string[]): Promise<CleanRegionPreview[]> {
  const data = await asJson<{ regions: CleanRegionPreview[] }>(await fetch(`${BASE}/${projectId}/clean/preview`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ shape_handles: shapeHandles })
  }));
  return data.regions;
}

/** Finalizes the selection: exports a clean DXF/DWG (outline + kept
 * COLUMN/DUCT obstacles only) and re-runs extraction against it, returning
 * the same GeometryResult shape uploadCad does so the caller can transition
 * straight into Geometry Review. */
export async function confirmClean(projectId: string, shapeHandles: string[]): Promise<GeometryResult> {
  return asJson(await fetch(`${BASE}/${projectId}/clean/confirm`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ shape_handles: shapeHandles })
  }));
}

/** Downloads the cleaned file directly, for a user who doesn't want to
 * continue into the zoning pipeline right away. */
export async function downloadClean(projectId: string, format: 'dxf' | 'dwg') {
  const res = await fetch(`${BASE}/${projectId}/clean/download?format=${format}`);
  await downloadFile(res, `${projectId}_clean.${format}`);
}

export async function createManualRegion(
  projectId: string, pointsFt: number[][], mode: 'shape' | 'walls' | 'draw', sourceShapeHandle?: string, closedGapCount = 0
): Promise<GeometryResult> {
  return asJson(await fetch(`${BASE}/${projectId}/regions/manual`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ points_ft: pointsFt, mode, source_shape_handle: sourceShapeHandle || null, closed_gap_count: closedGapCount })
  }));
}

export async function setRequirements(projectId: string, req: Requirements): Promise<Requirements> {
  return asJson(await fetch(`${BASE}/${projectId}/requirements`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(req)
  }));
}

export async function getRequirements(projectId: string): Promise<Requirements | null> {
  const res = await fetch(`${BASE}/${projectId}/requirements`);
  if (res.status === 404) return null;
  return asJson(res);
}

export async function runZoning(projectId: string, regionId: string): Promise<ZoningRunResult> {
  return asJson(await fetch(`${BASE}/${projectId}/zoning-runs`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ region_id: regionId })
  }));
}

/** Asks Claude to propose a layout directly from the real floor geometry,
 * instead of the deterministic packer — genuinely slower (a real model call,
 * usually 20-40s) and costs real API usage, so this is only ever triggered by
 * an explicit user click, never auto-run like the two deterministic
 * strategies. Returns the same ZoningRunResult shape with the AI candidate
 * merged into `candidates`, so selecting/editing/exporting it needs no
 * AI-specific frontend code past this call. */
export async function runAiZoning(projectId: string, regionId: string): Promise<ZoningRunResult> {
  return asJson(await fetch(`${BASE}/${projectId}/ai-zoning-runs`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ region_id: regionId })
  }));
}

/** Poses auditorium placement as a real combinatorial optimization
 * (OR-Tools CP-SAT over a real candidate pool of maximal free rectangles)
 * instead of any greedy heuristic — genuinely slower (can take up to
 * placement/solver.py's TIME_LIMIT_SECONDS, ~20s) so this is only ever
 * triggered by an explicit user click, same convention as runAiZoning.
 * Returns the same ZoningRunResult shape with the OPTIMIZED candidate
 * merged into `candidates`. */
export async function runOptimizedZoning(projectId: string, regionId: string): Promise<ZoningRunResult> {
  return asJson(await fetch(`${BASE}/${projectId}/zoning-runs/optimize`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ region_id: regionId })
  }));
}

export async function getLatestRun(projectId: string): Promise<ZoningRunResult | null> {
  const res = await fetch(`${BASE}/${projectId}/zoning-runs/latest`);
  if (res.status === 404) return null;
  return asJson(res);
}

export async function selectCandidate(projectId: string, candidateId: string): Promise<EditableLayout> {
  return asJson(await fetch(`${BASE}/${projectId}/layout/select-candidate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ candidate_id: candidateId })
  }));
}

export async function getLayout(projectId: string): Promise<EditableLayout | null> {
  const res = await fetch(`${BASE}/${projectId}/layout`);
  if (res.status === 404) return null;
  return asJson(res);
}

export async function updateLayout(projectId: string, layout: Pick<EditableLayout, 'rooms' | 'boundary_points_ft' | 'obstacles' | 'circulation_area_sqft'>): Promise<EditableLayout> {
  return asJson(await fetch(`${BASE}/${projectId}/layout`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(layout)
  }));
}

/** Places one new room (AUDITORIUM | FOYER | FNB | WASHROOM | BOX_OFFICE | BOH | PASSAGE)
 * into the current layout at a real, collision-free position the backend
 * finds via the same entry-aware scan-and-fit machinery auto-layout itself
 * uses — never a client-guessed corner. Throws a plain Error (its `message`
 * is the honest "no space" reason) when nothing fits anywhere. */
export async function addZone(projectId: string, roomType: string): Promise<EditableLayout> {
  return asJson(await fetch(`${BASE}/${projectId}/layout/zones`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ room_type: roomType })
  }));
}

/** Re-orients an already-placed screen: which of its 4 walls is the real
 * projection-screen wall. The room's footprint doesn't move — only the
 * server-side seat estimate is recomputed (against the correct axis) and
 * any doors on the new screen wall get flagged. A narrow, single-room
 * endpoint, not a generic layout PUT — see main.py's update_screen_wall
 * docstring for why. */
export async function setScreenWall(projectId: string, roomId: string, screenWall: 'min_x' | 'max_x' | 'min_y' | 'max_y'): Promise<EditableLayout> {
  return asJson(await fetch(`${BASE}/${projectId}/layout/rooms/${roomId}/screen-wall`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ screen_wall: screenWall })
  }));
}

async function downloadFile(res: Response, fallbackName: string) {
  if (!res.ok) {
    let detail: any = null;
    try { detail = await res.json(); } catch { /* ignore */ }
    throw new Error(detail?.detail || `Export failed (${res.status})`);
  }
  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function exportPdf(projectId: string, projectMeta: Record<string, any>, sheetType = 'Zoning Layout') {
  const res = await fetch(`${BASE}/${projectId}/export/pdf`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_meta: projectMeta, sheet_type: sheetType })
  });
  await downloadFile(res, `${projectId}_zoning_layout.pdf`);
}

export async function exportCad(projectId: string, projectMeta: Record<string, any>, format: 'dxf' | 'dwg') {
  const res = await fetch(`${BASE}/${projectId}/export/cad`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_meta: projectMeta, format })
  });
  await downloadFile(res, `${projectId}_zoning_layout.${format}`);
}

export interface ExportHistoryEntry {
  revision: string;
  sheet_type: string;
  format: string;
  filename: string;
  generated_at: string;
  drawn_by: string;
  checked_by: string;
  remarks: string;
}

export async function getExportHistory(projectId: string): Promise<ExportHistoryEntry[]> {
  const res = await fetch(`${BASE}/${projectId}/export-history`);
  if (!res.ok) throw new Error('Failed to load export history');
  const data = await res.json();
  return data.history;
}
