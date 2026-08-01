"""Document path validation.

Every check here fails with a sentence naming the fix, because these are the
errors an agent hits most often — a typo'd path, a file that turned out to be a
Word document, a scan that came out at 40 MB.
"""

from __future__ import annotations

from pathlib import Path

from .config import SUPPORTED_EXTENSIONS, Settings
from .errors import TurboSignError


def _within_allowed(path: Path, allowed: tuple[Path, ...]) -> bool:
    """Whether ``path`` sits under one of the allowed roots."""
    for root in allowed:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
        # end try
    # end for
    return False
# end def


def resolve_document(path_str: str, settings: Settings) -> Path:
    """Validate a document path and return it resolved.

    Checks, in the order that produces the most useful message: the path
    exists and is a file, it sits under an allowed root, its extension is one
    TurboSign accepts, and it is within the size cap.

    Raises:
        TurboSignError: With a hint naming the specific fix.
    """
    if not path_str or not path_str.strip():
        raise TurboSignError(
            "No document path was given.",
            "Pass file_path as an absolute path, for example "
            "/home/you/contracts/nda.pdf",
        )
    # end if

    path = Path(path_str.strip()).expanduser()
    try:
        path = path.resolve()
    except OSError as exc:
        raise TurboSignError(
            f"Could not resolve the path {path_str!r}: {exc}",
            "Check for typos and use an absolute path.",
        ) from exc
    # end try

    if not path.exists():
        raise TurboSignError(
            f"No file at {path}.",
            "Check the path. Use an absolute path — a relative one is "
            "resolved against the server's working directory, not yours.",
        )
    # end if

    if not path.is_file():
        raise TurboSignError(
            f"{path} is a directory, not a document.",
            "Point file_path at a single PDF.",
        )
    # end if

    if not _within_allowed(path, settings.allowed_dirs):
        roots = ", ".join(str(p) for p in settings.allowed_dirs)
        raise TurboSignError(
            f"{path} is outside the directories this server may send from.",
            f"Allowed roots are: {roots}. Move the document under one of "
            "them, or widen TURBOSIGN_ALLOWED_DIRS.",
        )
    # end if

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise TurboSignError(
            f"TurboSign does not accept {suffix or 'extensionless'} files.",
            "Supported types are " + ", ".join(SUPPORTED_EXTENSIONS) + ".",
        )
    # end if

    size = path.stat().st_size
    if size == 0:
        raise TurboSignError(
            f"{path} is empty.",
            "Check the file was written completely before sending it.",
        )
    # end if
    if size > settings.max_file_bytes:
        cap_mb = settings.max_file_bytes / 1024 / 1024
        raise TurboSignError(
            f"{path} is {size / 1024 / 1024:.1f} MB, over the {cap_mb:.0f} MB cap.",
            "Compress the PDF, or raise TURBOSIGN_MAX_FILE_MB if the upload "
            "can afford the extra time.",
        )
    # end if

    return path
# end def


def resolve_output_path(path_str: str, settings: Settings) -> Path:
    """Validate a path to write a downloaded document to.

    The parent directory must already exist and be under an allowed root; this
    tool downloads files, it does not build directory trees.
    """
    if not path_str or not path_str.strip():
        raise TurboSignError(
            "No output path was given.",
            "Pass output_path, for example /home/you/signed/nda-signed.pdf",
        )
    # end if

    path = Path(path_str.strip()).expanduser()
    parent = path.parent.expanduser()
    try:
        parent = parent.resolve()
    except OSError as exc:
        raise TurboSignError(
            f"Could not resolve the output directory for {path_str!r}: {exc}",
            "Use an absolute path.",
        ) from exc
    # end try

    if not parent.is_dir():
        raise TurboSignError(
            f"The directory {parent} does not exist.",
            "Create it first, or choose an existing directory.",
        )
    # end if

    if not _within_allowed(parent, settings.allowed_dirs):
        roots = ", ".join(str(p) for p in settings.allowed_dirs)
        raise TurboSignError(
            f"{parent} is outside the directories this server may write to.",
            f"Allowed roots are: {roots}.",
        )
    # end if

    return parent / path.name
# end def
