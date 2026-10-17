"""Validated firewall policies; no caller-supplied nft syntax."""

import ipaddress

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_PORTS = (22, 80, 443, 2222)
TABLE = "xhttp_manager"


class PortRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    port: int = Field(ge=1, le=65535)
    protocol: str = "tcp"
    action: str = "allow"
    sources: list[str] = Field(default_factory=list, max_length=128)
    note: str = Field(default="", max_length=120)

    @field_validator("protocol")
    @classmethod
    def protocol_valid(cls, value):
        if value not in ("tcp", "udp"):
            raise ValueError("Protocol must be tcp or udp")
        return value

    @field_validator("action")
    @classmethod
    def action_valid(cls, value):
        if value not in ("allow", "deny"):
            raise ValueError("Action must be allow or deny")
        return value

    @field_validator("sources")
    @classmethod
    def sources_valid(cls, values):
        return sorted({str(ipaddress.ip_network(value.strip(), strict=False)) for value in values})

    @model_validator(mode="after")
    def deny_without_sources(self):
        if self.action == "deny" and self.sources:
            raise ValueError("A closed port cannot have a whitelist")
        return self


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[PortRule] = Field(default_factory=list, max_length=256)
    trusted_interfaces: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("trusted_interfaces")
    @classmethod
    def interfaces_valid(cls, values):
        import re

        for value in values:
            if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", value):
                raise ValueError("Use explicit internal interface names")
        return sorted(set(values))

    @model_validator(mode="after")
    def unique_ports(self):
        keys = [(r.protocol, r.port) for r in self.rules]
        if len(keys) != len(set(keys)):
            raise ValueError("Only one rule per port and protocol is allowed")
        return self


def permitted(policy, port, address, protocol="tcp"):
    ip = ipaddress.ip_address(address)
    rule = next((r for r in policy.rules if r.port == port and r.protocol == protocol), None)
    if rule:
        return rule.action == "allow" and (
            not rule.sources or any(ip in ipaddress.ip_network(source) for source in rule.sources)
        )
    return protocol == "tcp" and port in DEFAULT_PORTS


def render_policy(policy: Policy):
    lines = [f"table inet {TABLE} {{"]
    for name, forwarded in (("ports_in", False), ("ports_dnat", True)):
        lines.append(f"  chain {name} {{")
        for rule in sorted(policy.rules, key=lambda r: (r.protocol, r.port)):
            match = (
                f"meta l4proto {rule.protocol} ct original proto-dst {rule.port}"
                if forwarded
                else f"{rule.protocol} dport {rule.port}"
            )
            if rule.action == "allow":
                if not rule.sources:
                    lines.append(f"    {match} counter accept")
                else:
                    for version in (4, 6):
                        nets = [
                            s for s in rule.sources if ipaddress.ip_network(s).version == version
                        ]
                        if nets:
                            family = "ip" if version == 4 else "ip6"
                            lines.append(
                                f"    {match} {family} saddr {{ {', '.join(nets)} }} counter accept"
                            )
            lines.append(f"    {match} counter drop")
        defaults = [
            str(p)
            for p in DEFAULT_PORTS
            if not any(r.protocol == "tcp" and r.port == p for r in policy.rules)
        ]
        if defaults:
            match = "meta l4proto tcp ct original proto-dst" if forwarded else "tcp dport"
            lines.append(f"    {match} {{ {', '.join(defaults)} }} counter accept")
        lines.extend(["    counter drop", "  }"])
    internal = [
        '    iifname "lo" accept',
        '    iifname "docker*" accept',
        '    iifname "br-*" accept',
    ]
    internal += [f'    iifname "{name}" accept' for name in policy.trusted_interfaces]
    lines += ["  chain input {", "    type filter hook input priority -10; policy drop;"]
    lines += internal
    lines += [
        "    ct state established,related accept",
        "    ct state invalid drop",
        "    meta l4proto { icmp, ipv6-icmp } accept",
        "    udp sport 67 udp dport 68 accept",
        "    udp sport 547 udp dport 546 accept",
        "    jump ports_in",
        "  }",
        "  chain forward {",
        "    type filter hook forward priority -10; policy accept;",
    ]
    lines += internal
    lines += [
        "    ct state established,related accept",
        "    ct state invalid drop",
        "    ct status dnat jump ports_dnat",
        '    oifname "docker*" jump ports_in',
        '    oifname "br-*" jump ports_in',
        "  }",
        "}",
    ]
    return "\n".join(lines) + "\n"
