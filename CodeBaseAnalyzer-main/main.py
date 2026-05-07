from grok_client import get_grok_iga_recommendation
from fastapi import FastAPI, HTTPException
from github import clone_repo
from utils.file_loader import load_code_files
from core.engine import run_analysis
from pydantic import BaseModel
from typing import Any

# ── Java ──────────────────────────────────────────────────────────────────────
from languages.java import parser    as java_parser
from languages.java import extractor as java_extractor
from languages.java import dataflow  as java_dataflow

# ── Python ────────────────────────────────────────────────────────────────────
from languages.python import parser    as py_parser
from languages.python import extractor as py_extractor
from languages.python import dataflow  as py_dataflow

# ── JavaScript / JSX ─────────────────────────────────────────────────────────
from languages.javascript import parser    as js_parser
from languages.javascript import extractor as js_extractor
from languages.javascript import dataflow  as js_dataflow

# ── C# ────────────────────────────────────────────────────────────────────────
from languages.csharp import parser    as cs_parser
from languages.csharp import extractor as cs_extractor
from languages.csharp import dataflow  as cs_dataflow

app = FastAPI(title="Codebase IAM Analyzer", version="7.0")


# ── Language module wrappers ──────────────────────────────────────────────────

class JavaModule:
    parse                    = staticmethod(java_parser.parse)
    extract_endpoints        = staticmethod(java_extractor.extract_endpoints)
    extract_auth             = staticmethod(java_extractor.extract_auth)
    extract_data_exposures   = staticmethod(java_extractor.extract_data_exposures)
    build_exposure_map       = staticmethod(java_dataflow.build_exposure_map)
    extract_iam_entry_points = staticmethod(java_extractor.extract_iam_entry_points)
    extract_all_methods      = staticmethod(java_extractor.extract_all_methods)
    build_iam_trees          = staticmethod(java_dataflow.build_iam_trees)


class PythonModule:
    parse                    = staticmethod(py_parser.parse)
    extract_endpoints        = staticmethod(py_extractor.extract_endpoints)
    extract_auth             = staticmethod(py_extractor.extract_auth)
    extract_data_exposures   = staticmethod(py_extractor.extract_data_exposures)
    build_exposure_map       = staticmethod(py_dataflow.build_exposure_map)
    extract_iam_entry_points = staticmethod(py_extractor.extract_iam_entry_points)
    extract_all_methods      = staticmethod(py_extractor.extract_all_methods)
    build_iam_trees          = staticmethod(py_dataflow.build_iam_trees)


class JavaScriptModule:
    parse                    = staticmethod(js_parser.parse)
    extract_endpoints        = staticmethod(js_extractor.extract_endpoints)
    extract_auth             = staticmethod(js_extractor.extract_auth)
    extract_data_exposures   = staticmethod(js_extractor.extract_data_exposures)
    build_exposure_map       = staticmethod(js_dataflow.build_exposure_map)
    extract_iam_entry_points = staticmethod(js_extractor.extract_iam_entry_points)
    extract_all_methods      = staticmethod(js_extractor.extract_all_methods)
    build_iam_trees          = staticmethod(js_dataflow.build_iam_trees)
    extract_all       = staticmethod(js_extractor.extract_all)


class CSharpModule:
    parse                    = staticmethod(cs_parser.parse)
    extract_endpoints        = staticmethod(cs_extractor.extract_endpoints)
    extract_auth             = staticmethod(cs_extractor.extract_auth)
    extract_data_exposures   = staticmethod(cs_extractor.extract_data_exposures)
    build_exposure_map       = staticmethod(cs_dataflow.build_exposure_map)
    extract_iam_entry_points = staticmethod(cs_extractor.extract_iam_entry_points)
    extract_all_methods      = staticmethod(cs_extractor.extract_all_methods)
    build_iam_trees          = staticmethod(cs_dataflow.build_iam_trees)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _run_for_all_languages(files: list) -> dict:
    result = {}

    java_files = [(p, c) for p, c in files if p.endswith(".java")]
    py_files   = [(p, c) for p, c in files if p.endswith(".py")]
    js_files   = [(p, c) for p, c in files if p.endswith((".js", ".jsx"))]
    cs_files   = [(p, c) for p, c in files if p.endswith(".cs")]

    if java_files:
        result["java"]       = run_analysis(java_files, JavaModule)
    if py_files:
        result["python"]     = run_analysis(py_files,   PythonModule)
    if js_files:
        result["javascript"] = run_analysis(js_files,   JavaScriptModule)
    if cs_files:
        result["csharp"]     = run_analysis(cs_files,   CSharpModule)

    return result


