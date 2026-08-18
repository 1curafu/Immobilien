import sqlite3

from src.cooldown import clear_failure, hours_since_failure, init_cooldown, is_in_cooldown, record_failure


def _conn():
    conn = sqlite3.connect(":memory:")
    init_cooldown(conn)
    return conn


def test_is_in_cooldown_false_when_never_failed():
    conn = _conn()
    assert is_in_cooldown(conn, "immoscout24", cooldown_hours=3) is False


def test_is_in_cooldown_true_immediately_after_recording_failure():
    conn = _conn()
    record_failure(conn, "immoscout24")
    assert is_in_cooldown(conn, "immoscout24", cooldown_hours=3) is True


def test_is_in_cooldown_false_after_cooldown_window_elapsed():
    conn = _conn()
    conn.execute(
        "INSERT INTO scraper_failures (name, failed_at) VALUES ('immoscout24', datetime('now', '-5 hours'))"
    )
    conn.commit()
    assert is_in_cooldown(conn, "immoscout24", cooldown_hours=3) is False


def test_is_in_cooldown_true_within_cooldown_window():
    conn = _conn()
    conn.execute(
        "INSERT INTO scraper_failures (name, failed_at) VALUES ('immoscout24', datetime('now', '-1 hours'))"
    )
    conn.commit()
    assert is_in_cooldown(conn, "immoscout24", cooldown_hours=3) is True


def test_clear_failure_resets_cooldown():
    conn = _conn()
    record_failure(conn, "immoscout24")
    clear_failure(conn, "immoscout24")
    assert is_in_cooldown(conn, "immoscout24", cooldown_hours=3) is False


def test_hours_since_failure_returns_none_when_never_failed():
    conn = _conn()
    assert hours_since_failure(conn, "immoscout24") is None


def test_hours_since_failure_is_approximately_correct():
    conn = _conn()
    conn.execute(
        "INSERT INTO scraper_failures (name, failed_at) VALUES ('immoscout24', datetime('now', '-2 hours'))"
    )
    conn.commit()
    hours = hours_since_failure(conn, "immoscout24")
    assert 1.9 < hours < 2.1


def test_record_failure_is_scoped_per_scraper_name():
    conn = _conn()
    record_failure(conn, "immoscout24")
    assert is_in_cooldown(conn, "homegate", cooldown_hours=3) is False
