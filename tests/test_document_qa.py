"""Deterministic tests for the document QA answerer. Retrieval and answering are faked;
no Groq calls, no fastembed load, no live library needed."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import storage
from scripts.answer_questions import (GroundedAnswer, Question, QuestionSet, compare,
                                      evaluate, resolve_gold, run_qa, render_failures_md,
                                      snippet_supported, rank_of, load_questions)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def clear_library():
    with storage.lock, storage.connection() as db:
        db.execute('DELETE FROM doc_chunks')
        db.execute('DELETE FROM doc_files')
        db.execute('DELETE FROM doc_vectors')
    storage.doc_chunks.clear()
    storage.doc_files.clear()


def chunk(source, ordinal, page, text):
    return {"id": f"{source}::{ordinal:05d}", "source": source, "page": page,
            "heading": None, "text": text}


GOLD_CHUNK = chunk("Team-Task-Reminders.pdf", 9, 2,
                   "Permission rule: Only the workspace owner may change the default reminder time.")
OTHER_CHUNK = chunk("Team-Task-Reminders.pdf", 8, 2,
                    "Reminder rule: Send an in-app reminder one day before the due date, at 9:00.")
DISTRACT_CHUNK = chunk("Other.pdf", 1, 1, "The team meets every Tuesday to review snacks.")


def question(**over):
    data = {"id": "q_who", "question": "Who may change the default time?",
            "expected_found": True,
            "gold": {"source": "Team-Task-Reminders.pdf", "page": 2,
                     "must_contain": "workspace owner may change the default reminder time"}}
    data.update(over)
    return Question.model_validate(data)


def retrieved(*chunks):
    return {"chunks": list(chunks)}


def answered(found=True, answer="The workspace owner may change it [K1].", citations=("K1",), model="fake"):
    return {"parsed": GroundedAnswer(found=found, answer=answer, citations=list(citations)),
            "model": model}


# --- the strict-answer contract --------------------------------------------------

def test_found_answer_must_cite():
    with pytest.raises(ValidationError):
        GroundedAnswer(found=True, answer="Owner can change it.", citations=[])


def test_not_found_must_not_cite_and_must_state_plainly():
    with pytest.raises(ValidationError):
        GroundedAnswer(found=False, answer="Nope.", citations=["K1"])
    with pytest.raises(ValidationError):
        GroundedAnswer(found=False, answer="Maybe not present.")
    ok = GroundedAnswer(found=False, answer="The documents do not contain the answer.", citations=[])
    assert ok.found is False


# --- gold resolution and support checks ------------------------------------------

def test_resolve_gold_and_rank():
    gold_id = resolve_gold(question().gold, [OTHER_CHUNK, GOLD_CHUNK])
    assert gold_id == GOLD_CHUNK["id"]
    assert rank_of(gold_id, [OTHER_CHUNK, GOLD_CHUNK]) == 2
    assert rank_of(gold_id, [OTHER_CHUNK]) is None
    assert resolve_gold({"source": "Nope.pdf", "must_contain": "text"}, [GOLD_CHUNK]) is None


def test_resolve_gold_links_persian_forms():
    persian = chunk("brief.docx", 1, None, "شماره کتاب ۱۲۳")
    assert resolve_gold({"source": "brief.docx", "must_contain": "كتاب ١٢٣"}, [persian]) == persian["id"]


def test_snippet_supported():
    assert snippet_supported("workspace owner may change the default reminder time",
                             "only the OWNER can change the default reminder time per docs")
    assert not snippet_supported("workspace owner may change the default reminder time",
                                 "the answer is tuesday snacks")
    assert snippet_supported("", "anything")  # nothing to verify


# --- failure classification --------------------------------------------------------

def test_retrieval_miss_recorded():
    result, failures = evaluate(question(), "keyword", retrieved(OTHER_CHUNK, DISTRACT_CHUNK),
                                GOLD_CHUNK["id"], answered())
    assert any("retrieval miss" in f for f in failures)
    assert result["gold_rank"] is None


def test_gold_must_exist_in_library():
    result, failures = evaluate(question(), "keyword", retrieved(OTHER_CHUNK), None, answered())
    assert any("does not exist in the library" in f for f in failures)


def test_hallucinated_and_missing_citations():
    _, failures = evaluate(question(), "keyword", retrieved(GOLD_CHUNK),
                           GOLD_CHUNK["id"], answered(citations=["K7"]))
    assert any("hallucinated citation" in f for f in failures)
    _, failures = evaluate(question(), "keyword", retrieved(GOLD_CHUNK),
                           GOLD_CHUNK["id"],
                           {"parsed": GroundedAnswer.model_validate(
                               {"found": True, "answer": "Owner changes it.", "citations": ["K1"]}),
                            "model": "fake"})
    assert not failures  # answer text itself carries the claim words


def test_retrieved_but_ignored_when_model_denies_answer():
    result, failures = evaluate(question(), "semantic", retrieved(GOLD_CHUNK), GOLD_CHUNK["id"],
                                answered(found=False,
                                         answer="The documents do not contain the answer.",
                                         citations=()))
    assert result["answer"]["found"] is False
    assert any("retrieved but ignored" in f for f in failures)


def test_retrieved_but_ignored_when_gold_uncited_and_unmatched():
    result, failures = evaluate(question(), "keyword", retrieved(GOLD_CHUNK, OTHER_CHUNK),
                                GOLD_CHUNK["id"],
                                answered(answer="Reminders arrive early [K2].", citations=("K2",)))
    assert any("retrieved but ignored" in f or "unsupported citation" in f for f in failures)


def test_unsupported_citation_bucket():
    _, failures = evaluate(question(), "keyword", retrieved(DISTRACT_CHUNK, OTHER_CHUNK),
                           GOLD_CHUNK["id"], answered(answer="Snacks are decided on tuesday [K1].", citations=("K1",)))
    assert any("retrieval miss" in f for f in failures)
    assert any("unsupported citation" in f for f in failures)


def test_expected_not_found_but_model_answered():
    q = question(expected_found=False, gold=None)
    _, failures = evaluate(q, "keyword", retrieved(DISTRACT_CHUNK), None,
                           answered(answer="Gmail is used [K1].", citations=("K1",)))
    assert any("hallucination" in f for f in failures)


def test_skipped_answerer_is_not_a_failure():
    result, failures = evaluate(question(), "keyword", retrieved(GOLD_CHUNK),
                                GOLD_CHUNK["id"], {"skipped": "answering disabled"})
    assert failures == [] and result["answer"]["skipped"] == "answering disabled"


def test_unavailable_mode_skips_cleanly():
    result, failures = evaluate(question(), "semantic", {"unavailable": "no embedded passages"},
                                GOLD_CHUNK["id"], answered())
    assert result["status"] == "skipped" and failures == []


# --- mode comparison ------------------------------------------------------------------

def test_compare_semantic_only_gold():
    k = {"retrieved": [{"chunk_id": OTHER_CHUNK["id"]}], "gold_rank": None}
    s = {"retrieved": [{"chunk_id": GOLD_CHUNK["id"]}], "gold_rank": 1}
    notes = compare(k, s)
    assert notes["overlap"] == 0 and "semantic-only-gold" in notes["verdict"]


def test_compare_keyword_first_and_mode_unavailable():
    k = {"retrieved": [{"chunk_id": GOLD_CHUNK["id"]}], "gold_rank": 1}
    s = {"retrieved": [{"chunk_id": GOLD_CHUNK["id"]}, {"chunk_id": OTHER_CHUNK["id"]}], "gold_rank": 1}
    assert compare(k, s)["verdict"] == "keyword-first"
    assert "one mode unavailable" in compare(k, {"status": "skipped"})["verdict"]


# --- orchestrator + artifacts -----------------------------------------------------------

def test_run_qa_end_to_end_with_fakes_and_artifacts(tmp_path):
    storage.doc_chunks[GOLD_CHUNK["id"]] = GOLD_CHUNK
    storage.doc_chunks[OTHER_CHUNK["id"]] = OTHER_CHUNK
    qs = QuestionSet(note="unit run", questions=[question()])

    def fake_retrieve(text, mode):
        return retrieved(GOLD_CHUNK) if mode == "semantic" else retrieved(OTHER_CHUNK)

    calls = []

    def fake_answer(text, passages):
        calls.append((text, tuple(p["chunk_id"] for p in passages)))
        if passages[0]["chunk_id"] == GOLD_CHUNK["id"]:
            return answered(answer="The workspace owner may change it [K1].", citations=("K1",))
        return answered(answer="Reminders arrive early [K1].", citations=("K1",))

    report = run_qa(qs, fake_retrieve, fake_answer, top=5)
    entry = report[0]
    assert entry["gold_chunk_id"] == GOLD_CHUNK["id"]
    assert entry["modes"]["semantic"]["gold_rank"] == 1
    assert entry["modes"]["keyword"]["gold_rank"] is None
    assert any("retrieval miss" in f for f in entry["failures"])
    assert any("retrieved but ignored" in f for f in entry["failures"]) or \
        any("unsupported" in f for f in entry["failures"])
    assert entry["comparison"]["verdict"] == "semantic-only-gold — the multilingual embeddings found what keywords missed"

    md = render_failures_md(report, qs.note)
    assert "retrieval miss" in md and "semantic-only-gold" in md and q_markdown_ok(md)
    (tmp_path / "failures.md").write_text(md, encoding="utf-8")
    assert "q_who" in (tmp_path / "failures.md").read_text(encoding="utf-8")


def q_markdown_ok(md):
    return "## Mode comparison per question" in md


def test_load_questions_rejects_bad_files(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"questions": [{"id": "1BAD", "question": "x"}]}), encoding="utf-8")
    with pytest.raises(SystemExit):
        load_questions(bad)
    shipped = load_questions(ROOT / "eval" / "questions.json")
    assert len(shipped.questions) == 7


# --- real CLI, retrieval only, disposable database ---------------------------------------

def test_cli_retrieval_only_on_fresh_import(tmp_path):
    db = str(tmp_path / "qa.sqlite3")
    chunks_file = tmp_path / "chunks.json"
    chunks_file.write_text(json.dumps([
        {"source": "demo.pdf", "page": 2, "heading": "Rules",
         "text": "Reminder rule: send one day before the due date at nine."},
        {"source": "demo.pdf", "page": 2, "heading": "Rules",
         "text": "Permission rule: only the workspace owner may change the default reminder time."},
    ]), encoding="utf-8")
    questions_file = tmp_path / "questions.json"
    questions_file.write_text(json.dumps({"questions": [
        {"id": "q_who", "question": "owner default reminder time change",
         "expected_found": True,
         "gold": {"source": "demo.pdf", "page": 2, "must_contain": "workspace owner may change"}},
        {"id": "q_missing", "question": "billing provider email",
         "expected_found": False, "gold": None},
    ]}), encoding="utf-8")

    env = {**os.environ, "ZERO_MAGIC_DB": db}
    imported = subprocess.run([sys.executable, "-m", "scripts.import_chunks", str(chunks_file)],
                              cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
    assert imported.returncode == 0, imported.stdout + imported.stderr

    run = subprocess.run([sys.executable, "-m", "scripts.answer_questions", str(questions_file),
                          "--db", db, "--no-answering", "--out", str(tmp_path / "out")],
                         cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stdout + run.stderr
    assert "q_who" in run.stdout
    results = json.loads(next(Path(tmp_path / "out").glob("qa-*/results.json")).read_text(encoding="utf-8"))
    assert results[0]["gold_chunk_id"] == "demo.pdf::00002"
    # semantic was unavailable (no vectors) — skipped, not a crash
    assert results[0]["modes"]["semantic"]["status"] == "skipped"
    failures_text = next(Path(tmp_path / "out").glob("qa-*/failures.md")).read_text(encoding="utf-8")
    assert "Observed failures" in failures_text
