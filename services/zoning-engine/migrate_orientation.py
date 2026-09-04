"""
One-time data migration: applies the same Y-axis flip cad_extraction.py's
_identity_tf now applies at extraction time (see its own docstring) to every
project's ALREADY-STORED geometry/requirements/run/layout JSON files.

Why this is needed: the orientation fix only changes what happens on a FRESH
extraction (a new upload, or an existing project's "Replace CAD File"). Every
project extracted before that fix has its boundary/obstacle/room coordinates
saved in the old, un-flipped convention — those files are static, on disk;
nothing re-extracts them on its own. Left alone, those projects would keep
rendering vertically mirrored in the web editor forever, while any NEW
project would render correctly — a confusing, silent inconsistency.

What does NOT need migrating: already-generated export files (PDF/DXF/DWG in
each project's exports/ directory). Those were produced by the OLD
export_pdf.py/export_dxf.py, which (before this session's fix) read the OLD,
un-flipped points_ft directly into an inherently Y-up target (DXF is
native Y-up; reportlab's canvas is native Y-up) with no transform at all —
so old exports were already correctly oriented, and stay that way untouched.
Only the JSON files consumed by the Y-down SVG web viewer need the flip.

Usage:
    python3 migrate_orientation.py --dry-run   # report what would change, write nothing
    python3 migrate_orientation.py             # apply, with a .bak backup of every file touched

Idempotent: writes a `.orientation_migrated` marker file per project after a
successful (non-dry-run) migration and skips any project that already has
one, so re-running this script is always safe.
"""
import argparse
import json
import os
import shutil

import storage

MARKER_NAME = ".orientation_migrated"


def flip_points(points):
    return [[p[0], -p[1]] for p in points]


def flip_point(pt):
    return [pt[0], -pt[1]] if pt else pt


def flip_bbox(bbox):
    if not bbox:
        return bbox
    return {**bbox, "min_y": -bbox["max_y"], "max_y": -bbox["min_y"]}


def flip_room(room):
    if room.get("geometry_points_ft"):
        room["geometry_points_ft"] = flip_points(room["geometry_points_ft"])
        xs = [p[0] for p in room["geometry_points_ft"]]
        ys = [p[1] for p in room["geometry_points_ft"]]
        # origin_ft is documented as the room's own min-corner — recomputed
        # fresh from the flipped points rather than transformed in place,
        # since flipping Y swaps which corner is "min" (see the equivalent
        # note in export_dxf.py/export_pdf.py from this session's live fix).
        room["origin_ft"] = [min(xs), min(ys)]
    return room


def flip_obstacle(obs):
    if isinstance(obs, dict):
        if obs.get("points_ft"):
            obs["points_ft"] = flip_points(obs["points_ft"])
        return obs
    return flip_points(obs)  # bare point-list form, seen in a few older records


def flip_raw_geometry(raw):
    """Two real shapes exist for this structure in stored data: the simple
    per-region/whole-drawing backdrop (lines as bare [pt, pt] pairs, text
    position under "position") and the richer full_raw_geometry backdrop
    (lines as {id, a, b, layer, category, curve_group} dicts, text position
    under "position_ft") — both handled here rather than assuming one."""
    if not raw:
        return raw
    if raw.get("lines"):
        flipped = []
        for line in raw["lines"]:
            if isinstance(line, dict):
                line["a"] = flip_point(line["a"])
                line["b"] = flip_point(line["b"])
                flipped.append(line)
            else:
                a, b = line
                flipped.append([flip_point(a), flip_point(b)])
        raw["lines"] = flipped
    if raw.get("circles"):
        for c in raw["circles"]:
            c["center"] = flip_point(c["center"])
    if raw.get("texts"):
        for t in raw["texts"]:
            if "position" in t:
                t["position"] = flip_point(t["position"])
            elif "position_ft" in t:
                t["position_ft"] = flip_point(t["position_ft"])
    if raw.get("closed_shapes"):
        for shape in raw["closed_shapes"]:
            if shape.get("points_ft"):
                shape["points_ft"] = flip_points(shape["points_ft"])
    if raw.get("bounds_ft"):
        raw["bounds_ft"] = flip_bbox(raw["bounds_ft"])
    return raw


