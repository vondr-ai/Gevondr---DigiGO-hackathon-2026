from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Optional
from uuid import UUID, uuid4

from attrs import define, field

from src.database.postgres.py_models import IntegrationType, OCRStatus


@define
class LocalDocumentStore:
    name: str  # Name for the document database (will be used as S3 prefix with integration_id)


@define
class SharepointConfig:
    client_id: str
    client_secret: str
    tenant_id: str  # Fixed typo: tennet_id -> tenant_id


class DocumentProcessingStatus(StrEnum):
    NOT_PROCESSED = "not_processed"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    SKIPPED = "skipped"


@define
class IndexKey:
    """Metadata schema definition for document collections"""

    key: str
    description: Optional[str] = None
    options: Optional[list[str | int | float | datetime]] = None
    datatype: Optional[type] = None
    id: UUID = field(default=uuid4())

    def __attrs_post_init__(self):
        if self.options and self.datatype:
            raise ValueError(
                "Cannot have both options (enum) and datatype (single type)"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        result: dict[str, Any] = {
            "key": self.key,
            "id": str(self.id),
        }
        if self.description is not None:
            result["description"] = self.description
        if self.options is not None:
            # Serialize options, handling datetime objects
            result["options"] = [
                opt.isoformat() if isinstance(opt, datetime) else opt
                for opt in self.options
            ]
        if self.datatype is not None:
            # Store datatype as string name
            result["datatype"] = self.datatype.__name__
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IndexKey":
        """Create IndexKey from dictionary."""
        # Parse datatype from string name
        datatype = None
        if "datatype" in data and data["datatype"]:
            type_map = {
                "str": str,
                "int": int,
                "float": float,
                "datetime": datetime,
            }
            datatype = type_map.get(data["datatype"])

        # Parse options, handling ISO datetime strings
        options = None
        if "options" in data and data["options"]:
            parsed_options = []
            for opt in data["options"]:
                if isinstance(opt, str) and "T" in opt:
                    # Try to parse as datetime
                    try:
                        parsed_options.append(datetime.fromisoformat(opt))
                    except ValueError:
                        parsed_options.append(opt)
                else:
                    parsed_options.append(opt)
            options = parsed_options

        return cls(
            key=data["key"],
            description=data.get("description"),
            options=options,
            datatype=datatype,
            id=UUID(data["id"]) if "id" in data else uuid4(),
        )

    def to_string(self) -> str:
        """Human-readable string representation."""
        type_info = "Any"

        if self.datatype:
            type_info = f"Type: {self.datatype.__name__}"
        elif self.options:
            # Limit display to first 3 options to avoid massive strings
            opts_preview = ", ".join(str(o) for o in self.options[:3])
            if len(self.options) > 3:
                opts_preview += ", ..."
            type_info = f"Options: [{opts_preview}]"

        desc_str = f" | {self.description}" if self.description else ""

        return f"IndexKey('{self.key}') [{type_info}]{desc_str}"


@define
class IndexValue:
    """Metadata value for a specific document"""

    key: str
    value: str
    key_id: UUID
    id: UUID | None = None

    def to_serializable_dict(self) -> dict[str, Any]:
        """Convert index value to JSON-serializable dict."""
        return {
            "key": self.key,
            "value": self.value,
            "key_id": str(self.key_id),
            "id": str(self.id) if self.id else None,
        }

    @classmethod
    def from_serialized(cls, data: Mapping[str, Any]) -> "IndexValue":
        """Recreate index value from serialized dict."""
        key_id = data.get("key_id")
        index_id = data.get("id")

        resolved_key_id = key_id if isinstance(key_id, UUID) else UUID(str(key_id))
        resolved_index_id = (
            index_id
            if index_id is None or isinstance(index_id, UUID)
            else UUID(str(index_id))
        )

        return cls(
            key=data["key"],
            value=data["value"],
            key_id=resolved_key_id,
            id=resolved_index_id,
        )


@define
class Folder:
    """Represents a folder in the document database hierarchy"""

    external_id: str
    name: str
    integration_id: UUID
    path: str
    document_index_id: UUID | None = None
    id: UUID | None = None
    parent_id: UUID | None = None
    web_url: Optional[str] = None
    created_at: datetime = datetime.now(timezone.utc)
    modified_at: datetime = datetime.now(timezone.utc)
    metadata: Optional[dict] = None

    def get_depth(self) -> int:
        """Returns the depth of this folder in the hierarchy"""
        return len([p for p in self.path.split("/") if p])

    def is_root(self) -> bool:
        """Check if this is a root folder"""
        return self.parent_id is None


@define
class DocumentUnitBase:
    # === ALWAYS PRESENT (filled at discovery) ===
    id: UUID
    integration_id: UUID
    external_id: str
    filename: str
    path: str
    size: int
    web_url: str
    external_created_at: datetime
    external_modified_at: datetime
    status: DocumentProcessingStatus

    created_at: datetime = field(factory=lambda: datetime.now(timezone.utc))

    # === OPTIONAL (filled at discovery) ===
    document_index_id: UUID | None = None  # NULL = staging area, non-NULL = indexed
    folder_id: UUID | None = None
    download_url: Optional[str] = None
    metadata: Optional[dict] = None
    content_hash: Optional[str] = None
    canonical_document_id: Optional[UUID] = None
    revision_group_id: Optional[UUID] = None
    revision_rank: Optional[int] = None
    is_latest_revision: bool = True

    # === FILLED AFTER PROCESSING ===
    pages: Optional[int] = None
    processed_at: Optional[datetime] = None
    retry_count: int = 0
    run_ocr: bool = False
    ocr_status: OCRStatus = OCRStatus.NOT_REQUESTED
    ocr_error_message: Optional[str] = None
    ocr_requested_at: Optional[datetime] = None
    ocr_completed_at: Optional[datetime] = None


@define
class DocumentUnit(DocumentUnitBase):
    """Represents a document in various stages of processing"""

    # === FILLED AFTER PROCESSING ===
    full_text: Optional[str] = None
    short_summary: Optional[str] = None
    summary: Optional[str] = None
    document_type: Optional[str] = None
    value_streams: Optional[list[str]] = None

    # === METADATA (stored as JSONB) ===
    index_values: Optional[list[IndexValue]] = None

    # === ERROR TRACKING ===
    error_message: Optional[str] = None


class DocumentConnectionType(StrEnum):
    """Types of relationships between documents."""

    REVISION = "revision"
    RELEVANT = "relevant"
    DUPLICATE = "duplicate"


@define
class DocumentConnection:
    """Represents a relationship between two document units."""

    id: UUID
    source_id: UUID
    target_id: UUID
    type: DocumentConnectionType
    created_by: UUID
    created_at: datetime
    description: Optional[str] = None

    @classmethod
    def create(
        cls,
        source_id: UUID,
        target_id: UUID,
        connection_type: DocumentConnectionType,
        created_by: UUID,
        description: Optional[str] = None,
    ) -> "DocumentConnection":
        """Factory helper to create a new connection with generated id/timestamps."""
        now = datetime.now(timezone.utc)
        return cls(
            id=uuid4(),
            source_id=source_id,
            target_id=target_id,
            type=connection_type,
            created_by=created_by,
            created_at=now,
            description=description,
        )


@define
class FilenameSearchResult:
    document_id: UUID
    filename: str
    score: float


@define
class ExternalDocument:
    id: str
    filename: str
    created_at: datetime
    modified_at: datetime
    folder_id: Optional[UUID]  # Can be None for root-level files
    path: str
    size: int
    web_url: str
    download_url: Optional[str] = None
    metadata: Optional[dict] = None

    def to_unit(
        self,
        integration_id: UUID,
        document_index_id: UUID | None = None,
        doc_process_status: DocumentProcessingStatus = DocumentProcessingStatus.NOT_PROCESSED,
    ) -> DocumentUnitBase:
        return DocumentUnitBase(
            id=uuid4(),
            integration_id=integration_id,
            document_index_id=document_index_id,
            external_id=self.id,
            filename=self.filename,
            path=self.path,
            size=self.size,
            web_url=self.web_url,
            folder_id=self.folder_id,
            external_created_at=self.created_at,
            external_modified_at=self.modified_at,
            status=doc_process_status,
            metadata=self.metadata,
            content_hash=self.metadata.get("hash") if self.metadata else None,
        )


@define
class FolderHierarchy:
    """Manages the complete folder structure for an integration"""

    integration_id: UUID
    folders: dict[UUID, Folder] = field(factory=dict)  # folder_id -> Folder
    folders_by_external_id: dict[str, Folder] = field(
        factory=dict
    )  # external_id -> Folder

    def add_folder(self, folder: Folder) -> None:
        """Add a folder to the hierarchy, skipping duplicates by external_id."""
        assert folder.id
        if folder.external_id in self.folders_by_external_id:
            return
        self.folders[folder.id] = folder
        self.folders_by_external_id[folder.external_id] = folder

    def get_folder(self, folder_id: UUID) -> Optional[Folder]:
        """Get folder by internal ID"""
        return self.folders.get(folder_id)

    def get_folder_by_external_id(self, external_id: str) -> Optional[Folder]:
        """Get folder by external ID (from SharePoint/Drive)"""
        return self.folders_by_external_id.get(external_id)

    def get_children(self, folder_id: UUID) -> list[Folder]:
        """Get all direct children of a folder"""
        return [f for f in self.folders.values() if f.parent_id == folder_id]

    def get_root_folders(self) -> list[Folder]:
        """Get all root folders"""
        return [f for f in self.folders.values() if f.is_root()]

    def get_folder_tree(self, folder_id: Optional[UUID] = None) -> dict:
        """Get folder tree structure starting from a folder (or all roots if None)"""
        if folder_id is None:
            return {
                "roots": [
                    self._build_tree(root.id)
                    for root in self.get_root_folders()
                    if root.id is not None
                ]
            }
        return self._build_tree(folder_id)

    def _build_tree(self, folder_id: UUID | None) -> dict:
        """Recursively build tree structure"""
        if folder_id is None:
            return {}

        folder = self.get_folder(folder_id)
        if not folder:
            return {}

        children = self.get_children(folder_id)
        return {
            "folder": folder,
            "children": [
                self._build_tree(child.id) for child in children if child.id is not None
            ],
        }


@define
class DocumentDatabaseIndex:
    """
    Represents a document index configuration attached to a single source integration.
    """

    id: UUID
    name: str
    description: str
    source_integration_id: UUID
    source_integration_type: IntegrationType
    created_by: UUID
    created_at: datetime
    modified_at: datetime
    last_synced_at: Optional[datetime] = None
    doc_count: int = 0
    size: int = 0
    page_count: int = 0
    keys: list[IndexKey] = field(factory=list)
    folder_hierarchy: Optional[FolderHierarchy] = None
    is_locked: bool = False

    def rebuild_folder_hierarchy(self, folders: list[Folder]) -> None:
        """Rebuild the folder hierarchy from a list of folders"""
        self.folder_hierarchy = FolderHierarchy(
            integration_id=self.source_integration_id
        )
        for folder in folders:
            self.folder_hierarchy.add_folder(folder)

    def get_documents_in_folder(
        self, folder_id: UUID, documents: list[DocumentUnit], recursive: bool = False
    ) -> list[DocumentUnit]:
        """Get all documents in a specific folder"""
        if not recursive:
            return [doc for doc in documents if doc.folder_id == folder_id]

        # Get folder and all descendants
        folder_ids = {folder_id}
        if self.folder_hierarchy:
            folder_ids.update(self._get_descendant_folder_ids(folder_id))

        return [doc for doc in documents if doc.folder_id in folder_ids]

    def _get_descendant_folder_ids(self, folder_id: UUID | None) -> set[UUID]:
        """Get all descendant folder IDs recursively"""
        descendants = set()
        if folder_id is None or not self.folder_hierarchy:
            return descendants

        children = self.folder_hierarchy.get_children(folder_id)
        for child in children:
            if child.id is None:
                continue
            descendants.add(child.id)
            descendants.update(self._get_descendant_folder_ids(child.id))

        return descendants

    def can_update_schema(self) -> bool:
        """Return True when schema (keys) remain editable."""
        return not self.is_locked and self.doc_count == 0
