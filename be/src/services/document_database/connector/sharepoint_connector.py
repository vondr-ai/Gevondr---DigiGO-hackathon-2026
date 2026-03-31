from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID
from uuid import uuid4

import httpx
from attrs import define
from attrs import field

from src.database.postgres.document_index_models import DocumentUnitBase
from src.database.postgres.document_index_models import ExternalDocument
from src.database.postgres.document_index_models import Folder
from src.database.postgres.document_index_models import FolderHierarchy
from src.database.session_manager import SessionManager

logger = logging.getLogger(__name__)


@define
class SharePointConnector:
    """
    Connector for Microsoft SharePoint document libraries using delegated permissions.

    This connector:
    - Uses a pre-obtained access token (resolved via identity-backed token adapter)
    - Iterates over all drives in a site
    - Uses Microsoft Graph delta queries for efficient incremental syncing
    - Fetches folder hierarchy and document metadata
    - Tracks per-drive delta tokens
    """

    site_id: str
    access_token: str
    session_manager: SessionManager
    _new_delta_tokens: dict[str, str] = field(factory=dict, init=False)

    GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

    async def list_drives(self) -> list[dict]:
        """List all document library drives for the site."""
        url = f"{self.GRAPH_API_BASE}/sites/{self.site_id}/drives"
        headers = {"Authorization": f"Bearer {self.access_token}"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                logger.error(
                    "Failed to list drives for site %s: %s - %s",
                    self.site_id,
                    response.status_code,
                    response.text,
                )
                return []

            data = response.json()
            drives = data.get("value", [])
            logger.info("Found %d drives for site %s", len(drives), self.site_id)
            return drives

    async def get_updated_database(
        self,
        integration_id: UUID,
        delta_tokens: dict[str, str] | None = None,
    ) -> tuple[FolderHierarchy, list[ExternalDocument], list[str], dict[str, str]]:
        """
        Fetch changes from all drives in the SharePoint site using delta queries.

        Args:
            integration_id: UUID of the integration
            delta_tokens: Per-drive delta tokens from previous sync

        Returns:
            Tuple of (folders, documents, deleted_ids, new_delta_tokens)
        """
        delta_tokens = delta_tokens or {}
        self._new_delta_tokens = {}

        drives = await self.list_drives()
        if not drives:
            logger.warning("No drives found for site %s", self.site_id)
            return (
                FolderHierarchy(integration_id=integration_id),
                [],
                [],
                {},
            )

        all_folder_hierarchy = FolderHierarchy(integration_id=integration_id)
        all_documents: list[ExternalDocument] = []
        all_deleted_ids: list[str] = []

        for drive in drives:
            drive_id = drive.get("id")
            if not drive_id:
                continue

            existing_token = delta_tokens.get(drive_id)

            if existing_token:
                logger.info(
                    "Using delta token for incremental sync of drive %s", drive_id
                )
                delta_url = existing_token
            else:
                logger.info(
                    "No delta token for drive %s - performing full sync", drive_id
                )
                delta_url = f"{self.GRAPH_API_BASE}/drives/{drive_id}/root/delta"

            folders, docs, deleted = await self._process_delta_response(
                integration_id, delta_url, drive_id
            )

            for folder in folders.folders.values():
                all_folder_hierarchy.add_folder(folder)
            all_documents.extend(docs)
            all_deleted_ids.extend(deleted)

        logger.info(
            "Multi-drive sync complete: %d folders, %d documents, %d deletions across %d drives",
            len(all_folder_hierarchy.folders),
            len(all_documents),
            len(all_deleted_ids),
            len(drives),
        )

        return (
            all_folder_hierarchy,
            all_documents,
            all_deleted_ids,
            self._new_delta_tokens,
        )

    async def _process_delta_response(
        self,
        integration_id: UUID,
        delta_url: str,
        drive_id: str,
    ) -> tuple[FolderHierarchy, list[ExternalDocument], list[str]]:
        """Process delta API response for a single drive."""
        headers = {"Authorization": f"Bearer {self.access_token}"}
        folder_hierarchy = FolderHierarchy(integration_id=integration_id)
        documents: list[ExternalDocument] = []
        deleted_external_ids: list[str] = []

        current_url = delta_url

        async with httpx.AsyncClient(timeout=120.0) as client:
            while current_url:
                try:
                    response = await client.get(current_url, headers=headers)

                    if response.status_code != 200:
                        logger.error(
                            "Failed to fetch delta from SharePoint drive %s: %s - %s",
                            drive_id,
                            response.status_code,
                            response.text,
                        )
                        break

                    data = response.json()

                    for item in data.get("value", []):
                        self._process_delta_item(
                            item,
                            integration_id,
                            folder_hierarchy,
                            documents,
                            deleted_external_ids,
                        )

                    next_link = data.get("@odata.nextLink")
                    delta_link = data.get("@odata.deltaLink")

                    if delta_link:
                        self._new_delta_tokens[drive_id] = delta_link
                        logger.info("Captured new delta token for drive %s", drive_id)
                        current_url = None
                    elif next_link:
                        current_url = next_link
                    else:
                        logger.warning(
                            "Delta response for drive %s ended without delta token",
                            drive_id,
                        )
                        current_url = None

                except Exception as e:
                    logger.error(
                        "Error processing delta response for drive %s: %s",
                        drive_id,
                        e,
                        exc_info=True,
                    )
                    break

        return folder_hierarchy, documents, deleted_external_ids

    def _process_delta_item(
        self,
        item: dict,
        integration_id: UUID,
        folder_hierarchy: FolderHierarchy,
        documents: list[ExternalDocument],
        deleted_external_ids: list[str],
    ) -> None:
        """Process a single item from delta response."""
        if "deleted" in item:
            deleted_external_ids.append(item["id"])
            return

        if item.get("id") == "root" or item.get("name") == "root":
            return

        if "folder" in item:
            folder = self._item_to_folder(item, integration_id, folder_hierarchy)
            if folder:
                folder_hierarchy.add_folder(folder)

        elif "file" in item:
            document = self._item_to_document(item, folder_hierarchy)
            if document:
                documents.append(document)

    def _item_to_folder(
        self, item: dict, integration_id: UUID, folder_hierarchy: FolderHierarchy
    ) -> Optional[Folder]:
        """Convert a SharePoint item to a Folder domain object."""
        try:
            parent_id = None
            parent_path = ""

            parent_ref = item.get("parentReference", {})
            parent_external_id = parent_ref.get("id")

            if parent_external_id and parent_external_id != "root":
                parent_folder = folder_hierarchy.get_folder_by_external_id(
                    parent_external_id
                )
                if parent_folder:
                    parent_id = parent_folder.id
                    parent_path = parent_folder.path

            folder_path = (
                f"{parent_path}/{item['name']}" if parent_path else item["name"]
            )

            return Folder(
                id=uuid4(),
                external_id=item["id"],
                name=item["name"],
                path=folder_path,
                integration_id=integration_id,
                document_index_id=None,
                parent_id=parent_id,
                web_url=item.get("webUrl"),
                metadata={},
                created_at=datetime.fromisoformat(
                    item["createdDateTime"].replace("Z", "+00:00")
                ),
                modified_at=datetime.fromisoformat(
                    item["lastModifiedDateTime"].replace("Z", "+00:00")
                ),
            )
        except Exception as e:
            logger.error("Error converting item to folder: %s", e, exc_info=True)
            return None

    def _item_to_document(
        self, item: dict, folder_hierarchy: FolderHierarchy
    ) -> Optional[ExternalDocument]:
        """Convert a SharePoint item to an ExternalDocument domain object."""
        try:
            folder_id = None
            folder_path = ""

            parent_ref = item.get("parentReference", {})
            parent_external_id = parent_ref.get("id")

            if parent_external_id and parent_external_id != "root":
                parent_folder = folder_hierarchy.get_folder_by_external_id(
                    parent_external_id
                )
                if parent_folder:
                    folder_id = parent_folder.id
                    folder_path = parent_folder.path

            doc_path = f"{folder_path}/{item['name']}" if folder_path else item["name"]

            return ExternalDocument(
                id=item["id"],
                filename=item["name"],
                created_at=datetime.fromisoformat(
                    item["createdDateTime"].replace("Z", "+00:00")
                ),
                modified_at=datetime.fromisoformat(
                    item["lastModifiedDateTime"].replace("Z", "+00:00")
                ),
                folder_id=folder_id,
                path=doc_path,
                size=item.get("size", 0),
                web_url=item.get("webUrl", ""),
                download_url=None,
                metadata={
                    "mime_type": item.get("file", {}).get("mimeType"),
                    "hash": item.get("file", {}).get("hashes", {}).get("quickXorHash"),
                    "drive_id": parent_ref.get("driveId"),
                    "created_by": item.get("createdBy", {})
                    .get("user", {})
                    .get("displayName"),
                    "modified_by": item.get("lastModifiedBy", {})
                    .get("user", {})
                    .get("displayName"),
                },
            )
        except Exception as e:
            logger.error("Error converting item to document: %s", e, exc_info=True)
            return None

    async def get_download_url(
        self, external_docs: list[DocumentUnitBase]
    ) -> list[DocumentUnitBase]:
        """Populate download URLs using Graph API item content endpoints."""
        for doc in external_docs:
            if doc.external_id:
                # We need the drive_id from the item's parentReference.
                # For now, use the /sites/{site_id}/drive/items/{item_id}/content pattern
                # which works for the default drive. For multi-drive, we store drive info in metadata.
                drive_id = (doc.metadata or {}).get("drive_id")
                if drive_id:
                    doc.download_url = (
                        f"{self.GRAPH_API_BASE}/drives/{drive_id}"
                        f"/items/{doc.external_id}/content"
                    )
                else:
                    doc.download_url = (
                        f"{self.GRAPH_API_BASE}/sites/{self.site_id}"
                        f"/drive/items/{doc.external_id}/content"
                    )
        return external_docs

    async def download(self, doc: DocumentUnitBase) -> bytes | None:
        """Download document content from SharePoint."""
        if not doc.download_url:
            logger.error("No download URL for document: %s", doc.filename)
            return None

        headers = {"Authorization": f"Bearer {self.access_token}"}
        max_retries = 3

        for attempt in range(max_retries):
            try:
                timeout_config = httpx.Timeout(600.0, connect=60.0)
                async with httpx.AsyncClient(
                    timeout=timeout_config, follow_redirects=True
                ) as client:
                    async with client.stream(
                        "GET", doc.download_url, headers=headers
                    ) as response:
                        if response.status_code == 200:
                            content = await response.aread()
                            logger.info(
                                "Downloaded %s (%d bytes) from SharePoint",
                                doc.filename,
                                len(content),
                            )
                            return content
                        else:
                            logger.error(
                                "Failed to download %s: %s",
                                doc.filename,
                                response.status_code,
                            )
                            if response.status_code < 500:
                                return None

            except (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException) as e:
                wait_time = 2 * (attempt + 1)
                logger.warning(
                    "Attempt %d/%d failed for %s: %s. Retrying in %ds...",
                    attempt + 1,
                    max_retries,
                    doc.filename,
                    e,
                    wait_time,
                )
                if attempt == max_retries - 1:
                    logger.error(
                        "Final failure downloading %s after %d attempts",
                        doc.filename,
                        max_retries,
                    )
                    return None
                await asyncio.sleep(wait_time)

            except Exception as e:
                logger.error(
                    "Error downloading %s from SharePoint: %s",
                    doc.filename,
                    e,
                    exc_info=True,
                )
                return None

        return None
