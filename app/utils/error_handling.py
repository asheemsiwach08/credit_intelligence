class PDFReadError(Exception):
    """Raised when a PDF file can't be read or decrypted."""
    pass

class BadURLError(Exception):
    """Raised when a source URL is invalid or unreachable."""
    pass

class OpenAITimeout(Exception):
    """Raised when OpenAI API times out or fails."""
    pass

class ValidationError(Exception):
    """Raised when required user fields are missing or invalid."""
    pass

class DataPersisterError(Exception):
    """Raised when saving to the database fails."""
    pass
