"""
rules.py  (languages/javascript)
----------------------------------
Tree-sitter queries for JavaScript / JSX files.

All node type names are validated against tree-sitter-javascript:
  • import_statement      (NOT import_declaration)
  • function_expression   (NOT function — for const fn = function() {})
  • export_statement      wraps function_declaration or lexical_declaration

JavaScript has no Java-style annotations, so queries target:
  • import / require statements  → framework detection
  • function declarations, arrow-function variable declarators,
    method definitions inside classes   → function registry
  • call expressions               → route registration & called-method graph
  • class declarations             → NestJS controller/resolver context
  • decorators                     → NestJS HTTP verb / GraphQL decorators
"""

from tree_sitter import Query


# ─────────────────────────────────────────────────────────────────────────────
# IMPORT DETECTION
# Captures both ES-module and CommonJS require() forms.
# ─────────────────────────────────────────────────────────────────────────────

def import_query(lang):
    """
    ES-module:   import express from 'express'
    CommonJS:    const express = require('express')
    Named:       import { ApolloServer } from 'apollo-server'

    Node type is `import_statement` in tree-sitter-javascript
    (not `import_declaration`).
    """
    return Query(lang, """
    (import_statement
      source: (string) @import.source
    ) @import.decl

    (variable_declarator
      value: (call_expression
        function: (identifier) @require.fn
        arguments: (arguments (string) @require.source)
      )
    ) @require.decl
    """)


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION REGISTRY QUERIES
# Captures every callable unit as a "method" for the call-graph registry.
# ─────────────────────────────────────────────────────────────────────────────

def function_declaration_query(lang):
    """
    Named function declarations:   function getUserById(req, res) { … }
    """
    return Query(lang, """
    (function_declaration
      name: (identifier) @fn.name
      body: (statement_block) @fn.body
    ) @fn.decl
    """)


def arrow_function_query(lang):
    """
    Arrow functions and function expressions assigned to a const/let/var:
        const getUser = async (req, res) => { … }
        const getUser = async function(req, res) { … }

    Note: `function_expression` is the correct node type for anonymous/named
    function expressions.  The bare `function` type is not valid in queries.
    """
    return Query(lang, """
    (variable_declarator
      name: (identifier) @fn.name
      value: [
        (arrow_function      body: (statement_block) @fn.body)
        (arrow_function      body: (_)               @fn.body)
        (function_expression body: (statement_block) @fn.body)
      ]
    ) @fn.decl
    """)


def method_definition_query(lang):
    """
    Class method definitions:
        class UserController {
          async getUser(req, res) { … }
        }
    """
    return Query(lang, """
    (method_definition
      name: (property_identifier) @fn.name
      body: (statement_block) @fn.body
    ) @fn.decl
    """)


# ─────────────────────────────────────────────────────────────────────────────
# NESTJS / TYPESCRIPT DECORATOR QUERY
# Captures decorators directly above a method or class definition.
# ─────────────────────────────────────────────────────────────────────────────

def decorator_query(lang):
    """
    @Get('/users')
    @Post()
    @Resolver()
    @Controller('/api')
    """
    return Query(lang, """
    (decorator
      [
        (identifier)                              @dec.name
        (call_expression
          function: (identifier)                  @dec.name
          arguments: (arguments)                  @dec.args
        )
        (call_expression
          function: (member_expression
            property: (property_identifier)       @dec.name
          )
          arguments: (arguments)                  @dec.args
        )
      ]
    ) @dec.decl
    """)


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE REGISTRATION CALL QUERY
# Captures Express/Fastify/Koa/Hapi style route registrations.
#
#   app.get('/users', handler)
#   router.post('/users', auth, handler)
#   fastify.get('/users', opts, handler)
#   server.route({ method: 'GET', path: '/users', handler })
# ─────────────────────────────────────────────────────────────────────────────

def route_call_query(lang):
    """
    Matches: <object>.<method>(<string>, …)
    The caller filters by whether <method> is a known HTTP verb or 'route'.
    """
    return Query(lang, """
    (call_expression
      function: (member_expression
        object:   (_)                       @route.obj
        property: (property_identifier)     @route.verb
      )
      arguments: (arguments
        .
        [
          (string)                          @route.path
          (template_string)                 @route.path
        ]
        (_)*
      )
    ) @route.call
    """)


# ─────────────────────────────────────────────────────────────────────────────
# CALL EXPRESSION QUERY (for called-method graph edges)
# ─────────────────────────────────────────────────────────────────────────────

def call_expression_query(lang):
    """
    Any function call — used to extract outgoing edges from a function body.

    Captures both bare calls  foo()  and method calls  obj.foo() .
    """
    return Query(lang, """
    (call_expression
      function: [
        (identifier)                          @call.name
        (member_expression
          property: (property_identifier)     @call.name
        )
      ]
    )
    """)


# ─────────────────────────────────────────────────────────────────────────────
# CLASS DECLARATION QUERY
# Used to detect NestJS @Controller, @Resolver, @Injectable class context.
# ─────────────────────────────────────────────────────────────────────────────

def class_declaration_query(lang):
    return Query(lang, """
    (class_declaration
      name: (identifier) @class.name
      body: (class_body) @class.body
    ) @class.decl
    """)


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT DEFAULT HANDLER QUERY  (Next.js API routes)
# ─────────────────────────────────────────────────────────────────────────────

def export_default_query(lang):
    """
    export default function handler(req, res) { … }
    export default async function handler(req, res) { … }
    export default async (req, res) => { … }    (via const re-export)

    `export_statement` is the correct wrapper node in tree-sitter-javascript.
    Function expressions inside export use `function_expression`, not `function`.
    """
    return Query(lang, """
    (export_statement
      (function_declaration
        name: (identifier) @fn.name
        body: (statement_block) @fn.body
      ) @fn.decl
    )

    (export_statement
      (lexical_declaration
        (variable_declarator
          name: (identifier) @fn.name
          value: [
            (arrow_function      body: (statement_block) @fn.body)
            (function_expression body: (statement_block) @fn.body)
          ]
        ) @fn.decl
      )
    )
    """)