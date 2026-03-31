# src\database\postgres\py_models.py
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Optional
from uuid import UUID

from attrs import define, field


class UserRole(StrEnum):
    NORMAL = "normal"
    ADMIN = "admin"
    SYSTEM = "system"


class GroupIcon(StrEnum):
    """
    Available icons for groups, mapped to Lucide Vue icon names.
    Geometric shapes for visual differentiation.
    """

    # Default
    CIRCLE = "circle"  # Circle - default

    # Basic Shapes
    SQUARE = "square"  # Square
    TRIANGLE = "triangle"  # Triangle
    PENTAGON = "pentagon"  # Pentagon
    HEXAGON = "hexagon"  # Hexagon
    OCTAGON = "octagon"  # Octagon

    # Stars
    STAR = "star"  # Star
    SPARKLE = "sparkle"  # Sparkle

    # Diamonds & Gems
    DIAMOND = "diamond"  # Diamond
    GEM = "gem"  # Gem

    # Hearts & Symbols
    HEART = "heart"  # Heart
    CLUB = "club"  # Club
    SPADE = "spade"  # Spade

    # Special Shapes
    CLOVER = "clover"  # Clover
    FLOWER = "flower"  # Flower
    DROPLET = "droplet"  # Droplet


@define
class User:
    id: UUID
    membership_id: UUID
    email: str
    first_name: str
    last_name: str
    role: UserRole
    created_at: datetime
    modified_at: datetime
    project_omgevingen: list["ProjectOmgeving"] | None = None
    relatics_token_id: Optional[UUID] = None
    password: Optional[str] = None
    last_login_at: Optional[datetime] = None
    profile_image_url: Optional[str] = None


@define
class UserAssets:
    user_id: UUID
    profile_image_key: Optional[str] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime = datetime.now(timezone.utc)
    modified_at: datetime = datetime.now(timezone.utc)


@define
class GroupAsset:
    group_id: UUID
    icon: str = "circle"
    created_at: datetime = datetime.now(timezone.utc)
    modified_at: datetime = datetime.now(timezone.utc)


class IntegrationType(StrEnum):
    UPLOAD = "upload"
    RELATICS_ACTIVE = "relatics_active"
    RELATICS_HISTORIC = "relatics_historic"
    PRIMAVERA_HISTORIC = "primavera_historic"
    SHAREPOINT = "sharepoint"
    ACC = "acc"


class IntegrationSyncStatus(StrEnum):
    PENDING = "pending"  # Waiting for file upload to complete
    SYNCED = "synced"
    IN_PROGRESS = "in_progress"
    IN_QUEUE = "in_queue"
    CONNECTED = "connected"
    FAILED = "failed"


class IntegrationAccessMode(StrEnum):
    """Access mode for an integration within a specific ProjectOmgeving context."""

    READ_ONLY = "read_only"
    READ_WRITE = "read_write"


@define
class ProjectOmgeving:
    id: UUID
    name: str
    created_at: datetime
    modified_at: datetime
    created_by: UUID
    integrations: list[UUID]
    is_protected: bool = False
    color: Optional[str] = None
    image_url: Optional[str] = None
    creator: Optional[User] = None


@define
class IntegrationPermissons:
    pass


@define
class IntegrationMetadata:
    """Base model for project metadata."""

    id: UUID
    name: str
    created_at: datetime
    modified_at: datetime
    created_by: UUID  # user_id
    sync_status: IntegrationSyncStatus  # Updated from currently_syncing
    type: IntegrationType
    read_only: bool
    is_protected: bool = field(default=False, kw_only=True)
    last_synced_at: Optional[datetime] = field(default=None, kw_only=True)

    def to_string(self) -> str:
        """
        Returns a human-readable, LLM-friendly string representation of the integration object.
        """
        # Format timestamps nicely
        # Determine the access mode
        access_mode = "Read-Only 🔒" if self.read_only else "Read/Write 🔄"

        # Determine sync status icon
        if self.sync_status == IntegrationSyncStatus.SYNCED:
            status_icon = "✅"
        elif self.sync_status == IntegrationSyncStatus.IN_PROGRESS:
            status_icon = "⏳"
        else:
            status_icon = "❌"
        type_display = ""

        if self.type == IntegrationType.RELATICS_ACTIVE:
            type_display = "Active Relatics project"
        elif self.type == IntegrationType.RELATICS_HISTORIC:
            type_display = "Historic Relatics project"
        elif self.type == IntegrationType.PRIMAVERA_HISTORIC:
            type_display = "Historic Primavera P6 project"
        elif self.type == IntegrationType.SHAREPOINT:
            type_display = "SharePoint document integration"
        elif self.type == IntegrationType.ACC:
            type_display = "Autodesk Construction Cloud integration"

        # Construct the final string
        return (
            f"**Integration Summary:**\n"
            f"| :--- | :--- |\n"
            f"| **Name** | {self.name} |\n"
            f"| **Type** | {type_display} |\n"
            f"| **Status** | **{self.sync_status}** {status_icon} |\n"
            f"| **Access** | {access_mode} |\n"
        )


