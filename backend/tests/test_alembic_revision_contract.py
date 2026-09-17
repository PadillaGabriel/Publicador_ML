from pathlib import Path
import re


REVISION_PATTERN = re.compile(r'^revision\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
ALEMBIC_VERSION_MAX_LENGTH = 32


def test_all_alembic_revision_ids_fit_version_table_contract():
    versions_dir = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    violations = []

    for migration in sorted(versions_dir.glob("*.py")):
        match = REVISION_PATTERN.search(migration.read_text(encoding="utf-8"))
        if match is None:
            continue
        revision = match.group(1)
        if len(revision) > ALEMBIC_VERSION_MAX_LENGTH:
            violations.append((migration.name, revision, len(revision)))

    assert violations == [], f"Alembic revision IDs exceed VARCHAR(32): {violations}"