def _parse_keywords(raw: str) -> list[str]:
    """
    Split a comma-separated keyword string into a clean lowercase list.
    Single keyword strings are returned as a one-element list.
    Empty tokens (e.g. trailing comma) are dropped.
    """
    return [k.strip().lower() for k in raw.split(",") if k.strip()]


# ── Tree traversal helpers ────────────────────────────────────────────────────

def _tree_has_keyword(node: dict, kw: str) -> bool:
    """Return True if kw appears anywhere in the node or its subtree."""
    if kw in (node.get("code_block") or "").lower():
        return True
    return any(_tree_has_keyword(c, kw) for c in node.get("calls", []))


def _tree_has_any_keyword(node: dict, keywords: list[str]) -> bool:
    """
    Return True if at least ONE keyword from the list appears anywhere
    in the node's code_block or recursively in any child node.
    """
    body = (node.get("code_block") or "").lower()
    if any(kw in body for kw in keywords):
        return True
    return any(_tree_has_any_keyword(c, keywords) for c in node.get("calls", []))


def _collect_tree_text(node: dict) -> str:
    """
    Concatenate all code_block text from a node and every descendant
    into a single lowercase string for whole-tree keyword checks.
    """
    text = (node.get("code_block") or "").lower()
    for child in node.get("calls", []):
        text += " " + _collect_tree_text(child)
    return text


def _tree_has_all_keywords(node: dict, keywords: list[str]) -> bool:
    """
    Return True if ALL keywords appear somewhere across the node's entire
    subtree (each keyword may be in a different child node).
    """
    combined = _collect_tree_text(node)
    return all(kw in combined for kw in keywords)


def _collect_matching_code_blocks(
    node: dict,
    keywords: list[str],
    results: list,
    visited: set,
) -> None:
    """
    Walk every node in the tree recursively and collect code_block records
    whose code_block contains at least one keyword.

    Deduplication is done via (name, file) identity to avoid emitting
    the same function twice when it appears in multiple call trees.
    """
    name      = node.get("name") or node.get("handler", "")
    file_path = node.get("file", "")
    body      = node.get("code_block") or ""
    key       = (name, file_path)

    if key not in visited and body and any(kw in body.lower() for kw in keywords):
        visited.add(key)
        results.append({
            "name":       name,
            "file":       file_path,
            "type":       node.get("endpoint_type") or node.get("type", ""),
            "code_block": body,
        })

    for child in node.get("calls", []):
        _collect_matching_code_blocks(child, keywords, results, visited)


# ── Filter helpers applied per language result ────────────────────────────────

def _filter_result_any(result: dict, keywords: list[str]) -> dict:
    """Keep records that contain at least one of the keywords."""
    result["endpoints"] = [
        ep for ep in result.get("endpoints", [])
        if any(kw in (ep.get("code_block") or "").lower() for kw in keywords)
    ]
    result["data_exposures"] = [
        exp for exp in result.get("data_exposures", [])
        if any(kw in (exp.get("code_block") or "").lower() for kw in keywords)
    ]
    result["exposure_map"] = {
        k: v for k, v in result.get("exposure_map", {}).items()
        if any(kw in (v.get("code_block") or "").lower() for kw in keywords)
    }
    result["iam_trees"] = [
        t for t in result.get("iam_trees", [])
        if _tree_has_any_keyword(t, keywords)
    ]
    return result


