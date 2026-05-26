from __future__ import annotations

import argparse
from pathlib import Path

from .api import serve_api
from .bootstrap import bootstrap_master, bootstrap_node
from .config import LinkRayConfig, NodeHost, parse_inbound_ports, parse_node_host
from .doctor import exit_code, run_doctor
from .egern import serve_egern
from .install import install_master, install_node
from .ports import write_ports_json
from .relay import serve_relay
from .render import render_master, render_node, validate_rendered
from .sub_auto import serve_sub_auto


def parse_nodes(values: list[str] | None, default_domain: str | None = None) -> list[NodeHost]:
    if values:
        return [parse_node_host(value) for value in values]
    if default_domain:
        return [NodeHost("primary", default_domain)]
    return []


def add_common_master_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--domain", required=True, help="Master domain, for example edge-a.example.com")
    parser.add_argument("--admin-username", default="admin")
    parser.add_argument("--admin-password", default="REPLACE_WITH_ADMIN_PASSWORD")
    parser.add_argument("--cert-file", default="/var/lib/marzban/certs/linkray/fullchain.cer")
    parser.add_argument("--key-file", default="/var/lib/marzban/certs/linkray/linkray.key")
    parser.add_argument("--reality-private-key", default="REPLACE_WITH_REALITY_PRIVATE_KEY")
    parser.add_argument("--reality-short-id", default="REPLACE_WITH_SHORT_ID")
    parser.add_argument("--grpc-service-name", default="grpc")
    parser.add_argument("--panel-port", default=9443, type=int)
    parser.add_argument(
        "--node",
        action="append",
        help="Subscription host entry in name=domain form. Repeat for multi-node setups.",
    )
    parser.add_argument(
        "--inbound",
        action="append",
        help="Override an inbound port in key=port form, for example vless_tls=28080. Repeat as needed.",
    )


def config_from_args(args: argparse.Namespace) -> LinkRayConfig:
    return LinkRayConfig(
        domain=args.domain,
        admin_username=args.admin_username,
        admin_password=args.admin_password,
        cert_file=args.cert_file,
        key_file=args.key_file,
        reality_private_key=args.reality_private_key,
        reality_short_id=args.reality_short_id,
        grpc_service_name=args.grpc_service_name,
        panel_port=args.panel_port,
        inbound_ports=parse_inbound_ports(args.inbound),
    )


def add_render_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    render = subparsers.add_parser("render", help="Render deployment files")
    render_sub = render.add_subparsers(dest="role", required=True)

    master = render_sub.add_parser("master", help="Render Marzban master files")
    add_common_master_args(master)
    master.add_argument("--output", required=True, type=Path, help="Output directory")

    node = render_sub.add_parser("node", help="Render Marzban node files")
    node.add_argument("--output", required=True, type=Path, help="Output directory")


def add_install_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    install = subparsers.add_parser("install", help="Install rendered files onto this machine")
    install_sub = install.add_subparsers(dest="role", required=True)

    master = install_sub.add_parser("master", help="Install Marzban master files")
    add_common_master_args(master)
    master.add_argument("--root", type=Path, default=Path("/"), help="Install root. Use a temp directory for dry testing.")
    master.add_argument("--apply", action="store_true", help="Actually write files. Omit for dry-run.")

    node = install_sub.add_parser("node", help="Install Marzban node files")
    node.add_argument("--root", type=Path, default=Path("/"), help="Install root. Use a temp directory for dry testing.")
    node.add_argument("--apply", action="store_true", help="Actually write files. Omit for dry-run.")


def add_bootstrap_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    bootstrap = subparsers.add_parser("bootstrap", help="Configure a fresh server end-to-end")
    bootstrap_sub = bootstrap.add_subparsers(dest="role", required=True)

    master = bootstrap_sub.add_parser("master", help="Bootstrap a Marzban master")
    add_common_master_args(master)
    master.add_argument("--root", type=Path, default=Path("/"), help="Install root. Use a temp directory for dry testing.")
    master.add_argument("--apply", action="store_true", help="Actually change files/services. Omit for dry-run.")
    master.add_argument("--issue-cert", action="store_true", help="Issue or renew a certificate with acme.sh DNS Cloudflare.")
    master.add_argument("--cf-token-env", default="CF_Token", help="Environment variable name containing the Cloudflare API token.")

    node = bootstrap_sub.add_parser("node", help="Bootstrap a Marzban node")
    node.add_argument("--root", type=Path, default=Path("/"), help="Install root. Use a temp directory for dry testing.")
    node.add_argument("--apply", action="store_true", help="Actually change files/services. Omit for dry-run.")


def add_ports_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    ports = subparsers.add_parser("ports", help="Refresh LinkRay port status JSON")
    ports.add_argument(
        "--node",
        action="append",
        required=True,
        help="Node entry in name=domain form. Repeat for multi-node setups.",
    )
    ports.add_argument("--output", required=True, type=Path)
    ports.add_argument("--timeout", default=2.0, type=float)
    ports.add_argument(
        "--inbound",
        action="append",
        help="Override an inbound port in key=port form, for example vless_tls=28080. Repeat as needed.",
    )


def add_api_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    api = subparsers.add_parser("api", help="Run the LinkRay node status API")
    api.add_argument("--listen", default="127.0.0.1")
    api.add_argument("--port", default=61990, type=int)
    api.add_argument(
        "--node",
        action="append",
        help="Node entry in name=domain form. Defaults to edge-a=edge-a.example.com and edge-b=edge-b.example.com.",
    )
    api.add_argument(
        "--inbound",
        action="append",
        help="Override an inbound port in key=port form, for example vless_tls=28080. Repeat as needed.",
    )
    api.add_argument("--timeout", default=2.0, type=float)
    api.add_argument("--ttl", default=60.0, type=float)


