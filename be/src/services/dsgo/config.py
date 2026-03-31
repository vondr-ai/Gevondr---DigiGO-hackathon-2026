"""Load configuration from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def get_config() -> dict:
    return {
        "client_id": os.environ["DSGO_CLIENT_ID"],
        "private_key_path": os.environ["DSGO_PRIVATE_KEY_PATH"],
        "certificate_path": os.environ["DSGO_CERTIFICATE_PATH"],
        "registry_url": os.environ["DSGO_REGISTRY_URL"],
        "registry_party_id": os.environ["DSGO_REGISTRY_PARTY_ID"],
    }
