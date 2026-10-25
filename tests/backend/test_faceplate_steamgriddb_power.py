import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
from unittest.mock import patch, sentinel
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from signalbar.faceplate.power_events import parse_line, stray_helpers
from signalbar.faceplate.steamgriddb import (
    MAX_SOURCE_BYTES, SteamGridDBError, SteamGridDBFaceplate, decode_frames,
    _apply_loop_cleanup, _dashboard_pack_frames,
    _cover_dimensions, _crop_cover, _decoder_error, _source_extension,
    _repair_terminal_black_edges, _trim_terminal_decoder_blanks,
)
from signalbar.faceplate import steamgriddb as steamgriddb_module
from signalbar.faceplate.library import installed_games


def compiled_gif():
    from signalbar.faceplate.gif import encode
    return encode(64, 54, [(24, 52, 96)], [bytes(3456)])


class Response:
    def __init__(self, body, headers=None):
        self.body = body
        self.headers = headers or {}
        self.offset = 0
        self.read_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size=-1):
        self.read_sizes.append(size)
        if size < 0:
            size = len(self.body) - self.offset
        chunk = self.body[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


class Opener:
    def __init__(self, body, headers=None):
        self.body = body
        self.headers = headers or {}
        self.requests = []
        self.responses = []

    def open(self, request, timeout=0):
        self.requests.append((request, timeout))
        response = Response(self.body, self.headers)
        self.responses.append(response)
        return response


def download_fixture(payload, extension):
    def download(_url, temporary, progress=None):
        Path(temporary).write_bytes(payload)
        if callable(progress):
            progress(35, "download", "Source downloaded · 1 MiB")
        return extension, len(payload)
    return download


class SteamGridDBAndPowerTests(unittest.TestCase):
    def test_static_compilation_decodes_only_one_frame_even_for_mislabeled_sources(self):
        width, height = _cover_dimensions(512, 512)
        completed = type("Completed", (), {
            "returncode": 0, "stdout": bytes((20, 40, 80)) * width * height * 3,
            "stderr": b"",
        })()
        for decoder in ("gst-launch-1.0", "ffmpeg"):
            with self.subTest(decoder=decoder), patch.object(
                steamgriddb_module.shutil, "which",
                side_effect=lambda name: f"/usr/bin/{name}" if name == decoder else None,
            ), patch.object(steamgriddb_module.subprocess, "run", return_value=completed) as run:
                frames = decode_frames("/tmp/source.png", source_width=512, source_height=512,
                                       animation_style="static")
                self.assertEqual(len(frames), 1)
                command = run.call_args.args[0]
                if decoder == "ffmpeg":
                    self.assertEqual(command[command.index("-frames:v") + 1], "1")
                else:
                    self.assertIn("eos-after=2", command)

    def test_api_key_validation_states_never_expose_the_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory, clock=lambda: 1234.5)
            detected = library.set_api_key("personal-key-1234567890")
            self.assertEqual(detected["validation_state"], "detected_unverified")
            self.assertNotIn("api_key", detected)
            with patch.object(library, "_json_request", return_value={"success": True}):
                validated = library.validate_api_key()
            self.assertEqual(validated["validation_state"], "validated")
            self.assertEqual(validated["validated_at"], 1234.5)
            library.set_api_key("replacement-key-123456789")
            self.assertEqual(library.status()["validation_state"], "detected_unverified")

    def test_api_key_validation_distinguishes_rejection_and_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory, clock=lambda: 77)
            library.set_api_key("personal-key-1234567890")
            with patch.object(library, "_json_request", side_effect=SteamGridDBError(
                "rejected", "unauthorized",
            )):
                self.assertEqual(library.validate_api_key()["validation_state"], "rejected")
            with patch.object(library, "_json_request", side_effect=SteamGridDBError(
                "offline", "offline",
            )):
                offline = library.validate_api_key()
            self.assertEqual(offline["validation_state"], "offline")
            self.assertEqual(offline["validation_checked_at"], 77)
            self.assertEqual(offline["validation_code"], "offline")
            self.assertEqual(offline["validation_detail"], "offline")

    def test_api_key_validation_exposes_safe_transport_diagnostics(self):
        cases = (
            (URLError(socket.gaierror("name lookup failed")), "dns",
             "hostname could not be resolved"),
            (HTTPError("https://www.steamgriddb.com/api/v2/games/steam/620",
                       429, "rate limited", {}, None),
             "rate_limited", "HTTP 429"),
        )
        for failure, code, message in cases:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                class FailingOpener:
                    def open(self, _request, timeout=0):
                        raise failure

                library = SteamGridDBFaceplate(directory, opener=FailingOpener())
                library.set_api_key("personal-key-1234567890")
                status = library.validate_api_key()
                self.assertEqual(status["validation_state"], "offline")
                self.assertEqual(status["validation_code"], code)
                self.assertIn(message, status["validation_detail"])
                self.assertNotIn("personal-key", json.dumps(status))

    def test_api_key_validation_retries_with_verified_steamos_system_ca(self):
        missing_issuer = URLError(ssl.SSLCertVerificationError("missing issuer"))

        class CertificateFailingOpener:
            def open(self, _request, timeout=0):
                raise missing_issuer

        fallback = Opener(b'{"success":true,"data":{"id":620}}')
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(
                directory, opener=CertificateFailingOpener(), clock=lambda: 88,
            )
            library.set_api_key("personal-key-1234567890")
            with patch.object(
                steamgriddb_module, "SYSTEM_CA_BUNDLES", ("/etc/ssl/cert.pem",),
            ), patch.object(
                steamgriddb_module.os.path, "isfile", return_value=True,
            ), patch.object(
                steamgriddb_module.os.path, "realpath", return_value="/etc/ssl/cert.pem",
            ), patch.object(
                steamgriddb_module.ssl, "create_default_context",
                return_value=sentinel.verified,
            ) as context, patch.object(
                steamgriddb_module, "HTTPSHandler", return_value=sentinel.https_handler,
            ) as handler, patch.object(
                steamgriddb_module, "build_opener", return_value=fallback,
            ) as build:
                status = library.validate_api_key()
        self.assertEqual(status["validation_state"], "validated")
        self.assertEqual(status["validated_at"], 88)
        context.assert_called_once_with(cafile="/etc/ssl/cert.pem")
        handler.assert_called_once_with(context=sentinel.verified)
        build.assert_called_once()

    def test_webm_magic_is_supported_for_animated_steamgriddb_sources(self):
        self.assertEqual(_source_extension(b"\x1a\x45\xdf\xa3" + b"webm"), "webm")

    def test_source_limit_is_128_mib_and_download_is_streamed(self):
        self.assertEqual(MAX_SOURCE_BYTES, 128 * 1024 * 1024)
        body = b"\x1a\x45\xdf\xa3" + b"webm-payload"
        opener = Opener(body, {"Content-Length": str(len(body))})
        progress = []
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "source.tmp"
            library = SteamGridDBFaceplate(directory, opener=opener)
            with patch.object(steamgriddb_module, "DOWNLOAD_CHUNK_BYTES", 4):
                extension, size = library._download_to(
                    "https://cdn2.steamgriddb.com/hero/example.webm",
                    target,
                    progress=lambda *event: progress.append(event),
                )
            payload = target.read_bytes()
        self.assertEqual(extension, "webm")
        self.assertEqual(size, len(body))
        self.assertEqual(payload, body)
        self.assertTrue(all(size == 4 for size in opener.responses[0].read_sizes[:-1]))
        self.assertEqual(progress[-1][0], 35)

    def test_oversized_source_is_rejected_from_content_length_before_writing(self):
        opener = Opener(b"small", {"Content-Length": str(MAX_SOURCE_BYTES + 1)})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "source.tmp"
            library = SteamGridDBFaceplate(directory, opener=opener)
            with self.assertRaisesRegex(SteamGridDBError, "128 MiB"):
                library._download_to(
                    "https://cdn2.steamgriddb.com/hero/example.webm", target,
                )
            self.assertFalse(target.exists())

    def test_installed_games_are_read_from_all_local_steam_libraries(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            steam = home / ".local/share/Steam"
            extra = home / "Games/SteamLibrary"
            (steam / "steamapps").mkdir(parents=True)
            (extra / "steamapps").mkdir(parents=True)
            (steam / "steamapps/libraryfolders.vdf").write_text(
                f'"libraryfolders"\n{{\n "1"\n {{\n  "path" "{extra}"\n }}\n}}\n',
                encoding="utf-8",
            )
            (steam / "steamapps/appmanifest_620.acf").write_text(
                '"AppState"\n{\n "appid" "620"\n "name" "Portal 2"\n}\n',
                encoding="utf-8",
            )
            (extra / "steamapps/appmanifest_123.acf").write_text(
                '"AppState"\n{\n "appid" "123"\n "name" "Another Game"\n}\n',
                encoding="utf-8",
            )
            self.assertEqual(installed_games(home), [
                {"appid": 123, "name": "Another Game"},
                {"appid": 620, "name": "Portal 2"},
            ])

    def test_logind_parser_distinguishes_start_and_end(self):
        self.assertEqual(parse_line("PrepareForSleep (true,)"), ("sleep", True))
        self.assertEqual(parse_line("PrepareForSleep (false,)"), ("sleep", False))
        self.assertEqual(parse_line("PrepareForShutdownWithMetadata (true,)"),
                         ("shutdown", True))
        self.assertIsNone(parse_line("Unrelated (true,)"))

    def test_stray_helper_scan_is_scoped_to_our_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            own = root / "101"
            other = root / "102"
            own.mkdir()
            other.mkdir()
            (own / "cmdline").write_bytes(b"gabecubeaura-faceplate-login1\0monitor\0")
            (other / "cmdline").write_bytes(b"some-other-monitor\0")
            uid = os.stat(own).st_uid
            self.assertEqual(stray_helpers(str(root), uid=uid), [101])

    def test_personal_key_is_private_and_search_returns_square_choices(self):
        payload = json.dumps({"success": True, "data": [{
            "id": 77, "score": 42, "style": "alternate",
            "url": "https://cdn2.steamgriddb.com/grid/example.webp",
            "thumb": "https://cdn2.steamgriddb.com/thumb/example.webm",
            "type": "animated", "author": {"name": "Artist"},
            "width": 512, "height": 512,
        }]}).encode("utf-8")
        opener = Opener(payload)
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory, opener=opener)
            library.set_api_key("personal-key-1234567890")
            results = library.search(620, "animated")
            mode = (Path(directory) / "auth.json").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)
        self.assertEqual(results[0]["id"], 77)
        self.assertTrue(results[0]["animated"])
        self.assertEqual(results[0]["kind"], "grid")
        self.assertEqual((results[0]["width"], results[0]["height"]), (512, 512))
        self.assertEqual(opener.requests[0][0].get_header("Authorization"),
                         "Bearer personal-key-1234567890")

    def test_animated_any_searches_grid_and_hero_formats(self):
        payload = json.dumps({"success": True, "data": [{
            "id": 91, "score": 8,
            "url": "https://cdn2.steamgriddb.com/grid/animated.webp",
            "thumb": "https://cdn2.steamgriddb.com/thumb/animated.webm",
            "type": "animated", "width": 920, "height": 430,
        }]}).encode("utf-8")
        opener = Opener(payload)
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory, opener=opener)
            library.set_api_key("personal-key-1234567890")
            results = library.search(620, "animated_any")
        self.assertEqual({asset["kind"] for asset in results}, {"grid", "hero"})
        self.assertEqual(len(opener.requests), 2)
        grid_url, hero_url = (request.full_url for request, _timeout in opener.requests)
        self.assertIn("/grids/steam/620?", grid_url)
        self.assertIn("/heroes/steam/620?", hero_url)
        self.assertIn("600x900", parse_qs(urlsplit(grid_url).query)["dimensions"][0])
        self.assertNotIn("512x512", parse_qs(urlsplit(grid_url).query)["dimensions"][0])
        self.assertIn("1920x620", parse_qs(urlsplit(hero_url).query)["dimensions"][0])
        self.assertEqual(parse_qs(urlsplit(grid_url).query)["types"], ["animated"])
        self.assertEqual(parse_qs(urlsplit(grid_url).query)["limit"], ["12"])
        self.assertEqual(parse_qs(urlsplit(hero_url).query)["limit"], ["12"])
        self.assertEqual(results[0]["kind"], "hero")

    def test_legacy_square_animation_default_migrates_to_all_useful_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            Path(directory, "preferences.json").write_text(
                json.dumps({"schema": 1, "preference": "animated"}), encoding="utf-8",
            )
            self.assertEqual(library.preference(), "animated_any")

    def test_cover_crop_preserves_wide_and_portrait_aspect_ratios(self):
        self.assertEqual(_cover_dimensions(920, 430), (116, 54))
        self.assertEqual(_cover_dimensions(600, 900), (64, 96))
        wide = bytes((index % 256 for index in range(116 * 54 * 3)))
        portrait = bytes((index % 256 for index in range(64 * 96 * 3)))
        self.assertEqual(len(_crop_cover(wide, 116, 54, 50)), 64 * 54 * 3)
        self.assertEqual(len(_crop_cover(portrait, 64, 96, 50)), 64 * 54 * 3)

    def test_cover_decode_width_is_rgb_stride_aligned(self):
        width, height = _cover_dimensions(1919, 620)
        self.assertEqual(width % 4, 0)
        self.assertEqual(height, 54)

    def test_short_abrupt_decoder_black_tail_is_removed(self):
        visible = bytes((32, 96, 180)) * 64 * 54
        black = bytes(64 * 54 * 3)
        self.assertEqual(
            _trim_terminal_decoder_blanks([visible, visible, black, black]),
            [visible, visible],
        )

    def test_authored_dark_endings_are_preserved(self):
        black = bytes(64 * 54 * 3)
        dim = bytes((4, 5, 6)) * 64 * 54
        visible = bytes((32, 96, 180)) * 64 * 54
        self.assertEqual(
            _trim_terminal_decoder_blanks([dim, black]),
            [dim, black],
        )
        self.assertEqual(
            _trim_terminal_decoder_blanks([visible] + [black] * 4),
            [visible] + [black] * 4,
        )

    def test_final_decoder_black_edge_is_restored_from_previous_frame(self):
        row = bytes((32, 96, 180)) * 64
        visible = row * 54
        damaged = bytes(64 * 3) + visible[64 * 3:]
        repaired = _repair_terminal_black_edges([visible, damaged])
        self.assertEqual(repaired, [visible, visible])

    def test_authored_black_edge_is_not_changed(self):
        black_row = bytes(64 * 3)
        colour_rows = bytes((32, 96, 180)) * 64 * 53
        frame = black_row + colour_rows
        self.assertEqual(_repair_terminal_black_edges([frame, frame]), [frame, frame])

    def test_medium_cleanup_finds_best_join_within_last_half_second(self):
        first = bytes((20, 80, 180)) * 64 * 54
        other = bytes((180, 40, 20)) * 64 * 54
        tail = bytes((60, 20, 80)) * 64 * 54
        frames = [first, other, other, first, tail]
        cleaned, details = _apply_loop_cleanup(frames, "medium")
        self.assertEqual(cleaned, frames[:-1])
        self.assertEqual(details["loop_cleanup"], "medium")
        self.assertEqual(details["loop_trimmed_frames"], 1)
        self.assertEqual(details["loop_trimmed_ms"], 100)

    def test_aggressive_cleanup_searches_four_to_ten_terminal_frames(self):
        first = bytes((20, 80, 180)) * 64 * 54
        other = bytes((180, 40, 20)) * 64 * 54
        frames = [first, other, other, first] + [other] * 6
        cleaned, details = _apply_loop_cleanup(frames, "aggressive")
        self.assertEqual(cleaned, frames[:-6])
        self.assertEqual(cleaned[-1], first)
        self.assertEqual(details["loop_trimmed_frames"], 6)
        self.assertEqual(details["loop_trimmed_ms"], 600)

    def test_no_cleanup_keeps_every_timing_slot_and_restores_decoder_blank(self):
        visible = bytes((32, 96, 180)) * 64 * 54
        black = bytes(64 * 54 * 3)
        source = [visible, visible, black]
        cleaned, details = _apply_loop_cleanup(source, "no")
        self.assertEqual(cleaned, [visible, visible, visible])
        self.assertEqual(len(cleaned), len(source))
        self.assertEqual(details["loop_cleanup"], "no")
        self.assertEqual(details["loop_trimmed_frames"], 0)

    def test_unknown_cleanup_level_falls_back_to_no_cleanup(self):
        visible = bytes((32, 96, 180)) * 64 * 54
        black = bytes(64 * 54 * 3)
        source = [visible, visible, black]
        cleaned, details = _apply_loop_cleanup(source, "maximum")
        self.assertEqual(cleaned, [visible, visible, visible])
        self.assertEqual(len(cleaned), len(source))
        self.assertEqual(details["loop_cleanup"], "no")

    def test_soft_cleanup_does_not_encode_a_terminal_black_flash(self):
        width, height = _cover_dimensions(920, 430)
        visible = bytes((32, 96, 180)) * width * height
        black = bytes(width * height * 3)
        completed = type("Completed", (), {
            "returncode": 0, "stdout": visible + visible + black, "stderr": b"",
        })()
        with patch.object(
            steamgriddb_module.shutil, "which",
            side_effect=lambda name: "/usr/bin/gst-launch-1.0" if name == "gst-launch-1.0" else None,
        ), patch.object(steamgriddb_module.subprocess, "run", return_value=completed):
            frames = decode_frames(
                "/tmp/source.webm", source_width=920, source_height=430,
                loop_cleanup="soft",
            )
        self.assertEqual(len(frames), 2)
        self.assertTrue(all(any(frame) for frame in frames))

    def test_pan_uses_a_seamless_ping_pong_path_without_short_rows(self):
        width, height = _cover_dimensions(920, 430)
        raw = bytes(
            channel
            for _y in range(height)
            for x in range(width)
            for channel in (max(1, x), 30, 80)
        )
        completed = type("Completed", (), {
            "returncode": 0, "stdout": raw, "stderr": b"",
        })()
        with patch.object(
            steamgriddb_module.shutil, "which",
            side_effect=lambda name: "/usr/bin/gst-launch-1.0" if name == "gst-launch-1.0" else None,
        ), patch.object(steamgriddb_module.subprocess, "run", return_value=completed):
            frames = decode_frames(
                "/tmp/source.png", source_width=920, source_height=430,
                animation_style="pan",
            )
        self.assertEqual(len(frames), 80)
        self.assertTrue(all(len(frame) == 64 * 54 * 3 for frame in frames))
        self.assertEqual(frames[0], frames[-1])
        self.assertNotEqual(frames[0], frames[40])
        self.assertTrue(all(any(frame[:64 * 3]) for frame in frames))

    def test_webm_decoder_falls_back_to_ffmpeg_with_actionable_errors(self):
        width, height = _cover_dimensions(920, 430)
        failed = type("Completed", (), {
            "returncode": 1, "stdout": b"", "stderr": b"missing WebM decoder\n",
        })()
        succeeded = type("Completed", (), {
            "returncode": 0, "stdout": bytes((20, 40, 80)) * width * height,
            "stderr": b"",
        })()
        with patch.object(
            steamgriddb_module.shutil, "which",
            side_effect=lambda name: f"/usr/bin/{name}" if name in {"gst-launch-1.0", "ffmpeg"} else None,
        ), patch.object(
            steamgriddb_module.subprocess, "run", side_effect=(failed, succeeded),
        ) as run:
            frames = decode_frames(
                "/tmp/source.webm", source_width=920, source_height=430,
            )
        self.assertEqual(len(frames), 1)
        self.assertEqual(run.call_count, 2)

    def test_webm_decoder_retries_ffmpeg_with_generated_timestamps(self):
        width, height = _cover_dimensions(1920, 620)
        failed = type("Completed", (), {
            "returncode": 1, "stdout": b"", "stderr": b"no packets\n",
        })()
        succeeded = type("Completed", (), {
            "returncode": 0, "stdout": bytes((20, 40, 80)) * width * height,
            "stderr": b"",
        })()
        with patch.object(
            steamgriddb_module.shutil, "which",
            side_effect=lambda name: f"/usr/bin/{name}" if name in {"gst-launch-1.0", "ffmpeg"} else None,
        ), patch.object(
            steamgriddb_module.subprocess, "run",
            side_effect=(failed, failed, succeeded),
        ) as run:
            frames = decode_frames(
                "/tmp/source.webm", source_width=1920, source_height=620,
            )
        self.assertEqual(len(frames), 1)
        self.assertEqual(run.call_count, 3)
        recovery = run.call_args_list[2].args[0]
        self.assertIn("+genpts+discardcorrupt", recovery)
        self.assertIn("0:v:0", recovery)

    def test_decoder_error_keeps_codec_cause_instead_of_generic_summary(self):
        stderr = (
            b"Decoder (codec av1) not found for input stream #0:0\n"
            b"Nothing was written into output file, because a stream received no packets.\n"
        )
        self.assertEqual(
            _decoder_error(stderr),
            "Decoder (codec av1) not found for input stream #0:0",
        )

    def test_animated_preparation_falls_back_to_optimized_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            asset = {
                "id": 91, "score": 1, "style": "alternate",
                "url": "https://cdn2.steamgriddb.com/hero/original.webm",
                "thumb": "https://cdn2.steamgriddb.com/thumb/preview.webm",
                "animated": True, "author": "Artist", "kind": "hero",
                "width": 1920, "height": 620,
            }
            downloads = []

            def download(url, temporary, progress=None):
                downloads.append(url)
                Path(temporary).write_bytes(b"\x1a\x45\xdf\xa3webm")
                if callable(progress):
                    progress(35, "download", "Source downloaded · 1 MiB")
                return "webm", 12

            compiled = (
                compiled_gif()
            )
            progress = []
            with patch.object(library, "_download_to", side_effect=download), patch(
                "signalbar.faceplate.steamgriddb.compile_source",
                side_effect=(SteamGridDBError("AV1 decoder unavailable"),
                             (compiled, 0.20, 24)),
            ):
                prepared = library.prepare_choice(
                    620, asset, "animated",
                    progress=lambda *event: progress.append(event),
                )
        self.assertEqual(downloads, [asset["url"], asset["thumb"]])
        self.assertEqual(prepared["source_variant"], "optimized_preview")
        self.assertEqual(prepared["frames"], 24)
        self.assertTrue(any(stage == "fallback" for _percent, stage, _detail in progress))

    def test_prepared_manifest_records_loop_cleanup_result(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            asset = {
                "id": 92, "score": 1, "style": "alternate",
                "url": "https://cdn2.steamgriddb.com/hero/loop.webm",
                "thumb": "https://cdn2.steamgriddb.com/thumb/loop.webm",
                "animated": True, "author": "Artist", "kind": "hero",
                "width": 1920, "height": 620,
            }
            compiled = (
                compiled_gif()
            )

            def compile_with_stats(_path, **options):
                options["cleanup_stats"].update({
                    "loop_cleanup": "aggressive", "loop_original_frames": 74,
                    "loop_trimmed_frames": 6, "loop_trimmed_ms": 600,
                })
                return compiled, 0.20, 68

            with patch.object(
                library, "_download_to",
                side_effect=download_fixture(b"\x1a\x45\xdf\xa3webm", "webm"),
            ), patch(
                "signalbar.faceplate.steamgriddb.compile_source",
                side_effect=compile_with_stats,
            ):
                prepared = library.prepare_choice(
                    620, asset, "animated", loop_cleanup="aggressive",
                )
        self.assertEqual(prepared["loop_cleanup"], "aggressive")
        self.assertEqual(prepared["loop_original_frames"], 74)
        self.assertEqual(prepared["loop_trimmed_frames"], 6)
        self.assertEqual(prepared["loop_trimmed_ms"], 600)
        self.assertEqual(prepared["frames"], 68)

    def test_selection_compiles_once_and_is_reusable_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            library._results[620] = {77: {
                "id": 77, "score": 1, "style": "alternate",
                "url": "https://cdn2.steamgriddb.com/grid/example.png",
                "thumb": "https://cdn2.steamgriddb.com/thumb/example.png",
                "animated": False, "author": "Artist", "kind": "hero",
                "width": 1920, "height": 620,
            }}
            png = b"\x89PNG\r\n\x1a\n" + b"source"
            gif = compiled_gif()
            with patch.object(library, "_download_to", side_effect=download_fixture(png, "png")), patch(
                "signalbar.faceplate.steamgriddb.compile_source",
                return_value=(gif, 0.25, 1),
            ) as compile_mock:
                selected = library.select(620, 77, crop_y=70, saturation=125)
            cached = library.selected(620)
            source = library.selected_source(620)
        self.assertEqual(selected["crop_y"], 70)
        self.assertEqual(selected["crop_axis"], "horizontal")
        self.assertEqual(selected["asset_kind"], "hero")
        self.assertEqual(selected["saturation"], 125)
        self.assertEqual(compile_mock.call_count, 1)
        self.assertEqual(compile_mock.call_args.kwargs["source_width"], 1920)
        self.assertEqual(compile_mock.call_args.kwargs["source_height"], 620)
        self.assertEqual(cached[0], gif)
        self.assertEqual(source.name, "source.png")

    def test_preparation_does_not_replace_active_art_until_explicit_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            asset = {
                "id": 88, "score": 1, "style": "alternate",
                "url": "https://cdn2.steamgriddb.com/hero/example.png",
                "thumb": "https://cdn2.steamgriddb.com/thumb/example.png",
                "animated": False, "author": "Artist", "kind": "hero",
                "width": 1920, "height": 620,
            }
            png = b"\x89PNG\r\n\x1a\nsource"
            gif = compiled_gif()
            progress = []
            with patch.object(library, "_download_to", side_effect=download_fixture(png, "png")), patch(
                "signalbar.faceplate.steamgriddb.compile_source",
                return_value=(gif, 0.25, 80),
            ) as compile_mock:
                prepared = library.prepare_choice(
                    620, asset, "pan", progress=lambda *event: progress.append(event),
                )
            self.assertIsNone(library.selected(620))
            self.assertEqual(prepared["animation_style"], "pan")
            self.assertEqual(prepared["frames"], 80)
            self.assertEqual(compile_mock.call_args.kwargs["animation_style"], "pan")
            self.assertEqual(
                progress,
                [
                    (8, "download", "Downloading source artwork"),
                    (35, "download", "Source downloaded · 1 MiB"),
                    (40, "decode", "Decoding source frames"),
                    (94, "validate", "Validating hardware GIF"),
                    (100, "ready", "Ready to activate"),
                ],
            )
            activated = library.activate_prepared(620, "pan")
            self.assertEqual(activated["mode"], "pan")
            self.assertEqual(library.selected(620)[0], gif)

    def test_explicit_preparation_persists_a_small_dashboard_background_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            asset = {
                "id": 89, "score": 1, "style": "alternate",
                "url": "https://cdn2.steamgriddb.com/hero/example.png",
                "thumb": "https://cdn2.steamgriddb.com/thumb/example.png",
                "animated": False, "author": "Artist", "kind": "hero",
                "width": 1920, "height": 620,
            }
            png = b"\x89PNG\r\n\x1a\nsource"
            compiled = compiled_gif()
            frames = [bytes((index * 10, 30, 80)) * (64 * 54) for index in range(1, 7)]
            with patch.object(
                library, "_download_to", side_effect=download_fixture(png, "png"),
            ), patch(
                "signalbar.faceplate.steamgriddb.compile_source",
                return_value=(compiled, 0.25, 60, frames),
            ):
                prepared = library.prepare_choice(
                    620, asset, "animated", crop_x=35,
                    dashboard_treatment="palette-echo",
                    dashboard_compression="fine",
                    dashboard_clock_size="compact",
                    dashboard_show_battery=False,
                )
            library.activate_prepared(620, "animated")
            pack = library.selected_dashboard_pack(620)
        self.assertEqual(6, prepared["dashboard_pack_frames"])
        self.assertEqual(35, prepared["crop_x"])
        self.assertEqual("palette-echo", prepared["dashboard_treatment"])
        self.assertEqual("fine", prepared["dashboard_compression"])
        self.assertEqual("compact", prepared["dashboard_clock_size"])
        self.assertFalse(prepared["dashboard_show_battery"])
        self.assertEqual(tuple(frames), pack[0])

    def test_logo_anchors_resolve_dashboard_exclusions_during_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            asset = {
                "id": 89, "score": 1, "style": "alternate",
                "url": "https://cdn2.steamgriddb.com/hero/example.png",
                "thumb": "https://cdn2.steamgriddb.com/thumb/example.png",
                "animated": False, "author": "Artist", "kind": "hero",
                "width": 1920, "height": 620,
            }
            compiled = compiled_gif()
            frame = bytes((20, 40, 80)) * (64 * 54)
            with patch.object(
                library, "_download_to", side_effect=download_fixture(b"source", "png"),
            ), patch(
                "signalbar.faceplate.steamgriddb.compile_source",
                return_value=(compiled, 0.25, 1, [frame]),
            ):
                top = library.prepare_choice(
                    620, asset, "static", logo_position="top",
                    dashboard_show_clock=True,
                )
                bottom = library.prepare_choice(
                    620, asset, "static", logo_position="bottom_rail",
                    dashboard_show_session=True, dashboard_show_battery=True,
                )
        self.assertFalse(top["dashboard_show_clock"])
        self.assertFalse(bottom["dashboard_show_status_rail"])
        self.assertFalse(bottom["dashboard_show_session"])
        self.assertFalse(bottom["dashboard_show_battery"])

    def test_dashboard_background_pack_keeps_every_prepared_frame(self):
        source_frames = [
            bytes((index, 30, 80)) * (64 * 54) for index in range(80)
        ]
        sampled = _dashboard_pack_frames(source_frames)
        self.assertEqual(source_frames, sampled)

        with tempfile.TemporaryDirectory() as directory:
            library = SteamGridDBFaceplate(directory)
            asset = {
                "id": 90, "score": 1, "style": "alternate",
                "url": "https://cdn2.steamgriddb.com/hero/example.png",
                "thumb": "https://cdn2.steamgriddb.com/thumb/example.png",
                "animated": True, "author": "Artist", "kind": "hero",
                "width": 1920, "height": 620,
            }
            png = b"\x89PNG\r\n\x1a\nsource"
            compiled = compiled_gif()
            with patch.object(
                library, "_download_to", side_effect=download_fixture(png, "png"),
            ), patch(
                "signalbar.faceplate.steamgriddb.compile_source",
                return_value=(compiled, 0.25, 80, sampled),
            ):
                prepared = library.prepare_choice(620, asset, "animated")
            library.activate_prepared(620, "animated")
            pack = library.selected_dashboard_pack(620)
        self.assertEqual(80, prepared["dashboard_pack_frames"])
        self.assertEqual(80, len(pack[0]))


if __name__ == "__main__":
    unittest.main()
