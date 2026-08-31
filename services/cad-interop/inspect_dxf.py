#!/usr/bin/env python3
"""
inspect_dxf.py
Opens a DXF file using ezdxf and prints:
- Total entity count
- List of distinct entity types found with counts
"""

import sys
import os
from collections import Counter
import ezdxf

def inspect(dxf_path: str):
    if not os.path.isfile(dxf_path):
        print(f"Error: File '{dxf_path}' not found.", file=sys.stderr)
        sys.exit(1)

    print(f"File: {os.path.basename(dxf_path)}")
    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception as e:
        print(f"Error reading DXF file: {e}", file=sys.stderr)
        sys.exit(1)

    # Count entities across layouts (modelspace + any paper space)
    entity_counts = Counter()
    for layout in doc.layouts:
        for entity in layout:
            entity_counts[entity.dxftype()] += 1

    total_entities = sum(entity_counts.values())

    print(f"DXF Version: {doc.dxfversion}")
    print(f"Total entity count: {total_entities}")
    print("Distinct entity types:")
    for entity_type, count in sorted(entity_counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {entity_type}: {count}")

    return total_entities, entity_counts

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 inspect_dxf.py <path_to_dxf_file>")
        sys.exit(1)
    inspect(sys.argv[1])
