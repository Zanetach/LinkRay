from __future__ import annotations

import argparse
import os
from pathlib import Path

from .api import serve_api
from .bootstrap import bootstrap_master, bootstrap_node
from .clash import serve_clash
from .config import (
    XRAY_RUNTIME_MODES,
    LinkRayConfig,
    NodeHost,
    parse_inbound_ports,
    parse_node_host,
    parse_snell_inbound_ports,
    parse_singbox_inbound_ports,
)
from .doctor import exit_code, run_doctor
from .egern import serve_egern
from .install import install_master, install_node
from .ports import write_ports_json
from .protocol_prefs import DEFAULT_PROTOCOL_PREFS_PATH
from .protocols import PROTOCOL_CAPABILITIES, protocol_capabilities_json
from .relay import serve_relay
from .render import render_master, render_node, validate_rendered
from .rules import DEFAULT_RULE_DIR, update_route_rules
from .shadowrocket import serve_shadowrocket
from .singbox import serve_singbox
from .snell_runtime import serve_snell_usage
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
    parser.add_argument("--snell-psk", default="REPLACE_WITH_SNELL_PSK")
    parser.add_argument(
        "--residential-socks-url-env",
        default="",
        help="Environment variable containing a socks5:// residential proxy URL for AI-domain server-side routing.",
    )
    parser.add_argument(
        "--xray-runtime",
        choices=XRAY_RUNTIME_MODES,
        default="marzban",
        help="Xray runtime owner. marzban keeps the current LinkRay panel-managed process; linkray emits linkray-xray.service.",
    )
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
    parser.add_argument(
        "--singbox-inbound",
        action="append",
        help="Override a sing-box inbound port in key=port form, for example hysteria2=443. Repeat as needed.",
    )
    parser.add_argument(
        "--snell-inbound",
        action="append",
        help="Override a Snell inbound port in key=port form, for example snell=19180.",
    )


def config_from_args(args: argparse.Namespace) -> LinkRayConfig:
    residential_proxy_url = os.environ.get(args.residential_socks_url_env, "") if args.residential_socks_url_env else ""
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
        xray_runtime_mode=args.xray_runtime,
        snell_psk=args.snell_psk,
        residential_proxy_url=residential_proxy_url,
        inbound_ports=parse_inbound_ports(args.inbound),
        singbox_inbound_ports=parse_singbox_inbound_ports(args.singbox_inbound),
        snell_inbound_ports=parse_snell_inbound_ports(args.snell_inbound),
    )


def add_common_node_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--domain", help="Node domain, for example edge-b.example.com. Enables advanced runtimes.")
    parser.add_argument("--cert-file", default="/var/lib/marzban/certs/linkray/fullchain.cer")
    parser.add_argument("--key-file", default="/var/lib/marzban/certs/linkray/linkray.key")
    parser.add_argument("--snell-psk", default="REPLACE_WITH_SNELL_PSK")
    parser.add_argument(
        "--residential-socks-url-env",
        default="",
        help="Environment variable containing a socks5:// residential proxy URL for AI-domain server-side routing.",
    )
    parser.add_argument(
        "--singbox-inbound",
        action="append",
        help="Override a sing-box inbound port in key=port form, for example hysteria2=443. Repeat as needed.",
    )
    parser.add_argument(
        "--snell-inbound",
        action="append",
        help="Override a Snell inbound port in key=port form, for example snell=19180.",
    )


def node_config_from_args(args: argparse.Namespace) -> LinkRayConfig | None:
    if not getattr(args, "domain", None):
        return None
    residential_proxy_url = os.environ.get(args.residential_socks_url_env, "") if args.residential_socks_url_env else ""
    return LinkRayConfig(
        domain=args.domain,
        cert_file=args.cert_file,
        key_file=args.key_file,
        snell_psk=args.snell_psk,
        residential_proxy_url=residential_proxy_url,
        singbox_inbound_ports=parse_singbox_inbound_ports(args.singbox_inbound),
        snell_inbound_ports=parse_snell_inbound_ports(args.snell_inbound),
    )


def add_render_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    render = subparsers.add_parser("render", help="Render deployment files")
    render_sub = render.add_subparsers(dest="role", required=True)

    master = render_sub.add_parser("master", help="Render LinkRay master files")
    add_common_master_args(master)
    master.add_argument("--output", required=True, type=Path, help="Output directory")

    node = render_sub.add_parser("node", help="Render LinkRay node files")
    add_common_node_args(node)
    node.add_argument("--output", required=True, type=Path, help="Output directory")


def add_install_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    install = subparsers.add_parser("install", help="Install rendered files onto this machine")
    install_sub = install.add_subparsers(dest="role", required=True)

    master = install_sub.add_parser("master", help="Install LinkRay master files")
    add_common_master_args(master)
    master.add_argument("--root", type=Path, default=Path("/"), help="Install root. Use a temp directory for dry testing.")
    master.add_argument("--apply", action="store_true", help="Actually write files. Omit for dry-run.")

    node = install_sub.add_parser("node", help="Install LinkRay node files")
    add_common_node_args(node)
    node.add_argument("--root", type=Path, default=Path("/"), help="Install root. Use a temp directory for dry testing.")
    node.add_argument("--apply", action="store_true", help="Actually write files. Omit for dry-run.")


