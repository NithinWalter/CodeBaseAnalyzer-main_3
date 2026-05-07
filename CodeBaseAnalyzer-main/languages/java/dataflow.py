"""
dataflow.py  (languages/java)
------------------------------
Responsible for two things:

1. build_exposure_map()  – unchanged flat map for backward compatibility.
2. build_iam_trees()     – the primary new output: a list of IAM call trees.
   Each tree is rooted at a data-exposing entry point and has recursive
   `calls` arrays resolved across the entire codebase registry.
"""

# ══════════════════════════════════════════════════════════════════════════════
# CHILD NODE TYPE CLASSIFIER
# ══════════════════════════════════════════════════════════════════════════════

_AUTH_KEYWORDS = {
    "auth", "authenticate", "authoriz", "login", "logout", "signout",
    "token", "claim", "permission", "role", "secure", "principal",
    "password", "credential", "session", "verif", "check", "guard",
    "jwt", "oauth", "oidc", "saml", "bearer",   # ← add these
}

# Body tokens → child node type
_CHILD_BODY_SIGNATURES = {
    "SQL/ORM": [
        "entitymanager", "jdbctemplate", "namedparameterjdbctemplate",
        "drivermanager.getconnection", "executequery(", "executeupdate(",
        "preparestatement(", "resultset", "sqlsession.",
        ".findall()", ".findbyid(", ".save(", ".delete(", ".count(",
        "createquery(", "criteriabuilder", "criteriaquery",
        "dslcontext", "r2dbctemplate", "datasource.getconnection",
    ],
    "LDAP": [
        "ldaptemplate.search(", "ldaptemplate.find(", "ldaptemplate.bind(",
        "ldaptemplate.lookup(", "ldaptemplate.modify(",
        "initialdicontext(", "initialldapcontext(",
        "dircontext.search(", "ldapcontext.search(",
        "namingenumeration", "searchcontrols",
        "ldapconnection.search(",
    ],
    "ACTIVE_DIRECTORY": [
        "activedirectoryldapauthenticationprovider",
        "samaccountname", "useraccountcontrol",
        "objectclass=user", "objectclass=person",
        "principalcontext(", "userprincipal.findbyidentity(",
    ],
    "GRPC": [
        "streamobserver", "onnext(", "oncompleted(",
        "blockingstub.", "asyncstub.", "futurestub.",
        "managedchannel", "grpcchannel",
    ],
    "GRAPHQL": [
        "datafetchingenvironment", "datafetcher",
        "runtimewiring", "graphqlschema",
    ],
    "REST_CLIENT": [
        "resttemplate.", "webclient.", "httpclient.", "okhttp",
        "httpurlconnection", "feign", "retrofit",
    ],
    "MESSAGING": [
        "kafkatemplate.send(", "rabbittemplate.", "jmstemplate.",
        "sqsclient.sendmessage(",
    ],
    "FILE_IO": [
        "fileoutputstream(", "fileinputstream(",
        "csvprinter(", "xssfworkbook(", "jaxbcontext.",
        "ftpclient.", "channelsftp.", "ftpsclient.",
        "objectmapper.writevalue(",
    ],
    "WEBSOCKET": [
        "session.getbasicremote(", "session.getasyncremote(",
        "simpmessagingtemplate.convertandsend(",
    ],
}


def _ci(s):
    return s.lower() if s else ""


def _classify_child_type(method_dict):
    """
    Determine the display `type` for a non-entry-point child node.
    """
    body  = _ci(method_dict.get("body_text", "") or method_dict.get("code_block", ""))
    auth  = method_dict.get("auth", [])
    name  = _ci(method_dict.get("name", ""))

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


def _build_calls(called_method_names, registry, chain, depth):
    """
    For each name in `called_method_names`, look up the method in the registry,
    classify it, and recurse.

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

        # Use first candidate (single best match)
        candidate = candidates[0]
        child_key = (candidate.get("file", ""), cname)

        if child_key in seen_child or child_key in chain:
            # Circular reference stub
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

        # Normalise auth
        raw_auth   = candidate.get("auth", [])
        auth_list  = [a if isinstance(a, str) else
                      (a.get("code_block") or a.get("type", ""))
                      for a in raw_auth]

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


def build_iam_trees(entry_points, method_registry):
    """
    Build the complete IAM call tree list.

    Parameters
    ----------
    entry_points    : list[dict]   – records from extract_iam_entry_points(),
                                     each has `called_methods`
    method_registry : dict         – { method_name: [method_dict, ...] }
                                     built from extract_all_methods() across
                                     all files

    Returns
    -------
    list[dict]  – one root node per entry point:
    {
      "name":          str,         # method name
      "endpoint_type": str,         # REST | LDAP | JDBC | SOAP | GRPC | …
      "file":          str,         # source file path
      "route":         str | None,  # URL route (REST only)
      "method":        str | None,  # HTTP verb (REST only)
      "code_block":    str,         # full source with annotations
      "auth":          [str],       # auth annotations on this method
      "calls": [
        {
          "name":       str,
          "type":       str,        # AUTH | SQL/ORM | LDAP | GRPC | BUSINESS | …
          "file":       str,
          "code_block": str,
          "auth":       [str],
          "calls":      [...]       # recursive
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


# ══════════════════════════════════════════════════════════════════════════════
# BACKWARD-COMPATIBLE FLAT MAP
# ══════════════════════════════════════════════════════════════════════════════

def build_exposure_map(endpoints, data_exposures):
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