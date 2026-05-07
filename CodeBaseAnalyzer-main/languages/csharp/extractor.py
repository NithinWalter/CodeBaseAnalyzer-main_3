"""
extractor.py  (languages/csharp)
----------------------------------
Phase 1  – extract_iam_entry_points()
    Scans every method / local-function / minimal-API lambda in a C# file and
    returns only those that are IAM-consumable data-exposing entry points.

Phase 2  – extract_all_methods()
    Returns EVERY callable unit as a lightweight dict so engine.py can build
    the cross-file method registry for call-graph resolution.

Phase 3  – extract_all()  ← PRIMARY ENTRY POINT (new)
    Single tree pass that produces entry_points, all_methods, endpoints,
    data_exposures, and auth in one shot.  engine.py uses this to avoid
    the 3× re-extraction that the legacy shims caused.

Detection strategy — 4-level priority (mirrors Java / JS / Python extractors):

  1. HTTP-verb / framework attributes
       [HttpGet]  [HttpPost]  [OperationContract]  [QueryMapping]
       [FunctionName]  [ServerEndpoint]  [MessageMapping]
  2. Minimal API route registrations
       app.MapGet("/path", handler)  app.MapPost(…)
  3. Body signature scanning
       new SqlConnection(  context.Users.ToList(  ldapConnection.Search(
  4. Class-level fallback
       field type DbContext → JPA for all methods in that class
       field type SqlConnection → JDBC
       base class Hub → WEBSOCKET
       base class ControllerBase/ApiController → REST
"""

import bisect
import re

from tree_sitter import QueryCursor

from .parser import CS_LANGUAGE
from . import rules

# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL QUERY CACHE
# Query compilation is expensive (string parsing + tree-sitter compile step).
# Build each query once at import time and reuse the compiled object.
# QueryCursor is cheap and IS created per-call (it tracks match state).
# ══════════════════════════════════════════════════════════════════════════════

_Q_NAMESPACE    = rules.using_directive_query(CS_LANGUAGE)
_Q_CLASS_DECL   = rules.class_declaration_query(CS_LANGUAGE)
_Q_FIELD_TYPE   = rules.field_type_query(CS_LANGUAGE)
_Q_METHOD_DECL  = rules.method_declaration_query(CS_LANGUAGE)
_Q_LOCAL_FN     = rules.local_function_query(CS_LANGUAGE)
_Q_MINIMAL_API  = rules.minimal_api_query(CS_LANGUAGE)
_Q_LAMBDA_ARG   = rules.lambda_argument_query(CS_LANGUAGE)
_Q_INVOCATION   = rules.invocation_query(CS_LANGUAGE)
_Q_ATTRIBUTE    = rules.attribute_query(CS_LANGUAGE)


# ══════════════════════════════════════════════════════════════════════════════
# ATTRIBUTE → (endpoint_type, http_verb) MAPS
# ══════════════════════════════════════════════════════════════════════════════

# ASP.NET Core MVC / Web API HTTP-verb attributes
_HTTP_VERB_ATTRS = {
    "httpget":     ("REST", "GET"),
    "httppost":    ("REST", "POST"),
    "httpput":     ("REST", "PUT"),
    "httpdelete":  ("REST", "DELETE"),
    "httppatch":   ("REST", "PATCH"),
    "httphead":    ("REST", "HEAD"),
    "httpoptions": ("REST", "OPTIONS"),
    # Route + no verb → REST
    "route":       ("REST", None),
    # OData
    "enablequery":  ("REST", "GET"),
}

# Minimal API MapXxx verbs → http_verb
_MINIMAL_API_VERBS = {
    "mapget":     "GET",
    "mappost":    "POST",
    "mapput":     "PUT",
    "mapdelete":  "DELETE",
    "mappatch":   "PATCH",
    "maphead":    "HEAD",
    "mapmethods": "ANY",
    "map":        "ANY",
}

# Non-HTTP framework attributes → endpoint_type
_FRAMEWORK_ATTRS = {
    # WCF / SOAP
    "operationcontract":  "SOAP",
    "webmethod":          "SOAP",
    # gRPC
    "grpcservice":        "GRPC",
    # GraphQL — HotChocolate
    "querymapping":       "GRAPHQL",
    "mutationmapping":    "GRAPHQL",
    "subscriptionmapping":"GRAPHQL",
    "usedbcontext":       "GRAPHQL",
    # SignalR
    "hubmethodname":      "WEBSOCKET",
    "servermapping":      "WEBSOCKET",
    # Azure Functions
    "functionname":       "SERVERLESS",
}

# Auth-related attribute names
_AUTH_ATTRS = {
    "authorize", "allowanonymous", "requireauthorization",
    "roles", "policy", "claimsauthorize",
    "jwtbearer", "basicauth", "apikey",
}

# Pre-compiled regex for fast auth hint matching (replaces O(N×H) nested loop)
_AUTH_HINTS_RE = re.compile(
    "|".join(re.escape(h) for h in _AUTH_ATTRS), re.IGNORECASE
)

