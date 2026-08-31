#!/usr/bin/env python3
"""
test_zoning_input.py
Unit tests and acceptance checks for Milestone M2 Zoning Input Contract.
Validates zoning_inputs_v1.json and zoning_program_v1.json against all requirements.
"""

import os
import json
import unittest
from shapely.geometry import Polygon

class TestZoningInputContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(base_dir, "output")
        cls.inputs_file = os.path.join(output_dir, "zoning_inputs_v1.json")
        cls.report_file = os.path.join(output_dir, "zoning_input_validation_report.json")
        cls.program_file = os.path.join(base_dir, "zoning_program_v1.json")

        with open(cls.inputs_file, "r", encoding="utf-8") as f:
            cls.inputs = json.load(f)
        with open(cls.program_file, "r", encoding="utf-8") as f:
            cls.program = json.load(f)

    def test_program_schema_validity(self):
        """Validates that zoning_program_v1.json has valid requirements structure."""
        self.assertEqual(self.program.get("version"), "1.0")
        self.assertIn("rooms", self.program)
        self.assertIn("required_adjacencies", self.program)
        self.assertIn("preferred_adjacencies", self.program)
        self.assertIn("circulation_constraints", self.program)
        self.assertIn("global_constraints", self.program)

    def test_total_regions_count(self):
        """Verifies that all 8 PlanRegions are present."""
        self.assertEqual(self.inputs["total_regions"], 8)
        self.assertEqual(len(self.inputs["regions"]), 8)

    def test_region_id_uniqueness(self):
        """Check 1: Every region has a unique region_id."""
        rids = [r["region_id"] for r in self.inputs["regions"]]
        self.assertEqual(len(rids), len(set(rids)))

    def test_unverified_regions_status_and_null_area(self):
        """Checks 3, 4, 5: Unverified regions must have UNUSABLE_NO_VERIFIED_BOUNDARY and null area."""
        unverified_ids = ["dhule-basement", "dhule-ground", "vadodara-option-1", "vadodara-option-2"]
        for r in self.inputs["regions"]:
            if r["region_id"] in unverified_ids:
                self.assertEqual(r["zoning_status"], "UNUSABLE_NO_VERIFIED_BOUNDARY")
                self.assertIsNone(r["usable_planning_area_sqft"])
                self.assertIsNone(r["verified_boundary"]["geometry"])

    def test_verified_regions_status_and_area(self):
        """Check 11: Dhule 1st-4th floors must be ZONING_READY with exact Step 5 usable areas."""
        expected_s5 = {
            "dhule-first-floor": 5215.06,
            "dhule-second-floor": 5216.19,
            "dhule-third-floor": 5216.20,
            "dhule-fourth-floor": 5222.04
        }
        for r in self.inputs["regions"]:
            rid = r["region_id"]
            if rid in expected_s5:
                self.assertEqual(r["zoning_status"], "ZONING_READY")
                self.assertEqual(r["verified_boundary"]["status"], "VERIFIED")
                self.assertAlmostEqual(r["usable_planning_area_sqft"], expected_s5[rid], places=2)
                self.assertAlmostEqual(r["verified_boundary"]["area_sqft"], 5242.03 if "fourth" not in rid else 5242.04, places=2)

    def test_fourth_floor_lift_22D8(self):
        """Check 12: Fourth floor must explicitly preserve lift 22D8."""
        r4 = next(r for r in self.inputs["regions"] if r["region_id"] == "dhule-fourth-floor")
        nv_handles = [h for nv in r4["additional_verified_obstructions"] for h in nv["source_handles"]]
        self.assertIn("22D8", nv_handles)
        nv_item = next(nv for nv in r4["additional_verified_obstructions"] if "22D8" in nv["source_handles"])
        self.assertAlmostEqual(nv_item["area_sqft"], 3.61, places=2)

    def test_stairs_remain_uncertain(self):
        """Check 8: All stairs MUST remain FOOTPRINT_UNCERTAIN."""
        for r in self.inputs["regions"]:
            for st in r["circulation_elements"]:
                if st.get("category") == "STAIR":
                    self.assertEqual(st.get("status"), "FOOTPRINT_UNCERTAIN")

    def test_provenance_integrity(self):
        """Checks 9 & 10: All obstructions and boundaries preserve provenance."""
        for r in self.inputs["regions"]:
            for ho in r["hard_obstructions"]:
                self.assertIn("provenance", ho)
                self.assertTrue(ho["source_handle"])
            if r["verified_boundary"]["status"] == "VERIFIED":
                self.assertIn("provenance", r["verified_boundary"])

if __name__ == "__main__":
    unittest.main()
