"""Validate network inputs before placing them in firewall configuration."""

from ipaddress import IPv4Network


def ipv4_cidr(value):
    """Normalize a source network; reject IPv6 and injected rule syntax."""
    return str(IPv4Network(str(value), strict=False))


class FilterModule:
    def filters(self):
        return {"milkyway_ipv4_cidr": ipv4_cidr}


if __name__ == "__main__":
    assert ipv4_cidr("192.168.100.101/32") == "192.168.100.101/32"
    for invalid in ("0.0.0.0/0; accept", "::/0", "not-a-network"):
        try:
            ipv4_cidr(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid firewall input accepted")
