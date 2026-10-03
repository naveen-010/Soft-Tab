"""Build an unsigned Firefox add-on without bundling tests or dependencies."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
destination = root / "dist" / "soft-tab-1.0.0.xpi"
destination.parent.mkdir(exist_ok=True)
with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
    for source in sorted((root / "extension").iterdir()):
        archive.write(source, source.name)
print(destination)
