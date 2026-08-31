import {
  GeometryResult, GeometryRegion, Requirements, ZoningRunResult, EditableLayout, ValidationError, SelectableSeatType
} from '../types/live';

const BASE = '/api/projects';

export async function getSeatTypes(): Promise<SelectableSeatType[]> {
  const res = await fetch('/api/seat-types');
  if (!res.ok) throw new Error('Failed to load seat types');
  const data = await res.json();
  return data.seat_types;
}

export class ValidationRejectedError extends Error {
  errors: ValidationError[];
  constructor(message: string, errors: ValidationError[]) {
    super(message);
    this.errors = errors;
  }
}

async function asJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: any = null;
    try { detail = await res.json(); } catch { /* ignore */ }
    if (res.status === 422 && detail?.detail?.errors) {
      throw new ValidationRejectedError(detail.detail.message || 'Validation failed', detail.detail.errors);
    }
    const msg = detail?.detail ? (typeof detail.detail === 'string' ? detail.detail : JSON.stringify(detail.detail)) : `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return res.json();
}

/** Real upload with real byte-level progress via XHR (fetch doesn't expose upload progress). */
export function uploadCad(projectId: string, file: File, onProgress: (pct: number) => void): Promise<GeometryResult> {
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
    xhr.send(form);
  });
}

export async function getGeometry(projectId: string): Promise<GeometryResult> {
  return asJson(await fetch(`${BASE}/${projectId}/geometry`));
}

export async function updateGeometry(projectId: string, regions: GeometryRegion[]): Promise<GeometryResult> {
  return asJson(await fetch(`${BASE}/${projectId}/geometry`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ regions })
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

export async function getLatestRun(projectId: string): Promise<ZoningRunResult | null> {
  const res = await fetch(`${BASE}/${projectId}/zoning-runs/latest`);
  if (res.status === 404) return null;
  return asJson(res);
}

export async function selectCandidate(projectId: string, candidateId: string): Promise<EditableLayout> {
  return asJson(await fetch(`${BASE}/${projectId}/layout/select-candidate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ region_id: candidateId })
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
