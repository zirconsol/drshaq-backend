import unittest

from app.client_ip import build_trusted_proxy_networks, extract_client_ip_from_headers


class ClientIpExtractionTests(unittest.TestCase):
    def test_direct_connection_ignores_forwarded_headers(self) -> None:
        result = extract_client_ip_from_headers(
            peer_ip='198.51.100.12',
            headers={'x-forwarded-for': '203.0.113.10'},
            trusted_proxy_networks=build_trusted_proxy_networks(['10.0.0.0/8']),
            trust_proxy_headers=True,
        )
        self.assertEqual(result, '198.51.100.12')

    def test_trusted_proxy_uses_forwarded_chain(self) -> None:
        result = extract_client_ip_from_headers(
            peer_ip='10.10.10.10',
            headers={'x-forwarded-for': '198.51.100.10, 10.10.10.5'},
            trusted_proxy_networks=build_trusted_proxy_networks(['10.0.0.0/8']),
            trust_proxy_headers=True,
        )
        self.assertEqual(result, '198.51.100.10')

    def test_cdn_header_has_priority_over_xff(self) -> None:
        result = extract_client_ip_from_headers(
            peer_ip='10.20.30.40',
            headers={
                'cf-connecting-ip': '203.0.113.99',
                'x-forwarded-for': '198.51.100.1, 10.20.30.1',
            },
            trusted_proxy_networks=build_trusted_proxy_networks(['10.0.0.0/8']),
            trust_proxy_headers=True,
        )
        self.assertEqual(result, '203.0.113.99')

    def test_proxy_headers_disabled_returns_peer(self) -> None:
        result = extract_client_ip_from_headers(
            peer_ip='10.20.30.40',
            headers={'cf-connecting-ip': '203.0.113.99'},
            trusted_proxy_networks=build_trusted_proxy_networks(['10.0.0.0/8']),
            trust_proxy_headers=False,
        )
        self.assertEqual(result, '10.20.30.40')


if __name__ == '__main__':
    unittest.main()
