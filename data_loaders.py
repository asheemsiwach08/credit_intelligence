import os
import json
import PyPDF2
import logging
from pathlib import Path
from typing import Optional


# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def load_json(file_path: str) -> str:
    """Load and validate JSON data from a file."""
    if not file_path.lower().endswith('.json'):
        raise ValueError("Provided file is not a JSON file.")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, (dict, list)):
                raise ValueError("Invalid JSON format: Must be dict or list.")
            logging.info("JSON data loaded successfully.")
            return str(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to read JSON file: {e}")


def extract_text_from_pdf(file_path: str, password: str = "") -> str:
    """Extract text from a PDF file with validation and error handling."""
    if not file_path.lower().endswith('.pdf'):
        raise ValueError("Provided file is not a PDF.")

    try:
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            if reader.is_encrypted:
                logging.info("PDF is encrypted. Attempting decryption.")
                if not reader.decrypt(password):
                    raise PermissionError("Incorrect password or failed to decrypt PDF.")

            if not reader.pages:
                raise ValueError("PDF file is empty or unreadable.")

            text = ''
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text() or ''
                logging.info(f"Extracted text from page {page_num + 1}")
                text += page_text
            return text.strip()
    except Exception as e:
        raise RuntimeError(f"Failed to extract text from PDF: {e}")



def load_data(file_path: str | Path, password: Optional[str] = None) -> str:
    """
    Load data from a .json or .pdf file.

    Args:
        file_path: Path to a JSON or PDF file.
        password : Password for encrypted PDFs (ignored for JSON).

    Returns:
        The file contents as a string.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path.resolve()}")
    if not os.access(path, os.R_OK):
        raise PermissionError(f"File is not readable: {path.resolve()}")

    ext = path.suffix.lower()
    if ext == ".json":
        if password:
            raise ValueError("Password argument is only valid for PDF input.")
        return load_json(str(path))

    if ext == ".pdf":
        if password is None:
            raise ValueError("Encrypted PDF requires a password.")
        return extract_text_from_pdf(str(path), password=password)

    raise ValueError(
        f"Unsupported file type '{ext}'. Only '.json' and '.pdf' are accepted."
    )
