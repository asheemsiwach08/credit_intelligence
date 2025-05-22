import io
import os
import json
import boto3
import PyPDF2
import logging
from pathlib import Path
from typing import Optional, Union

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


def read_s3_object(bucket: str, key: str, *, boto3_session: boto3.Session | None = None) -> bytes:
    """
    Download an object from S3 and return its raw bytes.
    A custom boto3 Session can be injected (handy for unit tests or STS creds).
    """
    session = boto3_session or boto3.Session()
    s3 = session.client("s3")
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()
    except s3.exceptions.NoSuchKey as e:
        raise FileNotFoundError(f"s3://{bucket}/{key} not found") from e
    except Exception as e:
        raise RuntimeError(f"Failed to download s3://{bucket}/{key}: {e}") from e


def loads_json_bytes(blob: bytes) -> str:
    """Return *pretty‑printed* JSON string"""
    data = json.loads(blob.decode("utf-8"))
    return json.dumps(data, indent=2, ensure_ascii=False)

# --------------------------------------------------------------------------- #
# 2.  PDF TEXT EXTRACTION (works with bytes OR local file path)
# --------------------------------------------------------------------------- #

def extract_text_from_pdf(source: Union[str, bytes, io.BytesIO], password: str = "") -> str:
    """
    Extract text from a PDF.
    * source can be: local file path, raw bytes, or a BytesIO stream.
    """
    try:
        # Normalise the input into a file‑like object
        if isinstance(source, (bytes, bytearray)):
            file_obj = io.BytesIO(source)
        elif isinstance(source, io.BytesIO):
            file_obj = source
        elif isinstance(source, str):
            if not source.lower().endswith(".pdf"):
                raise ValueError("Provided file is not a PDF.")
            file_obj = open(source, "rb")
        else:
            raise TypeError("Unsupported source type for PDF extraction.")

        with file_obj as fp:
            reader = PyPDF2.PdfReader(fp)
            if reader.is_encrypted:
                logging.info("PDF is encrypted. Attempting decryption.")
                if password is None:
                    raise ValueError("Encrypted PDF requires a password.")
                if not reader.decrypt(password):
                    raise PermissionError("Incorrect password or failed to decrypt PDF.")

            if not reader.pages:
                raise ValueError("PDF file is empty or unreadable.")

            text_parts: list[str] = []
            for idx, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                logging.info("Extracted text from page %s", idx)
                text_parts.append(page_text)

            return "".join(text_parts).strip()
    except Exception as e:
        raise RuntimeError(f"Failed to extract text from PDF: {e}") from e


# --------------------------------------------------------------------------- #
# 3.  PUBLIC APIS
# --------------------------------------------------------------------------- #

def load_data(
    path_or_uri: str | Path,
    *,
    password: Optional[str] = None,
    boto3_session: boto3.Session | None = None,
) -> str:
    """
    Load JSON/PDF data from a local file **or** an s3:// URI.

    Returns the raw JSON string (pretty‑printed) **or** extracted PDF text.
    """
    # ---- S3 URI ----------------------------------------------------------- #
    if str(path_or_uri).startswith("s3://"):
        _, _, bucket, *rest = str(path_or_uri).split("/", 3)
        if not bucket or not rest:
            raise ValueError(f"Malformed S3 URI: {path_or_uri}")
        key = rest[0] if len(rest) == 1 else rest[1]
        return load_data_s3(bucket, key, password=password, boto3_session=boto3_session)

    # ---- Local file ------------------------------------------------------- #
    p = Path(path_or_uri)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {p.resolve()}")
    if not os.access(p, os.R_OK):
        raise PermissionError(f"File is not readable: {p.resolve()}")

    ext = p.suffix.lower()
    if ext == ".json":
        if password:
            raise ValueError("Password argument is only valid for PDF input.")
        return loads_json_bytes(p.read_bytes())

    if ext == ".pdf":
        return extract_text_from_pdf(str(p), password or "")

    raise ValueError(f"Unsupported file type '{ext}'. Only '.json' and '.pdf' are accepted.")


def load_data_s3(
    bucket: str,
    key: str,
    *,
    password: Optional[str] = None,
    boto3_session: boto3.Session | None = None) -> str:
    """
    Load JSON/PDF data from an S3 bucket.

    Returns the raw JSON string, extracted PDF text.
    """
    blob = read_s3_object(bucket, key, boto3_session=boto3_session)
    ext = Path(key).suffix.lower()

    if ext == ".json":
        if password:
            raise ValueError("Password argument is only valid for PDF input.")
        return loads_json_bytes(blob)

    if ext == ".pdf":
        return extract_text_from_pdf(blob, password or "")

    raise ValueError(f"Unsupported S3 object type '{ext}'. Only '.json' and '.pdf' are accepted.")
