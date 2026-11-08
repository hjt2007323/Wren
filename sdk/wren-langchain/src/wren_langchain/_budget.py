"""UTF-8 byte accounting shared by the LLM-facing content formatters.

Every formatter that writes the ``content`` field of the tool envelope must
honour the same 16 KiB **byte** ceiling, and that ceiling has to count whatever
footer or ``[truncated]`` marker the formatter appends.  Keeping the accounting
in one place is what stops the six formatters from drifting apart; the classic
drift is measuring characters instead of bytes, which lets Chinese or emoji text
blow through the byte budget by 3-4x.

The module intentionally has no dependency on pyarrow or on the rest of the
SDK, so it can be reasoned about and unit-tested on its own.
"""

from __future__ import annotations

from typing import Callable, Sequence

CONTENT_CAP_BYTES = 16 * 1024


def utf8_bytes(text: str) -> int:
    """Return the UTF-8 size of *text* without copying pure-ASCII strings."""
    return len(text) if text.isascii() else len(text.encode("utf-8"))


def truncate_to_bytes(text: str, budget: int) -> str:
    """Return the longest prefix of *text* that encodes to <= *budget* bytes.

    The cut lands on a code-point boundary: slicing the *encoded* bytes and
    decoding with ``errors="ignore"`` drops a partial multibyte sequence instead
    of raising or emitting invalid UTF-8.
    """
    if budget <= 0:
        return ""
    if utf8_bytes(text) <= budget:
        return text
    return text.encode("utf-8")[:budget].decode("utf-8", "ignore")


def fit_text(
    text: str, *, suffix: str = "", cap: int = CONTENT_CAP_BYTES
) -> tuple[str, bool]:
    """Fit *text* plus *suffix* into *cap* UTF-8 bytes.

    Returns ``(fitted, truncated)``.  The suffix is reserved before slicing, so
    ``utf8_bytes(fitted) <= cap`` holds even when the suffix itself is large.
    """
    if utf8_bytes(text) <= cap:
        return text, False
    suffix = truncate_to_bytes(suffix, cap)
    budget = cap - utf8_bytes(suffix)
    return truncate_to_bytes(text, budget) + suffix, True


def fit_blocks(
    blocks: Sequence[str],
    *,
    separator: str,
    cap: int,
    footer: Callable[[int, int], str],
    head: str = "",
) -> tuple[str, int, bool]:
    """Join the longest prefix of *blocks* that fits in *cap* bytes.

    ``head`` is an optional always-included prefix (e.g. a table header), and
    ``footer(shown, total)`` produces the counted marker appended when the list
    is cut.  Only whole blocks are kept — a truncated list never ends with half a
    row, line or item.

    Returns ``(text, shown, truncated)``.  When even the first block cannot fit,
    ``shown`` is ``0`` and the first block is byte-truncated so the caller still
    returns an honest, capped hint instead of nothing.
    """
    total = len(blocks)
    lead = head + separator if head else ""
    used = utf8_bytes(lead)
    sep_bytes = utf8_bytes(separator)
    shown = 0

    for index, block in enumerate(blocks):
        extra = utf8_bytes(block) + (sep_bytes if index else 0)
        if index == total - 1:
            # Last block: if everything fits, do not reserve room for a footer
            # that would never be emitted.
            if used + extra <= cap:
                used += extra
                shown = total
            break
        candidate = footer(index + 1, total)
        if used + extra + utf8_bytes(candidate) <= cap:
            used += extra
            shown = index + 1
        else:
            break

    if shown == total:
        return lead + separator.join(blocks), total, False

    tail = footer(shown, total)
    if shown == 0:
        # Keep the always-included head (e.g. a table header); only the first
        # block is byte-cut, and the footer says why.
        budget = cap - utf8_bytes(tail) - utf8_bytes(lead)
        return lead + truncate_to_bytes(blocks[0], max(0, budget)) + tail, 0, True
    return lead + separator.join(blocks[:shown]) + tail, shown, True
