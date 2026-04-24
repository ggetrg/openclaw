#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any


TEXT_EXTS = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".html",
    ".py",
    ".go",
    ".java",
    ".kt",
    ".rb",
    ".rs",
    ".php",
    ".c",
    ".h",
    ".hpp",
    ".cpp",
    ".swift",
    ".m",
    ".mm",
    ".cs",
    ".scala",
    ".lua",
    ".sh",
    ".sql",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
}
IGNORE_DIRS = {
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".turbo",
    ".idea",
    ".vscode",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "coverage",
    ".venv",
    "venv",
    "vendor",
    "Pods",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def try_read_text(path: Path, max_bytes: int = 250_000) -> str:
    try:
        raw = path.read_bytes()
    except Exception:
        return ""
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("latin-1")
        except Exception:
            return ""


def should_include(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTS:
        return True
    if path.name in {"Dockerfile", "Makefile"}:
        return True
    return False


def line_number_from_index(content: str, idx: int) -> int:
    return content.count("\n", 0, idx) + 1


def infer_module(rel_path: str) -> str:
    parts = rel_path.split("/")
    if len(parts) >= 3 and parts[0] == "src" and parts[1] in {"views", "components", "services", "stores", "constants"}:
        return "/".join(parts[:3])
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0] if parts else "."


def extract_symbol_entries(content: str) -> list[dict[str, Any]]:
    patterns = [
        r"^\s*class\s+([A-Za-z_]\w*)",
        r"^\s*def\s+([A-Za-z_]\w*)",
        r"^\s*function\s+([A-Za-z_]\w*)",
        r"^\s*const\s+([A-Za-z_]\w*)\s*=\s*\(",
        r"^\s*export\s+function\s+([A-Za-z_]\w*)",
        r"^\s*export\s+class\s+([A-Za-z_]\w*)",
        r"^\s*interface\s+([A-Za-z_]\w*)",
        r"^\s*type\s+([A-Za-z_]\w*)\s*=",
        r"^\s*func\s+([A-Za-z_]\w*)",
    ]
    entries: list[dict[str, Any]] = []
    seen = set()
    for p in patterns:
        for m in re.finditer(p, content, flags=re.MULTILINE):
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            entries.append({"name": name, "line": line_number_from_index(content, m.start())})
            if len(entries) >= 40:
                return entries
    return entries


def extract_symbols(content: str, suffix: str) -> list[str]:
    _ = suffix
    return [x["name"] for x in extract_symbol_entries(content)]


def compact_unique(items: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def extract_operations(content: str, rel_path: str, suffix: str) -> list[str]:
    operations: list[str] = []
    handler_patterns = [
        r"\b(handle[A-Z][A-Za-z0-9_]*)\b",
        r"\b(on[A-Z][A-Za-z0-9_]*)\b",
        r"\b(start[A-Z][A-Za-z0-9_]*)\b",
        r"\b(stop[A-Z][A-Za-z0-9_]*)\b",
        r"\b(play[A-Z][A-Za-z0-9_]*)\b",
        r"\b(pause[A-Z][A-Za-z0-9_]*)\b",
    ]
    for pattern in handler_patterns:
        operations.extend(re.findall(pattern, content))
    source_like = suffix in {".ts", ".tsx", ".js", ".jsx", ".vue", ".py", ".go", ".java"}
    if source_like and re.search(r"\b(submit|save|delete|update|create)\b", content.lower()):
        operations.append("数据提交与变更")
    return compact_unique(operations, 12)


def extract_data_specs(content: str) -> list[str]:
    specs: list[str] = []
    for pattern in [
        r"\b(?:interface|type)\s+([A-Za-z_]\w*(?:Req|Request|Resp|Response|DTO|Payload|Params))\b",
        r"\b([A-Za-z_]\w*Schema)\b",
        r"\b([A-Za-z_]\w*Config)\b",
        r"\b([A-Za-z_]\w*State)\b",
    ]:
        specs.extend(re.findall(pattern, content))
    return compact_unique(specs, 16)


def extract_api_endpoints(content: str) -> list[str]:
    endpoints: list[str] = []
    endpoints.extend(re.findall(r"['\"](/api/[A-Za-z0-9_\-/]+)['\"]", content))
    endpoints.extend(re.findall(r"(?:get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]\s*[\),]", content, flags=re.IGNORECASE))
    return compact_unique(endpoints, 12)


def extract_import_specs(content: str) -> list[str]:
    specs: list[str] = []
    specs.extend(re.findall(r"from\s+['\"]([^'\"]+)['\"]", content))
    specs.extend(re.findall(r"import\s+['\"]([^'\"]+)['\"]", content))
    specs.extend(re.findall(r"import\(\s*['\"]([^'\"]+)['\"]\s*\)", content))
    specs.extend(re.findall(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)", content))
    specs = [x for x in specs if x.startswith(".") or x.startswith("@/") or x.startswith("src/")]
    return compact_unique(specs, 40)


def extract_call_candidates(content: str) -> list[str]:
    candidates = re.findall(r"\b([A-Za-z_]\w*)\s*\(", content)
    stop_words = {
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "return",
        "new",
        "function",
        "defineProps",
        "defineEmits",
        "ref",
        "reactive",
        "computed",
        "watch",
        "onMounted",
        "onUnmounted",
        "setTimeout",
        "setInterval",
        "clearTimeout",
        "clearInterval",
    }
    filtered = [x for x in candidates if len(x) >= 3 and x not in stop_words]
    return compact_unique(filtered, 80)


def extract_unit_conversions(content: str) -> list[str]:
    rules: list[str] = []
    for src, dst, _ in re.findall(r"([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*[*\/]\s*(1000|100|60|3600)", content):
        rules.append(f"{src}->{dst}")
    for src, dst in re.findall(r"([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*[*\/]\s*0\.0*1", content):
        rules.append(f"{src}->{dst}")
    unit_tokens = re.findall(
        r"(?<![a-z0-9])(ppm|ppb|μg/m3|ug/m3|mg/m3|m/s|km/h|kmh|℃|°c|celsius|fahrenheit|kpa|pa|g/s|kg/h|m3/h)(?![a-z0-9])",
        content.lower(),
    )
    for token in unit_tokens:
        if token in {"℃", "°c", "celsius", "fahrenheit"}:
            rules.append("温度单位转换")
        elif token in {"m/s", "km/h", "kmh"}:
            rules.append("速度单位转换")
        elif token in {"ppm", "ppb", "μg/m3", "ug/m3", "mg/m3"}:
            rules.append("浓度单位转换")
        else:
            rules.append(f"单位:{token}")
    if re.search(r"\b(getUnit|unitMap|unitType|unitLabel|changeUnit|convertUnit)\b", content):
        rules.append("单位映射/转换函数")
    return compact_unique(rules, 16)


def extract_state_links(content: str) -> list[str]:
    links: list[str] = []
    links.extend(re.findall(r"\buse([A-Z][A-Za-z0-9_]*Store)\b", content))
    links.extend(re.findall(r"\bdefineStore\(\s*['\"]([^'\"]+)['\"]", content))
    links.extend(re.findall(r"\bstoreToRefs\(\s*([A-Za-z_]\w*)\s*\)", content))
    links.extend(re.findall(r"\b([A-Za-z_]\w*Store)\b", content))
    links.extend(re.findall(r"\b([A-Za-z_]\w*State)\b", content))
    links.extend(re.findall(r"\b(localStorage|sessionStorage|pinia|vuex)\b", content))
    links.extend(re.findall(r"\b(commit|dispatch)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content))
    normalized: list[str] = []
    for item in links:
        if isinstance(item, tuple):
            normalized.append("::".join([x for x in item if x]))
        else:
            normalized.append(item)
    return compact_unique(normalized, 24)


def infer_tags(rel_path: str) -> list[str]:
    lower = rel_path.lower()
    tags = []
    for k in [
        "api",
        "route",
        "controller",
        "service",
        "model",
        "schema",
        "db",
        "repo",
        "store",
        "component",
        "view",
        "page",
        "hook",
        "test",
        "spec",
        "config",
        "script",
    ]:
        if k in lower:
            tags.append(k)
    return tags[:8]


def scan_project(
    project_path: Path,
    exclude_prefixes: list[str] | None = None,
    prev_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    modules: dict[str, dict[str, Any]] = {}
    excludes = exclude_prefixes or []
    prev_map = prev_map or {}
    reuse_count = 0
    update_count = 0
    for root, dirs, filenames in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".DS")]
        root_path = Path(root)
        for name in filenames:
            p = root_path / name
            if not should_include(p):
                continue
            rel = str(p.relative_to(project_path))
            if any(rel == ex or rel.startswith(ex + "/") for ex in excludes):
                continue
            stat = p.stat()
            size = stat.st_size
            mtime_ns = int(stat.st_mtime_ns)
            prev_meta = prev_map.get(rel)
            prev_meta_ready = prev_meta and all(
                k in prev_meta
                for k in ["import_specs", "call_candidates", "symbol_entries", "unit_conversions", "state_links"]
            )
            if prev_meta_ready and prev_meta.get("bytes") == size and prev_meta.get("mtime_ns") == mtime_ns:
                meta = dict(prev_meta)
                reuse_count += 1
            else:
                content = try_read_text(p)
                if not content:
                    continue
                line_count = content.count("\n") + 1
                digest = sha1_text(content)
                symbol_entries = extract_symbol_entries(content)
                symbols = [x["name"] for x in symbol_entries]
                tags = infer_tags(rel)
                module = infer_module(rel)
                operations = extract_operations(content, rel, p.suffix.lower())
                data_specs = extract_data_specs(content)
                api_endpoints = extract_api_endpoints(content)
                import_specs = extract_import_specs(content)
                call_candidates = extract_call_candidates(content)
                unit_conversions = extract_unit_conversions(content)
                state_links = extract_state_links(content)
                meta = {
                    "path": rel,
                    "module": module,
                    "ext": p.suffix.lower(),
                    "bytes": size,
                    "mtime_ns": mtime_ns,
                    "lines": line_count,
                    "sha1": digest,
                    "symbols": symbols,
                    "symbol_entries": symbol_entries[:16],
                    "tags": tags,
                    "operations": operations,
                    "data_specs": data_specs,
                    "api_endpoints": api_endpoints,
                    "import_specs": import_specs,
                    "call_candidates": call_candidates,
                    "unit_conversions": unit_conversions,
                    "state_links": state_links,
                }
                update_count += 1
            files.append(meta)
            module = meta.get("module") or infer_module(rel)
            mod = modules.setdefault(
                module,
                {
                    "module": module,
                    "files": 0,
                    "lines": 0,
                    "top_tags": {},
                    "top_symbols": [],
                    "top_operations": [],
                    "data_specs": [],
                    "unit_conversions": [],
                    "state_links": [],
                },
            )
            mod["files"] += 1
            mod["lines"] += meta.get("lines", 0)
            for t in meta.get("tags", []):
                mod["top_tags"][t] = mod["top_tags"].get(t, 0) + 1
            mod["top_symbols"].extend(meta.get("symbols", [])[:3])
            mod["top_operations"].extend(meta.get("operations", [])[:3])
            mod["data_specs"].extend(meta.get("data_specs", [])[:3])
            mod["unit_conversions"].extend(meta.get("unit_conversions", [])[:3])
            mod["state_links"].extend(meta.get("state_links", [])[:4])
    module_list = []
    for _, m in modules.items():
        sorted_tags = sorted(m["top_tags"].items(), key=lambda x: x[1], reverse=True)
        m["top_tags"] = [k for k, _ in sorted_tags[:8]]
        m["top_symbols"] = compact_unique(m["top_symbols"], 12)
        m["top_operations"] = compact_unique(m["top_operations"], 10)
        m["data_specs"] = compact_unique(m["data_specs"], 10)
        m["unit_conversions"] = compact_unique(m["unit_conversions"], 10)
        m["state_links"] = compact_unique(m["state_links"], 12)
        module_list.append(m)
    module_list.sort(key=lambda x: x["lines"], reverse=True)
    files.sort(key=lambda x: x["lines"], reverse=True)
    return {
        "generated_at": utc_now(),
        "project_path": str(project_path),
        "file_count": len(files),
        "total_lines": sum(f["lines"] for f in files),
        "scan_stats": {"reused_files": reuse_count, "updated_files": update_count},
        "modules": module_list,
        "files": files,
    }


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_diff(prev: dict[str, Any], curr: dict[str, Any]) -> dict[str, Any]:
    prev_map = {f["path"]: f for f in prev.get("files", [])}
    curr_map = {f["path"]: f for f in curr.get("files", [])}
    added = [p for p in curr_map if p not in prev_map]
    removed = [p for p in prev_map if p not in curr_map]
    changed = [p for p in curr_map if p in prev_map and curr_map[p]["sha1"] != prev_map[p]["sha1"]]
    return {
        "at": curr["generated_at"],
        "added": sorted(added),
        "removed": sorted(removed),
        "changed": sorted(changed),
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
    }


def write_module_knowledge(kb_root: Path, curr: dict[str, Any], diff: dict[str, Any]) -> None:
    module_dir = kb_root / "modules"
    module_dir.mkdir(parents=True, exist_ok=True)
    files_by_module: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for f in curr.get("files", []):
        files_by_module[f.get("module", ".")].append(f)
    changed_paths = set(diff.get("changed", [])) | set(diff.get("added", []))
    changed_modules = {f.get("module", ".") for f in curr.get("files", []) if f.get("path") in changed_paths}
    if not changed_modules:
        changed_modules = set(files_by_module.keys())
    for module in changed_modules:
        files = sorted(files_by_module.get(module, []), key=lambda x: x.get("lines", 0), reverse=True)
        operations = compact_unique([op for f in files for op in f.get("operations", [])], 20)
        data_specs = compact_unique([s for f in files for s in f.get("data_specs", [])], 20)
        endpoints = compact_unique([e for f in files for e in f.get("api_endpoints", [])], 20)
        unit_conversions = compact_unique([u for f in files for u in f.get("unit_conversions", [])], 20)
        state_links = compact_unique([s for f in files for s in f.get("state_links", [])], 24)
        payload = {
            "generated_at": curr.get("generated_at"),
            "project_path": curr.get("project_path"),
            "module": module,
            "file_count": len(files),
            "operations": operations,
            "data_specs": data_specs,
            "api_endpoints": endpoints,
            "unit_conversions": unit_conversions,
            "state_links": state_links,
            "files": [
                {
                    "path": f.get("path"),
                    "lines": f.get("lines"),
                    "symbols": f.get("symbols", [])[:10],
                    "operations": f.get("operations", []),
                    "data_specs": f.get("data_specs", []),
                    "api_endpoints": f.get("api_endpoints", []),
                    "unit_conversions": f.get("unit_conversions", []),
                    "state_links": f.get("state_links", []),
                }
                for f in files[:30]
            ],
        }
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "__", module)
        write_json(module_dir / f"{safe_name}.json", payload)


def build_knowledge_graph_snapshot(curr: dict[str, Any]) -> dict[str, Any]:
    files = curr.get("files", [])
    path_set = {f.get("path", "") for f in files}
    node_map: dict[str, dict[str, Any]] = {}
    edge_weights: dict[tuple[str, str, str], int] = {}

    def upsert_node(node_id: str, label: str, node_type: str, inc: int = 1) -> None:
        node = node_map.get(node_id)
        if not node:
            node = {"id": node_id, "label": label, "type": node_type, "weight": 0}
            node_map[node_id] = node
        node["weight"] = int(node.get("weight", 0)) + inc

    def add_edge(src: str, dst: str, edge_type: str, inc: int = 1) -> None:
        key = (src, dst, edge_type)
        edge_weights[key] = edge_weights.get(key, 0) + inc

    for f in files:
        src_module = f.get("module") or infer_module(f.get("path", ""))
        src_node = f"module:{src_module}"
        upsert_node(src_node, src_module, "module")

        for spec in f.get("import_specs", []):
            target_path = resolve_import_target(f.get("path", ""), spec, path_set)
            if not target_path:
                continue
            target_module = infer_module(target_path)
            if not target_module or target_module == src_module:
                continue
            dst_node = f"module:{target_module}"
            upsert_node(dst_node, target_module, "module")
            add_edge(src_node, dst_node, "module_dependency")

        for state in f.get("state_links", []):
            label = str(state).strip()
            if not label:
                continue
            state_node = f"state:{label}"
            upsert_node(state_node, label, "state")
            add_edge(src_node, state_node, "state_interaction")

        for endpoint in f.get("api_endpoints", []):
            label = str(endpoint).strip()
            if not label:
                continue
            api_node = f"api:{label}"
            upsert_node(api_node, label, "api")
            add_edge(src_node, api_node, "api_call")

    nodes = sorted(node_map.values(), key=lambda x: (x["type"], -x["weight"], x["label"]))
    edges = [
        {"source": s, "target": t, "type": tp, "weight": w}
        for (s, t, tp), w in edge_weights.items()
    ]
    edges.sort(key=lambda x: x["weight"], reverse=True)

    by_type = collections.Counter(n["type"] for n in nodes)
    edge_types = collections.Counter(e["type"] for e in edges)
    return {
        "generated_at": curr.get("generated_at"),
        "project_path": curr.get("project_path"),
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "module_nodes": by_type.get("module", 0),
            "state_nodes": by_type.get("state", 0),
            "api_nodes": by_type.get("api", 0),
            "state_edges": edge_types.get("state_interaction", 0),
            "module_edges": edge_types.get("module_dependency", 0),
            "api_edges": edge_types.get("api_call", 0),
        },
        "nodes": nodes,
        "edges": edges[:1200],
    }


def run_scan(project_path: Path, kb_root: Path) -> dict[str, Any]:
    latest_path = kb_root / "latest_snapshot.json"
    history_dir = kb_root / "snapshots"
    history_dir.mkdir(parents=True, exist_ok=True)
    prev = load_json(latest_path, {"files": []})
    excludes: list[str] = []
    try:
        kb_rel = str(kb_root.relative_to(project_path))
        if kb_rel and kb_rel != ".":
            excludes.append(kb_rel)
    except Exception:
        pass
    prev_map = {f["path"]: f for f in prev.get("files", [])}
    curr = scan_project(project_path, excludes, prev_map=prev_map)
    diff = build_diff(prev, curr)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    snapshot_path = history_dir / f"snapshot-{stamp}.json"
    write_json(snapshot_path, curr)
    write_json(latest_path, curr)
    write_json(kb_root / "module_index.json", {"generated_at": curr["generated_at"], "modules": curr["modules"]})
    write_json(kb_root / "knowledge_graph.json", build_knowledge_graph_snapshot(curr))
    write_module_knowledge(kb_root, curr, diff)
    append_jsonl(kb_root / "changes.jsonl", diff)
    return {
        "snapshot": str(snapshot_path),
        "diff": diff,
        "stats": {
            "file_count": curr["file_count"],
            "total_lines": curr["total_lines"],
            "reused_files": curr.get("scan_stats", {}).get("reused_files", 0),
            "updated_files": curr.get("scan_stats", {}).get("updated_files", 0),
        },
    }


def tokenize(text: str) -> list[str]:
    raw = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", text.lower())
    tokens: list[str] = []
    for t in raw:
        if len(t) >= 2:
            tokens.append(t)
        if re.search(r"[\u4e00-\u9fff]", t):
            chars = [c for c in t if re.match(r"[\u4e00-\u9fff]", c)]
            for i in range(len(chars) - 1):
                tokens.append("".join(chars[i : i + 2]))
        mix = re.findall(r"[a-z0-9_]+", t)
        for m in mix:
            if len(m) >= 2:
                tokens.append(m)
    dedup = []
    seen = set()
    for t in tokens:
        if t not in seen:
            seen.add(t)
            dedup.append(t)
    expanded = []
    expansions = {
        "样式": ["style", "scss", "theme", "class"],
        "接口": ["api", "request", "response", "service"],
    }
    for t in dedup:
        expanded.append(t)
        for k, vals in expansions.items():
            if k in t:
                expanded.extend(vals)
    return compact_unique(expanded, 120)


def score_item(question_tokens: set[str], item: dict[str, Any]) -> int:
    fields = [
        item.get("path", ""),
        item.get("module", ""),
        " ".join(item.get("symbols", [])),
        " ".join(item.get("tags", [])),
        " ".join(item.get("operations", [])),
        " ".join(item.get("data_specs", [])),
        " ".join(item.get("api_endpoints", [])),
        " ".join(item.get("unit_conversions", [])),
        " ".join(item.get("state_links", [])),
    ]
    text = " ".join(fields).lower()
    score = 0
    for t in question_tokens:
        if t in text:
            score += 3 if len(t) >= 6 else (2 if len(t) >= 4 else 1)
    path = item.get("path", "").lower()
    if any(t in question_tokens for t in {"样式", "style", "scss", "css"}):
        if re.search(r"\.(scss|sass|less|css|vue)$", path):
            score += 3
    if any(t in question_tokens for t in {"状态", "store", "state", "交互"}):
        if item.get("state_links"):
            score += 4
    return score


def resolve_import_target(current_rel: str, spec: str, path_set: set[str]) -> str | None:
    if spec.startswith("@/"):
        base = "src/" + spec[2:]
    elif spec.startswith("src/"):
        base = spec
    elif spec.startswith("."):
        base = str((Path(current_rel).parent / spec).as_posix())
    else:
        return None
    if base in path_set:
        return base
    ext = Path(base).suffix.lower()
    exts = [".ts", ".tsx", ".js", ".jsx", ".vue", ".json", ".py", ".scss", ".css", ".less", ".sass"]
    candidates: list[str] = []
    if ext:
        candidates.append(base)
    else:
        for e in exts:
            candidates.append(base + e)
    for e in exts:
        candidates.append(base.rstrip("/") + "/index" + e)
    for cand in candidates:
        if cand in path_set:
            return cand
    return None


def build_call_chain_summary(all_files: list[dict[str, Any]], top_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    path_set = {f.get("path", "") for f in all_files}
    file_map = {f.get("path", ""): f for f in all_files}
    service_files = [f for f in all_files if "/services/" in f.get("path", "") or "service" in f.get("tags", [])]
    service_symbol_map: dict[str, str] = {}
    for sf in service_files:
        for sym in sf.get("symbols", []):
            service_symbol_map[sym] = sf.get("path", "")
    page_candidates = [
        f
        for f in top_files
        if f.get("ext") in {".vue", ".tsx", ".jsx", ".ts", ".js"} and ("/views/" in f.get("path", "") or "/components/" in f.get("path", ""))
    ]
    if not page_candidates:
        page_candidates = top_files[:3]
    summary: list[dict[str, Any]] = []
    for page in page_candidates[:5]:
        ops = compact_unique(page.get("operations", []), 8)
        imports = page.get("import_specs", [])
        linked_services: list[str] = []
        for spec in imports:
            target = resolve_import_target(page.get("path", ""), spec, path_set)
            if not target:
                continue
            if "/services/" in target:
                linked_services.append(target)
        for call_name in page.get("call_candidates", []):
            owner = service_symbol_map.get(call_name)
            if owner:
                linked_services.append(f"{owner}::{call_name}")
        linked_services = compact_unique(linked_services, 10)
        linked_service_files = compact_unique([x.split("::", 1)[0] for x in linked_services], 6)
        endpoint_nodes: list[str] = []
        data_nodes: list[str] = []
        unit_nodes: list[str] = []
        state_nodes: list[str] = []
        for sf_path in linked_service_files:
            sf = file_map.get(sf_path, {})
            endpoint_nodes.extend(sf.get("api_endpoints", []))
            data_nodes.extend(sf.get("data_specs", []))
            unit_nodes.extend(sf.get("unit_conversions", []))
            state_nodes.extend(sf.get("state_links", []))
        data_nodes.extend(page.get("data_specs", []))
        unit_nodes.extend(page.get("unit_conversions", []))
        state_nodes.extend(page.get("state_links", []))
        interfaces = compact_unique(linked_services + endpoint_nodes, 12)
        data_structures = compact_unique(data_nodes, 12)
        unit_rules = compact_unique(unit_nodes, 8)
        state_relations = compact_unique(state_nodes, 10)
        chain = {
            "page": page.get("path", ""),
            "operations": ops,
            "interfaces": interfaces,
            "data_structures": data_structures,
            "unit_rules": unit_rules,
            "state_relations": state_relations,
            "chain": f"页面({page.get('path', '')}) -> 操作({', '.join(ops[:3]) or '未识别'}) -> 接口({', '.join(interfaces[:3]) or '未识别'}) -> 数据结构({', '.join(data_structures[:3]) or '未识别'}) -> 单位({', '.join(unit_rules[:2]) or '未识别'}) -> 状态({', '.join(state_relations[:2]) or '未识别'})",
        }
        summary.append(chain)
    return summary


def build_module_relation_graph(all_files: list[dict[str, Any]], focus_modules: list[str], max_edges: int = 40) -> dict[str, Any]:
    path_set = {f.get("path", "") for f in all_files}
    files_by_module: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for f in all_files:
        files_by_module[f.get("module", ".")].append(f)
    edges: dict[tuple[str, str], int] = {}
    for src_module in focus_modules[:8]:
        for f in files_by_module.get(src_module, []):
            for spec in f.get("import_specs", []):
                target_path = resolve_import_target(f.get("path", ""), spec, path_set)
                if not target_path:
                    continue
                target_module = infer_module(target_path)
                if not target_module or target_module == src_module:
                    continue
                key = (src_module, target_module)
                edges[key] = edges.get(key, 0) + 1
    edge_list = sorted(
        [{"from": a, "to": b, "weight": w} for (a, b), w in edges.items()],
        key=lambda x: x["weight"],
        reverse=True,
    )[:max_edges]
    node_set = set(focus_modules[:8])
    for e in edge_list:
        node_set.add(e["from"])
        node_set.add(e["to"])
    nodes = [{"module": n} for n in sorted(node_set)]
    return {"nodes": nodes, "edges": edge_list}


def run_ask(kb_root: Path, question: str, topk: int = 8) -> dict[str, Any]:
    latest = load_json(kb_root / "latest_snapshot.json", {})
    files = latest.get("files", [])
    q_tokens = set(tokenize(question))
    scored = []
    for f in files:
        s = score_item(q_tokens, f)
        if s > 0:
            scored.append((s, f))
    scored.sort(key=lambda x: (x[0], x[1].get("lines", 0)), reverse=True)
    top_files = [f for _, f in scored[:topk]]
    confidence = "high" if scored and scored[0][0] >= 8 else ("medium" if scored and scored[0][0] >= 4 else "low")
    if not top_files:
        top_files = sorted(files, key=lambda x: x.get("lines", 0), reverse=True)[:topk]
    related_modules = {}
    action_pool: list[str] = []
    data_pool: list[str] = []
    endpoint_pool: list[str] = []
    unit_pool: list[str] = []
    state_pool: list[str] = []
    for f in top_files:
        top = f.get("module") or (f["path"].split("/", 1)[0] if "/" in f["path"] else ".")
        related_modules[top] = related_modules.get(top, 0) + 1
        action_pool.extend(f.get("operations", []))
        data_pool.extend(f.get("data_specs", []))
        endpoint_pool.extend(f.get("api_endpoints", []))
        unit_pool.extend(f.get("unit_conversions", []))
        state_pool.extend(f.get("state_links", []))
    modules = sorted(related_modules.items(), key=lambda x: x[1], reverse=True)
    matched_files = []
    for f in top_files:
        matched_files.append(
            {
                "path": f["path"],
                "module": f.get("module"),
                "lines": f["lines"],
                "symbols": f.get("symbols", [])[:8],
                "symbol_entries": f.get("symbol_entries", [])[:6],
                "tags": f.get("tags", []),
                "operations": f.get("operations", []),
                "data_specs": f.get("data_specs", []),
                "api_endpoints": f.get("api_endpoints", []),
                "unit_conversions": f.get("unit_conversions", []),
                "state_links": f.get("state_links", []),
            }
        )
    page_actions = compact_unique(action_pool, 20)
    data_specs = compact_unique(data_pool, 20)
    endpoints = compact_unique(endpoint_pool, 20)
    unit_rules = compact_unique(unit_pool, 20)
    state_relations = compact_unique(state_pool, 24)
    call_chain_summary = build_call_chain_summary(files, top_files)
    module_relation_graph = build_module_relation_graph(files, [m for m, _ in modules[:8]])
    return {
        "question": question,
        "generated_at": utc_now(),
        "confidence": confidence,
        "matched_files": matched_files,
        "related_modules": [{"module": m, "matched_files": c} for m, c in modules[:8]],
        "page_actions": page_actions,
        "data_norms": {
            "data_specs": data_specs,
            "api_endpoints": endpoints,
            "unit_conversion_rules": unit_rules,
            "state_interactions": state_relations,
        },
        "call_chain_summary": call_chain_summary,
        "module_relation_graph": module_relation_graph,
        "suggestion": "先看 matched_files 前 3 个文件的 symbol_entries 与 operations，再回溯 services/stores 的调用链与请求结构。",
    }


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def plist_content(script_path: Path, project_path: Path, kb_root: Path, interval_sec: int, label: str) -> str:
    stdout_path = kb_root / "logs" / "launchd.stdout.log"
    stderr_path = kb_root / "logs" / "launchd.stderr.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>{script_path}</string>
    <string>scan</string>
    <string>--project-path</string>
    <string>{project_path}</string>
    <string>--kb-root</string>
    <string>{kb_root}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>{interval_sec}</integer>
  <key>StandardOutPath</key>
  <string>{stdout_path}</string>
  <key>StandardErrorPath</key>
  <string>{stderr_path}</string>
</dict>
</plist>
"""


def run_launchctl(args: list[str]) -> None:
    subprocess.run(["launchctl", *args], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def install_launchd(script_path: Path, project_path: Path, kb_root: Path, interval_sec: int, label: str) -> dict[str, Any]:
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    (kb_root / "logs").mkdir(parents=True, exist_ok=True)
    plist.write_text(plist_content(script_path, project_path, kb_root, interval_sec, label), encoding="utf-8")
    run_launchctl(["unload", str(plist)])
    run_launchctl(["load", str(plist)])
    return {"status": "installed", "label": label, "plist": str(plist), "interval_sec": interval_sec}


def uninstall_launchd(label: str) -> dict[str, Any]:
    plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    if plist.exists():
        run_launchctl(["unload", str(plist)])
        plist.unlink()
    return {"status": "uninstalled", "label": label, "plist": str(plist)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["scan", "watch", "ask", "install", "uninstall"])
    parser.add_argument("--project-path", required=False, default="")
    parser.add_argument("--kb-root", required=False, default="/Users/ikun/.openclaw/qqbot/data/project-kb")
    parser.add_argument("--interval-sec", type=int, default=1800)
    parser.add_argument("--question", default="")
    parser.add_argument("--label", default="com.ikun.openclaw.projectkb")
    args = parser.parse_args()

    project_path = Path(args.project_path).expanduser().resolve() if args.project_path else None
    kb_root = Path(args.kb_root).expanduser().resolve()

    if args.mode in {"scan", "watch"} and (project_path is None or not project_path.exists()):
        raise SystemExit("请传入有效的 --project-path")

    if args.mode == "scan":
        result = run_scan(project_path, kb_root)
        print_json(result)
        return

    if args.mode == "watch":
        while True:
            result = run_scan(project_path, kb_root)
            print_json(result)
            time.sleep(max(args.interval_sec, 60))

    if args.mode == "ask":
        if not args.question:
            raise SystemExit("ask 模式需要 --question")
        result = run_ask(kb_root, args.question)
        print_json(result)

    if args.mode == "install":
        if project_path is None or not project_path.exists():
            raise SystemExit("install 模式需要有效的 --project-path")
        script_path = Path(__file__).resolve()
        result = install_launchd(script_path, project_path, kb_root, max(args.interval_sec, 60), args.label)
        print_json(result)

    if args.mode == "uninstall":
        result = uninstall_launchd(args.label)
        print_json(result)


if __name__ == "__main__":
    main()
