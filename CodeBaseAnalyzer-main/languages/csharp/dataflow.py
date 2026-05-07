"""
dataflow.py  (languages/csharp)
---------------------------------
Mirrors the Java / JS dataflow modules exactly.  Two public surfaces:

1. build_exposure_map()  – unchanged flat map for backward compatibility.
2. build_iam_trees()     – primary output: a list of IAM call trees rooted at
   data-exposing entry points, with recursive `calls` arrays resolved across
   the entire codebase method registry.

Child-node type classification uses C#-specific body signatures
(type names, method patterns) rather than Java class references or JS packages.
"""

# ══════════════════════════════════════════════════════════════════════════════
# CHILD NODE TYPE CLASSIFIER
# ══════════════════════════════════════════════════════════════════════════════

_AUTH_KEYWORDS = {
    "auth", "authenticate", "authoriz", "login", "logout", "signout",
    "token", "claim", "permission", "role", "secure", "principal",
    "password", "credential", "session", "verif", "check", "guard",
    "jwt", "identity", "policy", "apikey",
    "oauth", "oidc", "saml", "bearer",           # ← add these
}

# Body tokens → child node type  (case-insensitive substrings)
_CHILD_BODY_SIGNATURES = {
    "SQL/ORM": [
        # EF Core / EF6
        ".tolist(", ".tolistasync(", ".firstordefault(",
        ".firstordefaultasync(", ".findasync(", ".find(",
        ".add(", ".addrange(", ".update(", ".remove(",
        ".savechanges(", ".savechangesasync(", ".fromsqlraw(",
        "dbcontext", "dbset<",
        # Dapper
        "connection.query<", "connection.execute(", "sqlmapper.",
        # NHibernate
        "isession.get<", "isession.save(", "isession.createquery(",
        # Raw ADO.NET
        "sqlconnection(", "sqlcommand(", "executenonquery(",
        "executereader(", "executescalar(",
        "npgsqlconnection(", "mysqlconnection(",
        "oracleconnection(", "oledbconnection(",
    ],
    "NOSQL": [
        # MongoDB
        "mongodbclient(", "imongocollection<",
        ".insertone(", ".replaceone(", ".deleteone(", ".aggregate(",
        "bsondocument",
        # Redis
        "connectionmultiplexer.connect(", "idatabase.stringget(",
        "idatabase.stringset(",
        # Cosmos DB
        "cosmosclient(", "container.readitemasync(",
        "container.createitemasync(",
        # Cassandra
        "cassandrasession", "session.execute(",
        # Elasticsearch / OpenSearch
        "elasticclient(", "client.index<", "client.search<",
        "opensearchclient(",
    ],
    "LDAP": [
        "directoryentry(", "directorysearcher(",
        "principalcontext(", "userprincipal.findbyidentity(",
        "ldapconnection(", "searchrequest(",
        "novell.directory.ldap",
    ],
    "GRPC": [
        "serverservicedefinition", "asyncunaryservercall",
        "iasyncstreamwriter", "serverstream.writeasync(",
        "grpcchannel", "channel.foraddress(",
    ],
    "GRAPHQL": [
        "iresolvercontext", "hotchocolate",
        "schema.execute(", "documentexecutor",
        "fieldtype", "resolvecontext",
    ],
    "REST_CLIENT": [
        "httpclient.getasync(", "httpclient.postasync(",
        "httpclient.putasync(", "httpclient.deleteasync(",
        "httpclient.sendasync(", "httpclient.getstring(",
        "restclient(", "refit.",
        "new httpclient(",
    ],
    "MESSAGING": [
        "imodel.basicpublish(", "rabbitmq",
        "sns.publishasync(", "sqs.sendmessageasync(",
        "servicebussender.sendmessageasync(",
        "eventhubproducerclient", "topicproducer",
        "ikafkaproducer", "masstransit",
    ],
    "FILE_IO": [
        "filestream(", "streamwriter(", "file.writealltext(",
        "file.writeallbytes(", "csvwriter(", "csvhelper",
        "excelpackage(", "excelworksheet",
        "xlworkbook(", "xmldocument(", "xmlwriter(",
        "xmlserializer(", "xdocument.save(",
        "jsonconvert.serializeobject(", "json.serialize(",
    ],
    "CLOUD_STORAGE": [
        "blobserviceclient(", "blobclient.uploadasync(",
        "amazons3client(", "putobjectrequest(",
        "transferutility.upload(",
        "storageclient.create(", "bucket.uploadobjectasync(",
    ],
    "WEBSOCKET": [
        "clients.all.sendasync(", "clients.caller.sendasync(",
        "clients.group(", "ihubcontext<",
        "websocket.sendasync(", "websocket.receiveasync(",
        "clientwebsocket(",
    ],
    "SERVERLESS": [
        "functioncontext", "httptrigger", "timertrigger",
        "queuetrigger", "blobtrigger",
        "ilambdacontext", "lambdaruntime",
    ],
    "SOAP": [
        "soapmessage", "soapenvelope",
        "channelfactory<", "servicehost(",
        "corewcf",
    ],
    "WEBHOOK": [
        "x-hub-signature", "webhooksecret",
        "iwebhookreceiver", "webhookpayload",
        "stripe-signature",
    ],
    "SEARCH_ENGINE": [
        "searchdescriptor<", "querydescriptor<",
        "client.index<", "client.search<",
        "opensearchclient(",
    ],
}


