"""cfg deploys, reports drift and rolls back, always into a temporary Claude home."""

import json

import pytest

from tests.conftest import ROOT, load

cfg = load(ROOT / "tools" / "cfg.py", "cfg")


def run(home, *args):
    return cfg.main([*args, "--target", str(home)])


@pytest.fixture
def home(tmp_path):
    return tmp_path / "claude"


def test_first_deploy_needs_a_host(home, capsys):
    assert run(home, "deploy") == 2
    assert "--host" in capsys.readouterr().err


def test_unknown_host(home, capsys):
    assert run(home, "plan", "--host", "nope") == 2
    assert "no host profile" in capsys.readouterr().err


def test_deploy_without_yes_changes_nothing(home, capsys):
    assert run(home, "deploy", "--host", "personal") == 0
    assert "dry run" in capsys.readouterr().out
    assert not home.exists()


def test_deploy_installs_everything_the_host_selects(home):
    assert run(home, "deploy", "--host", "work", "--yes") == 0
    host = json.loads((ROOT / "hosts" / "work.json").read_text())
    for skill in host["skills"]:
        assert (home / "skills" / skill / "SKILL.md").is_file()
    for hook in host["hooks"]:
        assert (home / "hooks" / hook).is_file()
    settings = json.loads((home / "settings.json").read_text())
    assert settings["enabledPlugins"] == {"oh-my-claudecode@omc": True}
    commands = [h["command"] for g in settings["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert commands == [
        f"python3 -I {home}/hooks/merge_confirm.py",
        f"python3 -I {home}/hooks/bash_guard.py",
        f"python3 -I {home}/hooks/skill_gate.py",
        f"python3 -I {home}/hooks/secrets_guard.py",
    ]
    state = json.loads((home / "claude-config" / "state.json").read_text())
    assert state["host"] == "work" and state["defaultTracker"] == "jira"
    assert "{claude_home}" not in (home / "settings.json").read_text()


def test_deploy_is_idempotent(home, capsys):
    run(home, "deploy", "--host", "personal", "--yes")
    before = (home / "settings.json").read_bytes(), (home / "CLAUDE.md").read_bytes()
    capsys.readouterr()
    assert run(home, "deploy", "--yes") == 0
    assert "nothing to change" in capsys.readouterr().out
    assert before == ((home / "settings.json").read_bytes(), (home / "CLAUDE.md").read_bytes())


def test_existing_settings_and_omc_block_survive(home):
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"theme": "dark", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]}}))
    (home / "CLAUDE.md").write_text("<!-- OMC:START -->\nomc rules\n<!-- OMC:END -->\n")
    run(home, "deploy", "--host", "personal", "--yes")
    settings = json.loads((home / "settings.json").read_text())
    assert settings["theme"] == "dark" and "Stop" in settings["hooks"]
    md = (home / "CLAUDE.md").read_text()
    assert md.startswith("<!-- OMC:START -->\nomc rules\n<!-- OMC:END -->")
    assert md.count(cfg.START) == 1 and "Guardrails" in md


def test_claude_md_block_is_replaced_not_duplicated(home):
    home.mkdir()
    (home / "CLAUDE.md").write_text(f"top\n\n{cfg.START}\nSTALE-BLOCK\n{cfg.END}\nbottom\n")
    run(home, "deploy", "--host", "personal", "--yes")
    md = (home / "CLAUDE.md").read_text()
    assert md.startswith("top\n") and md.endswith("bottom\n") and "STALE-BLOCK" not in md


def test_switching_host_removes_what_the_new_host_lacks(home, tmp_path, monkeypatch):
    hosts = tmp_path / "repo" / "hosts"
    hosts.mkdir(parents=True)
    small = json.loads((ROOT / "hosts" / "personal.json").read_text())
    small.update(name="small", skills=["linux-troubleshooting"], hooks=["host_default.py"])
    (hosts / "small.json").write_text(json.dumps(small))
    run(home, "deploy", "--host", "personal", "--yes")
    monkeypatch.setattr(cfg, "ROOT", ROOT)
    real = cfg.load_host
    monkeypatch.setattr(cfg, "load_host", lambda name: small if name == "small" else real(name))
    assert run(home, "deploy", "--host", "small", "--yes") == 0
    assert not (home / "skills" / "github-issue-lifecycle").exists()
    assert not (home / "hooks" / "merge_confirm.py").exists()
    settings = json.loads((home / "settings.json").read_text())
    assert "PreToolUse" not in settings["hooks"]


