from tree_sitter import Language, Parser
import tree_sitter_java as tsjava

JAVA_LANGUAGE = Language(tsjava.language())


def parse(code: str):
    parser = Parser(JAVA_LANGUAGE)
    return parser.parse(bytes(code, "utf8"))