def _filter_result_all(result: dict, keywords: list[str]) -> dict:
    """Keep records that contain ALL of the keywords."""
    result["endpoints"] = [
        ep for ep in result.get("endpoints", [])
        if all(kw in (ep.get("code_block") or "").lower() for kw in keywords)
    ]
    result["data_exposures"] = [
        exp for exp in result.get("data_exposures", [])
        if all(kw in (exp.get("code_block") or "").lower() for kw in keywords)
    ]
    result["exposure_map"] = {
        k: v for k, v in result.get("exposure_map", {}).items()
        if all(kw in (v.get("code_block") or "").lower() for kw in keywords)
    }
    result["iam_trees"] = [
        t for t in result.get("iam_trees", [])
        if _tree_has_all_keywords(t, keywords)
    ]
    return result


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(repo_url: str):
    """Run full analysis and return all results for every detected language."""
    try:
        repo_path = clone_repo(repo_url)
        files     = load_code_files(repo_path)
        return _run_for_all_languages(files)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze/search")
def analyze_search(repo_url: str, keyword: str):
    """
    Legacy single-keyword search.
    Returns data-exposing functions whose code_block (or any node in their
    call subtree) contains the keyword.
    """
    try:
        repo_path = clone_repo(repo_url)
        files     = load_code_files(repo_path)
        kw        = keyword.strip().lower()
        raw       = _run_for_all_languages(files)

        filtered = {}
        for lang, result in raw.items():
            result["endpoints"] = [
                ep for ep in result.get("endpoints", [])
                if kw in (ep.get("code_block") or "").lower()
            ]
            result["data_exposures"] = [
                exp for exp in result.get("data_exposures", [])
                if kw in (exp.get("code_block") or "").lower()
            ]
            result["exposure_map"] = {
                k: v for k, v in result.get("exposure_map", {}).items()
                if kw in (v.get("code_block") or "").lower()
            }
            result["iam_trees"] = [
                t for t in result.get("iam_trees", [])
                if _tree_has_keyword(t, kw)
            ]
            filtered[lang] = result

        return filtered
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/iam")
def analyze_iam(repo_url: str):
    """
    Run full analysis and return only iam_trees per language
    """
    try:
        repo_path = clone_repo(repo_url)
        files     = load_code_files(repo_path)
        raw       = _run_for_all_languages(files)

        output = {}
        for lang, result in raw.items():
            if isinstance(result, dict) and "iam_trees" in result:
                output[lang] = {
                    "iam_trees": result.get("iam_trees", [])
                }

        return output

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/search/any")
def analyze_search_any(repo_url: str, keywords: str):
    """
    Multi-keyword OR search.

    `keywords` is a comma-separated string, e.g. "email,password,token"
    or a single word "token".

    Returns data-exposing functions (endpoints, data_exposures, exposure_map,
    iam_trees) where the function itself *or any node in its call subtree*
    contains **at least one** of the supplied keywords.
    """
    try:
        kw_list = _parse_keywords(keywords)
        if not kw_list:
            raise HTTPException(status_code=400, detail="No valid keywords provided.")

        repo_path = clone_repo(repo_url)
        files     = load_code_files(repo_path)
        raw       = _run_for_all_languages(files)

        return {
            lang: _filter_result_any(result, kw_list)
            for lang, result in raw.items()
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze/search/all")
def analyze_search_all(repo_url: str, keywords: str):
    """
    Multi-keyword AND search.

    `keywords` is a comma-separated string, e.g. "email,password,token"
    or a single word "token".

    Returns data-exposing functions (endpoints, data_exposures, exposure_map,
    iam_trees) where **all** supplied keywords are present somewhere across
    the function and its entire call subtree (each keyword may appear in
    a different child node).
    """
    try:
        kw_list = _parse_keywords(keywords)
        if not kw_list:
            raise HTTPException(status_code=400, detail="No valid keywords provided.")

        repo_path = clone_repo(repo_url)
        files     = load_code_files(repo_path)
        raw       = _run_for_all_languages(files)

        return {
            lang: _filter_result_all(result, kw_list)
            for lang, result in raw.items()
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze/search/code")
def analyze_search_code(repo_url: str, keywords: str):
    """
    Code-block keyword search across all nodes.

    `keywords` is a comma-separated string, e.g. "email,password,token"
    or a single word "token".

    Walks every node in every call tree (root entry points and all recursive
    child nodes) as well as flat endpoints and data_exposures, and returns
    a deduplicated list of code_block records whose source text contains
    at least one of the supplied keywords.

    Response shape per language:
    {
      "<lang>": {
        "matches": [
          {
            "name":       str,   # function / method name
            "file":       str,   # source file path
            "type":       str,   # endpoint_type or call node type
            "code_block": str    # full source text of the function
          },
          ...
        ]
      }
    }
    """
    try:
        kw_list = _parse_keywords(keywords)
        if not kw_list:
            raise HTTPException(status_code=400, detail="No valid keywords provided.")

        repo_path = clone_repo(repo_url)
        files     = load_code_files(repo_path)
        raw       = _run_for_all_languages(files)

        output = {}
        for lang, result in raw.items():
            matches  = []
            visited  = set()   # (name, file) dedup guard

            # ── Walk IAM call trees (includes all child nodes recursively) ──
            for tree in result.get("iam_trees", []):
                _collect_matching_code_blocks(tree, kw_list, matches, visited)

            # ── Flat endpoints not already captured via iam_trees ────────────
            for ep in result.get("endpoints", []):
                name      = ep.get("handler", "")
                file_path = ep.get("file", "")
                body      = ep.get("code_block") or ""
                key       = (name, file_path)
                if key not in visited and body and any(kw in body.lower() for kw in kw_list):
                    visited.add(key)
                    matches.append({
                        "name":       name,
                        "file":       file_path,
                        "type":       ep.get("method", "REST"),
                        "code_block": body,
                    })

            # ── Flat data_exposures not already captured ─────────────────────
            for exp in result.get("data_exposures", []):
                name      = exp.get("handler", "")
                file_path = exp.get("file", "")
                body      = exp.get("code_block") or ""
                key       = (name, file_path)
                if key not in visited and body and any(kw in body.lower() for kw in kw_list):
                    visited.add(key)
                    matches.append({
                        "name":       name,
                        "file":       file_path,
                        "type":       ", ".join(exp.get("exposure_types", [])),
                        "code_block": body,
                    })

            output[lang] = {"matches": matches}

        return output
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# ── IAM Tree Cleaner ─────────────────────────────────────────────────────────

class IAMTreeInput(BaseModel):
    analysis: Any


def _clean_node(node: dict) -> dict:
    """
    Recursively clean IAM tree node:
    - remove code_block
    - remove file
    - remove empty fields
    """
    if not isinstance(node, dict):
        return node

    cleaned = {}

    for key, value in node.items():
        #  remove unwanted fields
        if key in ("code_block", "file"):
            continue

        #  recursive cleaning
        if isinstance(value, dict):
            value = _clean_node(value)
        elif isinstance(value, list):
            value = [_clean_node(v) for v in value if v not in (None, "", [], {})]

        #  remove empty values
        if value in (None, "", [], {}):
            continue

        cleaned[key] = value

    return cleaned


def _extract_clean_iam_trees(analysis: Any) -> dict:
    """
    Extract and clean iam_trees from any analysis format
    """
    output = {}

    if not isinstance(analysis, dict):
        return {}

    for lang, result in analysis.items():
        if not isinstance(result, dict):
            continue

        trees = result.get("iam_trees", [])
        cleaned_trees = [_clean_node(t) for t in trees if t]

        if cleaned_trees:
            output[lang] = {"iam_trees": cleaned_trees}

    return output


@app.post("/iam/clean")
def clean_iam_tree(body: IAMTreeInput):
    """
    Input: full analysis JSON
    Output: cleaned IAM trees only
    """
    try:
        cleaned = _extract_clean_iam_trees(body.analysis)
        return cleaned
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/iam/recommend")
def recommend_iam(body: IAMTreeInput):
    try:
        
        cleaned_data = _extract_clean_iam_trees(body.analysis)

        #  Send directly to Grok
        result = get_grok_iga_recommendation(cleaned_data)

        return {
            "status": "success",
            "recommendation": result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))    