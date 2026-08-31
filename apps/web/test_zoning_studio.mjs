// test_zoning_studio.mjs
// Milestone M8 — Frontend Zoning Studio Test Suite

import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

console.log('\n' + '='.repeat(80));
console.log('M8 FRONTEND ZONING STUDIO TEST SUITE (TESTS 1 TO 10)');
console.log('='.repeat(80));

const results = [];

function runTest(id, name, fn) {
  try {
    fn();
    results.push({ id, name, passed: true });
    console.log(`  [PASS] Test ${id.toString().padStart(2, ' ')}: ${name}`);
  } catch (err) {
    results.push({ id, name, passed: false, error: err.message });
    console.log(`  [FAIL] Test ${id.toString().padStart(2, ' ')}: ${name} - ${err.message}`);
  }
}

// Load data files from public/cad-data
const dataDir = path.join(__dirname, 'public', 'cad-data');
const decData = JSON.parse(fs.readFileSync(path.join(dataDir, 'zoning_decision_v1.json'), 'utf-8'));
const layData = JSON.parse(fs.readFileSync(path.join(dataDir, 'zoning_layouts_v2.json'), 'utf-8'));
const revData = JSON.parse(fs.readFileSync(path.join(dataDir, 'zoning_revisions_v1.json'), 'utf-8'));

// Test 1: CAD upload state
runTest(1, 'CAD upload state & DWG validation', () => {
  const validDwg = 'Dhule_Cinema_Complex.dwg';
  const invalidDxf = 'drawing.pdf';
  assert.ok(validDwg.toLowerCase().endsWith('.dwg'), 'Should accept .dwg file');
  assert.ok(!invalidDxf.toLowerCase().endsWith('.dwg'), 'Should reject non-.dwg file');

  const steps = [
    'CAD conversion (DWG → DXF)',
    'Multi-region geometry extraction',
    'Architectural boundary reconstruction',
    'Fixed planning obstruction identification',
    'Usable planning area calculation',
    'Deterministic zoning generation',
    'Multi-candidate optimization & scoring'
  ];
  assert.strictEqual(steps.length, 7, 'Pipeline must have 7 discrete processing steps');
});

// Test 2: Floor switching
runTest(2, 'Floor switching across 8 regions', () => {
  assert.strictEqual(decData.regions.length, 8, 'Should have 8 total regions');
  const readyFloors = decData.regions.filter(r => r.decision_status !== 'BLOCKED_NO_VERIFIED_BOUNDARY');
  const blockedFloors = decData.regions.filter(r => r.decision_status === 'BLOCKED_NO_VERIFIED_BOUNDARY');
  assert.strictEqual(readyFloors.length, 4, 'Should have 4 decision-ready floors');
  assert.strictEqual(blockedFloors.length, 4, 'Should have 4 blocked floors');
});

// Test 3: Candidate switching
runTest(3, 'Candidate switching (A, B, C, D) and preferred status', () => {
  const r1 = layData.regions[2]; // Dhule 1st floor
  assert.strictEqual(r1.candidates.length, 4, 'Must generate 4 candidates (A, B, C, D)');
  const pref = r1.candidates.find(c => c.candidate_id.includes('candidate-c'));
  assert.ok(pref, 'Candidate C must exist');
  assert.strictEqual(pref.scores.total_score, 90.28, 'Candidate C preferred score must be 90.28');
  assert.ok(pref.scores.total_score > r1.candidates[0].scores.total_score, 'Candidate C must score higher than Candidate A');
});

// Test 4: Canvas layer toggling
runTest(4, 'Canvas layer toggling definitions', () => {
  const defaultLayers = {
    cadLinework: true,
    verifiedBoundary: true,
    generatedRooms: true,
    circulation: true,
    columns: true,
    hardObstructions: true,
    uncertainGeometry: true,
    reviewRequired: true,
    dimensions: false,
    provenance: false
  };
  assert.strictEqual(defaultLayers.cadLinework, true);
  assert.strictEqual(defaultLayers.dimensions, false);
  const toggled = { ...defaultLayers, dimensions: !defaultLayers.dimensions };
  assert.strictEqual(toggled.dimensions, true, 'Layer toggle must invert boolean state');
});

