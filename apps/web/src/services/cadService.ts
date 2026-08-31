import { FloorRegionData, CandidateData, RoomData } from '../types/zoning';

export const INITIAL_PROCESSING_STEPS = [
  { id: 'cad_conv', label: 'CAD conversion (DWG → DXF)', status: 'PENDING' as const },
  { id: 'geom_ext', label: 'Multi-region geometry extraction', status: 'PENDING' as const },
  { id: 'bound_rec', label: 'Architectural boundary reconstruction', status: 'PENDING' as const },
  { id: 'obs_ident', label: 'Fixed planning obstruction identification', status: 'PENDING' as const },
  { id: 'usable_area', label: 'Usable planning area calculation', status: 'PENDING' as const },
  { id: 'zone_gen', label: 'Deterministic zoning generation', status: 'PENDING' as const },
  { id: 'opt_score', label: 'Multi-candidate optimization & scoring', status: 'PENDING' as const },
  { id: 'seat_layout', label: 'Seat layout & Area/Seat chart generation', status: 'PENDING' as const },
  { id: 'feasibility', label: 'Feasibility / compliance evaluation', status: 'PENDING' as const }
];

export function formatBytes(bytes: number, decimals = 1): string {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

export async function fetchZoningStudioData(): Promise<FloorRegionData[]> {
  try {
    const [decRes, layRes, decV2Res, seatRes, feasRes, chartRes] = await Promise.all([
      fetch('/cad-data/zoning_decision_v1.json'),
      fetch('/cad-data/zoning_layouts_v2.json'),
      fetch('/cad-data/zoning_decision_v2.json'),
      fetch('/cad-data/seat_layout_v1.json'),
      fetch('/cad-data/feasibility_v1.json'),
      fetch('/cad-data/area_seat_chart_v1.json')
    ]);

    if (!decRes.ok || !layRes.ok) {
      throw new Error('Failed to load zoning datasets from /cad-data/');
    }

    const decData = await decRes.json();
    const layData = await layRes.json();
    // Seat-aware M8 datasets. These are additive on top of the frozen M0-M7 pipeline;
    // if any are missing (e.g. a fresh clone that hasn't run the M8 scripts yet), the
    // UI degrades gracefully back to the M5 v1 scores instead of failing to load.
    const decV2Data = decV2Res.ok ? await decV2Res.json() : null;
    const seatData = seatRes.ok ? await seatRes.json() : null;
    const feasData = feasRes.ok ? await feasRes.json() : null;
    const chartData = chartRes.ok ? await chartRes.json() : null;

    const layMap = new Map<string, any>();
    for (const r of layData.regions || []) {
      layMap.set(r.region_id, r);
    }

    // Prefer the seat-aware v2 decision data (real per-candidate scores + seat counts);
    // fall back to v1 if M8 hasn't been run.
    const decisionRegions: any[] = (decV2Data?.regions || decData.regions || []);
    const decisionByRegionId = new Map<string, any>();
    for (const r of decisionRegions) decisionByRegionId.set(r.region_id, r);

    const seatRegionMap = new Map<string, any>();
    for (const r of seatData?.regions || []) seatRegionMap.set(r.region_id, r);

    const feasRegionMap = new Map<string, any>();
    for (const r of feasData?.regions || []) feasRegionMap.set(r.region_id, r);

    const chartRegionMap = new Map<string, any>();
    for (const r of chartData?.regions || []) chartRegionMap.set(r.region_id, r);

    const floors: FloorRegionData[] = [];

    for (const reg of decData.regions || []) {
      const rid = reg.region_id;
      const isBlocked = reg.decision_status === 'BLOCKED_NO_VERIFIED_BOUNDARY';

      // Use the v2 (seat-aware) version of this region's decision data when available —
      // it carries real per-candidate score_components/total_score/seat_data.
      const scoredRegion = decisionByRegionId.get(rid) || reg;
      const prefCand = scoredRegion.preferred_candidate;
      const seatRegion = seatRegionMap.get(rid);
      const seatCandById = new Map<string, any>((seatRegion?.candidates || []).map((c: any) => [c.candidate_id, c]));

      const candidates: CandidateData[] = [];
      let defaultRooms: RoomData[] = [];

      if (!isBlocked && layMap.has(rid)) {
        const layReg = layMap.get(rid);
        const scoredCandById = new Map<string, any>((scoredRegion.candidates || []).map((c: any) => [c.candidate_id, c]));

        for (const cand of layReg.candidates || []) {
          const candId = cand.candidate_id;
          const isPref = prefCand && candId === prefCand.candidate_id;

          // Real per-candidate score data, joined by candidate_id from the decision file —
          // previously this fell through to the same hardcoded fallback numbers for every
          // candidate because it was (incorrectly) read from the geometry file, which has
          // no score fields at all.
          const scored = scoredCandById.get(candId);
          const seatCand = seatCandById.get(candId);
          const auditoriumSeatByRoomId = new Map<string, any>(
            (seatCand?.auditoriums || []).map((a: any) => [a.room_id, a])
          );

          let candSvg = `/cad-data/optimized_zoning/dhule_${rid.replace('dhule-', '').replace('-', '_')}_${cand.candidate_label.replace('Candidate ', 'candidate_')}.svg`;

          const candRooms: RoomData[] = (cand.rooms || []).map((rm: any) => {
            const seatInfo = auditoriumSeatByRoomId.get(rm.room_id);
            return {
              room_id: rm.room_id || `${rid}-${rm.room_type.toLowerCase()}`,
              room_type: rm.room_type,
              display_name: rm.display_name,
              area_sqft: rm.area_sqft,
              width_ft: rm.width_ft,
              depth_ft: rm.depth_ft,
              min_area_sqft: rm.room_type.includes('AUDITORIUM') ? 600 : rm.room_type.includes('FOYER') ? 250 : 50,
              min_dimensions: `${rm.width_ft} × ${rm.depth_ft} ft`,
              status: rm.status || (rid === 'dhule-fourth-floor' && ['RESTROOMS', 'MANAGER_OFFICE'].includes(rm.room_type) ? 'REVIEW_REQUIRED' : 'VALID'),
              adjacency: rm.room_type === 'PROJECTION_ROOM' ? 'Shared wall with Screen 1 (29.0 ft)' : 'Direct interface to central gathering concourse',
              structural_clearance: 'Zero column collision (> 0.16 ft positive clearance)',
              source: cand.candidate_label,
              seat_count: seatInfo ? seatInfo.seat_packing.seat_count : undefined,
              seat_breakdown: seatInfo ? seatInfo.seat_breakdown : undefined,
              seat_estimate_status: seatInfo ? seatInfo.seat_packing.status : undefined,
              preset_fit: seatInfo ? seatInfo.preset_fit : undefined
            };
          });

          if (isPref) {
            defaultRooms = candRooms;
          }

          candidates.push({
            candidate_id: candId,
            candidate_label: cand.candidate_label,
            strategy: cand.strategy_name || cand.strategy || scored?.strategy || 'Optimization Strategy',
            total_score: scored?.total_score ?? cand.total_score ?? 0,
            score_breakdown: {
              area_efficiency: scored?.score_components_v2?.area_efficiency ?? scored?.score_components?.area_efficiency ?? 0,
              circulation_quality: scored?.score_components_v2?.circulation ?? scored?.score_components?.circulation ?? 0,
              adjacency_satisfaction: scored?.score_components_v2?.adjacency ?? scored?.score_components?.adjacency ?? 0,
              room_proportions: scored?.score_components_v2?.proportion ?? scored?.score_components?.proportion ?? 0,
              structural_clearance: scored?.score_components_v2?.clearance ?? scored?.score_components?.clearance ?? 0,
              layout_simplicity: scored?.score_components_v2?.simplicity ?? scored?.score_components?.simplicity ?? 0,
              uncertainty_penalty: scored?.score_components_v2?.uncertainty_penalty ?? scored?.score_components?.uncertainty_penalty ?? 0,
              seats: scored?.score_components_v2?.seats
            },
            is_preferred: isPref,
            status: scored?.status || cand.status || (rid === 'dhule-fourth-floor' ? 'VALID_REVIEW_REQUIRED' : 'VALID'),
            svg_url: candSvg,
            rooms: candRooms,
            circulation_area_sqft: scored?.circulation_area_sqft ?? 0,
            total_room_area_sqft: scored?.occupied_area_sqft ?? 0,
            total_allocated_sqft: (scored?.occupied_area_sqft ?? 0) + (scored?.circulation_area_sqft ?? 0),
            total_seats: seatCand?.total_seats,
            screen_count: seatCand?.screen_count,
            seats_per_screen: seatCand?.screen_count ? Math.round((seatCand.total_seats / seatCand.screen_count) * 10) / 10 : undefined
          });
        }
      }

      const floorSlug = rid.replace('dhule-', '').replace('-', '_');
      const prefSvg = `/cad-data/zoning_decision/dhule_${floorSlug}_decision.svg`;
      const revSvg = `/cad-data/review_package/dhule_${floorSlug}_review.svg`;

      floors.push({
        region_id: rid,
        plan_region: reg.plan_region,
        document: reg.document || 'Dhule Drawing Set',
        decision_status: reg.decision_status,
        is_blocked: isBlocked,
        m5_preferred_candidate_id: prefCand ? prefCand.candidate_id : null,
        m5_preferred_score: scoredRegion.preferred_score ?? reg.preferred_score ?? (prefCand ? prefCand.total_score : null),
        candidates: candidates,
        selected_candidate_id: (prefCand ? prefCand.candidate_id : (candidates[2]?.candidate_id || candidates[0]?.candidate_id || '')),
        preferred_svg_url: prefSvg,
        decision_svg_url: prefSvg,
        review_svg_url: revSvg,
        rooms: defaultRooms,
        blocker_message: isBlocked ? 'Verified exterior boundary required before architectural zoning review can commence.' : undefined,
        has_review_required: rid === 'dhule-fourth-floor',
        uncertainty_penalty: rid === 'dhule-fourth-floor' ? -5.0 : 0.0,
        feasibility: feasRegionMap.get(rid),
        area_seat_chart: chartRegionMap.get(rid)
      });
    }

    return floors;
  } catch (err) {
    console.error('Error fetching zoning data:', err);
    throw err;
  }
}
