"""
extractor.py  (languages/java)
--------------------------------
Phase 1  – extract_iam_entry_points()
    Scans every method in the codebase and returns only those that are
    IAM-consumable data-exposing entry points.  Each record carries the
    full code_block, the IAM endpoint_type, HTTP route/method (if REST),
    and the list of method names called inside the body.

Phase 2  – extract_all_methods()
    Returns EVERY method in the file as a lightweight dict so the engine
    can build the cross-file method registry for call-graph resolution.

Phase 3  – extract_all()  ← PRIMARY ENTRY POINT (new)
    Single tree pass that produces entry_points, all_methods, endpoints,
    data_exposures, and auth in one shot.  engine.py uses this to avoid
    the 3× re-extraction that the legacy shims caused.
"""

import bisect
import re

from tree_sitter import QueryCursor
from .parser import JAVA_LANGUAGE
from . import rules
from core.models import create_auth


# ══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL QUERY CACHE
# Query compilation is expensive (string parsing + tree-sitter compile step).
# Build each query once at import time and reuse the compiled object.
# QueryCursor is cheap and IS created per-call (it tracks match state).
# ══════════════════════════════════════════════════════════════════════════════

_Q_ANNOTATED_METHOD = rules.annotated_method_query(JAVA_LANGUAGE)
_Q_FULL_METHOD      = rules.full_method_query(JAVA_LANGUAGE)
_Q_METHOD_INV       = rules.method_invocation_query(JAVA_LANGUAGE)
_Q_CLASS_ANN        = rules.class_annotation_query(JAVA_LANGUAGE)
_Q_SUPERCLASS       = rules.superclass_query(JAVA_LANGUAGE)
_Q_FIELD_TYPE       = rules.class_field_type_query(JAVA_LANGUAGE)
_Q_CLASS_ROUTE      = rules.class_route_query(JAVA_LANGUAGE)
_Q_ENDPOINT         = rules.endpoint_query(JAVA_LANGUAGE)
_Q_AUTH             = rules.auth_query(JAVA_LANGUAGE)


# ══════════════════════════════════════════════════════════════════════════════
# IAM ENDPOINT TYPE DEFINITIONS
# Each key is the canonical endpoint_type label used in the output.
# ══════════════════════════════════════════════════════════════════════════════

# ── HTTP verb annotations → (endpoint_type, http_verb) ───────────────────────
REST_ANN_MAP = {
    # Spring MVC / WebFlux
    "getmapping":     ("REST", "GET"),
    "postmapping":    ("REST", "POST"),
    "putmapping":     ("REST", "PUT"),
    "deletemapping":  ("REST", "DELETE"),
    "patchmapping":   ("REST", "PATCH"),
    "requestmapping": ("REST", "REQUEST"),
    # JAX-RS
    "get":            ("REST", "GET"),
    "post":           ("REST", "POST"),
    "put":            ("REST", "PUT"),
    "delete":         ("REST", "DELETE"),
    "patch":          ("REST", "PATCH"),
    "head":           ("REST", "HEAD"),
    "options":        ("REST", "OPTIONS"),
}

# ── GraphQL endpoint annotations ─────────────────────────────────────────────
GRAPHQL_ANN = {
    "querymapping", "mutationmapping", "schemamapping", "subscriptionmapping",
    "batchmapping", "graphqlquery", "graphqlmutation", "graphqlsubscription",
    "dgsquery", "dgsdata", "dgsmutation", "dgssubscription",
    "querytype", "mutationtype", "subscriptiontype",
}

# ── SOAP annotations ──────────────────────────────────────────────────────────
SOAP_ANN = {
    "webmethod", "operationcontract", "webget", "webinvoke",
    "webserviceprovider",
}

# ── WebSocket annotations ─────────────────────────────────────────────────────
WS_ANN = {
    "serverendpoint", "onopen", "onmessage", "onclose", "onerror",
    "messagemapping", "sendto", "sendtouser", "subscribemapping",
}

# ── SCIM annotations ──────────────────────────────────────────────────────────
SCIM_ANN = {"scimresource", "scimendpoint", "scimcontroller"}

# ── OAuth2 / OIDC / SAML annotations ─────────────────────────────────────────
OAUTH2_ANN = {"oauth2login", "oauth2userinfoendpoint"}
OIDC_ANN   = {"oidcuserinfoendpoint", "openidconnect"}
SAML_ANN   = {"saml2login", "saml2metadatafilter"}

# ── Class-level annotations that declare an IAM service class ────────────────
CLASS_IAM_ANN = {
    "webservice":          "SOAP",
    "webserviceprovider":  "SOAP",
    "grpcservice":         "GRPC",
    "serverendpoint":      "WEBSOCKET",
    "scimcontroller":      "SCIM",
}

