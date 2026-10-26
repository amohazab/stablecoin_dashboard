"""`uv run python tools/measure_entry.py <draft>` (delivery rule 3; committed at P-10.13).

Measure a PROGRESS.md entry draft: total lines, Content block lines (between
'- **Content:**' and '- **Artifacts:**', exclusive), widest line, sha256."""
import hashlib
import pathlib
import sys

p = pathlib.Path(sys.argv[1])
raw = p.read_bytes()
lines = raw.decode("utf-8").splitlines()
start = next(i for i, ln in enumerate(lines) if ln.startswith("- **Content:**"))
end = next(i for i, ln in enumerate(lines) if ln.startswith("- **Artifacts:**"))
content = end - start - 1
print(f"file: {p.name}")
print(f"total lines: {len(lines)}")
print(f"Content lines: {content}{'  FLAG > 60' if content > 60 else ''}")
print(f"widest line: {max(len(ln) for ln in lines)} chars")
print(f"sha256: {hashlib.sha256(raw).hexdigest()}")