@define
class ActiveRelaticsMetadata(IntegrationMetadata):
    """Metadata specific to an active Relatics project."""

    hostname: str
    environment_id: str
    workspace_id: str
    type: IntegrationType = IntegrationType.RELATICS_ACTIVE


@define
class HistoricRelaticsMetadata(IntegrationMetadata):
    """Metadata specific to a historic Relatics project."""

    s3_key: str
    filename: str
    type: IntegrationType = IntegrationType.RELATICS_HISTORIC


@define
class HistoricPrimaveraMetadata(IntegrationMetadata):
    """Metadata specific to a historic Primavera P6 project (XER upload)."""

    s3_key: str
    filename: str
    type: IntegrationType = IntegrationType.PRIMAVERA_HISTORIC


@define
class SharepointMetadata(IntegrationMetadata):
    """Metadata specific to a SharePoint integration."""

    site_id: str
    tenant_id: str
    site_name: str = ""
    type: IntegrationType = IntegrationType.SHAREPOINT

    # Staging area statistics (documents discovered but not yet indexed)
    total_documents: int = 0  # Total documents discovered from SharePoint
    total_size: int = 0  # Total size in bytes of all discovered documents


@define
class AccMetadata(IntegrationMetadata):
    """Metadata specific to an Autodesk Construction Cloud integration."""

    hub_id: str
    project_id: str
    project_name: str = ""
    type: IntegrationType = IntegrationType.ACC

    total_documents: int = 0
    total_size: int = 0


class DocumentType(StrEnum):
    UPLOADED = "uploaded"  # a document uploaded in any chatting context
    REPORT = "report"  # a report generated by our system
    PROJECTANALYSE = "projectanalyse"
    PROJECT_CONTEXT = "project_context"  # a document providing project context


class OCRStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentAssetStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@define
class DocumentBase:
    id: UUID
    user_id: UUID
    filename: str


class TokenProvider(StrEnum):
    RELATICS = "relatics"
    RELATICS_API = "relatics-api"
    MICROSOFT = "microsoft"


class OAuth2Provider(StrEnum):
    RELATICS = "relatics"


class OAuth2GrantType(StrEnum):
    AUTHORIZATION_CODE = "authorization_code"
    CLIENT_CREDENTIALS = "client_credentials"


class OAuth2ClientPurpose(StrEnum):
    API = "api"
    WEBSERVICE = "webservice"


@define
class Tokens:
    provider: TokenProvider
    access_token: str
    expires_at: datetime
    refresh_token: Optional[str] = None


@define
class OAuth2Client:
    id: UUID
    provider: OAuth2Provider
    name: str
    client_id: str
    client_secret: str
    tenant_id: Optional[str]
    base_url: str
    token_url: str
    scopes: Optional[list[str]]
    grant_type: OAuth2GrantType
    metadata: dict
    created_at: datetime
    modified_at: datetime


@define
class Document(DocumentBase):
    type: DocumentType
    project_omgeving_id: UUID
    created_at: datetime = datetime.now(timezone.utc)
    modified_at: datetime = datetime.now(timezone.utc)

    thread_id: Optional[UUID] = None
    s3_key: Optional[str] = None
    full_text: Optional[str] = None
    summary_text: Optional[str] = None
    pages: Optional[int] = None
    run_ocr: bool = False
    ocr_status: OCRStatus = OCRStatus.NOT_REQUESTED
    ocr_error_message: Optional[str] = None
    ocr_requested_at: Optional[datetime] = None
    ocr_completed_at: Optional[datetime] = None
    file_upload_status: DocumentAssetStatus = DocumentAssetStatus.PENDING
    file_upload_error_message: Optional[str] = None
    file_uploaded_at: Optional[datetime] = None
    page_image_status: DocumentAssetStatus = DocumentAssetStatus.PENDING
    page_image_error_message: Optional[str] = None
    page_images_completed_at: Optional[datetime] = None


