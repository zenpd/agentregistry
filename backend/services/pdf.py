"""A small PDF writer for the registry's reports (scorecards, evidence packs):
headings, wrapped text, simple tables and page numbers, in Helvetica on A4.
No dependency: the file is built by hand following the PDF 1.4 format."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

PAGE_W, PAGE_H = 595, 842          # A4 in points
MARGIN = 50
LINE = 1.35                        # line height as a multiple of the font size


def _latin1(text: str) -> str:
    """Helvetica here uses WinAnsi: replace what it cannot show."""
    swaps = {"→": "->", "←": "<-", "–": "-", "—": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...", "·": "-",
             "≥": ">=", "≤": "<=", "×": "x", "✓": "v"}
    out = "".join(swaps.get(ch, ch) for ch in str(text))
    return out.encode("latin-1", "replace").decode("latin-1")


def _escape(text: str) -> str:
    return _latin1(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _width(text: str, size: float, bold: bool = False) -> float:
    """Approximate Helvetica width: narrow and wide letters averaged."""
    w = 0.0
    for ch in text:
        if ch in "il.,:;'|!I ":
            w += 0.28
        elif ch in "mwMW@%":
            w += 0.85
        elif ch.isupper() or ch.isdigit():
            w += 0.64
        else:
            w += 0.52
    return w * size * (1.06 if bold else 1.0)


def wrap(text: str, size: float, width: float, bold: bool = False) -> list[str]:
    lines: list[str] = []
    for para in _latin1(text).split("\n"):
        words, cur = para.split(" "), ""
        for word in words:
            trial = f"{cur} {word}".strip()
            if _width(trial, size, bold) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


class Doc:
    def __init__(self, title: str):
        self.title = title
        self.pages: list[list[str]] = [[]]
        self.y = PAGE_H - MARGIN

    # ── layout ────────────────────────────────────────────────────────────
    def _need(self, height: float) -> None:
        if self.y - height < MARGIN + 20:
            self.pages.append([])
            self.y = PAGE_H - MARGIN

    def _put(self, x: float, text: str, size: float, bold: bool = False, grey: bool = False) -> None:
        font = "/F2" if bold else "/F1"
        colour = "0.4 0.4 0.4 rg " if grey else "0 0 0 rg "
        self.pages[-1].append(f"BT {colour}{font} {size} Tf {x:.1f} {self.y:.1f} Td ({_escape(text)}) Tj ET")

    def heading(self, text: str, size: float = 16) -> None:
        self._need(size * 2.2)
        self.y -= size * 0.6
        for line in wrap(text, size, PAGE_W - 2 * MARGIN, bold=True):
            self.y -= size * LINE
            self._put(MARGIN, line, size, bold=True)
        self.y -= size * 0.3

    def text(self, text: str, size: float = 10, bold: bool = False, grey: bool = False) -> None:
        for line in wrap(text, size, PAGE_W - 2 * MARGIN, bold):
            self._need(size * LINE)
            self.y -= size * LINE
            self._put(MARGIN, line, size, bold, grey)
        self.y -= size * 0.4

    def rule(self) -> None:
        self._need(10)
        self.y -= 6
        self.pages[-1].append(f"0.8 0.8 0.8 RG 0.5 w {MARGIN} {self.y:.1f} m {PAGE_W - MARGIN} {self.y:.1f} l S")
        self.y -= 4

    def table(self, headers: list[str], rows: list[list[str]], widths: list[float], size: float = 9) -> None:
        """widths are shares of the text width; cells wrap within their column."""
        total = PAGE_W - 2 * MARGIN
        cols = [w / sum(widths) * total for w in widths]

        def draw(cells: list[str], bold: bool) -> None:
            wrapped = [wrap(str(c), size, cols[i] - 6, bold) for i, c in enumerate(cells)]
            height = max(len(w) for w in wrapped) * size * LINE + 3
            self._need(height)
            top = self.y
            for i, lines in enumerate(wrapped):
                x = MARGIN + sum(cols[:i])
                self.y = top
                for line in lines:
                    self.y -= size * LINE
                    self._put(x, line, size, bold)
            self.y = top - height
            self.pages[-1].append(f"0.88 0.88 0.88 RG 0.4 w {MARGIN} {self.y + 1:.1f} m {PAGE_W - MARGIN} {self.y + 1:.1f} l S")

        draw(headers, True)
        for r in rows:
            draw(r, False)
        self.y -= 6

    # ── output ────────────────────────────────────────────────────────────
    def bytes(self) -> bytes:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        objects: list[bytes] = []

        def add(body: str | bytes) -> int:
            objects.append(body.encode("latin-1") if isinstance(body, str) else body)
            return len(objects)

        catalog = add("")          # filled once the page tree number is known
        pages_obj = add("")
        f1 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        kids = []
        n = len(self.pages)
        for i, ops in enumerate(self.pages, start=1):
            footer = (f"BT 0.4 0.4 0.4 rg /F1 8 Tf {MARGIN} 28 Td ({_escape(self.title)} - generated {stamp} - page {i} of {n}) Tj ET")
            stream = "\n".join(ops + [footer]).encode("latin-1")
            content = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
            kids.append(add(f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                            f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> /Contents {content} 0 R >>"))
        objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
        objects[pages_obj - 1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {n} >>".encode()
        info = add(f"<< /Title ({_escape(self.title)}) /Producer (Agent Registry) >>")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode()
        out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
