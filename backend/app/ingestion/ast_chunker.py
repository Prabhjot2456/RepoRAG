"""
AST-based code chunker using tree-sitter.

Uses tree-sitter to parse source code into an Abstract Syntax Tree (AST),
then extracts complete functions, classes, and methods as atomic chunks.
This ensures that logical code units are never split across chunk boundaries,
dramatically improving RAG retrieval quality.

Supported languages:
  Python, JavaScript, TypeScript, Go, Rust, Java, C, C++

Falls back gracefully to regex-based chunking if tree-sitter
grammars are not installed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.ingestion.parser import ParsedFile
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Default chunk parameters (mirrored from chunker.py)
DEFAULT_CHUNK_SIZE = 1500       # characters
DEFAULT_CHUNK_OVERLAP = 200     # characters


# ── Tree-sitter language loading ───────────────────────────────────────────────

_LANGUAGE_CACHE: Dict[str, Any] = {}
_PARSER_CACHE: Dict[str, Any] = {}

# Mapping from our language names to tree-sitter package names
# and the node types we want to extract
_LANGUAGE_CONFIG: Dict[str, Dict[str, Any]] = {
    "python": {
        "module": "tree_sitter_python",
        "node_types": [
            "function_definition",
            "class_definition",
            "decorated_definition",
        ],
        "name_field": "name",
    },
    "javascript": {
        "module": "tree_sitter_javascript",
        "node_types": [
            "function_declaration",
            "class_declaration",
            "method_definition",
            "arrow_function",
            "lexical_declaration",   # const foo = () => ...
            "variable_declaration",  # var foo = function() ...
            "export_statement",
        ],
        "name_field": "name",
    },
    "typescript": {
        "module": "tree_sitter_typescript",
        "variant": "typescript",
        "node_types": [
            "function_declaration",
            "class_declaration",
            "method_definition",
            "arrow_function",
            "lexical_declaration",
            "variable_declaration",
            "export_statement",
            "interface_declaration",
            "type_alias_declaration",
            "enum_declaration",
        ],
        "name_field": "name",
    },
    "go": {
        "module": "tree_sitter_go",
        "node_types": [
            "function_declaration",
            "method_declaration",
            "type_declaration",
        ],
        "name_field": "name",
    },
    "rust": {
        "module": "tree_sitter_rust",
        "node_types": [
            "function_item",
            "impl_item",
            "struct_item",
            "enum_item",
            "trait_item",
            "mod_item",
        ],
        "name_field": "name",
    },
    "java": {
        "module": "tree_sitter_java",
        "node_types": [
            "class_declaration",
            "method_declaration",
            "constructor_declaration",
            "interface_declaration",
            "enum_declaration",
        ],
        "name_field": "name",
    },
    "c": {
        "module": "tree_sitter_c",
        "node_types": [
            "function_definition",
            "struct_specifier",
            "enum_specifier",
            "union_specifier",
        ],
        "name_field": "declarator",
    },
    "cpp": {
        "module": "tree_sitter_cpp",
        "node_types": [
            "function_definition",
            "class_specifier",
            "struct_specifier",
            "namespace_definition",
            "enum_specifier",
        ],
        "name_field": "declarator",
    },
}


def _get_parser(language: str) -> Optional[Any]:
    """
    Get or create a tree-sitter parser for the given language.
    Returns None if tree-sitter or the language grammar is not installed.
    """
    if language in _PARSER_CACHE:
        return _PARSER_CACHE[language]

    config = _LANGUAGE_CONFIG.get(language)
    if not config:
        return None

    try:
        from tree_sitter import Language, Parser
        import importlib

        module = importlib.import_module(config["module"])

        # Some grammars (like typescript) have variants
        if "variant" in config:
            lang_func = getattr(module, "language_" + config["variant"], None)
            if lang_func is None:
                lang_func = getattr(module, "language", None)
        else:
            lang_func = getattr(module, "language", None)

        if lang_func is None:
            logger.warning("ast_language_func_not_found", language=language, module=config["module"])
            _PARSER_CACHE[language] = None
            return None

        ts_language = Language(lang_func())
        parser = Parser(ts_language)
        _PARSER_CACHE[language] = parser
        _LANGUAGE_CACHE[language] = ts_language

        logger.info("ast_parser_loaded", language=language)
        return parser

    except ImportError as exc:
        logger.debug("ast_import_error", language=language, error=str(exc))
        _PARSER_CACHE[language] = None
        return None
    except Exception as exc:
        logger.warning("ast_parser_error", language=language, error=str(exc))
        _PARSER_CACHE[language] = None
        return None


def is_ast_available(language: str) -> bool:
    """Check if AST parsing is available for the given language."""
    return _get_parser(language) is not None


# ── AST Node extraction ───────────────────────────────────────────────────────

def _extract_node_name(node: Any, language: str) -> str:
    """
    Extract a human-readable name from an AST node.
    Handles language-specific naming conventions.
    """
    config = _LANGUAGE_CONFIG.get(language, {})
    name_field = config.get("name_field", "name")

    # Try direct child by field name
    name_node = node.child_by_field_name(name_field)
    if name_node:
        return name_node.text.decode("utf-8", errors="replace")

    # For decorated definitions (Python), look inside
    if node.type == "decorated_definition":
        for child in node.children:
            if child.type in ("function_definition", "class_definition"):
                inner_name = child.child_by_field_name("name")
                if inner_name:
                    return inner_name.text.decode("utf-8", errors="replace")

    # For export statements, look for the declaration inside
    if node.type == "export_statement":
        for child in node.children:
            child_name = child.child_by_field_name("name")
            if child_name:
                return child_name.text.decode("utf-8", errors="replace")
            # Arrow functions in lexical declarations
            if child.type == "lexical_declaration":
                for decl in child.children:
                    decl_name = decl.child_by_field_name("name")
                    if decl_name:
                        return decl_name.text.decode("utf-8", errors="replace")

    # For variable/lexical declarations (JS arrow functions)
    if node.type in ("lexical_declaration", "variable_declaration"):
        for child in node.children:
            decl_name = child.child_by_field_name("name")
            if decl_name:
                return decl_name.text.decode("utf-8", errors="replace")

    # For C/C++ where 'declarator' may be nested
    if name_field == "declarator":
        declarator = node.child_by_field_name("declarator")
        if declarator:
            # May be a function_declarator wrapping an identifier
            inner = declarator.child_by_field_name("declarator")
            if inner:
                return inner.text.decode("utf-8", errors="replace")
            return declarator.text.decode("utf-8", errors="replace").split("(")[0].strip()

    return "unknown"


def _classify_node_type(node_type: str) -> str:
    """Map AST node type to a simpler chunk_type label."""
    type_mapping = {
        # Functions
        "function_definition": "function",
        "function_declaration": "function",
        "function_item": "function",
        "method_definition": "method",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
        "arrow_function": "function",
        "lexical_declaration": "function",
        "variable_declaration": "function",
        # Classes / Types
        "class_definition": "class",
        "class_declaration": "class",
        "class_specifier": "class",
        "struct_specifier": "struct",
        "struct_item": "struct",
        "interface_declaration": "interface",
        "type_alias_declaration": "type_alias",
        "type_declaration": "type",
        "enum_declaration": "enum",
        "enum_specifier": "enum",
        "enum_item": "enum",
        "union_specifier": "union",
        # Modules / Namespaces
        "impl_item": "impl",
        "trait_item": "trait",
        "mod_item": "module",
        "namespace_definition": "namespace",
        # Exports
        "export_statement": "export",
        # Decorated
        "decorated_definition": "function",
    }
    return type_mapping.get(node_type, "code_block")


def _get_top_level_definitions(
    root_node: Any,
    target_types: List[str],
    source_bytes: bytes,
) -> List[Dict[str, Any]]:
    """
    Walk the AST and collect top-level (and one-level-deep) definitions.
    Returns a list of dicts with node info.
    """
    definitions: List[Dict[str, Any]] = []

    def _walk(node: Any, depth: int = 0):
        # Only go 2 levels deep (module-level and one nesting)
        if depth > 2:
            return

        for child in node.children:
            if child.type in target_types:
                definitions.append({
                    "node": child,
                    "type": child.type,
                    "start_byte": child.start_byte,
                    "end_byte": child.end_byte,
                    "start_line": child.start_point[0],  # 0-indexed
                    "end_line": child.end_point[0],       # 0-indexed
                    "depth": depth,
                })
            else:
                # Recurse into non-target nodes (e.g., module body)
                # but only if they are structural containers
                if child.type in (
                    "module", "program", "translation_unit",
                    "source_file", "statement_block", "block",
                    "declaration_list", "field_declaration_list",
                ):
                    _walk(child, depth)
                elif depth == 0:
                    # At top level, recurse into everything
                    _walk(child, depth + 1)

    _walk(root_node)
    return definitions


# ── Main AST chunking function ─────────────────────────────────────────────────

def chunk_file_with_ast(parsed: ParsedFile) -> Optional[List["Chunk"]]:
    """
    Chunk a file using tree-sitter AST parsing.

    Returns a list of Chunks if successful, or None if AST parsing
    is not available for this language (caller should fall back to regex).
    """
    from app.ingestion.chunker import Chunk

    language = parsed.language
    if not language or language not in _LANGUAGE_CONFIG:
        return None

    parser = _get_parser(language)
    if parser is None:
        return None

    source_bytes = parsed.content.encode("utf-8")

    try:
        tree = parser.parse(source_bytes)
    except Exception as exc:
        logger.warning("ast_parse_failed", path=parsed.relative_path, error=str(exc))
        return None

    root = tree.root_node
    config = _LANGUAGE_CONFIG[language]
    target_types = config["node_types"]

    definitions = _get_top_level_definitions(root, target_types, source_bytes)

    if not definitions:
        # No top-level definitions found — AST parsed OK but file
        # might be pure config/data. Return None to fall back.
        return None

    chunks: List[Chunk] = []
    lines = parsed.content.splitlines(keepends=True)

    # Extract header / imports (everything before the first definition)
    first_def_line = definitions[0]["start_line"]
    if first_def_line > 0:
        header_content = "".join(lines[:first_def_line]).strip()
        if header_content:
            chunks.append(Chunk(
                content=header_content,
                metadata={
                    "file_path": parsed.relative_path,
                    "language": language,
                    "chunk_type": "imports",
                    "start_line": 1,
                    "end_line": first_def_line,
                    "ast_parsed": True,
                },
            ))

    # Process each definition
    for defn in definitions:
        start_line = defn["start_line"]
        end_line = defn["end_line"] + 1  # Make inclusive
        content = "".join(lines[start_line:end_line]).strip()

        if not content:
            continue

        node_type = defn["type"]
        name = _extract_node_name(defn["node"], language)
        chunk_type = _classify_node_type(node_type)

        # If the chunk is very large, split it into sub-chunks
        if len(content) > DEFAULT_CHUNK_SIZE * 2:
            sub_chunks = _split_ast_chunk(content, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP)
            for j, sc in enumerate(sub_chunks):
                chunks.append(Chunk(
                    content=sc,
                    metadata={
                        "file_path": parsed.relative_path,
                        "language": language,
                        "chunk_type": chunk_type,
                        "symbol": name,
                        "start_line": start_line + 1,
                        "end_line": end_line,
                        "sub_chunk": j,
                        "ast_parsed": True,
                    },
                ))
        else:
            chunks.append(Chunk(
                content=content,
                metadata={
                    "file_path": parsed.relative_path,
                    "language": language,
                    "chunk_type": chunk_type,
                    "symbol": name,
                    "start_line": start_line + 1,
                    "end_line": end_line,
                    "ast_parsed": True,
                },
            ))

    # Check for trailing content after the last definition
    if definitions:
        last_def_end = definitions[-1]["end_line"] + 1
        if last_def_end < len(lines):
            trailing = "".join(lines[last_def_end:]).strip()
            if trailing and len(trailing) > 50:  # Only if non-trivial
                chunks.append(Chunk(
                    content=trailing,
                    metadata={
                        "file_path": parsed.relative_path,
                        "language": language,
                        "chunk_type": "code_block",
                        "start_line": last_def_end + 1,
                        "end_line": len(lines),
                        "ast_parsed": True,
                    },
                ))

    if not chunks:
        return None

    logger.debug(
        "ast_chunking_complete",
        path=parsed.relative_path,
        language=language,
        num_definitions=len(definitions),
        num_chunks=len(chunks),
    )
    return chunks


def _split_ast_chunk(text: str, size: int, overlap: int) -> List[str]:
    """Split a large AST node into overlapping sub-chunks at line boundaries."""
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + size
        if end < len(text):
            # Snap to nearest newline
            newline_pos = text.rfind("\n", start, end)
            if newline_pos > start:
                end = newline_pos + 1
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start = max(start + 1, end - overlap)
    return chunks
