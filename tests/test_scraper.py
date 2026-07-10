"""Unit tests for the pure parsing/dedup helpers in tiktok_scraper/scraper.py."""
import scraper


def test_extract_videos_from_search_json_basic():
    data = {
        "item_list": [
            {
                "id": "123",
                "desc": "dating tips #fyp",
                "author": {"uniqueId": "alice"},
                "stats": {"diggCount": 5, "commentCount": 2, "shareCount": 1, "playCount": 100},
                "createTime": 111,
            }
        ]
    }
    videos = scraper.extract_videos_from_search_json(data)
    assert len(videos) == 1
    v = videos[0]
    assert v["video_id"] == "123"
    assert v["username"] == "alice"
    assert v["video_url"] == "https://www.tiktok.com/@alice/video/123"
    assert v["stats"] == {"likes": 5, "comments_count": 2, "shares": 1, "views": 100}
    assert v["create_time"] == 111


def test_extract_videos_from_search_json_nested_item_wrapper():
    # The search API sometimes nests the video under an "item" key.
    data = {"itemList": [{"item": {"id": "9", "author": {"unique_id": "bob"}}}]}
    videos = scraper.extract_videos_from_search_json(data)
    assert len(videos) == 1
    assert videos[0]["username"] == "bob"


def test_extract_videos_from_search_json_missing_id_or_author_skipped():
    data = {"item_list": [{"desc": "no id or author"}, {"id": "1"}]}
    assert scraper.extract_videos_from_search_json(data) == []


def test_extract_videos_from_search_json_unexpected_shape_returns_empty():
    assert scraper.extract_videos_from_search_json({}) == []
    assert scraper.extract_videos_from_search_json({"unrelated": "data"}) == []


def test_extract_comments_from_json_basic():
    data = {
        "comments": [
            {"cid": "c1", "text": "so true", "user": {"unique_id": "bob"}, "digg_count": 3, "create_time": 222}
        ]
    }
    comments = scraper.extract_comments_from_json(data)
    assert len(comments) == 1
    c = comments[0]
    assert c["comment_id"] == "c1"
    assert c["username"] == "bob"
    assert c["text"] == "so true"
    assert c["likes"] == 3
    assert c["create_time"] == 222


def test_extract_comments_from_json_requires_id_and_text():
    data = {"comments": [{"cid": "c1"}, {"text": "no id"}]}
    assert scraper.extract_comments_from_json(data) == []


def test_dedupe_by_key_preserves_first_seen_order_keeps_last_value():
    items = [{"id": "a", "v": 1}, {"id": "b", "v": 2}, {"id": "a", "v": 3}]
    result = scraper.dedupe_by_key(items, "id")
    assert [x["id"] for x in result] == ["a", "b"]
    assert result[0]["v"] == 3


def test_dedupe_by_key_empty_list():
    assert scraper.dedupe_by_key([], "id") == []


def test_save_and_load_results_roundtrip(tmp_path):
    out_file = tmp_path / "nested" / "results.json"
    scraper.save_results(str(out_file), [{"video_id": "x"}])
    assert out_file.exists()
    assert not (tmp_path / "nested" / "results.json.tmp").exists()
    assert scraper.load_existing_results(str(out_file)) == [{"video_id": "x"}]


def test_load_existing_results_missing_file_returns_empty(tmp_path):
    assert scraper.load_existing_results(str(tmp_path / "missing.json")) == []


def test_load_existing_results_corrupt_file_returns_empty(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not valid json")
    assert scraper.load_existing_results(str(bad_file)) == []
