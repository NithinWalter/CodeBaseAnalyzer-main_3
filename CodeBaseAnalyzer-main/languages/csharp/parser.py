"""
parser.py  (languages/csharp)
-------------------------------
Wraps tree-sitter-c-sharp so the rest of the engine can call:

    tree = cs_parser.parse(source_code)

and get back a tree-sitter Tree object, exactly like the Java/JS modules.
"""

from tree_sitter import Language, Parser
import tree_sitter_c_sharp as tscs

CS_LANGUAGE = Language(tscs.language())


def parse(code: str):
    parser = Parser(CS_LANGUAGE)
    return parser.parse(bytes(code, "utf8"))