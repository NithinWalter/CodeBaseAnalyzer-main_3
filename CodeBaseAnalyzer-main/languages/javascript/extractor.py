"""
extractor.py  (languages/javascript)
--------------------------------------
Phase 1  – extract_iam_entry_points()
    Scans every function/arrow-function/method in a JS/JSX file and returns
    only those that are IAM-consumable data-exposing entry points.

Phase 2  – extract_all_methods()
    Returns EVERY callable unit in the file as a lightweight dict so the
    engine can build the cross-file method registry for call-graph resolution.

Phase 3  – extract_all()  ← PRIMARY ENTRY POINT (new)
    Single tree pass that produces entry_points, all_methods, endpoints,
    data_exposures, and auth in one shot.  engine.py uses this to avoid
    the 3× re-extraction that the legacy shims caused.

Detection strategy (4-level priority, mirrors Java extractor):

  1. NestJS / decorators  – @Get(), @Post(), @Query(), @Resolver(), …
  2. Route-registration call pattern  – app.get('/p', fn), router.post(…)
  3. Body signature scanning  – imports + API call patterns
  4. File-level import fallback  – if file imports 'express' and no route
     detected yet, any exported async function is a candidate REST handler.
"""

import re
from tree_sitter import QueryCursor

from .parser import JS_LANGUAGE
from . import rules

# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL QUERY CACHE
# Query compilation is expensive (string parsing + tree-sitter compile step).
# Build each query once at import time and reuse the compiled object.
# QueryCursor is cheap and IS created per-call (it tracks match state).
# ══════════════════════════════════════════════════════════════════════════════

_Q_IMPORT         = rules.import_query(JS_LANGUAGE)
_Q_ROUTE_CALL     = rules.route_call_query(JS_LANGUAGE)
_Q_DECORATOR      = rules.decorator_query(JS_LANGUAGE)
_Q_FN_DECL        = rules.function_declaration_query(JS_LANGUAGE)
_Q_ARROW_FN       = rules.arrow_function_query(JS_LANGUAGE)
_Q_METHOD_DEF     = rules.method_definition_query(JS_LANGUAGE)
_Q_EXPORT_DEFAULT = rules.export_default_query(JS_LANGUAGE)
_Q_CALL_EXPR      = rules.call_expression_query(JS_LANGUAGE)

# ══════════════════════════════════════════════════════════════════════════════
# HTTP VERB SETS
# ══════════════════════════════════════════════════════════════════════════════

_REST_VERBS = {"get", "post", "put", "delete", "patch", "head", "options", "all"}

# ── NestJS / decorator → (endpoint_type, http_verb) ──────────────────────────
_NESTJS_HTTP = {
    "get":     ("REST", "GET"),
    "post":    ("REST", "POST"),
    "put":     ("REST", "PUT"),
    "delete":  ("REST", "DELETE"),
    "patch":   ("REST", "PATCH"),
    "head":    ("REST", "HEAD"),
    "options": ("REST", "OPTIONS"),
    "all":     ("REST", "ALL"),
    # HTTP (NestJS alias)
    "http":    ("REST", "REQUEST"),
}

# NestJS / Mercurius GraphQL decorators
_NESTJS_GRAPHQL_DEC = {
    "query", "mutation", "subscription", "resolver",
    "referencesolver", "resolveield",
}

# NestJS misc
_NESTJS_WS_DEC = {
    "subscribeMessage", "websocketgateway", "messageBody",
    "connectedsocket", "webSocketServer",
}

# Auth-related decorator names
_AUTH_DEC = {
    "useguards", "roles", "public", "authorize", "bearer",
    "jwtauthguard", "authguard", "permissions",
}

# ══════════════════════════════════════════════════════════════════════════════
# AUTH HINTS
# ══════════════════════════════════════════════════════════════════════════════

_AUTH_HINTS = {
    "jwt", "jsonwebtoken", "passport", "auth", "authentication",
    "authorization", "guard", "token", "session", "cookie",
    "bcrypt", "argon2", "crypto",
}

# Pre-compiled regex for fast auth hint matching (replaces O(N×H) nested loop)
_AUTH_HINTS_RE = re.compile(
    "|".join(re.escape(h) for h in _AUTH_HINTS), re.IGNORECASE
)

# ══════════════════════════════════════════════════════════════════════════════
# BODY SIGNATURE TABLES
# Each maps endpoint_type → list of case-insensitive substrings found
# inside the function body (imports resolved first, then inline calls).
# ══════════════════════════════════════════════════════════════════════════════

