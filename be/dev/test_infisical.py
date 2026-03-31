"""Manual smoke-test for InfisicalClient (httpx implementation).

Usage:
    uv run python dev/test_infisical.py

Requires a .env file (or env vars) with:
    INFISICAL_ENDPOINT
    INFISICAL_CLIENT_ID
    INFISICAL_CLIENT_SECRET
    INFISICAL_PROJECT_ID
    ENVIRONMENT          (e.g. "dev" / "prod")

Edit SECRET_NAME / SECRET_PATH below to match a secret that exists in your
Infisical project.
"""

import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s  %(name)s  %(message)s",
    stream=sys.stdout,
)

SECRET_NAME = "GEMINI_API_KEY"  # <-- change me
SECRET_PATH = "/"               # <-- change me if the secret lives in a subfolder


def main() -> None:
    from src.services.key_vault.client import InfisicalClient
    from src.services.key_vault.config import InfisicalConfig

    config = InfisicalConfig()
    print(f"\nEndpoint : {config.endpoint}")
    print(f"Project  : {config.project_id}")
    print(f"Env      : {config.environment}")
    print(f"Secret   : {SECRET_NAME!r} at path {SECRET_PATH!r}\n")

    client = InfisicalClient(config=config)

    value = client.get_secret(SECRET_NAME, path=SECRET_PATH)
    # Print only first / last 4 chars so the secret is never fully exposed in logs
    masked = value[:4] + "****" + value[-4:] if len(value) >= 8 else "****"
    print(f"Secret value (masked): {masked}")
    print("\nSUCCESS")


if __name__ == "__main__":
    main()
