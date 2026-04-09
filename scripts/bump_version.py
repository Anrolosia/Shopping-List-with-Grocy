#!/usr/bin/env python3
"""Bump the version in a manifest.json file.

Usage: python3 scripts/bump_version.py <manifest_path> <patch|minor|major>
"""
import json
import sys

manifest_path = sys.argv[1]
bump_type = sys.argv[2]

with open(manifest_path, "r") as f:
    manifest = json.load(f)

parts = list(map(int, manifest["version"].split(".")))
idx = {"major": 0, "minor": 1, "patch": 2}[bump_type]
parts[idx] += 1
for i in range(idx + 1, 3):
    parts[i] = 0

manifest["version"] = ".".join(map(str, parts))

with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")

print(f"Bumped to {manifest['version']}")