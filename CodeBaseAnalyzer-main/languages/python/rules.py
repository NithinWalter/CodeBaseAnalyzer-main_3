from tree_sitter import Query


# ─────────────────────────────────────────────────────────────────────────────
# PYTHON GRAMMAR REFERENCE  (tree-sitter-python)
#
#  decorated_definition  – one or more decorators + function/class definition
#  function_definition   – def [async] name(params): body
#  class_definition      – class Name(bases): body
#  decorator             – @expression
#  block                 – indented body
#  parameters            – function parameter list
#  argument_list         – superclass list in class_definition
#  call                  – function call expression
#  import_statement      – import x
#  import_from_statement – from x import y
# ─────────────────────────────────────────────────────────────────────────────


def decorated_function_query(lang):
    """
    Decorated function definitions — catches Flask/FastAPI/Django routes,
    GraphQL resolvers, Celery tasks, etc.

    Captures:
      @decorator  – each decorator node (one per match)
      @func.name  – function identifier
      @func.params – parameter list
      @func.body  – function body block
      @func.def   – function_definition node
      @func.decl  – full decorated_definition node ← code_block
    """
    return Query(lang, """
    (decorated_definition
      (decorator) @decorator
      (function_definition
        name: (identifier) @func.name
        parameters: (parameters) @func.params
        body: (block) @func.body
      ) @func.def
    ) @func.decl
    """)


def full_function_query(lang):
    """
    Every function definition regardless of decorators.
    Primary workhorse for data-exposure body scanning and method registry.

    Captures:
      @func.name  – function identifier
      @func.body  – function body block
      @func.decl  – function_definition node ← code_block
    """
    return Query(lang, """
    (function_definition
      name: (identifier) @func.name
      body: (block) @func.body
    ) @func.decl
    """)


def class_definition_query(lang):
    """
    All class definitions — used to build class-level context maps.

    Captures:
      @class.name – class identifier
      @class.body – class body block
      @class.decl – class_definition node
    """
    return Query(lang, """
    (class_definition
      name: (identifier) @class.name
      body: (block) @class.body
    ) @class.decl
    """)


def class_with_bases_query(lang):
    """
    Class definitions that inherit from a base class.
    Used to detect gRPC servicers, DRF ViewSets, Django CBVs, etc.

    Captures:
      @class.name  – class identifier
      @class.bases – argument_list of superclasses
      @class.body  – class body block
      @class.decl  – full class_definition node
    """
    return Query(lang, """
    (class_definition
      name: (identifier) @class.name
      superclasses: (argument_list) @class.bases
      body: (block) @class.body
    ) @class.decl
    """)


def class_method_query(lang):
    """
    Undecorated method definitions inside class bodies.
    Catches Django CBV HTTP methods (get/post/put/delete),
    gRPC servicer methods, Flask MethodView methods.

    Captures:
      @class.name   – enclosing class identifier
      @method.name  – method identifier
      @method.body  – method body block
      @method.def   – function_definition node ← code_block
      @class.decl   – enclosing class_definition node
    """
    return Query(lang, """
    (class_definition
      name: (identifier) @class.name
      body: (block
        (function_definition
          name: (identifier) @method.name
          body: (block) @method.body
        ) @method.def
      )
    ) @class.decl
    """)


def decorated_class_method_query(lang):
    """
    Decorated method definitions inside class bodies.
    Catches DRF methods with @permission_classes, @action, etc.

    Captures:
      @class.name       – enclosing class identifier
      @method.decorator – each decorator on the method
      @method.name      – method identifier
      @method.body      – method body block
      @method.def       – function_definition node
      @method.decl      – decorated_definition node ← code_block
      @class.decl       – enclosing class_definition node
    """
    return Query(lang, """
    (class_definition
      name: (identifier) @class.name
      body: (block
        (decorated_definition
          (decorator) @method.decorator
          (function_definition
            name: (identifier) @method.name
            body: (block) @method.body
          ) @method.def
        ) @method.decl
      )
    ) @class.decl
    """)


def import_query(lang):
    """
    All import statements — used for framework/library detection.

    Captures:
      @import.name – first identifier in the module name
    """
    return Query(lang, """
    [
      (import_statement
        name: (dotted_name (identifier) @import.name))
      (import_from_statement
        module_name: (dotted_name (identifier) @import.name))
    ]
    """)


def call_expression_query(lang):
    """
    All function/method call expressions inside a block node.
    Used for call-graph edge extraction.

    Captures:
      @call.name – the called function/attribute identifier
    """
    return Query(lang, """
    [
      (call
        function: (identifier) @call.name)
      (call
        function: (attribute
          attribute: (identifier) @call.name))
    ]
    """)