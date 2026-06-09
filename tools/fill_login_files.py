#!/usr/bin/env python3
"""Fill the <LOGIN_FILE_{site}> placeholders in the dataset JSONLs with the per-site
login-trace paths listed in dataset/login_files.csv.

Run once after recording your own login traces and filling in the CSV:

    python tools/fill_login_files.py

Each row of dataset/login_files.csv maps a site (the `web_name`) to the path of your
recorded login trace, e.g.:

    site,login_file
    Wolfram,login_traces/Wolfram_login/session_xxx/session-xxx.json

Sites left blank in the CSV keep their <LOGIN_FILE_{site}> placeholder.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "dataset" / "login_files.csv"
TARGETS = [
    "dataset/tasks_with_navigation.jsonl",
    "dataset/tasks_without_navigation.jsonl",
    "dataset/artifact_test.jsonl",
]


def load_mapping():
    mapping = {}
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            site = (row.get("site") or "").strip()
            path = (row.get("login_file") or "").strip()
            if site and path:
                mapping[site] = path
    return mapping


def main():
    mapping = load_mapping()
    if not mapping:
        print(f"No login_file paths filled in {CSV_PATH} - nothing to do.")
        return
    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            continue
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        filled = 0
        unresolved = set()
        for i, line in enumerate(lines):
            s = line.rstrip("\n")
            if not s.strip():
                continue
            obj = json.loads(s)
            lcf = obj.get("login_click_file")
            if isinstance(lcf, str) and lcf.startswith("<LOGIN_FILE_") and lcf.endswith(">"):
                site = lcf[len("<LOGIN_FILE_"):-1]
                if site in mapping:
                    obj["login_click_file"] = mapping[site]
                    lines[i] = json.dumps(obj) + ("\n" if line.endswith("\n") else "")
                    filled += 1
                else:
                    unresolved.add(site)
        p.write_text("".join(lines), encoding="utf-8")
        msg = f"{rel}: filled {filled}"
        if unresolved:
            msg += f"  | not in CSV (left as placeholder): {sorted(unresolved)}"
        print(msg)


if __name__ == "__main__":
    main()
