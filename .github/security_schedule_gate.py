#!/usr/bin/env python3
"""Gate Security workflow findings.

Push and pull_request fail on every moderate-or-higher advisory that is not
in the documented no-fix allowlist. The daily schedule still scans, but it
fails only when such an advisory was not already reported by the previous
scheduled run, so the owner is emailed when a new issue appears rather than
every day for the same set.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BLOCKING_NPM_SEVERITIES = {"moderate", "high", "critical"}
ADVISORY_ID = re.compile(
    r"GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}|CVE-\d{4}-\d+|PYSEC-\d{4}-\d+",
    re.IGNORECASE,
)


def normalize_id(value: str) -> str:
    text = value.strip()
    upper = text.upper()
    if upper.startswith("GHSA-"):
        return text.lower()
    if upper.startswith(("CVE-", "PYSEC-")):
        return upper
    return text


def ids_in_text(value: str) -> set[str]:
    return {normalize_id(match) for match in ADVISORY_ID.findall(value or "")}


def dedupe(groups: list[set[str]]) -> list[frozenset[str]]:
    seen: list[frozenset[str]] = []
    known: set[frozenset[str]] = set()
    for group in groups:
        frozen = frozenset(group)
        if not frozen or frozen in known:
            continue
        known.add(frozen)
        seen.append(frozen)
    return seen


def format_findings(groups: list[frozenset[str]]) -> str:
    lines = [",".join(sorted(group)) for group in groups]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def parse_findings(text: str) -> list[frozenset[str]]:
    groups: list[set[str]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        ids = {normalize_id(part) for part in line.split(",") if part.strip()}
        if ids:
            groups.append(ids)
    return dedupe(groups)


def flatten(groups: list[frozenset[str]]) -> set[str]:
    found: set[str] = set()
    for group in groups:
        found.update(group)
    return found


def load_allowlist(path: Path | None) -> set[str]:
    if path is None or not path.is_file():
        return set()
    return flatten(parse_findings(path.read_text()))


def extract_npm(report: dict) -> list[frozenset[str]]:
    groups: list[set[str]] = []
    vulnerabilities = report.get("vulnerabilities") or {}
    for vuln in vulnerabilities.values():
        parent_severity = str(vuln.get("severity") or "").lower()
        for via in vuln.get("via") or []:
            if not isinstance(via, dict):
                continue
            severity = str(via.get("severity") or parent_severity).lower()
            if severity not in BLOCKING_NPM_SEVERITIES:
                continue
            ids = ids_in_text(str(via.get("url") or ""))
            ids.update(ids_in_text(str(via.get("title") or "")))
            if ids:
                groups.append(ids)
    return dedupe(groups)


def extract_pip(report: dict | list) -> list[frozenset[str]]:
    dependencies = report.get("dependencies") if isinstance(report, dict) else report
    groups: list[set[str]] = []
    for dep in dependencies or []:
        for vuln in dep.get("vulns") or []:
            ids = ids_in_text(str(vuln.get("id") or ""))
            if vuln.get("id"):
                ids.add(normalize_id(str(vuln["id"])))
            for alias in vuln.get("aliases") or []:
                ids.add(normalize_id(str(alias)))
                ids.update(ids_in_text(str(alias)))
            if ids:
                groups.append(ids)
    return dedupe(groups)


def extract_sarif(report: dict) -> list[frozenset[str]]:
    groups: list[set[str]] = []
    for run in report.get("runs") or []:
        rules = ((run.get("tool") or {}).get("driver") or {}).get("rules") or []
        for result in run.get("results") or []:
            ids = ids_in_text(str(result.get("ruleId") or ""))
            message = ((result.get("message") or {}).get("text")) or ""
            ids.update(ids_in_text(str(message)))
            rule_index = result.get("ruleIndex")
            if isinstance(rule_index, int) and 0 <= rule_index < len(rules):
                rule = rules[rule_index]
                ids.update(ids_in_text(str(rule.get("id") or "")))
                for deprecated in rule.get("deprecatedIds") or []:
                    ids.add(normalize_id(str(deprecated)))
                    ids.update(ids_in_text(str(deprecated)))
            if ids:
                groups.append(ids)
    return dedupe(groups)


def failing_groups(
    groups: list[frozenset[str]],
    allow_ids: set[str],
    previous_ids: set[str] | None,
) -> list[frozenset[str]]:
    failing: list[frozenset[str]] = []
    for group in groups:
        if group & allow_ids:
            continue
        if previous_ids is not None and group & previous_ids:
            continue
        failing.append(group)
    return failing


def write_osv_config(allowlist: Path, dest: Path) -> None:
    """Write the config OSV-Scanner 2.0.2 loads from the repository root.

    GitHub advisory aliases are filtered together, so one id from the
    allowlist suppresses the CVE and GHSA forms of that advisory.
    """
    lines = [
        "# Generated from .github/security-allowlist.txt.",
        "# Each id is an advisory with no patched release.",
        "",
    ]
    for advisory_id in sorted(load_allowlist(allowlist)):
        lines.extend(
            [
                "[[IgnoredVulns]]",
                f'id = "{advisory_id}"',
                'reason = "No patched release. See .github/security-allowlist.txt."',
                "",
            ]
        )
    dest.write_text("\n".join(lines))


def load_json(path: Path) -> dict | list:
    return json.loads(path.read_text())


def emit(groups: list[frozenset[str]]) -> int:
    sys.stdout.write(format_findings(groups))
    return 0


def read_groups(path: Path | None) -> list[frozenset[str]]:
    if path is None or not path.is_file():
        return []
    return parse_findings(path.read_text())


def run_gate(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="security_schedule_gate.py gate")
    parser.add_argument("--mode", choices=("strict", "schedule"), required=True)
    parser.add_argument("--findings", type=Path, required=True)
    parser.add_argument("--allowlist", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--audit-failed", action="store_true")
    args = parser.parse_args(argv)

    groups = read_groups(args.findings)
    allow_ids = load_allowlist(args.allowlist)
    previous_ids = flatten(read_groups(args.previous)) if args.mode == "schedule" else None
    if args.audit_failed and not groups:
        print("Scanner reported a failure but no advisory ids could be read.", file=sys.stderr)
        return 1

    failing = failing_groups(groups, allow_ids, previous_ids)
    if not failing:
        if args.mode == "schedule":
            print("No new advisories.")
        else:
            print("No advisories outside the allowlist.")
        return 0

    label = "New advisories" if args.mode == "schedule" else "Advisories outside the allowlist"
    print(f"{label}:", file=sys.stderr)
    for group in failing:
        print(",".join(sorted(group)), file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: security_schedule_gate.py extract-npm|extract-pip|extract-sarif|gate ...", file=sys.stderr)
        return 2
    command = argv[1]
    if command in {"extract-npm", "extract-pip", "extract-sarif"}:
        if len(argv) != 3:
            print(f"usage: security_schedule_gate.py {command} REPORT", file=sys.stderr)
            return 2
        report = load_json(Path(argv[2]))
        if command == "extract-npm":
            return emit(extract_npm(report))
        if command == "extract-pip":
            return emit(extract_pip(report))
        return emit(extract_sarif(report))
    if command == "write-osv-config":
        if len(argv) != 4:
            print("usage: security_schedule_gate.py write-osv-config ALLOWLIST DEST", file=sys.stderr)
            return 2
        write_osv_config(Path(argv[2]), Path(argv[3]))
        return 0
    if command == "gate":
        return run_gate(argv[2:])
    print(f"unknown command {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
