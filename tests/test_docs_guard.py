from __future__ import annotations

import contextlib
import io
import json
import os
import unittest.mock
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import docs_guard


def metadata_comment(metadata: dict[str, object]) -> str:
    return "<!-- docs-architect-meta\n" + json.dumps(metadata, indent=2) + "\n-->\n"


def base_requirement(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "id": "REQ-2026-001",
        "type": "requirement",
        "title": "Example requirement",
        "status": "accepted",
        "owners": ["team-docs"],
        "origin": {"kind": "request", "ref": "User request"},
        "approval": {
            "kind": "issue-state",
            "ref": "https://example.com/issues/1#accepted",
        },
        "sources": [],
        "update_when": [],
        "relations": [],
        "dependencies": [],
        "affected_code": ["src/**"],
        "affected_docs": ["docs/SYSTEM.md"],
        "evidence": [],
        "open_questions": [],
        "documentation_disposition": "pending",
        "acceptance": [
            {
                "id": "AC-1",
                "text": "Behavior is observable",
                "status": "pending",
                "evidence": [],
            }
        ],
    }
    value.update(overrides)
    return value


def system_doc(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "id": "SYS-api",
        "type": "system-doc",
        "title": "API behavior",
        "status": "active",
        "owners": ["team-api"],
        "sources": ["src/api/**"],
        "update_when": ["config/routes.json"],
        "relations": [],
        "affected_docs": [],
    }
    value.update(overrides)
    return value


class DocsGuardTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        payload, exit_code = docs_guard.run_init(self.root)
        self.assertEqual(exit_code, 0, payload)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_artifact(self, relative: str, metadata: dict[str, object], body: str = "") -> Path:
        return self.write(relative, metadata_comment(metadata) + "\n" + body)

    def commit_fixture(self) -> None:
        for cmd in (["init", "-q"], ["add", "."], ["-c", "user.name=Fixture", "-c", "user.email=test@example.test", "commit", "-qm", "baseline"]):
            subprocess.run(["git", *cmd], cwd=self.root, check=True, capture_output=True)

    def test_assess_separates_background_debt_and_full_index_gate(self) -> None:
        self.write_artifact("docs/legacy.md", system_doc(id="SYS-legacy", title="", sources=["old/**"]))
        self.write("docs/how-to.md", "# Plain Markdown")
        self.commit_fixture()
        self.write("src/fix.py", "FIX = True")
        result, code = docs_guard.run_assess(self.root, ["src/fix.py"], None)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["decision"], "continue_with_debt")
        self.assertFalse(result["audit_ok"])
        self.assertEqual({row["path"] for row in result["background"]}, {"docs/legacy.md"})
        self.assertEqual(len(result["file_digests"]["src/fix.py"]), 64)
        self.assertEqual(docs_guard.run_check(self.root)[1], 1)
        self.assertEqual(docs_guard.run_index(self.root, True)[1], 1)
        self.write("docs/legacy.md", "# plain now")
        result, code = docs_guard.run_assess(self.root, ["src/fix.py"], None)
        self.assertEqual(code, 1, result)
        self.assertIn("managed_marker_removed", {r["code"] for r in result["blocking"]})

    def test_assess_linked_artifact_and_missing_baseline_are_not_clean(self) -> None:
        self.write_artifact("docs/api.md", system_doc(title=""))
        self.commit_fixture()
        self.write("src/api/entry.py", "value = 1")
        result, code = docs_guard.run_assess(self.root, None, "HEAD")
        self.assertEqual(code, 1)
        self.assertTrue(result["can_implement"])
        self.assertIn("docs/api.md", {r.get("path") for r in result["blocking"]})
        result, code = docs_guard.run_assess(self.root, ["src/api/entry.py"], "not-a-ref")
        self.assertEqual(code, 1)
        self.assertIn("baseline_unknown", {r["code"] for r in result["unknown"]})

    def test_opaque_historical_identity_does_not_certify_or_stop_implementation(self) -> None:
        self.write_artifact("docs/old.md", {"schema_version": 1, "id": "SYS-legacy"})
        self.commit_fixture()
        self.write("src/new.py", "value = 1")
        result, code = docs_guard.run_assess(self.root, None, None)
        self.assertEqual(code, 1, result)
        self.assertTrue(result["can_implement"])
        self.assertFalse(result["can_close_docs"])
        self.assertIn("docs/old.md", {r.get("path") for r in result["unknown"]})
        (self.root / "docs/old.md").write_bytes(b"\xff")
        result, code = docs_guard.run_assess(self.root, None, None)
        self.assertEqual(code, 1)
        self.assertIn("unreadable_managed_file", {r["code"] for r in result["unknown"]})

    def test_scoped_product_spec_can_own_updated_behavior(self) -> None:
        self.write_artifact("docs/SYSTEM.md", system_doc(type="product-spec"))
        self.write_artifact("docs/req.md", base_requirement(documentation_disposition="updated", affected_code=["src/api/x.py"]))
        self.assertIn("missing_current_state_affected_doc", {f["code"] for f in docs_guard.run_check(self.root)[0]["findings"]})
        config = self.root / docs_guard.CONFIG_NAME
        config.write_text(json.dumps(dict(json.loads(config.read_text()), change_policy="scoped")), encoding="utf-8")
        self.assertNotIn("missing_current_state_affected_doc", {f["code"] for f in docs_guard.run_check(self.root)[0]["findings"]})
        config.write_text(json.dumps(dict(json.loads(config.read_text()), change_policy="typo")), encoding="utf-8")
        self.assertEqual(docs_guard.run_check(self.root)[1], 1)

    def sha256_revision(self, relative: str) -> str:
        path = self.root / relative
        digest = docs_guard.hashlib.sha256(path.read_bytes()).hexdigest()
        return f"sha256:{digest}@{relative}"

    def captured_result_evidence(self) -> list[dict[str, str]]:
        self.write(
            "evidence/check.txt",
            "command: python -m unittest\nresult: passed\n",
        )
        return [
            {
                "kind": "command",
                "ref": "evidence/check.txt",
                "description": "Captured verification command and passing result",
            }
        ]

    def finding_codes(self, payload: dict[str, object]) -> set[str]:
        findings = payload.get("findings", [])
        self.assertIsInstance(findings, list)
        return {item["code"] for item in findings if isinstance(item, dict)}

    def test_multiline_metadata_parses_and_valid_repository_passes(self) -> None:
        self.write("src/api/handler.py", "def handle():\n    return 'ok'\n")
        self.write_artifact("docs/requirements/REQ-2026-001.md", base_requirement())
        self.write_artifact("docs/SYSTEM.md", system_doc(), "See [requirement](requirements/REQ-2026-001.md).\n")

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 0, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["artifacts"], 2)

    def test_duplicate_ids_are_errors(self) -> None:
        self.write_artifact("docs/a.md", system_doc())
        self.write_artifact("docs/b.md", system_doc(title="Duplicate"))

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("duplicate_id", self.finding_codes(payload))

    def test_broken_local_link_is_an_error(self) -> None:
        self.write("docs/guide.md", "[missing](does-not-exist.md)\n")

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("broken_link", self.finding_codes(payload))

    def test_done_requirement_requires_acceptance_and_documentation_evidence(self) -> None:
        requirement = base_requirement(
            status="done",
            acceptance=[
                {
                    "id": "AC-1",
                    "text": "Behavior is observable",
                    "status": "passed",
                    "evidence": [],
                }
            ],
            affected_docs=[],
            documentation_disposition="pending",
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", requirement)

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        codes = self.finding_codes(payload)
        self.assertIn("missing_acceptance_evidence", codes)
        self.assertIn("documentation_pending", codes)

    def test_done_requirement_allows_evidenced_no_change(self) -> None:
        self.write("tests/test_api.py", "def test_behavior():\n    pass\n")
        result_evidence = self.captured_result_evidence()
        requirement = base_requirement(
            status="done",
            acceptance=[
                {
                    "id": "AC-1",
                    "text": "Behavior is observable",
                    "status": "passed",
                    "evidence": [
                        {
                            "kind": "test",
                            "ref": "tests/test_api.py::test_behavior",
                            "description": "Test definition",
                        }
                    ],
                }
            ],
            evidence=result_evidence,
            affected_docs=[],
            documentation_disposition="no_change_required",
            no_doc_change_scope=["tests/test_api.py"],
            no_doc_change_reason=(
                "Reviewed the test-only fixture scope; runtime behavior and existing "
                "durable documentation remain unchanged."
            ),
            verified_at="2026-08-12",
            verified_against=self.sha256_revision("evidence/check.txt"),
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", requirement)

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 0, payload)

    def test_impact_matches_sources_and_traverses_relations(self) -> None:
        self.write("src/api/handler.py", "changed\n")
        requirement = base_requirement(
            affected_code=[],
            relations=[{"type": "related_to", "target": "SYS-api"}],
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", requirement)
        self.write_artifact("docs/SYSTEM.md", system_doc())

        payload, exit_code = docs_guard.run_impact(
            self.root, ["src/api/handler.py"], None
        )

        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(
            [item["id"] for item in payload["affected_documents"]],
            ["REQ-2026-001", "SYS-api"],
        )
        requirement_result = next(
            item
            for item in payload["affected_documents"]
            if item["id"] == "REQ-2026-001"
        )
        self.assertIn("relation traversal", requirement_result["reasons"][0])

    def test_impact_reports_full_multihop_relation_path(self) -> None:
        self.write("src/api/handler.py", "changed\n")
        self.write_artifact(
            "docs/A.md",
            system_doc(
                id="SYS-a",
                sources=["src/api/**"],
                relations=[{"type": "related_to", "target": "SYS-b"}],
            ),
        )
        self.write_artifact(
            "docs/B.md",
            system_doc(
                id="SYS-b",
                sources=[],
                relations=[{"type": "related_to", "target": "SYS-c"}],
            ),
        )
        self.write_artifact("docs/C.md", system_doc(id="SYS-c", sources=[]))

        payload, exit_code = docs_guard.run_impact(
            self.root, ["src/api/handler.py"], None
        )

        self.assertEqual(exit_code, 0, payload)
        result = next(
            item for item in payload["affected_documents"] if item["id"] == "SYS-c"
        )
        self.assertIn("SYS-a --related_to--> SYS-b --related_to--> SYS-c", result["reasons"][0])

    def test_impact_traverses_requirement_dependencies(self) -> None:
        self.write("src/dependency.py", "changed\n")
        self.write_artifact(
            "docs/requirements/REQ-2026-002.md",
            base_requirement(
                id="REQ-2026-002",
                title="Dependency",
                affected_code=["src/dependency.py"],
            ),
        )
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                dependencies=["REQ-2026-002"],
                affected_code=[],
            ),
        )

        payload, exit_code = docs_guard.run_impact(
            self.root, ["src/dependency.py"], None
        )

        self.assertEqual(exit_code, 0, payload)
        dependent = next(
            item
            for item in payload["affected_documents"]
            if item["id"] == "REQ-2026-001"
        )
        self.assertIn("reverse:depends_on", dependent["reasons"][0])

    def test_impact_reports_unmatched_change_for_semantic_review(self) -> None:
        self.write_artifact("docs/SYSTEM.md", system_doc(sources=[]))

        payload, exit_code = docs_guard.run_impact(self.root, ["src/new.py"], None)

        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(payload["affected_documents"], [])
        self.assertTrue(payload["semantic_review_recommended"])

    def test_impact_still_reports_matches_when_repository_has_validation_errors(self) -> None:
        self.write("src/api.py", "changed\n")
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                status="done",
                affected_code=["src/api.py"],
                documentation_disposition="pending",
            ),
        )

        payload, exit_code = docs_guard.run_impact(
            self.root, ["src/api.py"], None
        )

        self.assertEqual(exit_code, 1, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(
            [item["id"] for item in payload["affected_documents"]],
            ["REQ-2026-001"],
        )
        self.assertIn("incomplete_acceptance", self.finding_codes(payload))

    def test_index_generation_is_deterministic_and_idempotent(self) -> None:
        self.write("src/api/handler.py", "changed\n")
        self.write_artifact("docs/SYSTEM.md", system_doc())

        first, first_exit = docs_guard.run_index(self.root, True)
        json_path = self.root / "docs/generated/traceability.json"
        first_content = json_path.read_text(encoding="utf-8")
        second, second_exit = docs_guard.run_index(self.root, True)

        self.assertEqual(first_exit, 0, first)
        self.assertEqual(second_exit, 0, second)
        self.assertEqual(first_content, json_path.read_text(encoding="utf-8"))
        self.assertEqual(set(first["files"].values()), {"updated"})
        self.assertEqual(set(second["files"].values()), {"unchanged"})

    def test_index_preview_survives_validation_errors_but_write_is_blocked(self) -> None:
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                status="done",
                documentation_disposition="pending",
            ),
        )

        preview, preview_exit = docs_guard.run_index(self.root, False)
        written, write_exit = docs_guard.run_index(self.root, True)

        self.assertEqual(preview_exit, 1, preview)
        self.assertFalse(preview["ok"])
        self.assertIn("REQ-2026-001", preview["markdown_preview"])
        self.assertTrue(preview["files"])
        self.assertEqual(write_exit, 1, written)
        self.assertFalse((self.root / "docs/generated/traceability.json").exists())

    def test_init_preserves_existing_configuration_when_no_merge_is_needed(self) -> None:
        config_path = self.root / docs_guard.CONFIG_NAME
        original = config_path.read_text(encoding="utf-8")

        payload, exit_code = docs_guard.run_init(self.root)

        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(config_path.read_text(encoding="utf-8"), original)
        self.assertIn(docs_guard.CONFIG_NAME, payload["unchanged"])

    def test_init_merges_new_canonical_document_into_existing_configuration(self) -> None:
        config_path = self.root / docs_guard.CONFIG_NAME
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["custom_policy"] = {"preserve": True}
        config_path.write_text(json.dumps(config, indent=4) + "\n", encoding="utf-8")
        self.write("docs/index.md", "# Documentation\n")
        self.write("ARCHITECTURE.md", "# Architecture\n")

        first, first_exit = docs_guard.run_init(self.root)
        merged = json.loads(config_path.read_text(encoding="utf-8"))
        first_bytes = config_path.read_bytes()
        check, check_exit = docs_guard.run_check(self.root)
        second, second_exit = docs_guard.run_init(self.root)

        self.assertEqual(first_exit, 0, first)
        self.assertIn(".docs-architect.json (updated)", first["created"])
        self.assertEqual(merged["docs_roots"], ["docs", "ARCHITECTURE.md"])
        self.assertEqual(merged["custom_policy"], {"preserve": True})
        self.assertEqual(check_exit, 0, check)
        self.assertEqual(second_exit, 0, second)
        self.assertEqual(config_path.read_bytes(), first_bytes)
        self.assertIn(docs_guard.CONFIG_NAME, second["unchanged"])

    def test_cli_json_output_is_machine_readable(self) -> None:
        self.write_artifact("docs/requirements/REQ-2026-001.md", base_requirement())
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            exit_code = docs_guard.main(["--root", str(self.root), "check", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])

    def test_absolute_metadata_paths_are_rejected(self) -> None:
        self.write_artifact(
            "docs/SYSTEM.md", system_doc(sources=["C:/private/source.py"])
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("unsafe_path", self.finding_codes(payload))

    def test_advanced_requirement_requires_structured_origin(self) -> None:
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(origin="User request"),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid_origin", self.finding_codes(payload))
        self.assertIn("missing_origin", self.finding_codes(payload))

    def test_advanced_requirement_requires_explicit_approval(self) -> None:
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(approval=None),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("missing_approval", self.finding_codes(payload))

    def test_relation_and_dependency_may_target_existing_paths(self) -> None:
        self.write("docs/external-spec.md", "# External specification\n")
        requirement = base_requirement(
            dependencies=["docs/external-spec.md"],
            relations=[{"type": "derives_from", "target": "docs/external-spec.md"}],
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", requirement)

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 0, payload)

    def test_custom_generated_directory_uses_correct_links_and_init_path(self) -> None:
        config_path = self.root / docs_guard.CONFIG_NAME
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["generated_dir"] = "artifacts/docs-index"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.write("src/api/handler.py", "changed\n")
        self.write_artifact("docs/SYSTEM.md", system_doc())

        init_payload, init_exit = docs_guard.run_init(self.root)
        index_payload, index_exit = docs_guard.run_index(self.root, True)
        generated = self.root / "artifacts/docs-index/traceability.md"

        self.assertEqual(init_exit, 0, init_payload)
        self.assertEqual(index_exit, 0, index_payload)
        self.assertTrue((self.root / "artifacts/docs-index").is_dir())
        self.assertIn("../../docs/SYSTEM.md", generated.read_text(encoding="utf-8"))

    def test_nested_globs_match_zero_or_more_directories(self) -> None:
        self.assertTrue(docs_guard.matches_pattern("src/api.py", "src/**/api.py"))
        self.assertTrue(docs_guard.matches_pattern("src/v1/api.py", "src/**/api.py"))
        self.assertTrue(docs_guard.matches_pattern("src/api/v1.py", "src/**"))
        self.assertFalse(docs_guard.matches_pattern("src2/api.py", "src/**"))

    def test_duplicate_metadata_keys_are_rejected(self) -> None:
        self.write(
            "docs/duplicate.md",
            '<!-- docs-architect-meta {"schema_version":1,"id":"A","id":"B"} -->\n',
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid_metadata_json", self.finding_codes(payload))

    def test_passed_acceptance_requires_resolvable_evidence(self) -> None:
        requirement = base_requirement(
            acceptance=[
                {
                    "id": "AC-1",
                    "text": "Behavior is observable",
                    "status": "passed",
                    "evidence": [
                        {
                            "kind": "test",
                            "ref": "tests/missing.py::test_behavior",
                            "description": "Expected regression test",
                        }
                    ],
                }
            ]
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", requirement)

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("unresolvable_evidence", self.finding_codes(payload))

    def test_done_requirement_rejects_open_questions(self) -> None:
        self.write("tests/test_api.py", "# evidence\n")
        self.write("docs/SYSTEM.md", "# System\n")
        requirement = base_requirement(
            status="done",
            acceptance=[
                {
                    "id": "AC-1",
                    "text": "Behavior is observable",
                    "status": "passed",
                    "evidence": [
                        {
                            "kind": "test",
                            "ref": "tests/test_api.py",
                            "description": "Passed",
                        }
                    ],
                }
            ],
            affected_docs=["docs/SYSTEM.md"],
            open_questions=["Does this work for every tenant?"],
            documentation_disposition="updated",
            verified_at="2026-08-12",
            verified_against="0123456789abcdef",
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", requirement)

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("unresolved_questions", self.finding_codes(payload))

    def test_impact_matches_affected_document_paths(self) -> None:
        self.write("docs/SYSTEM.md", "changed\n")
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(affected_docs=["docs/SYSTEM.md"]),
        )

        payload, exit_code = docs_guard.run_impact(
            self.root, ["docs/SYSTEM.md"], None
        )

        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(
            [item["id"] for item in payload["affected_documents"]],
            ["REQ-2026-001"],
        )

    def test_verification_anchor_fields_must_be_paired(self) -> None:
        self.write("src/api/handler.py", "changed\n")
        self.write_artifact(
            "docs/SYSTEM.md", system_doc(verified_at="2026-08-12")
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("incomplete_verification_anchor", self.finding_codes(payload))

    def test_windows_drive_relative_paths_are_rejected(self) -> None:
        self.write_artifact(
            "docs/SYSTEM.md", system_doc(sources=["C:private/source.py"])
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("unsafe_path", self.finding_codes(payload))

    def test_done_requirement_rejects_incomplete_requirement_dependency(self) -> None:
        self.write("tests/test_api.py", "# evidence\n")
        self.write("docs/SYSTEM.md", "# System\n")
        dependency = base_requirement(
            id="REQ-2026-002", title="Dependency", status="in_progress"
        )
        requirement = base_requirement(
            status="done",
            dependencies=["REQ-2026-002"],
            acceptance=[
                {
                    "id": "AC-1",
                    "text": "Behavior is observable",
                    "status": "passed",
                    "evidence": [
                        {
                            "kind": "test",
                            "ref": "tests/test_api.py",
                            "description": "Passed",
                        }
                    ],
                }
            ],
            affected_docs=["docs/SYSTEM.md"],
            documentation_disposition="updated",
            verified_at="2026-08-12",
            verified_against="0123456789abcdef",
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", requirement)
        self.write_artifact("docs/requirements/REQ-2026-002.md", dependency)

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("unresolved_dependency", self.finding_codes(payload))

    def test_malformed_metadata_shapes_return_findings_instead_of_crashing(self) -> None:
        self.write_artifact(
            "docs/SYSTEM.md",
            system_doc(sources=1, relations=None),  # type: ignore[arg-type]
        )
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(dependencies=None),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid_field", self.finding_codes(payload))
        self.assertIn("invalid_relations", self.finding_codes(payload))

    def test_schema_version_rejects_boolean_float_and_nonfinite_json(self) -> None:
        for name, raw_version in (("bool", "true"), ("float", "1.0")):
            self.write(
                f"docs/{name}.md",
                '<!-- docs-architect-meta {"schema_version":'
                + raw_version
                + ',"id":"SYS-'
                + name
                + '","type":"system-doc","title":"Bad","status":"active"} -->\n',
            )
        self.write(
            "docs/nonfinite.md",
            '<!-- docs-architect-meta {"schema_version":1,"id":"SYS-nan",'
            '"type":"system-doc","title":"Bad","status":"active","value":NaN} -->\n',
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        codes = self.finding_codes(payload)
        self.assertIn("unsupported_schema", codes)
        self.assertIn("invalid_metadata_json", codes)

    def test_unclosed_second_metadata_marker_is_rejected(self) -> None:
        self.write_artifact("docs/SYSTEM.md", system_doc())
        path = self.root / "docs/SYSTEM.md"
        path.write_text(
            path.read_text(encoding="utf-8") + "\n<!-- docs-architect-meta {\n",
            encoding="utf-8",
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid_metadata_comment", self.finding_codes(payload))

    def test_windows_rooted_alias_and_reserved_paths_are_rejected(self) -> None:
        unsafe = [
            r"\Windows",
            "/etc",
            "...",
            "docs/trailing.",
            "docs/trailing ",
            "docs/CON",
            "C:relative.txt",
            "C:/absolute.txt",
        ]
        for value in unsafe:
            self.assertFalse(docs_guard.is_safe_relative(value), value)

    def test_absolute_windows_evidence_and_markdown_links_are_rejected(self) -> None:
        requirement = base_requirement(
            status="done",
            acceptance=[
                {
                    "id": "AC-1",
                    "text": "Behavior is observable",
                    "status": "passed",
                    "evidence": [
                        {
                            "kind": "test",
                            "ref": "C:/missing.py::test_behavior",
                            "description": "Claimed test",
                        }
                    ],
                }
            ],
            affected_docs=[],
            documentation_disposition="no_change_required",
            no_doc_change_reason="The examined behavior is internal and existing docs remain true.",
            verified_at="2026-08-12",
            verified_against="0123456789abcdef",
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", requirement)
        self.write("docs/guide.md", "[private](C:/missing.md)\n")

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        codes = self.finding_codes(payload)
        self.assertIn("unsafe_evidence_path", codes)
        self.assertIn("link_outside_root", codes)

    def test_bare_command_evidence_and_unstable_completion_revision_fail(self) -> None:
        requirement = base_requirement(
            status="done",
            acceptance=[
                {
                    "id": "AC-1",
                    "text": "Behavior is observable",
                    "status": "passed",
                    "evidence": [
                        {"kind": "command", "ref": "false", "description": "Claimed"}
                    ],
                }
            ],
            affected_docs=[],
            documentation_disposition="no_change_required",
            no_doc_change_reason="The examined behavior is internal and existing docs remain true.",
            verified_at="2026-08-12",
            verified_against="HEAD",
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", requirement)

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        codes = self.finding_codes(payload)
        self.assertIn("unresolvable_evidence", codes)
        self.assertIn("unstable_completion_revision", codes)

    def test_captured_command_evidence_is_resolvable(self) -> None:
        self.write("evidence/check.txt", "command: python -m unittest\nresult: passed\n")
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                acceptance=[
                    {
                        "id": "AC-1",
                        "text": "Behavior is observable",
                        "status": "passed",
                        "evidence": [
                            {
                                "kind": "command",
                                "ref": "evidence/check.txt",
                                "description": "Captured command and result",
                            }
                        ],
                    }
                ]
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 0, payload)

    def test_python_test_locators_resolve_real_functions_and_methods(self) -> None:
        self.write(
            "tests/test_api.py",
            "def test_top():\n    pass\n\n"
            "async def test_async():\n    pass\n\n"
            "class TestApi:\n    def test_method(self):\n        pass\n",
        )
        artifact_path = self.write_artifact(
            "docs/requirements/REQ-2026-001.md", base_requirement()
        )
        artifact, _ = docs_guard.parse_artifact(artifact_path, self.root)
        assert artifact is not None

        references = [
            "tests/test_api.py::test_top",
            "tests/test_api.py::test_async[param-value]",
            "tests/test_api.py::TestApi::test_method[param]",
        ]
        for reference in references:
            with self.subTest(reference=reference):
                findings = docs_guard.validate_evidence_references(
                    [
                        {
                            "kind": "test",
                            "ref": reference,
                            "description": "Collected test definition",
                        }
                    ],
                    artifact,
                    self.root,
                )
                self.assertEqual(findings, [])

    def test_python_test_locator_rejects_missing_or_text_only_names(self) -> None:
        self.write(
            "tests/test_api.py",
            "# def test_comment_only(): pass\n"
            "TEXT = 'def test_string_only(): pass'\n"
            "class TestApi:\n    def test_real(self):\n        pass\n",
        )
        artifact_path = self.write_artifact(
            "docs/requirements/REQ-2026-001.md", base_requirement()
        )
        artifact, _ = docs_guard.parse_artifact(artifact_path, self.root)
        assert artifact is not None

        references = [
            "tests/test_api.py::test_missing",
            "tests/test_api.py::test_comment_only",
            "tests/test_api.py::test_string_only",
            "tests/test_api.py::TestMissing::test_real",
            "tests/test_api.py::TestApi::test_missing",
            "tests/test_api.py::",
        ]
        for reference in references:
            with self.subTest(reference=reference):
                findings = docs_guard.validate_evidence_references(
                    [
                        {
                            "kind": "test",
                            "ref": reference,
                            "description": "Claimed test definition",
                        }
                    ],
                    artifact,
                    self.root,
                )
                self.assertIn(
                    "unresolvable_test_locator",
                    {finding.code for finding in findings},
                )

    def test_test_locator_handles_line_ranges_and_non_python_frameworks(self) -> None:
        self.write("tests/check.ts", "line one\nline two\nline three\n")
        artifact_path = self.write_artifact(
            "docs/requirements/REQ-2026-001.md", base_requirement()
        )
        artifact, _ = docs_guard.parse_artifact(artifact_path, self.root)
        assert artifact is not None

        valid = docs_guard.validate_evidence_references(
            [
                {
                    "kind": "test",
                    "ref": "tests/check.ts#L2-L3",
                    "description": "Line-addressed test definition",
                },
                {
                    "kind": "test",
                    "ref": "tests/check.ts",
                    "description": "Framework-neutral file reference",
                },
            ],
            artifact,
            self.root,
        )
        invalid_line = docs_guard.validate_evidence_references(
            [
                {
                    "kind": "test",
                    "ref": "tests/check.ts#L4",
                    "description": "Out-of-range line",
                }
            ],
            artifact,
            self.root,
        )
        unsupported = docs_guard.validate_evidence_references(
            [
                {
                    "kind": "test",
                    "ref": "tests/check.ts::test_name",
                    "description": "Unsupported node locator",
                }
            ],
            artifact,
            self.root,
        )

        self.assertEqual(valid, [])
        self.assertIn(
            "unresolvable_test_locator", {finding.code for finding in invalid_line}
        )
        self.assertIn(
            "unsupported_test_locator", {finding.code for finding in unsupported}
        )

    def test_advanced_requirement_rejects_agent_or_insecure_approval(self) -> None:
        for approval in (
            {"kind": "agent", "ref": "Agent approved its own proposal"},
            {"kind": "issue-state", "ref": "http://example.com/issues/1"},
            {"kind": "request", "ref": "User approved"},
        ):
            with self.subTest(approval=approval):
                self.write_artifact(
                    "docs/requirements/REQ-2026-001.md",
                    base_requirement(approval=approval),
                )
                payload, exit_code = docs_guard.run_check(self.root)
                self.assertEqual(exit_code, 1, payload)
                self.assertIn("invalid_approval", self.finding_codes(payload))

    def test_repository_approval_record_must_exist_and_not_be_self_reference(self) -> None:
        missing = base_requirement(
            approval={"kind": "request-record", "ref": "evidence/request.md"}
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", missing)
        missing_payload, missing_exit = docs_guard.run_check(self.root)

        self.write("evidence/request.md", "User approval captured from request.\n")
        valid_payload, valid_exit = docs_guard.run_check(self.root)

        self.assertEqual(missing_exit, 1, missing_payload)
        self.assertIn("invalid_approval", self.finding_codes(missing_payload))
        self.assertEqual(valid_exit, 0, valid_payload)

        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                approval={
                    "kind": "request-record",
                    "ref": "docs/requirements/REQ-2026-001.md",
                }
            ),
        )
        self_payload, self_exit = docs_guard.run_check(self.root)
        self.assertEqual(self_exit, 1, self_payload)
        self.assertIn("invalid_approval", self.finding_codes(self_payload))

    def test_verification_revision_requires_resolvable_commit_or_digest(self) -> None:
        self.write("evidence/result.txt", "result: passed\n")
        digest_revision = self.sha256_revision("evidence/result.txt")
        self.assertTrue(
            docs_guard.verification_revision_resolves(self.root, digest_revision)
        )
        self.assertFalse(
            docs_guard.verification_revision_resolves(
                self.root, "sha256:" + "0" * 64 + "@evidence/result.txt"
            )
        )
        self.assertFalse(
            docs_guard.verification_revision_resolves(
                self.root, "agent-says-current"
            )
        )

        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"], cwd=self.root, check=True
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.root, check=True)
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        self.assertTrue(docs_guard.verification_revision_resolves(self.root, commit))
        self.assertFalse(docs_guard.verification_revision_resolves(self.root, "main"))

    def test_done_requires_captured_result_beyond_test_definition(self) -> None:
        self.write("tests/test_api.py", "def test_behavior():\n    pass\n")
        requirement = base_requirement(
            status="done",
            acceptance=[
                {
                    "id": "AC-1",
                    "text": "Behavior is observable",
                    "status": "passed",
                    "evidence": [
                        {
                            "kind": "test",
                            "ref": "tests/test_api.py::test_behavior",
                            "description": "Test definition",
                        }
                    ],
                }
            ],
            affected_docs=[],
            documentation_disposition="no_change_required",
            no_doc_change_scope=["tests/test_api.py"],
            no_doc_change_reason=(
                "Reviewed the internal test scope; durable runtime documentation remains unchanged."
            ),
            verified_at="2026-08-12",
            verified_against=self.sha256_revision("tests/test_api.py"),
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", requirement)

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        codes = self.finding_codes(payload)
        self.assertIn("missing_completion_result_evidence", codes)
        self.assertIn("missing_no_doc_change_evidence", codes)

    def test_no_change_requires_scope_evidence_and_empty_affected_docs(self) -> None:
        self.write("src/internal.py", "VALUE = 1\n")
        evidence = self.captured_result_evidence()
        requirement = base_requirement(
            affected_docs=["docs/SYSTEM.md"],
            evidence=evidence,
            documentation_disposition="no_change_required",
            no_doc_change_reason="No documentation change.",
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", requirement)

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        codes = self.finding_codes(payload)
        self.assertIn("insufficient_no_doc_change_reason", codes)
        self.assertIn("missing_no_doc_change_scope", codes)
        self.assertIn("no_change_has_affected_docs", codes)

    def test_nonexistent_commit_evidence_is_rejected(self) -> None:
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                acceptance=[
                    {
                        "id": "AC-1",
                        "text": "Behavior is observable",
                        "status": "passed",
                        "evidence": [
                            {
                                "kind": "commit",
                                "ref": "deadbee",
                                "description": "Missing commit",
                            }
                        ],
                    }
                ]
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("unresolvable_evidence", self.finding_codes(payload))

    def test_unknown_evidence_kind_cannot_satisfy_acceptance(self) -> None:
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                acceptance=[
                    {
                        "id": "AC-1",
                        "text": "Behavior is observable",
                        "status": "passed",
                        "evidence": [
                            {
                                "kind": "assertion",
                                "ref": "missing",
                                "description": "Unsupported claim",
                            }
                        ],
                    }
                ]
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        codes = self.finding_codes(payload)
        self.assertIn("invalid_acceptance_evidence", codes)
        self.assertIn("missing_acceptance_evidence", codes)

    def test_git_blob_cannot_be_used_as_commit_evidence(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        evidence_path = self.write("evidence/result.txt", "passed\n")
        blob = subprocess.run(
            ["git", "hash-object", "-w", str(evidence_path)],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                acceptance=[
                    {
                        "id": "AC-1",
                        "text": "Behavior is observable",
                        "status": "passed",
                        "evidence": [
                            {
                                "kind": "commit",
                                "ref": blob,
                                "description": "Blob is not a commit",
                            }
                        ],
                    }
                ]
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        self.assertIn("unresolvable_evidence", self.finding_codes(payload))

    def test_done_requirement_requires_completion_verification(self) -> None:
        self.write("tests/test_api.py", "# evidence\n")
        requirement = base_requirement(
            status="done",
            acceptance=[
                {
                    "id": "AC-1",
                    "text": "Behavior is observable",
                    "status": "passed",
                    "evidence": [
                        {"kind": "test", "ref": "tests/test_api.py", "description": "Passed"}
                    ],
                }
            ],
            affected_docs=[],
            documentation_disposition="no_change_required",
            no_doc_change_reason="The examined behavior is internal and existing docs remain true.",
        )
        self.write_artifact("docs/requirements/REQ-2026-001.md", requirement)

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("missing_completion_verification", self.finding_codes(payload))

    def test_no_change_reason_must_be_specific_string(self) -> None:
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                documentation_disposition="no_change_required",
                no_doc_change_reason={"claimed": True},
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("missing_no_doc_change_reason", self.finding_codes(payload))

    def test_path_dependency_enforces_requirement_completion(self) -> None:
        self.write("tests/test_api.py", "# evidence\n")
        self.write("docs/SYSTEM.md", "# System\n")
        self.write_artifact(
            "docs/requirements/REQ-2026-002.md",
            base_requirement(id="REQ-2026-002", title="Dependency", status="in_progress"),
        )
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                status="done",
                dependencies=["docs/requirements/REQ-2026-002.md"],
                acceptance=[
                    {
                        "id": "AC-1",
                        "text": "Behavior is observable",
                        "status": "passed",
                        "evidence": [
                            {"kind": "test", "ref": "tests/test_api.py", "description": "Passed"}
                        ],
                    }
                ],
                affected_docs=["docs/SYSTEM.md"],
                documentation_disposition="updated",
                verified_at="2026-08-12",
                verified_against="0123456789abcdef",
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("unresolved_dependency", self.finding_codes(payload))

    def test_depends_on_relation_enforces_requirement_completion(self) -> None:
        self.write("tests/test_api.py", "# evidence\n")
        self.write_artifact(
            "docs/requirements/REQ-2026-002.md",
            base_requirement(id="REQ-2026-002", title="Dependency", status="in_progress"),
        )
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                status="done",
                dependencies=[],
                relations=[{"type": "depends_on", "target": "REQ-2026-002"}],
                acceptance=[
                    {
                        "id": "AC-1",
                        "text": "Behavior is observable",
                        "status": "passed",
                        "evidence": [
                            {"kind": "test", "ref": "tests/test_api.py", "description": "Passed"}
                        ],
                    }
                ],
                affected_docs=[],
                documentation_disposition="no_change_required",
                no_doc_change_reason="The examined behavior is internal and existing docs remain true.",
                verified_at="2026-08-12",
                verified_against="0123456789abcdef",
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        self.assertIn("unresolved_dependency", self.finding_codes(payload))

    def test_updated_disposition_rejects_source_file_as_documentation(self) -> None:
        self.write("src/app.py", "print('ok')\n")
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                affected_docs=["src/app.py"],
                documentation_disposition="updated",
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        self.assertIn("affected_doc_not_scanned", self.finding_codes(payload))

    def test_updated_disposition_rejects_requirement_self_as_only_document(self) -> None:
        requirement_path = "docs/requirements/REQ-2026-001.md"
        self.write_artifact(
            requirement_path,
            base_requirement(
                affected_docs=[requirement_path],
                documentation_disposition="updated",
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        self.assertIn("missing_current_state_affected_doc", self.finding_codes(payload))

    def test_updated_disposition_rejects_another_requirement_as_only_document(self) -> None:
        self.write_artifact(
            "docs/requirements/REQ-2026-002.md",
            base_requirement(id="REQ-2026-002", title="Related requirement"),
        )
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                affected_docs=["docs/requirements/REQ-2026-002.md"],
                documentation_disposition="updated",
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        self.assertIn("missing_current_state_affected_doc", self.finding_codes(payload))

    def test_updated_disposition_rejects_navigation_index_as_only_document(self) -> None:
        self.write("docs/requirements/INDEX.md", "# Requirement index\n")
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                affected_docs=["docs/requirements/INDEX.md"],
                documentation_disposition="updated",
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        self.assertIn("missing_current_state_affected_doc", self.finding_codes(payload))

    def test_updated_disposition_requires_governed_active_system_document(self) -> None:
        for name in ("SUMMARY.md", "TOC.md", "CHANGELOG.md", "current-state.md"):
            with self.subTest(name=name):
                self.write(f"docs/{name}", "# Not governed current state\n")
                self.write_artifact(
                    "docs/requirements/REQ-2026-001.md",
                    base_requirement(
                        affected_docs=[f"docs/{name}"],
                        documentation_disposition="updated",
                    ),
                )

                payload, exit_code = docs_guard.run_check(self.root)

                self.assertEqual(exit_code, 1, payload)
                self.assertIn(
                    "missing_current_state_affected_doc", self.finding_codes(payload)
                )

    def test_updated_disposition_rejects_non_active_system_document(self) -> None:
        for status in ("draft", "completed", "superseded", "retired"):
            with self.subTest(status=status):
                self.write_artifact("docs/SYSTEM.md", system_doc(status=status))
                self.write_artifact(
                    "docs/requirements/REQ-2026-001.md",
                    base_requirement(
                        affected_docs=["docs/SYSTEM.md"],
                        documentation_disposition="updated",
                    ),
                )

                payload, exit_code = docs_guard.run_check(self.root)

                self.assertEqual(exit_code, 1, payload)
                self.assertIn(
                    "missing_current_state_affected_doc", self.finding_codes(payload)
                )

    def test_updated_disposition_rejects_unrelated_active_system_document(self) -> None:
        self.write("src/api/handler.py", "def handle():\n    return 'ok'\n")
        self.write("src/unrelated.py", "VALUE = 1\n")
        self.write_artifact(
            "docs/SYSTEM.md",
            system_doc(sources=["src/unrelated.py"], relations=[]),
        )
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                affected_code=["src/api/handler.py"],
                affected_docs=["docs/SYSTEM.md"],
                documentation_disposition="updated",
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        self.assertIn(
            "missing_current_state_affected_doc", self.finding_codes(payload)
        )

    def test_updated_disposition_rejects_agent_adapter_as_only_document(self) -> None:
        self.write("AGENTS.md", "# Agent instructions\n")
        config_path = self.root / docs_guard.CONFIG_NAME
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["adapters"] = {"codex": ["AGENTS.md"]}
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                affected_docs=["AGENTS.md"],
                documentation_disposition="updated",
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        self.assertIn("missing_current_state_affected_doc", self.finding_codes(payload))

    def test_markdown_links_support_spaces_and_balanced_parentheses(self) -> None:
        self.write("docs/guide with spaces.md", "# Guide\n")
        self.write("docs/guide(v2).md", "# Guide\n")
        self.write(
            "docs/index.md",
            "[spaced](<guide with spaces.md>)\n[balanced](guide(v2).md)\n",
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 0, payload)

    def test_supported_external_markdown_links_are_ignored(self) -> None:
        self.write(
            "docs/index.md",
            "[web](https://example.com/a)\n[mail](mailto:test@example.com)\n",
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 0, payload)

    def test_images_and_reference_links_are_validated(self) -> None:
        self.write(
            "docs/index.md",
            "![missing image](missing.png)\n[missing guide][guide]\n\n"
            "[guide]: missing-guide.md\n",
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        self.assertEqual(
            [item["code"] for item in payload["findings"]].count("broken_link"),
            2,
        )

    def test_links_inside_fenced_code_are_not_validated(self) -> None:
        self.write(
            "docs/index.md",
            "# Example\n\n```markdown\n[example](not-a-real-file.md)\n```\n",
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 0, payload)

    def test_wrong_case_repository_link_is_rejected_on_windows_too(self) -> None:
        self.write("docs/SYSTEM.md", "# System\n")
        self.write("docs/index.md", "[system](system.md)\n")

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1)
        self.assertIn("broken_link", self.finding_codes(payload))

    def test_generated_indexes_can_rebuild_after_artifact_removal(self) -> None:
        first_path = self.write_artifact("docs/A.md", system_doc(id="SYS-a"))
        first, first_exit = docs_guard.run_index(self.root, True)
        first_path.unlink()
        self.write_artifact("docs/B.md", system_doc(id="SYS-b"))

        second, second_exit = docs_guard.run_index(self.root, True)

        self.assertEqual(first_exit, 0, first)
        self.assertEqual(second_exit, 0, second)
        ids = [row["id"] for row in second["traceability"]["artifacts"]]
        self.assertEqual(ids, ["SYS-b"])

    def test_index_write_rolls_back_when_second_replace_fails(self) -> None:
        self.write_artifact("docs/A.md", system_doc(id="SYS-a"))
        first, first_exit = docs_guard.run_index(self.root, True)
        json_path = self.root / "docs/generated/traceability.json"
        markdown_path = self.root / "docs/generated/traceability.md"
        old_json = json_path.read_bytes()
        old_markdown = markdown_path.read_bytes()
        self.write_artifact("docs/B.md", system_doc(id="SYS-b"))
        real_replace = os.replace
        replace_count = 0

        def fail_second_replace(source: object, destination: object) -> None:
            nonlocal replace_count
            replace_count += 1
            if replace_count == 2:
                raise OSError("simulated replace failure")
            real_replace(source, destination)

        with unittest.mock.patch("scripts.docs_guard.os.replace", fail_second_replace):
            second, second_exit = docs_guard.run_index(self.root, True)

        self.assertEqual(first_exit, 0, first)
        self.assertEqual(second_exit, 1, second)
        self.assertEqual(json_path.read_bytes(), old_json)
        self.assertEqual(markdown_path.read_bytes(), old_markdown)

    def test_init_preflight_leaves_no_partial_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs/decisions").write_text("occupied", encoding="utf-8")

            payload, exit_code = docs_guard.run_init(root)

            self.assertEqual(exit_code, 1, payload)
            self.assertFalse((root / docs_guard.CONFIG_NAME).exists())
            self.assertFalse((root / "docs/requirements").exists())
            self.assertIn("init_path_not_directory", self.finding_codes(payload))

    def test_git_impact_preserves_unicode_and_untracked_paths(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.root, check=True)
        self.write_artifact(
            "docs/SYSTEM.md",
            system_doc(id="SYS-unicode", sources=["src/中文.py"]),
        )
        self.write("src/中文.py", "initial\n")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=self.root, check=True)
        self.write("src/中文.py", "changed\n")
        self.write("src/new file.py", "new\n")

        payload, exit_code = docs_guard.run_impact(self.root, None, None)

        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(payload["changed_files"], ["src/new file.py", "src/中文.py"])
        self.assertEqual(
            [item["id"] for item in payload["affected_documents"]],
            ["SYS-unicode"],
        )

    def test_git_impact_reports_both_sides_of_a_rename(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.root, check=True)
        self.write_artifact(
            "docs/OLD.md",
            system_doc(id="SYS-old", title="Old path", sources=["src/old.py"]),
        )
        self.write_artifact(
            "docs/NEW.md",
            system_doc(id="SYS-new", title="New path", sources=["src/new.py"]),
        )
        self.write("src/old.py", "initial\n")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=self.root, check=True)
        subprocess.run(
            ["git", "mv", "src/old.py", "src/new.py"], cwd=self.root, check=True
        )

        payload, exit_code = docs_guard.run_impact(self.root, None, None)

        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(payload["changed_files"], ["src/new.py", "src/old.py"])
        self.assertEqual(
            [item["id"] for item in payload["affected_documents"]],
            ["SYS-new", "SYS-old"],
        )

    def test_git_impact_supports_repository_without_head(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.write_artifact(
            "docs/SYSTEM.md",
            system_doc(id="SYS-new", sources=["src/new.py"]),
        )
        self.write("src/new.py", "new\n")

        payload, exit_code = docs_guard.run_impact(self.root, None, None)

        self.assertEqual(exit_code, 0, payload)
        self.assertIn("src/new.py", payload["changed_files"])
        self.assertEqual(
            [item["id"] for item in payload["affected_documents"]], ["SYS-new"]
        )

    def test_git_unavailable_returns_structured_finding(self) -> None:
        with unittest.mock.patch(
            "scripts.docs_guard.subprocess.run", side_effect=FileNotFoundError("git")
        ):
            changed, findings = docs_guard.git_changed_files(self.root, None)

        self.assertEqual(changed, [])
        self.assertEqual([item.code for item in findings], ["git_unavailable"])

    def test_git_impact_rejects_a_target_nested_in_another_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
            nested = outer / "fixture"
            nested.mkdir()

            changed, findings = docs_guard.git_changed_files(nested, None)

        self.assertEqual(changed, [])
        self.assertEqual([item.code for item in findings], ["git_root_mismatch"])

    def test_index_preview_reports_whether_outputs_would_change(self) -> None:
        self.write_artifact("docs/A.md", system_doc(id="SYS-a"))
        first, first_exit = docs_guard.run_index(self.root, False)
        written, written_exit = docs_guard.run_index(self.root, True)
        second, second_exit = docs_guard.run_index(self.root, False)

        self.assertEqual(first_exit, 0, first)
        self.assertEqual(written_exit, 0, written)
        self.assertEqual(second_exit, 0, second)
        self.assertEqual(set(first["files"].values()), {"would_update"})
        self.assertEqual(set(second["files"].values()), {"unchanged"})

    def test_config_scan_roots_and_generated_dir_reject_globs(self) -> None:
        config = dict(docs_guard.DEFAULT_CONFIG)
        config["docs_roots"] = ["docs/**"]
        config["generated_dir"] = "docs/generated/**"

        findings = docs_guard.validate_config(config)

        self.assertEqual(
            [item.code for item in findings].count("invalid_config"), 2
        )

    def test_config_rejects_empty_or_generated_covered_document_roots(self) -> None:
        empty = dict(docs_guard.DEFAULT_CONFIG)
        empty["docs_roots"] = []
        covered = dict(docs_guard.DEFAULT_CONFIG)
        covered["docs_roots"] = ["docs"]
        covered["generated_dir"] = "docs"

        empty_findings = docs_guard.validate_config(empty)
        covered_findings = docs_guard.validate_config(covered)

        self.assertIn("invalid_config", {item.code for item in empty_findings})
        self.assertIn("invalid_config", {item.code for item in covered_findings})

    def test_check_rejects_missing_or_unscannable_document_roots(self) -> None:
        config_path = self.root / docs_guard.CONFIG_NAME
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["docs_roots"] = ["missing-docs"]
        config_path.write_text(json.dumps(config), encoding="utf-8")

        missing_payload, missing_exit = docs_guard.run_check(self.root)

        self.assertEqual(missing_exit, 1, missing_payload)
        self.assertIn("missing_docs_root", self.finding_codes(missing_payload))

        (self.root / "empty-docs").mkdir()
        config["docs_roots"] = ["empty-docs"]
        config_path.write_text(json.dumps(config), encoding="utf-8")
        empty_payload, empty_exit = docs_guard.run_check(self.root)

        self.assertEqual(empty_exit, 1, empty_payload)
        self.assertIn("docs_root_unscanned", self.finding_codes(empty_payload))

    def test_explicit_file_root_cannot_be_hidden_by_exclude_or_generated_dir(self) -> None:
        self.write("docs/index.md", "# Documentation\n")
        self.write("GUIDE.md", "[missing](missing.md)\n")
        config_path = self.root / docs_guard.CONFIG_NAME
        original = json.loads(config_path.read_text(encoding="utf-8"))

        for exclusion in ("GUIDE.md", "*.md", "G*.md", "**/*.md"):
            with self.subTest(exclusion=exclusion):
                config = dict(original)
                config["docs_roots"] = ["docs", "GUIDE.md"]
                config["exclude"] = [exclusion]
                config_path.write_text(json.dumps(config), encoding="utf-8")

                payload, exit_code = docs_guard.run_check(self.root)

                self.assertEqual(exit_code, 1, payload)
                self.assertIn("docs_root_unscanned", self.finding_codes(payload))

        generated = dict(original)
        generated["docs_roots"] = ["docs", "GUIDE.md"]
        generated["generated_dir"] = "GUIDE.md"
        config_path.write_text(json.dumps(generated), encoding="utf-8")
        payload, exit_code = docs_guard.run_check(self.root)
        self.assertEqual(exit_code, 1, payload)
        self.assertIn("invalid_config", self.finding_codes(payload))

    def test_nonmatching_exclude_still_scans_explicit_file_root(self) -> None:
        self.write("docs/index.md", "# Documentation\n")
        self.write("GUIDE.md", "[missing](missing.md)\n")
        config_path = self.root / docs_guard.CONFIG_NAME
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["docs_roots"] = ["docs", "GUIDE.md"]
        config["exclude"] = ["OTHER.md"]
        config_path.write_text(json.dumps(config), encoding="utf-8")

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        self.assertIn("broken_link", self.finding_codes(payload))
        self.assertNotIn("docs_root_unscanned", self.finding_codes(payload))

    def test_declared_adapter_cannot_be_hidden_by_exclude(self) -> None:
        self.write("docs/index.md", "# Documentation\n")
        self.write("AGENTS.md", "[missing](missing.md)\n")
        config_path = self.root / docs_guard.CONFIG_NAME
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["adapters"] = {"codex": ["AGENTS.md"]}
        config["exclude"] = ["AGENTS.md"]
        config_path.write_text(json.dumps(config), encoding="utf-8")

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        self.assertIn("adapter_unscanned", self.finding_codes(payload))

    def test_init_rejects_excluded_canonical_document_without_writes(self) -> None:
        self.write("ARCHITECTURE.md", "# Architecture\n")
        config_path = self.root / docs_guard.CONFIG_NAME
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["exclude"] = ["ARCHITECTURE.md"]
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        before = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }

        payload, exit_code = docs_guard.run_init(self.root)
        after = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }

        self.assertEqual(exit_code, 1, payload)
        self.assertIn("canonical_doc_excluded", self.finding_codes(payload))
        self.assertEqual(before, after)

    def test_done_rejects_unmanaged_path_dependency(self) -> None:
        self.write("unmanaged-dependency.md", "Status: in progress\n")
        self.write("tests/test_api.py", "def test_behavior():\n    pass\n")
        evidence = self.captured_result_evidence()
        self.write_artifact(
            "docs/requirements/REQ-2026-001.md",
            base_requirement(
                status="done",
                dependencies=["unmanaged-dependency.md"],
                acceptance=[
                    {
                        "id": "AC-1",
                        "text": "Behavior is observable",
                        "status": "passed",
                        "evidence": [
                            {
                                "kind": "test",
                                "ref": "tests/test_api.py::test_behavior",
                                "description": "Test definition",
                            }
                        ],
                    }
                ],
                evidence=evidence,
                affected_docs=[],
                documentation_disposition="no_change_required",
                no_doc_change_scope=["tests/test_api.py"],
                no_doc_change_reason=(
                    "Reviewed the internal test scope; durable runtime documentation remains unchanged."
                ),
                verified_at="2026-08-12",
                verified_against=self.sha256_revision("evidence/check.txt"),
            ),
        )

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 1, payload)
        self.assertIn("unresolved_dependency", self.finding_codes(payload))

    def test_check_requires_existing_architecture_document_to_be_scanned(self) -> None:
        self.write("docs/index.md", "# Documentation\n")
        self.write("ARCHITECTURE.md", "[missing](does-not-exist.md)\n")

        unscanned_payload, unscanned_exit = docs_guard.run_check(self.root)

        self.assertEqual(unscanned_exit, 1, unscanned_payload)
        self.assertIn(
            "canonical_doc_not_scanned", self.finding_codes(unscanned_payload)
        )

        config_path = self.root / docs_guard.CONFIG_NAME
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["docs_roots"].append("ARCHITECTURE.md")
        config_path.write_text(json.dumps(config), encoding="utf-8")

        scanned_payload, scanned_exit = docs_guard.run_check(self.root)

        self.assertEqual(scanned_exit, 1, scanned_payload)
        self.assertIn("broken_link", self.finding_codes(scanned_payload))

    def test_declared_missing_adapter_is_reported_as_a_warning(self) -> None:
        config_path = self.root / docs_guard.CONFIG_NAME
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["adapters"] = {"codex": ["AGENTS.md"]}
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.write("docs/index.md", "# Documentation\n")

        payload, exit_code = docs_guard.run_check(self.root)

        self.assertEqual(exit_code, 0, payload)
        self.assertIn("adapter_missing", self.finding_codes(payload))

    def test_default_configuration_does_not_predeclare_agent_tools(self) -> None:
        self.assertEqual(docs_guard.DEFAULT_CONFIG["adapters"], {})
        config = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "assets/templates/.docs-architect.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(config, docs_guard.DEFAULT_CONFIG)

    def test_init_registers_only_existing_agent_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".cursor/rules").mkdir(parents=True)
            (root / "AGENTS.md").write_text("# Codex\n", encoding="utf-8")
            (root / ".cursor/rules/ui.mdc").write_text(
                "---\nglobs: src/ui/**\n---\n", encoding="utf-8"
            )

            payload, exit_code = docs_guard.run_init(root)
            config = json.loads(
                (root / docs_guard.CONFIG_NAME).read_text(encoding="utf-8")
            )

        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(
            config["adapters"],
            {
                "codex": ["AGENTS.md"],
                "cursor": [".cursor/rules/ui.mdc"],
            },
        )

    def test_init_registers_existing_architecture_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ARCHITECTURE.md").write_text(
                "# Architecture\n", encoding="utf-8"
            )

            payload, exit_code = docs_guard.run_init(root)
            config = json.loads(
                (root / docs_guard.CONFIG_NAME).read_text(encoding="utf-8")
            )

        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(config["docs_roots"], ["docs", "ARCHITECTURE.md"])


class EvaluationContractTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository_root = Path(__file__).resolve().parents[1]
        cls.evaluation_path = cls.repository_root / "evals/evals.json"
        cls.payload = json.loads(cls.evaluation_path.read_text(encoding="utf-8"))

    def test_evaluation_suite_has_required_trigger_and_mode_coverage(self) -> None:
        evaluations = self.payload["evals"]
        self.assertGreaterEqual(len(evaluations), 10)
        self.assertLessEqual(len(evaluations), 24)
        self.assertEqual(len({item["id"] for item in evaluations}), len(evaluations))
        self.assertEqual(len({item["name"] for item in evaluations}), len(evaluations))

        categories = {item["category"] for item in evaluations}
        self.assertTrue(
            {
                "trigger-explicit",
                "trigger-implicit",
                "trigger-contextual",
                "trigger-negative",
            }.issubset(categories)
        )
        modes = {item["mode"] for item in evaluations if item["should_trigger"]}
        self.assertEqual(
            modes, {"audit", "init", "intake", "sync", "check", "close", "garden"}
        )
        self.assertTrue(
            all(
                item["mode"] == "none"
                for item in evaluations
                if not item["should_trigger"]
            )
        )

    def test_evaluation_fixtures_are_portable_and_exist(self) -> None:
        fixture_root = self.payload["fixture_root"]
        self.assertTrue(docs_guard.is_safe_relative(fixture_root))
        self.assertTrue((self.repository_root / fixture_root).is_dir())

        for evaluation in self.payload["evals"]:
            self.assertIsInstance(evaluation["files"], list)
            self.assertTrue(evaluation["prompt"].strip())
            self.assertTrue(evaluation["expected_output"].strip())
            self.assertTrue(evaluation["expectations"])
            self.assertTrue(evaluation["assertions"])
            for fixture in evaluation["files"]:
                with self.subTest(evaluation=evaluation["name"], fixture=fixture):
                    self.assertTrue(docs_guard.is_safe_relative(fixture))
                    self.assertTrue(fixture.startswith(f"{fixture_root}/"))
                    self.assertTrue((self.repository_root / fixture).exists())

    def test_all_requirement_fixtures_use_the_complete_requirement_shape(self) -> None:
        required = {
            "origin",
            "approval",
            "acceptance",
            "dependencies",
            "affected_code",
            "affected_docs",
            "evidence",
            "open_questions",
            "documentation_disposition",
        }
        for path in (self.repository_root / "evals/fixtures").rglob("*.md"):
            artifact, _ = docs_guard.parse_artifact(path, self.repository_root)
            if artifact is None or artifact.metadata.get("type") != "requirement":
                continue
            with self.subTest(path=path):
                self.assertEqual(required - artifact.metadata.keys(), set())

    def test_healthy_requirement_fixtures_do_not_use_fixture_approval(self) -> None:
        intentionally_invalid = {"audit-broken", "check-invalid"}
        fixture_root = self.repository_root / "evals/fixtures"
        for path in fixture_root.rglob("*.md"):
            if intentionally_invalid.intersection(path.parts):
                continue
            artifact, _ = docs_guard.parse_artifact(path, self.repository_root)
            if artifact is None or artifact.metadata.get("type") != "requirement":
                continue
            approval = artifact.metadata.get("approval")
            with self.subTest(path=path):
                if approval is not None:
                    self.assertNotEqual(approval.get("kind"), "fixture")

    def test_product_spec_eval_is_independent_of_prior_evaluations(self) -> None:
        evaluation = next(
            item
            for item in self.payload["evals"]
            if item["name"] == "create-product-spec-boundary"
        )
        combined_contract = " ".join(
            [evaluation["prompt"], evaluation["expected_output"], *evaluation["expectations"]]
        )
        self.assertIn("REQ-2026-002", combined_contract)
        self.assertIn("Create both", evaluation["expected_output"])
        self.assertNotIn("the new requirement", evaluation["prompt"].lower())

    def test_healthy_managed_fixtures_pass_docs_guard(self) -> None:
        fixture_root = self.repository_root / "evals/fixtures"
        healthy = {
            "close-incomplete",
            "close-ready",
            "cross-tool",
            "cursor-adapter",
            "impact-map",
            "intake-ready",
            "no-doc-change",
            "sync-aligned",
            "sync-stale",
        }
        for fixture_name in sorted(healthy):
            payload, exit_code = docs_guard.run_check(fixture_root / fixture_name)
            with self.subTest(fixture=fixture_name):
                self.assertEqual(exit_code, 0, payload)
                self.assertTrue(payload["ok"])

    def test_seeded_fixture_findings_remain_detectable(self) -> None:
        fixture_root = self.repository_root / "evals/fixtures"
        expected = {
            "audit-broken": {"broken_link", "incomplete_acceptance"},
            "check-invalid": {"broken_link", "duplicate_id", "missing_relation_target"},
            "garden": {"invalid_verified_against"},
        }
        for fixture_name, expected_codes in expected.items():
            payload, exit_code = docs_guard.run_check(fixture_root / fixture_name)
            codes = {finding["code"] for finding in payload["findings"]}
            with self.subTest(fixture=fixture_name):
                self.assertEqual(exit_code, 1, payload)
                self.assertTrue(expected_codes.issubset(codes), codes)

    def test_every_governed_artifact_type_has_a_template_and_eval(self) -> None:
        templates = {
            "requirement": "requirement.md",
            "product-spec": "product-spec.md",
            "decision": "decision.md",
            "exec-plan": "execution-plan.md",
            "system-doc": "system-document.md",
            "evidence": "evidence.md",
        }
        template_types = set()
        for artifact_type, filename in templates.items():
            path = self.repository_root / "assets/templates" / filename
            self.assertTrue(path.is_file())
            artifact, findings = docs_guard.parse_artifact(path, self.repository_root)
            self.assertIsNotNone(artifact, findings)
            assert artifact is not None
            self.assertEqual(artifact.metadata.get("type"), artifact_type)
            template_types.add(artifact_type)
        self.assertEqual(template_types, docs_guard.ARTIFACT_TYPES)

        evaluation_names = {item["name"] for item in self.payload["evals"]}
        self.assertIn("create-product-spec-boundary", evaluation_names)
        self.assertIn("create-evidence-manifest", evaluation_names)


if __name__ == "__main__":
    unittest.main()