def add_bootstrap_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    bootstrap = subparsers.add_parser("bootstrap", help="Configure a fresh server end-to-end")
    bootstrap_sub = bootstrap.add_subparsers(dest="role", required=True)

    master = bootstrap_sub.add_parser("master", help="Bootstrap a LinkRay master")
    add_common_master_args(master)
    master.add_argument("--root", type=Path, default=Path("/"), help="Install root. Use a temp directory for dry testing.")
    master.add_argument("--apply", action="store_true", help="Actually change files/services. Omit for dry-run.")
    master.add_argument("--issue-cert", action="store_true", help="Issue or renew a certificate with acme.sh DNS Cloudflare.")
    master.add_argument("--cf-token-env", default="CF_Token", help="Environment variable name containing the Cloudflare API token.")

    node = bootstrap_sub.add_parser("node", help="Bootstrap a LinkRay node")
    add_common_node_args(node)
    node.add_argument("--root", type=Path, default=Path("/"), help="Install root. Use a temp directory for dry testing.")
    node.add_argument("--apply", action="store_true", help="Actually change files/services. Omit for dry-run.")
    node.add_argument("--pull-cert-from", help="SSH source such as root@master.example.com for pulling ssl_client_cert.pem.")
    node.add_argument("--remote-cert-path", default="/var/lib/marzban/ssl_client_cert.pem")


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
    ports.add_argument(
        "--singbox-inbound",
        action="append",
        help="Override a sing-box inbound port in key=port form, for example hysteria2=29080.",
    )
    ports.add_argument(
        "--snell-inbound",
        action="append",
        help="Override a Snell inbound port in key=port form, for example snell=29180.",
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
    api.add_argument(
        "--singbox-inbound",
        action="append",
        help="Override a sing-box inbound port in key=port form, for example hysteria2=29080.",
    )
    api.add_argument(
        "--snell-inbound",
        action="append",
        help="Override a Snell inbound port in key=port form, for example snell=29180.",
    )
    api.add_argument("--timeout", default=2.0, type=float)
    api.add_argument("--ttl", default=60.0, type=float)
    api.add_argument(
        "--protocol-preferences-path",
        type=Path,
        default=Path("/var/lib/marzban/linkray/protocols/users.json"),
    )


def add_egern_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    egern = subparsers.add_parser("egern", help="Run the Egern subscription adapter")
    egern.add_argument("--listen", default="127.0.0.1")
    egern.add_argument("--port", default=61992, type=int)
    egern.add_argument("--marzban-url", default="http://127.0.0.1:8000")
    egern.add_argument("--server-domain", default="")


def add_clash_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    clash = subparsers.add_parser("clash", help="Run the Clash/Mihomo subscription adapter")
    clash.add_argument("--listen", default="127.0.0.1")
    clash.add_argument("--port", default=61991, type=int)
    clash.add_argument("--marzban-url", default="http://127.0.0.1:8000")
    clash.add_argument("--server-domain", default="")
    clash.add_argument("--snell-runtime-dir", type=Path, default=Path("/var/lib/marzban/linkray/snell"))
    clash.add_argument("--snell-reload-command", default="")
    clash.add_argument("--rules-base-url", default="")


def add_shadowrocket_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    shadowrocket = subparsers.add_parser("shadowrocket", help="Run the Shadowrocket subscription adapter")
    shadowrocket.add_argument("--listen", default="127.0.0.1")
    shadowrocket.add_argument("--port", default=61994, type=int)
    shadowrocket.add_argument("--marzban-url", default="http://127.0.0.1:8000")
    shadowrocket.add_argument("--server-domain", default="")
    shadowrocket.add_argument("--snell-runtime-dir", type=Path, default=Path("/var/lib/marzban/linkray/snell"))
    shadowrocket.add_argument("--snell-reload-command", default="")
    shadowrocket.add_argument("--protocol-preferences-path", type=Path, default=DEFAULT_PROTOCOL_PREFS_PATH)


def add_singbox_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    singbox = subparsers.add_parser("sing-box", help="Run the sing-box subscription adapter")
    singbox.add_argument("--listen", default="127.0.0.1")
    singbox.add_argument("--port", default=61995, type=int)
    singbox.add_argument("--marzban-url", default="http://127.0.0.1:8000")
    singbox.add_argument("--server-domain", default="")
    singbox.add_argument(
        "--advanced-domain",
        action="append",
        help="Additional LinkRay advanced runtime domain to include in sing-box subscriptions. Repeat for multi-node setups.",
    )
    singbox.add_argument("--runtime-dir", type=Path, default=Path("/var/lib/marzban/linkray/singbox"))
    singbox.add_argument("--reload-command", default="")
    singbox.add_argument("--sync-command", default="", help="Optional shell command to sync runtime users to secondary nodes after changes.")
    singbox.add_argument("--rules-base-url", default="")
    singbox.add_argument("--protocol-preferences-path", type=Path, default=DEFAULT_PROTOCOL_PREFS_PATH)
    singbox.add_argument(
        "--singbox-inbound",
        action="append",
        help="Override a sing-box inbound port in key=port form. Repeat as needed.",
    )


def add_snell_usage_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    snell_usage = subparsers.add_parser("snell-usage", help="Run the Snell per-user usage sidecar")
    snell_usage.add_argument("--listen", default="127.0.0.1")
    snell_usage.add_argument("--port", default=61997, type=int)
    snell_usage.add_argument("--runtime-dir", type=Path, default=Path("/var/lib/marzban/linkray/snell"))


def add_sub_auto_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    sub_auto = subparsers.add_parser("sub-auto", help="Run automatic subscription format routing")
    sub_auto.add_argument("--listen", default="127.0.0.1")
    sub_auto.add_argument("--port", default=61993, type=int)
    sub_auto.add_argument("--marzban-url", default="http://127.0.0.1:8000")
    sub_auto.add_argument("--clash-url", default="http://127.0.0.1:61991")
    sub_auto.add_argument("--egern-url", default="http://127.0.0.1:61992")
    sub_auto.add_argument("--shadowrocket-url", default="http://127.0.0.1:61994")
    sub_auto.add_argument("--singbox-url", default="http://127.0.0.1:61995")


def add_rules_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    rules = subparsers.add_parser("rules", help="Manage LinkRay route rules")
    rules_sub = rules.add_subparsers(dest="action", required=True)
    update = rules_sub.add_parser("update", help="Update CN domain and IP CIDR route rules")
    update.add_argument("--output", type=Path, default=DEFAULT_RULE_DIR)
    update.add_argument("--timeout", type=float, default=20.0)


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


def add_protocols_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    protocols = subparsers.add_parser("protocols", help="Show LinkRay protocol capability status")
    protocols.add_argument("--json", action="store_true", help="Print machine-readable JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="linkray")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_render_parser(subparsers)
    add_install_parser(subparsers)
    add_bootstrap_parser(subparsers)
    add_ports_parser(subparsers)
    add_api_parser(subparsers)
    add_clash_parser(subparsers)
    add_egern_parser(subparsers)
    add_shadowrocket_parser(subparsers)
    add_singbox_parser(subparsers)
    add_snell_usage_parser(subparsers)
    add_sub_auto_parser(subparsers)
    add_rules_parser(subparsers)
    add_relay_parser(subparsers)
    add_protocols_parser(subparsers)

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
        result = render_node(args.output, config=node_config_from_args(args))
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
            print("Files installed. Review hosts.sql before applying it to the LinkRay SQLite database.")
        return 0

    if args.command == "install" and args.role == "node":
        actions = install_node(root=args.root, apply=args.apply, config=node_config_from_args(args))
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
            singbox_inbound_ports=parse_singbox_inbound_ports(args.singbox_inbound),
            snell_inbound_ports=parse_snell_inbound_ports(args.snell_inbound),
        )
        print(output)
        return 0

    if args.command == "api":
        args.nodes = parse_nodes(args.node) or [
            NodeHost("edge-a", "edge-a.example.com"),
            NodeHost("edge-b", "edge-b.example.com"),
        ]
        args.inbound_ports = parse_inbound_ports(args.inbound)
        args.singbox_inbound_ports = parse_singbox_inbound_ports(args.singbox_inbound)
        args.snell_inbound_ports = parse_snell_inbound_ports(args.snell_inbound)
        return serve_api(args)

    if args.command == "clash":
        return serve_clash(args)

    if args.command == "egern":
        return serve_egern(args)

    if args.command == "shadowrocket":
        return serve_shadowrocket(args)

    if args.command == "sing-box":
        return serve_singbox(args)

    if args.command == "snell-usage":
        return serve_snell_usage(args)

    if args.command == "sub-auto":
        return serve_sub_auto(args)

    if args.command == "rules" and args.action == "update":
        rules = update_route_rules(output=args.output, timeout=args.timeout)
        print(f"{args.output}/cn-domains.txt: {len(rules.cn_domain_suffixes)} domain suffixes")
        print(f"{args.output}/cn-ip-cidrs.txt: {len(rules.cn_ip_cidrs)} CIDRs")
        return 0

    if args.command == "relay":
        args.inbound_ports = parse_inbound_ports(args.inbound)
        return serve_relay(args)

    if args.command == "protocols":
        if args.json:
            print(protocol_capabilities_json(), end="")
        else:
            for capability in PROTOCOL_CAPABILITIES:
                print(
                    f"{capability.status}\t{capability.runtime}\t"
                    f"{capability.name}\t{capability.transport}/{capability.security}"
                )
        return 0

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
        actions = bootstrap_node(
            root=args.root,
            apply=args.apply,
            pull_cert_from=args.pull_cert_from,
            remote_cert_path=args.remote_cert_path,
            config=node_config_from_args(args),
        )
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"{mode}: node bootstrap root={args.root}")
        for action in actions:
            print(action.describe())
        if not args.apply:
            print("No files were written and no commands were executed. Re-run with --apply to bootstrap.")
        return 1 if any(not action.ok for action in actions) else 0

    parser.error("unhandled command")
    return 2
