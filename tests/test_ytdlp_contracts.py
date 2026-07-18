import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yt_dlp

from src.core.transcript import TranscriptExtractor
from src.core.ytdlp_client import YTDLPClient


ROOT = Path(__file__).resolve().parents[1]


def youtube_dl_mock(youtube_dl, info=None, error=None):
    instance = youtube_dl.return_value.__enter__.return_value
    if error is not None:
        instance.extract_info.side_effect = error
    else:
        instance.extract_info.return_value = info
    return instance


class YTDLPExtractionContractTests(unittest.TestCase):
    def make_client(self):
        with patch.object(YTDLPClient, "_load_settings", return_value={}):
            return YTDLPClient()

    @patch("src.core.ytdlp_client.yt_dlp.YoutubeDL")
    def test_channel_info_contract_uses_metadata_only_extraction(self, youtube_dl):
        extractor = youtube_dl_mock(
            youtube_dl,
            {
                "channel_id": "UCddiUEpeqJcYeBxX1IVBKvQ",
                "channel": "The Verge",
                "channel_url": "https://www.youtube.com/channel/UCddiUEpeqJcYeBxX1IVBKvQ",
            },
        )

        result = self.make_client().extract_channel_info("@verge")

        self.assertEqual(
            result,
            {
                "channel_id": "UCddiUEpeqJcYeBxX1IVBKvQ",
                "channel_name": "The Verge",
                "channel_url": "https://www.youtube.com/channel/UCddiUEpeqJcYeBxX1IVBKvQ",
            },
        )
        extractor.extract_info.assert_called_once_with(
            "https://www.youtube.com/@verge/videos", download=False
        )
        options = youtube_dl.call_args.args[0]
        self.assertEqual(options["extract_flat"], "in_playlist")
        self.assertEqual(options["playlistend"], 1)
        self.assertTrue(options["skip_download"])

    @patch("src.core.ytdlp_client.yt_dlp.YoutubeDL")
    def test_playlist_contract_filters_shorts_and_honors_limit(self, youtube_dl):
        extractor = youtube_dl_mock(
            youtube_dl,
            {
                "entries": [
                    {
                        "id": "video000001",
                        "title": "Regular video",
                        "url": "https://www.youtube.com/watch?v=video000001",
                        "upload_date": "20260718",
                    },
                    {
                        "id": "short000001",
                        "title": "Short video",
                        "url": "https://www.youtube.com/shorts/short000001",
                        "upload_date": "20260717",
                    },
                    {
                        "id": "video000002",
                        "title": "Second regular video",
                        "url": "https://www.youtube.com/watch?v=video000002",
                        "upload_date": "20260716",
                    },
                ]
            },
        )

        result = self.make_client().get_channel_videos(
            "UCddiUEpeqJcYeBxX1IVBKvQ", max_videos=1, skip_shorts=True
        )

        self.assertEqual(
            result,
            [
                {
                    "id": "video000001",
                    "title": "Regular video",
                    "url": "https://www.youtube.com/watch?v=video000001",
                    "published": "20260718",
                }
            ],
        )
        extractor.extract_info.assert_called_once_with(
            "https://www.youtube.com/channel/UCddiUEpeqJcYeBxX1IVBKvQ/videos",
            download=False,
        )
        options = youtube_dl.call_args.args[0]
        self.assertEqual(options["extract_flat"], "in_playlist")
        self.assertEqual(options["playlistend"], 3)

    @patch("src.core.ytdlp_client.yt_dlp.YoutubeDL")
    def test_metadata_contract_preserves_fields_and_formats_values(self, youtube_dl):
        extractor = youtube_dl_mock(
            youtube_dl,
            {
                "id": "dQw4w9WgXcQ",
                "title": "Never Gonna Give You Up",
                "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "duration": 213,
                "view_count": 1_000_000,
                "upload_date": "20091025",
                "description": "Official music video",
                "channel": "Rick Astley",
                "uploader": "Rick Astley",
                "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
            },
        )

        result = self.make_client().get_video_metadata("dQw4w9WgXcQ")

        self.assertEqual(result["duration"], 213)
        self.assertEqual(result["duration_string"], "3m 33s")
        self.assertEqual(result["view_count_string"], "1.0M views")
        self.assertEqual(result["upload_date_string"], "2009-10-25")
        self.assertEqual(result["channel_id"], "UCuAXFkgsw1L7xaCfnd5JJOw")
        extractor.extract_info.assert_called_once_with(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ", download=False
        )

    @patch("src.core.ytdlp_client.yt_dlp.YoutubeDL")
    def test_download_error_contract_returns_none(self, youtube_dl):
        youtube_dl_mock(youtube_dl, error=yt_dlp.utils.DownloadError("video unavailable"))

        result = self.make_client().extract_channel_info("@missing")

        self.assertIsNone(result)

    @patch("yt_dlp.YoutubeDL")
    def test_subtitle_contract_prefers_manual_json3_captions(self, youtube_dl):
        youtube_dl_mock(
            youtube_dl,
            {
                "duration": 213,
                "subtitles": {
                    "en": [
                        {"ext": "vtt", "url": "https://example.test/manual.vtt"},
                        {"ext": "json3", "url": "https://example.test/manual.json3"},
                    ]
                },
                "automatic_captions": {
                    "en": [
                        {"ext": "json3", "url": "https://example.test/automatic.json3"}
                    ]
                },
            },
        )
        extractor = TranscriptExtractor(preferred_languages=["en"], max_retries=1)

        with patch.object(
            extractor, "_fetch_subtitle_json3", return_value="manual transcript"
        ) as fetch_subtitle:
            result = extractor._method_2_ytdlp("dQw4w9WgXcQ")

        self.assertEqual(result, ("manual transcript", "3:33"))
        fetch_subtitle.assert_called_once_with("https://example.test/manual.json3")
        options = youtube_dl.call_args.args[0]
        self.assertTrue(options["skip_download"])
        self.assertTrue(options["writesubtitles"])
        self.assertTrue(options["writeautomaticsub"])
        self.assertEqual(options["subtitleslangs"], ["en"])


class YTDLPRuntimeContractTests(unittest.TestCase):
    def test_runtime_options_use_only_the_supported_concurrency_name(self):
        with patch.object(YTDLPClient, "_load_settings", return_value={}):
            options = YTDLPClient().ydl_opts

        self.assertEqual(options["concurrent_fragment_downloads"], 1)
        self.assertNotIn("concurrent_fragments", options)

    def test_requirements_install_the_pinned_official_ejs_and_deno_extras(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("yt-dlp[default,deno,pin-deno]==2026.6.9", requirements)
        self.assertNotIn("yt-dlp==2024.10.7", requirements)

    def test_distroless_targets_receive_the_builder_virtualenv(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn(
            "RUN pip install --no-cache-dir --upgrade pip==26.1.2", dockerfile
        )
        self.assertIn("RUN pip install --no-cache-dir -r requirements.txt", dockerfile)
        self.assertEqual(
            dockerfile.count("COPY --from=builder /app/venv /app/venv"), 2
        )
        self.assertGreaterEqual(
            dockerfile.count('ENV PATH="/app/venv/bin:$PATH"'), 3
        )

    def test_ci_installs_dependencies_and_runs_all_contract_tests(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("python3 -m pip install -r requirements-dev.txt", workflow)
        self.assertIn("python3 -m unittest discover -s tests -v", workflow)


if __name__ == "__main__":
    unittest.main()
