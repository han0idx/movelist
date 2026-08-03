#!/usr/bin/env python3
"""
Rebuild the root-level zip files from the folders in src/ and keep manifest.json
in sync.

Rules:
  - Each sub-folder of src/ (except the assets folder and non-folders) becomes
    <folder>.zip at the repo root. The zip contains the *contents* of the folder
    (relative paths), not the folder itself.
  - The assets folder (src/assets) becomes assets.zip and is tracked under the
    top-level "assets" key of the manifest (no "parent" field).
  - Game folders are tracked under manifest["packages"][<name>] with fields
    file, hash and parent. New games default to parent = false. Existing entries
    keep every field they already have (parent, roms, ...); only file and hash
    are refreshed.
  - A game folder that no longer exists has its zip deleted and its manifest
    entry removed.
  - hash is the SHA-256 of the generated zip file.

Zips are produced deterministically (sorted entries, fixed metadata, fixed
compression) so the hash only changes when the actual content changes.
"""

import hashlib
import json
import os
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
MANIFEST_PATH = REPO_ROOT / "manifest.json"

# Name of the folder inside src/ that maps to the top-level "assets" manifest key.
ASSETS_FOLDER = "assets"
ASSETS_ZIP = "assets.zip"

# Files inside src/ that are not game folders and must be ignored.
IGNORED_ROOT_NAMES = {"README.MD", "README.md", "readme.md", ".gitkeep"}

# Fixed timestamp for every zip entry (1980-01-01 00:00:00), the earliest value
# a zip supports. Guarantees reproducible archives.
FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def iter_files(folder: Path):
    """Yield every file inside *folder* as (absolute_path, arcname) sorted by
    arcname. arcname uses forward slashes and is relative to *folder*."""
    entries = []
    for path in folder.rglob("*"):
        if path.is_file():
            arcname = path.relative_to(folder).as_posix()
            entries.append((path, arcname))
    entries.sort(key=lambda item: item[1])
    return entries


def build_zip(folder: Path, zip_path: Path) -> None:
    """Create *zip_path* from the contents of *folder* deterministically."""
    tmp_path = zip_path.with_suffix(zip_path.suffix + ".tmp")
    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for file_path, arcname in iter_files(folder):
            info = zipfile.ZipInfo(arcname, date_time=FIXED_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(file_path, "rb") as fh:
                zf.writestr(info, fh.read())
    os.replace(tmp_path, zip_path)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("assets", {})
    data.setdefault("packages", {})
    if not isinstance(data["packages"], dict):
        data["packages"] = {}
    return data


def save_manifest(data: dict) -> None:
    with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def game_folders():
    """Return {name: Path} for every game folder in src/ (excludes assets)."""
    folders = {}
    if not SRC_DIR.is_dir():
        return folders
    for child in sorted(SRC_DIR.iterdir()):
        if not child.is_dir():
            continue
        if child.name == ASSETS_FOLDER:
            continue
        folders[child.name] = child
    return folders


def main() -> None:
    manifest = load_manifest()
    packages = manifest["packages"]

    # --- assets folder -> assets.zip ---
    assets_dir = SRC_DIR / ASSETS_FOLDER
    assets_zip_path = REPO_ROOT / ASSETS_ZIP
    if assets_dir.is_dir():
        build_zip(assets_dir, assets_zip_path)
        entry = manifest.get("assets")
        if not isinstance(entry, dict):
            entry = {}
        entry["file"] = ASSETS_ZIP
        entry["hash"] = sha256_of(assets_zip_path)
        manifest["assets"] = entry
    else:
        # assets folder removed -> drop zip and clear entry
        if assets_zip_path.exists():
            assets_zip_path.unlink()
        manifest["assets"] = {}

    # --- game folders -> <name>.zip ---
    folders = game_folders()
    for name, folder in folders.items():
        zip_name = name + ".zip"
        zip_path = REPO_ROOT / zip_name
        build_zip(folder, zip_path)
        digest = sha256_of(zip_path)
        existing = packages.get(name)
        if isinstance(existing, dict):
            # Preserve every user-managed field (parent, roms, ...).
            existing["file"] = zip_name
            existing["hash"] = digest
            packages[name] = existing
        else:
            packages[name] = {
                "file": zip_name,
                "hash": digest,
                "parent": False,
            }

    # --- remove zips + manifest entries for folders that disappeared ---
    existing_names = set(folders.keys())
    for name in list(packages.keys()):
        if name not in existing_names:
            packages.pop(name, None)
            stale_zip = REPO_ROOT / (name + ".zip")
            if stale_zip.exists():
                stale_zip.unlink()

    save_manifest(manifest)
    print("Manifest and zips rebuilt successfully.")


if __name__ == "__main__":
    main()
