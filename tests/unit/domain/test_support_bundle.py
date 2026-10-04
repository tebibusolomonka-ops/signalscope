import hashlib
import io
import json
import zipfile

from signalscope.core.settings import Settings
from signalscope.domain.diagnostics.support_bundle import SupportBundleService

EXPECTED_FILES = {
    "manifest.json",
    "environment.json",
    "production_config.json",
    "migration.json",
    "readiness.json",
    "queues.json",
    "recent_errors.json",
    "version.txt",
}


def read_bundle(data: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(data))


def test_bundle_contains_expected_files() -> None:
    data = SupportBundleService(Settings()).build_without_database()

    with read_bundle(data) as archive:
        assert set(archive.namelist()) == EXPECTED_FILES


def test_manifest_checksums_match_file_contents() -> None:
    data = SupportBundleService(Settings()).build_without_database()

    with read_bundle(data) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format_version"] == "1"
        for entry in manifest["files"]:
            content = archive.read(entry["path"])
            assert len(content) == entry["size_bytes"]
            assert hashlib.sha256(content).hexdigest() == entry["sha256"]


def test_archive_paths_are_safe() -> None:
    data = SupportBundleService(Settings()).build_without_database()

    with read_bundle(data) as archive:
        for name in archive.namelist():
            assert not name.startswith("/")
            assert ".." not in name


def test_without_database_has_no_readiness_or_errors() -> None:
    data = SupportBundleService(Settings()).build_without_database()

    with read_bundle(data) as archive:
        assert json.loads(archive.read("readiness.json")) is None
        assert json.loads(archive.read("recent_errors.json")) == []
