from abc import abstractmethod, ABC
from pathlib import Path

from src.services.document_database.ocr.doc_router import ProcessDecision



class FileReader(ABC):

    @abstractmethod
    async def read(
        self,
        filename:str,
        path:str,
        fate:ProcessDecision
    ) -> str:
        """
        Read and process the document content.

        Args:
            filename: The name of the file
            path: The path to the file
            fate: Processing decision (READ or OCR)

        Returns:
            The processed text content from the document
        """
        pass

    @abstractmethod
    def get_page_count(self, filename: str, path: str) -> int:
        """
        Get the number of pages in the document.

        Args:
            filename: The name of the file
            path: The path to the file

        Returns:
            The number of pages in the document. Returns 1 for single-page documents.
        """
        pass

    def _resolve_file_path(self, path: str, filename: str) -> Path:
        """
        Helper method to resolve the full file path.

        Args:
            path: The path (can be file or directory)
            filename: The filename

        Returns:
            The resolved Path object
        """
        file_path = Path(path)
        if not file_path.is_file():
            file_path = Path(path) / filename
        return file_path


