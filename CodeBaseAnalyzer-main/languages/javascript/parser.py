"""
parser.py  (languages/javascript)
----------------------------------
Wraps tree-sitter-javascript so the rest of the engine can call:

    tree = js_parser.parse(source_code)

and get back a tree-sitter Tree object, exactly like the Java module.
"""

from tree_sitter import Language, Parser
import tree_sitter_javascript as tsjs

JS_LANGUAGE = Language(tsjs.language())


def parse(code: str):
    parser = Parser(JS_LANGUAGE)
    return parser.parse(bytes(code, "utf8"))