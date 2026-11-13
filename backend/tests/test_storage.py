"""Private file storage (spec v1.2, T06 and Section 8): upload/get/delete and tenant safety."""
import os

import pytest

from app.core.config import settings
from app.services.storage import (
    InvalidObjectKey,
    LocalDiskStorage,
    ObjectNotFound,
    ensure_tenant_key,
    get_storage,
    safe_file_name,
    tenant_document_key,
)


@pytest.fixture()
def storage(tmp_path):
    return LocalDiskStorage(tmp_path / "objects")


def test_upload_get_delete_round_trip(storage):
    key = tenant_document_key(1, "doc-1", "fees.pdf")
    stored = storage.put(key, b"%PDF-1.7 school fees")
    assert stored.key == "tenant/1/documents/doc-1/fees.pdf"
    assert stored.size == 20
    assert len(stored.sha256) == 64
    assert storage.exists(key)
    assert storage.get(key) == b"%PDF-1.7 school fees"
    assert storage.delete(key) is True
    assert not storage.exists(key)
    assert storage.delete(key) is False
    with pytest.raises(ObjectNotFound):
        storage.get(key)


def test_overwrite_replaces_the_whole_file_and_leaves_no_temp_files(storage):
    key = "tenant/1/documents/doc-1/a.txt"
    storage.put(key, b"first version, longer")
    storage.put(key, b"second")
    assert storage.get(key) == b"second"
    assert [p.name for p in (storage.root / "tenant/1/documents/doc-1").iterdir()] == ["a.txt"]


def test_files_are_private_to_the_app_user(storage):
    key = "tenant/1/documents/doc-1/a.txt"
    storage.put(key, b"x")
    if os.name == "posix":
        assert oct((storage.root / key).stat().st_mode & 0o777) == oct(0o600)


def test_delete_removes_empty_folders_but_not_the_root(storage):
    storage.put("tenant/1/documents/doc-1/a.txt", b"x")
    storage.delete("tenant/1/documents/doc-1/a.txt")
    assert storage.root.exists()
    assert list(storage.root.iterdir()) == []


@pytest.mark.parametrize(
    "key",
    ["", "/etc/passwd", "../outside.txt", "tenant/1/../../outside.txt", "tenant/1/./a", "tenant\\1\\a", "tenant//a", "tenant/1/", "a/b c", "x" * 600],
)
def test_unsafe_keys_are_refused(storage, key):
    with pytest.raises(InvalidObjectKey):
        storage.put(key, b"x")


@pytest.mark.skipif(os.name != "posix", reason="symlinks need a POSIX filesystem")
def test_symlink_cannot_lead_outside_storage(storage, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (storage.root / "tenant").mkdir(parents=True)
    (storage.root / "tenant" / "1").symlink_to(outside)
    with pytest.raises(InvalidObjectKey):
        storage.put("tenant/1/documents/doc/a.txt", b"x")
    assert list(outside.iterdir()) == []


def test_tenant_cannot_use_another_tenants_key():
    assert ensure_tenant_key(1, "tenant/1/documents/d/a.pdf")
    for key in ["tenant/2/documents/d/a.pdf", "tenant/12/documents/d/a.pdf", "documents/d/a.pdf"]:
        with pytest.raises(InvalidObjectKey):
            ensure_tenant_key(1, key)


@pytest.mark.parametrize("tenant_id", [0, -1, True, "1"])
def test_invalid_tenant_ids_are_refused(tenant_id):
    with pytest.raises(InvalidObjectKey):
        tenant_document_key(tenant_id, "doc", "a.pdf")


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Fees 2026.pdf", "Fees_2026.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\report.DOCX", "report.docx"),
        ("الرسوم الدراسية.pdf", "file.pdf"),
        (".hidden", "file.hidden"),
        ("", "file"),
        ("a" * 300 + ".md", "a" * 117 + ".md"),
    ],
)
def test_safe_file_name(name, expected):
    assert safe_file_name(name) == expected


def test_factory_returns_local_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_local_root", str(tmp_path / "volume"))
    storage = get_storage()
    assert isinstance(storage, LocalDiskStorage)
    assert storage.root == (tmp_path / "volume").resolve()


def test_factory_refuses_unknown_backend(monkeypatch):
    monkeypatch.setattr(settings, "storage_backend", "s3")
    with pytest.raises(RuntimeError):
        get_storage()
