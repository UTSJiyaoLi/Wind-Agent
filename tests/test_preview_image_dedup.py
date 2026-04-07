from __future__ import annotations

from rag.retrieval import build_preview_images


def test_build_preview_images_dedup_same_asset_across_chunks() -> None:
    contexts = [
        {
            "rank": 1,
            "page_no": 10,
            "file_name": "doc_a.pdf",
            "media_refs": {
                "images_info": [
                    {"asset_path": "/tmp/assets/fig_01.png", "title": "Figure 1", "kind": "image"},
                ]
            },
        },
        {
            "rank": 2,
            "page_no": 10,
            "file_name": "doc_a.pdf",
            "media_refs": {
                "related_visuals": [
                    {"asset_path": "/tmp/assets/fig_01.png", "title": "Figure 1", "kind": "image"},
                ]
            },
        },
    ]

    previews = build_preview_images(contexts)

    assert len(previews) == 1
    assert previews[0]["asset_path"] == "/tmp/assets/fig_01.png"
    assert sorted(previews[0]["indices"]) == ["CTX1", "CTX2"]

