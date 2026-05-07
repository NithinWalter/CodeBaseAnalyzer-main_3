"""
extractor.py  (languages/python)
---------------------------------
Phase 1  – extract_iam_entry_points()
    Scans every function/method in the codebase and returns only those that
    are IAM-consumable data-exposing entry points.

Phase 2  – extract_all_methods()
    Returns EVERY function/method in the file for the cross-file method
    registry used by the call-graph builder.

Phase 3  – extract_all()  ← PRIMARY ENTRY POINT (new)
    Single tree pass that produces entry_points, all_methods, endpoints,
    data_exposures, and auth in one shot.  engine.py uses this to avoid
    the 3× re-extraction that the legacy shims caused.
"""

import bisect
import re

from tree_sitter import QueryCursor
from .parser import PYTHON_LANGUAGE
from . import rules
from core.models import create_auth


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL QUERY CACHE
# Query compilation is expensive (string parsing + tree-sitter compile step).
# Build each query once at import time and reuse the compiled object.
# QueryCursor is cheap and IS created per-call (it tracks match state).
# ══════════════════════════════════════════════════════════════════════════════

_Q_CLASS_WITH_BASES = rules.class_with_bases_query(PYTHON_LANGUAGE)
_Q_CLASS_DEF        = rules.class_definition_query(PYTHON_LANGUAGE)
_Q_DECORATED_FN     = rules.decorated_function_query(PYTHON_LANGUAGE)
_Q_FULL_FN          = rules.full_function_query(PYTHON_LANGUAGE)
_Q_CALL_EXPR        = rules.call_expression_query(PYTHON_LANGUAGE)


# ══════════════════════════════════════════════════════════════════════════════
# HTTP VERB ROUTING PATTERNS
# ══════════════════════════════════════════════════════════════════════════════

# Maps lowercased decorator token → (endpoint_type, http_verb)
REST_DECORATOR_VERB_MAP = {
    # FastAPI / Starlette
    ".get(":     ("REST", "GET"),
    ".post(":    ("REST", "POST"),
    ".put(":     ("REST", "PUT"),
    ".delete(":  ("REST", "DELETE"),
    ".patch(":   ("REST", "PATCH"),
    ".head(":    ("REST", "HEAD"),
    ".options(": ("REST", "OPTIONS"),
    # Falcon / Hapi style
    ".on_get":   ("REST", "GET"),
    ".on_post":  ("REST", "POST"),
    ".on_put":   ("REST", "PUT"),
    ".on_delete":("REST", "DELETE"),
    ".on_patch": ("REST", "PATCH"),
}

# CBV HTTP method names (Django/DRF/Flask/Tornado)
CBV_HTTP_METHODS = {"get", "post", "put", "patch", "delete",
                    "head", "options", "on_get", "on_post",
                    "on_put", "on_delete", "on_patch"}

# ══════════════════════════════════════════════════════════════════════════════
# AUTH HINTS
# ══════════════════════════════════════════════════════════════════════════════

AUTH_HINTS = {
    # Django
    "login_required", "permission_required", "staff_member_required",
    "user_passes_test", "superuser_required",
    # DRF
    "authentication_classes", "permission_classes", "isauthenticated",
    "isadminuser", "isauthenticatedorreadonly", "tokenauthentication",
    "sessionauthentication", "basicauthentication",
    # Flask / Flask-Login / Flask-JWT
    "jwt_required", "fresh_jwt_required",
    "jwt_optional", "roles_required", "roles_accepted",
    # FastAPI
    "get_current_user", "get_current_active_user", "oauth2_scheme",
    "depends", "security",
    # Generic
    "requires_auth", "authenticated", "auth_required",
    "require_permissions", "has_permission", "token_required",
    "oidc_exempt", "requires_login", "check_permissions",
}

# Pre-compiled regex for fast auth hint matching (replaces O(N×H) nested loop)
_AUTH_HINTS_RE = re.compile(
    "|".join(re.escape(h) for h in AUTH_HINTS), re.IGNORECASE
)

# ══════════════════════════════════════════════════════════════════════════════
# CLASS BASE HINTS  → endpoint_type
# ══════════════════════════════════════════════════════════════════════════════

CLASS_BASE_IAM = {
    # DRF
    "apiview":                "REST",
    "genericapiview":         "REST",
    "listapiview":            "REST",
    "createapiview":          "REST",
    "retrieveapiview":        "REST",
    "updateapiview":          "REST",
    "destroyapiview":         "REST",
    "listcreateapiview":      "REST",
    "retrieveupdateapiview":  "REST",
    "retrievedestroyapiview": "REST",
    "retrieveupdatedestroyapiview": "REST",
    "viewset":                "REST",
    "modelviewset":           "REST",
    "readonlymodelviewset":   "REST",
    # Django CBV
    "view":                   "REST",
    "templateview":           "REST",
    "listview":               "REST",
    "detailview":             "REST",
    "createview":             "REST",
    "updateview":             "REST",
    "deleteview":             "REST",
    "formview":               "REST",
    # Flask
    "methodview":             "REST",
    # Tornado
    "requesthandler":         "REST",
    # aiohttp
    "web.view":               "REST",
    # Falcon
    "resource":               "REST",
    # gRPC
    "servicerbase":           "GRPC",
    "servicer":               "GRPC",
    # GraphQL (graphene)
    "objecttype":             "GRAPHQL",
    "mutation":               "GRAPHQL",
    "query":                  "GRAPHQL",
    # Spyne (SOAP)
    "servicebase":            "SOAP",
    "complexmodel":           "SOAP",
}

