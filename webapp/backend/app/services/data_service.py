"""Reads parser/analyser output straight off disk (the sysdiagnose framework's own cache
files) — the API layer never re-runs a parser, it only reads what the worker already
wrote to `<case>/parsed_data/`.
"""

import functools
import importlib
import json
import os
from pathlib import Path

from app import config  # noqa: F401  (sets SYSDIAGNOSE_CASES_PATH before framework import)
from app.categories import category_for


@functools.lru_cache(maxsize=1)
def _sd():
    from sysdiagnose import Sysdiagnose

    return Sysdiagnose()


def sd_config():
    return _sd().config


@functools.lru_cache(maxsize=1)
def module_meta() -> dict[str, dict]:
    """Static metadata about every parser/analyser, independent of any case:
    name -> {kind, description, format, is_timeline, category}.
    Computed once by importing each module (cheap: no case is instantiated)."""
    from sysdiagnose.utils.base import BaseAnalyserInterface, BaseParserInterface

    cfg = sd_config()
    result: dict[str, dict] = {}
    for kind, base_class, names in (
        ("parser", BaseParserInterface, cfg.get_parsers().keys()),
        ("analyser", BaseAnalyserInterface, cfg.get_analysers().keys()),
    ):
        for name in names:
            module = importlib.import_module(f"sysdiagnose.{kind}s.{name}")
            for attr in dir(module):
                obj = getattr(module, attr)
                if isinstance(obj, type) and issubclass(obj, base_class) and obj is not base_class:
                    result[name] = {
                        "kind": kind,
                        "description": obj.description,
                        "format": obj.format,
                        "is_timeline": obj.format == "jsonl",
                        "category": category_for(name),
                    }
                    break
    return result


def output_path(case_id: str, name: str) -> Path | None:
    meta = module_meta().get(name)
    if not meta:
        return None
    folder = sd_config().get_case_parsed_data_folder(case_id)
    return Path(folder) / f"{name}.{meta['format']}"


def read_output(case_id: str, name: str):
    """Returns (meta, data). `data` is parsed JSON for json/jsonl formats, raw text otherwise."""
    meta = module_meta().get(name)
    if not meta:
        return None, None
    path = output_path(case_id, name)
    if not path or not path.exists():
        return meta, None

    if meta["format"] == "json":
        with open(path) as f:
            return meta, json.load(f)
    if meta["format"] == "jsonl":
        data = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    data.append(json.loads(line))
        return meta, data
    # custom formats (gpx/kml/csv/txt/md/html): return raw text, frontend decides how to render
    with open(path, encoding="utf-8", errors="replace") as f:
        return meta, f.read()


def delete_case_data(case_id: str) -> None:
    """Remove a case's on-disk folder (raw upload + parsed output) and its entry in the
    framework's cases.json. Reuses the framework's own delete_case, which resolves the
    folder strictly under cases_root and holds the cases.json file lock while updating it.
    Missing on disk is not an error — the DB row is the source of truth for the API and is
    deleted by the caller regardless, so a half-provisioned case can still be cleaned up."""
    sd = _sd()
    try:
        sd.delete_case(case_id)
    except ValueError:
        # framework raises ValueError when the case_id isn't in cases.json (never fully
        # created, or already removed on disk) — nothing left to delete on disk.
        pass
    # refresh the framework's in-memory case cache so a later re-create with the same id
    # doesn't collide with a stale entry.
    sd.cases(force=True)


def read_unparsed(case_id: str) -> list[dict]:
    path = Path(sd_config().get_case_parsed_data_folder(case_id)) / "_unparsed.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def search_case(case_id: str, query: str, limit: int = 100) -> list[dict]:
    query_lower = query.lower()
    folder = Path(sd_config().get_case_parsed_data_folder(case_id))
    hits: list[dict] = []

    for name, meta in module_meta().items():
        if meta["format"] not in ("json", "jsonl"):
            continue
        path = folder / f"{name}.{meta['format']}"
        if not path.exists():
            continue

        _meta, data = read_output(case_id, name)
        records = data if isinstance(data, list) else [data] if data else []
        for record in records:
            text = json.dumps(record, ensure_ascii=False, default=str)
            if query_lower in text.lower():
                hits.append({"parser": name, "category": meta["category"], "record": record})
                if len(hits) >= limit:
                    return hits
    return hits