# ══════════════════════════════════════════════════════════════════════════════
# BODY SIGNATURE TABLES  (case-insensitive substrings)
# ══════════════════════════════════════════════════════════════════════════════

BODY_SIGNATURES = {
    # ── REST (inbound) ────────────────────────────────────────────────────────
    "REST": [
        "actionresult", "iactionresult", "httpcontext",
        "request.body", "request.form", "request.query",
        "results.ok(", "results.created(", "results.notfound(",
        "controllerbase", "controller",
        "ok(", "badrequest(", "notfound(", "created(",
    ],
    # ── GraphQL ───────────────────────────────────────────────────────────────
    "GRAPHQL": [
        "iresolvercontext", "iquerysession",
        "hotchocolate", "[usepaging]", "[usefiltering]", "[usesorting]",
        "graphql.net", "schema.execute(",
        "documentexecutor", "fieldtype", "resolvecontext",
    ],
    # ── gRPC ──────────────────────────────────────────────────────────────────
    "GRPC": [
        "grpc.aspnetcore", "serverservicedefinition",
        "asyncunaryservercall", "asyncclientstreamingcall",
        "iasyncstreamwriter", "asyncserverstreaming",
        "serverstream.writeasync(", "grpcchannel",
        "grpcenvironment", "channel.foraddress(",
    ],
    # ── SOAP / WCF ────────────────────────────────────────────────────────────
    "SOAP": [
        "soapmessage", "soapenvelope", "soapfault",
        "channelfactory<", "servicehostbase",
        "servicehost(", "ihttphandler",
        "corewcf", "wcf",
    ],
    # ── Direct SQL ────────────────────────────────────────────────────────────
    "JDBC": [
        "sqlconnection(", "sqlcommand(", "sqlclient",
        "npgsqlconnection(", "npgsqlcommand(",
        "mysqlconnection(", "mysqldataadapter",
        "oracleconnection(", "oraclecommand(",
        "oledbconnection(", "odbc",
        "executenonquery(", "executescalar(", "executereader(",
        "datareader", "dataadapter", "sqldataadapter",
        "new sqlconnection", "new npgsqlconnection",
        "new mysqlconnection", "new oracleconnection",
    ],
    # ── NoSQL ─────────────────────────────────────────────────────────────────
    "NOSQL": [
        # MongoDB
        "mongodbclient(", "imongocollection<", "mongodbclient",
        ".find(", ".insertone(", ".replaceone(", ".deleteone(",
        ".aggregate(", "bsondocument",
        # Redis
        "stackexchange.redis", "connectionmultiplexer.connect(",
        "idatabase.stringget(", "idatabase.stringset(",
        "redismultiplexer",
        # Cosmos DB
        "cosmosclient(", "container.readitemasync(",
        "container.createitemasync(", "cosmosdb",
        # Cassandra
        "cassandrasession", "cassandracluster",
        "session.execute(", "cassandramapping",
        # Elasticsearch
        "elasticclient(", "nest.", "elasticsearch.net",
        "client.index<", "client.search<",
        "opensearch.net", "opensearchclient(",
    ],
    # ── LDAP / Active Directory ───────────────────────────────────────────────
    "LDAP": [
        "directoryentry(", "directoryentry",
        "directorysearcher(", "directorysearcher",
        "searchresult", "searchresultcollection",
        "principalcontext(", "userprincipal.findbyidentity(",
        "groupprincipal.findbyidentity(",
        "accountmanagement",
        "ldapconnection(", "novell.directory.ldap",
        "ldapdirectoryidentifier",
        "searchrequest(", "searchresponse",
        "directoryservices",
        "ldap://", "ldaps://",
    ],
    # ── File I/O ──────────────────────────────────────────────────────────────
    "FILE_IO": [
        # System.IO
        "filestream(", "streamwriter(", "file.writealltext(",
        "file.writeallbytes(", "file.appendalltext(",
        "fileinfo(", "directory.createfile(",
        # JSON
        "jsonconvert.serializeobject(", "json.serialize(",
        "jsondocument.parse(", "jsonnode.",
        # CSV
        "csvwriter(", "csvhelper", "csvwriter",
        "delimiter", "getrecords<", "writerecords(",
        # Excel
        "epplus", "excelpackage(", "excelworksheet",
        "closedxml", "xlworkbook", "xlworksheet",
        "xlsxwriter",
        # XML
        "xmldocument(", "xmlwriter(", "xmlserializer(",
        "xdocument.save(", "xelement(",
        "xsltransform(", "xmltextwriter(",
    ],
    # ── HTTP Client (Outbound) ────────────────────────────────────────────────
    "REST_OUTBOUND": [
        "httpclient.getasync(", "httpclient.postasync(",
        "httpclient.putasync(", "httpclient.deleteasync(",
        "httpclient.sendasync(", "httpclient.getstring(",
        "ihttpclientfactory", "httpclientfactory",
        "restsharp", "restclient(", "restclient.execute(",
        "refit.", "irestservice",
        "new httpclient(",
    ],
    # ── WebSocket / SignalR ───────────────────────────────────────────────────
    "WEBSOCKET": [
        "hub", "clients.all.sendasync(", "clients.caller.sendasync(",
        "clients.group(", "groups.addasync(",
        "ihubcontext<", "hubcontext",
        "websocket.sendasync(", "websocket.receiveasync(",
        "system.net.websockets", "signalr",
        "clientwebsocket(",
    ],
    # ── Messaging ─────────────────────────────────────────────────────────────
    "MESSAGING": [
        "imodel.basicpublish(", "rabbitmq",
        "amazonsnsclient(", "amazonsqsclient(",
        "sns.publishasync(", "sqs.sendmessageasync(",
        "servicebus", "servicebussender.sendmessageasync(",
        "eventhubproducerclient", "eventhubconsumerclient",
        "topicproducer", "ikafkaproducer",
        "kafkaconsumer", "masstransit",
        "ibusbontrol", "busfactory.createusingrabbitm",
    ],
    # ── Cloud Storage ─────────────────────────────────────────────────────────
    "CLOUD_STORAGE": [
        # Azure Blob
        "blobserviceclient(", "blobcontainerclient(",
        "blobclient.uploadasync(", "blobclient.downloadasync(",
        "azure.storage.blobs",
        # AWS S3
        "amazons3client(", "awssdk.s3",
        "putobjectrequest(", "getobjectrequest(",
        "transferutility.upload(",
        # Google Cloud Storage
        "storageclient.create(", "google.cloud.storage",
        "bucket.uploadobjectasync(",
    ],
    # ── Search Engines ────────────────────────────────────────────────────────
    "SEARCH_ENGINE": [
        "nest.", "elasticclient(", "elasticsearch.net",
        "opensearch.net", "opensearchclient(",
        "client.index<", "client.search<",
        "searchdescriptor<", "querydescriptor<",
    ],
    # ── Serverless ────────────────────────────────────────────────────────────
    "SERVERLESS": [
        "functioncontext", "ilogger logger",
        "httptrigger", "timertrigger", "queuetrigger",
        "blobtrigger", "eventhubtrigger", "servicebustrigger",
        "azurefunction", "functionruntime",
        "amazonlambda", "ilambdacontext",
        "lambdaruntime", "lambdaentrypoint",
    ],
    # ── OAuth2 / OIDC / SAML ─────────────────────────────────────────────────
    "OAUTH2": [
        "claimsprincipal", "claimsidentity",
        "jwtbearer", "jwtregisteredclaimnames",
        "openidconnect", "microsoftidentity",
        "identityserver", "duende",
        "oauthvalidationoptions", "iauthorizationservice",
        "saml2securitytokenhandler",
    ],
    # ── Webhook ───────────────────────────────────────────────────────────────
    "WEBHOOK": [
        "x-hub-signature", "webhooksecret",
        "webhookenabled", "iwebhookreceiver",
        "webhookpayload", "stripe-signature",
        "githubwebhook",
    ],
}

