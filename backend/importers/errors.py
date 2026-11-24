"""Errors raised by the importers."""


class ImporterError(Exception):
    """A download or parse failed; the last good copy stays in place."""


class MissingContactInfoError(ImporterError):
    """No project URL configured: data hosts must not be contacted."""
