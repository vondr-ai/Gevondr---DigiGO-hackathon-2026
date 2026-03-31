"""Probe whether current DSGO credentials can support H2M in acceptance.

This script does not try to prove what DSGO can never do.
It proves what *our current credential set* can and cannot do today.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dsgo.auth import DSGOAuth
from src.dsgo.config import get_config


@dataclass
class ProbeResult:
    oidc_available: bool
    code_flow_available: bool
    userinfo_available: bool
    pkce_available: bool
    token_auth_methods: list[str]
    has_client_secret: bool
    has_redirect_uri: bool
    m2m_token_is_jwt: bool
    userinfo_status_with_m2m: int | None


def fetch_oidc_config(base_url: str) -> dict:
    response = requests.get(f"{base_url.rstrip('/')}/.well-known/openid-configuration", timeout=20)
    response.raise_for_status()
    return response.json()


def get_userinfo_status(base_url: str, token: str) -> int | None:
    response = requests.get(
        f"{base_url.rstrip('/')}/connect/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    return response.status_code


def run_probe() -> ProbeResult:
    config = get_config()
    oidc = fetch_oidc_config(config["registry_url"])

    auth = DSGOAuth(**config)
    token = auth.get_access_token()

    token_auth_methods = oidc.get("token_endpoint_auth_methods_supported", [])
    response_types = oidc.get("response_types_supported", [])
    pkce_methods = oidc.get("code_challenge_methods_supported", [])

    has_client_secret = bool(os.getenv("DSGO_CLIENT_SECRET"))
    has_redirect_uri = bool(os.getenv("DSGO_REDIRECT_URI"))

    return ProbeResult(
        oidc_available=True,
        code_flow_available="code" in response_types,
        userinfo_available=bool(oidc.get("userinfo_endpoint")),
        pkce_available=bool(pkce_methods),
        token_auth_methods=token_auth_methods,
        has_client_secret=has_client_secret,
        has_redirect_uri=has_redirect_uri,
        m2m_token_is_jwt=token.count(".") == 2,
        userinfo_status_with_m2m=get_userinfo_status(config["registry_url"], token),
    )


def print_report(result: ProbeResult) -> None:
    print("DSGO acceptance H2M capability probe")
    print("=" * 60)
    print()
    print("[1] Acceptance capabilities")
    print(f"  OIDC configuration available: {'yes' if result.oidc_available else 'no'}")
    print(f"  Authorization code flow available: {'yes' if result.code_flow_available else 'no'}")
    print(f"  Userinfo endpoint published: {'yes' if result.userinfo_available else 'no'}")
    print(f"  PKCE methods published: {'yes' if result.pkce_available else 'no'}")
    print(f"  Token endpoint auth methods: {', '.join(result.token_auth_methods) or '(none)'}")
    print()
    print("[2] Our current credential set")
    print(f"  Has client secret: {'yes' if result.has_client_secret else 'no'}")
    print(f"  Has redirect URI: {'yes' if result.has_redirect_uri else 'no'}")
    print()
    print("[3] Current M2M integration")
    print(f"  M2M access token looks like JWT: {'yes' if result.m2m_token_is_jwt else 'no'}")
    print(f"  userinfo with current M2M token: HTTP {result.userinfo_status_with_m2m}")
    print()
    print("[4] Conclusion")

    if result.code_flow_available and result.userinfo_available:
        print("  Acceptance exposes the technical building blocks for H2M.")
    else:
        print("  Acceptance does not expose enough OIDC building blocks for H2M.")

    if not result.has_client_secret or not result.has_redirect_uri:
        print("  Our current credentials/config are insufficient to run an end-to-end H2M proof.")
    else:
        print("  Our current credentials/config may be sufficient to attempt an end-to-end H2M proof.")

    if result.userinfo_status_with_m2m != 200:
        print("  Our current M2M integration does not yield user identity and cannot enforce personal rights.")
    else:
        print("  Our current M2M integration unexpectedly returns user identity.")

    print()
    print("[5] Decision for the hackathon")
    print("  With the credentials we have today, we can prove organization-level authorization.")
    print("  We cannot prove or operate personal-rights authorization end-to-end without additional H2M setup.")


def print_json(result: ProbeResult) -> None:
    print(json.dumps(result.__dict__, indent=2))


if __name__ == "__main__":
    probe = run_probe()
    if "--json" in os.sys.argv:
        print_json(probe)
    else:
        print_report(probe)
