from typing import List, Optional, Any


def create_auth(type_, file, code_block=None):
    return {
        "type":       type_,
        "file":       file,
        "code_block": code_block,
    }


def create_endpoint_node(name, endpoint_type, file, code_block,
                         route=None, http_method=None, auth=None, calls=None):
    """
    Root node of an IAM call tree — a data-exposing entry point.

    Fields
    ------
    name           – method / function name
    endpoint_type  – IAM category: REST | SOAP | GRPC | GRAPHQL | JDBC | JPA |
                     LDAP | ACTIVE_DIRECTORY | CSV | EXCEL | JSON_EXPORT | XML |
                     FTP | SFTP | FTPS | REST_OUTBOUND | SCIM | OAUTH2 | OIDC |
                     SAML | WEBSOCKET | MESSAGING
    file           – source file path
    code_block     – full method source text including annotations
    route          – URL route (REST / SOAP / GraphQL / GRPC / WebSocket entry points)
    http_method    – HTTP verb (REST only)
    auth           – list of auth annotation strings on this method
    calls          – list of child call_node dicts (recursive)
    """
    return {
        "name":          name,
        "endpoint_type": endpoint_type,
        "file":          file,
        "route":         route,
        "method":        http_method,
        "code_block":    code_block,
        "auth":          auth or [],
        "calls":         calls or [],
    }


def create_data_exposure(handler, file, exposure_types=None, code_block=None, auth=None):
    """
    A non-REST data exposure record — JDBC, JPA, LDAP, CSV, EXCEL, etc.

    Fields
    ------
    handler        – method / function name
    file           – source file path
    exposure_types – list of IAM exposure type labels (e.g. ["JDBC"], ["CSV"])
    code_block     – full method source text
    auth           – list of auth annotation dicts or strings on this method
    """
    return {
        "handler":        handler,
        "file":           file,
        "exposure_types": exposure_types or [],
        "code_block":     code_block,
        "auth":           auth or [],
    }


def create_call_node(name, call_type, file, code_block, auth=None, calls=None):
    """
    A child node in an IAM call tree — one function called by its parent.

    Fields
    ------
    name       – method / function name
    call_type  – AUTH | SQL/ORM | LDAP | GRPC | GRAPHQL | REST_CLIENT |
                 MESSAGING | FILE_IO | BUSINESS
    file       – source file path
    code_block – full method source text
    auth       – list of auth annotation strings on this method
    calls      – list of deeper child call_node dicts
    """
    return {
        "name":       name,
        "type":       call_type,
        "file":       file,
        "code_block": code_block,
        "auth":       auth or [],
        "calls":      calls or [],
    }