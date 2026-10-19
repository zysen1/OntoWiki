"""Command line for compile, lint, query, eval, demo, and the MCP server."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ontowiki.demo.export import build_timeline, committed_timeline_matches, dump_timeline
from ontowiki.eval.harness import committed_matches, dump_eval, run_eval
from ontowiki.lint.agent import LintAgent, write_review
from ontowiki.paths import committed_eval, committed_timeline
from ontowiki.query.ask import ask
from ontowiki.service import Workspace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ontowiki", description="Ontology-constrained temporal wiki")
    sub = parser.add_subparsers(dest="cmd", required=True)

    compile_parser = sub.add_parser("compile", help="compile sources into a workspace")
    compile_parser.add_argument("--ontology", type=Path, required=True)
    compile_parser.add_argument("--sources", type=Path, required=True)
    compile_parser.add_argument("--out", type=Path, required=True)
    compile_parser.add_argument("--graphiti", action="store_true", help="also mirror episodes to Graphiti if configured")

    lint_parser = sub.add_parser("lint", help="write a review of contradictions, stale claims, and orphans")
    lint_parser.add_argument("--workspace", type=Path, required=True)
    lint_parser.add_argument("--as-of", default=None)

    query_parser = sub.add_parser("query", help="ask the compiled wiki")
    query_parser.add_argument("question")
    query_parser.add_argument("--workspace", type=Path, required=True)
    query_parser.add_argument("--as-of", default=None)
    query_parser.add_argument("--depth", type=int, default=3)

    eval_parser = sub.add_parser("eval", help="compare OntoWiki with vector RAG on the bundled notes")
    eval_parser.add_argument("--out", type=Path, default=None)
    eval_parser.add_argument("--check", action="store_true", help="exit 1 if the live run differs from the committed JSON")

    demo_parser = sub.add_parser("demo", help="write the timeline JSON the web view scrubs")
    demo_parser.add_argument("--out", type=Path, default=None)
    demo_parser.add_argument("--check", action="store_true")

    mcp_parser = sub.add_parser("mcp", help="serve query, claim, and provenance tools over MCP")
    mcp_parser.add_argument("--workspace", type=Path, required=True)
    mcp_parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    mcp_parser.add_argument("--port", type=int, default=8200)

    args = parser.parse_args(argv)
    if args.cmd == "compile":
        return _compile(args)
    if args.cmd == "lint":
        return _lint(args)
    if args.cmd == "query":
        return _query(args)
    if args.cmd == "eval":
        return _eval(args)
    if args.cmd == "demo":
        return _demo(args)
    if args.cmd == "mcp":
        return _mcp(args)
    return 2


def _compile(args: argparse.Namespace) -> int:
    from ontowiki.compile.compiler import compile_workspace
    from ontowiki.kg.graphiti_backend import client_from_env

    client = client_from_env() if args.graphiti else None
    if args.graphiti and client is None:
        print("Graphiti mirror skipped: set GRAPHITI_NEO4J_URI and install graphiti-core.", file=sys.stderr)
    report = compile_workspace(args.ontology, args.sources, args.out, graphiti_client=client)
    print(
        f"accepted {report.accepted} claims, {report.contradictions} contradictions, "
        f"{report.superseded} superseded, {len(report.pages)} pages"
    )
    for rejection in report.rejected:
        print(f"rejected {rejection.source}: {rejection.message}", file=sys.stderr)
    return 0 if report.ok else 1


def _lint(args: argparse.Namespace) -> int:
    workspace = Workspace(args.workspace)
    try:
        report = LintAgent(workspace.store, workspace.ontology, workspace.wiki_dir).run(args.as_of)
        path = write_review(report, workspace.wiki_dir)
    finally:
        workspace.close()
    print(path.read_text(encoding="utf-8"))
    return 0


def _query(args: argparse.Namespace) -> int:
    workspace = Workspace(args.workspace)
    try:
        result = ask(workspace.store, args.question, as_of=args.as_of, depth=args.depth)
    finally:
        workspace.close()
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


def _eval(args: argparse.Namespace) -> int:
    payload = run_eval()
    text = dump_eval(payload)
    if args.check and not committed_matches(payload):
        print(f"eval drifted from {committed_eval()}", file=sys.stderr)
        return 1
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    elif not args.check:
        print(text, end="")
    return 0


def _demo(args: argparse.Namespace) -> int:
    payload = build_timeline()
    if args.check and not committed_timeline_matches(payload):
        print(f"timeline drifted from {committed_timeline()}", file=sys.stderr)
        return 1
    if args.out or not args.check:
        destination = args.out or committed_timeline()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(dump_timeline(payload), encoding="utf-8")
        print(destination)
    return 0


def _mcp(args: argparse.Namespace) -> int:
    from ontowiki.mcp_server.server import build_server

    server = build_server(args.workspace)
    if args.transport == "streamable-http":
        server.settings.host = "127.0.0.1"
        server.settings.port = args.port
        server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")
    return 0
