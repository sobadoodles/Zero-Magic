"""CLI question answerer over the knowledge library, with citations and failure collection.

Answers ONLY from retrieved passages, cites [K#] ids per claim, says plainly when the
documents do not contain the answer, retrieves through BOTH keyword and semantic modes
for comparison, and writes results + failures.md artifacts.

Reads the SQLite knowledge library (run with the server stopped, or use --db on a copy).
Model answers need your configured .env Groq key; without it, answering is SKIPPED while
retrieval comparison still runs (--no-answering forces the same offline behavior).
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.document_chunks import normalize_for_search
from app.document_qa import GroundedAnswer, build_messages, label_passages  # re-exported for tests
from app.document_search import search_words


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,60}$")
    question: str = Field(min_length=4, max_length=800)
    expected_found: bool
    gold: dict | None = None  # {source, page?, must_contain}


class QuestionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(default="", max_length=500)
    questions: list[Question] = Field(min_length=1, max_length=40)


def load_questions(path: Path) -> QuestionSet:
    try:
        return QuestionSet.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as error:
        raise SystemExit(f"The questions file is not valid: {error}")


def flatten(text):
    return re.sub(r"\s+", " ", normalize_for_search(text)).casefold()


def resolve_gold(gold, chunks):
    """Map a question's gold description onto a real chunk id in the library."""
    if not gold:
        return None
    wanted = flatten(gold.get("must_contain", ""))
    if not wanted:
        return None
    for chunk in chunks:
        if chunk["source"] != gold.get("source"):
            continue
        if "page" in gold and chunk.get("page") != gold["page"]:
            continue
        if wanted in flatten(chunk["text"]):
            return chunk["id"]
    return None


def rank_of(chunk_id, retrieved):
    for position, chunk in enumerate(retrieved, 1):
        if chunk["id"] == chunk_id:
            return position
    return None


def snippet_supported(snippet, combined_text):
    """Mechanical citation-support proxy: most significant snippet words must appear."""
    needed = {word for word in search_words(snippet) if len(word) > 3}
    if not needed:
        return True
    present = search_words(combined_text)
    return len(needed & present) / len(needed) >= 0.6


def make_groq_answerer():
    from app.llm import ask_structured, ModelUnavailableError, StructuredOutputError

    def answer(question_text, passages):
        try:
            result = ask_structured(build_messages(question_text, passages), GroundedAnswer)
        except (ModelUnavailableError, StructuredOutputError) as error:
            return {"skipped": str(error)}
        return {"parsed": result["parsed"], "model": result["model"]}
    return answer


def make_retriever(top):
    from app import knowledge

    def retrieve(question_text, mode):
        try:
            return {"chunks": knowledge.retrieve(question_text, limit=top, mode=mode)}
        except Exception as error:  # missing vectors, missing/blocked fastembed, bad query
            detail = getattr(error, "detail", None) or str(error)
            return {"unavailable": str(detail)}
    return retrieve


