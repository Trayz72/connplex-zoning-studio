#!/usr/bin/env python3
"""
convert.py
Converts DWG <-> DXF files using ODA File Converter.
Usage:
  python3 convert.py <input_file_path> <target_format: dxf|dwg> [output_folder]
"""

import sys
import os
import shutil
import subprocess
import tempfile

def find_oda_executable():
    # 1. Explicit environment variable
    env_path = os.environ.get("ODA_PATH")
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path

    # 2. Standard names in PATH
    for name in ["ODAFileConverter", "oda-file-converter", "ODAFileConverter_QT6"]:
        found = shutil.which(name)
        if found:
            return found

    # 3. Known common install locations
    candidates = [
        "/usr/bin/ODAFileConverter",
        "/usr/local/bin/ODAFileConverter",
        "/opt/ODAFileConverter/ODAFileConverter",
        "/opt/oda/ODAFileConverter",
        os.path.expanduser("~/.local/bin/ODAFileConverter"),
        os.path.expanduser("~/.local/ODAFileConverter/ODAFileConverter"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "oda/usr/bin/ODAFileConverter"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "oda/ODAFileConverter"),
    ]
    for cand in candidates:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand

    return None

def convert(input_path: str, target_format: str, output_folder: str = None) -> str:
    input_path = os.path.abspath(input_path)
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    target_format = target_format.lower().lstrip(".")
    if target_format not in ["dxf", "dwg"]:
        raise ValueError(f"Unsupported target format: '{target_format}'. Must be 'dxf' or 'dwg'.")

    output_format = target_format.upper()
    output_version = "ACAD2018"

    if output_folder:
        output_folder = os.path.abspath(output_folder)
        os.makedirs(output_folder, exist_ok=True)
    else:
        output_folder = os.path.dirname(input_path)

    oda_bin = find_oda_executable()
    if not oda_bin:
        raise RuntimeError("ODA File Converter executable not found. Please ensure ODA File Converter is installed.")

    input_filename = os.path.basename(input_path)
    base_name, in_ext_raw = os.path.splitext(input_filename)
    in_ext = in_ext_raw.lstrip(".").upper() or "DWG"
    expected_output = os.path.join(output_folder, f"{base_name}.{target_format}")

    # Use isolated temp directories so only the requested file is converted
    with tempfile.TemporaryDirectory(prefix="oda_in_") as temp_in, \
         tempfile.TemporaryDirectory(prefix="oda_out_") as temp_out:

        temp_input_file = os.path.join(temp_in, input_filename)
        shutil.copy2(input_path, temp_input_file)

        # Arguments: <Source dir> <Target dir> <Output version> <Output format> <Recurse> <Audit> <Filter>
        cmd = [
            oda_bin,
            temp_in,
            temp_out,
            output_version,
            output_format,
            "0",      # Recurse = 0
            "1",      # Audit = 1
            input_filename
        ]

        env = os.environ.copy()
        if "DISPLAY" not in env or not env["DISPLAY"]:
            env["DISPLAY"] = ":0"

        oda_dir = os.path.dirname(oda_bin)
        lib_dirs = [
            oda_dir,
            os.path.join(oda_dir, "../lib"),
            os.path.join(oda_dir, "lib"),
            "/usr/lib/x86_64-linux-gnu"
        ]
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = ":".join([d for d in lib_dirs if os.path.isdir(d)] + ([existing_ld] if existing_ld else []))

        result = subprocess.run(cmd, capture_output=True, text=True, env=env)

        err_files = [f for f in os.listdir(temp_out) if f.lower().endswith(".err")]
        if err_files:
            err_details = []
            for ef in err_files:
                with open(os.path.join(temp_out, ef), "r", encoding="utf-8", errors="replace") as f:
                    content = f.read().strip()
                    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
                    non_header_lines = [ln for ln in lines if not ln.startswith("OdError thrown")]
                    if non_header_lines:
                        err_details.append(": ".join(non_header_lines))
                    else:
                        err_details.append(content)
            underlying = " | ".join(err_details)
            raise RuntimeError(f"Could not convert this {in_ext} file: {underlying}")

        out_files = [f for f in os.listdir(temp_out) if f.lower().endswith(f".{target_format}")]
        if not out_files:
            raise RuntimeError(
                f"Could not convert this {in_ext} file: ODA File Converter did not produce a .{target_format} file (exit code {result.returncode})"
            )

        converted_file = os.path.join(temp_out, out_files[0])
        shutil.move(converted_file, expected_output)

    print(f"Conversion successful:")
    print(f"  Input:  {input_path}")
    print(f"  Output: {expected_output} ({os.path.getsize(expected_output)} bytes)")
    return expected_output

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 convert.py <input_file_path> <target_format: dxf|dwg> [output_folder]")
        sys.exit(1)

    in_file = sys.argv[1]
    tgt_format = sys.argv[2]
    out_dir = sys.argv[3] if len(sys.argv) > 3 else None

    try:
        convert(in_file, tgt_format, out_dir)
    except Exception as err:
        print(f"{err}", file=sys.stderr)
        sys.exit(1)