def test_locally_edited_file_is_a_conflict(home, capsys):
    run(home, "deploy", "--host", "personal", "--yes")
    skill = home / "skills" / "fresh-session-handoff" / "SKILL.md"
    skill.write_text("my edit")
    assert run(home, "plan") == 1
    assert "CONFLICT" in capsys.readouterr().out
    assert run(home, "deploy", "--yes") == 1
    assert skill.read_text() == "my edit"
    assert run(home, "deploy", "--yes", "--force") == 0
    assert skill.read_text() != "my edit"


def test_status_reports_modified_missing_and_sync(home, capsys):
    run(home, "deploy", "--host", "personal", "--yes")
    capsys.readouterr()
    run(home, "status")
    assert "in sync" in capsys.readouterr().out
    (home / "hooks" / "merge_confirm.py").write_text("x")
    (home / "skills" / "fresh-session-handoff" / "SKILL.md").unlink()
    run(home, "status")
    out = capsys.readouterr().out
    assert "modified  hooks/merge_confirm.py" in out and "missing   skills/fresh-session-handoff/SKILL.md" in out


def test_status_without_a_deploy(home, capsys):
    run(home, "status")
    assert "no deploy recorded" in capsys.readouterr().out


def test_rollback_restores_the_previous_state(home):
    home.mkdir()
    (home / "settings.json").write_text('{"theme": "dark"}\n')
    run(home, "deploy", "--host", "personal", "--yes")
    run(home, "rollback")
    assert (home / "settings.json").read_text() == '{"theme": "dark"}\n'
    assert not (home / "skills").exists() and not (home / "hooks").exists()
    assert not (home / "CLAUDE.md").exists()
    assert not (home / "claude-config" / "state.json").exists()


def test_rollback_undoes_only_the_last_deploy(home):
    run(home, "deploy", "--host", "personal", "--yes")
    first = (home / "settings.json").read_bytes()
    (home / "skills" / "fresh-session-handoff" / "SKILL.md").write_text("edit")
    run(home, "deploy", "--yes", "--force")
    run(home, "rollback")
    assert (home / "skills" / "fresh-session-handoff" / "SKILL.md").read_text() == "edit"
    assert (home / "settings.json").read_bytes() == first


def test_rollback_with_no_backup(home, capsys):
    assert run(home, "rollback") == 2
    assert "no backup" in capsys.readouterr().err


def test_old_backups_are_pruned(home):
    run(home, "deploy", "--host", "personal", "--yes")
    for i in range(cfg.KEEP_BACKUPS + 2):
        (home / "hooks" / "merge_confirm.py").write_text(str(i))
        run(home, "deploy", "--yes", "--force")
    assert len(list((home / "claude-config" / "backups").iterdir())) == cfg.KEEP_BACKUPS


def test_invalid_settings_json_is_reported(home, capsys):
    home.mkdir()
    (home / "settings.json").write_text("{nope")
    assert run(home, "deploy", "--host", "personal", "--yes") == 2
    assert "not valid JSON" in capsys.readouterr().err


# --- regressions found in review ---------------------------------------------------------


def backups(home):
    root = home / "claude-config" / "backups"
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


def test_a_deploy_that_changes_nothing_leaves_no_backup(home):
    run(home, "deploy", "--host", "personal", "--yes")
    for _ in range(cfg.KEEP_BACKUPS + 1):
        run(home, "deploy", "--yes")
    assert len(backups(home)) == 1
    run(home, "rollback")
    assert not (home / "skills").exists()


def test_rollback_keeps_settings_changed_after_the_deploy(home):
    home.mkdir()
    (home / "settings.json").write_text('{"theme": "dark"}\n')
    run(home, "deploy", "--host", "personal", "--yes")
    settings = json.loads((home / "settings.json").read_text())
    settings["permissions"] = {"allow": ["Bash(ls)"]}
    (home / "settings.json").write_text(json.dumps(settings))
    assert run(home, "rollback") == 0
    after = json.loads((home / "settings.json").read_text())
    assert after["theme"] == "dark" and after["permissions"] == {"allow": ["Bash(ls)"]}
    assert "hooks" not in after
    assert "oh-my-claudecode@omc" in after["enabledPlugins"]  # plugins are only ever added


