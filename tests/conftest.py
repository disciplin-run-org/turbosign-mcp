"""Shared fixtures.

PDFs are built in code rather than committed as binaries: this is a public
repo, generated fixtures cannot accidentally carry someone's real name or
address, and a text-based fixture is reviewable in a diff.
"""

from __future__ import annotations

import pytest

from turbosign_mcp.config import Settings


def make_pdf(
    text: str = "",
    pages: int = 1,
    width: float = 612,
    height: float = 792,
) -> bytes:
    """Build a minimal but valid PDF containing ``text`` on every page.

    Hand-assembled so the byte offsets in the xref table are exact — pypdf is
    strict enough that a sloppy fixture would fail for the wrong reason.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)  # 1-based object number
    # end def

    font_num = None
    page_nums: list[int] = []
    content_nums: list[int] = []

    # Reserve 1 = catalog, 2 = pages tree; fill them in at the end.
    objects.append(b"")  # 1 catalog
    objects.append(b"")  # 2 pages

    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    font_num = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for _ in range(pages):
        lines = []
        y = height - 72
        for line in (escaped.split("\n") if escaped else []):
            lines.append(f"BT /F1 12 Tf 72 {y:.0f} Td ({line}) Tj ET".encode())
            y -= 16
        # end for
        stream = b"\n".join(lines) or b" "
        content_num = add(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
        content_nums.append(content_num)
        page_num = add(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            + f"{width:.0f} {height:.0f}".encode()
            + b"] /Contents "
            + str(content_num).encode()
            + b" 0 R /Resources << /Font << /F1 "
            + str(font_num).encode()
            + b" 0 R >> >> >>"
        )
        page_nums.append(page_num)
    # end for

    kids = b" ".join(f"{n} 0 R".encode() for n in page_nums)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (
        b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(pages).encode() + b" >>"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    # end for

    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    # end for
    out += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_at).encode()
        + b"\n%%EOF\n"
    )
    return bytes(out)
# end def


@pytest.fixture
def plain_pdf() -> bytes:
    """A PDF with body text but no anchor tokens."""
    return make_pdf("Mutual Non-Disclosure Agreement\nDated 1 August 2026")
# end def


@pytest.fixture
def anchored_pdf() -> bytes:
    """A PDF carrying anchor tokens for two signers."""
    return make_pdf(
        "Agreement\nSigned: {Signature1}  Date: {Date1}\n"
        "Counter-signed: {Signature2}"
    )
# end def


@pytest.fixture
def two_recipients() -> list[dict]:
    """A parsed recipient list, parallel signing."""
    return [
        {"name": "Bob Smith", "email": "bob@example.com", "signingOrder": 1},
        {"name": "Ann Jones", "email": "ann@example.com", "signingOrder": 1},
    ]
# end def


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Fully configured settings pointing at a throwaway sandbox."""
    return Settings(
        api_key="test-key",
        org_id="test-org",
        sender_email="sender@example.com",
        sender_name="Test Sender",
        base_url="https://api.turbodocx.test",
        sources={"api_key": "env"},
        allowed_dirs=(tmp_path.resolve(),),
        max_file_bytes=10 * 1024 * 1024,
        timeout=5.0,
    )
# end def


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point the credential store at a temp dir and clear every TURBO* var."""
    for name in list(__import__("os").environ):
        if name.startswith(("TURBODOCX_", "TURBOSIGN_")):
            monkeypatch.delenv(name, raising=False)
        # end if
    # end for
    monkeypatch.setenv("TURBOSIGN_HOME", str(tmp_path / "home"))
    return tmp_path / "home"
# end def
