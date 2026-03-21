#!/usr/bin/env python3
"""Create a minimal workflow, wait for COMPLETED, validate draft + final reports via API."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import httpx

BASE = os.environ.get("RESEARCH_URL", "http://localhost:8000").rstrip("/")
POLL_S = 3
MAX_WAIT_S = 900  # 15 min — adjust if agents are slow


async def main() -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=120.0) as client:
        r = await client.get("/api/v1/health")
        r.raise_for_status()
        h = r.json()
        print("Health:", json.dumps(h, indent=2))
        if not h.get("gateway_connected"):
            print("ERROR: gateway not connected — start gateway on :8080 first.", file=sys.stderr)
            return 2

        body = {
            "topic": "Three bullet benefits of unit tests (one sentence each)",
            "context": "Test run only. Be extremely brief.",
            "depth": "shallow",
            "max_review_cycles": 1,
        }
        r = await client.post("/api/v1/workflows", json=body)
        if r.status_code != 200:
            print("Create failed:", r.status_code, r.text)
            return 1
        wf_id = r.json()["workflow_id"]
        print(f"\nCreated {wf_id}, polling until COMPLETED (max {MAX_WAIT_S}s)...\n")

        start = time.time()
        last_state = None
        while time.time() - start < MAX_WAIT_S:
            st = await client.get(f"/api/v1/workflows/{wf_id}/state")
            if st.status_code != 200:
                print("state:", st.status_code, st.text)
                await asyncio.sleep(POLL_S)
                continue
            data = st.json()
            cur = data["current_state"]
            if cur != last_state:
                print(f"  [{int(time.time() - start):4d}s] {cur}")
                last_state = cur
            if cur == "COMPLETED":
                break
            if cur == "USER_REVIEW":
                await client.post(
                    f"/api/v1/workflows/{wf_id}/approve",
                    json={"comment": "validate_research_outcome.py auto-approve"},
                )
            if cur in ("FAILED", "CANCELLED"):
                print("Terminal failure state:", cur)
                return 1
            await asyncio.sleep(POLL_S)
        else:
            print("TIMEOUT")
            return 1

        # --- Validate reports ---
        rep = await client.get(f"/api/v1/workflows/{wf_id}/report")
        print("\nGET /report:", rep.status_code)
        if rep.status_code != 200:
            print(rep.text)
            return 1
        jr = rep.json()
        print("  version:", jr.get("version"), " is_final:", jr.get("is_final"))
        content = jr.get("content") or ""
        print("  content length:", len(content))
        if len(content) < 50:
            print("ERROR: /report content too short")
            return 1
        print("  preview:\n", content[:400], "\n  ...")

        fin = await client.get(f"/api/v1/workflows/{wf_id}/report/final")
        print("\nGET /report/final:", fin.status_code)
        if fin.status_code != 200:
            print(fin.text)
            return 1
        jf = fin.json()
        fc = jf.get("content") or ""
        print("  length_chars:", jf.get("length_chars"), " file_path:", jf.get("file_path"))
        if len(fc) < 50:
            print("ERROR: final content too short")
            return 1
        print("  preview:\n", fc[:400], "\n  ...")

        print("\n=== PASS — research outcome visible via API ===")
        print(f"  Workflow: {wf_id}")
        print(f"  Draft + final markdown exist; /report returns best; /report/final includes body.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
