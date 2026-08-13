<!-- docs-architect-meta
{"schema_version":1,"id":"DOC-API","type":"system-doc","title":"HTTP API","status":"active","sources":["src/api.py"],"update_when":["Health response changes"],"relations":[{"type":"documents","target":"REQ-2026-008"}]}
-->

# HTTP API

`GET /health` returns `{"status": "ok", "version": "<deployed version>"}`.