BODY_SIGNATURES = {
    # ── REST (inbound)  ───────────────────────────────────────────────────────
    "REST": [
        "req.body", "req.params", "req.query", "res.json(", "res.send(",
        "res.status(", "ctx.body", "ctx.params", "ctx.query",
        "reply.send(", "reply.code(",
        # Next.js / serverless
        "req.method", "res.end(",
    ],
    # ── GraphQL  ──────────────────────────────────────────────────────────────
    "GRAPHQL": [
        "apolloserver(", "new apolloserver(",
        "graphqlschema(", "buildschema(", "makeschema(",
        "typedefs", "resolvers",
        "graphql(schema", "graphqlhttp(",
        "graphqlyoga(", "yoga(",
        "mercurius(",
        "context.dataloaders", "info.fieldname", "parent, args, context",
        "@nestjs/graphql",
    ],
    # ── gRPC  ─────────────────────────────────────────────────────────────────
    "GRPC": [
        "@grpc/grpc-js", "grpc.server(", "grpc.credentials",
        "server.addservice(", "server.bindAsync(",
        "grpc.loadpackagedefinition(", "protoloader.loadSync(",
        "call.request", "callback(null,", "call.write(",
        "grpcobject",
    ],
    # ── SOAP  ─────────────────────────────────────────────────────────────────
    "SOAP": [
        "soap.createserver(", "soap.listen(",
        "soap.createclient(", "soap.wsdl",
        "strong-soap", "easysoap",
        "soapclient.call(", "soap.createClientAsync(",
    ],
    # ── Direct SQL  ───────────────────────────────────────────────────────────
    "JDBC": [
        "pool.query(", "client.query(", "connection.query(",
        "db.query(", "pool.execute(", "pool.getconnection(",
        "mysql.createpool(", "mysql2.createpool(",
        "pg.pool(", "new pg.client(",
        "sqlite3.database(", "mssql.request(", "mssql.query(",
        "oracledb.getconnection(",
        "pool.request(", "pool.input(", "recordset",
    ],
    # ── NoSQL / MongoDB  ──────────────────────────────────────────────────────
    "NOSQL": [
        "db.collection(", ".find(", ".findone(", ".insertone(",
        ".insertmany(", ".updateone(", ".updatemany(",
        ".deleteone(", ".deletemany(", ".aggregate(",
        "mongoose.model(", "new mongoose.schema(",
        "model.find(", "model.findbyid(", "model.create(",
        # Redis
        "redisclient.get(", "redisclient.set(", "redisclient.hset(",
        "client.get(", "client.set(", "redis.get(",
        "ioredis(",
        # Cassandra
        "cassandra-driver", "client.execute(",
        # Elasticsearch
        "@elastic/elasticsearch", "client.index(", "client.search(",
        "opensearch-js",
    ],
    # ── LDAP / Active Directory  ──────────────────────────────────────────────
    "LDAP": [
        "ldapjs", "ldap.createclient(", "client.search(",
        "client.bind(", "client.add(", "client.modify(",
        "client.del(", "client.compare(",
        "activedirectory2", "ad.authenticate(", "ad.finduser(",
        "ad.getgroupmembershipforrdn(",
    ],
    # ── File-based Exposure  ──────────────────────────────────────────────────
    "FILE_IO": [
        # Built-in fs
        "fs.writefile(", "fs.createwritestream(", "fs.appendfile(",
        "fs.writesync(",
        # CSV
        "csv-parser", "csv.parse(", "csvstringify(", "parse(data",
        "csvwriter(", "createcsvwriter(", "csv.stringify(",
        # JSON
        "json.stringify(", "jsonfile.writefile(",
        # XML
        "xml2js.parsestring(", "xmlbuilder.create(", "new dom(",
        "builder.buildObject(",
        # Excel
        "xlsx.utils.book_new(", "xlsx.writeFile(", "new exceljs.workbook(",
        "workbook.xlsx.writeFile(",
    ],
    # ── REST Outbound / HTTP Client  ──────────────────────────────────────────
    "REST_OUTBOUND": [
        "axios.get(", "axios.post(", "axios.put(", "axios.delete(",
        "axios.patch(", "axios.request(", "axios.create(",
        "fetch(", "node-fetch", "got.get(", "got.post(",
        "superagent.get(", "superagent.post(",
        "http.request(", "https.request(",
        "request(", "needle.get(", "needle.post(",
    ],
    # ── WebSocket / Real-time  ────────────────────────────────────────────────
    "WEBSOCKET": [
        "io.on('connection'", 'io.on("connection"',
        "wss.on('connection'", 'wss.on("connection"',
        "socket.emit(", "socket.on(",
        "ws.send(", "ws.on(",
        "io.to(", "io.emit(",
        "uwebsockets", "uwsapp(",
    ],
    # ── Messaging  ────────────────────────────────────────────────────────────
    "MESSAGING": [
        "producer.send(", "kafkajs", "kafka.producer(", "kafka.consumer(",
        "amqplib", "channel.publish(", "channel.assertqueue(",
        "amqp.createconnection(", "rabbitmq",
        "sns.publish(", "sqs.sendmessage(",
        "bull.add(", "bullmq",
    ],
    # ── Cloud Object Storage  ─────────────────────────────────────────────────
    "CLOUD_STORAGE": [
        "s3.putobject(", "s3.getobject(", "s3.upload(", "s3.deletobject(",
        "@aws-sdk/client-s3", "new s3client(",
        "blobserviceclient", "containerclient.uploadblockblob(",
        "@azure/storage-blob",
        "@google-cloud/storage", "bucket.upload(", "bucket.file(",
    ],
    # ── Search Engines  ───────────────────────────────────────────────────────
    "SEARCH_ENGINE": [
        "@elastic/elasticsearch", "client.index(", "client.search(",
        "opensearch-js", "client.indices.create(",
    ],
    # ── Serverless / Function handlers  ──────────────────────────────────────
    "SERVERLESS": [
        "exports.handler", "module.exports.handler",
        "context.succeed(", "context.fail(", "callback(null,",
        "firebase-functions", "functions.https.onrequest(",
        "functions.pubsub.schedule(",
        "@azure/functions", "context.res",
        "vercel", "next.js",
    ],
    # ── OAuth2 / OIDC / SAML  ────────────────────────────────────────────────
    "OAUTH2": [
        "passport.authenticate(", "passport-oauth2",
        "oauth2.authorizationcode", "client.callback(",
        "openid-client", "issuer.discover(", "client.userinfo(",
        "passport-saml", "samlstrategy(",
    ],
    # ── SCIM  ────────────────────────────────────────────────────────────────
    "SCIM": [
        "/scim/v2", "scimresource", "scimuser", "scimgroup",
        "scimerror",
    ],
    # ── Webhooks (push-based)  ───────────────────────────────────────────────
    "WEBHOOK": [
        "webhook", "x-hub-signature", "x-signature",
        "stripe-signature", "github-signature",
        "payload.event", "webhook.on(",
    ],
}

