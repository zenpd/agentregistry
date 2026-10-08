#!/usr/bin/env python3
"""Agent Registry command line, for CI pipelines. Standard library only.

    export REGISTRY_URL=https://registry.example.com      # the UI address; /api/v1 is added
    export REGISTRY_API_KEY=ark_...                        # Settings → API keys (scope: register, certify_check)

    python registry_cli.py register agent.json            # create, or update declared fields
    python registry_cli.py check "Invoice Agent" --stage Production

`check` exits 0 when the agent may go to the stage, 1 when it may not (the
reasons are printed), 2 on a usage or connection error. `register` exits 0
when the agent was created, updated or unchanged."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def _call(method: str, path: str, body: dict | None = None) -> dict:
    base = os.environ.get("REGISTRY_URL", "").rstrip("/")
    key = os.environ.get("REGISTRY_API_KEY", "")
    if not base or not key:
        print("Set REGISTRY_URL and REGISTRY_API_KEY.", file=sys.stderr)
        sys.exit(2)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base}/api/v1{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        print(f"The registry answered HTTP {exc.code}: {detail}", file=sys.stderr)
        sys.exit(2)
    except urllib.error.URLError as exc:
        print(f"Could not reach the registry: {exc.reason}", file=sys.stderr)
        sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="registry_cli")
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register", help="Register or update an agent from a JSON manifest")
    reg.add_argument("manifest")
    chk = sub.add_parser("check", help="May the agent go to a stage? Exit 1 when not")
    chk.add_argument("agent", help="Agent id, slug or name")
    chk.add_argument("--stage", default="Production")
    args = parser.parse_args(argv)

    if args.command == "register":
        with open(args.manifest, encoding="utf-8") as f:
            manifest = json.load(f)
        result = _call("POST", "/ci/register", manifest)
        print(f"{result['status']}: {result['id']}" + (f" ({', '.join(result['changed'])})" if result.get("changed") else ""))
        return 0

    query = urllib.parse.urlencode({"agent": args.agent, "stage": args.stage})
    result = _call("GET", f"/ci/check?{query}")
    if result["allowed"]:
        print(f"OK: {result['name']} may go to {result['targetStage']}.")
        return 0
    print(f"BLOCKED: {result['name']} may not go to {result['targetStage']}:")
    for reason in result["reasons"]:
        print(f"  - {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
