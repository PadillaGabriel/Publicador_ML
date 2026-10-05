from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / 'app'

def test_endpoint_requires_expected_version_and_lease():
    router = (BASE / 'drafts' / 'router.py').read_text()
    assert 'x_expected_product_version: uuid.UUID | None = Header(default=None)' in router
    assert 'x_product_lease_token: str | None = Header(default=None)' in router
    assert 'authorization=lambda product_id: require_edit_token(' in router

def test_rebase_serializes_writes_and_checks_batch_version():
    service = (BASE / 'drafts' / 'service.py').read_text()
    method = service.split('def rebase_batch_product_version(', 1)[1]
    assert 'DraftBatch.id == batch_id).with_for_update()' in method
    assert 'authorization(current.product_master_id)' in method
    assert 'current.id != expected_product_version_id' in method
    assert 'latest != current.version_number' in method
    assert 'actor_user_id=actor_user_id' in method

def test_client_sends_fencing_token_and_expected_product_version():
    frontend = (BASE.parents[1] / 'frontend' / 'src' / 'main.tsx').read_text()
    section = frontend.split('async function saveCorrectionsAndRevalidate()', 1)[1].split('async function refreshUploadedImages', 1)[0]
    assert '"X-Product-Lease-Token": correctionToken' in section
    assert '"X-Expected-Product-Version": versionId' in section
