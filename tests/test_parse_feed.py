"""Feed / watch parsers — no live YouTube."""
import unittest

from desk.parse import (
    apply_upload_floor,
    is_empty_watch,
    length_of,
    parse_count,
    related_videos,
    walk_videos,
    watch_info,
)


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

    def test_related_lockup_name_with_digit_not_views(self):
        data = {
            "lockupViewModel": {
                "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
                "contentId": "abcdefghijk",
                "metadata": {
                    "lockupMetadataViewModel": {
                        "title": {"content": "Visa in 10 minutes"},
                        "metadata": {
                            "contentMetadataViewModel": {
                                "metadataRows": [
                                    {"metadataParts": [{"text": {"content": "Zawba3a Tech"}}]},
                                    {
                                        "metadataParts": [
                                            {
                                                "text": {"content": "30\xa0ألف"},
                                                "accessibilityLabel": "30 ألف مشاهدة",
                                            },
                                            {"text": {"content": "خلال 9 أشهر"}},
                                        ]
                                    },
                                ]
                            }
                        },
                    }
                },
            }
        }
        related = related_videos(data)
        self.assertEqual(related[0]["channel"], "Zawba3a Tech")
        self.assertEqual(related[0]["views"], 30_000)

    def test_related_lockup_arabic_views_from_a11y(self):
        data = {
            "contents": {
                "twoColumnWatchNextResults": {
                    "secondaryResults": {
                        "secondaryResults": {
                            "results": [
                                {
                                    "lockupViewModel": {
                                        "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
                                        "contentId": "abcdefghijk",
                                        "metadata": {
                                            "lockupMetadataViewModel": {
                                                "title": {"content": "Homemade Biryani"},
                                                "metadata": {
                                                    "contentMetadataViewModel": {
                                                        "metadataRows": [
                                                            {
                                                                "metadataParts": [
                                                                    {"text": {"content": "Tonny's Kitchen"}}
                                                                ]
                                                            },
                                                            {
                                                                "metadataParts": [
                                                                    {
                                                                        "text": {"content": "3.8\xa0مليون"},
                                                                        "accessibilityLabel": "3.8 مليون مشاهدة",
                                                                    },
                                                                    {"text": {"content": "قبل سنة واحدة"}},
                                                                ]
                                                            },
                                                        ]
                                                    }
                                                },
                                            }
                                        },
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        }
        related = related_videos(data)
        self.assertEqual(related[0]["channel"], "Tonny's Kitchen")
        self.assertEqual(related[0]["views"], 3_800_000)
        self.assertEqual(related[0]["published"], "قبل سنة واحدة")

    def test_related_skips_engagement_lockups(self):
        data = {
            "engagementPanelSectionListRenderer": {
                "lockupViewModel": {
                    "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
                    "contentId": "zzzzzzzzzzz",
                    "metadata": {"lockupMetadataViewModel": {"title": {"content": "Comment clip"}}},
                }
            },
            "compactVideoRenderer": {
                "videoId": "abcdefghijk",
                "title": {"simpleText": "On the rail"},
            },
        }
        related = related_videos(data)
        self.assertEqual([v["video_id"] for v in related], ["abcdefghijk"])

    def test_collab_owner_attributed_title(self):
        cid = "UCk1Z7BCvWGhuplXWiKfSzKA"
        data = {
            "videoPrimaryInfoRenderer": {"title": {"simpleText": "Ruqyah"}},
            "videoOwnerRenderer": {
                "attributedTitle": {
                    "content": "الكوثر قران كريم | Quran ودار الرقية الشرعية | Dar Al-Ruqyah",
                    "commandRuns": [
                        {
                            "onTap": {
                                "innertubeCommand": {
                                    "showDialogCommand": {
                                        "panelLoadingStrategy": {
                                            "inlineContent": {
                                                "dialogViewModel": {
                                                    "customContent": {
                                                        "listViewModel": {
                                                            "listItems": [
                                                                {
                                                                    "listItemViewModel": {
                                                                        "title": {"content": "الكوثر قران كريم | Quran"},
                                                                        "subtitle": {
                                                                            "content": "@Al-Kawthar-t7y • 179 ألف مشترك"
                                                                        },
                                                                        "commandRuns": [
                                                                            {
                                                                                "onTap": {
                                                                                    "innertubeCommand": {
                                                                                        "browseEndpoint": {
                                                                                            "browseId": cid
                                                                                        }
                                                                                    }
                                                                                }
                                                                            }
                                                                        ],
                                                                    }
                                                                }
                                                            ]
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    ],
                }
            },
        }
        info = watch_info(data)
        self.assertEqual(info["channel"], "الكوثر قران كريم | Quran")
        self.assertEqual(info["channel_id"], cid)
        self.assertEqual(info["subscribers"], 179_000)

    def test_empty_watch_helper(self):
        self.assertTrue(is_empty_watch({"title": "", "video_id": "not-a-video"}, []))
        self.assertFalse(is_empty_watch({"title": "Hello"}, []))
        self.assertFalse(is_empty_watch({"title": ""}, [{"video_id": "abcdefghijk"}]))

    def test_parse_count_handle_then_subs(self):
        self.assertEqual(parse_count("@Al-Kawthar-t7y • 179 ألف مشترك"), 179_000)
        self.assertEqual(parse_count("\u200f\u2068@Al-Kawthar-t7y\u2069 \u2022 179 ألف مشترك"), 179_000)
        self.assertIsNone(parse_count("@name1Msubscribers"))

    def test_upload_floor_drops_old_week_leaks(self):
        rows = [
            {"video_id": "aaaaaaaaaaa", "published": "قبل 6 أيام"},
            {"video_id": "bbbbbbbbbbb", "published": "قبل شهر واحد"},
            {"video_id": "ccccccccccc", "published": "قبل 3 أشهر"},
            {"video_id": "ddddddddddd", "published": ""},
        ]
        kept = apply_upload_floor(rows, "week")
        self.assertEqual([v["video_id"] for v in kept], ["aaaaaaaaaaa", "ddddddddddd"])
        self.assertEqual(len(apply_upload_floor(rows, None)), 4)


if __name__ == "__main__":
    unittest.main()
