<!-- docs-architect-meta {"schema_version":1,"id":"DOC-EXPORT","type":"system-doc","status":"active","title":"Export API","owners":[],"sources":["src/export.py"],"update_when":["Export quoting or record-boundary behavior changes"],"relations":[{"type":"documents","target":"REQ-2026-011"}],"acceptance":[],"evidence":[],"affected_docs":[],"verified_at":null,"verified_against":null} -->

# Export API

`export_rows` emits one CSV record per input row and quotes fields containing commas, quotes, or newlines.