# ══════════════════════════════════════════════════════════════════════════════
# METHOD ANNOTATION HINTS  → endpoint_type
# ══════════════════════════════════════════════════════════════════════════════

METHOD_DEC_IAM = {
    # FastAPI / Starlette explicit
    "app.get":        "REST",  "router.get":    "REST",
    "app.post":       "REST",  "router.post":   "REST",
    "app.put":        "REST",  "router.put":    "REST",
    "app.delete":     "REST",  "router.delete": "REST",
    "app.patch":      "REST",  "router.patch":  "REST",
    "blueprint.route":"REST",  "app.route":     "REST",
    # Flask blueprint / app
    "bp.route":       "REST",  "blueprint.get": "REST",
    # DRF @api_view
    "api_view":       "REST",
    # Django @require_http_methods
    "require_http_methods": "REST",
    "require_GET":    "REST",  "require_POST":  "REST",
    # GraphQL
    "strawberry.field":       "GRAPHQL",
    "strawberry.mutation":    "GRAPHQL",
    "strawberry.subscription":"GRAPHQL",
    "graphql_field":          "GRAPHQL",
    "resolver":               "GRAPHQL",
    # Celery / messaging
    "shared_task":     "MESSAGING",
    "app.task":        "MESSAGING",
    "celery.task":     "MESSAGING",
    "task":            "MESSAGING",
    # WebSocket
    "websocket_route": "WEBSOCKET",
    "on_event":        "WEBSOCKET",
}

# ══════════════════════════════════════════════════════════════════════════════
# BODY SIGNATURE TABLES  (case-insensitive token matching)
# ══════════════════════════════════════════════════════════════════════════════

