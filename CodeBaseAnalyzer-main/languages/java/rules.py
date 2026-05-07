from tree_sitter import Query


# ─────────────────────────────────────────────────────────────────────────────
# ORIGINAL QUERIES (fixed)
# ─────────────────────────────────────────────────────────────────────────────

def endpoint_query(lang):
    return Query(lang, """
    (method_declaration
      (modifiers
        (annotation
          name: (identifier) @ann.name
          arguments: (annotation_argument_list)? @ann.args
        )+
      )
      name: (identifier) @method.name
      body: (block) @method.body
    ) @method.decl
    """)


def auth_query(lang):
    """All annotation names in the file – filtered in Python."""
    return Query(lang, """
    (annotation
      name: (identifier) @auth.name
    )
    """)


def full_method_query(lang):
    """
    Every method declaration regardless of annotations.
    """
    return Query(lang, """
    (method_declaration
      name: (identifier) @method.name
      body: (block) @method.body
    ) @method.decl
    """)


def annotated_method_query(lang):
    return Query(lang, """
    (method_declaration
      (modifiers
        (annotation
          name: (identifier) @ann.name
          arguments: (annotation_argument_list)? @ann.args
        )+
      )
      name: (identifier) @method.name
      body: (block) @method.body
    ) @method.decl
    """)


def class_annotation_query(lang):
    return Query(lang, """
    (class_declaration
      (modifiers
        (annotation
          name: (identifier) @class.ann
        )+
      )
      name: (identifier) @class.name
    ) @class.decl
    """)


def class_route_query(lang):
    return Query(lang, """
    (class_declaration
      (modifiers
        (annotation
          name: (identifier) @route.ann
          arguments: (annotation_argument_list) @route.args
        )
      )
    ) @class.decl
    """)


# ─────────────────────────────────────────────────────────────────────────────
# NEW QUERIES (unchanged — already valid)
# ─────────────────────────────────────────────────────────────────────────────

def superclass_query(lang):
    return Query(lang, """
    (class_declaration
      name: (identifier) @class.name
      (superclass
        [
          (type_identifier)         @superclass.name
          (scoped_type_identifier)  @superclass.name
        ]
      )
    ) @class.decl
    """)


def class_field_type_query(lang):
    return Query(lang, """
    (class_declaration
      name: (identifier) @class.name
      body: (class_body
        (field_declaration
          type: (type_identifier) @field.type
        )*
      )
    ) @class.decl
    """)


def method_invocation_query(lang):
    return Query(lang, """
    (method_invocation
      name: (identifier) @call.name
    )
    """)