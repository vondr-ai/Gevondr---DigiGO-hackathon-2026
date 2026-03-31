from dataclasses import dataclass, field
import os

from dotenv import load_dotenv
load_dotenv()


@dataclass
class InfisicalConfig:
    endpoint: str = field(default_factory=lambda: os.getenv("INFISICAL_ENDPOINT", ""))
    client_id: str = field(default_factory=lambda: os.getenv("INFISICAL_CLIENT_ID", ""))
    client_secret: str = field(default_factory=lambda: os.getenv("INFISICAL_CLIENT_SECRET", ""))
    project_id: str = field(default_factory=lambda: os.getenv("INFISICAL_PROJECT_ID", ""))
    environment:str = field(default_factory=lambda: os.getenv("ENVIRONMENT", ""))