"""Contracts for the lightweight Decky Pixel Studio artwork worker."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from signalbar.faceplate.artwork_jobs import ArtworkPreparationJobs
from signalbar.faceplate.steamgriddb import SteamGridDBError


class _Library:
    def __init__(self, root):
        self.root = Path(root)

    @staticmethod
    def _cached_asset(appid, asset_id, asset_kind):
        if (appid, asset_id, asset_kind) != (620, 42, "grid"):
            return None
        return {
            "id": 42, "kind": "grid", "animated": False,
            "url": "https://www.steamgriddb.com/example.png",
            "thumb": "https://www.steamgriddb.com/example-thumb.png",
            "width": 512, "height": 512, "author": "test",
        }


class _Process:
    pid = 1234

    @staticmethod
    def poll():
        return 0

    @staticmethod
    def wait(timeout=None):
        return 0


class _Thread:
    def __init__(self, **_kwargs):
        pass

    def start(self):
        pass


class _FailedProcess:
    pid = 4321

    @staticmethod
    def poll():
        return 1

    @staticmethod
    def wait(timeout=None):
        return 1


class FaceplateArtworkJobsTests(unittest.TestCase):
    def test_restart_reconciles_orphaned_active_jobs_but_preserves_ready(self):
        for state in ('queued','running','cancelling','ready'):
            with self.subTest(state=state),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'jobs'/'orphan.progress.json';path.parent.mkdir()
                path.write_text(json.dumps({'state':state,'stage':state,'percent':20}))
                jobs=ArtworkPreparationJobs(_Library(directory),lambda:{'appid':0})
                result=jobs.status()
                self.assertEqual('ready' if state=='ready' else 'failed',result['state'])
                self.assertNotIn(jobs.cancel()['state'],{'queued','running','cancelling'})
                self.assertEqual(result['state'],json.loads(path.read_text())['state'])

    def test_latest_terminal_progress_survives_plugin_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            jobs_root = Path(directory) / "jobs"
            jobs_root.mkdir()
            older = jobs_root / "older.progress.json"
            newest = jobs_root / "newest.progress.json"
            older.write_text(json.dumps({
                "state": "ready", "stage": "ready", "percent": 100,
                "detail": "Old result", "updated_at": 10,
            }), encoding="utf-8")
            newest.write_text(json.dumps({
                "state": "failed", "stage": "decode", "percent": 40,
                "detail": "WebM decoder unavailable", "updated_at": 20,
            }), encoding="utf-8")
            os.utime(older, (10, 10))
            os.utime(newest, (20, 20))

            jobs = ArtworkPreparationJobs(_Library(directory), lambda: {"appid": 0})
            status = jobs.status()

        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["stage"], "decode")
        self.assertIn("decoder unavailable", status["detail"])

    def test_job_uses_clean_system_python_and_never_decky_loader(self):
        observed = {}

        def which(name, path=None):
            return {"python3": "/usr/bin/python3", "nice": "/usr/bin/nice"}.get(name)

        def popen(command, **options):
            observed["command"] = list(command)
            observed["environment"] = dict(options["env"])
            return _Process()

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "LD_PRELOAD": "/tmp/decky-preload.so",
            "LD_LIBRARY_PATH": "/tmp/decky-libs",
            "PYTHONHOME": "/tmp/decky-python",
            "PYTHONPATH": "/tmp/decky-modules",
        }, clear=False), patch(
            "signalbar.faceplate.artwork_jobs.shutil.which", side_effect=which,
        ), patch(
            "signalbar.faceplate.artwork_jobs.subprocess.Popen", side_effect=popen,
        ), patch(
            "signalbar.faceplate.artwork_jobs.threading.Thread", _Thread,
        ):
            jobs = ArtworkPreparationJobs(_Library(directory), lambda: {"appid": 0})
            jobs.start({
                "appid": 620, "asset_id": 42, "asset_kind": "grid",
                "mode": "static", "crop_y": 50, "saturation": 110,
                "brightness": 100, "loop_cleanup": "aggressive",
            })
            request = json.loads(next((Path(directory) / "jobs").glob("*.request.json")).read_text())

        self.assertIn("/usr/bin/python3", observed["command"])
        self.assertNotIn("LD_PRELOAD", observed["environment"])
        self.assertNotIn("PYTHONHOME", observed["environment"])
        self.assertNotIn("PYTHONPATH", observed["environment"])
        self.assertEqual(observed["environment"]["LD_LIBRARY_PATH"], "")
        self.assertEqual(request["loop_cleanup"], "aggressive")

    def test_running_game_rejects_animation_before_process_start(self):
        with tempfile.TemporaryDirectory() as directory:
            jobs = ArtworkPreparationJobs(_Library(directory), lambda: {"appid": 620})
            with self.assertRaisesRegex(SteamGridDBError, "Quit the running game"):
                jobs.start({
                    "appid": 620, "asset_id": 42, "asset_kind": "grid",
                    "mode": "animated",
                })

    def test_static_explicit_preparation_is_allowed_during_a_game(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "signalbar.faceplate.artwork_jobs.shutil.which",
            side_effect=lambda name, path=None: "/usr/bin/python3" if name == "python3" else None,
        ), patch("signalbar.faceplate.artwork_jobs.subprocess.Popen", return_value=_Process()), patch(
            "signalbar.faceplate.artwork_jobs.threading.Thread", _Thread,
        ):
            jobs = ArtworkPreparationJobs(_Library(directory), lambda: {"appid": 620})
            jobs.start({"appid": 620, "asset_id": 42, "asset_kind": "grid", "mode": "static"})
            payload = json.loads(next((Path(directory) / "jobs").glob("*.request.json")).read_text())
            self.assertEqual(payload["mode"], "static")

    def test_animation_cannot_bypass_guard_by_claiming_to_be_static(self):
        with tempfile.TemporaryDirectory() as directory:
            library = _Library(directory)
            original = library._cached_asset(620, 42, "grid")
            library._cached_asset = lambda *_: {**original, "animated": True}
            jobs = ArtworkPreparationJobs(library, lambda: {"appid": 620})
            with self.assertRaisesRegex(SteamGridDBError, "Choose a static"):
                jobs.start({"appid": 620, "asset_id": 42, "asset_kind": "grid", "mode": "static"})

    def test_job_defaults_to_no_loop_cleanup(self):
        observed = {}

        def popen(command, **_options):
            observed["command"] = list(command)
            return _Process()

        with tempfile.TemporaryDirectory() as directory, patch(
            "signalbar.faceplate.artwork_jobs.shutil.which",
            side_effect=lambda name, path=None: "/usr/bin/python3" if name == "python3" else None,
        ), patch(
            "signalbar.faceplate.artwork_jobs.subprocess.Popen", side_effect=popen,
        ), patch(
            "signalbar.faceplate.artwork_jobs.threading.Thread", _Thread,
        ):
            jobs = ArtworkPreparationJobs(_Library(directory), lambda: {"appid": 0})
            jobs.start({
                "appid": 620, "asset_id": 42, "asset_kind": "grid",
                "mode": "static",
            })
            request = json.loads(next(
                (Path(directory) / "jobs").glob("*.request.json")
            ).read_text())

        self.assertEqual(request["loop_cleanup"], "no")

    def test_abnormal_worker_exit_surfaces_decoder_stderr_instead_of_status_one(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            progress = root / "job.progress.json"
            stderr = root / "job.stderr.log"
            progress.write_text(json.dumps({
                "state": "running", "stage": "decode", "percent": 40,
                "detail": "Decoding source frames",
            }), encoding="utf-8")
            stderr.write_text(
                "GStreamer: missing WebM decoder; FFmpeg: invalid data\n",
                encoding="utf-8",
            )
            jobs = ArtworkPreparationJobs(_Library(directory), lambda: {"appid": 0})
            process = _FailedProcess()
            jobs.process = process
            jobs.progress_path = progress
            jobs._monitor(process, progress, stderr)
            result = json.loads(progress.read_text(encoding="utf-8"))
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["stage"], "decode")
        self.assertEqual(result["percent"], 40)
        self.assertIn("missing WebM decoder", result["detail"])
        self.assertNotIn("status 1", result["detail"])


if __name__ == "__main__":
    unittest.main()