# ── Import string → endpoint_type (package-level fallback)  ──────────────────
IMPORT_IAM = {
    "express":                  "REST",
    "fastify":                  "REST",
    "koa":                      "REST",
    "@hapi/hapi":               "REST",
    "hapi":                     "REST",
    "@nestjs/core":             "REST",
    "next":                     "REST",
    "apollo-server":            "GRAPHQL",
    "apollo-server-express":    "GRAPHQL",
    "apollo-server-fastify":    "GRAPHQL",
    "@nestjs/graphql":          "GRAPHQL",
    "graphql-yoga":             "GRAPHQL",
    "mercurius":                "GRAPHQL",
    "@grpc/grpc-js":            "GRPC",
    "grpc":                     "GRPC",
    "soap":                     "SOAP",
    "strong-soap":              "SOAP",
    "mysql":                    "JDBC",
    "mysql2":                   "JDBC",
    "pg":                       "JDBC",
    "sqlite3":                  "JDBC",
    "mssql":                    "JDBC",
    "oracledb":                 "JDBC",
    "mongoose":                 "NOSQL",
    "mongodb":                  "NOSQL",
    "redis":                    "NOSQL",
    "ioredis":                  "NOSQL",
    "cassandra-driver":         "NOSQL",
    "@elastic/elasticsearch":   "NOSQL",
    "opensearch-js":            "NOSQL",
    "ldapjs":                   "LDAP",
    "activedirectory2":         "LDAP",
    "axios":                    "REST_OUTBOUND",
    "node-fetch":               "REST_OUTBOUND",
    "got":                      "REST_OUTBOUND",
    "superagent":               "REST_OUTBOUND",
    "ws":                       "WEBSOCKET",
    "socket.io":                "WEBSOCKET",
    "kafkajs":                  "MESSAGING",
    "amqplib":                  "MESSAGING",
    "bull":                     "MESSAGING",
    "bullmq":                   "MESSAGING",
    "aws-sdk":                  "CLOUD_STORAGE",
    "@aws-sdk/client-s3":       "CLOUD_STORAGE",
    "@azure/storage-blob":      "CLOUD_STORAGE",
    "@google-cloud/storage":    "CLOUD_STORAGE",
    "firebase-functions":       "SERVERLESS",
    "@azure/functions":         "SERVERLESS",
    "passport":                 "OAUTH2",
    "passport-oauth2":          "OAUTH2",
    "openid-client":            "OAUTH2",
    "passport-saml":            "OAUTH2",
}

