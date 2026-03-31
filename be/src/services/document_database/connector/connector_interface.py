from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from uuid import UUID

from src.database.postgres.document_index_models import DocumentUnitBase
from src.database.postgres.document_index_models import ExternalDocument
from src.database.postgres.document_index_models import FolderHierarchy


class DocumentIndexConnector(ABC):
    """
    Abstract interface for document source connectors.

    Connectors are responsible for:
    1. Authenticating with external document sources
    2. Fetching folder hierarchy and document metadata
    3. Providing download capabilities for documents

    Implementations:
    - VondrDocumentDBConnector: S3-backed document storage
    - SharePointConnector: Microsoft SharePoint/OneDrive integration
    """

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authenticate with the document source.

        Returns:
            True if authentication successful, False otherwise
        """
        pass

    @abstractmethod
    async def get_updated_database(
        self,
        integration_id: UUID,
        *,
        max_documents: int | None = None,
        offset_documents: int = 0,
        disable_deletions: bool = False,
    ) -> tuple[FolderHierarchy, list[ExternalDocument], list[str]]:
        """
        Fetch the current state of the document database from the source.

        This method should:
        1. Fetch all folders and build the hierarchy
        2. Fetch all documents with their metadata
        3. Detect any documents that have been deleted from the source

        Args:
            integration_id: UUID of the integration (used for folder/document linkage)
            max_documents: Optional cap on returned documents (for partial runs)
            offset_documents: Number of documents to skip before returning results
            disable_deletions: If True, connector should never return deleted IDs

        Returns:
            Tuple containing:
            - FolderHierarchy: Complete folder structure from the source
            - list[ExternalDocument]: All documents with metadata
            - list[str]: External IDs of documents that were deleted from source
        """
        pass

    @abstractmethod
    async def get_download_url(
        self, external_docs: list[DocumentUnitBase]
    ) -> list[DocumentUnitBase]:
        """
        Populate the download_url field for documents.

        For sources that require presigned URLs (e.g., SharePoint), this method
        should generate and populate the download_url field.

        For sources that don't use presigned URLs (e.g., VondrDocumentDB with S3),
        this can be a no-op that just returns the documents as-is.

        Args:
            external_docs: Documents to populate download URLs for

        Returns:
            The same documents with download_url field populated
        """
        pass

    @abstractmethod
    async def get_metadata(
        self, external_docs: list[DocumentUnitBase]
    ) -> list[DocumentUnitBase]:
        """
        Enrich documents with additional metadata from the source.

        This method can be used to fetch extra metadata that wasn't included
        in the initial get_updated_database() call. For sources where all
        metadata is already fetched, this can be a no-op.

        Args:
            external_docs: Documents to enrich with metadata

        Returns:
            Documents with enriched metadata field
        """
        pass

    @abstractmethod
    async def download(self, external_doc: DocumentUnitBase) -> bytes | None:
        """
        Download the binary content of a document.

        This method should:
        1. Use the document's external_id, download_url, or path to locate the file
        2. Download the file bytes from the source
        3. Return the raw bytes

        Args:
            external_doc: Document to download

        Returns:
            Document bytes if successful, None if download fails
        """
        pass
