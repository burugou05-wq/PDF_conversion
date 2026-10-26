"""Regression checks for the release workflow (A-1).

These are deliberately plain-text assertions so the test suite needs no YAML
dependency. They guard the properties that make published releases immutable.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
PUBLISH_JOB = TEXT[TEXT.index("  publish-release:") :]


def test_manual_dispatch_cannot_publish():
    condition = PUBLISH_JOB.split("steps:", 1)[0]
    assert "github.event_name == 'push'" in condition
    assert "startsWith(github.ref, 'refs/tags/v')" in condition
    assert "workflow_dispatch" not in condition


def test_release_environment_and_attestation_permissions():
    header = PUBLISH_JOB.split("steps:", 1)[0]
    assert "environment: release" in header
    assert "contents: write" in header
    assert "id-token: write" in header
    assert "attestations: write" in header
    assert re.search(r"actions/attest-build-provenance@[0-9a-f]{40}", PUBLISH_JOB)


def test_existing_release_is_never_overwritten():
    assert "--clobber" not in PUBLISH_JOB
    assert "gh release upload" not in PUBLISH_JOB
    assert PUBLISH_JOB.count("refusing to modify assets") >= 2
    assert "--verify-tag" in PUBLISH_JOB


def test_signature_is_created_before_publish():
    assert "RELEASE_SIGNING_KEY_B64" in PUBLISH_JOB
    assert "SHA256SUMS.txt.sig" in PUBLISH_JOB
    assert PUBLISH_JOB.index("scripts/release_signing.py sign") < PUBLISH_JOB.index(
        "gh release create"
    )