# ── Superclass suffix patterns (gRPC generated base) ─────────────────────────
GRPC_IMPLBASE_RE = re.compile(r"grpc\b.*implbase", re.IGNORECASE)

# ── Auth annotation names ─────────────────────────────────────────────────────
AUTH_HINTS = {
    "preauthorize", "postauthorize", "secured", "rolesallowed",
    "permitall", "denyall", "authenticated", "authorize",
    "enablewebsecurity", "enablemethodsecurity",
    "declareroles", "runas", "bearer", "jwtauthentication",
}

# Pre-compiled regex for fast auth hint matching (replaces nested loop in _get_auth_annotations)
_AUTH_HINTS_RE = re.compile(
    "|".join(re.escape(h) for h in AUTH_HINTS), re.IGNORECASE
)

# ═══════════════════════════════════════════════════════════════════════════════
# BODY SIGNATURE TABLES
# Each maps endpoint_type → list of case-insensitive tokens that, when found
# in the method body, classify the method as that IAM exposure type.
# ═══════════════════════════════════════════════════════════════════════════════

BODY_SIGNATURES = {
    # ── JDBC / Direct SQL ─────────────────────────────────────────────────────
    "JDBC": [
        "drivermanager.getconnection", "preparestatement(", "preparecall(",
        "executequery(", "executeupdate(", "executebatch(",
        "stmt.execute(", "statement.execute(", "jdbc.execute(",
        "resultset", "callablestatement",
        "jdbctemplate", "namedparameterjdbctemplate", "simplejdbcinsert",
        "queryforlist(", "queryforobject(", "queryformap(", "batchupdate(",
        "hikari", "basicdatasource",
        "sqlsession.", "sqlsessionfactory", "sqlsessiontemplate",
        "dslcontext", "r2dbctemplate", "databaseclient",
    ],
    # ── LDAP / Directory ──────────────────────────────────────────────────────
    "LDAP": [
        "ldaptemplate.search(", "ldaptemplate.find(", "ldaptemplate.bind(",
        "ldaptemplate.lookup(", "ldaptemplate.authenticate(", "ldaptemplate.modify(",
        "ldaptemplate.unbind(", "ldaptemplate.list(",
        "initialdicontext(", "initialldapcontext(",
        "dircontext.search(", "ldapcontext.search(",
        "namingenumeration", "searchcontrols",
        "ldapconnection.search(", "ldapconnection.bind(",
        "ldapnetworkconnection",
    ],
    # ── Active Directory (LDAP + AD-specific patterns) ────────────────────────
    "ACTIVE_DIRECTORY": [
        "activedirectoryldapauthenticationprovider",
        "samaccountname", "useraccountcontrol", "distinguishedname",
        "objectclass=user", "objectclass=person",
        "cn=users,dc=", "memberof",
        "ldap://", "ldaps://",
        "principalcontext(", "userprincipal.findbyidentity(",
        "groupprincipal.findbyidentity(",
    ],
    # ── SOAP ─────────────────────────────────────────────────────────────────
    "SOAP": [
        "soapmessage", "soapbody", "soapenvelope", "soappart", "soapheader",
        "messagefactory.newinstance(", "soapconnection.call(",
        "dispatch.invoke(", "dispatch.invokeonewaay(",
        "jaxwsserverfactorybean", "jaxwsproxyfactorybean",
        "webservicegatewaysupport",
    ],
    # ── gRPC ─────────────────────────────────────────────────────────────────
    "GRPC": [
        "streamobserver", "responseobserver.onnext(", "responseobserver.oncompleted(",
        "responseobserver.onerror(",
        "blockingstub.", "asyncstub.", "futurestub.",
        "managedchannel.foraddress(", "managedchannelbuilder.foraddress(",
        "grpcchannel", "grpcclient",
    ],
    # ── GraphQL ───────────────────────────────────────────────────────────────
    "GRAPHQL": [
        "datafetchingenvironment", "datafetcher", "runtimewiring.newruntimewiring(",
        "typedefs", "graphqlschema.newschema(",
        "dgscomponent", "dgsqueryexecutor",
        "graphqlqueryresolver", "graphqlmutationresolver",
    ],
    # ── CSV Exports ───────────────────────────────────────────────────────────
    "CSV": [
        "csvprinter(", "csvformat.", "org.apache.commons.csv",
        "csvwriter(", "com.opencsv", "icecsv", "supercsv",
        "flatfileitemwriter", "delimitedlineaggregator",
        "writer.writerow(", "exportcsv(", "tocsv(",
    ],
    # ── Excel Exports ─────────────────────────────────────────────────────────
    "EXCEL": [
        "xssfworkbook(", "hssfworkbook(",
        "workbook.createsheet(", "workbook.write(",
        "row.createcell(", "org.apache.poi",
        "fastexcel", "easyexcel",
        "exportexcel(", "toexcel(",
    ],
    # ── JSON File Exports ─────────────────────────────────────────────────────
    "JSON_EXPORT": [
        "objectmapper.writevalue(new file",
        "objectmapper.writevalue(outputstream",
        "objectmapper.writevalue(writer",
        "objectmapper.writerwithdefaultprettyprinter(",
        "exportjson(", "responsebodyemitter", "sseemitter",
        "streamingresponsebody",
    ],
    # ── XML Exports ───────────────────────────────────────────────────────────
    "XML": [
        "jaxbcontext.newinstance(", "marshaller.marshal(",
        "unmarshaller.unmarshal(",
        "documentbuilder.parse(", "documentbuilderfactory.newinstance(",
        "saxparser.parse(", "saxparserfactory.newinstance(",
        "xmlstreamwriter.writestartelement(",
        "xmlinputfactory.newinstance(",
        "transformerfactory.newinstance(", "transformer.transform(",
        "dom4j", "jdom",
    ],
    # ── FTP ───────────────────────────────────────────────────────────────────
    "FTP": [
        "ftpclient.connect(", "ftpclient.login(", "ftpclient.storefile(",
        "ftpclient.retrievefile(", "org.apache.commons.net.ftp",
        "ftpoutboundgateway", "ftpsessionfactory",
    ],
    # ── SFTP ──────────────────────────────────────────────────────────────────
    "SFTP": [
        "channelsftp.put(", "channelsftp.get(", "channelsftp.ls(",
        "com.jcraft.jsch", "jsch()", "sftpclient",
        "sftpoutboundgateway", "sftpsessionfactory",
    ],
    # ── FTPS ──────────────────────────────────────────────────────────────────
    "FTPS": [
        "ftpsclient.connect(", "ftpsclient.login(",
        "org.apache.commons.net.ftp.ftpsclient",
    ],
    # ── REST Outbound ─────────────────────────────────────────────────────────
    "REST_OUTBOUND": [
        "resttemplate.getforobject(", "resttemplate.postforobject(",
        "resttemplate.exchange(", "resttemplate.getforentity(",
        "webclient.get(", "webclient.post(", "webclient.put(",
        "webclient.delete(", "webclient.patch(",
        "httpclient.execute(", "okhttp", "httpurlconnection",
        "feign", "retrofit",
    ],
    # ── SCIM ─────────────────────────────────────────────────────────────────
    "SCIM": [
        "scimuser", "scimgroup", "scimresource",
        "com.unboundid.scim2", "de.captaingoldfish.scim",
        "/scim/v2", "scimsdk", "scimentitymanager",
    ],
    # ── OAuth2 ────────────────────────────────────────────────────────────────
    "OAUTH2": [
        "oauth2user.getattributes(", "oauth2authorizedclient",
        "oauth2accesstoken", "defaultoauth2userservice.loaduser(",
        "oauth2userinfoendpoint", "oauth2tokenresponse",
        "oauth2resourceserver", "jwtauthenticationconverter",
    ],
    # ── OIDC ─────────────────────────────────────────────────────────────────
    "OIDC": [
        "oidcuser.getuserinfo(", "oidcidtoken", "openidconnect",
        "defaultoidcuserservice.loaduser(",
        "/.well-known/openid-configuration",
    ],
    # ── SAML ─────────────────────────────────────────────────────────────────
    "SAML": [
        "saml2authenticationtoken", "relyingpartyregistration",
        "org.opensaml", "samlresponse", "samlassertion",
        "saml2login", "spring.security.saml2",
        "saml2authenticationrequestfactory",
    ],
    # ── WebSocket ─────────────────────────────────────────────────────────────
    "WEBSOCKET": [
        "session.getbasicremote().sendtext(",
        "session.getasyncremote().sendtext(",
        "websocketsession.sendmessage(",
        "simpmessagingtemplate.convertandsend(",
        "simpmessagingtemplate.convertandsendtouser(",
        "sockjsservicefactory",
    ],
    # ── Messaging ─────────────────────────────────────────────────────────────
    "MESSAGING": [
        "kafkatemplate.send(", "kafkatemplate.senddefault(",
        "rabbittemplate.convertandsend(", "rabbittemplate.send(",
        "jmstemplate.convertandsend(", "jmstemplate.send(",
        "sqsclient.sendmessage(", "snsclient.publish(",
        "messagegateway", "integrationflow",
    ],
}

