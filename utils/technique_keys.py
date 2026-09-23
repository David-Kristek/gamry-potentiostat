"""Naming helpers for a technique sequence that repeats a technique (e.g. "ocp,eis,eis,lpr")."""

from __future__ import annotations

from collections import Counter


def occurrence_keys(techniques: list[str]) -> list[str]:
    """One unique key per position, e.g. ["ocp","eis","eis"] -> ["ocp","eis_1","eis_2"]."""
    counts = Counter(techniques)
    seen: Counter[str] = Counter()
    keys = []
    for name in techniques:
        seen[name] += 1
        keys.append(name if counts[name] == 1 else f"{name}_{seen[name]}")
    return keys


def base_technique(key: str) -> str:
    """"eis_2" -> "eis"; "eis" -> "eis"."""
    base, sep, suffix = key.rpartition("_")
    return base if sep and suffix.isdigit() else key
