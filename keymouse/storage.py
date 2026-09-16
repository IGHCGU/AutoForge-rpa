from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .models import Workflow


@dataclass
class WorkflowDocument:
    workflow: Workflow
    asset_dir: Path
    path: Path | None = None
    dirty: bool = False

    @classmethod
    def create(cls, name: str = "未命名流程") -> "WorkflowDocument":
        return cls(Workflow(name=name), Path(tempfile.mkdtemp(prefix="keymouse_assets_")))

    def resolve_asset(self, relative_path: str) -> Path:
        clean = relative_path.replace("\\", "/").removeprefix("assets/")
        candidate = (self.asset_dir / clean).resolve()
        if self.asset_dir.resolve() not in candidate.parents and candidate != self.asset_dir.resolve():
            raise ValueError("非法素材路径")
        return candidate

    def add_asset(self, source: str | Path) -> str:
        source_path = Path(source)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        stem = source_path.stem
        suffix = source_path.suffix.lower() or ".png"
        destination = self.asset_dir / f"{stem}{suffix}"
        index = 2
        while destination.exists() and destination.read_bytes() != source_path.read_bytes():
            destination = self.asset_dir / f"{stem}_{index}{suffix}"
            index += 1
        if not destination.exists():
            shutil.copy2(source_path, destination)
        self.dirty = True
        return f"assets/{destination.name}"

    def close(self) -> None:
        shutil.rmtree(self.asset_dir, ignore_errors=True)


def save_document(document: WorkflowDocument, path: str | Path) -> Path:
    destination = Path(path)
    if destination.suffix.lower() != ".kmflow":
        destination = destination.with_suffix(".kmflow")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".tmp")
    payload = json.dumps(document.workflow.to_dict(), ensure_ascii=False, indent=2)
    with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("workflow.json", payload)
        if document.asset_dir.exists():
            for asset in sorted(document.asset_dir.iterdir()):
                if asset.is_file():
                    archive.write(asset, f"assets/{asset.name}")
    temp_path.replace(destination)
    document.path = destination
    document.dirty = False
    return destination


def load_document(path: str | Path) -> WorkflowDocument:
    source = Path(path)
    asset_dir = Path(tempfile.mkdtemp(prefix="keymouse_assets_"))
    try:
        with zipfile.ZipFile(source, "r") as archive:
            names = archive.namelist()
            if "workflow.json" not in names:
                raise ValueError("流程包缺少 workflow.json")
            data = json.loads(archive.read("workflow.json").decode("utf-8"))
            for name in names:
                normalized = name.replace("\\", "/")
                if not normalized.startswith("assets/") or normalized.endswith("/"):
                    continue
                relative = Path(normalized).relative_to("assets")
                if ".." in relative.parts or len(relative.parts) != 1:
                    raise ValueError("流程包包含非法素材路径")
                target = asset_dir / relative.name
                target.write_bytes(archive.read(name))
        return WorkflowDocument(Workflow.from_dict(data), asset_dir, source, False)
    except Exception:
        shutil.rmtree(asset_dir, ignore_errors=True)
        raise

