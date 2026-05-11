#!/usr/bin/env python3
"""Convert a JSONL file to a pretty JSON array.

Usage:
  python scripts/jsonl_to_json.py \
    --input data/manuals/multihop_raw.jsonl
"""
import argparse
import json
import os
from pathlib import Path


DEFAULT_INPUT = "data/manuals/multihop_raw.jsonl"


def default_output_path(input_path: Path) -> Path:
    return input_path.with_suffix(".json")


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_no}: {exc}") from exc
    return records


def main():
    parser = argparse.ArgumentParser(description="Convert JSONL to pretty JSON array")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Input JSONL file")
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file. Defaults to the same directory and basename as input.",
    )
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else default_output_path(input_path)

    records = load_jsonl(input_path)
    os.makedirs(output_path.parent, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=args.indent)
        f.write("\n")

    print(f"Loaded {len(records)} records from {input_path}")
    print(f"Wrote JSON array to {output_path}")


if __name__ == "__main__":
    main()
