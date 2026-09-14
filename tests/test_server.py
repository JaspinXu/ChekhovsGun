import time

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
from conftest import DEMO_ITEMS
from fastapi.testclient import TestClient

from chekhovsgun.server.app import create_app


@pytest.fixture
def client(seeded):
    with TestClient(create_app(seeded.config, seeded)) as test_client:
        yield test_client


def test_healthz(client):
    assert client.get("/healthz").json()["ok"] is True


def test_dashboard_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "ChekhovsGun" in response.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/app.css").status_code == 200


def test_status_reports_both_adapters(client):
    payload = client.get("/api/status").json()
    assert {a["name"] for a in payload["adapters"]} == {"youtube", "bilibili"}
    assert payload["stats"]["items"] == DEMO_ITEMS


def test_config_endpoint_redacts_secrets(seeded):
    seeded.config.bilibili.sessdata = "super-secret"
    with TestClient(create_app(seeded.config, seeded)) as client:
        assert client.get("/api/config").json()["bilibili"]["sessdata"] == "***"


def test_relate_fires_on_a_related_video(client):
    response = client.post(
        "/api/relate",
        json={
            "source": "youtube", "source_id": "abc",
            "title": "RAG chunking strategies and hybrid retrieval",
            "description": "bm25 embeddings rerank",
        },
    )
    payload = response.json()
    assert payload["fired"] is True and payload["hits"]
    assert payload["hits"][0]["deep_link"]


def test_relate_stays_quiet_on_an_unrelated_video(client):
    payload = client.post("/api/relate", json={"title": "猫咪剪指甲全过程"}).json()
    assert payload["fired"] is False


def test_relate_by_url_detects_the_source(client):
    payload = client.get("/api/relate", params={"url": "https://youtu.be/zjkBMFhNj_g"}).json()
    assert "hits" in payload


def test_search(client):
    payload = client.get("/api/search", params={"q": "B-Tree 索引", "limit": 3}).json()
    assert payload["count"] >= 1
    assert any("B-Tree" in hit["item"]["title"] for hit in payload["hits"])


def test_search_rejects_an_empty_query(client):
    assert client.get("/api/search", params={"q": ""}).status_code == 422


def test_items_listing_and_filtering(client):
    assert client.get("/api/items").json()["count"] == DEMO_ITEMS
    payload = client.get("/api/items", params={"source": "bilibili"}).json()
    assert all(item["source"] == "bilibili" for item in payload["items"])


def test_item_detail_and_delete(client):
    item_id = client.get("/api/items").json()["items"][0]["id"]
    detail = client.get(f"/api/items/{item_id}").json()
    assert detail["item"]["id"] == item_id and detail["chunks"]
    assert client.delete(f"/api/items/{item_id}").status_code == 200
    assert client.get(f"/api/items/{item_id}").status_code == 404


def test_unknown_item_is_404(client):
    assert client.get("/api/items/nope:nope").status_code == 404


def test_feedback_is_recorded(client):
    assert client.post("/api/feedback", json={"item_id": "x", "useful": False}).json()["ok"]
    kinds = [event["kind"] for event in client.get("/api/events").json()["events"]]
    assert "feedback" in kinds


def test_cors_allows_the_video_sites(client):
    response = client.options(
        "/api/relate",
        headers={
            "Origin": "https://www.bilibili.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "https://www.bilibili.com"


def test_cors_allows_an_unpacked_extension_origin(client):
    origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    response = client.options(
        "/api/relate",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )
    assert response.headers.get("access-control-allow-origin") == origin


def test_ingest_job_lifecycle(client):
    job = client.post("/api/ingest", json={"source": "youtube", "limit": 1}).json()
    assert job["state"] == "running"
    for _ in range(100):
        state = client.get(f"/api/jobs/{job['job_id']}").json()
        if state["state"] != "running":
            break
        time.sleep(0.05)
    # youtube is unconfigured in tests, so the job completes with no reports.
    assert state["state"] in {"done", "failed"}


def test_relate_explains_why_it_stayed_quiet(client):
    payload = client.post("/api/relate", json={"title": "猫咪剪指甲全过程"}).json()
    assert payload["reason_code"] == "no_match"

    payload = client.get("/api/relate", params={"url": "https://example.com/x"}).json()
    assert payload["reason_code"] == "unknown_url"

    saved = client.get("/api/items", params={"source": "bilibili"}).json()["items"][0]
    payload = client.get("/api/relate", params={"url": saved["url"]}).json()
    if not payload["fired"]:
        assert payload["reason_code"] == "self_saved"


def test_mark_endpoint_updates_status_and_tags(client):
    item_id = client.get("/api/items").json()["items"][0]["id"]
    payload = client.post(
        f"/api/items/{item_id}/mark",
        json={"status": "digested", "add_tags": ["稍后复习"], "note": "看完了"},
    ).json()
    assert payload["item"]["status"] == "digested"
    assert payload["item"]["user_tags"] == ["稍后复习"]
    assert payload["item"]["note"] == "看完了"


def test_mark_rejects_an_unknown_status(client):
    item_id = client.get("/api/items").json()["items"][0]["id"]
    assert client.post(f"/api/items/{item_id}/mark", json={"status": "nope"}).status_code == 422


def test_mark_on_a_missing_item_is_404(client):
    assert client.post("/api/items/nope:nope/mark", json={"status": "muted"}).status_code == 404


def test_items_can_be_filtered_by_status_and_tag(client):
    item_id = client.get("/api/items").json()["items"][0]["id"]
    client.post(f"/api/items/{item_id}/mark", json={"status": "muted", "add_tags": ["x"]})
    assert client.get("/api/items", params={"status": "muted"}).json()["count"] == 1
    assert client.get("/api/items", params={"tag": "x"}).json()["count"] == 1


def test_tags_endpoint(client):
    item_id = client.get("/api/items").json()["items"][0]["id"]
    client.post(f"/api/items/{item_id}/mark", json={"add_tags": ["检索"]})
    assert client.get("/api/tags").json()["tags"] == [{"tag": "检索", "count": 1}]


def test_status_exposes_the_digestion_metrics(client):
    stats = client.get("/api/status").json()["stats"]
    for key in ("items_digested", "by_status", "coverage", "fire_rate", "comment_chunks"):
        assert key in stats