@define
class IntegrationPrompt:
    id: UUID
    content: str
    is_active: bool
    created_by_user_id: UUID
    created_at: datetime
    project_omgeving_id: Optional[UUID] = None
    integration_id: Optional[UUID] = None

    def __attrs_post_init__(self):
        """Validate that exactly one of project_omgeving_id or integration_id is set."""
        if (self.project_omgeving_id is None and self.integration_id is None) or (
            self.project_omgeving_id is not None and self.integration_id is not None
        ):
            raise ValueError(
                "Exactly one of project_omgeving_id or integration_id must be set"
            )


@define
class Skill:
    """Represents a structured, domain-specific workflow (Agent Skill)."""

    id: UUID
    name: str  # Level 1: Name for display/tool call
    description: str  # Level 1: Short description for system prompt
    full_content: str  # Level 2: Full markdown/instructions for tool response
    project_omgeving_id: UUID  # Foreign Key to project_omgeving
    is_active: bool
    created_at: datetime
    modified_at: datetime
    created_by_user_id: UUID
    current_version_id: Optional[UUID] = None  # FK to skill_version


@define
class SkillVersion:
    """Represents a historical snapshot of a skill's content."""

    id: UUID
    skill_id: UUID
    version_number: int  # Incrementing per skill (1, 2, 3, ...)
    name: str  # Snapshot of name at this version
    description: str  # Snapshot of description at this version
    full_content: str  # Snapshot of full_content at this version
    created_at: datetime
    created_by_user_id: UUID
    change_summary: Optional[str] = None  # Optional description of what changed


@define
class SkillExecution:
    """Tracks when a skill was triggered via get_skill_content_tool or automation."""

    id: UUID
    skill_id: UUID
    skill_version_id: Optional[
        UUID
    ]  # FK to skill_version (nullable for backwards compat)
    user_id: UUID  # Who triggered the skill
    thread_id: Optional[UUID]  # In which conversation thread
    project_omgeving_id: UUID
    triggered_at: datetime
    automation_id: Optional[UUID] = None
    scheduled_for: Optional[datetime] = None
    status: Optional[str] = None  # "running" | "completed" | "failed"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    result_summary: Optional[str] = None


@define
class SkillAutomation:
    """Represents a scheduled automation for a skill."""

    id: UUID
    skill_id: UUID
    project_omgeving_id: UUID
    created_by_user_id: UUID
    cron_expression: str
    timezone: str
    is_enabled: bool
    user_prompt: str
    created_at: datetime
    modified_at: datetime
    skip_action_approval: bool = False
    last_triggered_at: Optional[datetime] = None
    next_trigger_at: Optional[datetime] = None


@define
class SupportRequest:
    id: UUID
    user_id: UUID
    project_omgeving_id: UUID
    subject: str
    message: str
    created_at: datetime
    modified_at: datetime


@define
class IntegrationInterest:
    id: UUID
    user_id: UUID
    platform_id: str
    created_at: datetime
    modified_at: datetime


@define
class DocumentUserAccess:
    """Tracks which users have access to which documents (discovered via sync)."""

    id: UUID
    document_id: UUID
    user_id: UUID
    discovered_at: datetime | None = None


@define
class UserSharepointSync:
    """Per-user sync state for a SharePoint integration."""

    id: UUID
    user_id: UUID
    integration_id: UUID
    membership_id: UUID | None = None
    delta_tokens: dict[str, str] | None = None
    sync_status: str = "NOT_SYNCED"
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@define
class UserAccSync:
    """Per-user sync state for an ACC integration."""

    id: UUID
    user_id: UUID
    integration_id: UUID
    cursor_state: dict | None = None
    sync_status: str = "NOT_SYNCED"
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@define
class IntegrationWithProjectContext:
    """
    Wrapper for IntegrationMetadata with project-specific access mode.
    Used when fetching integrations within a specific ProjectOmgeving context.
    """

    integration: IntegrationMetadata
    access_mode: IntegrationAccessMode

    @property
    def effective_read_only(self) -> bool:
        """
        Calculate effective read-only status using master override logic.
        If the integration is globally read-only OR the project-level access is read-only,
        the result is read-only.
        """
        return (
            self.integration.read_only
            or self.access_mode == IntegrationAccessMode.READ_ONLY
        )
