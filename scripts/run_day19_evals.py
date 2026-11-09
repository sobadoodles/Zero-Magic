"""Day 19 groundedness eval harness for Zero Magic's /api/v1/boards/{id}/ask.

Adapted from the reference script to fit THIS app's actual contract:
  * Auth is a login cookie session (POST /api/v1/auth/login), not a bearer token.
  * The three metrics are scored from INDEPENDENT signals:
      - Retrieval    : does /knowledge/search return the ground-truth passage?
      - Groundedness : does /ask cite + support the claim from that passage?
      - Refusal      : does /ask return found=false on unanswerable questions?
  * Cause grouping (ingestion vs retrieval vs generation) distinguishes a clause
    that is absent from the whole library (ingestion) from one that exists but
    was not surfaced (retrieval) from one that was surfaced but not cited (generation).

Reads config from environment (or CLI flags). Writes a JSON report for eval_report.md.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 'app' package lives at repo root

import httpx


class ProviderExhausted(Exception):
    """Groq still 503 after the harness backoff — scored as an env failure, not a crash."""

REFUSAL_MARKERS = ["not contain", "not found", "no information", "cannot answer",
                   "do not mention", "does not mention", "not in the", "no relevant",
                   "unable to find", "not provided"]


def is_refusal_text(answer):
    low = (answer or "").lower()
    return any(m in low for m in REFUSAL_MARKERS)


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def clause_token(clause):
    """The searchable core of a clause tag: '[C15]' -> 'C15'."""
    return norm(clause).strip("[]").strip() if clause else None


class BoardEval:
    def __init__(self, base, board, user, pwd, mode, top):
        self.board, self.mode, self.top = board, mode, top
        self.c = httpx.Client(base_url=base, timeout=60.0)
        r = self.c.post("/api/v1/auth/login", json={"username": user, "password": pwd})
        r.raise_for_status()
        # Full set of stored passages on this board, for evidence-chunk location
        # and ingestion-vs-retrieval cause-grouping.
        docs = self.c.get(f"/api/v1/boards/{board}/documents").json()["documents"]
        self.chunks = []
        for doc in docs:
            detail = self.c.get(f"/api/v1/knowledge/{doc['source_name']}").json()
            self.chunks.extend({"id": ch["id"], "text": ch["text"]} for ch in detail["chunks"])
        self.library_text = norm(" ".join(ch["text"] for ch in self.chunks))

    def find_evidence(self, item):
        """The one stored chunk that literally contains the ground-truth answer.
        WORD-SET membership (same tokenizer as search) — substring checks would match
        'git' inside 'gitea' and pick the wrong evidence chunk."""
        from app.document_search import search_words

        kw_sets = [search_words(k) for k in item["expected_keywords"] if search_words(k)]
        if kw_sets:
            for chunk in self.chunks:
                words = search_words(chunk["text"])
                if all(kw <= words for kw in kw_sets):
                    return chunk
        clause = norm(item["expected_clause"]) if item["expected_clause"] else None
        if clause:
            for chunk in self.chunks:
                if clause in norm(chunk["text"]):
                    return chunk
        return None

    def ask(self, question):
        """POST /ask with rate-limit tolerance: our free-tier Groq keys share 8k TPM,
        and the app's 503 means 'provider unavailable', not 'wrong answer'."""
        for attempt, wait in enumerate((0, 12, 30, 60)):
            if wait:
                time.sleep(wait)
            r = self.c.post(f"/api/v1/boards/{self.board}/ask",
                            json={"question": question, "mode": self.mode, "limit": self.top})
            if r.status_code != 503:
                r.raise_for_status()
                return r.json()
        raise ProviderExhausted(r.json().get("detail", "503"))

    def retrieve_full(self, question):
        r = self.c.post("/api/v1/knowledge/search",
                        json={"query": question, "mode": self.mode, "limit": self.top,
                              "project_id": self.board})
        r.raise_for_status()
        return r.json()["results"]

    def retrieve(self, question):
        """The candidate pool /ask sees, via the same retrieve() the search uses."""
        return [hit["text"] for hit in self.retrieve_full(question)]

    def evaluate(self, item):
        try:
            return self._evaluate(item)
        except ProviderExhausted as error:
            kind = "refusal" if item["should_refuse"] else "answerable"
            return {"id": item["id"], "type": kind, "refusal_pass": False,
                    "retrieval_pass": False, "grounded_pass": False,
                    "cause": f"provider (503 after backoff: {str(error)[:60]})"}

    def _evaluate(self, item):
        if item["should_refuse"]:
            data = self.ask(item["question"])
            quotes = [c["quote"] for c in data.get("citations", []) if c.get("quote")]
            # The API's found flag is the authoritative signal on this app.
            declined = data.get("found") is False and not quotes
            return {"id": item["id"], "type": "refusal", "refusal_pass": bool(declined),
                    "found": data.get("found"), "answer": data.get("answer", ""),
                    "cause": None if declined else "refusal (answered instead of declining)"}

        retrieved = self.retrieve_full(item["question"])
        retrieved_ids = [hit["id"] for hit in retrieved]
        data = self.ask(item["question"])
        quotes = [c["quote"] for c in data.get("citations", []) if c.get("quote")]
        cited_blob = norm(" ".join(quotes))
        answer = data.get("answer", "")

        # The EVIDENCE chunk is the single stored passage that literally contains the
        # answer (all expected keywords, else the clause tag). Cause grouping keys off
        # WHERE it dropped out: library (ingestion) -> pool (retrieval) -> cited (generation).
        evidence = self.find_evidence(item)
        in_library = evidence is not None
        in_pool = bool(evidence) and evidence["id"] in retrieved_ids
        not_refused = data.get("found") is True
        has_cite = bool(data.get("citations"))
        support = bool(evidence) and any(
            norm(evidence["text"]) == norm(q) or norm(evidence["text"][:60]) in norm(q)
            for q in quotes)

        grounded = in_library and in_pool and not_refused and has_cite and support
        if not in_library:
            cause = "ingestion (answer content absent from stored passages)"
        elif not in_pool:
            cause = f"retrieval (evidence chunk ranked outside top-{self.top})"
        elif not grounded:
            cause = ("generation (answer chunk in pool but refused)" if not not_refused
                     else "generation (answer chunk not cited/supported)")
        else:
            cause = None

        return {"id": item["id"], "type": "answerable",
                "retrieval_pass": in_pool, "grounded_pass": grounded,
                "found": data.get("found"), "answer": answer,
                "cited_count": len(data.get("citations", [])),
                "evidence_id": evidence["id"] if evidence else None,
                "retrieved_ids": retrieved_ids, "cause": cause}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("ZERO_MAGIC_API_URL", "http://127.0.0.1:8123"))
    ap.add_argument("--board", default=os.environ.get("ZERO_MAGIC_BOARD_ID"))
    ap.add_argument("--user", default=os.environ.get("ZERO_MAGIC_USER"))
    ap.add_argument("--password", default=os.environ.get("ZERO_MAGIC_PASSWORD"))
    ap.add_argument("--questions", default=os.environ.get("EVAL_QUESTIONS_FILE",
                    os.path.join(os.path.dirname(__file__), "..", "eval", "day19", "eval_questions.json")))
    ap.add_argument("--mode", default=os.environ.get("ZERO_MAGIC_MODE", "keyword"), choices=["keyword", "semantic"])
    ap.add_argument("--top", type=int, default=int(os.environ.get("ZERO_MAGIC_TOP", "5")))
    ap.add_argument("--out", default=None, help="write JSON report here")
    a = ap.parse_args()
    if not (a.board and a.user and a.password):
        raise SystemExit("Set ZERO_MAGIC_BOARD_ID, ZERO_MAGIC_USER, ZERO_MAGIC_PASSWORD (or flags).")

    with open(a.questions, encoding="utf-8") as f:
        questions = json.load(f)

    ev = BoardEval(a.base, a.board, a.user, a.password, a.mode, a.top)
    results = []
    for q in questions:
        r = ev.evaluate(q)
        results.append(r)
        time.sleep(1.2)  # pacing: stay inside the free-tier tokens-per-minute window
        if r["type"] == "refusal":
            tag = f"REFUSE={'PASS' if r['refusal_pass'] else 'FAIL'}"
        else:
            tag = f"RET={'PASS' if r['retrieval_pass'] else 'FAIL'} GND={'PASS' if r['grounded_pass'] else 'FAIL'}"
        print(f"[{r['id']}] {tag}  {q['question'][:58]}")

    ans = [r for r in results if r["type"] == "answerable"]
    ref = [r for r in results if r["type"] == "refusal"]
    ret = sum(r["retrieval_pass"] for r in ans)
    gnd = sum(r["grounded_pass"] for r in ans)
    rfs = sum(r["refusal_pass"] for r in ref)
    print("\n" + "=" * 54)
    print(f"DAY 19 GROUNDEDNESS EVAL  (mode={a.mode}, top-k={a.top})")
    print(f"Retrieval    : {ret}/{len(ans)} ({ret/len(ans)*100:.0f}%)")
    print(f"Groundedness : {gnd}/{len(ans)} ({gnd/len(ans)*100:.0f}%)")
    print(f"Refusal      : {rfs}/{len(ref)} ({rfs/len(ref)*100:.0f}%)")
    print("=" * 54)

    buckets = {}
    for r in results:
        if r.get("cause"):
            key = r["cause"].split(" (")[0]
            buckets.setdefault(key, []).append(r["id"])
    if buckets:
        print("Failures by cause:")
        for k, ids in sorted(buckets.items()):
            print(f"  {k:12s}: {', '.join(ids)}")

    report = {"mode": a.mode, "top": a.top,
              "scores": {"retrieval": [ret, len(ans)], "groundedness": [gnd, len(ans)], "refusal": [rfs, len(ref)]},
              "failures_by_cause": buckets, "results": results}
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"report -> {a.out}")


if __name__ == "__main__":
    main()
