# SPDX-License-Identifier: Apache-2.0
"""UI hierarchy parsing and element selectors.

Turns the XML produced by ``uiautomator dump`` into nodes with usable bounds,
so gestures can aim at an element instead of a hard-coded coordinate.

Selector syntax (first match wins, in the order the caller asks for them):

    tap --id com.example:id/login      resource-id, exact
    tap --text 登录                     visible text, exact
    tap --desc 返回                     content-desc, exact
    tap --text~ 登录                    visible text, contains
    tap --class android.widget.Button   class name, contains

A bare string is treated as ``--text~`` (contains), which is what people mean
when they type an element's label.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable

_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


@dataclass
class Node:
    rid: str
    text: str
    desc: str
    cls: str
    bounds: tuple[int, int, int, int]
    clickable: bool
    enabled: bool
    visible: bool

    @property
    def width(self) -> int:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[1]

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2

    def label(self) -> str:
        return self.text or self.desc or self.rid or self.cls


def parse(xml_text: str) -> list[Node]:
    """Parse a uiautomator dump into nodes, keeping only laid-out elements."""
    if not xml_text or "<hierarchy" not in xml_text:
        return []
    # uiautomator sometimes emits a stray header line before the XML.
    start = xml_text.find("<hierarchy")
    try:
        root = ET.fromstring(xml_text[start:])
    except ET.ParseError:
        return []

    out: list[Node] = []
    for el in root.iter("node"):
        b = _BOUNDS.match(el.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = (int(g) for g in b.groups())
        out.append(Node(
            rid=el.get("resource-id", ""),
            text=el.get("text", ""),
            desc=el.get("content-desc", ""),
            cls=el.get("class", ""),
            bounds=(x1, y1, x2, y2),
            clickable=el.get("clickable") == "true",
            enabled=el.get("enabled") != "false",
            visible=el.get("visible-to-user") != "false",
        ))
    return out


def find(nodes: Iterable[Node], *, rid: str = "", text: str = "", desc: str = "",
         cls: str = "", contains: bool = False) -> list[Node]:
    """Return nodes matching every selector that was given (AND semantics)."""
    def hit(value: str, want: str) -> bool:
        if not want:
            return True
        return want in value if contains else value == want

    matches = [n for n in nodes
               if hit(n.rid, rid) and hit(n.text, text)
               and hit(n.desc, desc) and hit(n.cls, cls)]
    # Prefer what a user would call "the" element: on screen, enabled, biggest.
    return sorted(matches, key=lambda n: (not n.visible, not n.enabled, -n.area))


def resolve(nodes: Iterable[Node], expr: str) -> list[Node]:
    """Resolve a compact selector expression (``id:``/``text:``/``desc:``/``text~:``)."""
    if not expr:
        return []
    for prefix, kw in (("id:", "rid"), ("text:", "text"), ("desc:", "desc"),
                       ("class:", "cls"), ("text~:", "text")):
        if expr.startswith(prefix):
            value = expr[len(prefix):]
            return find(nodes, contains=prefix == "text~:", **{kw: value})
    return find(nodes, text=expr, contains=True)


def describe(nodes: Iterable[Node], limit: int = 25) -> str:
    """Human-readable listing, for ``droidkit touch ui``."""
    lines = []
    for n in list(nodes)[:limit]:
        if not (n.text or n.desc or n.rid):
            continue
        x, y = n.center
        tag = "click" if n.clickable else "     "
        lines.append(f"{tag} ({x:4d},{y:4d}) {n.width:4d}x{n.height:<4d} {n.label()[:60]}")
    return "\n".join(lines) if lines else "(no labelled elements)"
