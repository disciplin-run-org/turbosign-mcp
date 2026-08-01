"""Document path guards."""

from __future__ import annotations

import pytest

from turbosign_mcp.errors import TurboSignError
from turbosign_mcp.files import resolve_document, resolve_output_path

from .conftest import make_pdf


def _write(tmp_path, name="contract.pdf", content=None):
    path = tmp_path / name
    path.write_bytes(content if content is not None else make_pdf("hello"))
    return path
# end def


def test_a_normal_pdf_resolves(tmp_path, settings):
    path = _write(tmp_path)
    assert resolve_document(str(path), settings) == path.resolve()
# end def


def test_a_relative_path_is_expanded(tmp_path, settings, monkeypatch):
    _write(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert resolve_document("contract.pdf", settings).name == "contract.pdf"
# end def


def test_a_missing_file_says_so(tmp_path, settings):
    with pytest.raises(TurboSignError, match="No file at"):
        resolve_document(str(tmp_path / "nope.pdf"), settings)
    # end with
# end def


def test_a_directory_is_not_a_document(tmp_path, settings):
    with pytest.raises(TurboSignError, match="is a directory"):
        resolve_document(str(tmp_path), settings)
    # end with
# end def


def test_a_path_outside_the_allowed_roots_is_refused(tmp_path, settings):
    # The guard that stops an agent being talked into mailing out /etc/passwd.
    with pytest.raises(TurboSignError, match="outside the directories"):
        resolve_document("/etc/hostname", settings)
    # end with
# end def


def test_an_unsupported_extension_lists_what_is_supported(tmp_path, settings):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    with pytest.raises(TurboSignError) as excinfo:
        resolve_document(str(path), settings)
    # end with
    assert ".pdf" in excinfo.value.hint
# end def


def test_an_empty_file_is_refused(tmp_path, settings):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    with pytest.raises(TurboSignError, match="is empty"):
        resolve_document(str(path), settings)
    # end with
# end def


def test_an_oversized_file_names_the_cap(tmp_path, settings):
    from dataclasses import replace

    path = _write(tmp_path, content=b"%PDF-1.4\n" + b"x" * 4096)
    small = replace(settings, max_file_bytes=1024)
    with pytest.raises(TurboSignError) as excinfo:
        resolve_document(str(path), small)
    # end with
    assert "TURBOSIGN_MAX_FILE_MB" in excinfo.value.hint
# end def


def test_an_empty_path_asks_for_one(settings):
    with pytest.raises(TurboSignError, match="No document path"):
        resolve_document("   ", settings)
    # end with
# end def


# -- output paths ----------------------------------------------------------


def test_an_output_path_in_an_existing_directory_resolves(tmp_path, settings):
    out = resolve_output_path(str(tmp_path / "signed.pdf"), settings)
    assert out.name == "signed.pdf"
# end def


def test_an_output_path_in_a_missing_directory_is_refused(tmp_path, settings):
    with pytest.raises(TurboSignError, match="does not exist"):
        resolve_output_path(str(tmp_path / "nope" / "signed.pdf"), settings)
    # end with
# end def


def test_an_output_path_outside_the_allowed_roots_is_refused(settings):
    with pytest.raises(TurboSignError, match="outside the directories"):
        resolve_output_path("/etc/signed.pdf", settings)
    # end with
# end def
