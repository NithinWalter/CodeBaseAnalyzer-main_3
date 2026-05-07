"""
rules.py  (languages/csharp)
------------------------------
Tree-sitter queries for C# files.

All node type names are validated against tree-sitter-c-sharp:
  • Attributes live in `attribute_list` > `attribute` nodes
  • Class base types are in `base_list` with no named field (use child type)
  • Minimal API calls are `invocation_expression` on `member_access_expression`
  • Method bodies are `block` (not `statement_block` like JS)
  • Azure Functions at top-level use `local_function_statement`
  • `using` directives use `qualified_name` or `identifier` children

C# uses attributes instead of Java annotations:
  [HttpGet("{id}")]  [Authorize]  [ServiceContract]  [FunctionName("X")]
"""

from tree_sitter import Query


# ─────────────────────────────────────────────────────────────────────────────
# USING-DIRECTIVE (namespace imports)
# ─────────────────────────────────────────────────────────────────────────────

def using_directive_query(lang):
    """
    using Microsoft.AspNetCore.Mvc;
    using System.Data.SqlClient;
    using Alias = Some.Namespace;

    Captures both simple identifiers and dotted qualified names.
    """
    return Query(lang, """
    (using_directive
      [
        (identifier)     @using.ns
        (qualified_name) @using.ns
      ]
    ) @using.decl
    """)


# ─────────────────────────────────────────────────────────────────────────────
# CLASS / INTERFACE DECLARATIONS
# ─────────────────────────────────────────────────────────────────────────────

def class_declaration_query(lang):
    """
    Captures every class with its attribute list, name, base types, and body.

    base_list has no named grammar field — matched as an unkeyed child.
    """
    return Query(lang, """
    (class_declaration
      (attribute_list
        (attribute name: (identifier) @class.attr)
      )*
      name: (identifier) @class.name
      (base_list (identifier) @class.base)*
      body: (declaration_list) @class.body
    ) @class.decl
    """)


def interface_declaration_query(lang):
    """
    WCF [ServiceContract] interfaces.
    """
    return Query(lang, """
    (interface_declaration
      (attribute_list
        (attribute name: (identifier) @iface.attr)
      )*
      name: (identifier) @iface.name
      body: (declaration_list) @iface.body
    ) @iface.decl
    """)


# ─────────────────────────────────────────────────────────────────────────────
# METHOD DECLARATIONS
# ─────────────────────────────────────────────────────────────────────────────

def method_declaration_query(lang):
    """
    All methods with zero or more attribute lists.

        [HttpGet("{id}")]
        [Authorize]
        public async Task<IActionResult> GetUser(int id) { … }
    """
    return Query(lang, """
    (method_declaration
      (attribute_list
        (attribute
          name: (identifier) @attr.name
          (attribute_argument_list)? @attr.args
        )
      )*
      name: (identifier) @method.name
      body: (block) @method.body
    ) @method.decl
    """)


def method_no_body_query(lang):
    """
    Interface / abstract method stubs (no body block):

        [OperationContract]
        User GetUser(int id);
    """
    return Query(lang, """
    (method_declaration
      (attribute_list
        (attribute name: (identifier) @attr.name)
      )*
      name: (identifier) @method.name
    ) @method.decl
    """)


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL FUNCTION STATEMENTS
# Top-level Azure Function handlers parsed as local_function_statement
# when the file has no enclosing class (script-style .cs).
# ─────────────────────────────────────────────────────────────────────────────

def local_function_query(lang):
    """
    [FunctionName("GetUser")]
    public static async Task<IActionResult> RunFunc(
        [HttpTrigger(…)] HttpRequest req) { … }
    """
    return Query(lang, """
    (local_function_statement
      (attribute_list
        (attribute
          name: (identifier) @attr.name
          (attribute_argument_list)? @attr.args
        )
      )*
      name: (identifier) @fn.name
      body: (block) @fn.body
    ) @fn.decl
    """)


# ─────────────────────────────────────────────────────────────────────────────
# MINIMAL API — MapGet / MapPost / MapPut / MapDelete / MapPatch
# ─────────────────────────────────────────────────────────────────────────────

def minimal_api_query(lang):
    """
    app.MapGet("/users", async (AppDbContext db) => { … });
    app.MapPost("/users", (UserDto dto) => { … });

    Captures the verb name and the string literal route path.
    The first argument must be a string_literal.
    """
    return Query(lang, """
    (invocation_expression
      function: (member_access_expression
        name: (identifier) @map.verb
      )
      arguments: (argument_list
        .
        (argument (string_literal) @map.path)
        (_)*
      )
    ) @map.call
    """)


# ─────────────────────────────────────────────────────────────────────────────
# INVOCATION EXPRESSIONS (call-graph edges)
# ─────────────────────────────────────────────────────────────────────────────

def invocation_query(lang):
    """
    Captures every method call inside a body for call-graph edge extraction.

    Handles both:
      Method()                     → bare identifier call
      obj.Method()                 → member access
      obj.Prop.Method()            → chained member access
    """
    return Query(lang, """
    (invocation_expression
      function: [
        (identifier)                            @call.name
        (member_access_expression
          name: (identifier)                    @call.name
        )
      ]
    )
    """)


# ─────────────────────────────────────────────────────────────────────────────
# FIELD DECLARATIONS (injected service type detection)
# ─────────────────────────────────────────────────────────────────────────────

def field_type_query(lang):
    """
    private readonly AppDbContext _db;
    private readonly SqlConnection _conn;
    private readonly ILdapConnection _ldap;

    Captures the type name for each class field.
    """
    return Query(lang, """
    (field_declaration
      (variable_declaration
        type: [
          (identifier)               @field.type
          (generic_name
            (identifier)             @field.type
          )
          (qualified_name)           @field.type
          (nullable_type
            (identifier)             @field.type
          )
        ]
      )
    )
    """)


# ─────────────────────────────────────────────────────────────────────────────
# ATTRIBUTE QUERY (file-level auth scan)
# ─────────────────────────────────────────────────────────────────────────────

def attribute_query(lang):
    """All attribute names in the file — filtered in Python."""
    return Query(lang, """
    (attribute
      name: (identifier) @attr.name
      (attribute_argument_list)? @attr.args
    ) @attr.decl
    """)


# ─────────────────────────────────────────────────────────────────────────────
# LAMBDA IN ARGUMENT (Minimal API inline handler body)
# ─────────────────────────────────────────────────────────────────────────────

def lambda_argument_query(lang):
    """
    Captures lambda bodies passed as arguments (Minimal API handlers):

      app.MapGet("/users", async (AppDbContext db) => {
          return await db.Users.ToListAsync();   ← this block
      });
    """
    return Query(lang, """
    (argument
      [
        (lambda_expression body: (block) @fn.body)
        (lambda_expression body: (_)     @fn.body)
      ]
    ) @fn.decl
    """)