def test_rollback_keeps_an_omc_block_added_after_a_first_deploy(home):
    run(home, "deploy", "--host", "personal", "--yes")
    md = home / "CLAUDE.md"
    md.write_text("<!-- OMC:START -->\nomc\n<!-- OMC:END -->\n\n" + md.read_text())
    run(home, "rollback")
    assert md.read_text().strip() == "<!-- OMC:START -->\nomc\n<!-- OMC:END -->"
    assert cfg.START not in md.read_text()


@pytest.mark.parametrize("text", [
    f"keep\n{cfg.END}\nmid\n{cfg.START}\ntail\n",
    f"keep\n{cfg.START}\nuser text\n",
    f"{cfg.START}\na\n{cfg.END}\n{cfg.START}\nb\n{cfg.END}\n",
])
def test_damaged_markers_stop_the_deploy_and_lose_nothing(home, text, capsys):
    home.mkdir()
    (home / "CLAUDE.md").write_text(text)
    assert run(home, "deploy", "--host", "personal", "--yes") == 2
    assert (home / "CLAUDE.md").read_text() == text
    assert "CLAUDE.md" in capsys.readouterr().err
    assert not (home / "skills").exists()


def test_retrying_after_a_failed_deploy_does_not_duplicate_hooks(home, monkeypatch):
    real = cfg.write_atomic

    def flaky(path, data, follow=False):
        if path.name == "CLAUDE.md":
            raise PermissionError("denied")
        real(path, data, follow)

    monkeypatch.setattr(cfg, "write_atomic", flaky)
    assert run(home, "deploy", "--host", "personal", "--yes") == 3
    monkeypatch.setattr(cfg, "write_atomic", real)
    assert run(home, "deploy", "--host", "personal", "--yes") == 0
    settings = json.loads((home / "settings.json").read_text())
    assert [len(g["hooks"]) for g in settings["hooks"]["PreToolUse"]] == [1, 1, 1, 1]
    assert len(settings["hooks"]["UserPromptExpansion"]) == 1
    assert len(settings["hooks"]["SessionStart"]) == 1


def test_host_switch_leaves_one_entry_per_hook_and_rolls_back(home, monkeypatch):
    run(home, "deploy", "--host", "personal", "--yes")
    run(home, "deploy", "--host", "work", "--yes")
    state = json.loads((home / "claude-config" / "state.json").read_text())
    assert state["host"] == "work" and state["defaultTracker"] == "jira"
    settings = json.loads((home / "settings.json").read_text())
    assert sum(len(g["hooks"]) for g in settings["hooks"]["SessionStart"]) == 1
    run(home, "rollback")
    assert json.loads((home / "claude-config" / "state.json").read_text())["host"] == "personal"


def test_an_incomplete_backup_is_reported_not_a_traceback(home, capsys):
    run(home, "deploy", "--host", "personal", "--yes")
    (home / "claude-config" / "backups" / backups(home)[-1] / "created.json").unlink()
    assert run(home, "rollback") == 2
    assert "incomplete" in capsys.readouterr().err


def test_backups_sort_in_creation_order_past_ten(home):
    run(home, "deploy", "--host", "personal", "--yes")
    for i in range(12):
        (home / "hooks" / "merge_confirm.py").write_text(str(i))
        run(home, "deploy", "--yes", "--force")
    names = backups(home)
    assert names == sorted(names) and len(names) == cfg.KEEP_BACKUPS
    assert all(n.endswith(tuple(f"-{k:03d}" for k in range(1, 100))) for n in names)


def test_a_symlinked_settings_file_stays_a_symlink(home, tmp_path):
    home.mkdir()
    real = tmp_path / "dotfiles.json"
    real.write_text('{"theme": "dark"}\n')
    (home / "settings.json").symlink_to(real)
    run(home, "deploy", "--host", "personal", "--yes")
    assert (home / "settings.json").is_symlink()
    assert "hooks" in json.loads(real.read_text())


