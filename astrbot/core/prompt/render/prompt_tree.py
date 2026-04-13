"""Prompt tree nodes and builder helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


def _tag_name(tag: Any) -> str:
    return tag.value if hasattr(tag, "value") else str(tag)


@dataclass
class PromptNode:
    """A single node in the prompt tree."""

    text: str = ""
    priority: int = 0
    children: list[PromptNode] = field(default_factory=list)
    parent: PromptNode | None = None
    enabled: bool = True
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def depth(self) -> int:
        if self.parent is None:
            return 0
        return self.parent.depth + 1

    def add_child(self, node: PromptNode) -> PromptNode:
        node.parent = self
        self.children.append(node)
        return node

    def clone(self) -> PromptNode:
        new_node = PromptNode(
            text=self.text,
            priority=self.priority,
            enabled=self.enabled,
            meta=dict(self.meta),
        )
        for child in self.children:
            new_node.add_child(child.clone())
        return new_node


@dataclass
class NodeRef:
    """A chainable handle for operating on a prompt node."""

    builder: PromptBuilder
    node: PromptNode

    def add(
        self,
        text: str,
        *,
        priority: int = 0,
        enabled: bool = True,
        meta: dict[str, Any] | None = None,
    ) -> NodeRef:
        child = self.builder._add_text(
            text,
            parent=self.node,
            priority=priority,
            enabled=enabled,
            meta=meta,
        )
        return NodeRef(self.builder, child)

    def tag(
        self,
        tag: Any,
        *,
        priority: int = 0,
        enabled: bool = True,
        meta: dict[str, Any] | None = None,
    ) -> NodeRef:
        return self.builder._create_tag(
            tag,
            parent=self.node,
            priority=priority,
            enabled=enabled,
            meta=meta,
        )

    def container(
        self,
        *,
        priority: int = 0,
        enabled: bool = True,
        meta: dict[str, Any] | None = None,
    ) -> NodeRef:
        return self.builder._create_container(
            parent=self.node,
            priority=priority,
            enabled=enabled,
            meta=meta,
        )

    def include(self, item: Any, *, clone: bool = True) -> NodeRef:
        self.builder._include_into_parent(item, parent=self.node, clone=clone)
        return self

    def extend(self, item: Any, *, clone: bool = True) -> NodeRef:
        self.builder._extend_as_sibling(item, sibling_of=self.node, clone=clone)
        return self


class PromptBuilder:
    """Build and render a prompt tree."""

    def __init__(
        self,
        root_tag: Any | None = None,
        *,
        indent_size: int = 2,
        newline: str = "\n",
    ) -> None:
        self.indent_size = indent_size
        self.newline = newline
        self.roots: list[PromptNode] = []
        self._seq = 0

        if root_tag is None:
            self._root_node = PromptNode(
                text="",
                meta={"kind": "container_root", "_seq": self._next_seq()},
            )
            self._has_explicit_root_tag = False
        else:
            name = _tag_name(root_tag)
            self._root_node = PromptNode(
                text=f"<{name}>",
                meta={"kind": "tag_start", "tag": name, "_seq": self._next_seq()},
            )
            self._root_node.add_child(
                PromptNode(
                    text=f"</{name}>",
                    priority=-(10**9),
                    meta={"kind": "tag_end", "tag": name, "_seq": self._next_seq()},
                )
            )
            self._has_explicit_root_tag = True
            self.roots.append(self._root_node)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def ref(self) -> NodeRef:
        return NodeRef(self, self._root_node)

    def add(
        self,
        text: str,
        *,
        priority: int = 0,
        enabled: bool = True,
        meta: dict[str, Any] | None = None,
    ) -> NodeRef:
        return self.ref().add(text, priority=priority, enabled=enabled, meta=meta)

    def tag(
        self,
        tag: Any,
        *,
        priority: int = 0,
        enabled: bool = True,
        meta: dict[str, Any] | None = None,
    ) -> NodeRef:
        return self.ref().tag(tag, priority=priority, enabled=enabled, meta=meta)

    def container(
        self,
        *,
        priority: int = 0,
        enabled: bool = True,
        meta: dict[str, Any] | None = None,
    ) -> NodeRef:
        return self.ref().container(priority=priority, enabled=enabled, meta=meta)

    def include(self, item: Any, *, clone: bool = True) -> PromptBuilder:
        self.ref().include(item, clone=clone)
        return self

    def extend(self, item: Any, *, clone: bool = True) -> PromptBuilder:
        if self._has_explicit_root_tag:
            self._extend_as_sibling(item, sibling_of=self._root_node, clone=clone)
        else:
            self._extend_to_roots(item, clone=clone)
        return self

    def _add_text(
        self,
        text: str,
        *,
        parent: PromptNode,
        priority: int,
        enabled: bool,
        meta: dict[str, Any] | None,
    ) -> PromptNode:
        node = PromptNode(
            text=text,
            priority=priority,
            enabled=enabled,
            meta={**(meta or {}), "_seq": (meta or {}).get("_seq") or self._next_seq()},
        )
        parent.add_child(node)
        return node

    def _create_container(
        self,
        *,
        parent: PromptNode,
        priority: int,
        enabled: bool,
        meta: dict[str, Any] | None,
    ) -> NodeRef:
        node = PromptNode(
            text="",
            priority=priority,
            enabled=enabled,
            meta={
                **(meta or {}),
                "kind": "container",
                "_seq": (meta or {}).get("_seq") or self._next_seq(),
            },
        )
        parent.add_child(node)
        return NodeRef(self, node)

    def _create_tag(
        self,
        tag: Any,
        *,
        parent: PromptNode,
        priority: int,
        enabled: bool,
        meta: dict[str, Any] | None,
    ) -> NodeRef:
        name = _tag_name(tag)
        start = PromptNode(
            text=f"<{name}>",
            priority=priority,
            enabled=enabled,
            meta={
                **(meta or {}),
                "kind": "tag_start",
                "tag": name,
                "_seq": (meta or {}).get("_seq") or self._next_seq(),
            },
        )
        parent.add_child(start)
        start.add_child(
            PromptNode(
                text=f"</{name}>",
                priority=-(10**9),
                enabled=enabled,
                meta={
                    **(meta or {}),
                    "kind": "tag_end",
                    "tag": name,
                    "_seq": self._next_seq(),
                },
            )
        )
        return NodeRef(self, start)

    def _iter_item_roots(self, item: Any, *, clone: bool) -> Iterable[PromptNode]:
        if isinstance(item, NodeRef):
            yield item.node.clone() if clone else item.node
            return

        if isinstance(item, PromptNode):
            yield item.clone() if clone else item
            return

        if isinstance(item, PromptBuilder):
            for root in item.roots:
                yield root.clone() if clone else root
            if not item._has_explicit_root_tag:
                for child in item._root_node.children:
                    yield child.clone() if clone else child
            return

        raise TypeError(f"Unsupported item type: {type(item)}")

    def _include_into_parent(
        self,
        item: Any,
        *,
        parent: PromptNode,
        clone: bool,
    ) -> None:
        for node in self._iter_item_roots(item, clone=clone):
            parent.add_child(node)

    def _extend_to_roots(self, item: Any, *, clone: bool) -> None:
        for node in self._iter_item_roots(item, clone=clone):
            node.parent = None
            self.roots.append(node)

    def _extend_as_sibling(
        self,
        item: Any,
        *,
        sibling_of: PromptNode,
        clone: bool,
    ) -> None:
        parent = sibling_of.parent
        if parent is None:
            self._extend_to_roots(item, clone=clone)
            return
        self._include_into_parent(item, parent=parent, clone=clone)

    def build(self) -> str:
        lines: list[str] = []

        if not self._has_explicit_root_tag:
            for child in sorted(self._root_node.children, key=self._sort_key):
                self._render(child, lines)
            for root in sorted(self.roots, key=self._sort_key):
                self._render(root, lines)
        else:
            for root in sorted(self.roots, key=self._sort_key):
                self._render(root, lines)

        while lines and lines[-1] == "":
            lines.pop()

        return self.newline.join(lines)

    def _render(self, node: PromptNode, lines: list[str]) -> None:
        if not node.enabled:
            return

        kind = node.meta.get("kind")
        is_container = kind in {"container", "container_root"}
        indent_depth = node.depth

        if kind == "tag_end":
            indent_depth = node.parent.depth if node.parent is not None else 0

        indent = " " * (indent_depth * self.indent_size)

        if node.text:
            for line in node.text.splitlines():
                lines.append(indent + line)
        elif not is_container:
            lines.append("")

        for child in sorted(node.children, key=self._sort_key):
            self._render(child, lines)

    @staticmethod
    def _sort_key(node: PromptNode) -> tuple[int, int]:
        seq = node.meta.get("_seq")
        if isinstance(seq, int):
            return (-node.priority, seq)
        return (-node.priority, id(node))

    def debug_tree(self) -> str:
        output: list[str] = []
        if not self._has_explicit_root_tag:
            output.append("== container_root children ==")
            for child in sorted(self._root_node.children, key=self._sort_key):
                self._debug_node(child, output, 0)
            output.append("== extra roots ==")
            for root in sorted(self.roots, key=self._sort_key):
                self._debug_node(root, output, 0)
        else:
            output.append("== roots ==")
            for root in sorted(self.roots, key=self._sort_key):
                self._debug_node(root, output, 0)
        return self.newline.join(output)

    def _debug_node(self, node: PromptNode, output: list[str], level: int) -> None:
        disabled = "" if node.enabled else " (disabled)"
        meta = f" meta={node.meta}" if node.meta else ""
        text = node.text.replace("\n", "\\n")
        if len(text) > 120:
            text = text[:117] + "..."
        output.append(
            f"{'  ' * level}- p={node.priority} depth={node.depth}{disabled} "
            f'text="{text}"{meta}'
        )
        for child in sorted(node.children, key=self._sort_key):
            self._debug_node(child, output, level + 1)
