import shutil
from pathlib import Path

from claimsense import release as rel
from claimsense.brain import MockBrain
from claimsense.cli import corpus_problems
from claimsense.evalsuite import load_suite, run_suite

RELEASES = Path(__file__).resolve().parent.parent / "releases"


def test_promote_and_rollback(tmp_path):
    for f in RELEASES.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / "ACTIVE").write_text("v1.0.0\n", encoding="utf-8")
    rel.promote("v1.0.0", "test", "baseline", tmp_path)
    rel.promote("v1.1.0", "test", "bad push", tmp_path)
    assert rel.active_version(tmp_path) == "v1.1.0"
    assert rel.rollback("test", "regression", tmp_path) == "v1.0.0"
    assert rel.active_version(tmp_path) == "v1.0.0"
    assert "ROLLBACK" in rel.history(tmp_path)[-1]["reason"]


def test_smoke_gate_passes_on_good_release():
    rep = run_suite(load_suite("smoke"), MockBrain(), rel.Release.load("v1.0.0"))
    assert rep["gate_passed"] and rep["cases"] == 10


def test_golden_gate_blocks_the_drill_release():
    rep = run_suite(load_suite("golden"), MockBrain(), rel.Release.load("v1.1.0"))
    assert not rep["gate_passed"] and rep["adversarial_failures"]


def test_golden_set_shape():
    s = load_suite("golden")
    fam = [c["family"] for c in s["cases"]]
    assert len(fam) == 150 and fam.count("adversarial") == 30 and fam.count("variant") == 100
    subs = {c["subfamily"] for c in s["cases"] if c["family"] == "adversarial"}
    assert subs == {"prompt_injection", "cross_record_leakage", "forced_auto_decision"}


def test_corpus_is_clean():
    problems, _ = corpus_problems()
    assert problems == []
