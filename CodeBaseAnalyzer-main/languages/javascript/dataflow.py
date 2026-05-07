"""
dataflow.py  (languages/javascript)
--------------------------------------
Mirrors the Java dataflow module exactly.  Only two public surfaces:

1. build_exposure_map()  – unchanged flat map for backward compatibility.
2. build_iam_trees()     – primary output: a list of IAM call trees rooted at
   data-exposing entry points, with recursive `calls` arrays resolved across
   the entire codebase registry.

Child-node type classification uses JavaScript-specific body signatures
(package names, API patterns) rather than Java class references.
"""

# ══════════════════════════════════════════════════════════════════════════════
# CHILD NODE TYPE CLASSIFIER
# ══════════════════════════════════════════════════════════════════════════════

_AUTH_KEYWORDS = {
    "auth", "authenticate", "authoriz", "login", "logout", "signout",
    "token", "claim", "permission", "role", "secure", "principal",
    "password", "credential", "session", "verif", "check", "guard",
    "jwt", "passport", "bcrypt", "argon", "hash",
    "oauth", "oidc", "saml", "bearer",           # ← add these
}

# Body tokens → child node type (case-insensitive substrings)
_CHILD_BODY_SIGNATURES = {
    "SQL/ORM": [
        # Raw SQL drivers
        "pool.query(", "client.query(", "connection.query(",
        "db.query(", "pool.execute(",
        # Sequelize
        ".findall(", ".findone(", ".findbypk(", ".create(",
        ".bulkcreate(", ".update(", ".destroy(", ".count(",
        "sequelize.query(",
        # TypeORM
        "getrepository(", "createquerybuilder(",
        "manager.query(",
        # Prisma
        "prisma.", "prisma.findmany(", "prisma.create(",
        "prisma.update(", "prisma.delete(",
        # Knex
        "knex(", ".select(", ".where(", ".insert(", ".table(",
        "model.query(",
    ],
    "NOSQL": [
        # MongoDB native / Mongoose
        "db.collection(", ".find(", ".findone(", ".insertone(",
        ".insertmany(", ".updateone(", ".updatemany(",
        ".deleteone(", ".deletemany(", ".aggregate(",
        "model.find(", "model.findbyid(", "model.create(",
        # Redis
        "redisclient.get(", "redisclient.set(", "client.get(", "client.set(",
        "redis.get(", "redis.set(",
        # Cassandra
        "client.execute(",
        # Elasticsearch
        "client.index(", "client.search(", "client.indices",
    ],
    "LDAP": [
        "ldap.createclient(", "client.search(", "client.bind(",
        "client.add(", "client.modify(", "client.del(",
        "ad.authenticate(", "ad.finduser(", "ad.getgroupmembership",
    ],
    "GRPC": [
        "server.addservice(", "server.bindasync(",
        "call.request", "callback(null,", "call.write(",
        "blockingstub.", "grpcchannel", "grpcobject",
    ],
    "GRAPHQL": [
        "apolloserver(", "typedefs", "resolvers",
        "graphql(schema", "graphqlhttp(",
        "info.fieldname", "context.dataloaders",
    ],
    "REST_CLIENT": [
        "axios.get(", "axios.post(", "axios.put(", "axios.delete(",
        "axios.patch(", "axios.create(", "axios.request(",
        "fetch(", "node-fetch", "got.get(", "got.post(",
        "superagent.get(", "superagent.post(",
        "http.request(", "https.request(",
    ],
    "MESSAGING": [
        "producer.send(", "kafkajs", "kafka.producer(", "kafka.consumer(",
        "channel.publish(", "channel.assertqueue(", "amqplib",
        "sns.publish(", "sqs.sendmessage(",
        "bull.add(", "bullmq",
    ],
    "FILE_IO": [
        "fs.writefile(", "fs.createwritestream(", "fs.appendfile(",
        "csvstringify(", "csv.stringify(", "createcsvwriter(",
        "xlsx.writefile(", "workbook.xlsx.writefile(",
        "xml2js.parsestring(", "xmlbuilder.create(",
        "json.stringify(",
    ],
    "CLOUD_STORAGE": [
        "s3.putobject(", "s3.getobject(", "s3.upload(",
        "new s3client(", "blobserviceclient",
        "containerclient.uploadblockblob(",
        "bucket.upload(", "bucket.file(",
    ],
    "WEBSOCKET": [
        "socket.emit(", "socket.on(", "io.to(", "io.emit(",
        "ws.send(", "ws.on(",
        "io.on('connection'", 'io.on("connection"',
        "wss.on('connection'",
    ],
    "SERVERLESS": [
        "exports.handler", "module.exports.handler",
        "context.succeed(", "context.fail(",
        "functions.https.onrequest(",
    ],
    "WEBHOOK": [
        "webhook", "x-hub-signature", "x-signature",
        "stripe-signature", "payload.event",
    ],
    "SOAP": [
        "soap.createserver(", "soap.listen(",
        "soap.createclient(", "soapclient.call(",
    ],
}


def _ci(s):
    return s.lower() if s else ""


def _classify_child_type(method_dict: dict) -> str:
    """
    Determine the display `type` for a non-entry-point child node.
    """
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
    For each name in `called_method_names`, look up the function in the
    registry, classify its type, and recurse.

    Parameters
    ----------
    called_method_names : list[str]
    registry            : { fn_name: [method_dict, ...] }
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

        # Normalise auth (could be strings or dicts)
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
    Build the complete IAM call tree list for JavaScript files.

    Parameters
    ----------
    entry_points    : list[dict]  – records from extract_iam_entry_points(),
                                    each has `called_methods`
    method_registry : dict        – { fn_name: [method_dict, ...] }
                                    built from extract_all_methods() across
                                    all .js / .jsx files

    Returns
    -------
    list[dict]  – one root node per entry point:
    {
      "name":          str,          # function name
      "endpoint_type": str,          # REST | GRAPHQL | GRPC | JDBC | NOSQL | …
      "file":          str,          # source file path
      "route":         str | None,   # URL route (REST only)
      "method":        str | None,   # HTTP verb (REST only)
      "code_block":    str,          # full source code
      "auth":          [str],        # auth hints on this function
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
    Unchanged flat map — kept for other languages and backward compatibility.
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