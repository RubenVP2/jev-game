import json
from pathlib import Path

import pytest

from conftest import FakeClient, requires_chromium
from veille.harness import Harness, Verdict, golden_exemplars
from veille.harness.evaluate import SAMPLE_DOSSIER, item_from_dossier
from veille.harness.facts import FactSheet, clean_fact_sheet, numbers_in, ungrounded_figures
from veille.harness.normalize import normalize
from veille.harness.style import lint
from veille.llm import LLM
from veille.models import PostContent

DOSSIER = SAMPLE_DOSSIER.read_text()
ITEM = item_from_dossier(DOSSIER)

FACTS = {
    "subject": "Ledgerline",
    "topic": "STORAGE ENGINES",
    "what_it_is": "An embedded append-only log store in Rust with per-key compaction",
    "mechanism": ["Writes append to a segment file", "An in-memory index maps each key to its latest offset",
                  "Compaction rewrites only the live record of a key with too many superseded records"],
    "whats_new": "Garbage is tracked per key instead of per segment",
    "figures": [
        {"value": "1.9 million ops/s", "meaning": "write throughput, Zipfian, 16 threads",
         "quote": "| Write throughput | 1.9 million ops/s | 0.8 million ops/s |"},
        {"value": "48 bytes", "meaning": "index memory per key", "quote": "about 48 bytes per key"},
        {"value": "9.9x", "meaning": "invented", "quote": "this quote is not in the dossier 9.9"},
    ],
    "tradeoffs": ["The index must fit in memory", "No efficient range scans"],
    "critiques": [{"point": "RocksDB defaults are an unfair baseline", "attribution": "HN commenter"}],
    "code_example": "let store = Ledgerline::open(\"data/\", Options::default())?;",
    "audience": "Engineers running write-heavy key-value workloads",
    "use_if": ["Keyspace fits in RAM"], "skip_if": ["You need range scans"], "unknowns": "No range scan benchmark",
}


def post(post_text: str, figure: str = "1.9 million ops/s") -> dict:
    return {
        "angle": "Per-key compaction trades RAM for write amplification",
        "threads": {
            "post": post_text,
            "reply": "HN commenters note the baseline is RocksDB with default options, which few people run for this workload.",
        },
        "tiktok": {"title": "A log store that compacts per key", "description": "Ledgerline tracks garbage per key. #databases #rust"},
        "slides": [
            {"kind": "cover", "kicker": "hacker news / storage", "heading": "Compaction per key, not per segment.",
             "body": "Ledgerline is an append-only log store with an in-memory index."},
            {"kind": "mechanism", "heading": "How it works", "bullets": [
                "- Writes append to the active segment", "- The index maps each key to its latest offset",
                "- Hot keys get compacted alone."]},
            {"kind": "stat", "value": "1.3", "label": "write amplification in the README benchmark",
             "body": f"{figure} on one NVMe SSD with 16 threads. Baseline: RocksDB with default options."},
            {"kind": "compare", "heading": "Trade-off", "left_title": "Gains", "left": ["Low write amplification", "Hot keys compact alone"],
             "right_title": "Costs", "right": ["48 bytes of RAM per key", "No range scans"]},
            {"kind": "verdict", "heading": "Verdict", "body": "A strong fit for session stores whose keyspace fits in memory.",
             "left": ["Use it if: keys fit in RAM"], "right": ["Skip it if: you need range scans"]},
        ],
    }


GOOD_POST = "Ledgerline compacts per key, so a hot key never forces a rewrite of cold data.\n\nWrites append to a segment, an in-memory index tracks offsets.\nThe README reports 1.9 million ops/s on one NVMe SSD.\nThe cost: 48 bytes of RAM per key, and no range scans."


def verdict(score: int, issues: list[str]) -> str:
    scores = dict.fromkeys(["voice", "hook", "mechanism", "grounding", "tradeoff", "structure", "clarity"], score)
    return json.dumps({"scores": scores, "issues": issues, "summary": "s"})


def harness_with(settings, answers) -> tuple[Harness, FakeClient]:
    client = FakeClient(answers)
    llm = LLM(settings)
    llm._clients["first"] = client
    return Harness(settings, llm), client


def test_golden_exemplars_follow_the_house_style():
    exemplars = golden_exemplars()
    assert len(exemplars) >= 2
    for ex in exemplars:
        assert lint(ex, 5, 8) == []