BODY_SIGNATURES = {

    # ── REST APIs ─────────────────────────────────────────────────────────────
    "REST": [
        # FastAPI response classes
        "jsonresponse(", "htmlresponse(", "streamingresponse(",
        "redirectresponse(", "response(status_code",
        # Django
        "httpresponse(", "render(request", "jsonresponse(",
        "rest_framework.response", "response.response(",
        # Flask
        "make_response(", "flask.jsonify(", "jsonify(",
        # Tornado
        "self.write(", "self.finish(", "self.render(",
        # Falcon
        "resp.media", "resp.text", "resp.body",
        # Aiohttp
        "web.response(", "web.json_response(",
    ],

    # ── GraphQL ───────────────────────────────────────────────────────────────
    "GRAPHQL": [
        # graphene
        "graphene.objecttype", "graphene.mutation", "graphene.schema",
        "graphene.field(", "graphene.list(", "graphene.string(",
        "graphene.int(", "resolve_", "graphql_schema",
        # strawberry
        "strawberry.type", "strawberry.field", "strawberry.schema",
        "strawberry.mutation", "strawberry.query", "strawberry.subscription",
        "info.context", "strawberry_django",
        # ariadne
        "make_executable_schema(", "querytype(", "mutationtype(",
        "subscriptiontype(", "fallbackresolvers", "objecttype(",
        # graphql-core
        "graphqlschema(", "graphqlobjecttype(", "graphqlenumtype(",
        "schema.execute(", "schema.execute_sync(",
        # Hasura / generic
        "graphql_mutation", "graphql_query",
    ],

    # ── gRPC ─────────────────────────────────────────────────────────────────
    "GRPC": [
        # grpcio server
        "grpc.server(", "grpc.insecure_channel(", "grpc.secure_channel(",
        "server.add_insecure_port(", "server.add_servicer(",
        "add_servicer_to_server(", "grpc.channel_ready_future(",
        # generated stub patterns
        "_pb2_grpc", "_pb2.request", "servicer_context",
        "context.set_code(", "context.set_details(",
        "context.abort(", "context.send_initial_metadata(",
        # streaming
        "request_iterator", "response_iterator",
        # client stubs
        "stub.", "channel.unary_unary(", "channel.unary_stream(",
        "grpc.statuscode", "grpcio",
    ],

    # ── SOAP / XML Web Services ───────────────────────────────────────────────
    "SOAP": [
        # spyne
        "spyne.service", "servicebase", "rpc(", "srpc(",
        "soapui", "soap11(", "soap12(",
        "complexmodel", "array(", "unicode(", "integer(",
        "spyne.model", "spyne.protocol",
        "http.httptransport(", "wsgiapplication(",
        # zeep (client)
        "zeep.client(", "client.service.", "client.get_service(",
        "zeep.wsdl", "zeep.transport",
        # suds
        "suds.client(", "suds.service",
        # generic SOAP patterns
        "wsdl", "soapaction", "soapenvelope", "soapbody",
        "envelope.body", "xml.soapns",
    ],

    # ── SQL / Direct DB ───────────────────────────────────────────────────────
    "SQL": [
        # psycopg2
        "psycopg2.connect(", "conn.cursor(", "cursor.execute(",
        "cursor.fetchall(", "cursor.fetchone(", "cursor.fetchmany(",
        "cursor.mogrify(", "psycopg2.extras",
        # mysql-connector
        "mysql.connector.connect(", "pymysql.connect(",
        "mysql_cursor.execute(", "connection.cursor(",
        # sqlite3
        "sqlite3.connect(", "sqlite_cursor.execute(",
        "con.execute(", ":memory:",
        # cx_Oracle / oracledb
        "cx_oracle.connect(", "oracledb.connect(",
        "oracle_cursor.execute(",
        # pyodbc / generic
        "pyodbc.connect(", "odbc.connect(",
        "conn.execute(", "db.execute(",
        # raw SQL strings
        "select * from", "select ", "insert into",
        "update set", "delete from", "exec ", "sp_",
        "text(\"select", "text('select",
    ],

    # ── ORM ───────────────────────────────────────────────────────────────────
    "ORM": [
        # SQLAlchemy Core/ORM
        "session.query(", "session.execute(", "db.session",
        "session.add(", "session.delete(", "session.commit(",
        "session.flush(", "session.merge(",
        "engine.execute(", "engine.connect(",
        "create_engine(", "sessionmaker(", "scoped_session(",
        "declarative_base(", "mapped_column(", "relationship(",
        "select(", "insert(", "update(", "delete(", "text(",
        "table(", "column(", "metadata(",
        # SQLAlchemy 2.x
        "async_session", "asyncsession", "asyncengine",
        "select(model.", "scalars(", "scalar_one(",
        # Django ORM
        "objects.filter(", "objects.get(", "objects.all(",
        "objects.create(", "objects.update(", "objects.delete(",
        "objects.annotate(", "objects.aggregate(",
        ".save()", ".delete()", ".raw(",
        "get_or_create(", "update_or_create(", "bulk_create(",
        "bulk_update(", "values_list(", "values(",
        # Tortoise ORM
        "await model.filter(", "await model.get(",
        "tortoise.models", "fields.charfield",
        # Peewee
        ".select().where(", "peewee.model", "modelselect(",
        "database.execute_sql(",
        # databases (async)
        "await database.fetch_all(", "await database.execute(",
    ],

    # ── LDAP ─────────────────────────────────────────────────────────────────
    "LDAP": [
        # ldap3
        "ldap3.connection(", "conn.search(", "conn.bind(",
        "conn.add(", "conn.modify(", "conn.delete(",
        "conn.entries", "ldap3.server(", "ldap3.subtree",
        "ldap3.level", "ldap3.base", "connection(server",
        "server(host", "entry_dn", "entry_attributes",
        # python-ldap
        "ldap.initialize(", "l.search_s(", "l.search_ext(",
        "l.bind_s(", "l.add_s(", "l.modify_s(",
        "l.delete_s(", "ldap.scope_subtree",
        "ldap.moddn_s(", "ldap.passwd_s(",
        # django-auth-ldap
        "ldapbackend", "ldapsearch(", "auth_ldap",
        "ldap_user", "ldap_username_attr",
        # generic LDAP patterns
        "cn=", "dc=", "ou=", "dn=",
        "objectclass=", "uniquemember",
    ],

    # ── Active Directory ──────────────────────────────────────────────────────
    "ACTIVE_DIRECTORY": [
        # ldap3 AD-specific
        "samaccountname", "useraccountcontrol", "distinguishedname",
        "objectclass=user", "objectclass=person", "objectclass=group",
        "cn=users,dc=", "memberof", "primarygroupid",
        "ldap://", "ldaps://", "activedirectory",
        # pyad
        "pyad.aduser", "pyad.adgroup", "pyad.adquery(",
        "pyad.adcontainer", "adobject.from_dn(",
        # impacket
        "impacket.ldap", "msldap",
        # generic AD patterns
        "domain\\\\", "domain/", "kerberos", "ntlm",
        "gssapi", "sasl_credentials",
    ],

    # ── CSV File Export ───────────────────────────────────────────────────────
    "CSV": [
        "csv.writer(", "csv.dictwriter(", "csv.reader(",
        "csv.dictreader(", "csvwriter.writerow(",
        "csvwriter.writerows(", "csv.writeheader(",
        "to_csv(", "pandas.dataframe.to_csv(",
        "df.to_csv(", "export_csv(", "write_csv(",
        "csvresponse(", "streaming_csv", "unicodecsv",
        "csvformat", "flatfileexporter",
    ],

    # ── JSON File Export ──────────────────────────────────────────────────────
    "JSON_EXPORT": [
        "json.dump(open(", "json.dump(f,", "json.dump(file",
        "json.dumps(users", "json.dumps(data",
        "with open(.*\\.json.*) as f",
        "f.write(json.dumps(", "f.write(json.dump(",
        "export_json(", "jsonlines.open(",
        "ndjson.dump(", "print(json.dumps(",  # CLI/script exposure
        "sys.stdout.write(json", "click.echo(json",
    ],

    # ── XML Export ────────────────────────────────────────────────────────────
    "XML": [
        "xml.etree.elementtree", "et.tostring(", "et.parse(",
        "elementtree.write(", "etree.tostring(",
        "lxml.etree", "lxml.objectify",
        "xmltodict.unparse(", "dicttoxml(",
        "minidom.toprettyxml(", "parsestring(",
        "xml.dom.minidom", "xml.sax",
        "generate_xml(", "export_xml(",
        "serialize_xml(", "xmlresponse(",
    ],

    # ── Excel Export ──────────────────────────────────────────────────────────
    "EXCEL": [
        "openpyxl.workbook(", "workbook.save(",
        "xlsxwriter.workbook(", "worksheet.write(",
        "xlwt.workbook(", "xlrd.open_workbook(",
        "df.to_excel(", "pandas.to_excel(",
        "xlsxresponse(", "openpyxl.load_workbook(",
        "workbook.active", "ws.append(",
        "export_excel(", "write_excel(",
    ],

    # ── HTTP Clients / Outbound REST ──────────────────────────────────────────
    "REST_OUTBOUND": [
        # requests
        "requests.get(", "requests.post(", "requests.put(",
        "requests.delete(", "requests.patch(", "requests.session(",
        "session.get(", "session.post(", "session.request(",
        # httpx
        "httpx.get(", "httpx.post(", "httpx.client(",
        "httpx.asyncclient(", "async_client.get(",
        "httpx.put(", "httpx.delete(",
        # aiohttp
        "aiohttp.clientsession(", "clientsession(",
        "async with aiohttp",
        # urllib
        "urllib.request.urlopen(", "urllib.request.urlretrieve(",
        "http.client.httpconnection(", "http.client.httpsconnection(",
        # generic
        "api_client.get(", "api_client.post(",
    ],

    # ── WebSocket ─────────────────────────────────────────────────────────────
    "WEBSOCKET": [
        # websockets library
        "websockets.serve(", "websockets.connect(",
        "await websocket.send(", "await websocket.recv(",
        "websocket.send_text(", "websocket.send_bytes(",
        # FastAPI WebSocket
        "websocket.accept(", "await websocket.receive_text(",
        "await websocket.receive_json(",
        # Socket.IO
        "socketio.emit(", "sio.emit(", "@sio.on(",
        "@socketio.on(", "socketio.server(",
        # Django channels
        "channel_layer", "async_to_sync(channel_layer",
        "websocketconsumer", "asyncwebsocketconsumer",
        "self.channel_name", "self.channel_layer.group_send(",
        # Tornado
        "websockethandler", "self.write_message(",
        "tornado.websocket",
    ],

    # ── Cloud Storage / Object Storage ────────────────────────────────────────
    "FILE_STORAGE": [
        # AWS S3
        "boto3.client('s3')", 'boto3.client("s3")',
        "boto3.resource('s3')", 's3.upload_file(',
        "s3.put_object(", "s3.get_object(",
        "s3.download_file(", "s3_client.upload(",
        # Azure Blob
        "blobserviceclient(", "blob_client.upload_blob(",
        "blob_client.download_blob(", "containerclient(",
        "azure.storage.blob",
        # GCP Storage
        "storage.client(", "bucket.blob(", "blob.upload_from_file(",
        "blob.upload_from_string(", "blob.download_as_bytes(",
        "google.cloud.storage",
        # MinIO
        "minio.minio(", "minio_client.put_object(",
        "minio_client.get_object(",
        # Generic
        "cloudinary.uploader", "s3transfer",
    ],

    # ── Messaging / Celery / Event-driven ────────────────────────────────────
    "MESSAGING": [
        # Celery
        "@shared_task", "@app.task", "@celery.task",
        ".delay(", ".apply_async(", "send_task(",
        "celery.beat", "celery.schedules",
        # RabbitMQ / pika
        "pika.blockingconnection(", "channel.basic_publish(",
        "channel.basic_consume(", "channel.queue_declare(",
        # Kafka
        "kafkaproducer(", "kafkaconsumer(", "confluent_kafka",
        "producer.send(", "consumer.poll(",
        "aiokafka.aioproduce", "aiokafka.aioconsume",
        # AWS SQS / SNS
        "boto3.client('sqs')", 'boto3.client("sqs")',
        "sqs.send_message(", "sns.publish(",
        "sqs.receive_message(",
        # Django channels (messaging part)
        "channel_layer.group_send(", "channel_layer.send(",
    ],

    # ── Search Engines ────────────────────────────────────────────────────────
    "SEARCH_ENGINE": [
        # Elasticsearch
        "elasticsearch.elasticsearch(", "es.search(",
        "es.index(", "es.delete(", "es.update(",
        "elasticsearch.helpers", "asyncelasticsearch(",
        "elastic_transport", "elasticsearch7",
        # OpenSearch
        "opensearch(", "opensearchclient(",
        "opensearch.search(", "opensearch.index(",
        # Solr
        "pysolr.solr(", "solr.search(",
    ],

    # ── Webhook (Push-based) ──────────────────────────────────────────────────
    "WEBHOOK": [
        "webhook_url", "webhook_payload", "dispatch_webhook(",
        "send_webhook(", "trigger_webhook(", "webhook.send(",
        "requests.post(.*hook", "hmac.new(.*webhook",
        "x-hub-signature", "x-webhook-signature",
        "webhook_secret", "validate_webhook(",
    ],
}

