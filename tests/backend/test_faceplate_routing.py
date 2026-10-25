import json
import tempfile
import unittest
from pathlib import Path

from signalbar.faceplate.routing import (
    DEFAULT_GAME_SCENE,
    DEFAULT_HOME_SCENE,
    DEFAULT_VISUAL_THEME,
    DASHBOARD_VISUAL_THEMES,
    GAME_SCENES,
    HOME_SCENES,
    VISUAL_THEMES,
    WEATHER_VISUAL_THEMES,
    FaceplatePreferencesError,
    FaceplatePreferencesStore,
    FaceplateRevisionConflict,
    FaceplateSceneRouter,
)


class FaceplatePreferencesStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "shared" / "preferences.json"
        self.store = FaceplatePreferencesStore(self.path, wall_clock=lambda: 1234.5)

    def tearDown(self):
        self.temporary.cleanup()

    def test_absent_store_has_inert_route_defaults_without_enabling_hardware(self):
        snapshot = self.store.read()

        self.assertEqual(("weather", "dashboard", "native-clock", "artwork", "artwork-dashboard"), HOME_SCENES)
        self.assertEqual(
            ("dashboard", "artwork", "artwork-dashboard", "weather", "player-city"),
            GAME_SCENES,
        )
        self.assertEqual(DEFAULT_HOME_SCENE, snapshot.home_scene)
        self.assertEqual(DEFAULT_GAME_SCENE, snapshot.game_scene)
        self.assertEqual(DEFAULT_VISUAL_THEME, snapshot.visual_theme)
        self.assertEqual("weather-artwork-v2", snapshot.theme_for("weather"))
        self.assertEqual("weather-artwork-v2", snapshot.theme_for("dashboard"))
        self.assertEqual(
            ("integrated", "night-paper-v3", "night-paper", "sun-cut", "winter-loom"),
            VISUAL_THEMES,
        )
        self.assertEqual(0, snapshot.revision)
        self.assertFalse(self.path.exists())
        self.assertNotIn("enabled", snapshot.as_dict())

    def test_real_changes_are_atomic_shared_and_monotonic(self):
        first = self.store.update(home_scene="weather", expected_revision=0)
        unchanged = self.store.update(home_scene="weather", expected_revision=1)
        second_process = FaceplatePreferencesStore(self.path, wall_clock=lambda: 1235.0)
        second = second_process.update(game_scene="dashboard", expected_revision=1)

        self.assertEqual(1, first.revision)
        self.assertEqual(1, unchanged.revision)
        self.assertEqual(2, second.revision)
        self.assertEqual("weather", second.home_scene)
        self.assertEqual("dashboard", second.game_scene)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(2, payload["schema"])
        self.assertEqual(2, payload["revision"])
        self.assertEqual({"home": "weather", "game": "dashboard"}, payload["routes"])
        self.assertEqual("integrated", payload["visual_theme"])
        self.assertEqual({
            "weather": "weather-artwork-v2",
            "dashboard": "weather-artwork-v2",
            "performance": "integrated",
        }, payload["scene_themes"])
        self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_stale_writer_is_rejected(self):
        self.store.update(home_scene="weather", expected_revision=0)

        with self.assertRaises(FaceplateRevisionConflict):
            self.store.update(game_scene="weather", expected_revision=0)

        self.assertEqual(1, self.store.read().revision)
        self.assertEqual("artwork", self.store.read().game_scene)

    def test_context_routes_are_strict_and_independent(self):
        with self.assertRaises(ValueError):
            self.store.update(home_scene="player-city")
        with self.assertRaises(ValueError):
            self.store.update(game_scene="audio_sync")

        snapshot = self.store.update(home_scene="native-clock", game_scene="weather")
        self.assertEqual("native-clock", snapshot.scene_for("home"))
        self.assertEqual("weather", snapshot.scene_for("game"))

    def test_visual_theme_is_revisioned_and_rejects_unknown_values(self):
        snapshot = self.store.update(
            visual_theme="night-paper", expected_revision=0,
        )
        self.assertEqual(1, snapshot.revision)
        self.assertEqual("night-paper", snapshot.visual_theme)
        self.assertEqual("weather-artwork-v2", snapshot.theme_for("weather"))
        self.assertEqual("weather-artwork-v2", snapshot.theme_for("dashboard"))
        self.assertEqual("night-paper", snapshot.theme_for("performance"))
        unchanged = self.store.update(
            visual_theme="night-paper", expected_revision=1,
        )
        self.assertEqual(1, unchanged.revision)
        with self.assertRaises(ValueError):
            self.store.update(visual_theme="premium-neon")

    def test_weather_and_dashboard_offer_only_realistic_v2(self):
        self.assertEqual(("weather-artwork-v2",), WEATHER_VISUAL_THEMES)
        self.assertEqual(WEATHER_VISUAL_THEMES, DASHBOARD_VISUAL_THEMES)
        with self.assertRaises(ValueError):
            self.store.update(scene_kind="weather", scene_theme="integrated")
        with self.assertRaises(ValueError):
            self.store.update(scene_kind="dashboard", scene_theme="night-paper")
        weather = self.store.update(
            scene_kind="weather", scene_theme="weather-artwork-v2",
            expected_revision=0,
        )
        dashboard = self.store.update(
            scene_kind="dashboard", scene_theme="weather-artwork-v2",
            expected_revision=0,
        )
        with self.assertRaises(ValueError):
            self.store.update(scene_kind="performance", scene_theme="sun-cut", expected_revision=0)
        self.assertEqual("weather-artwork-v2", weather.theme_for("weather"))
        self.assertEqual("weather-artwork-v2", dashboard.theme_for("dashboard"))
        with self.assertRaises(ValueError):
            self.store.update(
                scene_kind="performance", scene_theme="weather-artwork-v1",
                expected_revision=1,
            )
        with self.assertRaises(ValueError):
            self.store.update(scene_kind="weather")

    def test_schema_one_global_theme_migrates_only_to_performance(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({
            "schema": 1,
            "revision": 4,
            "routes": {"home": "dashboard", "game": "performance"},
            "visual_theme": "sun-cut",
            "updated_at": 100.0,
        }), encoding="utf-8")

        snapshot = self.store.read()

        self.assertEqual("weather-artwork-v2", snapshot.theme_for("weather"))
        self.assertEqual("weather-artwork-v2", snapshot.theme_for("dashboard"))
        self.assertEqual("sun-cut", snapshot.theme_for("performance"))

    def test_legacy_schema_one_payload_defaults_to_integrated_theme(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({
            "schema": 1,
            "revision": 7,
            "routes": {"home": "weather", "game": "performance"},
            "updated_at": 100.0,
        }), encoding="utf-8")

        snapshot = self.store.read()

        self.assertEqual(7, snapshot.revision)
        self.assertEqual("integrated", snapshot.visual_theme)
        self.assertEqual("weather-artwork-v2", snapshot.theme_for("weather"))
        self.assertEqual("weather-artwork-v2", snapshot.theme_for("dashboard"))

    def test_schema_two_old_weather_and_dashboard_choices_migrate_without_rewrite(self):
        self.path.parent.mkdir(parents=True)
        original = {
            "schema": 2, "revision": 9,
            "routes": {"home": "dashboard", "game": "weather"},
            "visual_theme": "night-paper",
            "scene_themes": {
                "weather": "integrated", "dashboard": "sun-cut",
                "performance": "winter-loom",
            },
            "updated_at": 100.0,
        }
        self.path.write_text(json.dumps(original), encoding="utf-8")

        snapshot = self.store.read()

        self.assertEqual("weather-artwork-v2", snapshot.theme_for("weather"))
        self.assertEqual("weather-artwork-v2", snapshot.theme_for("dashboard"))
        self.assertEqual("winter-loom", snapshot.theme_for("performance"))
        self.assertEqual(original, json.loads(self.path.read_text(encoding="utf-8")))

    def test_corrupt_existing_file_is_not_overwritten_with_revision_zero(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not-json", encoding="utf-8")

        self.assertEqual(0, self.store.read().revision)
        with self.assertRaises(FaceplatePreferencesError):
            self.store.update(home_scene="weather")
        self.assertEqual("not-json", self.path.read_text(encoding="utf-8"))

    def test_unsupported_schema_reads_as_safe_defaults_but_is_not_overwritten(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps({
                "schema": 99,
                "revision": 42,
                "routes": {"home": "weather", "game": "performance"},
            }),
            encoding="utf-8",
        )

        self.assertEqual(0, self.store.read().revision)
        with self.assertRaises(FaceplatePreferencesError):
            self.store.update(game_scene="dashboard")


class FaceplateSceneRouterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        path = Path(self.temporary.name) / "preferences.json"
        self.store = FaceplatePreferencesStore(path, wall_clock=lambda: 1234.5)
        self.router = FaceplateSceneRouter(self.store)

    def tearDown(self):
        self.temporary.cleanup()

    def test_default_home_and_game_routes_keep_effective_scene_until_ready(self):
        home = self.router.reconcile(game_running=False, content_key="clock:10:15")
        self.assertEqual("dashboard", home.scene)
        self.assertEqual("", self.router.status()["effective_scene"])
        self.assertTrue(self.router.commit(home))

        game = self.router.reconcile(game_running=True, content_key="app:620")
        pending = self.router.status()
        self.assertEqual("artwork", pending["desired_scene"])
        self.assertEqual("dashboard", pending["effective_scene"])
        self.assertEqual("pending", pending["preparation"]["state"])
        self.assertTrue(self.router.commit(game))
        self.assertEqual("artwork", self.router.status()["effective_scene"])

    def test_saved_choice_does_not_depend_on_display_reconciliation(self):
        ticket=self.router.reconcile(game_running=False,content_key='existing')
        self.router.commit(ticket)
        self.store.update(home_scene='weather',game_scene='dashboard',expected_revision=0)
        saved=self.router.preference_status()
        self.assertEqual(saved['routes'],{'home':'weather','game':'dashboard'})
        self.assertEqual(saved['preference_revision'],1)
        self.assertEqual(saved['applied_preference_revision'],0)
        self.assertEqual(saved['desired_scene'],'dashboard')
        self.assertEqual(saved['effective_scene'],'dashboard')
        self.assertEqual(saved['generation'],ticket.generation)
        # Merely asking for saved choices never changes delivery authority.
        self.assertEqual(self.router.status()['preference_revision'],0)

    def test_new_generation_supersedes_slow_preparation_latest_wins(self):
        self.store.update(home_scene="weather")
        weather = self.router.reconcile(game_running=False, content_key="weather:rain:1")
        self.assertTrue(self.router.mark_preparing(weather))

        self.store.update(home_scene="dashboard", expected_revision=1)
        performance = self.router.reconcile(game_running=False, content_key="telemetry:v1")

        self.assertGreater(performance.generation, weather.generation)
        self.assertFalse(self.router.commit(weather))
        self.assertTrue(self.router.mark_preparing(performance))
        self.assertTrue(self.router.commit(performance))
        status = self.router.status()
        self.assertEqual("dashboard", status["effective_scene"])
        self.assertEqual(1, status["superseded"])

    def test_content_key_drives_regeneration_but_duplicates_do_not(self):
        first = self.router.reconcile(game_running=False, content_key="weather:1")
        duplicate = self.router.reconcile(game_running=False, content_key="weather:1")
        changed = self.router.reconcile(game_running=False, content_key="weather:2")

        self.assertEqual(first, duplicate)
        self.assertEqual(first.generation + 1, changed.generation)

    def test_current_failure_preserves_previous_effective_scene(self):
        dashboard = self.router.reconcile(game_running=False, content_key="clock:1")
        self.router.commit(dashboard)
        self.store.update(home_scene="weather")
        weather = self.router.reconcile(game_running=False, content_key="weather:offline")

        self.assertTrue(self.router.fail(weather, "weather unavailable"))
        status = self.router.status()
        self.assertEqual("weather", status["desired_scene"])
        self.assertEqual("dashboard", status["effective_scene"])
        self.assertEqual("error", status["preparation"]["state"])
        self.assertEqual("weather unavailable", status["preparation"]["error"])


if __name__ == "__main__":
    unittest.main()
