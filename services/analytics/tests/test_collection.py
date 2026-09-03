"""Token-gated collection page — the index of one fencer's unlisted bouts.

The access matrix at the bottom is the part that matters. A collection is
strictly more sensitive than any one report it points at: it says in one place
who this fencer has fenced, when, and how it ended. So the page has no id route
at all, and every way of reaching it without the right token has to answer
identically.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import collection, sharing
from app.server import app, _BASE_DIR


REPORTS_DIR = _BASE_DIR / "data" / "reports"

BOUT_ID = "_pytest_coll_260901_de64_s1_piste7_continuous_report"
SCOUT_ID = "_pytest_coll_260901_scout_s1_piste7_continuous_report"
COLLECTION_NAME = "_pytest_collection"


def _fencer(name: str) -> dict:
    return {
        "name": name,
        "club": "",
        "handedness": None,
        "total_touches_scored": 0,
        "total_touches_conceded": 0,
        "most_common_action": None,
        "most_common_action_pct": 0,
        "action_distribution": [],
    }


def _report(left: str, right: str, **summary) -> dict:
    base = {
        "final_score": "5-3",
        "total_touches": 8,
        "match_duration": "3:20",
        "total_frames_analyzed": 900,
        "analysis_time_sec": 1.0,
        "weapon": "foil",
        "bout_type": "de",
        "gender": None,
        "age_group": None,
    }
    base.update(summary)
    return {
        "summary": base,
        "touches": [],
        "exchanges": [],
        "continuous_summary": {"total_exchanges": 12},
        "left_fencer": _fencer(left),
        "right_fencer": _fencer(right),
        "insights": [],
        "warnings": [],
        "meta": {"phase": 6, "fps": 30.0},
    }


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def shared_collection():
    """A collection manifest plus two unlisted reports, cleaned up after.

    The server resolves data/reports from its own base dir rather than from a
    setting, so like test_report_sharing these have to be real files beside the
    real ones. Every id is prefixed so a leak is obvious.

    Yields ``(collection_token, bout_token, scout_token)``.
    """
    priv = sharing.private_dir(REPORTS_DIR)
    priv.mkdir(parents=True, exist_ok=True)

    bout = _report("김상대", "박소윤")
    bout_token = sharing.mark_unlisted(bout)
    (priv / f"{BOUT_ID}.json").write_text(json.dumps(bout), encoding="utf-8")

    scout = _report("정다희", "김래아")
    scout_token = sharing.mark_unlisted(scout)
    (priv / f"{SCOUT_ID}.json").write_text(json.dumps(scout), encoding="utf-8")

    manifest_dir = collection.collections_dir(REPORTS_DIR)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{COLLECTION_NAME}.json"
    coll_token = collection.generate_collection_token()
    manifest_path.write_text(json.dumps({
        "name": COLLECTION_NAME,
        "title": "박소윤 경기 분석",
        "fencer": "박소윤",
        "share_token": coll_token,
    }), encoding="utf-8")

    sharing.reset_token_index()
    try:
        yield coll_token, bout_token, scout_token
    finally:
        (priv / f"{BOUT_ID}.json").unlink(missing_ok=True)
        (priv / f"{SCOUT_ID}.json").unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        sharing.reset_token_index()


# ------------------------------------------------------------------
# id parsing
# ------------------------------------------------------------------


def test_strip_report_suffix_prefers_the_longer_one():
    assert collection.strip_report_suffix("a_b_continuous_report") == "a_b"
    assert collection.strip_report_suffix("a_b_report") == "a_b"
    assert collection.strip_report_suffix("a_b") == "a_b"


@pytest.mark.parametrize("report_id,expected", [
    ("260716_de32_s1_piste9_continuous_report", "2026-07-16"),
    ("20260828_김창환배_소율vs박소윤_전체_piste6_continuous_report", "2026-08-28"),
    ("usaf_B6k6SoJFAr8_continuous_report", None),
])
def test_parse_bout_id_reads_both_date_spellings(report_id, expected):
    assert collection.parse_bout_id(report_id)["date"] == expected


def test_parse_bout_id_reads_round_piste_and_set():
    parsed = collection.parse_bout_id("260716_de32_s1_piste9_continuous_report")
    assert parsed["round_label"] == "32강 1세트"
    assert parsed["piste"] == 9
    assert parsed["set_number"] == 1
    assert parsed["competition"] is None


def test_parse_bout_id_names_a_competition_but_not_a_format_word():
    """김창환배 is a competition; `pool` and `de64` are not."""
    named = collection.parse_bout_id("20260828_김창환배_소율vs박소윤_전체_piste6")
    assert named["competition"] == "김창환배"
    assert named["filename_names"] == ("소율", "박소윤")

    formatted = collection.parse_bout_id("260715_pool_a_piste2")
    assert formatted["competition"] is None
    assert formatted["round_label"] == "예선 A"


def test_parse_bout_id_flags_scouting_footage():
    assert collection.parse_bout_id("260716_scout_s3_piste3")["is_scout"] is True


def test_parse_bout_id_survives_an_id_following_no_convention():
    parsed = collection.parse_bout_id("whatever")
    assert parsed["date"] is None
    assert parsed["round_label"] is None
    assert parsed["piste"] is None


# ------------------------------------------------------------------
# names and scores
# ------------------------------------------------------------------


def test_placeholder_names_fall_back_to_the_filename():
    """The 08-28 bouts were never named; their fencers live in the filename."""
    report = _report("Left Fencer", "Right Fencer")
    parsed = collection.parse_bout_id("20260828_김창환배_소율vs박소윤_전체_piste6")
    assert collection.fencer_names(report, parsed) == ("소율", "박소윤")


def test_confirmed_names_beat_the_filename_order():
    """260815_Pool_Soyun,ParkVsDahee,Jung has its two sides the wrong way round."""
    report = _report("정다희", "박소윤")
    parsed = collection.parse_bout_id("260815_Pool_Soyun,ParkVsDahee,Jung_piste3")
    assert collection.fencer_names(report, parsed) == ("정다희", "박소윤")


def test_official_score_takes_the_headline_and_observed_sits_beneath():
    entry = collection.build_entry(
        "260716_de32_s1_piste9_continuous_report",
        _report("김주은", "박소윤", final_score="15-7", official_final_score="15-9"),
        subject="박소윤",
    )
    assert entry["score"] == "15-9"
    assert entry["score_is_official"] is True
    assert entry["observed_score"] == "15-7"


def test_a_label_is_never_printed_as_a_score():
    """final_score is "연속 분석" when the scoreboard could not be read at all."""
    entry = collection.build_entry(
        "260816_Sena,HongVsSoyun_piste12_continuous_report",
        _report("세나 홍", "박소윤", final_score="연속 분석"),
        subject="박소윤",
    )
    assert entry["score"] is None
    assert entry["observed_score"] is None
    assert entry["score_unread"] is True


def test_bout_without_the_subject_is_filed_as_scouting():
    own = collection.build_entry("260901_de64_s1_piste3", _report("김상대", "박소윤"), subject="박소윤")
    other = collection.build_entry("260716_scout_s3_piste3", _report("정다희", "김래아"), subject="박소윤")

    assert own["is_subject_bout"] is True
    assert own["opponent"] == "김상대"
    assert other["is_subject_bout"] is False
    assert other["is_scout"] is True


# ------------------------------------------------------------------
# building and grouping
# ------------------------------------------------------------------


def test_entries_skip_a_report_with_no_token(tmp_path):
    """A row with nowhere to go would name a minor for nothing."""
    priv = sharing.private_dir(tmp_path)
    priv.mkdir(parents=True)

    linkable = _report("A", "B")
    sharing.mark_unlisted(linkable)
    (priv / "260901_pool_a_piste1_continuous_report.json").write_text(
        json.dumps(linkable), encoding="utf-8")
    (priv / "260901_pool_b_piste1_continuous_report.json").write_text(
        json.dumps(_report("C", "D")), encoding="utf-8")

    entries = collection.build_entries(tmp_path)
    assert [e["report_id"] for e in entries] == ["260901_pool_a_piste1_continuous_report"]
    assert entries[0]["url"].startswith("/r/")


def test_public_reports_never_appear(tmp_path):
    (tmp_path / "public_continuous_report.json").write_text(
        json.dumps(_report("A", "B")), encoding="utf-8")
    assert collection.build_entries(tmp_path) == []


def test_days_are_newest_first_but_bouts_within_a_day_keep_their_order(tmp_path):
    priv = sharing.private_dir(tmp_path)
    priv.mkdir(parents=True)
    for stem in ("260715_pool_a_piste2", "260716_de64_s1_piste3", "260716_de64_s2_piste3"):
        report = _report("X", "박소윤")
        sharing.mark_unlisted(report)
        (priv / f"{stem}_continuous_report.json").write_text(json.dumps(report), encoding="utf-8")

    days = collection.group_by_day(collection.build_entries(tmp_path, subject="박소윤"))
    assert [d["date"] for d in days] == ["2026-07-16", "2026-07-15"]
    assert [e["round_label"] for e in days[0]["entries"]] == ["64강 1세트", "64강 2세트"]


def test_zoom_probe_marks_the_dual_camera_bouts(tmp_path):
    priv = sharing.private_dir(tmp_path)
    priv.mkdir(parents=True)
    report = _report("A", "박소윤")
    sharing.mark_unlisted(report)
    (priv / "260828_pool_a_piste6_continuous_report.json").write_text(
        json.dumps(report), encoding="utf-8")

    assert collection.build_entries(tmp_path, zoom_probe=lambda r: True)[0]["has_zoom"] is True
    assert collection.build_entries(tmp_path, zoom_probe=lambda r: False)[0]["has_zoom"] is False


# ------------------------------------------------------------------
# manifests and token lookup
# ------------------------------------------------------------------


def test_find_collection_by_token(tmp_path):
    directory = collection.collections_dir(tmp_path)
    directory.mkdir(parents=True)
    (directory / "soyun.json").write_text(
        json.dumps({"name": "soyun", "title": "T", "share_token": "abc123"}), encoding="utf-8")

    assert collection.find_collection_by_token(tmp_path, "abc123")["name"] == "soyun"
    assert collection.find_collection_by_token(tmp_path, "wrong") is None


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_empty_tokens_never_match(bad, tmp_path):
    """A manifest with no token must not be opened by supplying no token."""
    directory = collection.collections_dir(tmp_path)
    directory.mkdir(parents=True)
    (directory / "broken.json").write_text(
        json.dumps({"name": "broken", "share_token": ""}), encoding="utf-8")

    assert collection.find_collection_by_token(tmp_path, bad) is None


def test_a_manifest_is_not_mistaken_for_a_report(tmp_path):
    """collections/ sits below the report glob, like keypoints/ does."""
    directory = collection.collections_dir(tmp_path)
    directory.mkdir(parents=True)
    (directory / "soyun.json").write_text(
        json.dumps({"name": "soyun", "share_token": "abc123"}), encoding="utf-8")

    assert list(sharing.iter_report_files(tmp_path)) == []
    assert collection.build_entries(tmp_path) == []


# ------------------------------------------------------------------
# Access matrix — the reason this file exists
# ------------------------------------------------------------------


def test_correct_token_opens_the_collection(client, shared_collection):
    coll_token, bout_token, scout_token = shared_collection
    resp = client.get(f"/c/{coll_token}")

    assert resp.status_code != 500, resp.text[:2000]
    assert resp.status_code == 200
    assert "박소윤 경기 분석" in resp.text
    # Each row links to the bout's own existing token, never to its id.
    assert f"/r/{bout_token}" in resp.text
    assert f"/r/{scout_token}" in resp.text
    assert BOUT_ID not in resp.text
    assert SCOUT_ID not in resp.text


def test_no_token_has_no_route_at_all(client, shared_collection):
    """There is no /c/ without a token, and no id form to fall back to."""
    assert client.get("/c/").status_code == 404
    assert client.get("/c").status_code in (404, 307)


@pytest.mark.parametrize("bad", ["wrong-token", "x", "../../etc/passwd", "%20"])
def test_wrong_token_is_refused(client, shared_collection, bad):
    resp = client.get(f"/c/{bad}")
    assert resp.status_code == 404


def test_a_report_token_does_not_open_the_collection(client, shared_collection):
    """Handing someone one bout must not hand them the roster."""
    _, bout_token, _ = shared_collection
    assert client.get(f"/c/{bout_token}").status_code == 404


def test_refusals_are_indistinguishable(client, shared_collection):
    """A wrong token and a collection that never existed answer identically."""
    _, bout_token, _ = shared_collection
    bodies = {
        client.get(f"/c/{bad}").text
        for bad in ("wrong-token", bout_token, collection.generate_collection_token())
    }
    assert len(bodies) == 1


def test_the_collection_page_is_not_indexable(client, shared_collection):
    coll_token, _, _ = shared_collection
    assert "noindex" in client.get(f"/c/{coll_token}").text


def test_public_report_listing_still_omits_everything_private(client, shared_collection):
    """The collection must not have opened a second door into /reports."""
    listed = {r["video_id"] for r in client.get("/reports").json()["reports"]}
    assert BOUT_ID not in listed
    assert SCOUT_ID not in listed