def test_clean_fact_sheet_drops_ungrounded_figures():
    facts = clean_fact_sheet(FactSheet.model_validate(FACTS), DOSSIER)
    assert [f.value for f in facts.figures] == ["1.9 million ops/s", "48 bytes"]
    assert facts.code_example  # copied verbatim, kept
    invented = facts.model_copy(update={"code_example": "store.magic()"})
    assert clean_fact_sheet(invented, DOSSIER).code_example == ""


def test_numbers_and_grounding():
    assert numbers_in("1,204 stars, 3.20x and -41%") == {"1204", "3.2", "41"}
    content = PostContent.model_validate(post(GOOD_POST))
    assert ungrounded_figures(content, DOSSIER) == []
    content.threads.post = "Ledgerline is 5.3x faster than RocksDB."
    assert any("'5.3'" in p for p in ungrounded_figures(content, DOSSIER))
    content.threads.post = "Ledgerline reaches 1.9M ops/s and indexes 10M keys."
    assert ungrounded_figures(content, DOSSIER) == []  # scaled forms of 1.9 million / 10 million


def test_normalize_is_idempotent_and_adds_source():
    raw = PostContent.model_validate(post(GOOD_POST + " #db"))
    once = normalize(raw, ITEM.url, ITEM.discussion_url, ["#softwareengineering", "#tech"])
    assert "#db" not in once.threads.post
    assert f"Source: {ITEM.url}" in once.threads.reply
    assert f"Discussion: {ITEM.discussion_url}" in once.threads.reply
    assert once.slides[0].kicker == "HACKER NEWS / STORAGE"
    assert once.slides[0].heading.endswith("segment")
    assert once.slides[1].bullets == ["Writes append to the active segment", "The index maps each key to its latest offset",
                                      "Hot keys get compacted alone"]
    assert once.slides[-1].left == ["keys fit in RAM"]
    assert once.tiktok.description.endswith("#databases #rust #softwareengineering #tech")
    assert normalize(once, ITEM.url, ITEM.discussion_url, ["#softwareengineering", "#tech"]) == once


@pytest.mark.parametrize(
    ("text", "flagged"),
    [("We built it in Rust.", True), ("Our team ships it.", True), ("It uses async I/O.", False),
     ("Export rules in the US apply.", False), ("I think it works.", True)],
)
def test_first_person_rule(text, flagged):
    content = PostContent.model_validate(post(GOOD_POST))
    content.slides[0].body = text
    assert any("first person" in p for p in lint(content, 5, 8)) is flagged


def test_lint_catches_structure_problems():
    content = PostContent.model_validate(post(GOOD_POST))
    content.slides.insert(2, content.slides[2].model_copy())
    content.threads.post = "Is this the end of RocksDB? https://x.dev"
    problems = "\n".join(lint(content, 5, 8))
    assert "only one 'stat' slide" in problems
    assert "not a question" in problems
    assert "no link in the main post" in problems
    content.slides[1].bullets = ["step"] * 7
    assert "has 7 items, use 3 to 5" in "\n".join(lint(content, 5, 8))


async def test_compose_revises_until_the_judge_is_satisfied(settings):
    harness, client = harness_with(settings, [
        json.dumps(FACTS),
        json.dumps(post(GOOD_POST)),
        verdict(5, ["threads.post line 1: name the mechanism"]),
        json.dumps(post(GOOD_POST.replace("compacts per key", "compacts each key on its own"))),
        verdict(9, []),
    ])
    comp = await harness.compose(ITEM, DOSSIER, approved=[], recent_hooks=["Old hook"])
    assert comp.report.revisions == 1
    assert comp.report.score == 9
    assert "on its own" in comp.content.threads.post
    assert comp.report.writer == "first/m1"
    # The revision request carries the judge's issues and the previous version.
    revision_prompt = client.requests[3]["messages"][1]["content"]
    assert "name the mechanism" in revision_prompt and "PREVIOUS VERSION" in revision_prompt
    # Exemplars and recent hooks reach the writer.
    first_prompt = client.requests[1]["messages"][1]["content"]
    assert "STYLE REFERENCES" in first_prompt and "Old hook" in first_prompt
    # The ungrounded figure never reaches the writer.
    assert "9.9x" not in first_prompt