# ── Field type → IAM endpoint type (class-level fallback) ────────────────────
FIELD_TYPE_IAM = {
    # EF Core / EF6
    "dbcontext":            "JPA",
    "applicationdbcontext": "JPA",
    "appdbcontext":         "JPA",
    "isession":             "JPA",       # NHibernate
    # SQL
    "sqlconnection":        "JDBC",
    "npgsqlconnection":     "JDBC",
    "mysqlconnection":      "JDBC",
    "oracleconnection":     "JDBC",
    "oledbconnection":      "JDBC",
    # MongoDB
    "mongoclient":          "NOSQL",
    "imongocollection":     "NOSQL",
    "imongodbclient":       "NOSQL",
    # Redis
    "connectionmultiplexer":"NOSQL",
    "idatabase":            "NOSQL",
    # Cosmos DB
    "cosmosclient":         "NOSQL",
    # Elasticsearch
    "elasticclient":        "NOSQL",
    "nestclient":           "NOSQL",
    # LDAP / AD
    "directoryentry":       "LDAP",
    "directorysearcher":    "LDAP",
    "principalcontext":     "LDAP",
    "ldapconnection":       "LDAP",
    # HTTP Client
    "httpclient":           "REST_OUTBOUND",
    "restclient":           "REST_OUTBOUND",
    # SignalR
    "hub":                  "WEBSOCKET",
    "ihubcontext":          "WEBSOCKET",
    # Azure Blob
    "blobserviceclient":    "CLOUD_STORAGE",
    "blobcontainerclient":  "CLOUD_STORAGE",
    # S3
    "amazons3client":       "CLOUD_STORAGE",
    # Messaging
    "servicebussender":     "MESSAGING",
    "eventhubproducerclient":"MESSAGING",
}

# ── Base class → IAM endpoint type (class-level fallback) ────────────────────
BASE_CLASS_IAM = {
    "controllerbase":      "REST",
    "controller":          "REST",
    "apicontroller":       "REST",
    "odatafeedcontroller": "REST",   # OData
    "hub":                 "WEBSOCKET",
    "stronglytypedhub":    "WEBSOCKET",
}

