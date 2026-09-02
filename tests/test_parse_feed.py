"""Feed / watch parsers — no live YouTube."""
import unittest

from desk.parse import length_of, related_videos, walk_videos, watch_info


class WalkVideos(unittest.TestCase):
    def test_grid_and_lockup(self):
        data = {
            "contents": {
                "richGridRenderer": {
                    "contents": [
                        {
                            "gridVideoRenderer": {
                                "videoId": "abcdefghijk",
                                "title": {"simpleText": "Trending one"},
                                "shortBylineText": {"runs": [{"text": "Ch"}]},
                                "viewCountText": {"simpleText": "12K views"},
                            }
                        },
                        {
                            "lockupViewModel": {
                                "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
                                "contentId": "lmnopqrstuv",
                                "metadata": {
                                    "lockupMetadataViewModel": {
                                        "title": {"content": "Home two"},
                                    }
                                },
                            }
                        },
                    ]
                }
            }
        }
        videos = walk_videos(data)
        ids = [v["video_id"] for v in videos]
        self.assertIn("abcdefghijk", ids)
        self.assertIn("lmnopqrstuv", ids)

    def test_dedupes(self):
        data = {
            "a": {"videoRenderer": {"videoId": "abcdefghijk", "title": {"simpleText": "A"}}},
            "b": {"compactVideoRenderer": {"videoId": "abcdefghijk", "title": {"simpleText": "A"}, "channelId": "UC" + "x" * 22}},
        }
        videos = walk_videos(data)
        self.assertEqual(sum(1 for v in videos if v["video_id"] == "abcdefghijk"), 1)


class WatchInfo(unittest.TestCase):
    def test_primary_secondary(self):
        cid = "UC" + "y" * 22
        data = {
            "videoPrimaryInfoRenderer": {
                "title": {"simpleText": "Hello"},
                "viewCount": {"simpleText": "1,234 views"},
                "relativeDateText": {"simpleText": "2 days ago"},
            },
            "videoSecondaryInfoRenderer": {
                "owner": {
                    "videoOwnerRenderer": {
                        "title": {
                            "runs": [
                                {
                                    "text": "Owner",
                                    "navigationEndpoint": {"browseEndpoint": {"browseId": cid}},
                                }
                            ]
                        }
                    }
                },
                "description": {"simpleText": "About the clip"},
            },
        }
        info = watch_info(data)
        self.assertEqual(info["title"], "Hello")
        self.assertEqual(info["channel"], "Owner")
        self.assertEqual(info["channel_id"], cid)
        self.assertEqual(info["views"], 1234)
        self.assertEqual(info["published"], "2 days ago")
        self.assertEqual(info["description"], "About the clip")

    def test_nested_views_likes_comments(self):
        data = {
            "videoPrimaryInfoRenderer": {
                "title": {"simpleText": "Nested"},
                "viewCount": {
                    "videoViewCountRenderer": {
                        "viewCount": {"simpleText": "158.639 visualizações"},
                        "originalViewCount": "158639",
                    }
                },
            },
            "likeButtonViewModel": {"likeCountIfIndifferentNumber": 1900},
            "commentsHeaderRenderer": {"commentsCount": {"simpleText": "20"}},
        }
        info = watch_info(data)
        self.assertEqual(info["views"], 158639)
        self.assertEqual(info["likes"], 1900)
        self.assertEqual(info["comments"], 20)

    def test_related_keeps_cards_without_channel_id(self):
        data = {
            "compactVideoRenderer": {
                "videoId": "abcdefghijk",
                "title": {"simpleText": "No channel id"},
                "lengthText": {"simpleText": "12:04"},
            }
        }
        related = related_videos({"a": data})
        self.assertEqual(related[0]["video_id"], "abcdefghijk")
        self.assertEqual(related[0]["length"], "12:04")

    def test_length_from_overlay(self):
        card = {
            "thumbnailOverlayTimeStatusRenderer": {"text": {"simpleText": "3:01"}},
        }
        self.assertEqual(length_of(card), "3:01")


if __name__ == "__main__":
    unittest.main()
