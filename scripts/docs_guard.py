#!/usr/bin/env python3
"""Validate and index docs-architect metadata without third-party packages."""

from __future__ import annotations

import argparse
import ast
from collections import deque
import datetime as dt
import fnmatch
import hashlib
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Sequence
from urllib.parse import quote, unquote, urlsplit


CONFIG_NAME = ".docs-architect.json"
CANONICAL_ROOT_DOCS = ("ARCHITECTURE.md",)
SCHEMA_VERSION = 1
METADATA_MARKER_PATTERN = re.compile(r"<!--\s*docs-architect-meta\b")
METADATA_PATTERN = re.compile(
    r"<!--\s*docs-architect-meta\s*(.*?)\s*-->", re.DOTALL
)
EXTERNAL_LINK_SCHEMES = {"ftp", "http", "https", "mailto", "tel"}
EVIDENCE_URL_SCHEMES = {"http", "https"}
EVIDENCE_KINDS = {
    "test",
    "command",
    "log",
    "screenshot",
    "pull-request",
    "commit",
    "release",
    "document",
    "other",
}
APPROVAL_KINDS = {
    "commit",
    "document",
    "issue-state",
    "pull-request",
    "request-record",
}
COMPLETION_RESULT_EVIDENCE_KINDS = {"command", "log"}
NO_CHANGE_EVIDENCE_KINDS = {"command", "document", "log"}
MARKDOWN_SUFFIXES = {".md", ".mdc"}
MARKDOWN_FILENAMES = {".cursorrules"}
SHA256_REVISION_PATTERN = re.compile(
    r"sha256:([0-9a-fA-F]{64})@(.+)"
)
LINE_LOCATOR_PATTERN = re.compile(r"L([1-9][0-9]*)(?:-L([1-9][0-9]*))?")
WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CLOCK$",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

ARTIFACT_TYPES = {
    "requirement",
    "product-spec",
    "decision",
    "exec-plan",
    "system-doc",
    "evidence",
}
REQUIREMENT_STATUSES = {
    "intake",
    "clarifying",
    "accepted",
    "planned",
    "in_progress",
    "verifying",
    "documented",
    "done",
    "deferred",
    "rejected",
    "superseded",
}
ARTIFACT_STATUSES = {"draft", "active", "completed", "superseded", "retired"}
ACCEPTANCE_STATUSES = {"pending", "passed", "failed", "not_applicable"}
DOCUMENTATION_DISPOSITIONS = {"pending", "updated", "no_change_required"}
RELATION_TYPES = {
    "derives_from",
    "depends_on",
    "implements",
    "validates",
    "documents",
    "supersedes",
    "generated_from",
    "related_to",
}
ADVANCED_REQUIREMENT_STATUSES = {
    "accepted",
    "planned",
    "in_progress",
    "verifying",
    "documented",
    "done",
}
DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "docs_roots": ["docs"],
    "exclude": [
        ".git/**",
        ".venv/**",
        "build/**",
        "dist/**",
        "node_modules/**",
        "vendor/**",
    ],
    "adapters": {},
    "generated_dir": "docs/generated",
}


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    path: str | None = None
    artifact_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.path is not None:
            result["path"] = self.path
        if self.artifact_id is not None:
            result["artifact_id"] = self.artifact_id
        return result


@dataclass
class Artifact:
    path: Path
    relative_path: str
    metadata: dict[str, Any]

    @property
    def artifact_id(self) -> str:
        value = self.metadata.get("id")
        return value if isinstance(value, str) else ""


@dataclass
class ScanResult:
    artifacts: list[Artifact] = field(default_factory=list)
    markdown_files: list[Path] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def normalize_relative(value: str) -> str:
    normalized = value.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def path_is_absolute(value: str) -> bool:
    normalized = value.replace("\\", "/")
    windows_path = PureWindowsPath(value)
    return (
        PurePosixPath(normalized).is_absolute()
        or bool(windows_path.anchor)
        or bool(windows_path.drive)
    )


def is_safe_relative(value: str) -> bool:
    if not value:
        return False
    normalized = normalize_relative(value)
    if not normalized or path_is_absolute(normalized):
        return False
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    for part in parts:
        if part.endswith((".", " ")) or ":" in part:
            return False
        if not any(character in part for character in "*?["):
            basename = part.split(".", 1)[0].upper()
            if basename in WINDOWS_RESERVED_NAMES:
                return False
    return True