# ── Noise function names to skip in call graph  ───────────────────────────────
_CALL_SKIP = {
    # JS built-ins
    "console", "log", "error", "warn", "info", "debug",
    "json", "stringify", "parse", "toString", "valueOf",
    "hasOwnProperty", "isPrototypeOf",
    # Array / Object
    "map", "filter", "reduce", "forEach", "find", "findIndex",
    "some", "every", "includes", "indexOf", "push", "pop",
    "shift", "unshift", "splice", "slice", "concat", "join",
    "keys", "values", "entries", "assign", "freeze", "create",
    # Promise
    "then", "catch", "finally", "resolve", "reject", "all",
    "allSettled", "race", "any",
    # String
    "toLowerCase", "toUpperCase", "trim", "replace", "replaceAll",
    "split", "startsWith", "endsWith", "includes", "match",
    "padStart", "padEnd", "repeat",
    # Math / Number
    "parseInt", "parseFloat", "isNaN", "isFinite",
    "Math", "floor", "ceil", "round", "abs", "max", "min",
    # Lifecycle noise
    "constructor", "super", "next", "done", "callback",
    # Setters / getters noise
    "get", "set", "has", "delete", "clear", "size",
    # Common framework helpers that aren't business logic
    "send", "status", "json", "end", "redirect", "render",
    "use", "listen", "close", "connect",
}