# ── Namespace prefix → IAM hint ───────────────────────────────────────────────
NAMESPACE_IAM = {
    "microsoft.aspnetcore.mvc":            "REST",
    "microsoft.aspnetcore.builder":        "REST",
    "system.data.sqlclient":               "JDBC",
    "microsoft.data.sqlclient":            "JDBC",
    "npgsql":                              "JDBC",
    "mysql.data":                          "JDBC",
    "oracle.manageddataaccess":            "JDBC",
    "system.data.oledb":                   "JDBC",
    "system.data.odbc":                    "JDBC",
    "microsoft.entityframeworkcore":       "JPA",
    "system.data.entity":                  "JPA",
    "dapper":                              "JPA",
    "nhibernate":                          "JPA",
    "mongodb.driver":                      "NOSQL",
    "stackexchange.redis":                 "NOSQL",
    "microsoft.azure.cosmos":              "NOSQL",
    "cassandra":                           "NOSQL",
    "elasticsearch.net":                   "NOSQL",
    "nest":                                "NOSQL",
    "opensearch.net":                      "NOSQL",
    "system.directoryservices":            "LDAP",
    "novell.directory.ldap":               "LDAP",
    "system.net.http":                     "REST_OUTBOUND",
    "restsharp":                           "REST_OUTBOUND",
    "refit":                               "REST_OUTBOUND",
    "microsoft.aspnetcore.signalr":        "WEBSOCKET",
    "system.net.websockets":               "WEBSOCKET",
    "azure.storage.blobs":                 "CLOUD_STORAGE",
    "amazon.s3":                           "CLOUD_STORAGE",
    "google.cloud.storage":                "CLOUD_STORAGE",
    "azure.messaging":                     "MESSAGING",
    "rabbitmq.client":                     "MESSAGING",
    "confluentkafka":                      "MESSAGING",
    "masstransit":                         "MESSAGING",
    "microsoft.azure.functions":           "SERVERLESS",
    "amazon.lambda":                       "SERVERLESS",
    "hotchocolate":                        "GRAPHQL",
    "graphql":                             "GRAPHQL",
    "grpc.aspnetcore":                     "GRPC",
    "grpc.core":                           "GRPC",
    "system.servicemodel":                 "SOAP",
    "corewcf":                             "SOAP",
}

# ── Method names to skip in call graph ───────────────────────────────────────
_CALL_SKIP = {
    "ToString", "GetHashCode", "Equals", "GetType",
    "Add", "AddRange", "Remove", "Clear", "Count", "Contains",
    "Where", "Select", "FirstOrDefault", "First", "Single",
    "SingleOrDefault", "Last", "LastOrDefault", "Any", "All",
    "ToList", "ToArray", "ToDictionary", "ToLookup",
    "OrderBy", "OrderByDescending", "GroupBy", "Skip", "Take",
    "Sum", "Average", "Min", "Max", "Aggregate",
    "ForEach", "Join", "Zip",
    "Log", "LogInformation", "LogWarning", "LogError", "LogDebug",
    "WriteLineAsync", "WriteLine", "Write",
    "Ok", "BadRequest", "NotFound", "Created", "NoContent",
    "StatusCode", "Accepted", "Conflict", "Unauthorized", "Forbid",
    "Dispose", "DisposeAsync", "Close",
    "Task", "ConfigureAwait", "Result",
    "Get", "Set", "GetAsync", "SetAsync",
    "Parse", "TryParse", "Format", "Concat", "IsNullOrEmpty",
    "IsNullOrWhiteSpace", "Trim", "ToLower", "ToUpper",
    "Replace", "Split", "Contains", "StartsWith", "EndsWith",
}

