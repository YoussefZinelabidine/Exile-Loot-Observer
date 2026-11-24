"""Errors raised by the normaliser."""


class NormaliserError(Exception):
    """The item cannot be normalised. ``code`` is machine-readable (decision 32)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
