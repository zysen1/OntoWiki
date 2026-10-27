"""The scheduled Security gate alerts on new advisories only."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "security_schedule_gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("security_schedule_gate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load_gate()


def test_npm_extract_keeps_blocking_advisories_only():
    report = {
        "vulnerabilities": {
            "zod": {
                "severity": "high",
                "via": [
                    {
                        "severity": "high",
                        "title": "Zod memory exhaustion",
                        "url": "https://github.com/advisories/GHSA-mrhx-c7xc-m3w5",
                    }
                ],
            },
            "leftpad": {
                "severity": "low",
                "via": [
                    {
                        "severity": "low",
                        "url": "https://github.com/advisories/GHSA-1111-2222-3333",
                    }
                ],
            },
            "parent": {"severity": "high", "via": ["zod"]},
        }
    }
    assert gate.extract_npm(report) == [frozenset({"ghsa-mrhx-c7xc-m3w5"})]


def test_pip_extract_includes_aliases():
    report = {
        "dependencies": [
            {
                "name": "opentelemetry-api",
                "version": "1.39.1",
                "vulns": [
                    {
                        "id": "CVE-2026-114603",
                        "aliases": ["GHSA-xcq7-p3pf-p88h"],
                    }
                ],
            }
        ]
    }
    assert gate.extract_pip(report) == [frozenset({"CVE-2026-114603", "ghsa-xcq7-p3pf-p88h"})]


def test_sarif_extract_reads_rule_and_aliases():
    report = {
        "runs": [
            {
                "tool": {
                    "driver": {
                        "rules": [
                            {
                                "id": "CVE-2021-44906",
                                "deprecatedIds": ["CVE-2021-44906", "GHSA-xvch-5gv4-984h"],
                            }
                        ]
                    }
                },
                "results": [
                    {
                        "ruleId": "CVE-2021-44906",
                        "ruleIndex": 0,
                        "message": {"text": "also known as 'GHSA-xvch-5gv4-984h'"},
                    }
                ],
            }
        ]
    }
    assert gate.extract_sarif(report) == [frozenset({"CVE-2021-44906", "ghsa-xvch-5gv4-984h"})]


def test_strict_mode_fails_closed_and_honors_allowlist():
    groups = [frozenset({"ghsa-mrhx-c7xc-m3w5"})]
    assert gate.failing_groups(groups, set(), None) == groups
    assert gate.failing_groups(groups, {"ghsa-mrhx-c7xc-m3w5"}, None) == []


def test_schedule_mode_ignores_previously_reported_ids():
    groups = [frozenset({"CVE-2026-114603", "ghsa-xcq7-p3pf-p88h"})]
    assert gate.failing_groups(groups, set(), {"CVE-2026-114603"}) == []
    assert gate.failing_groups(groups, set(), set()) == groups


def test_schedule_mode_still_reports_a_new_id_beside_a_known_one():
    known = frozenset({"ghsa-mrhx-c7xc-m3w5"})
    fresh = frozenset({"ghsa-2464-fhr4-w9xw"})
    failing = gate.failing_groups([known, fresh], set(), {"ghsa-mrhx-c7xc-m3w5"})
    assert failing == [fresh]


def test_write_osv_config_lists_only_allowlisted_ids(tmp_path: Path):
    allowlist = tmp_path / "allowlist.txt"
    dest = tmp_path / "osv-scanner.toml"
    allowlist.write_text("# comment\nGHSA-mrhx-c7xc-m3w5\n")
    gate.write_osv_config(allowlist, dest)
    text = dest.read_text()
    assert 'id = "ghsa-mrhx-c7xc-m3w5"' in text
    assert "[[IgnoredVulns]]" in text
    assert "comment" not in text


def test_allowlist_comments_are_ignored(tmp_path: Path):
    path = tmp_path / "allowlist.txt"
    path.write_text("# note\n\nghsa-mrhx-c7xc-m3w5\n")
    assert gate.load_allowlist(path) == {"ghsa-mrhx-c7xc-m3w5"}


def test_gate_cli_schedule_passes_when_the_previous_scan_had_the_advisory(tmp_path: Path):
    findings = tmp_path / "findings.txt"
    previous = tmp_path / "previous.txt"
    findings.write_text("ghsa-mrhx-c7xc-m3w5\n")
    previous.write_text("ghsa-mrhx-c7xc-m3w5\n")
    code = gate.main(
        [
            "security_schedule_gate.py",
            "gate",
            "--mode",
            "schedule",
            "--findings",
            str(findings),
            "--previous",
            str(previous),
            "--audit-failed",
        ]
    )
    assert code == 0


def test_gate_cli_fails_closed_when_the_report_has_no_ids(tmp_path: Path):
    findings = tmp_path / "findings.txt"
    findings.write_text("")
    code = gate.main(
        [
            "security_schedule_gate.py",
            "gate",
            "--mode",
            "strict",
            "--findings",
            str(findings),
            "--audit-failed",
        ]
    )
    assert code == 1