def add_egern_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    egern = subparsers.add_parser("egern", help="Run the Egern subscription adapter")
    egern.add_argument("--listen", default="127.0.0.1")
    egern.add_argument("--port", default=61992, type=int)
    egern.add_argument("--marzban-url", default="http://127.0.0.1:8000")


def add_sub_auto_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    sub_auto = subparsers.add_parser("sub-auto", help="Run automatic subscription format routing")
    sub_auto.add_argument("--listen", default="127.0.0.1")
    sub_auto.add_argument("--port", default=61993, type=int)
    sub_auto.add_argument("--marzban-url", default="http://127.0.0.1:8000")
    sub_auto.add_argument("--egern-url", default="http://127.0.0.1:61992")


def add_relay_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    relay = subparsers.add_parser("relay", help="Run TCP relays for secondary nodes")
    relay.add_argument("--listen", default="0.0.0.0")
    relay.add_argument(
        "--node",
        action="append",
        help="Relay target in name=domain[:offset] form. The second node normally uses offset 100.",
    )
    relay.add_argument(
        "--inbound",
        action="append",
        help="Override an inbound port in key=port form, for example vless_tls=28080. Repeat as needed.",
    )
    relay.add_argument("--timeout", default=5.0, type=float)
    relay.add_argument("--log-level", default="info")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="linkray")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_render_parser(subparsers)
    add_install_parser(subparsers)
    add_bootstrap_parser(subparsers)
    add_ports_parser(subparsers)
    add_api_parser(subparsers)
    add_egern_parser(subparsers)
    add_sub_auto_parser(subparsers)
    add_relay_parser(subparsers)

    validate = subparsers.add_parser("validate", help="Validate rendered deployment files")
    validate.add_argument("--path", required=True, type=Path)

    doctor = subparsers.add_parser("doctor", help="Check LinkRay runtime health")
    doctor.add_argument("--role", required=True, choices=["master", "node"])
    doctor.add_argument("--root", type=Path, default=Path("/"))
    doctor.add_argument("--no-runtime", action="store_true", help="Only check files under --root")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "render" and args.role == "master":
        result = render_master(
            config_from_args(args),
            args.output,
            nodes=parse_nodes(args.node, default_domain=args.domain),
        )
        for path in result.files:
            print(path)
        return 0

    if args.command == "render" and args.role == "node":
        result = render_node(args.output)
        for path in result.files:
            print(path)
        return 0

    if args.command == "validate":
        errors = validate_rendered(args.path)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print(f"OK: {args.path}")
        return 0

    if args.command == "install" and args.role == "master":
        actions = install_master(
            config_from_args(args),
            root=args.root,
            apply=args.apply,
            nodes=parse_nodes(args.node, default_domain=args.domain),
        )
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: master install root={args.root}")
        for action in actions:
            print(action.describe())
        if not args.apply:
            print("No files were written. Re-run with --apply to install.")
        else:
            print("Files installed. Review hosts.sql before applying it to Marzban SQLite.")
        return 0

    if args.command == "install" and args.role == "node":
        actions = install_node(root=args.root, apply=args.apply)
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: node install root={args.root}")
        for action in actions:
            print(action.describe())
        if not args.apply:
            print("No files were written. Re-run with --apply to install.")
        return 0

    if args.command == "doctor":
        checks = run_doctor(args.role, root=args.root, runtime=not args.no_runtime)
        for check in checks:
            print(check.line())
        return exit_code(checks)

    if args.command == "ports":
        output = write_ports_json(
            parse_nodes(args.node),
            args.output,
            timeout=args.timeout,
            inbound_ports=parse_inbound_ports(args.inbound),
        )
        print(output)
        return 0

    if args.command == "api":
        args.nodes = parse_nodes(args.node) or [
            NodeHost("edge-a", "edge-a.example.com"),
            NodeHost("edge-b", "edge-b.example.com"),
        ]
        args.inbound_ports = parse_inbound_ports(args.inbound)
        return serve_api(args)

    if args.command == "egern":
        return serve_egern(args)

    if args.command == "sub-auto":
        return serve_sub_auto(args)

    if args.command == "relay":
        args.inbound_ports = parse_inbound_ports(args.inbound)
        return serve_relay(args)

    if args.command == "bootstrap" and args.role == "master":
        actions = bootstrap_master(
            config_from_args(args),
            root=args.root,
            apply=args.apply,
            nodes=parse_nodes(args.node, default_domain=args.domain),
            issue_cert=args.issue_cert,
            cf_token_env=args.cf_token_env,
        )
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: master bootstrap root={args.root}")
        for action in actions:
            print(action.describe())
        if not args.apply:
            print("No files were written and no commands were executed. Re-run with --apply to bootstrap.")
        else:
            print(f"Panel URL: https://{args.domain}:{args.panel_port}/dashboard/")
        return 1 if any(not action.ok for action in actions) else 0

    if args.command == "bootstrap" and args.role == "node":
        actions = bootstrap_node(root=args.root, apply=args.apply)
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: node bootstrap root={args.root}")
        for action in actions:
            print(action.describe())
        if not args.apply:
            print("No files were written and no commands were executed. Re-run with --apply to bootstrap.")
        return 1 if any(not action.ok for action in actions) else 0

    parser.error("unhandled command")
    return 2