async def test_compose_keeps_the_best_version(settings):
    harness, _ = harness_with(settings, [
        json.dumps(FACTS),
        json.dumps(post(GOOD_POST)),
        verdict(7, ["x"]),
        json.dumps(post(GOOD_POST.replace("compacts per key", "compacts keys"))),
        verdict(6, ["y"]),
        json.dumps(post(GOOD_POST.replace("compacts per key", "compacts each key"))),
        verdict(5, ["z"]),
    ])
    comp = await harness.compose(ITEM, DOSSIER, approved=[], recent_hooks=[])
    assert comp.report.revisions == 2
    assert comp.report.score == 7
    assert "compacts per key" in comp.content.threads.post
    assert comp.report.open_issues == ["x"]


async def test_writer_gets_figure_feedback_from_the_same_model(settings):
    harness, client = harness_with(settings, [
        json.dumps(FACTS),
        json.dumps(post(GOOD_POST, figure="2.4 million ops/s")),
        json.dumps(post(GOOD_POST)),
        verdict(9, []),
    ])
    comp = await harness.compose(ITEM, DOSSIER, approved=[], recent_hooks=[])
    assert "1.9 million ops/s" in comp.content.slides[2].body
    feedback = client.requests[2]["messages"][-1]["content"]
    assert "'2.4' is not in the dossier" in feedback


async def test_judge_failure_keeps_the_linted_draft(settings):
    harness, _ = harness_with(settings, [json.dumps(FACTS), json.dumps(post(GOOD_POST)), RuntimeError("judge down")])
    comp = await harness.compose(ITEM, DOSSIER, approved=[], recent_hooks=[])
    assert comp.report.score is None
    assert comp.content.threads.post.startswith("Ledgerline")


def test_approved_posts_come_before_golden_exemplars(settings, sample_content):
    harness = Harness(settings, LLM(settings))
    approved = sample_content.model_copy(update={"angle": "approved"})
    picked = harness.exemplars([approved])
    assert picked[0].angle == "approved"
    assert len(picked) == settings.app.harness.exemplars


def test_verdict_score_is_weighted():
    v = Verdict.model_validate(json.loads(verdict(8, [])))
    assert v.score == 8.0
    data = json.loads(verdict(10, []))
    data["scores"]["grounding"] = 0
    assert Verdict.model_validate(data).score == 8.0


async def test_minor_style_issues_do_not_sink_a_draft(settings):
    long_sentence = "Ledgerline keeps " + "every single key and offset " * 6 + "in memory."
    wordy = GOOD_POST.replace("The cost:", long_sentence + "\nThe cost:")
    harness, _ = harness_with(settings, [json.dumps(FACTS)] + [json.dumps(post(wordy))] * 4 + [verdict(9, [])])
    comp = await harness.compose(ITEM, DOSSIER, approved=[], recent_hooks=[])
    assert long_sentence in comp.content.threads.post
    assert any(issue.startswith("[style]") for issue in comp.report.open_issues)


async def test_hard_problems_still_fail_the_model(settings):
    from veille.llm import LLMError

    banned = GOOD_POST.replace("The cost:", "A game-changer. The cost:")
    harness, _ = harness_with(settings, [json.dumps(FACTS)] + [json.dumps(post(banned))] * 4)
    harness.llm._clients["second"] = FakeClient([json.dumps(post(banned))] * 4)
    with pytest.raises(LLMError):
        await harness.compose(ITEM, DOSSIER, approved=[], recent_hooks=[])


REALISTIC = Path(__file__).parent / "fixtures" / "realistic_post.json"


def test_a_realistic_model_output_passes_the_harness(settings):
    """A post written by a capable model, following the production prompt, must pass as is.

    Guards against rules that are stricter than what a real writer can satisfy (e.g. verbatim
    README code longer than the code width limit).
    """
    content = PostContent.model_validate(json.loads(REALISTIC.read_text()))
    assert Harness(settings, LLM(settings)).problems(content, ITEM, DOSSIER) == []


@requires_chromium
async def test_a_realistic_model_output_fits_the_slides(settings, tmp_path):
    from datetime import datetime

    from veille.carousel.render import render_slides

    content = normalize(PostContent.model_validate(json.loads(REALISTIC.read_text())), ITEM.url, ITEM.discussion_url, [])
    result = await render_slides(settings, content, tmp_path, 1, datetime(2026, 1, 1), ITEM)
    assert result.overflows == []
