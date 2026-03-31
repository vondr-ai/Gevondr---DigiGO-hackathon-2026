from pathlib import Path

from src.services.document_database.ocr.doc_router import ProcessDecision
from src.services.document_database.ocr.types.interface import FileReader


class TxtReader(FileReader):

    async def read(
        self,
        filename: str,
        path: str,
        fate: ProcessDecision
    ) -> str:
        """
        Reads plain text files.

        Args:
            filename: The name of the file
            path: The path to the file
            fate: Processing decision (ignored for text files)

        Returns:
            The text content with filename header
        """
        if fate == ProcessDecision.OCR:
            # Text files don't require OCR
            raise ValueError("OCR is not applicable for plain text files")

        file_path = Path(path)
        if not file_path.is_file():
            file_path = Path(path) / filename

        try:
            # Try UTF-8 first, fall back to latin-1 if that fails
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(file_path, 'r', encoding='latin-1') as f:
                    content = f.read()

            return f"Filename: {filename}\n{content}"

        except FileNotFoundError:
            raise FileNotFoundError(f"Text file not found: {file_path}")
        except Exception as e:
            raise RuntimeError(f"Error reading text file {filename}: {str(e)}")

    def get_page_count(self, filename: str, path: str) -> int:
        """Text files are single-page documents."""
        return 1