# ── Entry-point names to skip ─────────────────────────────────────────────────
_ENTRY_SKIP = {
    "Configure", "ConfigureServices", "Main", "CreateHostBuilder",
    "CreateWebHostBuilder", "BuildWebHost", "OnModelCreating",
    "OnConfiguring", "Dispose", "DisposeAsync",
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _ci(s):
    return s.lower() if s else ""


def _txt(node, code: str) -> str:
    return code[node.start_byte:node.end_byte]


def _strip_string_literal(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    if len(s) >= 2 and s[0] == '@' and s[1] == '"':
        return s[2:-1]
    if s.startswith("$\""):
        return s[2:-1]
    return s

_MODIFIER_RE = re.compile(
    r'\b(public|private|protected|internal|static|async|override|virtual|abstract)\b'
)

def _method_name(name_node, decl_node, code: str) -> str:
    """Extract method name safely.

    tree-sitter byte offsets can be 2 bytes ahead of the actual string
    position (CRLF vs LF mismatch), causing two truncation patterns:
      1. code_block starts mid-modifier  → e.g. 'blic async … Handle(…)'
      2. code_block starts mid-attribute → e.g. 'ttpGet]\n  public … GetX(…)'

    Fix: ignore the first (possibly truncated) line; find the first line
    that contains a real C# modifier keyword, then extract the last
    Identifier( pattern from it — that is always the method name.
    """
    raw = _txt(name_node, code)
    if raw.isidentifier():
        return raw

    decl_text = _txt(decl_node, code)

    # Find the first line that contains a visibility / modifier keyword
    sig_line = None
    for line in decl_text.split('\n'):
        if _MODIFIER_RE.search(line):
            sig_line = line.strip()
            break

    # Fallback: everything before the opening brace
    if not sig_line:
        sig_line = decl_text.split('{')[0].split('\n')[0]

    # Last Identifier( or Identifier<…>( is always the method name
    matches = re.findall(r'\b([A-Za-z_]\w*)\s*(?:<[^>()]*>)?\s*\(', sig_line)
    return matches[-1] if matches else raw


def _ns_to_iam(namespaces: set) -> str | None:
    """Return the first IAM type matched by any using directive."""
    for ns in namespaces:
        ns_lower = _ci(ns)
        for prefix, iam in NAMESPACE_IAM.items():
            if ns_lower.startswith(prefix):
                return iam
    return None


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 0 — FILE-LEVEL NAMESPACE COLLECTION
# ══════════════════════════════════════════════════════════════════════════════

def _collect_namespaces(tree, code: str) -> set:
    """
    Return all namespace strings from `using` directives.

    OPTIMIZED: Uses module-level cached _Q_NAMESPACE query object.
    """
    ns = set()
    cu = QueryCursor(_Q_NAMESPACE)
    for _, m in cu.matches(tree.root_node):
        for n in m.get("using.ns", []):
            ns.add(_txt(n, code))
    return ns


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 0b — CLASS CONTEXT MAP
# ══════════════════════════════════════════════════════════════════════════════

def _collect_class_contexts(tree, code: str) -> list:
    """
    Returns list of:
      { start, end, name, attrs, bases, field_types, iam_fallback }

    OPTIMIZED: Uses module-level cached _Q_CLASS_DECL and _Q_FIELD_TYPE
    query objects instead of compiling new queries on every call.
    """
    cu       = QueryCursor(_Q_CLASS_DECL)
    contexts = []

    for _, m in cu.matches(tree.root_node):
        decl_nodes = m.get("class.decl", [])
        name_nodes = m.get("class.name", [])
        attr_nodes = m.get("class.attr", [])
        base_nodes = m.get("class.base", [])
        body_nodes = m.get("class.body", [])

        if not decl_nodes or not name_nodes:
            continue

        decl = decl_nodes[0]
        body = body_nodes[0] if body_nodes else decl

        attrs = [_ci(_txt(n, code)) for n in attr_nodes]
        bases = [_ci(_txt(n, code)) for n in base_nodes]

        # Field type scan inside body using cached query
        fcu         = QueryCursor(_Q_FIELD_TYPE)
        field_types = set()
        for _, fm in fcu.matches(body):
            for fn in fm.get("field.type", []):
                field_types.add(_ci(_txt(fn, code)))

        # Determine class-level IAM fallback
        iam_fallback = None

        for base in bases:
            if base in BASE_CLASS_IAM:
                iam_fallback = BASE_CLASS_IAM[base]
                break

        if not iam_fallback:
            for ft in field_types:
                for key, iam in FIELD_TYPE_IAM.items():
                    if ft.startswith(key):
                        iam_fallback = iam
                        break
                if iam_fallback:
                    break

        if not iam_fallback:
            if "apicontroller" in attrs or "controller" in attrs:
                iam_fallback = "REST"
            elif "servicecontract" in attrs:
                iam_fallback = "SOAP"
            elif "grpcservice" in attrs:
                iam_fallback = "GRPC"

        contexts.append({
            "start":        decl.start_byte,
            "end":          decl.end_byte,
            "name":         _txt(name_nodes[0], code),
            "attrs":        attrs,
            "bases":        bases,
            "field_types":  field_types,
            "iam_fallback": iam_fallback,
        })

    return contexts


def _build_sorted_ctx(contexts: list) -> list:
    """
    Convert contexts list into a version sorted by start byte,
    enabling O(log N) binary-search lookups in _class_context_for.
    """
    return sorted(contexts, key=lambda c: c["start"])


def _class_context_for(byte_offset: int, sorted_contexts: list) -> dict | None:
    """
    Return the innermost class context that contains byte_offset.

    OPTIMIZED: O(log N) binary search via bisect instead of the original
    O(N) linear scan.  sorted_contexts must be the output of _build_sorted_ctx().
    """
    if not sorted_contexts:
        return None
    starts = [c["start"] for c in sorted_contexts]
    idx    = bisect.bisect_right(starts, byte_offset) - 1
    best   = None
    while idx >= 0:
        ctx = sorted_contexts[idx]
        if ctx["start"] <= byte_offset <= ctx["end"]:
            if best is None or (ctx["end"] - ctx["start"]) < (best["end"] - best["start"]):
                best = ctx
        if ctx["start"] < (best["start"] if best else byte_offset):
            break
        idx -= 1
    return best


# ══════════════════════════════════════════════════════════════════════════════
# CALLED-METHOD EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _extract_called_methods(body_node, code: str) -> list:
    """
    Return unique method call names inside body_node, noise-filtered.

    OPTIMIZED: Uses module-level cached _Q_INVOCATION query object.
    """
    cu    = QueryCursor(_Q_INVOCATION)
    found = set()
    for _, m in cu.matches(body_node):
        for n in m.get("call.name", []):
            name = _txt(n, code)
            if name not in _CALL_SKIP and len(name) > 2:
                found.add(name)
    return list(found)


# ══════════════════════════════════════════════════════════════════════════════
# AUTH HINT COLLECTION
# ══════════════════════════════════════════════════════════════════════════════

def _auth_from_attrs(attr_names: list) -> list:
    """Return auth attribute names using pre-compiled regex (replaces nested loop)."""
    return [a for a in attr_names if _AUTH_HINTS_RE.search(_ci(a))]


def _auth_from_body(body_lower: str) -> list:
    hints = []
    for kw in ["claimsprincipal", "jwtbearer", "authorize", "policy",
               "roles", "apikey", "identity"]:
        if kw in body_lower:
            hints.append(kw)
    return hints


# ══════════════════════════════════════════════════════════════════════════════
# BODY SIGNATURE DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _detect_iam_from_body(body_lower: str) -> str | None:
    for iam_type, sigs in BODY_SIGNATURES.items():
        if any(sig in body_lower for sig in sigs):
            return iam_type
    return None


# ══════════════════════════════════════════════════════════════════════════════
# ATTRIBUTE PARSING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _route_from_attrs(attr_args_nodes: list, code: str) -> str | None:
    """Extract the first string literal from attribute argument lists."""
    for n in attr_args_nodes:
        found = re.findall(r'"([^"]*)"', _txt(n, code))
        if found:
            return found[0]
    return None


def _classify_method_attrs(attr_names: list) -> tuple:
    """
    Given a list of attribute name strings, return (endpoint_type, http_verb)
    or (None, None) if not an IAM entry point via attribute detection.
    """
    for name in attr_names:
        nl   = _ci(name)
        pair = _HTTP_VERB_ATTRS.get(nl)
        if pair:
            return pair
        iam = _FRAMEWORK_ATTRS.get(nl)
        if iam:
            return (iam, None)
    return (None, None)


# ══════════════════════════════════════════════════════════════════════════════
# CALLABLE COLLECTION — produces a flat list of ALL callable units
# ══════════════════════════════════════════════════════════════════════════════

def _collect_all_callables(tree, code: str) -> list:
    """
    Returns list of dicts covering method_declaration and
    local_function_statement (script-style Azure Functions).

    OPTIMIZED: Uses module-level cached _Q_METHOD_DECL and _Q_LOCAL_FN
    query objects instead of compiling new queries on every call.
    """
    callables = []
    seen      = set()

    def _add(name, decl_node, body_node, attr_names, attr_args):
        key = decl_node.start_byte
        if key in seen:
            return
        seen.add(key)
        callables.append({
            "name":            name,
            "start_byte":      decl_node.start_byte,
            "end_byte":        decl_node.end_byte,
            "body_node":       body_node,
            "body_text":       _txt(body_node, code) if body_node else "",
            "code_block":      _txt(decl_node, code),
            "attr_names":      attr_names,
            "attr_args_nodes": attr_args,
        })

    # 1. method_declaration
    cu = QueryCursor(_Q_METHOD_DECL)
    for _, m in cu.matches(tree.root_node):
        decl_nodes = m.get("method.decl", [])
        name_nodes = m.get("method.name", [])
        body_nodes = m.get("method.body", [])
        attr_names = [_txt(n, code) for n in m.get("attr.name", [])]
        attr_args  = m.get("attr.args", [])
        if decl_nodes and name_nodes:
            body = body_nodes[0] if body_nodes else None
            _add(_method_name(name_nodes[0], decl_nodes[0], code), decl_nodes[0], body, attr_names, attr_args)
    # 2. local_function_statement (top-level Azure Functions)
    cu = QueryCursor(_Q_LOCAL_FN)
    for _, m in cu.matches(tree.root_node):
        decl_nodes = m.get("fn.decl", [])
        name_nodes = m.get("fn.name", [])
        body_nodes = m.get("fn.body", [])
        attr_names = [_txt(n, code) for n in m.get("attr.name", [])]
        attr_args  = m.get("attr.args", [])
        if decl_nodes and name_nodes:
            body = body_nodes[0] if body_nodes else None
            _add(_method_name(name_nodes[0], decl_nodes[0], code), decl_nodes[0], body, attr_names, attr_args)

    return callables


# ══════════════════════════════════════════════════════════════════════════════
# MINIMAL API COLLECTION
# ══════════════════════════════════════════════════════════════════════════════

def _collect_minimal_api_entries(tree, code: str, file: str,
                                  namespaces: set) -> list:
    """
    Detect app.MapGet / app.MapPost / … calls and return IAM entry-point dicts
    with inline lambda bodies resolved.

    OPTIMIZED: Uses module-level cached _Q_MINIMAL_API and _Q_LAMBDA_ARG
    query objects instead of compiling new queries on every call.
    """
    cu      = QueryCursor(_Q_MINIMAL_API)
    entries = []
    seen    = set()

    for _, m in cu.matches(tree.root_node):
        verb_nodes = m.get("map.verb", [])
        path_nodes = m.get("map.path", [])
        call_nodes = m.get("map.call", [])

        if not verb_nodes or not path_nodes or not call_nodes:
            continue

        verb_lo = _ci(_txt(verb_nodes[0], code))
        if verb_lo not in _MINIMAL_API_VERBS:
            continue

        http_verb  = _MINIMAL_API_VERBS[verb_lo]
        route      = _strip_string_literal(_txt(path_nodes[0], code))
        call_node  = call_nodes[0]
        code_block = _txt(call_node, code)

        key = (verb_lo, route)
        if key in seen:
            continue
        seen.add(key)

        # Try to find lambda body inside this call expression
        lcu        = QueryCursor(_Q_LAMBDA_ARG)
        body_text  = ""
        called_fns = []
        body_node  = None

        for _, lm in lcu.matches(call_node):
            for bn in lm.get("fn.body", []):
                body_node  = bn
                body_text  = _txt(bn, code)
                called_fns = _extract_called_methods(bn, code)
                break
            if body_node:
                break

        body_lower = _ci(body_text)
        auth_list  = _auth_from_body(body_lower)

        entries.append({
            "name":           f"MapHandler:{http_verb}:{route}",
            "endpoint_type":  "REST",
            "file":           file,
            "route":          route,
            "http_method":    http_verb,
            "code_block":     code_block,
            "auth":           auth_list,
            "called_methods": called_fns,
        })

    return entries


# ══════════════════════════════════════════════════════════════════════════════
# SHARED INTERNAL: AUTH RECORD EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _extract_auth_records(tree, code: str, file: str) -> list:
    """Extract file-level auth attribute records.

    Used by extract_all() and the extract_auth() shim so the query
    only executes once regardless of which path the caller takes.

    OPTIMIZED: Uses module-level cached _Q_ATTRIBUTE query object and
    pre-compiled _AUTH_HINTS_RE regex.
    """
    cu     = QueryCursor(_Q_ATTRIBUTE)
    result = []
    seen   = set()
    for _, m in cu.matches(tree.root_node):
        for n in m.get("attr.name", []):
            name = _txt(n, code)
            if _AUTH_HINTS_RE.search(_ci(name)) and name not in seen:
                seen.add(name)
                result.append({
                    "type":       name,
                    "file":       file,
                    "code_block": f"[{name}]",
                })
    return result


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
      all_methods     – list of all method records (for cross-file registry)
      endpoints       – flat REST endpoint records (backward-compat shim output)
      data_exposures  – flat non-REST exposure records (backward-compat shim output)
      auth            – file-level auth attribute records
    """
    namespaces      = _collect_namespaces(tree, code)
    contexts        = _collect_class_contexts(tree, code)
    sorted_contexts = _build_sorted_ctx(contexts)
    callables       = _collect_all_callables(tree, code)

    entry_points   = []
    all_methods    = []
    endpoints      = []
    data_exposures = []

    seen_ep  = set()   # (name, file, endpoint_type)
    seen_m   = set()   # (file, start_byte)
    # called_methods cache: compute once per declaration, reuse in both outputs
    called_cache = {}  # start_byte → [called_method_names]

    # ── Minimal API (MapGet / MapPost …) ─────────────────────────────────────
    for e in _collect_minimal_api_entries(tree, code, file, namespaces):
        dedup = (e["name"], file, e["endpoint_type"])
        if dedup not in seen_ep:
            seen_ep.add(dedup)
            entry_points.append(e)
            endpoints.append({
                "handler":    e["name"],
                "route":      e["route"],
                "method":     e["http_method"],
                "file":       file,
                "auth":       e["auth"],
                "code_block": e["code_block"],
            })

    # ── Regular methods / local functions ────────────────────────────────────
    for fn in callables:
        name       = fn["name"]
        start      = fn["start_byte"]
        body_text  = fn["body_text"]
        code_block = fn["code_block"]
        attr_names = fn["attr_names"]

        # ── Compute called_methods once per declaration ───────────────────────
        if start not in called_cache:
            called_cache[start] = (
                _extract_called_methods(fn["body_node"], code)
                if fn["body_node"] else []
            )
        called = called_cache[start]

        # ── all_methods record ────────────────────────────────────────────────
        m_key = (file, start)
        if m_key not in seen_m:
            seen_m.add(m_key)
            body_lower_m = _ci(body_text)
            auth_m       = list(set(
                _auth_from_attrs(attr_names) + _auth_from_body(body_lower_m)
            ))
            all_methods.append({
                "name":           name,
                "file":           file,
                "code_block":     code_block,
                "body_text":      body_text,
                "auth":           auth_m,
                "called_methods": called,
            })

        # ── entry-point candidate check ───────────────────────────────────────
        if name in _ENTRY_SKIP:
            continue

        endpoint_type = None
        http_verb     = None
        route         = None
        # Lazy-compute body_lower only when needed for signature scanning
        body_lower    = None

        # 1. Attribute-driven detection
        endpoint_type, http_verb = _classify_method_attrs(attr_names)
        if endpoint_type == "REST":
            route = _route_from_attrs(fn["attr_args_nodes"], code)

        # 2. Body signature scanning (only compute body_lower if needed)
        if not endpoint_type and body_text:
            body_lower    = _ci(body_text)
            endpoint_type = _detect_iam_from_body(body_lower)

        # 3. Class-level fallback
        if not endpoint_type:
            ctx = _class_context_for(start, sorted_contexts)
            if ctx and ctx["iam_fallback"]:
                endpoint_type = ctx["iam_fallback"]

        # 4. Namespace fallback (only if body exists & looks like handler)
        if not endpoint_type and body_text:
            if body_lower is None:
                body_lower = _ci(body_text)
            endpoint_type = _ns_to_iam(namespaces)

        if not endpoint_type:
            continue

        ep_key = (name, file, endpoint_type)
        if ep_key in seen_ep:
            continue
        seen_ep.add(ep_key)

        if body_lower is None:
            body_lower = _ci(body_text)
        auth_list = list(set(
            _auth_from_attrs(attr_names) + _auth_from_body(body_lower)
        ))

        ep_record = {
            "name":           name,
            "endpoint_type":  endpoint_type,
            "file":           file,
            "route":          route,
            "http_method":    http_verb,
            "code_block":     code_block,
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
                "code_block": code_block,
            })
        else:
            data_exposures.append({
                "handler":        name,
                "file":           file,
                "exposure_types": [endpoint_type],
                "code_block":     code_block,
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
    namespaces      = _collect_namespaces(tree, code)
    contexts        = _collect_class_contexts(tree, code)
    sorted_contexts = _build_sorted_ctx(contexts)
    callables       = _collect_all_callables(tree, code)

    entries = []
    seen    = set()

    for e in _collect_minimal_api_entries(tree, code, file, namespaces):
        dedup = (e["name"], file, e["endpoint_type"])
        if dedup not in seen:
            seen.add(dedup)
            entries.append(e)

    for fn in callables:
        name = fn["name"]
        if name in _ENTRY_SKIP:
            continue

        body_text  = fn["body_text"]
        body_lower = _ci(body_text)
        code_block = fn["code_block"]
        attr_names = fn["attr_names"]

        endpoint_type = None
        http_verb     = None
        route         = None

        endpoint_type, http_verb = _classify_method_attrs(attr_names)
        if endpoint_type == "REST":
            route = _route_from_attrs(fn["attr_args_nodes"], code)

        if not endpoint_type and body_lower:
            endpoint_type = _detect_iam_from_body(body_lower)

        if not endpoint_type:
            ctx = _class_context_for(fn["start_byte"], sorted_contexts)
            if ctx and ctx["iam_fallback"]:
                endpoint_type = ctx["iam_fallback"]

        if not endpoint_type and body_lower:
            endpoint_type = _ns_to_iam(namespaces)

        if not endpoint_type:
            continue

        dedup = (name, file, endpoint_type)
        if dedup in seen:
            continue
        seen.add(dedup)

        auth_list = list(set(
            _auth_from_attrs(attr_names) + _auth_from_body(body_lower)
        ))
        called = (_extract_called_methods(fn["body_node"], code)
                  if fn["body_node"] else [])

        entries.append({
            "name":           name,
            "endpoint_type":  endpoint_type,
            "file":           file,
            "route":          route,
            "http_method":    http_verb,
            "code_block":     code_block,
            "auth":           auth_list,
            "called_methods": called,
        })

    return entries


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — ALL-METHODS REGISTRY  (legacy, kept for backward compat)
# ══════════════════════════════════════════════════════════════════════════════

def extract_all_methods(tree, code: str, file: str) -> list:
    """
    Extract EVERY callable unit for the cross-file method registry.

    Kept for backward compatibility.  engine.py now calls extract_all() which
    produces this data without a second tree traversal.
    """
    callables = _collect_all_callables(tree, code)
    methods   = []
    seen      = set()

    for fn in callables:
        dedup = (file, fn["start_byte"])
        if dedup in seen:
            continue
        seen.add(dedup)

        body_lower = _ci(fn["body_text"])
        auth_list  = list(set(
            _auth_from_attrs(fn["attr_names"]) + _auth_from_body(body_lower)
        ))
        called = (_extract_called_methods(fn["body_node"], code)
                  if fn["body_node"] else [])

        methods.append({
            "name":           fn["name"],
            "file":           file,
            "code_block":     fn["code_block"],
            "body_text":      fn["body_text"],
            "auth":           auth_list,
            "called_methods": called,
        })

    return methods


# ══════════════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY SHIMS
# ══════════════════════════════════════════════════════════════════════════════

def extract_endpoints(tree, code: str, file: str) -> list:
    """Shim — flat REST endpoint dicts for exposure_map backward compat."""
    return extract_all(tree, code, file)["endpoints"]


def extract_auth(tree, code: str, file: str) -> list:
    """Shim — file-level auth attribute records."""
    return _extract_auth_records(tree, code, file)


def extract_data_exposures(tree, code: str, file: str) -> list:
    """Shim — non-REST entry points as data_exposure dicts."""
    return extract_all(tree, code, file)["data_exposures"]