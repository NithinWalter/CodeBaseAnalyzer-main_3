# engine.py – language-agnostic analysis runner.
#
# KEY OPTIMISATIONS vs the original:
#
# 1. Each file is parsed ONCE (was parsed twice: Pass 1 + Pass 2).
# 2. extract_all() is used when the language module provides it, doing a
#    single tree traversal that produces entry_points, all_methods,
#    endpoints, data_exposures, and auth together.  This eliminates the
#    original 3× re-extraction pattern:
#      extract_all_methods() + extract_iam_entry_points()
#      + extract_endpoints() (called extract_iam_entry_points again)
#      + extract_data_exposures() (called extract_iam_entry_points again)
# 3. Files are processed in parallel via ThreadPoolExecutor.

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

# Cap workers: tree-sitter C extension releases the GIL during parsing,
# so threads give real parallelism for the CPU-bound parse step.
_MAX_WORKERS = min(8, (os.cpu_count() or 4))


def _process_file(path, code, language_module, has_iam, has_extract_all):
    """
    Parse and extract everything from a single file.

    Returns a plain dict so results can be merged by the caller without
    any shared-state concerns.
    """
    tree = language_module.parse(code)   # ← ONE parse per file

    if has_iam and has_extract_all:
        # ── Fast path: single tree walk, all outputs at once ─────────────────
        result = language_module.extract_all(tree, code, path)
        return {
            "entry_points":   result["entry_points"],
            "all_methods":    result["all_methods"],
            "endpoints":      result["endpoints"],
            "data_exposures": result["data_exposures"],
            "auth":           result["auth"],
        }

    elif has_iam:
        # ── Slower path: separate calls but still single parse ────────────────
        entry_points   = language_module.extract_iam_entry_points(tree, code, path)
        all_methods    = language_module.extract_all_methods(tree, code, path)
        endpoints      = language_module.extract_endpoints(tree, code, path)
        data_exposures = language_module.extract_data_exposures(tree, code, path)
        auth           = language_module.extract_auth(tree, code, path)
        return {
            "entry_points":   entry_points,
            "all_methods":    all_methods,
            "endpoints":      endpoints,
            "data_exposures": data_exposures,
            "auth":           auth,
        }

    else:
        # ── Non-IAM language ─────────────────────────────────────────────────
        return {
            "entry_points":   [],
            "all_methods":    [],
            "endpoints":      language_module.extract_endpoints(tree, code, path),
            "data_exposures": language_module.extract_data_exposures(tree, code, path),
            "auth":           language_module.extract_auth(tree, code, path),
        }


def run_analysis(files, language_module):
    try:
        has_iam = (
            hasattr(language_module, "extract_iam_entry_points") and
            hasattr(language_module, "extract_all_methods") and
            hasattr(language_module, "build_iam_trees")
        )
        # extract_all() is the new fast combined path (Java already has it;
        # add it to other language modules the same way when you're ready).
        has_extract_all = hasattr(language_module, "extract_all")

        method_registry  = {}   # { method_name: [method_dict, ...] }
        all_entry_points = []
        endpoints        = []
        auth             = []
        data_exposures   = []

        # ── Parallel per-file processing ──────────────────────────────────────
        # Submit all files to the thread pool.  tree-sitter's C extension
        # releases the GIL during parsing, giving real concurrency there.
        # The Python-level dict building runs with GIL but is interleaved
        # with other threads' C-extension work, so we still win overall.
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            future_to_path = {
                executor.submit(
                    _process_file,
                    path, code, language_module, has_iam, has_extract_all
                ): path
                for path, code in files
            }

            for future in as_completed(future_to_path):
                try:
                    r = future.result()
                except Exception as exc:
                    path = future_to_path[future]
                    print(f"WARNING: skipping {path} – {exc}")
                    continue

                # Merge method registry
                for m in r["all_methods"]:
                    method_registry.setdefault(m["name"], []).append(m)

                all_entry_points.extend(r["entry_points"])
                endpoints.extend(r["endpoints"])
                data_exposures.extend(r["data_exposures"])
                auth.extend(r["auth"])

        # ── Dedup REST endpoints ──────────────────────────────────────────────
        unique = {}
        for ep in endpoints:
            key = (ep.get("method"), ep.get("route"), ep.get("file"))
            if key not in unique:
                unique[key] = ep
            else:
                existing_auth = {
                    a if isinstance(a, str) else a.get("type", "")
                    for a in unique[key]["auth"]
                }
                for a in ep["auth"]:
                    ak = a if isinstance(a, str) else a.get("type", "")
                    if ak not in existing_auth:
                        unique[key]["auth"].append(a)
                        existing_auth.add(ak)
        endpoints = list(unique.values())

        # ── Dedup data exposures ──────────────────────────────────────────────
        seen_exp = {}
        for exp in data_exposures:
            key = (
                exp.get("handler"),
                exp.get("file"),
                tuple(sorted(exp.get("exposure_types", []))),
            )
            if key not in seen_exp:
                seen_exp[key] = exp
            else:
                existing = {
                    a.get("type") if isinstance(a, dict) else a
                    for a in seen_exp[key]["auth"]
                }
                for a in exp["auth"]:
                    ak = a.get("type") if isinstance(a, dict) else a
                    if ak not in existing:
                        seen_exp[key]["auth"].append(a)
                        existing.add(ak)
        data_exposures = list(seen_exp.values())

        # ── Flat exposure map (all languages) ─────────────────────────────────
        exposure_map = language_module.build_exposure_map(endpoints, data_exposures)

        # ── IAM call trees (languages with IAM support) ───────────────────────
        iam_trees = []
        print("DEBUG total entry_points:", len(all_entry_points))
        if has_iam and all_entry_points:
            iam_trees = language_module.build_iam_trees(
                all_entry_points, method_registry
            )

        return {
            "endpoints":      endpoints,
            "data_exposures": data_exposures,
            "exposure_map":   exposure_map,
            "auth":           auth,
            "iam_trees":      iam_trees,
        }

    except Exception as e:
        print("ERROR in run_analysis:", str(e))
        return {"error": str(e)}