def test_a_home_with_a_space_gets_a_quoted_hook_command(tmp_path):
    spaced = tmp_path / "my claude"
    run(spaced, "deploy", "--host", "personal", "--yes")
    settings = json.loads((spaced / "settings.json").read_text())
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    import shlex

    assert shlex.split(command) == ["python3", "-I", f"{spaced}/hooks/merge_confirm.py"]


def test_non_ascii_settings_survive(home):
    home.mkdir()
    (home / "settings.json").write_text('{"note": "café"}', encoding="utf-8")
    run(home, "deploy", "--host", "personal", "--yes")
    assert "café" in (home / "settings.json").read_text(encoding="utf-8")


def test_malformed_hooks_in_settings_are_reported(home, capsys):
    home.mkdir()
    (home / "settings.json").write_text('{"hooks": []}')
    assert run(home, "deploy", "--host", "personal", "--yes") == 2
    assert "hooks" in capsys.readouterr().err


# --- security regressions ------------------------------------------------------------------


def test_state_paths_cannot_delete_outside_the_home(home, tmp_path):
    run(home, "deploy", "--host", "personal", "--yes")
    victim = tmp_path / "precious.txt"
    victim.write_text("keep")
    state_file = home / "claude-config" / "state.json"
    state = json.loads(state_file.read_text())
    state["files"]["skills/../../precious.txt"] = cfg.sha(b"keep")
    state_file.write_text(json.dumps(state))
    assert run(home, "deploy", "--yes") == 2
    assert victim.read_text() == "keep"


@pytest.mark.parametrize("rel", ["/etc/hostname", "../x", "settings.json/../../x", "notes/x.md", ""])
def test_safe_rel_refuses(home, rel):
    with pytest.raises(cfg.CfgError):
        cfg.safe_rel(home, rel)


def test_rollback_will_not_delete_outside_the_home(home, tmp_path):
    run(home, "deploy", "--host", "personal", "--yes")
    victim = tmp_path / "p2.txt"
    victim.write_text("keep")
    created = home / "claude-config" / "backups" / backups(home)[-1] / "created.json"
    created.write_text(json.dumps(["../p2.txt"]))
    assert run(home, "rollback") == 2
    assert victim.read_text() == "keep"


def test_a_linked_skills_directory_is_refused(home, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    home.mkdir()
    (home / "skills").symlink_to(outside)
    run(home, "deploy", "--host", "personal", "--yes")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("field,value", [("skills", ["../../tools"]), ("hooks", ["../../tools/cfg.py"]), ("skills", ["/etc"])])
def test_host_names_cannot_climb(tmp_path, monkeypatch, field, value):
    root = tmp_path / "repo"
    (root / "hosts").mkdir(parents=True)
    host = json.loads((ROOT / "hosts" / "personal.json").read_text())
    host.update(name="evil", **{field: value})
    (root / "hosts" / "evil.json").write_text(json.dumps(host))
    monkeypatch.setattr(cfg, "ROOT", root)
    with pytest.raises(cfg.CfgError, match="invalid skill or hook name"):
        cfg.load_host("evil")


def test_a_planted_temp_file_symlink_is_not_followed(home, tmp_path):
    home.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("keep")
    victim.chmod(0o600)
    (home / "settings.json.cfg-tmp").symlink_to(victim)
    run(home, "deploy", "--host", "personal", "--yes")
    assert victim.read_text() == "keep" and victim.stat().st_mode & 0o777 == 0o600


def test_settings_mode_is_kept(home):
    home.mkdir()
    (home / "settings.json").write_text("{}")
    (home / "settings.json").chmod(0o600)
    run(home, "deploy", "--host", "personal", "--yes")
    assert (home / "settings.json").stat().st_mode & 0o777 == 0o600


def test_rollback_with_settings_broken_after_deploy_changes_nothing(home, capsys):
    run(home, "deploy", "--host", "personal", "--yes")
    (home / "settings.json").write_text("{broken")
    md_before = (home / "CLAUDE.md").read_text()
    assert run(home, "rollback") == 2
    assert (home / "CLAUDE.md").read_text() == md_before


@pytest.mark.parametrize("name", ["..", "../hosts/personal", "a/../personal", "/tmp/h"])
def test_host_names_are_plain(home, name, capsys):
    assert run(home, "plan", "--host", name) == 2
    assert "invalid host name" in capsys.readouterr().err