def evaluate(question, mode, retrieved, gold_id, answer_result):
    """Return (mode_result, failures) for one question in one mode."""
    failures = []
    result = {"mode": mode}
    if "unavailable" in retrieved:
        result["status"] = "skipped"
        result["reason"] = retrieved["unavailable"]
        return result, failures

    passages = label_passages(retrieved["chunks"])
    result["retrieved"] = [{"id": p["id"], "chunk_id": p["chunk_id"], "source": p["source"],
                            "page": p["page"], "preview": p["text"][:120]} for p in passages]
    gold_rank = rank_of(gold_id, retrieved["chunks"]) if gold_id else None
    result["gold_rank"] = gold_rank
    if question.gold and gold_id is None:
        failures.append(f"{mode}: the gold passage does not exist in the library "
                        f"(expected {question.gold.get('source')} containing "
                        f"{question.gold.get('must_contain')!r})")
    elif question.gold and gold_id is not None and gold_rank is None:
        failures.append(f"{mode}: retrieval miss — the gold passage was not in the top {len(passages)}")

    if "skipped" in answer_result:
        result["answer"] = {"skipped": answer_result["skipped"]}
        return result, failures

    parsed = answer_result["parsed"]
    by_label = {p["id"]: p for p in passages}
    result["answer"] = {"found": parsed.found, "answer": parsed.answer,
                        "citations": parsed.citations, "model": answer_result["model"]}

    unknown = [citation for citation in parsed.citations if citation not in by_label]
    if unknown:
        failures.append(f"{mode}: hallucinated citation ids {unknown} — those passages were never provided")
    if parsed.found and not parsed.citations:
        failures.append(f"{mode}: answered without any citation")

    cited_text = " ".join(by_label[citation]["text"] for citation in parsed.citations if citation in by_label)
    if parsed.found:
        if question.expected_found and question.gold and gold_id is not None and gold_rank is not None:
            if gold_id not in [by_label[citation]["chunk_id"] for citation in parsed.citations if citation in by_label]:
                if not snippet_supported(question.gold["must_contain"], parsed.answer + " " + cited_text):
                    failures.append(f"{mode}: retrieved but ignored — the gold passage was in context yet "
                                    "neither cited nor reflected in the answer")
        if not snippet_supported((question.gold or {}).get("must_contain", parsed.answer), parsed.answer + " " + cited_text):
            failures.append(f"{mode}: unsupported citation — the cited passages do not contain the claim's key words")
        if not question.expected_found:
            failures.append(f"{mode}: hallucination — the question expects 'not found' but an answer with "
                            "citations was produced")
    else:
        if question.expected_found and gold_rank is not None:
            failures.append(f"{mode}: retrieved but ignored — the gold passage was in context but the model "
                            "said the documents do not contain the answer")
        if question.expected_found and gold_rank is None and gold_id is not None:
            failures.append(f"{mode}: answer missed, but this follows the retrieval miss above")
    return result, failures


def compare(keyword_result, semantic_result):
    notes = {"overlap": None, "verdict": "single-mode"}
    if "retrieved" not in keyword_result or "retrieved" not in semantic_result:
        notes["verdict"] = "one mode unavailable: " + ", ".join(
            m for m, r in (("keyword", keyword_result), ("semantic", semantic_result)) if "retrieved" not in r)
        return notes
    k_ids = {item["chunk_id"] for item in keyword_result["retrieved"]}
    s_ids = {item["chunk_id"] for item in semantic_result["retrieved"]}
    union = k_ids | s_ids
    notes["overlap"] = round(len(k_ids & s_ids) / len(union), 2) if union else 0
    k_rank, s_rank = keyword_result.get("gold_rank"), semantic_result.get("gold_rank")
    if k_rank and s_rank:
        notes["verdict"] = "keyword-first" if k_rank <= s_rank else "semantic-first"
    elif k_rank:
        notes["verdict"] = "keyword-only-gold"
    elif s_rank:
        notes["verdict"] = "semantic-only-gold — the multilingual embeddings found what keywords missed"
    else:
        notes["verdict"] = "both missed"
    return notes


def run_qa(question_set, retrieve, answer, top=5):
    """Pure orchestrator; retrieve(question, mode) and answer(question, passages) are injected."""
    from app import storage
    all_chunks = [storage.doc_chunks[key] for key in sorted(storage.doc_chunks)]
    report = []
    for question in question_set.questions:
        gold_id = resolve_gold(question.gold, all_chunks)
        entry = {"id": question.id, "question": question.question,
                 "expected_found": question.expected_found,
                 "gold_chunk_id": gold_id, "modes": {}, "failures": []}
        answer_cache = {}
        for mode in ("keyword", "semantic"):
            retrieved = retrieve(question.question, mode)
            passages = label_passages(retrieved["chunks"]) if "chunks" in retrieved else []
            if passages:
                key = tuple(p["chunk_id"] for p in passages)
                if key not in answer_cache:
                    answer_cache[key] = answer(question.question, passages)
                answer_result = answer_cache[key] if passages else {"skipped": "nothing retrieved"}
            else:
                answer_result = {"skipped": "no passages retrieved"}
            mode_result, failures = evaluate(question, mode, retrieved, gold_id, answer_result)
            entry["modes"][mode] = mode_result
            entry["failures"].extend(failures)
        entry["comparison"] = compare(entry["modes"]["keyword"], entry["modes"]["semantic"])
        if question.gold is None and entry["comparison"].get("verdict") == "both missed":
            entry["comparison"]["verdict"] = "no-gold probe (expected-miss question)"
        report.append(entry)
    return report