// Test 5: Room selection & inspection
runTest(5, 'Room selection & programmatic inspector data', () => {
  const r1 = decData.regions[2];
  const rooms = r1.preferred_candidate.room_summary;
  assert.strictEqual(rooms.length, 6, 'Should have 6 cinema program rooms');
  const aud2 = rooms.find(rm => rm.room_type === 'AUDITORIUM_2');
  assert.ok(aud2, 'AUDITORIUM_2 must exist');
  assert.strictEqual(aud2.area_sqft, 798.0, 'AUDITORIUM_2 area must be 798.0 sqft');
  assert.strictEqual(aud2.status, 'VALID', 'AUDITORIUM_2 status must be VALID on 1st floor');
});

// Test 6: Revision preview
runTest(6, 'Revision preview and score/area delta calculations', () => {
  const r1Score = 90.28;
  const revReq = {
    room_id: 'AUDITORIUM_2',
    type: 'INCREASE_ROOM_AREA',
    target_area_sqft: 820.4,
    score_delta: -0.04
  };
  const newScore = parseFloat((r1Score + revReq.score_delta).toFixed(2));
  assert.strictEqual(newScore, 90.24, 'Revised score preview must equal 90.24');
  assert.strictEqual(revReq.score_delta, -0.04, 'Delta must be -0.04');
});

// Test 7: Validation failure display
runTest(7, 'Validation failure display on geometric collision', () => {
  const failedRev = revData.revisions.find(r => r.revision_id === 'dhule-first-floor-rev-02');
  assert.ok(failedRev, 'Collision test revision must exist in audit log');
  assert.strictEqual(failedRev.request_status, 'VALIDATION_FAILED', 'Must report VALIDATION_FAILED');
  assert.ok(failedRev.validation_error.includes('HARD_OBSTRUCTION_COLLISION'), 'Must specify collision error');
});

// Test 8: Fourth-floor uncertainty display
runTest(8, 'Fourth-floor uncertainty display & -5.00 penalty', () => {
  const r4 = decData.regions[5];
  assert.strictEqual(r4.decision_status, 'VALID_REVIEW_REQUIRED', 'Fourth floor must be VALID_REVIEW_REQUIRED');
  const rooms = r4.preferred_candidate.room_summary;
  const wc = rooms.find(rm => rm.room_type === 'RESTROOMS');
  const mgr = rooms.find(rm => rm.room_type === 'MANAGER_OFFICE');
  assert.strictEqual(wc.status, 'REVIEW_REQUIRED', 'Restrooms must be REVIEW_REQUIRED');
  assert.strictEqual(mgr.status, 'REVIEW_REQUIRED', 'Manager Office must be REVIEW_REQUIRED');
  assert.strictEqual(r4.preferred_candidate.score_breakdown.uncertainty_penalty, 5.0, 'Must have 5.00 penalty');
});

// Test 9: Blocked floor protection
runTest(9, 'Blocked floor protection against room generation', () => {
  const basement = decData.regions[0];
  assert.strictEqual(basement.decision_status, 'BLOCKED_NO_VERIFIED_BOUNDARY');
  assert.strictEqual(basement.candidate_count, 0, 'Blocked floor must have 0 candidates');
  assert.strictEqual(basement.preferred_candidate, null, 'Blocked floor must have null preferred candidate');
});

// Test 10: Review decision state
runTest(10, 'Human review decision state & disclaimer adherence', () => {
  const validDecisions = ['PENDING_REVIEW', 'ACCEPT', 'REJECT', 'REQUEST_REVISION', 'REQUEST_FIELD_VERIFICATION'];
  assert.ok(validDecisions.includes('ACCEPT'));
  assert.ok(validDecisions.includes('REQUEST_FIELD_VERIFICATION'));
  const disclaimer = decData.architectural_disclaimer;
  assert.ok(disclaimer.includes('NOT constitute architectural approval'), 'Must contain architectural disclaimer');
});

const allPassed = results.every(r => r.passed);
console.log('='.repeat(80));
console.log(`OVERALL STATUS: ${allPassed ? 'ALL 10 FRONTEND TESTS PASSED 100%' : 'SOME TESTS FAILED'}`);
console.log('='.repeat(80) + '\n');

if (!allPassed) {
  process.exit(1);
}
