# tests/test_workflow_yaml.py
from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "search.yml"


def test_workflow_file_is_valid_yaml():
    assert WORKFLOW_PATH.exists()
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert "jobs" in workflow


def test_workflow_runs_on_schedule_and_manual_dispatch():
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    triggers = workflow.get(True, workflow.get("on"))  # PyYAML parses bare `on:` key as boolean True
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers


def test_workflow_installs_playwright_chromium_with_deps():
    text = WORKFLOW_PATH.read_text()
    assert "playwright install --with-deps chromium" in text


def test_workflow_uses_xvfb_to_run_the_scraper():
    text = WORKFLOW_PATH.read_text()
    assert "xvfb-run" in text
    assert "python -m src.main" in text


def test_workflow_declares_all_three_secrets():
    text = WORKFLOW_PATH.read_text()
    for secret in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL"):
        assert f"secrets.{secret}" in text


def test_workflow_push_is_gated_by_a_single_diff_check_not_two():
    # Regression test: `git diff --staged --quiet || git commit ...` followed
    # by a SECOND `git diff --staged --quiet || git push` never pushes — the
    # commit consumes the staged diff, so the second check always sees "no
    # changes" and skips the push. Confirmed live 2026-08-18: seen_listings.db
    # was committed on the runner every time but never reached origin. The
    # push must be gated by the same diff check that gates the commit, not a
    # second independent one.
    text = WORKFLOW_PATH.read_text()
    assert text.count("git diff --staged --quiet") == 1
    assert "git push" in text
