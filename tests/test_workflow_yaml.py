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
