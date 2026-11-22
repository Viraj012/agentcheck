"""Split a page's markdown-ish text into retrieval chunks along its heading structure."""

import re
from dataclasses import dataclass

from app.config import Settings

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
PATH_SEPARATOR = " > "


@dataclass(frozen=True)
class Chunk:
    heading_path: str
    text: str


@dataclass(frozen=True)
class _Piece:
    path: tuple[str, ...]
    text: str


def estimate_tokens(text: str) -> int:
    """Rough token count (about 4 characters per token for English). Good enough for sizing."""
    return (len(text) + 3) // 4


def chunk_page(text: str, settings: Settings) -> list[Chunk]:
    pieces: list[_Piece] = []
    for section in _sections(text):
        if estimate_tokens(section.text) <= settings.chunk_max_tokens:
            pieces.append(section)
        else:
            pieces += [
                _Piece(section.path, part)
                for part in _split_oversized(
                    section.text, settings.chunk_max_tokens, settings.chunk_overlap_tokens
                )
            ]
    packed = _pack(pieces, settings.chunk_target_tokens)
    merged = _merge_small(packed, settings.chunk_min_tokens, settings.chunk_max_tokens)
    return [Chunk(PATH_SEPARATOR.join(_common_path(group)), _join(group)) for group in merged]


def _sections(text: str) -> list[_Piece]:
    sections: list[_Piece] = []
    stack: list[tuple[int, str]] = []
    lines: list[str] = []

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body:
            sections.append(_Piece(tuple(title for _, title in stack), body))

    def only_headings() -> bool:
        return all(HEADING.match(line.strip()) or not line.strip() for line in lines)

    for line in text.splitlines():
        match = HEADING.match(line.strip())
        if match:
            if not only_headings():
                flush()
                lines = []
            level = len(match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match.group(2)))
        lines.append(line)
    flush()
    return sections


def _split_oversized(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    budget = max_tokens - overlap_tokens
    units: list[str] = []
    for paragraph in (p.strip() for p in text.split("\n\n")):
        if not paragraph:
            continue
        units += (
            [paragraph] if estimate_tokens(paragraph) <= budget else _windows(paragraph, budget)
        )
    parts: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if current and estimate_tokens(candidate) > max_tokens:
            parts.append(current)
            current = f"{_tail(current, overlap_tokens)} {unit}".strip()
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _windows(paragraph: str, budget: int) -> list[str]:
    windows: list[str] = []
    current: list[str] = []
    for word in paragraph.split():
        if current and estimate_tokens(" ".join([*current, word])) > budget:
            windows.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        windows.append(" ".join(current))
    return windows


def _tail(text: str, overlap_tokens: int) -> str:
    tail: list[str] = []
    for word in reversed(text.split()):
        if estimate_tokens(" ".join([word, *tail])) > overlap_tokens:
            break
        tail.insert(0, word)
    return " ".join(tail)


def _pack(pieces: list[_Piece], target_tokens: int) -> list[list[_Piece]]:
    groups: list[list[_Piece]] = []
    for piece in pieces:
        if groups and estimate_tokens(_join([*groups[-1], piece])) <= target_tokens:
            groups[-1].append(piece)
        else:
            groups.append([piece])
    return groups


def _merge_small(
    groups: list[list[_Piece]], min_tokens: int, max_tokens: int
) -> list[list[_Piece]]:
    merged: list[list[_Piece]] = []
    for group in groups:
        if (
            merged
            and estimate_tokens(_join(group)) < min_tokens
            and estimate_tokens(_join([*merged[-1], *group])) <= max_tokens
        ):
            merged[-1] = [*merged[-1], *group]
        else:
            merged.append(group)
    return merged


def _common_path(group: list[_Piece]) -> tuple[str, ...]:
    common = group[0].path
    for piece in group[1:]:
        length = 0
        while length < min(len(common), len(piece.path)) and common[length] == piece.path[length]:
            length += 1
        common = common[:length]
    return common


def _join(group: list[_Piece]) -> str:
    return "\n\n".join(piece.text for piece in group)