# ── Field type → endpoint_type (injected beans in class fields) ───────────────
FIELD_TYPE_IAM = {
    "jdbctemplate":                    "JDBC",
    "namedparameterjdbctemplate":      "JDBC",
    "datasource":                      "JDBC",
    "sqlsession":                      "JDBC",
    "sqlsessionfactory":               "JDBC",
    "dslcontext":                      "JDBC",
    "r2dbctemplate":                   "JDBC",
    "ldaptemplate":                    "LDAP",
    "ldapclient":                      "LDAP",
    "ldapconnection":                  "LDAP",
    "ldaprepository":                  "LDAP",
    "directorysearcher":               "ACTIVE_DIRECTORY",
    "ldapconnectionpool":              "ACTIVE_DIRECTORY",
    "managedchannel":                  "GRPC",
    "grpcchannel":                     "GRPC",
    "resttemplate":                    "REST_OUTBOUND",
    "webclient":                       "REST_OUTBOUND",
    "httpclient":                      "REST_OUTBOUND",
    "simpmessagingtemplate":           "WEBSOCKET",
    "kafkatemplate":                   "MESSAGING",
    "rabbittemplate":                  "MESSAGING",
    "jmstemplate":                     "MESSAGING",
    "ftpclient":                       "FTP",
    "ftpsclient":                      "FTPS",
    "channelsftp":                     "SFTP",
}

