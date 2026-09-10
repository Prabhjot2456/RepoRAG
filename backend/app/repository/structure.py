"""
Repository file-tree builder.
Produces a hierarchical FileNode structure suitable for the API and frontend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from app.ingestion.parser import detect_language
from app.models.schemas import FileNode


def build_file_tree(
    included_paths: List[Path],
    repo_root: Path,
) -> List[FileNode]:
    """
    Build a nested FileNode tree from a flat list of included file paths.
    Returns top-level nodes.
    """
    root_node: Dict = {"children": {}, "type": "directory", "name": "", "path": ""}

    for file_path in included_paths:
        try:
            rel = file_path.relative_to(repo_root)
        except ValueError:
            continue

        parts = list(rel.parts)
        current = root_node

        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                # It's a file
                size = None
                try:
                    size = file_path.stat().st_size
                except OSError:
                    pass
                rel_str = "/".join(parts[:i+1])
                current["children"][part] = {
                    "name": part,
                    "path": rel_str,
                    "type": "file",
                    "size": size,
                    "language": detect_language(file_path),
                    "children": None,
                }
            else:
                if part not in current["children"]:
                    current["children"][part] = {
                        "name": part,
                        "path": "/".join(parts[:i+1]),
                        "type": "directory",
                        "children": {},
                    }
                current = current["children"][part]

    def _to_nodes(node_dict: Dict) -> List[FileNode]:
        nodes = []
        for name, info in sorted(node_dict.items(), key=lambda x: (x[1]["type"] == "file", x[0])):
            if info["type"] == "directory":
                children = _to_nodes(info.get("children") or {})
                nodes.append(FileNode(
                    name=info["name"],
                    path=info["path"],
                    type="directory",
                    children=children,
                ))
            else:
                nodes.append(FileNode(
                    name=info["name"],
                    path=info["path"],
                    type="file",
                    size=info.get("size"),
                    language=info.get("language"),
                ))
        return nodes

    return _to_nodes(root_node["children"])