def _ci(s):
    return s.lower() if s else ""


def _classify_child_type(method_dict: dict) -> str:
    """Determine the display `type` for a non-entry-point child node."""
    body = _ci(
        method_dict.get("body_text", "") or method_dict.get("code_block", "")
    )
    auth = method_dict.get("auth", [])
    name = _ci(method_dict.get("name", ""))

    # Explicit auth signals
    if auth:
        return "AUTH"
    if any(kw in name for kw in _AUTH_KEYWORDS):
        return "AUTH"

    # Body token classification
    for child_type, sigs in _CHILD_BODY_SIGNATURES.items():
        if any(sig in body for sig in sigs):
            return child_type

    return "BUSINESS"


# ══════════════════════════════════════════════════════════════════════════════
# RECURSIVE TREE BUILDER
# ══════════════════════════════════════════════════════════════════════════════

MAX_DEPTH = 8


def _build_calls(
    called_method_names: list,
    registry: dict,
    chain: frozenset,
    depth: int,
) -> list:
    """
    For each name in `called_method_names`, look up the method in the registry,
    classify its type, and recurse.

    Parameters
    ----------
    called_method_names : list[str]
    registry            : { method_name: [method_dict, ...] }
    chain               : frozenset of (file, name) — cycle guard
    depth               : int

    Returns list of child call_node dicts.
    """
    if depth > MAX_DEPTH:
        return []

    calls      = []
    seen_child = set()

    for cname in called_method_names:
        candidates = registry.get(cname, [])
        if not candidates:
            continue

        candidate = candidates[0]
        child_key = (candidate.get("file", ""), cname)

        if child_key in seen_child or child_key in chain:
            calls.append({
                "name":       cname,
                "type":       "CIRCULAR_REF",
                "file":       candidate.get("file", ""),
                "code_block": "",
                "auth":       [],
                "calls":      [],
            })
            continue

        seen_child.add(child_key)

        child_type = _classify_child_type(candidate)
        new_chain  = chain | {child_key}

        # Normalise auth (strings or dicts)
        raw_auth  = candidate.get("auth", [])
        auth_list = [
            a if isinstance(a, str)
            else (a.get("code_block") or a.get("type", ""))
            for a in raw_auth
        ]

        grandchildren = _build_calls(
            candidate.get("called_methods", []),
            registry,
            new_chain,
            depth + 1,
        )

        calls.append({
            "name":       cname,
            "type":       child_type,
            "file":       candidate.get("file", ""),
            "code_block": candidate.get("code_block", ""),
            "auth":       auth_list,
            "calls":      grandchildren,
        })

    return calls


