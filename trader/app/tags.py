from __future__ import annotations


def normalize_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in tags:
        tag = str(raw).strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def tags_from_params(params: dict | None) -> list[str]:
    if not params:
        return []
    raw = params.get("tags")
    if not isinstance(raw, list):
        return []
    return normalize_tags([str(t) for t in raw])


def merge_tags_into_params(params: dict | None, tags: list[str]) -> dict:
    merged = dict(params or {})
    merged["tags"] = normalize_tags(tags)
    return merged
