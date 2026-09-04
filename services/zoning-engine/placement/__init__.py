"""Placement algorithms that go beyond layout_engine.py's original
fixed-step first-fit scan (_scan_place) — kept as a separate package
because these are genuinely different techniques (maximal-rectangle
detection, bounded backtracking, an exact combinatorial solver), not small
tweaks to the existing scan. layout_engine.py's interactive path
(_scan_place/_scan_place_best, used by every live Add-Zone click) is left
untouched; these modules are used where their extra cost is worth paying
(the custom-fit fallback, auto-layout's backtrack retry, and the opt-in
"Optimize Layout" action) — see
docs/prompts/component_placement_and_circulation_spec.md and this
project's LOG.md for the forensic finding that motivated them."""
