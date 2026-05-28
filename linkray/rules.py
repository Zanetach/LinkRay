from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen


DEFAULT_RULE_DIR = Path("/var/lib/marzban/linkray/rules")
CN_DOMAINS_FILE = "cn-domains.txt"
CN_IP_CIDRS_FILE = "cn-ip-cidrs.txt"

DEFAULT_CN_DOMAIN_SOURCES = (
    "https://raw.githubusercontent.com/felixonmars/dnsmasq-china-list/master/accelerated-domains.china.conf",
)
DEFAULT_CN_IP_SOURCES = (
    "https://raw.githubusercontent.com/17mon/china_ip_list/master/china_ip_list.txt",
)

BUILTIN_CN_DOMAIN_SUFFIXES = (
    "cn",
    "com.cn",
    "net.cn",
    "org.cn",
    "xn--fiqs8s",
    "xn--55qx5d",
    "xn--io0a7i",
    "tencentcloud.com",
    "qcloud.com",
    "myqcloud.com",
    "gtimg.com",
    "gtimg.cn",
    "qq.com",
    "weixin.qq.com",
    "wechat.com",
    "baidu.com",
    "bdimg.com",
    "bdstatic.com",
    "alicdn.com",
    "aliyun.com",
    "aliyuncs.com",
    "taobao.com",
    "tmall.com",
    "alipay.com",
    "jd.com",
    "360buyimg.com",
    "mi.com",
    "xiaomi.com",
    "huawei.com",
    "huaweicloud.com",
    "meituan.com",
    "dianping.com",
    "amap.com",
    "autonavi.com",
    "zhihu.com",
    "zhimg.com",
    "douban.com",
    "xiaohongshu.com",
    "xhscdn.com",
    "bilibili.com",
    "bilibili.tv",
    "iqiyi.com",
    "youku.com",
    "kugou.com",
    "kuwo.cn",
    "migu.cn",
    "douyin.com",
    "ixigua.com",
    "kuaishou.com",
)

BUILTIN_CN_IP_CIDRS = (
    "106.52.0.0/15",
    "106.54.0.0/16",
)


@dataclass(frozen=True)
class RouteRules:
    cn_domain_suffixes: list[str]
    cn_ip_cidrs: list[str]


def unique_sorted(values: list[str]) -> list[str]:
    return sorted({value.strip().lower() for value in values if value and value.strip()})


def parse_domain_lines(text: str) -> list[str]:
    domains: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("DOMAIN-SUFFIX,"):
            parts = line.split(",")
            if len(parts) >= 2:
                domains.append(parts[1].strip())
            continue
        if line.startswith(("server=/", "address=/", "ipset=/")):
            parts = line.split("/")
            if len(parts) >= 3 and parts[1]:
                domains.append(parts[1].strip())
            continue
        if line.startswith("full:"):
            domains.append(line.removeprefix("full:").strip())
            continue
        if "," in line:
            line = line.split(",", 1)[0].strip()
        if line and "/" not in line and " " not in line:
            domains.append(line)
    return unique_sorted(domains)


def parse_cidr_lines(text: str) -> list[str]:
    cidrs: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith(("IP-CIDR,", "IP-CIDR6,")):
            parts = line.split(",")
            if len(parts) >= 2:
                line = parts[1].strip()
        else:
            line = line.split(",", 1)[0].split(None, 1)[0].strip()
        try:
            cidrs.append(str(ipaddress.ip_network(line, strict=False)))
        except ValueError:
            continue
    return unique_sorted(cidrs)


def write_lines(path: Path, values: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(values) + "\n", encoding="utf-8")
    return path


def write_route_rules(root: Path, rules: RouteRules) -> tuple[Path, Path]:
    domains = write_lines(root / CN_DOMAINS_FILE, unique_sorted(rules.cn_domain_suffixes))
    cidrs = write_lines(root / CN_IP_CIDRS_FILE, unique_sorted(rules.cn_ip_cidrs))
    return domains, cidrs


def load_route_rules(root: Path = DEFAULT_RULE_DIR) -> RouteRules:
    domain_path = root / CN_DOMAINS_FILE
    cidr_path = root / CN_IP_CIDRS_FILE
    domain_suffixes = parse_domain_lines(domain_path.read_text(encoding="utf-8")) if domain_path.exists() else []
    ip_cidrs = parse_cidr_lines(cidr_path.read_text(encoding="utf-8")) if cidr_path.exists() else []
    return RouteRules(
        cn_domain_suffixes=domain_suffixes or unique_sorted(list(BUILTIN_CN_DOMAIN_SUFFIXES)),
        cn_ip_cidrs=ip_cidrs or unique_sorted(list(BUILTIN_CN_IP_CIDRS)),
    )


def fetch_text(url: str, timeout: float = 20.0) -> str:
    with urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def update_route_rules(
    output: Path = DEFAULT_RULE_DIR,
    domain_sources: tuple[str, ...] = DEFAULT_CN_DOMAIN_SOURCES,
    ip_sources: tuple[str, ...] = DEFAULT_CN_IP_SOURCES,
    timeout: float = 20.0,
) -> RouteRules:
    domains: list[str] = list(BUILTIN_CN_DOMAIN_SUFFIXES)
    cidrs: list[str] = list(BUILTIN_CN_IP_CIDRS)
    for source in domain_sources:
        domains.extend(parse_domain_lines(fetch_text(source, timeout=timeout)))
    for source in ip_sources:
        cidrs.extend(parse_cidr_lines(fetch_text(source, timeout=timeout)))
    rules = RouteRules(cn_domain_suffixes=unique_sorted(domains), cn_ip_cidrs=unique_sorted(cidrs))
    write_route_rules(output, rules)
    return rules