# ── Field / variable type hints ───────────────────────────────────────────────
CLASS_FIELD_HINTS = {
    "SQL":           ["connection", "cursor", "engine", "psycopg2",
                      "mysql.connector", "sqlite3", "cx_oracle"],
    "ORM":           ["session", "db.session", "sessionlocal",
                      "asyncsession", "scoped_session"],
    "LDAP":          ["ldap3.connection", "ldap.initialize", "ldapconn"],
    "GRPC":          ["grpc.channel", "grpc.stub", "grpcchannel"],
    "REST_OUTBOUND": ["requests.session", "httpx.client",
                      "aiohttp.clientsession"],
    "MESSAGING":     ["kafkaproducer", "kafkaconsumer", "pika.channel",
                      "celery.app"],
    "FILE_STORAGE":  ["boto3.client", "blobserviceclient", "storage.client"],
}

# ── Functions to always skip ──────────────────────────────────────────────────
_SKIP_METHODS = {
    "__init__", "__str__", "__repr__", "__len__", "__eq__", "__hash__",
    "__del__", "__enter__", "__exit__", "__iter__", "__next__",
    "__getitem__", "__setitem__", "__contains__", "__bool__",
    "setUp", "tearDown",   # test lifecycle
}

# ── Call graph noise to filter ────────────────────────────────────────────────
_CALL_SKIP = {
    # builtins
    "print", "len", "range", "enumerate", "zip", "map", "filter",
    "list", "dict", "set", "tuple", "str", "int", "float", "bool",
    "type", "isinstance", "issubclass", "hasattr", "getattr", "setattr",
    "open", "super", "sorted", "reversed", "sum", "min", "max",
    "any", "all", "next", "iter", "round", "abs", "id",
    # logging
    "logger", "logging", "debug", "info", "warning", "error", "critical",
    # exception
    "raise", "assert", "exit", "quit",
    # common methods
    "append", "extend", "update", "pop", "get", "keys", "values",
    "items", "join", "split", "strip", "replace", "format", "encode",
    "decode", "lower", "upper", "startswith", "endswith",
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _ci(s):
    return s.lower() if s else ""


def _txt(node, code):
    return code[node.start_byte:node.end_byte]


def _extract_route_from_decorator(dec_text):
    """Extract URL route string from a routing decorator."""
    match = re.search(r"""[\"'](/?[\w\-\{\}<>:/]+)[\"']""", dec_text)
    if match:
        path = match.group(1)
        if "/" in path:
            return path
    return "/"


def _extract_http_verb_from_decorator(dec_text):
    """Return (endpoint_type, http_verb) from a decorator string, or None."""
    dec_lower = _ci(dec_text)

    # FastAPI / Starlette / aiohttp etc.
    for pattern, pair in REST_DECORATOR_VERB_MAP.items():
        if pattern in dec_lower:
            return pair

    # Flask / Django @app.route / @bp.route / @app.add_url_rule
    if "route(" in dec_lower or "url_rule" in dec_lower:
        methods_match = re.search(
            r'methods\s*=\s*\[([^\]]+)\]', dec_text, re.IGNORECASE
        )
        if methods_match:
            raw = methods_match.group(1)
            methods = re.findall(r"['\"]([A-Z]+)['\"]", raw.upper())
            verb = ",".join(methods) if methods else "REQUEST"
        else:
            verb = "REQUEST"
        return ("REST", verb)

    # DRF @api_view
    if "api_view(" in dec_lower:
        methods_match = re.search(r'\[([^\]]+)\]', dec_text)
        if methods_match:
            raw = methods_match.group(1)
            methods = re.findall(r"['\"]([A-Z]+)['\"]", raw.upper())
            verb = ",".join(methods) if methods else "REQUEST"
        else:
            verb = "REQUEST"
        return ("REST", verb)

    # @require_http_methods
    if "require_http_methods(" in dec_lower or "require_get" in dec_lower:
        return ("REST", "GET")
    if "require_post" in dec_lower:
        return ("REST", "POST")

    return None


def _detect_iam_type_from_annotations(dec_texts):
    """Return endpoint_type from decorator texts, or None."""
    for dec in dec_texts:
        dec_lower = _ci(dec)
        for pattern, etype in METHOD_DEC_IAM.items():
            if _ci(pattern) in dec_lower:
                return etype
    return None


def _detect_iam_type_from_body(body_lower):
    """Return first matching IAM type from body signatures, or None."""
    for iam_type, sigs in BODY_SIGNATURES.items():
        if any(sig in body_lower for sig in sigs):
            return iam_type
    return None


def _get_auth_decorators(dec_texts):
    """Return auth decorator texts from the list.

    Uses a pre-compiled regex instead of the original O(N×H) nested loop.
    """
    return [d for d in dec_texts if _AUTH_HINTS_RE.search(d)]


def _build_class_context(tree, code):
    """
    Build { (start_byte, end_byte): ctx_dict } for every class.
    ctx_dict: { name, bases, decorators, route_prefix }

    OPTIMIZED: Uses module-level cached query objects instead of
    compiling a new Query on every call.
    """
    ctx = {}

    cu = QueryCursor(_Q_CLASS_WITH_BASES)
    for _, m in cu.matches(tree.root_node):
        decl  = m.get("class.decl",  [])
        name  = m.get("class.name",  [])
        bases = m.get("class.bases", [])
        if not decl:
            continue
        key = (decl[0].start_byte, decl[0].end_byte)
        ctx[key] = {
            "name":         _txt(name[0], code)  if name  else "",
            "bases":        _txt(bases[0], code) if bases else "",
            "decorators":   [],
            "route_prefix": "",
        }

    cu = QueryCursor(_Q_CLASS_DEF)
    for _, m in cu.matches(tree.root_node):
        decl = m.get("class.decl", [])
        name = m.get("class.name", [])
        if not decl:
            continue
        key = (decl[0].start_byte, decl[0].end_byte)
        if key not in ctx:
            ctx[key] = {
                "name":         _txt(name[0], code) if name else "",
                "bases":        "",
                "decorators":   [],
                "route_prefix": "",
            }

    return ctx


def _build_sorted_ctx(ctx_dict):
    """
    Convert the class context dict into a sorted list of (start, end, ctx)
    tuples, enabling O(log N) binary-search lookups in _find_class_ctx.
    """
    return sorted(
        [(s, e, c) for (s, e), c in ctx_dict.items()],
        key=lambda x: x[0],
    )


def _find_class_ctx(decl_start, sorted_ctx):
    """
    Return the class context dict for the class that contains decl_start.

    OPTIMIZED: O(log N) binary search via bisect instead of the original
    O(N) linear scan.  sorted_ctx must be the output of _build_sorted_ctx().
    """
    if not sorted_ctx:
        return {}
    starts = [x[0] for x in sorted_ctx]
    idx = bisect.bisect_right(starts, decl_start) - 1
    while idx >= 0:
        s, e, c = sorted_ctx[idx]
        if decl_start <= e:
            return c
        idx -= 1
    return {}


def _class_iam_type(ctx):
    """Resolve IAM type from class-level context."""
    bases_lower = _ci(ctx.get("bases", ""))
    for hint, etype in CLASS_BASE_IAM.items():
        if hint in bases_lower:
            return etype
    return None


def _extract_called_functions(body_node, code):
    """
    Extract function/method names called inside body_node.
    Filters noise using _CALL_SKIP.

    OPTIMIZED: Uses the module-level cached _Q_CALL_EXPR query object
    instead of compiling a new Query on every call.
    """
    cu = QueryCursor(_Q_CALL_EXPR)   # cursor is cheap; query object is cached
    found = set()
    for _, m in cu.matches(body_node):
        for n in m.get("call.name", []):
            name = code[n.start_byte:n.end_byte]
            if name not in _CALL_SKIP and len(name) > 2:
                found.add(name)
    return list(found)


def _build_method_ann_map(tree, code):
    """
    Scan decorated functions once and return:
      { func_def.start_byte: (decorated_def_text, [decorator_text, ...]) }

    Shared by extract_all, extract_iam_entry_points, and extract_all_methods
    so the decorated-function query only runs once per file.

    OPTIMIZED: Uses module-level cached _Q_DECORATED_FN query object.
    """
    dec_map = {}
    cu = QueryCursor(_Q_DECORATED_FN)
    for _, m in cu.matches(tree.root_node):
        func_def  = m.get("func.def",  [])
        func_decl = m.get("func.decl", [])
        decs      = m.get("decorator", [])
        if func_def and func_decl:
            key = func_def[0].start_byte
            dec_map[key] = (
                _txt(func_decl[0], code),
                [_txt(d, code) for d in decs],
            )
    return dec_map


# ══════════════════════════════════════════════════════════════════════════════
# SHARED INTERNAL: AUTH RECORD EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _extract_auth_records(tree, code, file):
    """Extract file-level auth decorator records.

    Used by extract_all() and the extract_auth() shim so the query
    only executes once regardless of which path the caller takes.
    """
    auth = []
    seen = set()
    cu   = QueryCursor(_Q_DECORATED_FN)
    for _, m in cu.matches(tree.root_node):
        for d in m.get("decorator", []):
            text = _txt(d, code)
            if _AUTH_HINTS_RE.search(text):
                key = text.strip()
                if key not in seen:
                    seen.add(key)
                    auth.append(create_auth(key, file, code_block=text))
    if "bearer" in _ci(code) or "jwt" in _ci(code):
        auth.append(create_auth("TokenBased", file))
    return auth


# ══════════════════════════════════════════════════════════════════════════════
# PRIMARY ENTRY POINT — extract_all()
# ══════════════════════════════════════════════════════════════════════════════

def extract_all(tree, code, file):
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
      auth            – file-level auth decorator records
    """
    class_ctx  = _build_class_context(tree, code)
    sorted_ctx = _build_sorted_ctx(class_ctx)
    dec_map    = _build_method_ann_map(tree, code)

    entry_points   = []
    all_methods    = []
    endpoints      = []
    data_exposures = []

    seen_ep  = set()   # (func_name, file, endpoint_type)
    seen_m   = set()   # (file, decl_start)
    # called_methods cache: compute once per declaration, reuse in both outputs
    called_cache = {}  # decl_start → [called_function_names]

    cu = QueryCursor(_Q_FULL_FN)
    for _, m in cu.matches(tree.root_node):
        name_nodes = m.get("func.name", [])
        body_nodes = m.get("func.body", [])
        decl_nodes = m.get("func.decl", [])
        if not name_nodes or not body_nodes or not decl_nodes:
            continue

        decl_start = decl_nodes[0].start_byte
        func_name  = _txt(name_nodes[0], code)
        body_node  = body_nodes[0]

        decorated_info = dec_map.get(decl_start)
        code_block = decorated_info[0] if decorated_info else _txt(decl_nodes[0], code)
        dec_texts  = decorated_info[1] if decorated_info else []

        ctx       = _find_class_ctx(decl_start, sorted_ctx)
        class_iam = _class_iam_type(ctx)

        # ── Compute called_methods once per declaration ───────────────────────
        if decl_start not in called_cache:
            called_cache[decl_start] = _extract_called_functions(body_node, code)
        called = called_cache[decl_start]

        # ── all_methods record ────────────────────────────────────────────────
        m_key = (file, decl_start)
        if m_key not in seen_m:
            seen_m.add(m_key)
            all_methods.append({
                "name":           func_name,
                "file":           file,
                "class_name":     ctx.get("name", ""),
                "code_block":     code_block,
                "body_text":      _txt(body_node, code),
                "auth":           _get_auth_decorators(dec_texts),
                "called_methods": called,
            })

        # ── entry-point candidate check ───────────────────────────────────────
        if func_name in _SKIP_METHODS:
            continue

        endpoint_type = None
        http_method   = None
        route         = None
        # Lazy-compute body_lower only when needed for signature scanning
        body_lower    = None

        # 1. REST verb from decorator
        for dec in dec_texts:
            pair = _extract_http_verb_from_decorator(dec)
            if pair:
                endpoint_type, http_method = pair
                route = _extract_route_from_decorator(dec)
                break

        # 2. CBV HTTP method name (get/post/put/delete inside a view class)
        if not endpoint_type and func_name.lower() in CBV_HTTP_METHODS:
            if class_iam == "REST" or (class_iam is None and
               any(b in _ci(ctx.get("bases", ""))
                   for b in ("view", "handler", "resource"))):
                endpoint_type = "REST"
                http_method   = func_name.upper()

        # 3. Non-REST annotation hint
        if not endpoint_type:
            endpoint_type = _detect_iam_type_from_annotations(dec_texts)

        # 4. Body signature scanning (only compute body_lower if needed)
        if not endpoint_type:
            body_lower    = _txt(body_node, code).lower()
            endpoint_type = _detect_iam_type_from_body(body_lower)

        # 5. Class-level fallback
        if not endpoint_type:
            endpoint_type = class_iam

        if not endpoint_type:
            continue

        ep_key = (func_name, file, endpoint_type)
        if ep_key in seen_ep:
            continue
        seen_ep.add(ep_key)

        auth_anns    = _get_auth_decorators(dec_texts)
        actual_route = route if endpoint_type == "REST" else None

        ep_record = {
            "name":           func_name,
            "endpoint_type":  endpoint_type,
            "file":           file,
            "route":          actual_route,
            "http_method":    http_method,
            "code_block":     code_block,
            "auth":           auth_anns,
            "called_methods": called,
        }
        entry_points.append(ep_record)

        # ── Derive flat records in the same pass (avoids re-extraction) ───────
        if endpoint_type == "REST":
            endpoints.append({
                "handler":    func_name,
                "route":      route or "/",
                "method":     http_method or "REST",
                "file":       file,
                "auth":       auth_anns,
                "code_block": code_block,
            })
        else:
            data_exposures.append({
                "handler":        func_name,
                "file":           file,
                "exposure_types": [endpoint_type],
                "code_block":     code_block,
                "auth":           [create_auth(a, file, code_block=a)
                                   for a in auth_anns],
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
# PHASE 1 – IAM ENTRY POINT EXTRACTION  (legacy, kept for backward compat)
# ══════════════════════════════════════════════════════════════════════════════

def extract_iam_entry_points(tree, code, file):
    """
    Scan every function/method and return only IAM-consumable entry points.

    Kept for backward compatibility.  engine.py now calls extract_all() which
    is faster.  This function is still correct and uses cached query objects.
    """
    class_ctx  = _build_class_context(tree, code)
    sorted_ctx = _build_sorted_ctx(class_ctx)
    dec_map    = _build_method_ann_map(tree, code)

    entries = []
    seen    = set()

    cu = QueryCursor(_Q_FULL_FN)
    for _, m in cu.matches(tree.root_node):
        name_nodes = m.get("func.name", [])
        body_nodes = m.get("func.body", [])
        decl_nodes = m.get("func.decl", [])
        if not name_nodes or not body_nodes or not decl_nodes:
            continue

        func_name  = _txt(name_nodes[0], code)
        if func_name in _SKIP_METHODS:
            continue

        decl_start = decl_nodes[0].start_byte
        body_node  = body_nodes[0]

        decorated_info = dec_map.get(decl_start)
        code_block = decorated_info[0] if decorated_info else _txt(decl_nodes[0], code)
        dec_texts  = decorated_info[1] if decorated_info else []

        ctx       = _find_class_ctx(decl_start, sorted_ctx)
        class_iam = _class_iam_type(ctx)

        endpoint_type = None
        http_method   = None
        route         = None

        for dec in dec_texts:
            pair = _extract_http_verb_from_decorator(dec)
            if pair:
                endpoint_type, http_method = pair
                route = _extract_route_from_decorator(dec)
                break

        if not endpoint_type and func_name.lower() in CBV_HTTP_METHODS:
            if class_iam == "REST" or (class_iam is None and
               any(b in _ci(ctx.get("bases", ""))
                   for b in ("view", "handler", "resource"))):
                endpoint_type = "REST"
                http_method   = func_name.upper()

        if not endpoint_type:
            endpoint_type = _detect_iam_type_from_annotations(dec_texts)
        if not endpoint_type:
            endpoint_type = _detect_iam_type_from_body(_ci(_txt(body_node, code)))
        if not endpoint_type:
            endpoint_type = class_iam
        if not endpoint_type:
            continue

        dedup = (func_name, file, endpoint_type)
        if dedup in seen:
            continue
        seen.add(dedup)

        entries.append({
            "name":           func_name,
            "endpoint_type":  endpoint_type,
            "file":           file,
            "route":          route if endpoint_type == "REST" else None,
            "http_method":    http_method,
            "code_block":     code_block,
            "auth":           _get_auth_decorators(dec_texts),
            "called_methods": _extract_called_functions(body_node, code),
        })

    return entries


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 – ALL-METHODS REGISTRY  (legacy, kept for backward compat)
# ══════════════════════════════════════════════════════════════════════════════

def extract_all_methods(tree, code, file):
    """
    Extract EVERY function/method in the file for the cross-file registry.

    Kept for backward compatibility.  engine.py now calls extract_all() which
    produces this data without a second tree traversal.
    """
    class_ctx  = _build_class_context(tree, code)
    sorted_ctx = _build_sorted_ctx(class_ctx)
    dec_map    = _build_method_ann_map(tree, code)

    methods = []
    seen    = set()

    cu = QueryCursor(_Q_FULL_FN)
    for _, m in cu.matches(tree.root_node):
        name_nodes = m.get("func.name", [])
        body_nodes = m.get("func.body", [])
        decl_nodes = m.get("func.decl", [])
        if not name_nodes or not body_nodes or not decl_nodes:
            continue

        decl_start = decl_nodes[0].start_byte
        dedup      = (file, decl_start)
        if dedup in seen:
            continue
        seen.add(dedup)

        func_name  = _txt(name_nodes[0], code)
        body_node  = body_nodes[0]

        decorated_info = dec_map.get(decl_start)
        code_block = decorated_info[0] if decorated_info else _txt(decl_nodes[0], code)
        dec_texts  = decorated_info[1] if decorated_info else []

        ctx = _find_class_ctx(decl_start, sorted_ctx)

        methods.append({
            "name":           func_name,
            "file":           file,
            "class_name":     ctx.get("name", ""),
            "code_block":     code_block,
            "body_text":      _txt(body_node, code),
            "auth":           _get_auth_decorators(dec_texts),
            "called_methods": _extract_called_functions(body_node, code),
        })

    return methods


# ══════════════════════════════════════════════════════════════════════════════
# LEGACY SHIMS  (keep engine.py backward compat)
# ══════════════════════════════════════════════════════════════════════════════

def extract_endpoints(tree, code, file):
    """Shim — flat REST endpoint dicts for exposure_map compat."""
    return extract_all(tree, code, file)["endpoints"]


def extract_auth(tree, code, file):
    """Shim — file-level auth decorator records."""
    return _extract_auth_records(tree, code, file)


def extract_data_exposures(tree, code, file):
    """Shim — non-REST entry points as data_exposure dicts."""
    return extract_all(tree, code, file)["data_exposures"]