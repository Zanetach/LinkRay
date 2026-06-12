from __future__ import annotations

import ipaddress
from collections.abc import Callable, Sequence
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

METACUBEX_RELEASE_BASE = "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest"
METACUBEX_MIHOMO_BASE = "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta"
METACUBEX_SINGBOX_BASE = "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/sing"

BUILTIN_CN_DOMAIN_SUFFIXES = (
    "cn",
    "com.cn",
    "net.cn",
    "org.cn",
    "xn--fiqs8s",
    "xn--55qx5d",
    "xn--io0a7i",
    "tencentcloud.com",
    "tencent.com",
    "tencent-cloud.com",
    "qcloud.com",
    "myqcloud.com",
    "smtcdns.com",
    "gtimg.com",
    "gtimg.cn",
    "qq.com",
    "weixin.qq.com",
    "wx.qq.com",
    "wechat.com",
    "weixinbridge.com",
    "servicewechat.com",
    "qlogo.cn",
    "qpic.cn",
    "idqqimg.com",
    "qqmail.com",
    "imqq.com",
    "myapp.com",
    "tenpay.com",
    "url.cn",
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

COMPACT_CN_DOMAIN_SUFFIXES: tuple[str, ...] = tuple(
    sorted(set(BUILTIN_CN_DOMAIN_SUFFIXES) | {"dns.pub", "doh.pub", "alidns.com"})
)

FOREIGN_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "dns.google",
    "cloudflare-dns.com",
    "telegram.org",
    "t.me",
    "youtube.com",
    "youtu.be",
    "googlevideo.com",
    "tiktok.com",
    "tiktokv.com",
    "tiktokcdn.com",
    "facebook.com",
    "fb.com",
    "fbcdn.net",
    "instagram.com",
    "whatsapp.com",
    "x.com",
    "twitter.com",
    "t.co",
    "google.com",
    "gstatic.com",
    "googleapis.com",
    "googleusercontent.com",
    "openai.com",
    "chatgpt.com",
    "oaistatic.com",
    "oaiusercontent.com",
    "anthropic.com",
    "claude.ai",
    "github.com",
    "githubusercontent.com",
)

BUILTIN_CN_IP_CIDRS = (
    "106.52.0.0/15",
    "106.54.0.0/16",
)


@dataclass(frozen=True)
class RouteRules:
    cn_domain_suffixes: list[str]
    cn_ip_cidrs: list[str]


@dataclass(frozen=True)
class MetaCubeXAsset:
    path: str
    url: str


METACUBEX_ASSETS: tuple[MetaCubeXAsset, ...] = (
    MetaCubeXAsset("geosite.dat", f"{METACUBEX_RELEASE_BASE}/geosite.dat"),
    MetaCubeXAsset("geoip.dat", f"{METACUBEX_RELEASE_BASE}/geoip.dat"),
    MetaCubeXAsset("country.mmdb", f"{METACUBEX_RELEASE_BASE}/country.mmdb"),
    MetaCubeXAsset("GeoLite2-ASN.mmdb", f"{METACUBEX_RELEASE_BASE}/GeoLite2-ASN.mmdb"),
    MetaCubeXAsset("mihomo/geosite-cn.mrs", f"{METACUBEX_MIHOMO_BASE}/geo/geosite/cn.mrs"),
    MetaCubeXAsset("mihomo/geoip-cn.mrs", f"{METACUBEX_MIHOMO_BASE}/geo/geoip/cn.mrs"),
    MetaCubeXAsset("sing-box/geosite-cn.srs", f"{METACUBEX_SINGBOX_BASE}/geo/geosite/cn.srs"),
    MetaCubeXAsset("sing-box/geoip-cn.srs", f"{METACUBEX_SINGBOX_BASE}/geo/geoip/cn.srs"),
)


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


def fetch_bytes(url: str, timeout: float = 20.0) -> bytes:
    with urlopen(url, timeout=timeout) as response:
        return response.read()


def write_bytes_atomic(path: Path, data: bytes) -> Path:
    if not data:
        raise ValueError(f"{path}: refusing to cache empty MetaCubeX asset")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def download_metacubex_assets(
    root: Path,
    assets: Sequence[MetaCubeXAsset] = METACUBEX_ASSETS,
    timeout: float = 20.0,
    fetcher: Callable[[str, float], bytes] = fetch_bytes,
) -> list[Path]:
    paths: list[Path] = []
    for asset in assets:
        target = root / asset.path
        paths.append(write_bytes_atomic(target, fetcher(asset.url, timeout)))
    return paths


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
    download_metacubex_assets(output, timeout=timeout)
    return rules