# ── Method-level annotations that signal a specific IAM type ─────────────────
METHOD_ANN_IAM = {
    # GraphQL
    "querymapping":        "GRAPHQL",
    "mutationmapping":     "GRAPHQL",
    "schemamapping":       "GRAPHQL",
    "subscriptionmapping": "GRAPHQL",
    "batchmapping":        "GRAPHQL",
    "graphqlquery":        "GRAPHQL",
    "graphqlmutation":     "GRAPHQL",
    "graphqlsubscription": "GRAPHQL",
    "dgsquery":            "GRAPHQL",
    "dgsmutation":         "GRAPHQL",
    "dgsdata":             "GRAPHQL",
    # SOAP
    "webmethod":           "SOAP",
    "operationcontract":   "SOAP",
    "webget":              "SOAP",
    "webinvoke":           "SOAP",
    # WebSocket
    "serverendpoint":      "WEBSOCKET",
    "onmessage":           "WEBSOCKET",
    "messagemapping":      "WEBSOCKET",
    "sendto":              "WEBSOCKET",
    "sendtouser":          "WEBSOCKET",
    "subscribemapping":    "WEBSOCKET",
    # SCIM
    "scimresource":        "SCIM",
    # OAuth2 / OIDC / SAML
    "oauth2login":         "OAUTH2",
    "oidclogin":           "OIDC",
    "saml2login":          "SAML",
    # Messaging
    "kafkalistener":       "MESSAGING",
    "rabbitlistener":      "MESSAGING",
    "jmslistener":         "MESSAGING",
    "sqslistener":         "MESSAGING",
    "eventlistener":       "MESSAGING",
}

# ── Noise methods to exclude from call graph edges ────────────────────────────
_CALL_SKIP = {
    # java.lang.Object
    "toString","hashCode","equals","getClass","clone","notify","notifyAll","wait","finalize",
    # String
    "toLowerCase","toUpperCase","trim","replace","replaceAll","replaceFirst",
    "split","join","substring","charAt","indexOf","startsWith","endsWith","matches","strip",
    "contains","format","valueOf","isEmpty","isBlank","length","toCharArray","getBytes",
    # Collections / Stream
    "add","remove","get","put","clear","size","isEmpty","contains","containsKey","containsValue",
    "entrySet","keySet","values","toArray","iterator","hasNext","next",
    "stream","parallelStream","filter","map","flatMap","collect","toList","forEach",
    "reduce","count","findFirst","findAny","anyMatch","allMatch","noneMatch",
    "sorted","distinct","limit","skip","peek","groupingBy","joining","toSet","toMap",
    # Optional
    "orElse","orElseGet","orElseThrow","isPresent","ifPresent","ifPresentOrElse","get","of","empty",
    # Logging
    "debug","info","warn","error","trace","log","getLogger","isDebugEnabled","isInfoEnabled",
    # Builder / factory noise
    "build","create","newInstance","builder","of","from","with","and",
    # Assertion / null check
    "requireNonNull","nonNull","isNull","checkNotNull","checkArgument","checkState",
    # Common setters/getters
    "getId","setId","getName","setName","getEmail","setEmail","getType","setType",
    "getStatus","setStatus","getRole","setRole","getUsername","setUsername",
    "getPassword","setPassword","getCreatedAt","getUpdatedAt","setCreatedAt","setUpdatedAt",
    # Numeric
    "parseInt","parseLong","parseDouble","parseFloat","intValue","longValue","doubleValue",
    # Object creation
    "new",
}

