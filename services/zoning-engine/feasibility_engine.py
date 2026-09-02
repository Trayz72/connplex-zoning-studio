"""Real feasibility/compliance evaluation against the versioned ViabilityRule
registry — same logic as services/cad-interop/evaluate_feasibility.py, ported to a
plain function. Never returns a silent pass: a rule that can't be evaluated from
available measurements comes back INSUFFICIENT_DATA, not PASS."""
import rules_registry


def evaluate_rule(rule: dict, measurements: dict) -> dict:
    metric = rule["metric"]
    if rule.get("evaluable") is False or metric not in measurements or measurements[metric] is None:
        return {
            "rule_id": rule["rule_id"], "result": "INSUFFICIENT_DATA", "severity": rule["severity"],
            "metric": metric, "measured_value": None, "threshold": rule.get("threshold"),
            "source": rule["source"],
            "message": f"Cannot evaluate — {metric} is not available."
        }

    measured = measurements[metric]
    op = rule["operator"]
    if op == ">=":
        passed = measured >= rule["threshold"]
    elif op == "<=":
        passed = measured <= rule["threshold"]
    elif op == "==":
        passed = measured == rule["threshold"]
    elif op == "between":
        passed = rule["threshold_min"] <= measured <= rule["threshold_max"]
    else:
        passed = None

    threshold_display = rule.get("threshold", f"{rule.get('threshold_min')}-{rule.get('threshold_max')}")
    unit_suffix = f" {rule['unit']}" if rule.get("unit") else ""
    # Every message_template in the registry is authored describing the FAIL
    # condition only ("Clear height below 10'-0" minimum — NOT VIABLE."), never
    # a pass case — confirmed by reading every entry in rules_registry_v1.json.
    # Using it unconditionally (the previous behavior) meant a rule that
    # genuinely PASSED still displayed that failure-sounding sentence,
    # distinguished from a real failure only by a subtle text-color
    # difference in the frontend — found on a real project where clear
    # height measured 12ft against a 10ft minimum (a clear PASS) but the
    # feasibility panel read "Clear height below 10'-0" minimum — NOT
    # VIABLE." verbatim. A passed rule now always gets an honest, neutral
    # message built from the actual measured value instead.
    if passed:
        message = f"{metric} = {measured}{unit_suffix} meets the {threshold_display}{unit_suffix} requirement."
    else:
        message = rule.get("message_template") or f"{metric} = {measured} vs threshold {threshold_display}"
    return {
        "rule_id": rule["rule_id"], "result": "PASS" if passed else "FAIL", "severity": rule["severity"],
        "metric": metric, "measured_value": measured, "threshold": threshold_display, "unit": rule.get("unit"),
        "source": rule["source"], "source_section": rule.get("source_section"),
        "message": message
    }


def evaluate(property_type: str, measurements: dict) -> dict:
    rules = rules_registry.viability_rules(property_type)
    results = [evaluate_rule(r, measurements) for r in rules]

    hard_fails = [r for r in results if r["result"] == "FAIL" and r["severity"] == "HARD"]
    warnings = [r for r in results if r["result"] == "FAIL" and r["severity"] in ("SOFT", "WARNING")]
    insufficient = [r for r in results if r["result"] == "INSUFFICIENT_DATA"]

    if hard_fails:
        overall = "NOT_FEASIBLE"
    elif insufficient:
        overall = "INSUFFICIENT_DATA"
    elif warnings:
        overall = "CONDITIONALLY_FEASIBLE"
    else:
        overall = "FEASIBLE"

    return {
        "feasibility_result": overall,
        "property_type_assumed": property_type,
        "measurements": measurements,
        "hard_fail_count": len(hard_fails),
        "warning_count": len(warnings),
        "insufficient_data_count": len(insufficient),
        "rule_results": results
    }
