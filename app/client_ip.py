from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Mapping


def build_trusted_proxy_networks(cidrs: list[str]) -> list:
    networks = []
    for cidr in cidrs:
        value = cidr.strip()
        if not value:
            continue
        try:
            networks.append(ip_network(value, strict=False))
        except ValueError:
            continue
    return networks


def _parse_ip(value: str | None):
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if ',' in candidate:
        candidate = candidate.split(',', 1)[0].strip()
    try:
        return ip_address(candidate)
    except ValueError:
        return None


def _parse_xff(value: str | None) -> list:
    if not value:
        return []
    result = []
    for token in value.split(','):
        parsed = _parse_ip(token)
        if parsed is not None:
            result.append(parsed)
    return result


def _is_trusted(ip, trusted_proxy_networks: list) -> bool:
    if ip is None:
        return False
    return any(ip in network for network in trusted_proxy_networks)


def extract_client_ip_from_headers(
    *,
    peer_ip: str | None,
    headers: Mapping[str, str],
    trusted_proxy_networks: list,
    trust_proxy_headers: bool,
) -> str:
    peer = _parse_ip(peer_ip)
    if not trust_proxy_headers or not _is_trusted(peer, trusted_proxy_networks):
        return str(peer) if peer else (peer_ip or 'unknown')

    normalized_headers = {key.lower(): value for key, value in headers.items()}

    for header_name in ('cf-connecting-ip', 'true-client-ip'):
        parsed = _parse_ip(normalized_headers.get(header_name))
        if parsed is not None:
            return str(parsed)

    forwarded_chain = _parse_xff(normalized_headers.get('x-forwarded-for'))
    if forwarded_chain:
        chain = forwarded_chain + ([peer] if peer is not None else [])
        for hop in reversed(chain):
            if not _is_trusted(hop, trusted_proxy_networks):
                return str(hop)
        return str(forwarded_chain[0])

    x_real_ip = _parse_ip(normalized_headers.get('x-real-ip'))
    if x_real_ip is not None:
        return str(x_real_ip)

    return str(peer) if peer else (peer_ip or 'unknown')


def extract_client_ip(request, *, trusted_proxy_networks: list, trust_proxy_headers: bool) -> str:
    peer_ip = request.client.host if request.client else None
    return extract_client_ip_from_headers(
        peer_ip=peer_ip,
        headers=request.headers,
        trusted_proxy_networks=trusted_proxy_networks,
        trust_proxy_headers=trust_proxy_headers,
    )
