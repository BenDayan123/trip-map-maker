"""Shared exception types."""


class PipelineError(Exception):
    """User-facing pipeline failure (bad file, API error, no locations, ...).

    Raised instead of exiting so callers (CLI, GUI) can present the message
    themselves rather than the process dying.
    """
