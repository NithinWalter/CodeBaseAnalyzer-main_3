from tree_sitter import Language, Parser
import tree_sitter_python as tspython

PYTHON_LANGUAGE = Language(tspython.language())


def parse(code: str):
    parser = Parser(PYTHON_LANGUAGE)
    return parser.parse(bytes(code, "utf8"))