# ── Entry-point methods to skip (infrastructure / lifecycle) ─────────────────
_ENTRY_SKIP = {
    "toString","hashCode","equals","clone","finalize","getClass",
    "onModelCreating","configure","main","init","destroy","afterPropertiesSet",
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _ci(s):
    return s.lower() if s else ""


def _txt(node, code):
    return code[node.start_byte:node.end_byte]


def _extract_route(arg_nodes, code):
    """Extract route string from annotation argument nodes."""
    for arg in arg_nodes:
        text  = code[arg.start_byte:arg.end_byte]
        found = re.findall(r'"(.*?)"', text)
        if found:
            return found[0]
    return "/"


def _join_routes(prefix, suffix):
    prefix = (prefix or "").rstrip("/")
    suffix = (suffix or "").strip()
    if not prefix:
        return suffix or "/"
    if not suffix or suffix == "/":
        return prefix
    if not suffix.startswith("/"):
        suffix = "/" + suffix
    return prefix + suffix


def _detect_iam_type_from_body(body_lower):
    """Return the first matching IAM type from body signatures, or None."""
    for iam_type, sigs in BODY_SIGNATURES.items():
        if any(sig in body_lower for sig in sigs):
            return iam_type
    return None


def _detect_iam_type_from_annotations(ann_list):
    """Return IAM type from method annotations, or None."""
    for ann in ann_list:
        a = _ci(ann)
        pair = REST_ANN_MAP.get(a)
        if pair:
            return "REST"
        mapped = METHOD_ANN_IAM.get(a)
        if mapped:
            return mapped
    return None


def _get_auth_annotations(ann_list):
    """Return auth annotation texts from annotation list.

    Uses a pre-compiled regex instead of the original O(N×H) nested loop.
    """
    return [a for a in ann_list if _AUTH_HINTS_RE.search(a)]


def _extract_called_methods(body_node, code):
    """
    Return unique method names called inside body_node.
    Filters out noise using _CALL_SKIP.

    OPTIMIZED: Uses the module-level cached _Q_METHOD_INV query object
    instead of compiling a new Query on every call.
    """
    cu = QueryCursor(_Q_METHOD_INV)   # cursor is cheap; query object is cached
    found = set()
    for _, match in cu.matches(body_node):
        for n in match.get("call.name", []):
            name = code[n.start_byte:n.end_byte]
            if name not in _CALL_SKIP and len(name) > 2:
                found.add(name)
    return list(found)


# ══════════════════════════════════════════════════════════════════════════════
# CLASS CONTEXT  (built once per file, shared by all methods in the file)
# ══════════════════════════════════════════════════════════════════════════════

def _build_class_context(tree, code):
    """
    Returns { (start_byte, end_byte): ctx_dict } for every class.
    ctx_dict: { name, annotations, superclass, field_types, route_prefix }

    OPTIMIZED: All four internal queries now use the module-level cached
    query objects instead of compiling a new Query per call.
    """
    ctx = {}

    # annotated classes
    cu = QueryCursor(_Q_CLASS_ANN)
    for _, m in cu.matches(tree.root_node):
        decl = m.get("class.decl", [])
        name = m.get("class.name", [])
        anns = m.get("class.ann",  [])
        if not decl:
            continue
        key = (decl[0].start_byte, decl[0].end_byte)
        ctx[key] = {
            "name":         _txt(name[0], code) if name else "",
            "annotations":  [_txt(n, code) for n in anns],
            "superclass":   "",
            "field_types":  [],
            "route_prefix": "",
        }

    # superclass
    cu = QueryCursor(_Q_SUPERCLASS)
    for _, m in cu.matches(tree.root_node):
        decl = m.get("class.decl",      [])
        name = m.get("class.name",      [])
        sc   = m.get("superclass.name", [])
        if not decl:
            continue
        key  = (decl[0].start_byte, decl[0].end_byte)
        sc_t = _txt(sc[0], code) if sc else ""
        if key in ctx:
            ctx[key]["superclass"] = sc_t
        else:
            ctx[key] = {
                "name":         _txt(name[0], code) if name else "",
                "annotations":  [],
                "superclass":   sc_t,
                "field_types":  [],
                "route_prefix": "",
            }

    # field types
    cu = QueryCursor(_Q_FIELD_TYPE)
    for _, m in cu.matches(tree.root_node):
        decl   = m.get("class.decl",  [])
        fields = m.get("field.type",  [])
        name   = m.get("class.name",  [])
        if not decl:
            continue
        key = (decl[0].start_byte, decl[0].end_byte)
        fts = [_txt(n, code) for n in fields]
        if key in ctx:
            ctx[key]["field_types"] = fts
        else:
            ctx[key] = {
                "name":         _txt(name[0], code) if name else "",
                "annotations":  [],
                "superclass":   "",
                "field_types":  fts,
                "route_prefix": "",
            }

    # class-level route prefix
    ROUTE_ANNS = {"requestmapping", "path"}
    cu = QueryCursor(_Q_CLASS_ROUTE)
    for _, m in cu.matches(tree.root_node):
        decl = m.get("class.decl",  [])
        ann  = m.get("route.ann",   [])
        args = m.get("route.args",  [])
        if not decl or not ann or not args:
            continue
        if _ci(_txt(ann[0], code)) not in ROUTE_ANNS:
            continue
        args_text = _txt(args[0], code)
        found     = re.findall(r'"(.*?)"', args_text)
        if not found:
            continue
        key = (decl[0].start_byte, decl[0].end_byte)
        if key in ctx:
            ctx[key]["route_prefix"] = found[0]
        elif decl:
            ctx[key] = {
                "name": "", "annotations": [], "superclass": "",
                "field_types": [], "route_prefix": found[0],
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
    # Find the last class whose start_byte <= decl_start
    idx = bisect.bisect_right(starts, decl_start) - 1
    # Walk backwards through overlapping ranges (handles nested classes)
    while idx >= 0:
        s, e, c = sorted_ctx[idx]
        if decl_start <= e:
            return c
        idx -= 1
    return {}


def _class_iam_type(ctx):
    """Resolve IAM type from class-level context (annotations, superclass, fields)."""
    for ann in ctx.get("annotations", []):
        mapped = CLASS_IAM_ANN.get(_ci(ann))
        if mapped:
            return mapped

    sc = ctx.get("superclass", "")
    if sc and re.search(r"grpc\b.*implbase", sc, re.IGNORECASE):
        return "GRPC"

    for ft in ctx.get("field_types", []):
        mapped = FIELD_TYPE_IAM.get(_ci(ft))
        if mapped:
            return mapped

    return None


# ══════════════════════════════════════════════════════════════════════════════
# SHARED INTERNAL: BUILD METHOD ANNOTATION MAP
# ══════════════════════════════════════════════════════════════════════════════

def _build_method_ann_map(tree, code):
    """
    Scan annotated methods once and return { decl_start_byte: [ann_text, ...] }.
    Shared by extract_all, extract_iam_entry_points, and extract_all_methods.
    """
    method_ann_map = {}
    cu = QueryCursor(_Q_ANNOTATED_METHOD)
    for _, m in cu.matches(tree.root_node):
        decl = m.get("method.decl", [])
        anns = m.get("ann.name",    [])
        if decl:
            key = decl[0].start_byte
            method_ann_map.setdefault(key, []).extend(
                [_txt(n, code) for n in anns]
            )
    return method_ann_map


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
      auth            – file-level auth annotation records
    """
    class_ctx  = _build_class_context(tree, code)
    sorted_ctx = _build_sorted_ctx(class_ctx)
    ann_map    = _build_method_ann_map(tree, code)

    entry_points   = []
    all_methods    = []
    endpoints      = []
    data_exposures = []

    seen_ep    = set()   # (method_name, file, endpoint_type)
    seen_m     = set()   # (file, decl_start)
    # called_methods cache: compute once per declaration, reuse in both outputs
    called_cache = {}    # decl_start → [called_method_names]

    cu = QueryCursor(_Q_FULL_METHOD)
    for _, m in cu.matches(tree.root_node):
        name_nodes = m.get("method.name", [])
        body_nodes = m.get("method.body", [])
        decl_nodes = m.get("method.decl", [])
        if not name_nodes or not body_nodes or not decl_nodes:
            continue

        decl_start  = decl_nodes[0].start_byte
        method_name = _txt(name_nodes[0], code)
        body_node   = body_nodes[0]
        ann_texts   = ann_map.get(decl_start, [])
        ctx         = _find_class_ctx(decl_start, sorted_ctx)

        # ── Compute called_methods once per declaration ───────────────────────
        if decl_start not in called_cache:
            called_cache[decl_start] = _extract_called_methods(body_node, code)
        called = called_cache[decl_start]

        # ── all_methods record ────────────────────────────────────────────────
        m_key = (file, decl_start)
        if m_key not in seen_m:
            seen_m.add(m_key)
            # body_text is used by dataflow for child-type classification
            body_text  = _txt(body_node, code)
            code_block = _txt(decl_nodes[0], code)
            all_methods.append({
                "name":           method_name,
                "file":           file,
                "class_name":     ctx.get("name", ""),
                "code_block":     code_block,
                "body_text":      body_text,
                "auth":           _get_auth_annotations(ann_texts),
                "called_methods": called,
            })
        else:
            # Already captured — still need code_block for entry-point below
            code_block = _txt(decl_nodes[0], code)

        # ── entry-point candidate check ───────────────────────────────────────
        if method_name in _ENTRY_SKIP:
            continue

        # Lazy-compute body_lower only when needed for signature scanning
        body_lower     = None
        endpoint_type  = None
        http_method    = None
        route          = "/"
        class_iam_type = _class_iam_type(ctx)
        cls_route_pre  = ctx.get("route_prefix", "")

        # 1. REST verb annotations
        for ann_text in ann_texts:
            a    = _ci(ann_text)
            pair = REST_ANN_MAP.get(a)
            if pair:
                endpoint_type, http_method = pair
                break

        # 2. Route extraction for REST
        if endpoint_type == "REST":
            cu2 = QueryCursor(_Q_ENDPOINT)
            for _, m2 in cu2.matches(decl_nodes[0]):
                arg_nodes = m2.get("ann.args", [])
                if arg_nodes:
                    route = _extract_route(arg_nodes, code)
                    break
            route = _join_routes(cls_route_pre, route)

        # 3. Non-REST annotation hints
        if not endpoint_type:
            endpoint_type = _detect_iam_type_from_annotations(ann_texts)

        # 4. Body signature scanning (only compute body_lower if needed)
        if not endpoint_type:
            body_lower    = _txt(body_node, code).lower()
            endpoint_type = _detect_iam_type_from_body(body_lower)

        # 5. Class-level fallback
        if not endpoint_type:
            endpoint_type = class_iam_type

        if not endpoint_type:
            continue

        ep_key = (method_name, file, endpoint_type)
        if ep_key in seen_ep:
            continue
        seen_ep.add(ep_key)

        auth_anns   = _get_auth_annotations(ann_texts)
        actual_route = route if endpoint_type == "REST" else None

        ep_record = {
            "name":           method_name,
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
                "handler":    method_name,
                "route":      route,
                "method":     http_method or "REST",
                "file":       file,
                "auth":       auth_anns,
                "code_block": code_block,
            })
        else:
            data_exposures.append({
                "handler":        method_name,
                "file":           file,
                "exposure_types": [endpoint_type],
                "code_block":     code_block,
                "auth":           [create_auth(a, file, code_block=a)
                                   for a in auth_anns],
            })

    # ── Auth extraction (single additional scan, fast) ────────────────────────
    auth = _extract_auth_records(tree, code, file)

    return {
        "entry_points":   entry_points,
        "all_methods":    all_methods,
        "endpoints":      endpoints,
        "data_exposures": data_exposures,
        "auth":           auth,
    }


def _extract_auth_records(tree, code, file):
    """Extract file-level auth annotation records (used by extract_all and extract_auth)."""
    cu   = QueryCursor(_Q_AUTH)
    auth = []
    for _, m in cu.matches(tree.root_node):
        for n in m.get("auth.name", []):
            text = code[n.start_byte:n.end_byte]
            if _AUTH_HINTS_RE.search(text):
                parent   = n.parent
                ann_text = code[parent.start_byte:parent.end_byte] if parent else text
                auth.append(create_auth(text, file, code_block=ann_text))
    if "token" in _ci(code):
        auth.append(create_auth("TokenBased", file))
    return auth


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — IAM ENTRY POINT EXTRACTION  (legacy, kept for backward compat)
# ══════════════════════════════════════════════════════════════════════════════

def extract_iam_entry_points(tree, code, file):
    """
    Scan every method and return only those that are IAM-consumable entry points.

    Kept for backward compatibility.  engine.py now calls extract_all() which
    is faster.  This function is still correct and uses cached query objects.
    """
    class_ctx      = _build_class_context(tree, code)
    sorted_ctx     = _build_sorted_ctx(class_ctx)
    method_ann_map = _build_method_ann_map(tree, code)

    entries = []
    seen    = set()

    cu = QueryCursor(_Q_FULL_METHOD)
    for _, m in cu.matches(tree.root_node):
        name_nodes = m.get("method.name", [])
        body_nodes = m.get("method.body", [])
        decl_nodes = m.get("method.decl", [])
        if not name_nodes or not body_nodes or not decl_nodes:
            continue

        method_name = _txt(name_nodes[0], code)
        if method_name in _ENTRY_SKIP:
            continue

        decl_start = decl_nodes[0].start_byte
        body_node  = body_nodes[0]
        body_lower = _ci(_txt(body_node, code))
        code_block = _txt(decl_nodes[0], code)
        ann_texts  = method_ann_map.get(decl_start, [])

        ctx            = _find_class_ctx(decl_start, sorted_ctx)
        class_iam_type = _class_iam_type(ctx)
        cls_route_pre  = ctx.get("route_prefix", "")

        endpoint_type = None
        http_method   = None
        route         = "/"

        for ann_text in ann_texts:
            a    = _ci(ann_text)
            pair = REST_ANN_MAP.get(a)
            if pair:
                endpoint_type, http_method = pair
                break

        if endpoint_type == "REST":
            cu2 = QueryCursor(_Q_ENDPOINT)
            for _, m2 in cu2.matches(decl_nodes[0]):
                arg_nodes = m2.get("ann.args", [])
                if arg_nodes:
                    route = _extract_route(arg_nodes, code)
                    break
            route = _join_routes(cls_route_pre, route)

        if not endpoint_type:
            endpoint_type = _detect_iam_type_from_annotations(ann_texts)
        if not endpoint_type:
            endpoint_type = _detect_iam_type_from_body(body_lower)
        if not endpoint_type:
            endpoint_type = class_iam_type
        if not endpoint_type:
            continue

        dedup = (method_name, file, endpoint_type)
        if dedup in seen:
            continue
        seen.add(dedup)

        auth_anns = _get_auth_annotations(ann_texts)
        entries.append({
            "name":           method_name,
            "endpoint_type":  endpoint_type,
            "file":           file,
            "route":          route if endpoint_type == "REST" else None,
            "http_method":    http_method,
            "code_block":     code_block,
            "auth":           auth_anns,
            "called_methods": _extract_called_methods(body_node, code),
        })

    return entries


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — ALL-METHODS REGISTRY  (legacy, kept for backward compat)
# ══════════════════════════════════════════════════════════════════════════════

def extract_all_methods(tree, code, file):
    """
    Extract EVERY method in the file for the cross-file method registry.

    Kept for backward compatibility.  engine.py now calls extract_all() which
    produces this data without a second tree traversal.
    """
    class_ctx      = _build_class_context(tree, code)
    sorted_ctx     = _build_sorted_ctx(class_ctx)
    method_ann_map = _build_method_ann_map(tree, code)

    methods = []
    seen    = set()

    cu = QueryCursor(_Q_FULL_METHOD)
    for _, m in cu.matches(tree.root_node):
        name_nodes = m.get("method.name", [])
        body_nodes = m.get("method.body", [])
        decl_nodes = m.get("method.decl", [])
        if not name_nodes or not body_nodes or not decl_nodes:
            continue

        decl_start = decl_nodes[0].start_byte
        dedup      = (file, decl_start)
        if dedup in seen:
            continue
        seen.add(dedup)

        method_name = _txt(name_nodes[0], code)
        body_node   = body_nodes[0]
        body_text   = _txt(body_node, code)
        code_block  = _txt(decl_nodes[0], code)
        ann_texts   = method_ann_map.get(decl_start, [])
        ctx         = _find_class_ctx(decl_start, sorted_ctx)

        methods.append({
            "name":           method_name,
            "file":           file,
            "class_name":     ctx.get("name", ""),
            "code_block":     code_block,
            "body_text":      body_text,
            "auth":           _get_auth_annotations(ann_texts),
            "called_methods": _extract_called_methods(body_node, code),
        })

    return methods


# ══════════════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY SHIMS  (other languages and engine.py still call these)
# ══════════════════════════════════════════════════════════════════════════════

def extract_endpoints(tree, code, file):
    """Shim — returns flat endpoint dicts for exposure_map backward compat."""
    entries = extract_iam_entry_points(tree, code, file)
    result  = []
    for e in entries:
        if e["endpoint_type"] == "REST":
            result.append({
                "handler":    e["name"],
                "route":      e.get("route") or "/",
                "method":     e.get("http_method") or "REST",
                "file":       e["file"],
                "auth":       e["auth"],
                "code_block": e["code_block"],
            })
    return result


def extract_auth(tree, code, file):
    """Shim — file-level auth annotation records."""
    return _extract_auth_records(tree, code, file)


def extract_data_exposures(tree, code, file):
    """Shim — returns non-REST entry points as data_exposure dicts."""
    entries = extract_iam_entry_points(tree, code, file)
    result  = []
    for e in entries:
        if e["endpoint_type"] != "REST":
            result.append({
                "handler":        e["name"],
                "file":           e["file"],
                "exposure_types": [e["endpoint_type"]],
                "code_block":     e["code_block"],
                "auth":           [create_auth(a, e["file"], code_block=a)
                                   for a in e["auth"]],
            })
    return result