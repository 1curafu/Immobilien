from src.dedupe import filter_new, init_db, mark_seen
from src.models import Listing


def _listing(id_):
    return Listing(id=id_, titel="Test", preis=650.0, ort="Weinfelden", zimmer=None,
                    url="https://example.com", quelle="flatfox")


def test_filter_new_returns_all_on_empty_db():
    conn = init_db(":memory:")
    listings = [_listing("flatfox:1"), _listing("flatfox:2")]
    assert filter_new(conn, listings) == listings


def test_filter_new_excludes_already_seen():
    conn = init_db(":memory:")
    a, b = _listing("flatfox:1"), _listing("flatfox:2")
    mark_seen(conn, [a])
    assert filter_new(conn, [a, b]) == [b]


def test_mark_seen_is_idempotent():
    conn = init_db(":memory:")
    a = _listing("flatfox:1")
    mark_seen(conn, [a])
    mark_seen(conn, [a])
    count = conn.execute("SELECT COUNT(*) FROM seen_listings").fetchone()[0]
    assert count == 1


def test_filter_new_handles_empty_input():
    conn = init_db(":memory:")
    assert filter_new(conn, []) == []
