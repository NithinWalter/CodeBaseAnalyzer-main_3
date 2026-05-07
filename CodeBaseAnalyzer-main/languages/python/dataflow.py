"""
dataflow.py  (languages/python)
---------------------------------
Two responsibilities:

1. build_exposure_map()  – flat backward-compatible map (unchanged).
2. build_iam_trees()     – recursive IAM call trees for Python codebases.
"""

MAX_DEPTH = 8

# ── Child node type body signatures ──────────────────────────────────────────

_AUTH_KEYWORDS = {
    "auth", "authenticate", "authoriz", "login", "logout", "signout",
    "token", "claim", "permission", "role", "secure", "principal",
    "password", "credential", "session", "verif", "check", "guard",
    "jwt", "oauth", "oidc", "saml", "bearer",
}

_CHILD_BODY_SIGNATURES = {
    "SQL/ORM": [
        # SQLAlchemy
        "session.query(", "session.execute(", "db.session",
        "session.add(", "session.commit(", "engine.execute(",
        "create_engine(", "select(", "insert(", "update(", "delete(",
        # Django ORM
        "objects.filter(", "objects.get(", "objects.all(",
        "objects.create(", ".save()", ".delete()",
        "get_or_create(", "update_or_create(", "bulk_create(",
        # Direct SQL
        "cursor.execute(", "conn.execute(", "psycopg2",
        "sqlite3.connect(", "mysql.connector", "cx_oracle",
        # Tortoise / Peewee
        "await model.filter(", "await model.get(",
        ".select().where(", "peewee.model",
    ],
    "LDAP": [
        "ldap3.connection(", "conn.search(", "conn.bind(",
        "ldap.initialize(", "l.search_s(", "l.bind_s(",
        "ldapbackend", "ldapsearch(",
        "cn=", "dc=", "ou=", "dn=",
    ],
    "ACTIVE_DIRECTORY": [
        "samaccountname", "useraccountcontrol",
        "objectclass=user", "objectclass=person",
        "pyad.aduser", "pyad.adgroup", "impacket.ldap",
    ],
    "GRPC": [
        "grpc.server(", "grpc.insecure_channel(", "grpc.secure_channel(",
        "add_servicer_to_server(", "_pb2_grpc", "context.set_code(",
        "stub.", "channel.unary_unary(",
    ],
    "GRAPHQL": [
        "graphene.objecttype", "graphene.schema", "schema.execute(",
        "strawberry.type", "strawberry.schema", "make_executable_schema(",
        "querytype(", "mutationtype(",
    ],
    "REST_CLIENT": [
        "requests.get(", "requests.post(", "requests.put(",
        "httpx.get(", "httpx.post(", "httpx.client(",
        "aiohttp.clientsession(", "session.get(", "session.post(",
        "urllib.request.urlopen(",
    ],
    "MESSAGING": [
        "@shared_task", "@app.task", ".delay(", ".apply_async(",
        "pika.blockingconnection(", "channel.basic_publish(",
        "kafkaproducer(", "producer.send(",
        "sqs.send_message(", "sns.publish(",
    ],
    "FILE_IO": [
        "csv.writer(", "to_csv(", "df.to_csv(",
        "json.dump(", "json.dumps(",
        "openpyxl.workbook(", "df.to_excel(",
        "xml.etree", "etree.tostring(",
        "boto3.client('s3')", 's3.put_object(',
        "blobserviceclient(", "storage.client(",
    ],
    "WEBSOCKET": [
        "await websocket.send(", "await websocket.recv(",
        "websocket.send_text(", "socketio.emit(", "sio.emit(",
        "self.write_message(", "channel_layer.group_send(",
        "websocketconsumer",
    ],
    "SEARCH_ENGINE": [
        "es.search(", "es.index(", "elasticsearch(",
        "opensearch(", "pysolr.solr(",
    ],
    "FILE_STORAGE": [
        "s3.upload_file(", "s3.put_object(", "s3.get_object(",
        "blob_client.upload_blob(", "blob.upload_from_file(",
    ],
}


def _ci(s):
    return s.lower() if s else ""


def _classify_child_type(method_dict):
    """Determine display type for a call-tree child node."""
    body  = _ci(method_dict.get("body_text", "") or
                method_dict.get("code_block", ""))
    auth  = method_dict.get("auth", [])
    name  = _ci(method_dict.get("name", ""))

    if auth:
        return "AUTH"
    if any(kw in name for kw in _AUTH_KEYWORDS):
        return "AUTH"

    for child_type, sigs in _CHILD_BODY_SIGNATURES.items():
        if any(sig in body for sig in sigs):
            return child_type

    return "BUSINESS"


def _build_calls(called_names, registry, chain, depth):
    """Recursively resolve called method names into child nodes."""
    if depth > MAX_DEPTH:
        return []

    calls      = []
    seen_child = set()

    for cname in called_names:
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

        raw_auth   = candidate.get("auth", [])
        auth_list  = [a if isinstance(a, str) else
                      (a.get("code_block") or a.get("type", ""))
                      for a in raw_auth]

        grandchildren = _build_calls(
            candidate.get("called_methods", []),
            registry, new_chain, depth + 1,
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


def build_iam_trees(entry_points, method_registry):
    """
    Build recursive IAM call trees for Python entry points.

    Parameters
    ----------
    entry_points    : list[dict]  – from extract_iam_entry_points()
    method_registry : dict        – { name: [method_dict, ...] }

    Returns
    -------
    list[dict]  – one root per entry point:
    {
      "name":          str,
      "endpoint_type": str,   # REST | ORM | SQL | LDAP | GRAPHQL | GRPC | …
      "file":          str,
      "route":         str | None,
      "method":        str | None,
      "code_block":    str,
      "auth":          [str],
      "calls":         [...]   # recursive
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

        raw_auth  = ep.get("auth", [])
        auth_list = [a if isinstance(a, str) else
                     (a.get("code_block") or a.get("type", ""))
                     for a in raw_auth]

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


# ── Backward-compatible flat map ──────────────────────────────────────────────

def build_exposure_map(endpoints, data_exposures):
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