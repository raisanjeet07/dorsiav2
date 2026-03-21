# Research workflow — expected outcomes

After a successful run (`current_state == COMPLETED`), you should have **two** markdown artifacts on disk (same workspace the research service uses):

| Stage | File | When |
|--------|------|------|
| **Research** | `workspace/{wf-id}/reports/draft-v1.md` | After `RESEARCHING` |
| **Final** | `workspace/{wf-id}/reports/final.md` | After `GENERATING_FINAL` (user approved) |

## HTTP API

| Endpoint | What you get |
|----------|----------------|
| `GET /api/v1/workflows/{id}/report` | **Best** report: `final` if `final.md` exists, else latest `draft-vN`. Response includes `is_final: true/false`. |
| `GET /api/v1/workflows/{id}/report/final` | **Final only** — returns `404` until `final.md` exists. Response includes full `content` and `length_chars`. |
| `GET /api/v1/workflows/{id}/state` | `current_state`, transition history, `forced_consensus`, etc. |

If you only ever called `/report` before completion, you still see **draft** content. After completion, `/report` returns the **final** polished report when `final.md` is present.

## Quick validate

```bash
# From repo root, with research service on :8000
python3 research-work-flow-ai/scripts/validate_research_outcome.py
```