def render_failures_md(report, source_note):
    lines = ["# Observed failures — document QA run", "",
             source_note, ""]
    buckets = {}
    for entry in report:
        for failure in entry["failures"]:
            bucket = failure.split(": ", 1)[0]
            buckets.setdefault(bucket, []).append(f"- **{entry['id']}** — {failure.split(': ', 1)[1]}")
    if not buckets:
        lines.append("No failures recorded: every gold passage was retrieved, cited, and supported.\n")
    for bucket in sorted(buckets):
        lines.append(f"## {bucket}")
        lines.extend(buckets[bucket])
        lines.append("")
    lines.append("## Mode comparison per question")
    for entry in report:
        k, s = entry["modes"]["keyword"], entry["modes"]["semantic"]
        lines.append(f"- {entry['id']}: keyword gold-rank {k.get('gold_rank', '-')}, "
                     f"semantic gold-rank {s.get('gold_rank', '-')}, overlap "
                     f"{entry['comparison'].get('overlap', '-')}, verdict "
                     f"{entry['comparison'].get('verdict', '-')}")
    return "\n".join(lines) + "\n"


def print_table(report):
    print(f"{'question':22s} {'gold':4s} {'K/S ranks':10s} {'K/S found':10s} {'fails':5s} verdict")
    for entry in report:
        k, s = entry["modes"]["keyword"], entry["modes"]["semantic"]
        ranks = f"{k.get('gold_rank', '-')}/{s.get('gold_rank', '-')}"
        found = f"{k.get('answer', {}).get('found', '?')}/{s.get('answer', {}).get('found', '?')}"
        print(f"{entry['id']:22s} {'yes' if entry['gold_chunk_id'] else '-':4s} {ranks:10s} "
              f"{found:10s} {len(entry['failures']):<5d} {entry['comparison'].get('verdict', '-')}")


def main():
    if hasattr(sys.stdout, "reconfigure"):  # keep Persian verdicts readable in any console
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("questions_file", type=Path)
    parser.add_argument("--db", help="SQLite path (defaults to the app .env/database; stop the server first)")
    parser.add_argument("--top", type=int, default=5, help="passages per question per mode (1-10)")
    parser.add_argument("--out", type=Path, default=Path("eval/results"))
    parser.add_argument("--no-answering", action="store_true",
                        help="retrieval + comparison only; never call the model")
    parser.add_argument("--strict", action="store_true", help="exit 1 when any failure is recorded")
    args = parser.parse_args()

    if args.db:
        import os
        os.environ["ZERO_MAGIC_DB"] = str(args.db)

    question_set = load_questions(args.questions_file)
    from app import storage  # after any --db override
    from app import knowledge  # noqa: F401  (populates doc dicts via storage)

    if not storage.doc_chunks:
        raise SystemExit("The knowledge library is empty. Import passages first: "
                         "python -m scripts.import_chunks data/week4-review-chunks-v4.json "
                         "--index data/week4-vector-index.json")

    top = max(1, min(args.top, 10))
    retrieve = make_retriever(top)
    if args.no_answering:
        def disabled_answer(question_text, passages):
            return {"skipped": "answering disabled (--no-answering)"}
        answer = disabled_answer
    else:
        answer = make_groq_answerer()

    report = run_qa(question_set, retrieve, answer, top)
    print_table(report)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = args.out / f"qa-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    failures_md = render_failures_md(report, question_set.note or f"questions: {args.questions_file}")
    (run_dir / "failures.md").write_text(failures_md, encoding="utf-8")

    total_failures = sum(len(entry["failures"]) for entry in report)
    print(f"\nWrote {run_dir / 'results.json'} and {run_dir / 'failures.md'} "
          f"({total_failures} failure(s) across {len(report)} questions).")
    if args.strict and total_failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