def contains_glob(value: str) -> bool:
    return any(character in value for character in "*?[")


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def resolve_repository_path(root: Path, value: str) -> Path | None:
    if not is_safe_relative(value):
        return None
    target = (root / normalize_relative(value)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def path_is_linklike(path: Path) -> bool:
    try:
        return path.is_symlink() or (
            hasattr(path, "is_junction") and path.is_junction()
        )
    except OSError:
        return True


def path_has_linklike_component(root: Path, value: str) -> bool:
    if not is_safe_relative(value):
        return True
    current = root.resolve()
    for part in PurePosixPath(normalize_relative(value)).parts:
        current = current / part
        if path_is_linklike(current):
            return True
        if not current.exists():
            break
    return False


def has_exact_repository_case(path: Path, root: Path) -> bool:
    """Return whether every existing component uses its on-disk spelling."""
    try:
        root_absolute = Path(os.path.abspath(root))
        path_absolute = Path(os.path.abspath(path))
        parts = path_absolute.relative_to(root_absolute).parts
    except (OSError, ValueError):
        return False

    current = root_absolute
    for part in parts:
        try:
            names = {entry.name for entry in os.scandir(current)}
        except OSError:
            return False
        if part not in names:
            return False
        current /= part
    return True


def repository_path_exists(
    root: Path, value: str, *, file_only: bool = False
) -> bool:
    resolved = resolve_repository_path(root, value)
    if resolved is None:
        return False
    unresolved = root / normalize_relative(value)
    if not resolved.exists() or not has_exact_repository_case(unresolved, root):
        return False
    return resolved.is_file() if file_only else True


def iter_repository_tree(start: Path, root: Path) -> Iterable[Path]:
    """Walk a contained tree without following symlinks or Windows junctions."""
    root_resolved = root.resolve()
    stack = [start]
    visited: set[Path] = set()
    while stack:
        directory = stack.pop()
        if path_is_linklike(directory):
            continue
        try:
            resolved_directory = directory.resolve()
            resolved_directory.relative_to(root_resolved)
        except (OSError, ValueError):
            continue
        if resolved_directory in visited:
            continue
        visited.add(resolved_directory)
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError:
            continue
        child_directories: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            if path_is_linklike(path):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    child_directories.append(path)
                elif entry.is_file(follow_symlinks=False):
                    yield path
            except OSError:
                continue
        stack.extend(reversed(child_directories))


def matches_pattern(path: str, pattern: str) -> bool:
    normalized_path = normalize_relative(path)
    normalized_pattern = normalize_relative(pattern)
    path_parts = tuple(part for part in normalized_path.split("/") if part)
    pattern_parts = tuple(part for part in normalized_pattern.split("/") if part)

    @lru_cache(maxsize=None)
    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        current = pattern_parts[pattern_index]
        if current == "**":
            return match(path_index, pattern_index + 1) or (
                path_index < len(path_parts) and match(path_index + 1, pattern_index)
            )
        return (
            path_index < len(path_parts)
            and fnmatch.fnmatchcase(path_parts[path_index], current)
            and match(path_index + 1, pattern_index + 1)
        )

    return match(0, 0)


def is_excluded(path: str, patterns: Sequence[str]) -> bool:
    return any(matches_pattern(path, pattern) for pattern in patterns)


def is_markdown_path(path: Path) -> bool:
    return path.suffix.lower() in MARKDOWN_SUFFIXES or path.name.lower() in MARKDOWN_FILENAMES


def is_generated_path(path: str, generated_dir: str) -> bool:
    normalized = normalize_relative(path)
    generated = normalize_relative(generated_dir).rstrip("/")
    return normalized == generated or normalized.startswith(f"{generated}/")


def is_scannable_markdown(
    path: Path,
    root: Path,
    exclusions: Sequence[str],
    generated_dir: str,
) -> bool:
    if not is_markdown_path(path):
        return False
    rel = relative_path(path, root)
    return not is_excluded(rel, exclusions) and not is_generated_path(
        rel, generated_dir
    )


def load_config(root: Path) -> tuple[dict[str, Any] | None, list[Finding]]:
    config_path = root / CONFIG_NAME
    if not config_path.is_file():
        return None, [
            Finding(
                "error",
                "missing_config",
                f"Run `init` to create {CONFIG_NAME}.",
                CONFIG_NAME,
            )
        ]

    try:
        config = load_json_object(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return None, [
            Finding("error", "invalid_config", str(exc), CONFIG_NAME)
        ]

    findings = validate_config(config)
    return config if not any(item.severity == "error" for item in findings) else None, findings


def validate_config(config: Any) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(config, dict):
        return [Finding("error", "invalid_config", "Configuration must be an object.")]
    if type(config.get("schema_version")) is not int or config.get("schema_version") != SCHEMA_VERSION:
        findings.append(
            Finding(
                "error",
                "unsupported_schema",
                f"schema_version must be {SCHEMA_VERSION}.",
                CONFIG_NAME,
            )
        )
    if config.get("change_policy", "strict") not in ("strict", "scoped"):
        findings.append(Finding("error", "invalid_config", "change_policy must be strict or scoped", CONFIG_NAME))
    for key in ("docs_roots", "exclude"):
        value = config.get(key)
        if (
            not isinstance(value, list)
            or (key == "docs_roots" and not value)
            or not all(isinstance(item, str) for item in value)
        ):
            findings.append(
                Finding(
                    "error",
                    "invalid_config",
                    f"{key} must be {'a non-empty' if key == 'docs_roots' else 'a'} string array.",
                    CONFIG_NAME,
                )
            )
    adapters = config.get("adapters")
    if not isinstance(adapters, dict) or not all(
        isinstance(paths, list) and all(isinstance(path, str) for path in paths)
        for paths in adapters.values()
    ):
        findings.append(
            Finding(
                "error",
                "invalid_config",
                "adapters must map tool names to string arrays.",
                CONFIG_NAME,
            )
        )
    generated_dir = config.get("generated_dir", "docs/generated")
    if not isinstance(generated_dir, str) or not is_safe_relative(generated_dir):
        findings.append(
            Finding(
                "error",
                "invalid_config",
                "generated_dir must be a repository-relative path.",
                CONFIG_NAME,
            )
        )
    for key in ("docs_roots", "exclude"):
        values = config.get(key, [])
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and not is_safe_relative(value):
                    findings.append(
                        Finding(
                            "error",
                            "unsafe_config_path",
                            f"{key} contains an unsafe repository path: {value}",
                            CONFIG_NAME,
                        )
                    )
                elif isinstance(value, str) and key == "docs_roots" and contains_glob(value):
                    findings.append(
                        Finding(
                            "error",
                            "invalid_config",
                            "docs_roots entries must be files or directories, not globs.",
                            CONFIG_NAME,
                        )
                    )
    if isinstance(adapters, dict):
        for paths in adapters.values():
            if not isinstance(paths, list):
                continue
            for value in paths:
                if isinstance(value, str) and not is_safe_relative(value):
                    findings.append(
                        Finding(
                            "error",
                            "unsafe_config_path",
                            f"adapters contains an unsafe repository path: {value}",
                            CONFIG_NAME,
                        )
                    )
                elif isinstance(value, str) and contains_glob(value):
                    findings.append(
                        Finding(
                            "error",
                            "invalid_config",
                            "adapter entries must be files or directories, not globs.",
                            CONFIG_NAME,
                        )
                    )
    if isinstance(generated_dir, str) and contains_glob(generated_dir):
        findings.append(
            Finding(
                "error",
                "invalid_config",
                "generated_dir must be a directory path, not a glob.",
                CONFIG_NAME,
            )
        )
    if isinstance(generated_dir, str) and is_safe_relative(generated_dir):
        generated = normalize_relative(generated_dir).rstrip("/")
        docs_roots = config.get("docs_roots", [])
        if isinstance(docs_roots, list):
            for value in docs_roots:
                if not isinstance(value, str) or not is_safe_relative(value):
                    continue
                docs_root = normalize_relative(value).rstrip("/")
                if docs_root == generated or docs_root.startswith(f"{generated}/"):
                    findings.append(
                        Finding(
                            "error",
                            "invalid_config",
                            "generated_dir cannot equal or contain a docs_roots entry: "
                            f"{value}",
                            CONFIG_NAME,
                        )
                    )
    return findings


def load_json_object(text: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"Unsupported JSON constant: {value}")

    return json.loads(
        text,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_constant,
    )


def configured_paths(config: dict[str, Any]) -> list[str]:
    paths = list(config.get("docs_roots", []))
    for adapter_paths in config.get("adapters", {}).values():
        paths.extend(adapter_paths)
    return [normalize_relative(path) for path in paths]


def validate_declared_adapters(
    root: Path,
    config: dict[str, Any],
    scanned_paths: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    adapters = config.get("adapters", {})
    if not isinstance(adapters, dict):
        return findings
    for tool_name, paths in adapters.items():
        if not isinstance(paths, list):
            continue
        for value in paths:
            if not isinstance(value, str) or not is_safe_relative(value):
                continue
            if not repository_path_exists(root, value):
                findings.append(
                    Finding(
                        "warning",
                        "adapter_missing",
                        f"Declared {tool_name} adapter does not exist: {value}",
                        CONFIG_NAME,
                    )
                )
                continue
            target = resolve_repository_path(root, value)
            if target is None:
                continue
            contributes = (
                normalize_relative(value) in scanned_paths
                if target.is_file()
                else any(
                    path.startswith(f"{normalize_relative(value).rstrip('/')}/")
                    for path in scanned_paths
                )
            )
            if not contributes:
                findings.append(
                    Finding(
                        "error",
                        "adapter_unscanned",
                        f"Declared {tool_name} adapter is excluded or contains no scannable Markdown: {value}",
                        CONFIG_NAME,
                    )
                )
    return findings


def validate_declared_document_roots(
    root: Path,
    config: dict[str, Any],
    scanned_paths: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    for value in config.get("docs_roots", []):
        if not isinstance(value, str) or not is_safe_relative(value):
            continue
        target = resolve_repository_path(root, value)
        if (
            target is None
            or path_has_linklike_component(root, value)
            or not target.exists()
            or not has_exact_repository_case(root / normalize_relative(value), root)
        ):
            findings.append(
                Finding(
                    "error",
                    "missing_docs_root",
                    f"Declared documentation root does not exist: {value}",
                    CONFIG_NAME,
                )
            )
            continue
        normalized = normalize_relative(value).rstrip("/")
        if target.is_file():
            contributes = normalize_relative(value) in scanned_paths
        elif target.is_dir():
            contributes = any(
                path.startswith(f"{normalized}/") for path in scanned_paths
            )
        else:
            contributes = False
        if not contributes:
            findings.append(
                Finding(
                    "error",
                    "docs_root_unscanned",
                    f"Declared documentation root contains no scannable Markdown: {value}",
                    CONFIG_NAME,
                )
            )
    return findings


def validate_canonical_root_docs(
    root: Path,
    scanned_paths: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    for value in CANONICAL_ROOT_DOCS:
        if not repository_path_exists(root, value):
            continue
        if normalize_relative(value) not in scanned_paths:
            findings.append(
                Finding(
                    "error",
                    "canonical_doc_not_scanned",
                    f"Canonical root document must be included in docs_roots: {value}",
                    CONFIG_NAME,
                )
            )
    return findings


def detect_existing_adapters(root: Path) -> dict[str, list[str]]:
    adapters: dict[str, list[str]] = {}
    candidates = {
        "codex": ["AGENTS.md"],
        "claude": ["CLAUDE.md"],
        "cursor": [".cursorrules"],
    }
    for tool_name, paths in candidates.items():
        existing = [path for path in paths if repository_path_exists(root, path)]
        if existing:
            adapters[tool_name] = existing

    cursor_rules = resolve_repository_path(root, ".cursor/rules")
    if (
        cursor_rules is not None
        and cursor_rules.is_dir()
        and not path_has_linklike_component(root, ".cursor/rules")
    ):
        rules = sorted(
            relative_path(path, root)
            for path in iter_repository_tree(cursor_rules, root)
            if path.suffix.lower() == ".mdc"
        )
        if rules:
            adapters["cursor"] = sorted(
                set(adapters.get("cursor", []) + rules)
            )
    return adapters


def collect_markdown_files(root: Path, config: dict[str, Any]) -> list[Path]:
    exclusions = config.get("exclude", [])
    generated_dir = normalize_relative(
        config.get("generated_dir", "docs/generated")
    )
    candidates: set[Path] = set()
    for configured in configured_paths(config):
        target = resolve_repository_path(root, configured)
        if target is None or path_has_linklike_component(root, configured):
            continue
        if target.is_file() and is_markdown_path(target):
            candidates.add(target.resolve())
        elif target.is_dir():
            for path in iter_repository_tree(target, root):
                if is_markdown_path(path):
                    candidates.add(path.resolve())
    return sorted(
        (
            path
            for path in candidates
            if is_scannable_markdown(path, root, exclusions, generated_dir)
        ),
        key=lambda path: relative_path(path, root),
    )


def parse_artifact(path: Path, root: Path) -> tuple[Artifact | None, list[Finding]]:
    rel = relative_path(path, root)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [Finding("error", "unreadable_markdown", str(exc), rel)]

    matches = METADATA_PATTERN.findall(text)
    marker_count = len(METADATA_MARKER_PATTERN.findall(text))
    if not matches and marker_count == 0:
        return None, []
    if marker_count != len(matches):
        return None, [
            Finding(
                "error",
                "invalid_metadata_comment",
                "Every docs-architect-meta marker must be closed correctly.",
                rel,
            )
        ]
    if marker_count != 1:
        return None, [
            Finding(
                "error",
                "metadata_count",
                "A managed document must contain exactly one docs-architect-meta comment.",
                rel,
            )
        ]
    try:
        metadata = load_json_object(matches[0])
    except (json.JSONDecodeError, ValueError) as exc:
        return None, [Finding("error", "invalid_metadata_json", str(exc), rel)]
    if not isinstance(metadata, dict):
        return None, [
            Finding("error", "invalid_metadata", "Metadata must be a JSON object.", rel)
        ]
    artifact = Artifact(path, rel, metadata)
    return artifact, validate_artifact(artifact, root)


def require_string(
    metadata: dict[str, Any], key: str, artifact: Artifact, findings: list[Finding]
) -> str | None:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        findings.append(
            Finding(
                "error",
                "missing_field",
                f"{key} must be a non-empty string.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
        return None
    return value


def validate_string_array(
    metadata: dict[str, Any],
    key: str,
    artifact: Artifact,
    findings: list[Finding],
    *,
    required: bool = False,
) -> list[str]:
    if required and key not in metadata:
        findings.append(
            Finding(
                "error",
                "missing_field",
                f"{key} must be present as an array, even when empty.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
        return []
    value = metadata.get(key, [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) and bool(item.strip()) for item in value
    ):
        findings.append(
            Finding(
                "error",
                "invalid_field",
                f"{key} must be an array of non-empty strings.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
        return []
    return value


def validate_artifact(artifact: Artifact, root: Path) -> list[Finding]:
    metadata = artifact.metadata
    findings: list[Finding] = []
    if type(metadata.get("schema_version")) is not int or metadata.get("schema_version") != SCHEMA_VERSION:
        findings.append(
            Finding(
                "error",
                "unsupported_schema",
                f"schema_version must be {SCHEMA_VERSION}.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
    require_string(metadata, "id", artifact, findings)
    artifact_type = require_string(metadata, "type", artifact, findings)
    require_string(metadata, "title", artifact, findings)
    status = require_string(metadata, "status", artifact, findings)
    if artifact_type and artifact_type not in ARTIFACT_TYPES:
        findings.append(
            Finding(
                "error",
                "invalid_type",
                f"Unsupported artifact type: {artifact_type}",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
    allowed_statuses = REQUIREMENT_STATUSES if artifact_type == "requirement" else ARTIFACT_STATUSES
    if status and status not in allowed_statuses:
        findings.append(
            Finding(
                "error",
                "invalid_status",
                f"Unsupported {artifact_type or 'artifact'} status: {status}",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )

    verified_at = metadata.get("verified_at")
    verified_against = metadata.get("verified_against")
    if verified_at is not None:
        if not isinstance(verified_at, str) or not valid_iso8601(verified_at):
            findings.append(
                Finding(
                    "error",
                    "invalid_verified_at",
                    "verified_at must be null or an ISO 8601 date or timestamp.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
    if verified_against is not None:
        if not isinstance(verified_against, str) or not verification_revision_resolves(
            root, verified_against
        ):
            findings.append(
                Finding(
                    "error",
                    "invalid_verified_against",
                    "verified_against must resolve to a repository commit or use "
                    "sha256:<digest>@<repository-relative-file> with matching content.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
    if (verified_at is None) != (verified_against is None):
        findings.append(
            Finding(
                "error",
                "incomplete_verification_anchor",
                "verified_at and verified_against must be recorded together.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )

    for key in ("owners", "sources", "update_when", "affected_docs"):
        values = validate_string_array(metadata, key, artifact, findings)
        for value in values:
            if key in {"sources", "affected_docs"} and not is_safe_relative(value):
                findings.append(
                    Finding(
                        "error",
                        "unsafe_path",
                        f"{key} contains a non-repository-relative path: {value}",
                        artifact.relative_path,
                        artifact.artifact_id or None,
                    )
                )

    relations = metadata.get("relations", [])
    if not isinstance(relations, list):
        findings.append(
            Finding(
                "error",
                "invalid_relations",
                "relations must be an array.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
    else:
        for relation in relations:
            if not isinstance(relation, dict):
                findings.append(
                    Finding(
                        "error",
                        "invalid_relation",
                        "Each relation must be an object.",
                        artifact.relative_path,
                        artifact.artifact_id or None,
                    )
                )
                continue
            relation_type = relation.get("type")
            target = relation.get("target")
            if (
                relation_type not in RELATION_TYPES
                or not isinstance(target, str)
                or not target.strip()
            ):
                findings.append(
                    Finding(
                        "error",
                        "invalid_relation",
                        "A relation requires an allowed type and non-empty target ID.",
                        artifact.relative_path,
                        artifact.artifact_id or None,
                    )
                )

    evidence = metadata.get("evidence", [])
    if not isinstance(evidence, list):
        findings.append(
            Finding(
                "error",
                "invalid_evidence",
                "evidence must be an array.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
    else:
        for item in evidence:
            if not valid_evidence_item(item):
                findings.append(
                    Finding(
                        "error",
                        "invalid_evidence",
                        "Each evidence item requires non-empty kind, ref, and description strings.",
                        artifact.relative_path,
                        artifact.artifact_id or None,
                    )
                )

    if artifact_type == "requirement":
        findings.extend(validate_requirement(artifact, root))

    sources = metadata.get("sources", [])
    if not isinstance(sources, list):
        sources = []
    for source in sources:
        if not isinstance(source, str) or not is_safe_relative(source):
            continue
        if not source_matches_repository(root, source):
            findings.append(
                Finding(
                    "warning",
                    "source_unmatched",
                    f"Source path or pattern does not match the repository: {source}",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
    findings.extend(validate_evidence_references(metadata.get("evidence", []), artifact, root))
    return findings


def valid_iso8601(value: str) -> bool:
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt.date.fromisoformat(value)
        except ValueError:
            return False
    return True


def validate_requirement(artifact: Artifact, root: Path) -> list[Finding]:
    metadata = artifact.metadata
    findings: list[Finding] = []
    status = metadata.get("status")
    verified_at = metadata.get("verified_at")
    verified_against = metadata.get("verified_against")
    for key in (
        "dependencies",
        "affected_code",
        "affected_docs",
        "open_questions",
    ):
        values = validate_string_array(
            metadata, key, artifact, findings, required=True
        )
        if key in {"affected_code", "affected_docs"}:
            for value in values:
                if not is_safe_relative(value):
                    findings.append(
                        Finding(
                            "error",
                            "unsafe_path",
                            f"{key} contains a non-repository-relative path: {value}",
                            artifact.relative_path,
                            artifact.artifact_id or None,
                        )
                    )
    disposition = metadata.get("documentation_disposition", "pending")
    if disposition not in DOCUMENTATION_DISPOSITIONS:
        findings.append(
            Finding(
                "error",
                "invalid_documentation_disposition",
                f"documentation_disposition must be one of {sorted(DOCUMENTATION_DISPOSITIONS)}.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
    acceptance = metadata.get("acceptance", [])
    if not isinstance(acceptance, list):
        findings.append(
            Finding(
                "error",
                "invalid_acceptance",
                "acceptance must be an array.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
        acceptance = []

    if "evidence" not in metadata:
        findings.append(
            Finding(
                "error",
                "missing_field",
                "evidence must be present as an array, even when empty.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
    if status in ADVANCED_REQUIREMENT_STATUSES and not acceptance:
        findings.append(
            Finding(
                "error",
                "missing_acceptance",
                f"A requirement in {status} must define acceptance criteria.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
    origin = metadata.get("origin")
    if origin is not None and not valid_origin(origin):
        findings.append(
            Finding(
                "error",
                "invalid_origin",
                "origin must be null or an object with non-empty kind and ref strings.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
    if status in ADVANCED_REQUIREMENT_STATUSES and not valid_origin(origin):
        findings.append(
            Finding(
                "error",
                "missing_origin",
                f"A requirement in {status} must record a structured origin.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )

    approval = metadata.get("approval")
    approval_valid = approval is not None and approval_resolves(
        approval, artifact, root
    )
    if approval is not None and not approval_valid:
        findings.append(
            Finding(
                "error",
                "invalid_approval",
                "approval must use an allowed authority kind and a resolvable commit, "
                "HTTPS authority URL, or repository record outside this requirement.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )
    if status in ADVANCED_REQUIREMENT_STATUSES and not approval_valid:
        findings.append(
            Finding(
                "error",
                "missing_approval",
                f"A requirement in {status} must record an explicit approval source.",
                artifact.relative_path,
                artifact.artifact_id or None,
            )
        )

    acceptance_ids: set[str] = set()
    for item in acceptance:
        if not isinstance(item, dict):
            findings.append(
                Finding(
                    "error",
                    "invalid_acceptance_item",
                    "Each acceptance item must be an object.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
            continue
        item_id = item.get("id")
        item_text = item.get("text")
        if (
            not isinstance(item_id, str)
            or not item_id.strip()
            or not isinstance(item_text, str)
            or not item_text.strip()
        ):
            findings.append(
                Finding(
                    "error",
                    "invalid_acceptance_item",
                    "Each acceptance item requires non-empty string id and text fields.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        elif item_id in acceptance_ids:
            findings.append(
                Finding(
                    "error",
                    "duplicate_acceptance_id",
                    f"Duplicate acceptance item ID: {item_id}",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        else:
            acceptance_ids.add(item_id)
        item_status = item.get("status")
        if item_status not in ACCEPTANCE_STATUSES:
            findings.append(
                Finding(
                    "error",
                    "invalid_acceptance_status",
                    f"Unsupported acceptance status: {item_status}",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        item_evidence = item.get("evidence", [])
        if not isinstance(item_evidence, list) or any(
            not valid_evidence_item(evidence_item) for evidence_item in item_evidence
        ):
            findings.append(
                Finding(
                    "error",
                    "invalid_acceptance_evidence",
                    "Acceptance evidence must contain valid evidence objects.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        if item_status in {"passed", "not_applicable"} and not valid_evidence(
            item_evidence
        ):
            findings.append(
                Finding(
                    "error",
                    "missing_acceptance_evidence",
                    "Passed and not_applicable acceptance items require evidence.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        findings.extend(validate_evidence_references(item_evidence, artifact, root))
        if status == "done":
            if item_status not in {"passed", "not_applicable"}:
                findings.append(
                    Finding(
                        "error",
                        "incomplete_acceptance",
                        "Done requirements may contain only passed or not_applicable acceptance items.",
                        artifact.relative_path,
                        artifact.artifact_id or None,
                    )
                )

    affected_docs = metadata.get("affected_docs", [])
    if disposition == "updated":
        if not isinstance(affected_docs, list) or not affected_docs:
            findings.append(
                Finding(
                    "error",
                    "missing_affected_docs",
                    "documentation_disposition=updated requires affected_docs.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        else:
            for affected_doc in affected_docs:
                if not isinstance(affected_doc, str) or not is_safe_relative(affected_doc):
                    continue
                if not repository_path_exists(root, affected_doc, file_only=True):
                    findings.append(
                        Finding(
                            "error",
                            "missing_affected_doc",
                            f"Updated documentation does not exist: {affected_doc}",
                            artifact.relative_path,
                            artifact.artifact_id or None,
                        )
                    )
    if disposition == "no_change_required":
        reason = metadata.get("no_doc_change_reason")
        if not isinstance(reason, str) or not reason.strip():
            findings.append(
                Finding(
                    "error",
                    "missing_no_doc_change_reason",
                    "no_change_required requires a non-empty string reason.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        elif not specific_no_change_reason(reason):
            findings.append(
                Finding(
                    "error",
                    "insufficient_no_doc_change_reason",
                    "no_doc_change_reason must identify both the examined scope and why "
                    "existing durable documentation remains true.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        scope = metadata.get("no_doc_change_scope")
        if not valid_no_change_scope(scope, root):
            findings.append(
                Finding(
                    "error",
                    "missing_no_doc_change_scope",
                    "no_change_required requires a non-empty no_doc_change_scope array "
                    "whose repository-relative paths or globs currently resolve.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        if isinstance(affected_docs, list) and affected_docs:
            findings.append(
                Finding(
                    "error",
                    "no_change_has_affected_docs",
                    "no_change_required requires affected_docs to be empty.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        top_level_evidence = metadata.get("evidence", [])
        if not has_resolvable_evidence(
            top_level_evidence,
            artifact,
            root,
            allowed_kinds=NO_CHANGE_EVIDENCE_KINDS,
        ):
            findings.append(
                Finding(
                    "error",
                    "missing_no_doc_change_evidence",
                    "no_change_required requires a captured review or result artifact in "
                    "top-level evidence.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )

    if status == "done":
        if verified_at is None or verified_against is None:
            findings.append(
                Finding(
                    "error",
                    "missing_completion_verification",
                    "A done requirement must record verified_at and verified_against.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        elif not isinstance(verified_against, str) or not verification_revision_resolves(
            root, verified_against
        ):
            findings.append(
                Finding(
                    "error",
                    "unstable_completion_revision",
                    "A done requirement must identify a resolvable immutable revision.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        if not has_resolvable_evidence(
            metadata.get("evidence", []),
            artifact,
            root,
            allowed_kinds=COMPLETION_RESULT_EVIDENCE_KINDS,
        ):
            findings.append(
                Finding(
                    "error",
                    "missing_completion_result_evidence",
                    "A done requirement requires captured command or log evidence that "
                    "records an observed verification result; test definitions alone are insufficient.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        if disposition not in {"updated", "no_change_required"}:
            findings.append(
                Finding(
                    "error",
                    "documentation_pending",
                    "A done requirement must resolve its documentation disposition.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
        open_questions = metadata.get("open_questions", [])
        if isinstance(open_questions, list) and open_questions:
            findings.append(
                Finding(
                    "error",
                    "unresolved_questions",
                    "A done requirement cannot retain open questions.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
    return findings


def valid_origin(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("kind"), str)
        and bool(value["kind"].strip())
        and isinstance(value.get("ref"), str)
        and bool(value["ref"].strip())
    )


def approval_resolves(value: Any, artifact: Artifact, root: Path) -> bool:
    if not valid_origin(value) or value["kind"] not in APPROVAL_KINDS:
        return False
    kind = value["kind"]
    reference = value["ref"].strip()
    if kind == "commit":
        return git_commit_exists(root, reference)
    if kind in {"issue-state", "pull-request"}:
        return urlsplit(reference).scheme.lower() == "https"
    path_reference = reference.split("#", 1)[0]
    if path_is_absolute(path_reference) or not repository_path_exists(
        root, path_reference, file_only=True
    ):
        return False
    resolved = resolve_repository_path(root, path_reference)
    if resolved is None or resolved.resolve() == artifact.path.resolve():
        return False
    return not is_generated_path(relative_path(resolved, root), "docs/generated")


def verification_revision_resolves(root: Path, value: str) -> bool:
    reference = value.strip()
    if git_commit_exists(root, reference):
        return True
    match = SHA256_REVISION_PATTERN.fullmatch(reference)
    if match is None:
        return False
    digest, path_reference = match.groups()
    if path_is_absolute(path_reference) or not repository_path_exists(
        root, path_reference, file_only=True
    ):
        return False
    resolved = resolve_repository_path(root, path_reference)
    if resolved is None:
        return False
    try:
        actual = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError:
        return False
    return actual.lower() == digest.lower()


def specific_no_change_reason(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = " ".join(value.strip().split())
    if len(normalized) < 40:
        return False
    return len(normalized) >= 40


def valid_no_change_scope(value: Any, root: Path) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(item, str)
            and is_safe_relative(item)
            and source_matches_repository(root, item)
            for item in value
        )
    )


def valid_evidence_item(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("kind"), str)
        and value["kind"] in EVIDENCE_KINDS
        and isinstance(value.get("ref"), str)
        and bool(value["ref"].strip())
        and isinstance(value.get("description"), str)
        and bool(value["description"].strip())
    )


def git_commit_exists(root: Path, reference: str) -> bool:
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", reference.strip()):
        return False
    try:
        process = subprocess.run(
            ["git", "cat-file", "-e", f"{reference.strip()}^{{commit}}"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return False
    return process.returncode == 0


def valid_evidence(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        valid_evidence_item(item) for item in value
    )


def evidence_reference_resolves(kind: str, reference: str, root: Path) -> bool:
    if kind == "commit":
        return git_commit_exists(root, reference)
    if kind == "release":
        return bool(reference.strip()) and reference.strip().lower() not in {
            "head",
            "latest",
            "main",
            "master",
            "develop",
        }
    if kind == "command":
        path_reference = reference.split("::", 1)[0].split("#", 1)[0]
        return repository_path_exists(root, path_reference, file_only=True)
    if path_is_absolute(reference):
        return False
    scheme = urlsplit(reference).scheme.lower()
    if scheme:
        return scheme in EVIDENCE_URL_SCHEMES
    if kind == "pull-request":
        return False
    path_reference = reference.split("::", 1)[0].split("#", 1)[0]
    if not repository_path_exists(root, path_reference, file_only=True):
        return False
    if kind == "test" and not test_locator_resolves(root, reference):
        return False
    return True


def has_resolvable_evidence(
    value: Any,
    artifact: Artifact,
    root: Path,
    *,
    allowed_kinds: set[str],
) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if (
            not valid_evidence_item(item)
            or item["kind"] not in allowed_kinds
            or not evidence_reference_resolves(item["kind"], item["ref"], root)
        ):
            continue
        reference = item["ref"]
        if urlsplit(reference).scheme:
            return True
        path_reference = reference.split("::", 1)[0].split("#", 1)[0]
        resolved = resolve_repository_path(root, path_reference)
        if resolved is not None and resolved.resolve() != artifact.path.resolve():
            return True
    return False


def python_locator_resolves(path: Path, locator: str) -> bool:
    parts = locator.split("::")
    if not parts or any(not part for part in parts) or len(parts) > 2:
        return False
    parts[-1] = parts[-1].split("[", 1)[0]
    if any(not part or not part.isidentifier() for part in parts):
        return False
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return False
    function_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    if len(parts) == 1:
        return any(
            isinstance(node, function_types) and node.name == parts[0]
            for node in module.body
        )
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == parts[0]:
            return any(
                isinstance(child, function_types) and child.name == parts[1]
                for child in node.body
            )
    return False


def line_locator_resolves(path: Path, locator: str) -> bool:
    match = LINE_LOCATOR_PATTERN.fullmatch(locator)
    if match is None:
        return False
    try:
        line_count = len(path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return False
    first = int(match.group(1))
    last = int(match.group(2) or first)
    return first <= last <= line_count


def test_locator_resolves(root: Path, reference: str) -> bool:
    if "::" in reference:
        path_reference, locator = reference.split("::", 1)
        resolved = resolve_repository_path(root, path_reference)
        return (
            resolved is not None
            and resolved.suffix.lower() == ".py"
            and python_locator_resolves(resolved, locator)
        )
    if "#" in reference:
        path_reference, locator = reference.rsplit("#", 1)
        resolved = resolve_repository_path(root, path_reference)
        return resolved is not None and line_locator_resolves(resolved, locator)
    return True


def validate_evidence_references(
    value: Any, artifact: Artifact, root: Path
) -> list[Finding]:
    if not isinstance(value, list):
        return []
    findings: list[Finding] = []
    for item in value:
        if not valid_evidence_item(item):
            continue
        kind = item["kind"]
        reference = item["ref"]
        if kind == "commit":
            if not git_commit_exists(root, reference):
                findings.append(
                    Finding(
                        "error",
                        "unresolvable_evidence",
                        f"Commit evidence is not an immutable object in this repository: {reference}",
                        artifact.relative_path,
                        artifact.artifact_id or None,
                    )
                )
            continue
        if kind == "release":
            if reference.strip().lower() in {"head", "latest", "main", "master", "develop"}:
                findings.append(
                    Finding(
                        "error",
                        "unstable_evidence",
                        f"{kind} evidence must identify an immutable revision or release: {reference}",
                        artifact.relative_path,
                        artifact.artifact_id or None,
                    )
                )
            continue
        if kind == "command":
            path_reference = reference.split("::", 1)[0].split("#", 1)[0]
            if not repository_path_exists(root, path_reference, file_only=True):
                findings.append(
                    Finding(
                        "error",
                        "unresolvable_evidence",
                        "Command evidence must reference a captured repository artifact.",
                        artifact.relative_path,
                        artifact.artifact_id or None,
                    )
                )
            continue
        if path_is_absolute(reference):
            findings.append(
                Finding(
                    "error",
                    "unsafe_evidence_path",
                    f"Evidence paths must be repository-relative: {reference}",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
            continue
        scheme = urlsplit(reference).scheme.lower()
        if scheme:
            if scheme not in EVIDENCE_URL_SCHEMES:
                findings.append(
                    Finding(
                        "error",
                        "unsupported_evidence_url",
                        f"Evidence URL scheme is not supported: {reference}",
                        artifact.relative_path,
                        artifact.artifact_id or None,
                    )
                )
            continue
        if kind == "pull-request":
            findings.append(
                Finding(
                    "error",
                    "unresolvable_evidence",
                    "Pull-request evidence must use a durable http or https URL.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
            continue
        path_reference = reference.split("::", 1)[0].split("#", 1)[0]
        if not repository_path_exists(root, path_reference, file_only=True):
            findings.append(
                Finding(
                    "error",
                    "unresolvable_evidence",
                    f"Evidence path does not exist: {reference}",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
            continue
        if kind == "test" and not test_locator_resolves(root, reference):
            code = (
                "unsupported_test_locator"
                if "::" in reference and Path(path_reference).suffix.lower() != ".py"
                else "unresolvable_test_locator"
            )
            findings.append(
                Finding(
                    "error",
                    code,
                    "Test evidence locator does not resolve to a Python function, class "
                    "method, or valid line range. Use a path-only reference for other frameworks.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
    return findings


def source_matches_repository(root: Path, pattern: str) -> bool:
    if not any(character in pattern for character in "*?["):
        return repository_path_exists(root, pattern)
    if not is_safe_relative(pattern):
        return False
    for path in iter_repository_tree(root, root):
        relative = path.relative_to(root).as_posix()
        if matches_pattern(relative, pattern):
            return True
    return False


def strip_fenced_code_blocks(text: str) -> str:
    lines: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines(keepends=True):
        match = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
                lines.append("\n" if line.endswith("\n") else "")
                continue
            if marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
                lines.append("\n" if line.endswith("\n") else "")
                continue
        lines.append(line if fence_character is None else ("\n" if line.endswith("\n") else ""))
    return "".join(lines)


def markdown_link_targets(text: str) -> Iterable[str]:
    """Yield inline, image, and reference destinations outside fenced code."""
    text = strip_fenced_code_blocks(text)
    definitions: dict[str, str] = {}
    definition_pattern = re.compile(
        r"^[ \t]{0,3}\[([^\]\n]+)\]:[ \t]*(?:<([^>\n]+)>|(\S+))",
        re.MULTILINE,
    )
    for match in definition_pattern.finditer(text):
        label = " ".join(match.group(1).lower().split())
        definitions[label] = match.group(2) or match.group(3)

    yielded_references: set[tuple[int, str]] = set()
    reference_pattern = re.compile(r"!?\[([^\]\n]+)\]\[([^\]\n]*)\]")
    for match in reference_pattern.finditer(text):
        label = match.group(2) or match.group(1)
        normalized = " ".join(label.lower().split())
        target = definitions.get(normalized)
        if target:
            yielded_references.add((match.start(), target))
            yield target
    shortcut_pattern = re.compile(
        r"(?<!\])!?\[([^\]\n]+)\](?![\[(:])"
    )
    for match in shortcut_pattern.finditer(text):
        normalized = " ".join(match.group(1).lower().split())
        target = definitions.get(normalized)
        if target and (match.start(), target) not in yielded_references:
            yield target

    index = 0
    while index < len(text):
        opening = text.find("[", index)
        if opening < 0:
            return
        label_end = text.find("](", opening + 1)
        if label_end < 0:
            return
        cursor = label_end + 2
        angle_wrapped = cursor < len(text) and text[cursor] == "<"
        if angle_wrapped:
            target_end = text.find(">", cursor + 1)
            if target_end >= 0 and target_end + 1 < len(text) and text[target_end + 1] == ")":
                yield text[cursor : target_end + 1]
                index = target_end + 2
                continue
        depth = 0
        escaped = False
        target_end = cursor
        while target_end < len(text):
            character = text[target_end]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    break
                depth -= 1
            target_end += 1
        if target_end < len(text):
            raw = text[cursor:target_end].strip()
            if raw:
                yield raw
            index = target_end + 1
        else:
            return


def validate_links(path: Path, root: Path) -> list[Finding]:
    rel = relative_path(path, root)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings: list[Finding] = []
    for raw_target in markdown_link_targets(text):
        target = raw_target.strip()
        if not (target.startswith("<") and target.endswith(">")):
            target = target.split(maxsplit=1)[0]
        target = target.strip("<>")
        target = unquote(target)
        if (
            not target
            or target.startswith("#")
            or target.startswith("//")
        ):
            continue
        if path_is_absolute(target):
            findings.append(
                Finding(
                    "error",
                    "link_outside_root",
                    f"Local link must be repository-relative: {target}",
                    rel,
                )
            )
            continue
        scheme = urlsplit(target).scheme.lower()
        if scheme:
            if scheme in EXTERNAL_LINK_SCHEMES:
                continue
            findings.append(
                Finding(
                    "error",
                    "unsupported_link_scheme",
                    f"Unsupported link scheme: {target}",
                    rel,
                )
            )
            continue
        target_without_anchor = target.split("#", 1)[0].split("?", 1)[0]
        if not target_without_anchor or "<" in target_without_anchor:
            continue
        resolved = (path.parent / target_without_anchor).resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            findings.append(
                Finding(
                    "error",
                    "link_outside_root",
                    f"Local link escapes the repository: {target}",
                    rel,
                )
            )
            continue
        if not resolved.exists() or not has_exact_repository_case(
            path.parent / target_without_anchor, root
        ):
            findings.append(
                Finding("error", "broken_link", f"Missing local link target: {target}", rel)
            )
    return findings


def scan_repository(root: Path, config: dict[str, Any]) -> ScanResult:
    result = ScanResult()
    result.markdown_files = collect_markdown_files(root, config)
    scanned_paths = {relative_path(path, root) for path in result.markdown_files}
    result.findings.extend(
        validate_declared_document_roots(root, config, scanned_paths)
    )
    result.findings.extend(validate_canonical_root_docs(root, scanned_paths))
    result.findings.extend(validate_declared_adapters(root, config, scanned_paths))
    for path in result.markdown_files:
        artifact, findings = parse_artifact(path, root)
        result.findings.extend(findings)
        result.findings.extend(validate_links(path, root))
        if artifact is not None:
            result.artifacts.append(artifact)
    result.findings.extend(validate_graph(result.artifacts, root))
    result.findings.extend(
        validate_documentation_dispositions(
            result.artifacts, result.markdown_files, root, config
        )
    )
    return result


def target_resolves(target: str, by_id: dict[str, Artifact], root: Path) -> bool:
    if target in by_id:
        return True
    return repository_path_exists(root, target)


def validate_documentation_dispositions(
    artifacts: Sequence[Artifact],
    markdown_files: Sequence[Path],
    root: Path,
    config: dict[str, Any],
) -> list[Finding]:
    scanned_paths = {relative_path(path, root) for path in markdown_files}
    artifacts_by_path = {artifact.relative_path: artifact for artifact in artifacts}
    findings: list[Finding] = []
    for artifact in artifacts:
        if (
            artifact.metadata.get("type") != "requirement"
            or artifact.metadata.get("documentation_disposition") != "updated"
        ):
            continue
        affected_docs = artifact.metadata.get("affected_docs", [])
        if not isinstance(affected_docs, list):
            continue
        current_state_docs: list[str] = []
        for value in affected_docs:
            if not isinstance(value, str) or not is_safe_relative(value):
                continue
            normalized = normalize_relative(value)
            if normalized not in scanned_paths:
                findings.append(
                    Finding(
                        "error",
                        "affected_doc_not_scanned",
                        "Updated documentation must reference a Markdown file included "
                        f"in the configured documentation scan: {value}",
                        artifact.relative_path,
                        artifact.artifact_id or None,
                    )
                )
                continue
            referenced_artifact = artifacts_by_path.get(normalized)
            if (
                referenced_artifact is not None
                and (referenced_artifact.metadata.get("type") == "system-doc" or (
                    config.get("change_policy") == "scoped"
                    and referenced_artifact.metadata.get("type") == "product-spec"
                ))
                and referenced_artifact.metadata.get("status") == "active"
                and system_doc_covers_requirement(
                    referenced_artifact, artifact
                )
            ):
                current_state_docs.append(normalized)
        if affected_docs and not current_state_docs:
            findings.append(
                Finding(
                    "error",
                    "missing_current_state_affected_doc",
                    "documentation_disposition=updated requires at least one scanned "
                    "active governed system-doc (or relevant active product-spec in scoped mode); unmanaged documents, non-active system "
                    "docs, lifecycle artifacts, adapters, and indexes do not satisfy the "
                    "documentation completion gate.",
                    artifact.relative_path,
                    artifact.artifact_id or None,
                )
            )
    return findings


def system_doc_covers_requirement(
    system_document: Artifact,
    requirement: Artifact,
) -> bool:
    requirement_code = requirement.metadata.get("affected_code", [])
    document_sources = system_document.metadata.get("sources", [])
    source_overlap = (
        isinstance(requirement_code, list)
        and isinstance(document_sources, list)
        and any(
            isinstance(code, str)
            and isinstance(source, str)
            and (
                matches_pattern(code, source)
                or matches_pattern(source, code)
                or code == source
            )
            for code in requirement_code
            for source in document_sources
        )
    )
    relations = system_document.metadata.get("relations", [])
    relation_match = isinstance(relations, list) and any(
        isinstance(relation, dict)
        and relation.get("type") == "documents"
        and relation.get("target") == requirement.artifact_id
        for relation in relations
    )
    return source_overlap or relation_match


def validate_graph(artifacts: Sequence[Artifact], root: Path) -> list[Finding]:
    findings: list[Finding] = []
    by_id: dict[str, Artifact] = {}
    by_path: dict[str, Artifact] = {}
    for artifact in artifacts:
        by_path[artifact.relative_path] = artifact
        artifact_id = artifact.artifact_id
        if not artifact_id:
            continue
        if artifact_id in by_id:
            findings.append(
                Finding(
                    "error",
                    "duplicate_id",
                    f"Duplicate artifact ID also used by {by_id[artifact_id].relative_path}.",
                    artifact.relative_path,
                    artifact_id,
                )
            )
        else:
            by_id[artifact_id] = artifact
    for artifact in artifacts:
        relations = artifact.metadata.get("relations", [])
        if not isinstance(relations, list):
            relations = []
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            target = relation.get("target")
            if isinstance(target, str) and target and not target_resolves(target, by_id, root):
                findings.append(
                    Finding(
                        "error",
                        "missing_relation_target",
                        f"Relation target does not exist: {target}",
                        artifact.relative_path,
                        artifact.artifact_id or None,
                    )
                )
        if artifact.metadata.get("type") == "requirement":
            dependencies = artifact.metadata.get("dependencies", [])
            if not isinstance(dependencies, list):
                dependencies = []
            related_dependencies = [
                relation.get("target")
                for relation in relations
                if isinstance(relation, dict)
                and relation.get("type") == "depends_on"
                and isinstance(relation.get("target"), str)
            ]
            dependency_targets = list(
                dict.fromkeys([*dependencies, *related_dependencies])
            )
            for dependency in dependency_targets:
                if isinstance(dependency, str) and not target_resolves(
                    dependency, by_id, root
                ):
                    findings.append(
                        Finding(
                            "error",
                            "missing_dependency",
                            f"Requirement dependency does not exist: {dependency}",
                            artifact.relative_path,
                            artifact.artifact_id or None,
                        )
                    )
                dependency_artifact = None
                if isinstance(dependency, str):
                    dependency_artifact = by_id.get(dependency)
                    if dependency_artifact is None and is_safe_relative(dependency):
                        resolved = resolve_repository_path(root, dependency)
                        if resolved is not None:
                            try:
                                dependency_artifact = by_path.get(relative_path(resolved, root))
                            except ValueError:
                                dependency_artifact = None
                if (
                    artifact.metadata.get("status") == "done"
                    and (
                        dependency_artifact is None
                        or dependency_artifact.metadata.get("type") != "requirement"
                        or dependency_artifact.metadata.get("status") != "done"
                    )
                ):
                    findings.append(
                        Finding(
                            "error",
                            "unresolved_dependency",
                            "Done requirement dependencies must resolve to scanned governed "
                            f"requirements in done state: {dependency}",
                            artifact.relative_path,
                            artifact.artifact_id or None,
                        )
                    )
    return findings


def run_check(root: Path) -> tuple[dict[str, Any], int]:
    config, config_findings = load_config(root)
    if config is None:
        payload = check_payload([], config_findings, 0)
        return payload, 1
    result = scan_repository(root, config)
    findings = config_findings + result.findings
    payload = check_payload(result.artifacts, findings, len(result.markdown_files))
    return payload, 1 if payload["summary"]["errors"] else 0


def check_payload(
    artifacts: Sequence[Artifact], findings: Sequence[Finding], markdown_count: int
) -> dict[str, Any]:
    errors = sum(item.severity == "error" for item in findings)
    warnings = sum(item.severity == "warning" for item in findings)
    return {
        "ok": errors == 0,
        "summary": {
            "artifacts": len(artifacts),
            "markdown_files": markdown_count,
            "errors": errors,
            "warnings": warnings,
        },
        "findings": [item.as_dict() for item in findings],
    }


def git_changed_files(root: Path, base: str | None) -> tuple[list[str], list[Finding]]:
    commands: list[list[str]] = []
    if base:
        commands.append(
            ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD", "--"]
        )
    try:
        top_level = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        return [], [Finding("error", "git_unavailable", str(exc))]
    if top_level.returncode != 0:
        return [], [
            Finding(
                "error",
                "git_root_unavailable",
                top_level.stderr.strip() or "Target is not inside a Git worktree.",
            )
        ]
    try:
        git_root = Path(top_level.stdout.strip()).resolve()
    except (OSError, ValueError) as exc:
        return [], [Finding("error", "git_root_unavailable", str(exc))]
    if git_root != root.resolve():
        return [], [
            Finding(
                "error",
                "git_root_mismatch",
                "Target root is nested inside another Git worktree; pass explicit "
                "repository-relative paths with --changed or initialize Git at the target root.",
            )
        ]
    if head.returncode == 0:
        commands.append(
            ["git", "diff", "--name-only", "--no-renames", "-z", "HEAD", "--"]
        )
    else:
        commands.extend(
            [
                ["git", "diff", "--name-only", "--no-renames", "-z", "--"],
                ["git", "diff", "--name-only", "--no-renames", "-z", "--cached", "--"],
            ]
        )
    commands.append(["git", "ls-files", "--others", "--exclude-standard", "-z"])
    changed: set[str] = set()
    for command in commands:
        try:
            process = subprocess.run(
                ["git", "-c", "core.quotepath=false", *command[1:]],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as exc:
            return [], [Finding("error", "git_unavailable", str(exc))]
        if process.returncode != 0:
            return [], [
                Finding(
                    "error",
                    "git_diff_failed",
                    process.stderr.strip() or "Unable to derive changed files from Git.",
                )
            ]
        changed.update(
            normalize_relative(path)
            for path in process.stdout.split("\0")
            if path
        )
    return sorted(changed), []


def run_impact(
    root: Path, changed: Sequence[str] | None, base: str | None
) -> tuple[dict[str, Any], int]:
    config, findings = load_config(root)
    if config is None:
        return {"ok": False, "changed_files": [], "affected_documents": [], "findings": [item.as_dict() for item in findings]}, 1
    scan = scan_repository(root, config)
    findings.extend(scan.findings)
    if changed:
        changed_files = sorted({normalize_relative(path) for path in changed})
        for changed_path in changed_files:
            if not is_safe_relative(changed_path):
                findings.append(
                    Finding(
                        "error",
                        "unsafe_changed_path",
                        f"Changed path must be repository-relative: {changed_path}",
                    )
                )
    else:
        changed_files, git_findings = git_changed_files(root, base)
        findings.extend(git_findings)
    if any(
        item.severity == "error"
        and item.code in {
            "git_diff_failed",
            "git_root_mismatch",
            "git_root_unavailable",
            "git_unavailable",
            "unsafe_changed_path",
        }
        for item in findings
    ):
        return {
            "ok": False,
            "changed_files": changed_files,
            "affected_documents": [],
            "findings": [item.as_dict() for item in findings],
        }, 1

    directly_affected: dict[str, list[str]] = {}
    artifacts_by_id = {
        artifact.artifact_id: artifact for artifact in scan.artifacts if artifact.artifact_id
    }
    directly_matched_paths: set[str] = set()
    for artifact in scan.artifacts:
        patterns = []
        for key in ("sources", "update_when", "affected_code", "affected_docs"):
            value = artifact.metadata.get(key, [])
            if isinstance(value, list):
                patterns.extend(item for item in value if isinstance(item, str))
        dependencies = artifact.metadata.get("dependencies", [])
        if not isinstance(dependencies, list):
            dependencies = []
        for dependency in dependencies:
            if (
                isinstance(dependency, str)
                and dependency not in artifacts_by_id
                and is_safe_relative(dependency)
            ):
                patterns.append(dependency)
        relations = artifact.metadata.get("relations", [])
        if not isinstance(relations, list):
            relations = []
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            target = relation.get("target")
            if (
                isinstance(target, str)
                and target not in artifacts_by_id
                and is_safe_relative(target)
            ):
                patterns.append(target)
        matches = sorted(
            {
                changed_path
                for changed_path in changed_files
                if changed_path == artifact.relative_path or any(matches_pattern(changed_path, pattern) for pattern in patterns)
            }
        )
        if matches and artifact.artifact_id:
            directly_matched_paths.update(matches)
            directly_affected[artifact.artifact_id] = [
                f"source match: {changed_path}" for changed_path in matches
            ]

    graph: dict[str, list[tuple[str, str]]] = {
        artifact_id: [] for artifact_id in artifacts_by_id
    }
    for artifact in scan.artifacts:
        if not artifact.artifact_id:
            continue
        relations = artifact.metadata.get("relations", [])
        if not isinstance(relations, list):
            relations = []
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            target = relation.get("target")
            if isinstance(target, str) and target in graph:
                relation_type = str(relation.get("type"))
                graph[artifact.artifact_id].append((target, relation_type))
                graph[target].append((artifact.artifact_id, f"reverse:{relation_type}"))
        dependencies = artifact.metadata.get("dependencies", [])
        if not isinstance(dependencies, list):
            dependencies = []
        for dependency in dependencies:
            if isinstance(dependency, str) and dependency in graph:
                graph[artifact.artifact_id].append((dependency, "depends_on"))
                graph[dependency].append(
                    (artifact.artifact_id, "reverse:depends_on")
                )

    reasons = dict(directly_affected)
    paths = {artifact_id: artifact_id for artifact_id in directly_affected}
    queue = deque(directly_affected)
    while queue:
        current = queue.popleft()
        for neighbor, relation_type in sorted(graph.get(current, [])):
            if neighbor in reasons:
                continue
            paths[neighbor] = f"{paths[current]} --{relation_type}--> {neighbor}"
            reasons[neighbor] = [f"relation traversal: {paths[neighbor]}"]
            queue.append(neighbor)

    affected = []
    for artifact_id in sorted(reasons):
        artifact = artifacts_by_id[artifact_id]
        affected.append(
            {
                "id": artifact_id,
                "type": artifact.metadata.get("type"),
                "status": artifact.metadata.get("status"),
                "title": artifact.metadata.get("title"),
                "path": artifact.relative_path,
                "reasons": reasons[artifact_id],
            }
        )
    unmatched = [
        path for path in changed_files if path not in directly_matched_paths
    ]
    return {
        "ok": not any(item.severity == "error" for item in findings),
        "changed_files": changed_files,
        "affected_documents": affected,
        "unmatched_changed_files": unmatched,
        "semantic_review_recommended": bool(unmatched),
        "findings": [item.as_dict() for item in findings],
    }, 1 if any(item.severity == "error" for item in findings) else 0


def assessment_base(root: Path, base: str | None) -> str | None:
    """Only trust a real merge-base from this worktree; never treat a missing base as clean."""
    try:
        def git(*args: str) -> str:
            result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)
            return result.stdout.decode("utf-8").strip()
        if Path(git("rev-parse", "--show-toplevel")).resolve() != root.resolve():
            return None
        ref = git("rev-parse", "--verify", "--end-of-options", (base or "HEAD") + "^{commit}")
        return git("merge-base", ref, "HEAD")
    except (OSError, UnicodeError, subprocess.CalledProcessError):
        return None


def run_assess(root: Path, changed: Sequence[str] | None, base: str | None) -> tuple[dict[str, Any], int]:
    """Action-specific diagnostics. Not a replacement for check or a certificate for index."""
    oid = assessment_base(root, base)
    delta, git_issues = git_changed_files(root, oid) if oid else ([], [])
    reported_paths = sorted(set(delta) | set(changed or []))
    report, _ = run_impact(root, reported_paths or None, oid)
    changed_set = set(report.get("changed_files", []))
    affected = {doc["path"] for doc in report.get("affected_documents", [])}
    affected_ids = {doc["id"] for doc in report.get("affected_documents", [])}
    errors = [row for row in report["findings"] if row["severity"] == "error"]
    blocking, background, unknown = [], [], []
    if not oid or git_issues:
        unknown.append({"code": "baseline_unknown", "message": "Supply a valid revision in the target Git worktree."})
    for row in errors:
        path = row.get("path")
        if path in changed_set | affected or row.get("artifact_id") in affected_ids or not path or path == CONFIG_NAME:
            blocking.append(row)
        elif (oid and not git_issues and path not in delta and CONFIG_NAME not in delta
              and row["code"] == "missing_field" and row.get("artifact_id")
              and row["message"].split(" ", 1)[0] in {"title", "owners", "evidence"}):
            # An intrinsic schema defect in an unchanged document, outside the known impact graph.
            background.append(row)
        else:
            unknown.append(row)

    config, _ = load_config(root)
    roots = [normalize_relative(v).rstrip("/") for v in configured_paths(config)] if config else []
    if CONFIG_NAME in delta:
        unknown.append({"code": "governance_scope_changed", "path": CONFIG_NAME,
                        "message": "Review policy changes explicitly; do not certify using the new scope alone."})
    # A removed envelope silently drops a document from the current graph. Check changed
    # tracked Markdown against the base blob, not just the working-tree parser.
    digests: dict[str, str | None] = {}
    for path in sorted(changed_set) if oid else []:
        if not is_safe_relative(path) or path_has_linklike_component(root, path):
            blocking.append({"code": "unsafe_changed_path", "path": path})
            continue
        target = resolve_repository_path(root, path)
        if target is None or (target.exists() and not target.is_file()):
            unknown.append({"code": "unreadable_changed_file", "path": path})
            continue
        digest = hashlib.sha256()
        if target.is_file():
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(131072), b""):
                    digest.update(chunk)
            digests[path] = digest.hexdigest()
        else:
            digests[path] = None
        if not config or not any(r == "." or path == r or path.startswith(r + "/") for r in roots):
            continue
        if not is_scannable_markdown(target, root, config.get("exclude", []), config.get("generated_dir", "docs/generated")):
            continue
        blob = subprocess.run(["git", "show", f"{oid}:{path}"], cwd=root, capture_output=True)
        if blob.returncode:
            continue  # a new path has no base artifact
        text = blob.stdout.decode("utf-8", errors="replace")
        if not METADATA_PATTERN.search(strip_fenced_code_blocks(text)):
            continue
        target = resolve_repository_path(root, path)
        if target is None or path_has_linklike_component(root, path):
            blocking.append({"code": "unsafe_managed_path", "path": path})
        else:
            try:
                current = target.read_text(encoding="utf-8") if target.is_file() else ""
            except (OSError, UnicodeError):
                unknown.append({"code": "unreadable_managed_file", "path": path})
                continue
            if not METADATA_PATTERN.search(strip_fenced_code_blocks(current)):
                blocking.append({"code": "managed_marker_removed", "path": path,
                                 "message": "Review retirement or relocation before certifying the documentation change."})

    unsafe = any(x["code"].startswith("unsafe") for x in blocking)
    ready = not (unknown or blocking)
    decision = ("stop_unsafe_operation" if unsafe else "repair_current_scope" if blocking else
                "review_unknown_scope" if unknown else "continue_with_debt" if background else "continue")
    return {"kind": "docs-architect.assessment.v1", "base_revision": oid, "decision": decision,
            "can_implement": not unsafe, "can_close_docs": ready, "audit_ok": report["ok"],
            "changed_files": sorted(changed_set), "affected_documents": report.get("affected_documents", []),
            "blocking": blocking, "unknown": unknown, "background": background, "file_digests": digests,
            "warnings": [row for row in report["findings"] if row["severity"] != "error"],
            "semantic_review_recommended": report.get("semantic_review_recommended", True)}, int(not ready)


def traceability_payload(artifacts: Sequence[Artifact]) -> dict[str, Any]:
    rows = []
    for artifact in sorted(artifacts, key=lambda item: (item.artifact_id, item.relative_path)):
        relations = artifact.metadata.get("relations", [])
        if not isinstance(relations, list):
            relations = []
        normalized_relations = sorted(
            (
                {"type": item.get("type"), "target": item.get("target")}
                for item in relations
                if isinstance(item, dict)
            ),
            key=lambda item: (str(item["type"]), str(item["target"])),
        )
        rows.append(
            {
                "id": artifact.artifact_id,
                "type": artifact.metadata.get("type"),
                "status": artifact.metadata.get("status"),
                "title": artifact.metadata.get("title"),
                "path": artifact.relative_path,
                "relations": normalized_relations,
            }
        )
    return {"schema_version": SCHEMA_VERSION, "artifacts": rows}


def render_traceability_markdown(
    payload: dict[str, Any], generated_dir: str = "docs/generated"
) -> str:
    lines = [
        "# Documentation Traceability Index",
        "",
        "> Generated by docs-architect. Do not edit by hand.",
        "",
        "| ID | Type | Status | Title | Path |",
        "|---|---|---|---|---|",
    ]
    for artifact in payload["artifacts"]:
        artifact_id = markdown_table_cell(artifact["id"])
        artifact_type = markdown_table_cell(artifact["type"])
        status = markdown_table_cell(artifact["status"])
        title = markdown_table_cell(artifact["title"])
        path = artifact["path"]
        path_label = markdown_table_cell(path)
        href = quote(
            posixpath.relpath(path, normalize_relative(generated_dir)), safe="/"
        )
        lines.append(
            f"| `{artifact_id}` | {artifact_type} | {status} | {title} | [{path_label}]({href}) |"
        )
    relations = [
        (artifact["id"], relation["type"], relation["target"])
        for artifact in payload["artifacts"]
        for relation in artifact["relations"]
    ]
    if relations:
        lines.extend(
            [
                "",
                "## Relationships",
                "",
                "| Source | Relationship | Target |",
                "|---|---|---|",
            ]
        )
        for source, relation_type, target in relations:
            lines.append(
                f"| `{markdown_table_cell(source)}` | "
                f"`{markdown_table_cell(relation_type)}` | "
                f"`{markdown_table_cell(target)}` |"
            )
    return "\n".join(lines) + "\n"


def markdown_table_cell(value: Any) -> str:
    return (
        str(value)
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("|", "\\|")
        .replace("`", "\\`")
    )


def atomic_write_if_changed(path: Path, content: str) -> str:
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "updated"


def preview_write_status(path: Path, content: str) -> str:
    try:
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            return "unchanged"
    except (OSError, UnicodeDecodeError):
        pass
    return "would_update"


def atomic_write_batch(items: Sequence[tuple[Path, str]]) -> dict[Path, str]:
    """Prepare every output before replacing any, then roll back on replace failure."""
    statuses: dict[Path, str] = {}
    pending: list[tuple[Path, Path]] = []
    originals: dict[Path, bytes | None] = {}
    try:
        for path, content in items:
            if path.is_file() and path.read_text(encoding="utf-8") == content:
                statuses[path] = "unchanged"
                continue
            if path.exists() and not path.is_file():
                raise OSError(f"Output path is not a regular file: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            originals[path] = path.read_bytes() if path.exists() else None
            descriptor, temporary_name = tempfile.mkstemp(
                dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(
                    descriptor, "w", encoding="utf-8", newline="\n"
                ) as handle:
                    handle.write(content)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
            pending.append((path, temporary))

        replaced: list[Path] = []
        try:
            for path, temporary in pending:
                os.replace(temporary, path)
                replaced.append(path)
                statuses[path] = "updated"
        except OSError:
            for path in reversed(replaced):
                original = originals[path]
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    descriptor, rollback_name = tempfile.mkstemp(
                        dir=path.parent,
                        prefix=f".{path.name}.",
                        suffix=".rollback",
                    )
                    rollback = Path(rollback_name)
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(original)
                    os.replace(rollback, path)
            raise
    finally:
        for _, temporary in pending:
            temporary.unlink(missing_ok=True)
    return statuses


def run_index(root: Path, write: bool) -> tuple[dict[str, Any], int]:
    config, findings = load_config(root)
    if config is None:
        return {"ok": False, "findings": [item.as_dict() for item in findings]}, 1
    scan = scan_repository(root, config)
    findings.extend(scan.findings)
    has_errors = any(item.severity == "error" for item in findings)
    if write and has_errors:
        return {"ok": False, "write": True, "findings": [item.as_dict() for item in findings]}, 1
    traceability = traceability_payload(scan.artifacts)
    json_content = json.dumps(traceability, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    generated_relative = normalize_relative(
        config.get("generated_dir", "docs/generated")
    )
    markdown_content = render_traceability_markdown(traceability, generated_relative)
    generated_dir = resolve_repository_path(root, generated_relative)
    if generated_dir is None or path_has_linklike_component(root, generated_relative):
        return {
            "ok": False,
            "findings": [
                Finding(
                    "error",
                    "unsafe_generated_dir",
                    "generated_dir resolves outside the repository.",
                    CONFIG_NAME,
                ).as_dict()
            ],
        }, 1
    files = {
        relative_path(generated_dir / "traceability.json", root): preview_write_status(
            generated_dir / "traceability.json", json_content
        ),
        relative_path(generated_dir / "traceability.md", root): preview_write_status(
            generated_dir / "traceability.md", markdown_content
        ),
    }
    if write:
        outputs = [
            (generated_dir / "traceability.json", json_content),
            (generated_dir / "traceability.md", markdown_content),
        ]
        try:
            statuses = atomic_write_batch(outputs)
        except OSError as exc:
            return {
                "ok": False,
                "write": True,
                "files": files,
                "findings": [
                    Finding(
                        "error",
                        "index_write_failed",
                        str(exc),
                        generated_relative,
                    ).as_dict()
                ],
            }, 1
        files = {
            relative_path(path, root): status for path, status in statuses.items()
        }
    return {
        "ok": not has_errors,
        "write": write,
        "files": files,
        "traceability": traceability,
        "markdown_preview": None if write else markdown_content,
        "findings": [item.as_dict() for item in findings],
    }, 1 if has_errors else 0


def run_init(root: Path) -> tuple[dict[str, Any], int]:
    if not root.is_dir():
        return {
            "ok": False,
            "created": [],
            "unchanged": [],
            "findings": [
                Finding("error", "missing_root", "Repository root does not exist.", str(root)).as_dict()
            ],
        }, 1
    created: list[str] = []
    unchanged: list[str] = []
    config_path = root / CONFIG_NAME
    config_content: str | None = None
    if config_path.exists():
        config, findings = load_config(root)
        if any(item.severity == "error" for item in findings):
            return {
                "ok": False,
                "created": created,
                "unchanged": unchanged,
                "findings": [item.as_dict() for item in findings],
            }, 1
        assert config is not None
        docs_roots = list(config.get("docs_roots", []))
        for canonical_doc in CANONICAL_ROOT_DOCS:
            if (
                repository_path_exists(root, canonical_doc)
                and canonical_doc not in docs_roots
            ):
                docs_roots.append(canonical_doc)
        if docs_roots != config.get("docs_roots"):
            config = dict(config)
            config["docs_roots"] = docs_roots
            config_content = json.dumps(config, indent=2, sort_keys=True) + "\n"
        else:
            unchanged.append(CONFIG_NAME)
    else:
        config = dict(DEFAULT_CONFIG)
        config["docs_roots"] = list(DEFAULT_CONFIG["docs_roots"])
        for canonical_doc in CANONICAL_ROOT_DOCS:
            if repository_path_exists(root, canonical_doc):
                config["docs_roots"].append(canonical_doc)
        config["adapters"] = detect_existing_adapters(root)
        config_content = json.dumps(config, indent=2, sort_keys=True) + "\n"
    assert config is not None
    exclusions = config.get("exclude", [])
    generated_dir = normalize_relative(config.get("generated_dir", "docs/generated"))
    canonical_conflicts: list[Finding] = []
    for canonical_doc in CANONICAL_ROOT_DOCS:
        target = resolve_repository_path(root, canonical_doc)
        if (
            target is not None
            and target.is_file()
            and not is_scannable_markdown(
                target, root, exclusions, generated_dir
            )
        ):
            canonical_conflicts.append(
                Finding(
                    "error",
                    "canonical_doc_excluded",
                    f"Existing canonical document is excluded from scanning: {canonical_doc}",
                    CONFIG_NAME,
                )
            )
    if canonical_conflicts:
        return {
            "ok": False,
            "created": [],
            "unchanged": unchanged,
            "findings": [item.as_dict() for item in canonical_conflicts],
        }, 1
    directories = (
        "docs/requirements",
        "docs/exec-plans/active",
        "docs/exec-plans/completed",
        "docs/decisions",
        generated_dir,
    )
    targets: list[tuple[str, Path]] = []
    findings: list[Finding] = []
    for directory in directories:
        target = resolve_repository_path(root, directory)
        if target is None or path_has_linklike_component(root, directory):
            findings.append(
                Finding(
                    "error",
                    "unsafe_init_path",
                    f"Initialization path must be a direct repository path: {directory}",
                    CONFIG_NAME,
                )
            )
            continue
        if target.exists() and not target.is_dir():
            findings.append(
                Finding(
                    "error",
                    "init_path_not_directory",
                    f"Initialization path is occupied by a non-directory: {directory}",
                    CONFIG_NAME,
                )
            )
            continue
        targets.append((directory, target))
    if findings:
        return {
            "ok": False,
            "created": [],
            "unchanged": unchanged,
            "findings": [item.as_dict() for item in findings],
        }, 1

    created_directories: list[Path] = []
    config_original = config_path.read_bytes() if config_path.exists() else None
    try:
        if config_content is not None:
            config_status = atomic_write_if_changed(config_path, config_content)
            if config_original is None:
                created.append(CONFIG_NAME)
            elif config_status == "updated":
                created.append(f"{CONFIG_NAME} (updated)")
        for directory, target in targets:
            if target.is_dir():
                unchanged.append(directory)
            else:
                target.mkdir(parents=True, exist_ok=True)
                created_directories.append(target)
                created.append(directory)
    except OSError as exc:
        for target in reversed(created_directories):
            try:
                target.rmdir()
            except OSError:
                pass
        if config_content is not None:
            if config_original is None:
                config_path.unlink(missing_ok=True)
            else:
                descriptor, rollback_name = tempfile.mkstemp(
                    dir=config_path.parent,
                    prefix=f".{config_path.name}.",
                    suffix=".rollback",
                )
                rollback = Path(rollback_name)
                try:
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(config_original)
                    os.replace(rollback, config_path)
                finally:
                    rollback.unlink(missing_ok=True)
        return {
            "ok": False,
            "created": [],
            "unchanged": unchanged,
            "findings": [
                Finding("error", "init_write_failed", str(exc), CONFIG_NAME).as_dict()
            ],
        }, 1
    return {"ok": True, "created": created, "unchanged": unchanged, "findings": []}, 0


def print_text(command: str, payload: dict[str, Any]) -> None:
    if command == "assess" and "decision" in payload:
        print(f"{payload['decision']} (can implement: {payload['can_implement']}; docs ready: {payload['can_close_docs']})")
        for group in ("blocking", "unknown", "background", "warnings"):
            for row in payload[group]:
                print(f"{group}: {row.get('path', '')} [{row['code']}] {row.get('message', '')}")
        return
    if command == "check":
        summary = payload.get("summary", {})
        print(
            f"docs-architect check: {summary.get('errors', 0)} error(s), "
            f"{summary.get('warnings', 0)} warning(s), "
            f"{summary.get('artifacts', 0)} artifact(s)"
        )
    elif command == "impact":
        print(f"Changed files: {len(payload.get('changed_files', []))}")
        print(f"Affected documents: {len(payload.get('affected_documents', []))}")
        for document in payload.get("affected_documents", []):
            print(f"- {document['id']}: {document['path']} ({'; '.join(document['reasons'])})")
        if payload.get("semantic_review_recommended"):
            print("Semantic review recommended for unmatched changed files.")
    elif command == "index":
        for path, status in payload.get("files", {}).items():
            print(f"{status}: {path}")
        if not payload.get("write") and payload.get("markdown_preview"):
            print(payload["markdown_preview"], end="")
    elif command == "init":
        for path in payload.get("created", []):
            print(f"created: {path}")
        for path in payload.get("unchanged", []):
            print(f"unchanged: {path}")
    for finding in payload.get("findings", []):
        location = f" {finding['path']}:" if finding.get("path") else ""
        print(
            f"{finding['severity'].upper()}{location} "
            f"[{finding['code']}] {finding['message']}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Target repository root.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create minimal governance directories and config.")
    init_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    check_parser = subparsers.add_parser("check", help="Validate documentation structure and metadata.")
    check_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    impact_parser = subparsers.add_parser("impact", help="Find documentation affected by changed files.")
    impact_parser.add_argument("--base", help="Git base ref for committed changes.")
    impact_parser.add_argument("--changed", nargs="+", help="Explicit repository-relative changed paths.")
    impact_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    assess = subparsers.add_parser("assess", help="Decide scoped documentation readiness, not full audit health.")
    assess.add_argument("--base", help="Baseline revision (default: HEAD)")
    assess.add_argument("--changed", nargs="+", help="Additional paths; does not hide the Git delta")
    assess.add_argument("--json", action="store_true")

    index_parser = subparsers.add_parser("index", help="Preview or write deterministic traceability indexes.")
    index_parser.add_argument("--write", action="store_true", help="Write generated index files.")
    index_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "init":
            payload, exit_code = run_init(root)
        elif args.command == "check":
            payload, exit_code = run_check(root)
        elif args.command == "assess":
            payload, exit_code = run_assess(root, args.changed, args.base)
        elif args.command == "impact":
            payload, exit_code = run_impact(root, args.changed, args.base)
        else:
            payload, exit_code = run_index(root, args.write)
    except (OSError, UnicodeError, ValueError) as exc:
        payload = {
            "ok": False,
            "findings": [
                Finding(
                    "error",
                    "operation_failed",
                    str(exc),
                    ".",
                ).as_dict()
            ],
        }
        exit_code = 1
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_text(args.command, payload)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
