"""The OMC quality gates this repo ships: the fragment cfg.py merges, and the two gate skills."""

import json

import pytest

from tests.conftest import ROOT

SKILLS = ROOT / "config" / "skills"
HOSTS = sorted((ROOT / "hosts").glob("*.json"))
FRAGMENT = json.loads((ROOT / "config" / "omc.fragment.json").read_text())
# The gate each skill is, per the spec's "OMC quality gates" section.
GATES = {"spec-test-plan": "blocking", "spec-scope": "advisory"}


def test_gate_fragment_names_real_skills_and_stages():
    assert list(FRAGMENT) == ["qualityGates"]
    gates = FRAGMENT["qualityGates"]
    assert set(gates) == {"deep-interview", "ralplan", "omc-review"}
    hosted = [set(json.loads(h.read_text())["skills"]) for h in HOSTS]
    for stage, entries in gates.items():
        assert entries, stage
        for entry in entries:
            assert set(entry) == {"skill", "mode"}, entry
            assert entry["mode"] in ("blocking", "advisory"), entry
            assert (SKILLS / entry["skill"] / "SKILL.md").is_file(), entry["skill"]
            assert all(entry["skill"] in skills for skills in hosted), entry["skill"]


@pytest.mark.parametrize("skill,mode", GATES.items())
def test_gate_skills_are_read_only_and_return_a_verdict(skill, mode):
    text = (SKILLS / skill / "SKILL.md").read_text()
    assert "read-only" in text.lower()
    assert "`VERDICT: PASS`" in text and "`VERDICT: BLOCK`" in text
    assert f"**{mode}**" in text
    stages = [s for s, entries in FRAGMENT["qualityGates"].items() if {"skill": skill, "mode": mode} in entries]
    assert stages and all(f"`{stage}`" in text for stage in stages)


def test_spec_scope_gate_matches_the_block_wording():
    text = " ".join((SKILLS / "spec-scope" / "SKILL.md").read_text().split())
    assert "Report work outside the approved spec or under its Non-Goals as `scope:` findings, not as defects." in text
    assert "Ask for an abstraction only when it makes the code easier to read or to maintain than the code without it." in text


def test_spec_scope_checks_the_reviewed_diff_and_its_verdict_rules_agree():
    """omc-review is the stage for diff gates; deep-interview and ralplan are for planning gates."""
    text = " ".join((SKILLS / "spec-scope" / "SKILL.md").read_text().split())
    assert "reviewed changes" in text and "every spec item built" in text and "reviewed plan" not in text
    assert "`VERDICT: PASS` when there is no `missing:` or `scope:` finding" in text
    assert "return `VERDICT: PASS` with that one note" in text


def test_spec_test_plan_accepts_a_skip_line_anywhere_without_a_section():
    text = (SKILLS / "spec-test-plan" / "SKILL.md").read_text()
    assert "with no `## Test plan` section" in text and "anywhere in the spec" in text  # as spec-check reads it
