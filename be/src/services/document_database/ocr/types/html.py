from pathlib import Path

from html_to_markdown import convert, ConversionOptions

from src.services.document_database.ocr.doc_router import ProcessDecision
from src.services.document_database.ocr.types.interface import FileReader


class HtmlReader(FileReader):

    async def read(
        self,
        filename: str,
        path: str,
        fate: ProcessDecision
    ) -> str:
        """
        Reads HTML files and converts them to markdown format.

        Args:
            filename: The name of the file
            path: The path to the file
            fate: Processing decision (ignored for HTML files)

        Returns:
            The markdown-converted content with filename header
        """
        if fate == ProcessDecision.OCR:
            # HTML files don't require OCR
            raise ValueError("OCR is not applicable for HTML files")

        file_path = Path(path)
        if not file_path.is_file():
            file_path = Path(path) / filename

        try:
            # Read the HTML content
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()
            except UnicodeDecodeError:
                with open(file_path, 'r', encoding='latin-1') as f:
                    html_content = f.read()

            # Convert HTML to markdown using the new API
            options = ConversionOptions()
            markdown_content = convert(html_content, options)

            return f"Filename: {filename}\n{markdown_content}"

        except FileNotFoundError:
            raise FileNotFoundError(f"HTML file not found: {file_path}")
        except Exception as e:
            raise RuntimeError(f"Error reading HTML file {filename}: {str(e)}")

    def get_page_count(self, filename: str, path: str) -> int:
        """HTML files are single-page documents."""
        _, _ = filename, path
        return 1