# ── Entry-point names to skip (lifecycle / infrastructure) ───────────────────
_ENTRY_SKIP = {
    "constructor", "main", "init", "setup", "bootstrap",
    "configure", "register", "onModuleInit", "onModuleDestroy",
    "onApplicationBootstrap", "beforeApplicationShutdown",
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _ci(s):
    return s.lower() if s else ""


def _txt(node, code: str) -> str:
    return code[node.start_byte:node.end_byte]


def _strip_quotes(s: str) -> str:
    """Remove surrounding quotes from a string literal."""
    s = s.strip()
    if len(s) >= 2 and s[0] in ('"', "'", "`") and s[-1] in ('"', "'", "`"):
        return s[1:-1]
    return s


def _extract_string_value(node, code: str) -> str:
    return _strip_quotes(_txt(node, code))


# ══════════════════════════════════════════════════════════════════════════════
# FILE-LEVEL IMPORT SCANNING
# ══════════════════════════════════════════════════════════════════════════════

def _collect_imports(tree, code: str) -> set:
    """
    Returns set of all raw package strings imported by the file.

    Handles:
      import express from 'express'
      import { Router } from 'express'
      const knex = require('knex')

    OPTIMIZED: Uses module-level cached _Q_IMPORT query object.
    """
    cu       = QueryCursor(_Q_IMPORT)
    packages = set()

    for _, m in cu.matches(tree.root_node):
        # ES-module import
        src = m.get("import.source", [])
        if src:
            packages.add(_strip_quotes(_txt(src[0], code)))

        # CommonJS require
        req_fn  = m.get("require.fn",     [])
        req_src = m.get("require.source", [])
        if req_fn and req_src:
            if _txt(req_fn[0], code) == "require":
                packages.add(_strip_quotes(_txt(req_src[0], code)))

    return packages


def _file_iam_types(packages: set) -> set:
    """Return all IAM types implied by the file's imports."""
    types = set()
    for pkg in packages:
        mapped = IMPORT_IAM.get(pkg)
        if mapped:
            types.add(mapped)
        for imp_key, imp_type in IMPORT_IAM.items():
            if pkg.startswith(imp_key) or imp_key.startswith(pkg.split("/")[0]):
                types.add(imp_type)
    return types


def _detect_iam_type_from_body(body_lower: str) -> str | None:
    """Return the first matching IAM type from body signatures, or None."""
    for iam_type, sigs in BODY_SIGNATURES.items():
        if any(sig in body_lower for sig in sigs):
            return iam_type
    return None


def _detect_iam_type_from_packages(packages: set) -> str | None:
    """Return IAM type from file imports (for fallback), or None."""
    for priority_type in [
        "REST", "GRAPHQL", "GRPC", "SOAP",
        "JDBC", "NOSQL", "LDAP",
        "WEBSOCKET", "MESSAGING", "CLOUD_STORAGE",
        "SERVERLESS", "OAUTH2", "REST_OUTBOUND",
        "FILE_IO", "SCIM", "WEBHOOK", "SEARCH_ENGINE",
    ]:
        for pkg in packages:
            if IMPORT_IAM.get(pkg) == priority_type:
                return priority_type
    return None


def _extract_called_functions(body_node, code: str) -> list:
    """
    Return unique function/method names called inside body_node.
    Filters out noise using _CALL_SKIP.

    OPTIMIZED: Uses module-level cached _Q_CALL_EXPR query object.
    """
    cu    = QueryCursor(_Q_CALL_EXPR)
    found = set()
    for _, match in cu.matches(body_node):
        for n in match.get("call.name", []):
            name = _txt(n, code)
            if name not in _CALL_SKIP and len(name) > 2:
                found.add(name)
    return list(found)


def _get_auth_hints(body_lower: str, packages: set) -> list:
    """Return auth-related clues found in the function body or imports.

    Uses a pre-compiled regex instead of the original O(N×H) nested loop.
    """
    hints = set()
    for m in _AUTH_HINTS_RE.finditer(body_lower):
        hints.add(m.group(0))
    for pkg in packages:
        if _AUTH_HINTS_RE.search(_ci(pkg)):
            hints.add(pkg)
    return list(hints)


# ══════════════════════════════════════════════════════════════════════════════
# ROUTE REGISTRATION DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _extract_route_registrations(tree, code: str) -> list:
    """
    Returns list of dicts:
      { handler_name, route, http_verb, start_byte, end_byte }
    Only matches if the verb is a known HTTP verb.

    OPTIMIZED: Uses module-level cached _Q_ROUTE_CALL query object.
    """
    cu            = QueryCursor(_Q_ROUTE_CALL)
    registrations = []
    seen          = set()

    for _, m in cu.matches(tree.root_node):
        verb_nodes = m.get("route.verb", [])
        path_nodes = m.get("route.path", [])
        call_nodes = m.get("route.call", [])

        if not verb_nodes or not path_nodes:
            continue

        verb = _ci(_txt(verb_nodes[0], code))
        if verb not in _REST_VERBS and verb != "route":
            continue

        path  = _extract_string_value(path_nodes[0], code)
        start = call_nodes[0].start_byte if call_nodes else 0
        end   = call_nodes[0].end_byte   if call_nodes else 0

        key = (verb, path)
        if key in seen:
            continue
        seen.add(key)

        registrations.append({
            "http_verb":  verb.upper(),
            "route":      path,
            "start_byte": start,
            "end_byte":   end,
        })

    return registrations


# ══════════════════════════════════════════════════════════════════════════════
# NESTJS DECORATOR DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _collect_decorators(tree, code: str) -> dict:
    """
    Returns { method_node_start_byte: [decorator_info, …] }

    decorator_info = { name: str, args: str, raw: str }

    OPTIMIZED: Uses module-level cached _Q_DECORATOR query object.
    """
    cu     = QueryCursor(_Q_DECORATOR)
    result = {}

    for _, m in cu.matches(tree.root_node):
        dec_decl = m.get("dec.decl", [])
        dec_name = m.get("dec.name", [])
        dec_args = m.get("dec.args", [])

        if not dec_decl or not dec_name:
            continue

        node    = dec_decl[0]
        sibling = node.next_sibling
        while sibling and sibling.type in ("comment", "decorator"):
            sibling = sibling.next_sibling

        if not sibling:
            continue

        target_start = sibling.start_byte
        name_text    = _txt(dec_name[0], code)
        args_text    = _txt(dec_args[0], code) if dec_args else ""

        result.setdefault(target_start, []).append({
            "name": name_text,
            "args": args_text,
            "raw":  _txt(node, code),
        })

    return result


def _nestjs_endpoint_type(decorators: list) -> tuple | None:
    """Given decorator list for a method/class, return (endpoint_type, http_verb) or None."""
    for dec in decorators:
        name_lower = _ci(dec["name"])
        pair = _NESTJS_HTTP.get(name_lower)
        if pair:
            return pair
        if name_lower in _NESTJS_GRAPHQL_DEC:
            return ("GRAPHQL", None)
        if name_lower in _NESTJS_WS_DEC:
            return ("WEBSOCKET", None)
    return None


def _nestjs_route_from_decorators(decorators: list) -> str:
    """Extract the route path from NestJS HTTP decorator args."""
    for dec in decorators:
        if _ci(dec["name"]) in _NESTJS_HTTP:
            found = re.findall(r"""['\"`]([^'\"`]+)['\"`]""", dec["args"])
            return found[0] if found else "/"
    return "/"


def _nestjs_verb_from_decorators(decorators: list) -> str | None:
    for dec in decorators:
        pair = _NESTJS_HTTP.get(_ci(dec["name"]))
        if pair:
            return pair[1]
    return None


def _auth_from_decorators(decorators: list) -> list:
    return [
        dec["raw"] for dec in decorators
        if _ci(dec["name"]) in _AUTH_DEC
        or _AUTH_HINTS_RE.search(_ci(dec["name"]))
    ]


# ══════════════════════════════════════════════════════════════════════════════
# FUNCTION COLLECTION — produces a flat list of all callable units
# ══════════════════════════════════════════════════════════════════════════════

def _collect_all_callables(tree, code: str) -> list:
    """
    Returns a list of dicts covering function declarations, arrow/function
    variable declarators, class method definitions, and export-default handlers.

    OPTIMIZED: Uses module-level cached query objects for all 4 query types.
    """
    callables = []
    seen      = set()

    def _add(name, decl_node, body_node, is_exported=False, is_default=False):
        key = (name, decl_node.start_byte)
        if key in seen:
            return
        seen.add(key)
        callables.append({
            "name":              name,
            "start_byte":        decl_node.start_byte,
            "end_byte":          decl_node.end_byte,
            "body_node":         body_node,
            "body_text":         _txt(body_node, code),
            "code_block":        _txt(decl_node, code),
            "is_exported":       is_exported,
            "is_default_export": is_default,
        })

    for q, is_default in [
        (_Q_FN_DECL,        False),
        (_Q_ARROW_FN,       False),
        (_Q_METHOD_DEF,     False),
        (_Q_EXPORT_DEFAULT, True),
    ]:
        cu = QueryCursor(q)
        for _, m in cu.matches(tree.root_node):
            names  = m.get("fn.name",  [])
            bodies = m.get("fn.body",  [])
            decls  = m.get("fn.decl",  [])
            if names and bodies and decls:
                _add(_txt(names[0], code), decls[0], bodies[0],
                     is_exported=is_default, is_default=is_default)

    return callables


# ══════════════════════════════════════════════════════════════════════════════
# SHARED INTERNAL: AUTH RECORD EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _extract_auth_records(tree, code: str, file: str) -> list:
    """Extract file-level auth import/decorator records.

    Used by extract_all() and the extract_auth() shim so the logic
    only executes once regardless of which path the caller takes.
    """
    packages = _collect_imports(tree, code)
    auth     = []
    for pkg in packages:
        if _AUTH_HINTS_RE.search(_ci(pkg)):
            auth.append({"type": pkg, "file": file, "code_block": f"import '{pkg}'"})
    if "jwt" in _ci(code) or "token" in _ci(code):
        auth.append({"type": "TokenBased", "file": file, "code_block": ""})
    return auth


# ══════════════════════════════════════════════════════════════════════════════
# PRIMARY ENTRY POINT — extract_all()
# ══════════════════════════════════════════════════════════════════════════════

def extract_all(tree, code: str, file: str) -> dict:
    """
    Single tree traversal that produces ALL extraction outputs at once.

    This is the primary function called by engine.py.  It replaces the
    previous pattern of calling extract_iam_entry_points + extract_all_methods
    + extract_endpoints + extract_data_exposures separately (which caused
    3–4× redundant tree walks and repeated query compilation per file).

    Returns a dict with keys:
      entry_points    – list of IAM entry point records
      all_methods     – list of all callable records (for cross-file registry)
      endpoints       – flat REST endpoint records (backward-compat shim output)
      data_exposures  – flat non-REST exposure records (backward-compat shim output)
      auth            – file-level auth import records
    """
    packages   = _collect_imports(tree, code)
    decorators = _collect_decorators(tree, code)
    routes     = _extract_route_registrations(tree, code)
    callables  = _collect_all_callables(tree, code)
    file_iam   = _file_iam_types(packages)

    entry_points   = []
    all_methods    = []
    endpoints      = []
    data_exposures = []

    seen_ep  = set()   # (name, file, endpoint_type)
    seen_m   = set()   # (file, start_byte)
    # called_methods cache: compute once per callable, reuse in both outputs
    called_cache = {}  # start_byte → [called_function_names]

    for fn in callables:
        name  = fn["name"]
        start = fn["start_byte"]

        # ── Compute called_methods once per callable ───────────────────────────
        if start not in called_cache:
            called_cache[start] = _extract_called_functions(fn["body_node"], code)
        called = called_cache[start]

        body_lower = _ci(fn["body_text"])
        fn_decs    = decorators.get(start, [])
        auth_list  = list(set(
            _auth_from_decorators(fn_decs) + _get_auth_hints(body_lower, packages)
        ))

        # ── all_methods record ────────────────────────────────────────────────
        m_key = (file, start)
        if m_key not in seen_m:
            seen_m.add(m_key)
            all_methods.append({
                "name":           name,
                "file":           file,
                "code_block":     fn["code_block"],
                "body_text":      fn["body_text"],
                "auth":           auth_list,
                "called_methods": called,
            })

        # ── entry-point candidate check ───────────────────────────────────────
        if name in _ENTRY_SKIP:
            continue

        endpoint_type = None
        http_verb     = None
        route         = None
        # Lazy-compute body_lower only when needed (already done above for auth;
        # reuse it here — no extra cost in JS since auth always needs it)

        # 1. NestJS / decorator-driven
        if fn_decs:
            result = _nestjs_endpoint_type(fn_decs)
            if result:
                endpoint_type, http_verb = result
                if endpoint_type == "REST":
                    route     = _nestjs_route_from_decorators(fn_decs)
                    http_verb = _nestjs_verb_from_decorators(fn_decs)

        # 2. Route registration: app.get('/path', thisHandler)
        if not endpoint_type:
            for reg in routes:
                if name.lower() in _ci(code):
                    endpoint_type = "REST"
                    http_verb     = reg["http_verb"]
                    route         = reg["route"]
                    break

        # 3. Body signature scanning
        if not endpoint_type:
            endpoint_type = _detect_iam_type_from_body(body_lower)

        # 4. File-level import fallback (handler-signal check)
        if not endpoint_type and file_iam:
            handler_signals = [
                "req,", "res,", "(req,", "(res,", "ctx,", "(ctx,",
                "event,", "(event,", "context,", "callback,",
                "request,", "response,",
            ]
            if any(sig in body_lower or sig in _ci(fn["code_block"])
                   for sig in handler_signals):
                endpoint_type = _detect_iam_type_from_packages(packages)

        # Next.js API route: export default handler
        if not endpoint_type and fn["is_default_export"]:
            if "req" in body_lower or "res" in body_lower:
                endpoint_type = "REST"

        if not endpoint_type:
            endpoint_type = "UNKNOWN"

        ep_key = (name, file, endpoint_type)
        if ep_key in seen_ep:
            continue
        seen_ep.add(ep_key)

        ep_record = {
            "name":           name,
            "endpoint_type":  endpoint_type,
            "file":           file,
            "route":          route if endpoint_type == "REST" else None,
            "http_method":    http_verb,
            "code_block":     fn["code_block"],
            "auth":           auth_list,
            "called_methods": called,
        }
        entry_points.append(ep_record)

        # ── Derive flat records in the same pass ──────────────────────────────
        if endpoint_type == "REST":
            endpoints.append({
                "handler":    name,
                "route":      route or "/",
                "method":     http_verb or "REST",
                "file":       file,
                "auth":       auth_list,
                "code_block": fn["code_block"],
            })
        else:
            data_exposures.append({
                "handler":        name,
                "file":           file,
                "exposure_types": [endpoint_type],
                "code_block":     fn["code_block"],
                "auth":           [{"type": a, "file": file, "code_block": a}
                                   for a in auth_list],
            })

    auth = _extract_auth_records(tree, code, file)

    return {
        "entry_points":   entry_points,
        "all_methods":    all_methods,
        "endpoints":      endpoints,
        "data_exposures": data_exposures,
        "auth":           auth,
    }


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — IAM ENTRY POINT EXTRACTION  (legacy, kept for backward compat)
# ══════════════════════════════════════════════════════════════════════════════

def extract_iam_entry_points(tree, code: str, file: str) -> list:
    """
    Scan every callable unit in the file and return only those that are
    IAM-consumable data-exposing entry points.

    Kept for backward compatibility.  engine.py now calls extract_all() which
    is faster.  This function is still correct and uses cached query objects.
    """
    packages   = _collect_imports(tree, code)
    decorators = _collect_decorators(tree, code)
    routes     = _extract_route_registrations(tree, code)
    callables  = _collect_all_callables(tree, code)
    file_iam   = _file_iam_types(packages)

    entries = []
    seen    = set()

    for fn in callables:
        name = fn["name"]
        if name in _ENTRY_SKIP:
            continue

        start      = fn["start_byte"]
        body_lower = _ci(fn["body_text"])
        fn_decs    = decorators.get(start, [])

        endpoint_type = None
        http_verb     = None
        route         = None

        if fn_decs:
            result = _nestjs_endpoint_type(fn_decs)
            if result:
                endpoint_type, http_verb = result
                if endpoint_type == "REST":
                    route     = _nestjs_route_from_decorators(fn_decs)
                    http_verb = _nestjs_verb_from_decorators(fn_decs)

        if not endpoint_type:
            for reg in routes:
                if name.lower() in _ci(code):
                    endpoint_type = "REST"
                    http_verb     = reg["http_verb"]
                    route         = reg["route"]
                    break

        if not endpoint_type:
            endpoint_type = _detect_iam_type_from_body(body_lower)

        if not endpoint_type and file_iam:
            handler_signals = [
                "req,", "res,", "(req,", "(res,", "ctx,", "(ctx,",
                "event,", "(event,", "context,", "callback,",
                "request,", "response,",
            ]
            if any(sig in body_lower or sig in _ci(fn["code_block"])
                   for sig in handler_signals):
                endpoint_type = _detect_iam_type_from_packages(packages)

        if not endpoint_type and fn["is_default_export"]:
            if "req" in body_lower or "res" in body_lower:
                endpoint_type = "REST"

        if not endpoint_type:
            continue

        dedup = (name, file, endpoint_type)
        if dedup in seen:
            continue
        seen.add(dedup)

        auth_list = list(set(
            _auth_from_decorators(fn_decs) + _get_auth_hints(body_lower, packages)
        ))

        entries.append({
            "name":           name,
            "endpoint_type":  endpoint_type,
            "file":           file,
            "route":          route if endpoint_type == "REST" else None,
            "http_method":    http_verb,
            "code_block":     fn["code_block"],
            "auth":           auth_list,
            "called_methods": _extract_called_functions(fn["body_node"], code),
        })

    return entries


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — ALL-METHODS REGISTRY  (legacy, kept for backward compat)
# ══════════════════════════════════════════════════════════════════════════════

def extract_all_methods(tree, code: str, file: str) -> list:
    """
    Extract EVERY callable unit in the file for the cross-file method registry.

    Kept for backward compatibility.  engine.py now calls extract_all() which
    produces this data without a second tree traversal.
    """
    packages   = _collect_imports(tree, code)
    decorators = _collect_decorators(tree, code)
    callables  = _collect_all_callables(tree, code)
    methods    = []
    seen       = set()

    for fn in callables:
        dedup = (file, fn["start_byte"])
        if dedup in seen:
            continue
        seen.add(dedup)

        fn_decs   = decorators.get(fn["start_byte"], [])
        auth_list = list(set(
            _auth_from_decorators(fn_decs) + _get_auth_hints(
                _ci(fn["body_text"]), packages
            )
        ))

        methods.append({
            "name":           fn["name"],
            "file":           file,
            "code_block":     fn["code_block"],
            "body_text":      fn["body_text"],
            "auth":           auth_list,
            "called_methods": _extract_called_functions(fn["body_node"], code),
        })

    return methods


# ══════════════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY SHIMS
# ══════════════════════════════════════════════════════════════════════════════

def extract_endpoints(tree, code: str, file: str) -> list:
    """Shim — returns flat REST endpoint dicts for exposure_map backward compat."""
    return extract_all(tree, code, file)["endpoints"]


def extract_auth(tree, code: str, file: str) -> list:
    """Shim — file-level auth annotation/import records."""
    return _extract_auth_records(tree, code, file)


def extract_data_exposures(tree, code: str, file: str) -> list:
    """Shim — returns non-REST entry points as data_exposure dicts."""
    return extract_all(tree, code, file)["data_exposures"]