"""The document model shared by every reader and by the keystroke planner."""

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------

SOFT_BREAK = "\x0b"  # line break inside a paragraph (Shift+Enter)


@dataclass
class Paragraph:
    runs: list = field(default_factory=list)  # [(text, frozenset of 'b','i','u','s','sup','sub')]
    heading: int = 0  # 0 = normal text, 1-6 = heading level
    list: str = None  # None, 'bullet' or 'numbered'
    level: int = 0  # list nesting level, 0-based
    align: str = "left"  # left, center, right, justify

    @property
    def text(self):
        return "".join(t for t, _ in self.runs)


NOFMT = frozenset()


def add_run(para, text, fmt):
    if not text:
        return
    if para.runs and para.runs[-1][1] == fmt:
        para.runs[-1] = (para.runs[-1][0] + text, fmt)
    else:
        para.runs.append((text, fmt))


def doc_from_plain(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [Paragraph(runs=[(line, NOFMT)] if line else []) for line in text.split("\n")]


class Unreadable(Exception):
    pass