def migrate_geometry(d):
    changed = False
    for key in ("raw_geometry", "full_raw_geometry"):
        if d.get(key):
            flip_raw_geometry(d[key])
            changed = True
    for region in d.get("regions", []):
        b = region.get("boundary")
        if b and b.get("points_ft"):
            b["points_ft"] = flip_points(b["points_ft"])
            b["bounding_box_ft"] = flip_bbox(b.get("bounding_box_ft"))
            changed = True
        for obs in region.get("obstacles", []):
            flip_obstacle(obs)
            changed = True
        for tl in region.get("text_labels", []):
            if tl.get("position_ft"):
                tl["position_ft"] = flip_point(tl["position_ft"])
                changed = True
        if region.get("raw_geometry"):
            flip_raw_geometry(region["raw_geometry"])
            changed = True
    return changed


def migrate_requirements(d):
    changed = False
    if d.get("entry_point_ft"):
        d["entry_point_ft"] = flip_point(d["entry_point_ft"])
        changed = True
    if d.get("exit_points_ft"):
        d["exit_points_ft"] = flip_points(d["exit_points_ft"])
        changed = True
    return changed


def migrate_layout(d):
    changed = False
    if d.get("boundary_points_ft"):
        d["boundary_points_ft"] = flip_points(d["boundary_points_ft"])
        changed = True
    for obs in d.get("obstacles", []):
        flip_obstacle(obs)
        changed = True
    for room in d.get("rooms", []):
        flip_room(room)
        changed = True
    return changed


def migrate_run(d):
    changed = False
    for candidate in d.get("candidates", []):
        for room in candidate.get("rooms", []):
            flip_room(room)
            changed = True
    return changed


def _process_file(path, migrate_fn, dry_run, report):
    data = storage.read_json(path)
    if not data:
        return
    changed = migrate_fn(data)
    if changed:
        report.append(os.path.relpath(path, storage.STORAGE_ROOT))
        if not dry_run:
            shutil.copyfile(path, path + ".bak")
            storage.write_json(path, data)


def migrate_project(project_id, dry_run):
    d = storage.project_dir(project_id)
    marker = os.path.join(d, MARKER_NAME)
    if os.path.isfile(marker):
        return None  # already migrated, real idempotency guard

    report = []
    _process_file(storage.geometry_path(project_id), migrate_geometry, dry_run, report)
    _process_file(storage.requirements_path(project_id), migrate_requirements, dry_run, report)
    _process_file(storage.layout_path(project_id), migrate_layout, dry_run, report)
    _process_file(storage.latest_run_path(project_id), migrate_run, dry_run, report)
    runs_dir = os.path.join(d, "runs")
    if os.path.isdir(runs_dir):
        for fname in os.listdir(runs_dir):
            _process_file(os.path.join(runs_dir, fname), migrate_run, dry_run, report)

    if not dry_run:
        with open(marker, "w") as f:
            f.write(storage.now_iso())

    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing anything.")
    args = parser.parse_args()

    if not os.path.isdir(storage.STORAGE_ROOT):
        print("No storage directory found — nothing to migrate.")
        return

    project_ids = sorted(
        name for name in os.listdir(storage.STORAGE_ROOT)
        if os.path.isdir(os.path.join(storage.STORAGE_ROOT, name))
    )
    print(f"{'DRY RUN — ' if args.dry_run else ''}Found {len(project_ids)} project(s) in storage.\n")

    for pid in project_ids:
        report = migrate_project(pid, args.dry_run)
        if report is None:
            print(f"  {pid}: already migrated, skipped.")
        elif not report:
            print(f"  {pid}: no coordinate data found, nothing to do.")
        else:
            verb = "would touch" if args.dry_run else "touched"
            print(f"  {pid}: {verb} {len(report)} file(s):")
            for f in report:
                print(f"      {f}")

    if args.dry_run:
        print("\nDry run only — nothing was written. Re-run without --dry-run to apply.")
    else:
        print("\nDone. A .bak copy of every changed file was written alongside it.")


if __name__ == "__main__":
    main()