def build_iam_trees(entry_points: list, method_registry: dict) -> list:
    """
    Build the complete IAM call tree list for C# files.

    Parameters
    ----------
    entry_points    : list[dict]  – records from extract_iam_entry_points(),
                                    each has `called_methods`
    method_registry : dict        – { method_name: [method_dict, ...] }
                                    built from extract_all_methods() across
                                    all .cs files

    Returns
    -------
    list[dict]  – one root node per entry point:
    {
      "name":          str,          # method name
      "endpoint_type": str,          # REST | GRAPHQL | GRPC | JDBC | NOSQL | …
      "file":          str,          # source file path
      "route":         str | None,   # URL route (REST only)
      "method":        str | None,   # HTTP verb (REST only)
      "code_block":    str,          # full source code of the method
      "auth":          [str],        # auth attributes / hints on this method
      "calls": [
        {
          "name":       str,
          "type":       str,         # AUTH | SQL/ORM | NOSQL | GRPC | BUSINESS | …
          "file":       str,
          "code_block": str,
          "auth":       [str],
          "calls":      [...]        # recursive
        }
      ]
    }
    """
    trees      = []
    seen_roots = set()

    for ep in entry_points:
        name  = ep.get("name", "")
        file  = ep.get("file", "")
        etype = ep.get("endpoint_type", "")

        root_key = (name, file, etype)
        if root_key in seen_roots:
            continue
        seen_roots.add(root_key)

        # Normalise auth
        raw_auth  = ep.get("auth", [])
        auth_list = [
            a if isinstance(a, str)
            else (a.get("code_block") or a.get("type", ""))
            for a in raw_auth
        ]

        calls = _build_calls(
            ep.get("called_methods", []),
            method_registry,
            frozenset({(file, name)}),
            depth=1,
        )

        trees.append({
            "name":          name,
            "endpoint_type": etype,
            "file":          file,
            "route":         ep.get("route"),
            "method":        ep.get("http_method"),
            "code_block":    ep.get("code_block", ""),
            "auth":          auth_list,
            "calls":         calls,
        })

    return trees


# ══════════════════════════════════════════════════════════════════════════════
# BACKWARD-COMPATIBLE FLAT MAP
# ══════════════════════════════════════════════════════════════════════════════

def build_exposure_map(endpoints: list, data_exposures: list) -> dict:
    """
    Unchanged flat map — kept for backward compatibility.
    """
    result = {}

    for ep in endpoints:
        http_method = ep.get("method") or "REST"
        route       = ep.get("route",   "")
        handler     = ep.get("handler", "")
        file_path   = ep.get("file",    "")
        key         = f"REST:{http_method}:{route}:{handler}"
        entry = {
            "type":        "REST",
            "handler":     handler,
            "file":        file_path,
            "route":       route,
            "http_method": http_method,
            "auth":        ep.get("auth",      []),
            "code_block":  ep.get("code_block"),
        }
        if key not in result or len(entry["auth"]) > len(result[key]["auth"]):
            result[key] = entry

    for exp in data_exposures:
        handler   = exp.get("handler",        "")
        file_path = exp.get("file",           "")
        for exp_type in exp.get("exposure_types", []):
            key = f"{exp_type}:{handler}:{file_path}"
            entry = {
                "type":        exp_type,
                "handler":     handler,
                "file":        file_path,
                "route":       None,
                "http_method": None,
                "auth":        exp.get("auth", []),
                "code_block":  exp.get("code_block"),
            }
            if key not in result or len(entry["auth"]) > len(result[key]["auth"]):
                result[key] = entry

    return result