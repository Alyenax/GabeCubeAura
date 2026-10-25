"""Original-image provenance, bounded reduction and exclusive routing."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from signalbar.arbiter import Arbiter
from signalbar.backend import Engine
from signalbar.faceplate.source_projection import (
    background_key, cache_key, load_source, project_backgrounds, saturate_colours, validate_frame,
)
from signalbar.faceplate.weather_artwork import _backgrounds, _preset
from signalbar.models import GameState, ProviderOutput
from signalbar.providers.faceplate_extension import BLACK, FaceplateExtension
from signalbar.settings import SettingsStore


def frame(pixel):
    return bytes(c for y in range(54) for x in range(64) for c in pixel(x, y))


def wait_ready(provider, phase='ready'):
    with provider.condition:
        ready = provider.condition.wait_for(lambda: provider.phase == phase, timeout=5)
    if not ready:
        raise AssertionError(provider.status())


class ProjectionTests(unittest.TestCase):
    def test_uniform_source_keeps_exact_rgb_and_black_without_boost(self):
        for colour in ((255, 0, 0), (12, 30, 94), (0, 0, 0), (255, 255, 255)):
            for mapping in ('bottom', 'whole'):
                self.assertEqual(project_backgrounds((bytes(colour) * 3456,), mapping), [colour] * 17)

    def test_bottom_uses_eight_original_rows_not_dashboard_footer(self):
        raw = frame(lambda x, y: (0, 0, 255) if y >= 46 else (255, 0, 0))
        self.assertEqual(project_backgrounds((raw,)), [(0, 0, 255)] * 17)
        self.assertEqual(project_backgrounds((raw,), 'whole'), [(217, 0, 38)] * 17)

    def test_temporal_average_is_stable_over_full_source_cycle(self):
        a = bytes((255, 0, 0)) * 3456
        b = bytes((0, 0, 255)) * 3456
        self.assertEqual(project_backgrounds((a, b)), [(128, 0, 128)] * 17)
        self.assertEqual(project_backgrounds((a, b)), project_backgrounds((a, b, a, b)))

    def test_fractional_bins_cover_each_column_exactly(self):
        for x in range(64):
            raw = frame(lambda col, y: (255, 0, 0) if col == x else (0, 0, 0))
            actual = project_backgrounds((raw,))
            expected = []
            for led in range(17):
                overlap = max(0, min((led + 1) * 64, (x + 1) * 17) - max(led * 64, x * 17))
                expected.append(((255 * overlap + 32) // 64, 0, 0))
            self.assertEqual(actual, expected)

    def test_rotation_changes_both_source_edge_and_horizontal_order_once(self):
        raw = frame(lambda x, y: (x * 4, y * 4, 0))
        explicit = frame(lambda x, y: ((63 - x) * 4, (53 - y) * 4, 0))
        for mapping in ('bottom', 'whole'):
            self.assertEqual(project_backgrounds((raw,), mapping, True), project_backgrounds((explicit,), mapping))

    def test_rejects_unbounded_or_non_native_sources(self):
        for frames, mapping in (((), 'bottom'), ((b'bad',), 'whole'), ((b'',) * 81, 'bottom'), ((b'',), 'bad')):
            with self.assertRaises(ValueError): project_backgrounds(frames, mapping)
        for colours in ([], [[0, 0, 256]] * 17, [[True, 0, 0]] * 17, [[1.2, 0, 0]] * 17):
            with self.assertRaises(ValueError): validate_frame(colours)

    def test_pack_hash_size_root_and_symlink_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'artwork-dashboard.rgb'
            raw = bytes((15, 35, 75)) * 3456; path.write_bytes(raw)
            source = dict(kind='artwork', root=str(root), path=str(path), frames=1,
                          sha256=hashlib.sha256(raw).hexdigest())
            self.assertEqual(load_source(source), (raw,))
            for changed in ({'sha256': 'wrong'}, {'frames': 81}, {'frames': 2}, {'root': str(root / 'missing')}, {'path': str(root / 'dashboard.gif')}):
                with self.assertRaises((ValueError, OSError)): load_source({**source, **changed})
            child = root / 'outside'; child.mkdir()
            with self.assertRaises(ValueError): load_source({**source, 'root': str(child)})
            alias = child / 'artwork-dashboard.rgb'; alias.symlink_to(path)
            with self.assertRaises(ValueError): load_source({**source, 'path': str(alias)})

    def test_weather_uses_exact_selected_raw_pack_not_composed_overlay(self):
        theme = 'weather-artwork-v2'
        # Use a real catalogue entry, not an invented scene identifier.
        from signalbar.faceplate.weather_artwork import load_catalog
        preset = next(p['id'] for p in load_catalog(theme)['presets'] if p['condition'] == 'rain')
        metadata = _preset(preset, theme)
        source = dict(kind='weather', theme=theme, preset_id=preset, sha256=metadata['background_raw_sha256'])
        self.assertEqual(load_source(source), _backgrounds(theme, preset))
        with self.assertRaises(ValueError): load_source({**source, 'sha256': 'changed'})

    def test_overlay_and_game_identity_never_rekey_same_source(self):
        source = {'kind': 'weather', 'sha256': 'source', 'asset': 'dashboard-12:00', 'context': 'home', 'appid': 0}
        a = cache_key(source, 'bottom', False)
        self.assertEqual(a, cache_key({**source, 'asset': 'dashboard-12:01', 'appid': 5, 'context': 'game', 'delivery_signature': 'new'}, 'bottom', False))
        self.assertNotEqual(a, cache_key(source, 'whole', False))
        self.assertNotEqual(a, cache_key(source, 'bottom', True))
        self.assertNotEqual(a, cache_key({**source, 'sha256': 'another'}, 'bottom', False))
        self.assertEqual(a, cache_key({**source, 'background_key': 'another-route', 'background_generation': 80}, 'bottom', False))

    def test_upstream_background_identity_excludes_all_dashboard_facts(self):
        weather = dict(kind='dashboard', visual_theme='weather-artwork-v2', condition='rain', variant=0, phase='day')
        artwork = dict(kind='artwork-dashboard', appid=620, source='hero')
        for payload in (weather, artwork):
            original = background_key(payload, 'home', 0, 'rgb-pack')
            overlays = dict(display_at='2030-01-01T12:35:00', temperature_c=99, unit='fahrenheit',
                            session_minutes=91, battery={'percent': 1}, status={'recording': True},
                            countdown={'remaining_minutes': 2}, bottom_mode='cpu_gpu', cpu_load=80,
                            gpu_load=99, precipitation_probability=100, city='Other',
                            next_hour={'temperature_c': -4}, today={'morning_c': 4, 'afternoon_c': 28})
            self.assertEqual(original, background_key({**payload, **overlays}, 'home', 0, 'rgb-pack'))
            self.assertNotEqual(original, background_key(payload, 'game', 620, 'rgb-pack'))
            self.assertNotEqual(original, background_key(payload, 'home', 0, 'new-rgb-pack'))
        for changed in ({'condition': 'snow'}, {'variant': 1}, {'phase': 'night'}, {'visual_theme': 'weather-artwork-v1'}):
            self.assertNotEqual(background_key(weather, 'home', 0), background_key({**weather, **changed}, 'home', 0))
        self.assertIsNone(background_key({'kind': 'performance'}, 'home', 0))

    def test_saturation_preserves_hue_peak_rgb_black_and_neutral_white(self):
        colour = ((100, 80, 60),) * 17
        self.assertEqual(saturate_colours(colour, 100), colour)
        self.assertEqual(saturate_colours(colour, 0), ((100, 100, 100),) * 17)
        self.assertEqual(saturate_colours(colour, 200), ((100, 60, 20),) * 17)
        self.assertEqual(saturate_colours(colour, 250), ((100, 50, 0),) * 17)
        for rgb in ((255, 255, 255), (180, 180, 180), (0, 0, 0), (255, 0, 0)):
            self.assertEqual(saturate_colours((rgb,) * 17, 250), (rgb,) * 17)
        for saturation in (0, 50, 100, 150, 200, 250):
            result = saturate_colours(((255, 215, 90), (32, 104, 240)), saturation)
            self.assertEqual([max(rgb) for rgb in result], [255, 240])


class ProjectionWorkerTests(unittest.TestCase):
    def test_reselecting_same_game_source_restores_immediately_without_preparation(self):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            worker = FaceplateExtension(folder, builder=lambda request: calls.append(request) or [(20, 40, 90)] * 17,
                                       clock=lambda: 5)
            self.addCleanup(worker.stop)
            source = {'kind': 'artwork', 'sha256': 'game-a', 'context': 'game', 'route_appid': 620}
            worker.configure(True, source); wait_ready(worker)
            for _ in range(5):
                worker.configure(False, source)
                self.assertIsNone(worker.output())
                worker.configure(True, source, saturation=200)
                self.assertEqual(worker.status()['phase'], 'ready')
                self.assertEqual(worker.output().frame, saturate_colours(((20, 40, 90),) * 17, 200))
            self.assertEqual(len(calls), 1)
            # A different game/source still requires its own preparation.
            worker.configure(False, None)
            worker.configure(True, {**source, 'sha256': 'game-b', 'route_appid': 621})
            wait_ready(worker)
            self.assertEqual(len(calls), 2)

    def test_idle_never_starts_thread_or_process(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = FaceplateExtension(folder)
            worker.configure(False, None)
            self.assertIsNone(worker.output())
            self.assertIsNone(worker.thread); self.assertIsNone(worker.process)
            self.assertEqual(worker.status()['phase'], 'off')
            worker.stop()
            worker.configure(True, {'kind': 'artwork'})
            self.assertIsNone(worker.thread)
            self.assertIsNone(worker.output())

    def test_renderer_has_no_disk_access_and_overlay_only_ack_does_not_rebuild(self):
        calls = []; now = [10.0]
        with tempfile.TemporaryDirectory() as folder:
            worker = FaceplateExtension(folder, builder=lambda r: calls.append(r) or [(20, 40, 90)] * 17, clock=lambda: now[0])
            try:
                source = {'kind': 'artwork', 'sha256': 'abc', 'asset': 'a'}
                worker.configure(True, source); wait_ready(worker)
                worker.configure(True, {**source, 'asset': 'b'})
                with patch.object(Path, 'read_bytes', side_effect=AssertionError('read in LED loop')), patch.object(Path, 'read_text', side_effect=AssertionError('read in LED loop')), patch('signalbar.providers.faceplate_extension.cache_key', side_effect=AssertionError('rehashed unchanged input')):
                    unchanged = worker.configured_source
                    for _ in range(100):
                        worker.configure(True, unchanged); worker.output(now[0] + 1)
                self.assertEqual(len(calls), 1)
                self.assertEqual(worker.output(now[0] + 1).frame, ((20, 40, 90),) * 17)
            finally: worker.stop()

    def test_latest_source_wins_and_disabled_late_work_cannot_resume(self):
        entered = threading.Event(); release = threading.Event(); calls = []
        def build(request):
            calls.append(request['source']['sha256'])
            if len(calls) == 1: entered.set(); release.wait(2)
            return [(200 if request['source']['sha256'] == 'new' else 10, 0, 0)] * 17
        with tempfile.TemporaryDirectory() as folder:
            worker = FaceplateExtension(folder, builder=build)
            try:
                worker.configure(True, {'kind': 'artwork', 'sha256': 'old'})
                self.assertTrue(entered.wait(2))
                worker.configure(True, {'kind': 'artwork', 'sha256': 'new'})
                release.set(); wait_ready(worker)
                self.assertEqual(worker.status()['colours'], [(200, 0, 0)] * 17)
                worker.configure(False, None)
                self.assertIsNone(worker.output())
            finally: release.set(); worker.stop()

    def test_failure_is_visible_black_and_does_not_spin_retry(self):
        calls = []
        def build(request): calls.append(request); raise ValueError('invalid pack')
        with tempfile.TemporaryDirectory() as folder:
            worker = FaceplateExtension(folder, builder=build); source = {'kind': 'artwork', 'sha256': 'bad'}
            try:
                worker.configure(True, source); wait_ready(worker, 'error')
                for _ in range(100): worker.configure(True, source)
                self.assertEqual(len(calls), 1); self.assertEqual(worker.output().frame, BLACK)
            finally: worker.stop()

    def test_real_process_and_persistent_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'artwork-dashboard.rgb'
            raw = bytes((8, 30, 120)) * 3456; path.write_bytes(raw)
            source = dict(kind='artwork', root=str(root), path=str(path), frames=1, sha256=hashlib.sha256(raw).hexdigest())
            worker = FaceplateExtension(root / 'cache')
            try:
                worker.configure(True, source); wait_ready(worker)
                self.assertIsNone(worker.process)
                self.assertEqual(worker.status()['colours'], [(8, 30, 120)] * 17)
                self.assertEqual(len(list((root / 'cache').glob('*.json'))), 1)
            finally: worker.stop()
            cached = FaceplateExtension(root / 'cache')
            try:
                with patch('signalbar.providers.faceplate_extension.subprocess.Popen', side_effect=AssertionError('unnecessary process')):
                    cached.configure(True, source); wait_ready(cached)
                self.assertEqual(cached.status()['colours'], [(8, 30, 120)] * 17)
            finally: cached.stop()

    def test_local_static_artwork_reuses_strip_without_process(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = FaceplateExtension(folder)
            try:
                with patch('signalbar.providers.faceplate_extension.subprocess.Popen', side_effect=AssertionError('decoded static artwork twice')):
                    worker.configure(True, {'kind': 'artwork-strip', 'colours': {'bottom': [[18, 0, 28]] * 17}})
                    wait_ready(worker)
                self.assertEqual(worker.status()['colours'], [(18, 0, 28)] * 17)
            finally: worker.stop()

    def test_short_fade_then_exact_colours_and_unavailable_is_black(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = FaceplateExtension(folder, builder=lambda _: [(100, 0, 0)] * 17, clock=lambda: 5)
            try:
                worker.configure(True, {'kind': 'artwork'}); wait_ready(worker)
                self.assertEqual(worker.output(5).frame, BLACK)
                self.assertEqual(worker.output(5.175).frame, ((50, 0, 0),) * 17)
                self.assertEqual(worker.output(6).frame, ((100, 0, 0),) * 17)
                worker.configure(True, None)
                self.assertEqual(worker.status()['phase'], 'waiting'); self.assertEqual(worker.output(6).frame, BLACK)
            finally: worker.stop()

    def test_real_replacement_holds_colours_until_ready_then_crossfades_without_black(self):
        entered = threading.Event(); release = threading.Event(); now = [5.0]
        def build(request):
            if request['source']['sha256'] == 'new':
                entered.set(); release.wait(2)
                return [(200, 80, 40)] * 17
            return [(40, 20, 10)] * 17
        with tempfile.TemporaryDirectory() as folder:
            worker = FaceplateExtension(folder, builder=build, clock=lambda: now[0])
            try:
                worker.configure(True, {'kind': 'artwork', 'sha256': 'old'}); wait_ready(worker)
                now[0] = 6
                worker.configure(True, {'kind': 'artwork', 'sha256': 'new'})
                self.assertTrue(entered.wait(2))
                self.assertEqual(worker.output(6).frame, ((40, 20, 10),) * 17)
                self.assertTrue(worker.status()['holding'])
                release.set(); wait_ready(worker)
                self.assertEqual(worker.output(6).frame, ((40, 20, 10),) * 17)
                self.assertEqual(worker.output(6.175).frame, ((120, 50, 25),) * 17)
                self.assertEqual(worker.output(7).frame, ((200, 80, 40),) * 17)
            finally: release.set(); worker.stop()

    def test_failed_replacement_keeps_old_colours_and_reports_error(self):
        def build(request):
            if request['source']['sha256'] == 'bad': raise ValueError('invalid background')
            return [(40, 80, 120)] * 17
        with tempfile.TemporaryDirectory() as folder:
            worker = FaceplateExtension(folder, builder=build, clock=lambda: 5)
            try:
                worker.configure(True, {'kind': 'artwork', 'sha256': 'good'}); wait_ready(worker)
                worker.configure(True, {'kind': 'artwork', 'sha256': 'bad'}); wait_ready(worker, 'error')
                self.assertEqual(worker.output(6).frame, ((40, 80, 120),) * 17)
                self.assertTrue(worker.status()['holding'])
                worker.configure(False, None)
                self.assertIsNone(worker.output())
            finally: worker.stop()

    def test_saturation_and_pending_state_are_live_without_rebuild_or_fade_restart(self):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            worker = FaceplateExtension(folder, builder=lambda r: calls.append(r) or [(100, 80, 60)] * 17, clock=lambda: 5)
            source = {'kind': 'artwork', 'sha256': 'same'}
            try:
                worker.configure(True, source); wait_ready(worker)
                initial_ready = worker.ready_at; generation = worker.generation
                with patch('signalbar.providers.faceplate_extension.cache_key', side_effect=AssertionError('saturation rekeyed the RGB source')):
                    worker.configure(True, source, saturation=200, pending=True)
                    self.assertEqual(worker.output(6).frame, ((100, 60, 20),) * 17)
                    self.assertEqual(worker.status()['phase'], 'holding')
                    worker.configure(True, source, saturation=100)
                self.assertEqual(worker.status()['phase'], 'ready')
                self.assertEqual(worker.output(6).frame, ((100, 80, 60),) * 17)
                self.assertEqual(len(calls), 1); self.assertEqual(worker.ready_at, initial_ready)
                self.assertEqual(worker.generation, generation)
            finally: worker.stop()


class ProjectionRoutingTests(unittest.TestCase):
    def test_home_game_override_persist_and_do_not_change_brightness_or_matrix_route(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'settings.json'); settings = SettingsStore(path)
            original = settings.all()
            settings.update({'home_display': 'faceplate_extension', 'game_display': 'faceplate_extension', 'faceplate_extension_mapping': 'whole'})
            settings.update_display(620, 'faceplate_extension')
            loaded = SettingsStore(path)
            self.assertEqual(loaded.display_for(0)['mode'], 'faceplate_extension')
            self.assertEqual(loaded.display_for(620)['mode'], 'faceplate_extension')
            self.assertEqual(loaded.all()['faceplate_extension_mapping'], 'whole')
            self.assertEqual(loaded.all()['mode'], 'faceplate_extension')
            for key in ('brightness', 'light_bar_day_brightness', 'faceplate_lab_brightness', 'faceplate_home_display', 'faceplate_game_display'):
                if key in original: self.assertEqual(loaded.all()[key], original[key])
            loaded.update({'faceplate_extension_mapping': 'unknown'})
            self.assertEqual(loaded.all()['faceplate_extension_mapping'], 'bottom')

    def test_saturation_validation_persistence_and_brightness_are_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'settings.json'); settings = SettingsStore(path)
            original = settings.all()
            for raw, expected in ((200, 200), (1000, 250), (-4, 0), ('150', 150), ('bad', 100), (None, 100), (float('inf'), 100)):
                settings.update({'faceplate_extension_saturation': raw})
                self.assertEqual(SettingsStore(path).all()['faceplate_extension_saturation'], expected)
                for name in ('light_bar_day_brightness', 'night_mode_brightness', 'faceplate_brightness', 'home_display', 'game_display'):
                    self.assertEqual(settings.all()[name], original[name])

    def test_exclusive_base_and_existing_priority_owners(self):
        black = ProviderOutput('none', None, ''); other = ProviderOutput('weather', ((255, 0, 0),) * 17, '')
        extension = ProviderOutput('faceplate-extension:weather', ((1, 2, 3),) * 17, '')
        args = dict(mode='faceplate_extension', guard_allows=True, game=GameState(), performance=other,
                    artwork=other, idle=black, weather_base=other, controller_base=other, faceplate_extension=extension)
        arbiter = Arbiter()
        self.assertEqual(arbiter.choose(**args), extension)
        self.assertEqual(arbiter.choose(**{**args, 'assistant_base': other}), other)
        self.assertEqual(arbiter.choose(**{**args, 'steam_priority': True}).provider, 'valve')
        self.assertEqual(arbiter.choose(**{**args, 'guard_allows': False}).provider, 'valve')
        self.assertEqual(arbiter.choose(**{**args, 'mode': 'bar_off'}).frame, BLACK)
        self.assertEqual(arbiter.choose(**{**args, 'mode': 'disabled'}).provider, 'none')
        self.assertEqual(arbiter.choose(**{**args, 'event': other}), other)
        self.assertEqual(Engine._stripmine_family(extension.provider), 'weather')
        self.assertEqual(Engine._stripmine_family('faceplate-extension:artwork-strip'), 'artwork')

    def make_engine(self):
        engine = Engine.__new__(Engine)
        engine._faceplate_suspended = False; engine._faceplate_extension_present = True
        engine._faceplate_extension_device = 'usb-a'
        engine.faceplate = SimpleNamespace(powered=True, last_synchronized=True, last_asset='confirmed', device_token='usb-a', delivery={'signature': 'abc'})
        engine._faceplate_extension_source = {'kind': 'artwork', 'asset': 'confirmed', 'appid': 620, 'context': 'game', 'delivery_signature': 'abc'}
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        engine.faceplate_extension = FaceplateExtension(self.temp.name, builder=lambda _: [(1, 2, 3)] * 17, clock=lambda: 5)
        self.addCleanup(engine.faceplate_extension.stop)
        return engine

    def test_current_ack_game_usb_power_and_suspend_are_all_required(self):
        values = dict(faceplate_lab_enabled=True, signalbar_enabled=True, faceplate_extension_mapping='bottom', faceplate_rotate_180=False)
        for mutation in ('game', 'asset', 'signature', 'device', 'off', 'suspended', 'disconnected', 'unconfirmed', 'matrix_disabled'):
            with self.subTest(mutation=mutation):
                engine = self.make_engine(); game = GameState(620, 'Portal 2'); config = dict(values)
                if mutation == 'game': game = GameState(621, 'Another game')
                elif mutation == 'asset': engine.faceplate.last_asset = 'new'
                elif mutation == 'signature': engine.faceplate.delivery = {'signature': 'different'}
                elif mutation == 'device': engine.faceplate.device_token = 'usb-b'
                elif mutation == 'off': engine.faceplate.powered = False
                elif mutation == 'suspended': engine._faceplate_suspended = True
                elif mutation == 'disconnected': engine._faceplate_extension_present = False
                elif mutation == 'unconfirmed': engine.faceplate.last_synchronized = False
                else: config['faceplate_lab_enabled'] = False
                output = engine._faceplate_extension_output(config, game, 'faceplate_extension', 5)
                unavailable = mutation in ('off', 'suspended', 'disconnected', 'matrix_disabled')
                self.assertIsNone(output) if unavailable else self.assertEqual(output.frame, BLACK)
                self.assertEqual(engine.faceplate_extension.status()['phase'], 'off' if unavailable else 'waiting')
        engine = self.make_engine()
        engine._faceplate_extension_output(values, GameState(620, 'Portal 2'), 'faceplate_extension', 5)
        wait_ready(engine.faceplate_extension)
        self.assertEqual(engine.faceplate_extension.status()['phase'], 'ready')

    def test_source_is_bound_before_ack_and_non_image_scene_clears_it(self):
        engine = self.make_engine(); ticket = SimpleNamespace(context='game')
        captured = {'kind': 'artwork', 'path': 'prepared-original', 'sha256': 'a'}
        engine._remember_faceplate_extension_source({'kind': 'artwork', 'appid': 620}, ticket, {}, captured)
        self.assertEqual(engine._faceplate_extension_source['path'], 'prepared-original')
        self.assertEqual(engine._faceplate_extension_source['delivery_signature'], 'abc')
        engine._remember_faceplate_extension_source({'kind': 'performance'}, ticket, {})
        self.assertIsNone(engine._faceplate_extension_source)

    def configure_known_background(self, engine, key='original', generation=1):
        engine._faceplate_extension_source.update(sha256='raw-source', background_key=key, background_generation=generation)
        engine._faceplate_extension_target = dict(key=key, generation=generation, context='game', appid=620)
        values = dict(faceplate_lab_enabled=True, signalbar_enabled=True, faceplate_extension_mapping='bottom', faceplate_rotate_180=False)
        engine._faceplate_extension_output(values, GameState(620, 'Portal 2'), 'faceplate_extension', 6)
        wait_ready(engine.faceplate_extension)
        return values

    def test_repeated_overlay_render_upload_ack_and_ack_failure_never_cut_projection(self):
        engine = self.make_engine(); calls = []
        engine.faceplate_extension.builder = lambda r: calls.append(r) or [(1, 2, 3)] * 17
        values = self.configure_known_background(engine)
        ready_at = engine.faceplate_extension.ready_at
        for i, state in enumerate(('sending', 'unconfirmed', 'failed', 'confirmed') * 5, 2):
            engine._faceplate_extension_target['generation'] = i
            engine._faceplate_extension_refresh = dict(key='original', generation=i)
            engine.faceplate.delivery = dict(scene='artwork-dashboard', state=state, signature=f'overlay-{i}')
            engine.faceplate.last_synchronized = state == 'confirmed'
            if state == 'confirmed': engine.faceplate.last_asset = f'overlay-{i}'
            self.assertEqual(engine._faceplate_extension_output(values, GameState(620, 'Portal 2'), 'faceplate_extension', 6).frame, ((1, 2, 3),) * 17)
            self.assertEqual(engine.faceplate_extension.status()['phase'], 'holding')
            engine._faceplate_extension_delivery_basis = {**engine._faceplate_extension_refresh, **{k: engine.faceplate.delivery[k] for k in ('scene', 'signature')}}
            engine._faceplate_extension_refresh = None
            self.assertEqual(engine._faceplate_extension_output(values, GameState(620, 'Portal 2'), 'faceplate_extension', 6).frame, ((1, 2, 3),) * 17)
            if state == 'confirmed':
                engine._remember_faceplate_extension_source(
                    {'kind': 'artwork-dashboard', 'appid': 620, '_extension_background_key': 'original'},
                    SimpleNamespace(context='game', generation=i), {}, {'kind': 'artwork', 'sha256': 'raw-source'})
                self.assertEqual(engine._faceplate_extension_output(values, GameState(620, 'Portal 2'), 'faceplate_extension', 6).frame, ((1, 2, 3),) * 17)
                self.assertEqual(engine.faceplate_extension.status()['phase'], 'ready')
        self.assertEqual(len(calls), 1)
        self.assertEqual(engine.faceplate_extension.ready_at, ready_at)

    def test_real_upstream_weather_solar_or_game_transition_holds_previous_not_unconfirmed_new_source(self):
        for key, context, appid in (('new-weather', 'game', 620), ('night', 'game', 620), ('new-game', 'game', 621), ('home', 'home', 0)):
            with self.subTest(key=key):
                engine = self.make_engine(); values = self.configure_known_background(engine)
                engine._faceplate_extension_target = dict(key=key, context=context, appid=appid, generation=2)
                game = GameState(appid, 'Game' if appid else '')
                engine._faceplate_extension_refresh = dict(key=key, generation=2)
                engine.faceplate.delivery = dict(scene='dashboard', state='sending', signature='new-gif')
                engine.faceplate.last_synchronized = False
                self.assertEqual(engine._faceplate_extension_output(values, game, 'faceplate_extension', 6).frame, ((1, 2, 3),) * 17)
                self.assertEqual(engine.faceplate_extension.status()['phase'], 'holding')
                self.assertEqual(engine._faceplate_extension_source['background_key'], 'original')

    def test_unknown_transfer_performance_or_unsupported_target_never_inherits_projection(self):
        for mutation in ('unknown-signature', 'assistant', 'performance', 'unavailable', 'wrong-game'):
            with self.subTest(mutation=mutation):
                engine = self.make_engine(); values = self.configure_known_background(engine)
                if mutation == 'unavailable': engine._faceplate_extension_target['key'] = None
                elif mutation == 'wrong-game': engine._faceplate_extension_target['appid'] = 621
                else:
                    scene = 'artwork-dashboard' if mutation == 'unknown-signature' else 'gabe' if mutation == 'assistant' else 'performance'
                    engine.faceplate.delivery = dict(scene=scene, state='confirmed', signature='outside-transfer')
                    engine._faceplate_extension_delivery_basis = dict(key='original', signature='known-transfer', scene='artwork-dashboard')
                self.assertEqual(engine._faceplate_extension_output(values, GameState(620, 'Portal 2'), 'faceplate_extension', 6).frame, BLACK)

    def test_late_scene_commit_cannot_accept_an_old_background(self):
        engine = self.make_engine(); self.configure_known_background(engine)
        engine._lock = threading.RLock(); engine._faceplate_timer_end = None
        engine._display_panel_off = lambda: False
        engine._write_faceplate_runtime_status = lambda: None
        engine._stop=threading.Event();engine._faceplate_suspended=False
        engine.faceplate_router = SimpleNamespace(mark_preparing=lambda _: True, commit=lambda _: False, status=lambda:{"generation":3})
        engine.faceplate.synchronize_artwork = lambda *_: {'found': True, 'projection_source': {'kind': 'artwork', 'sha256': 'late-original'}}
        original = dict(engine._faceplate_extension_source)
        engine._handle_faceplate_scene({'payload': {'kind': 'artwork', 'appid': 620, '_extension_background_key': 'late',
            'ticket': SimpleNamespace(context='game', generation=2)}})
        self.assertEqual(engine._faceplate_extension_source, original)

    def test_current_prepared_game_palette_replaces_home_without_a_usb_ack(self):
        engine = self.make_engine(); calls = []; now = [5.0]
        engine.faceplate_extension.clock = lambda: now[0]
        engine.faceplate_extension.builder = lambda r: calls.append(r) or ([(200, 80, 40)] * 17
            if r['source'].get('sha256') == 'game-original' else [(1, 2, 3)] * 17)
        values = self.configure_known_background(engine, 'home', 1)
        engine._faceplate_extension_source.update(context='home', route_appid=0)
        now[0] = 6
        engine._faceplate_extension_target = dict(key='game', context='game', appid=620, generation=2)
        engine.faceplate.last_synchronized = False
        engine.faceplate.delivery = dict(scene='artwork-dashboard', signature='new-game', state='unconfirmed')
        engine.faceplate_router = SimpleNamespace(commit=lambda _: self.fail('prepared source committed a USB scene'))
        payload = {'kind': 'artwork-dashboard', 'appid': 620, '_extension_background_key': 'game'}
        ticket = SimpleNamespace(context='game', generation=2)
        self.assertTrue(engine._publish_faceplate_extension_source(payload, ticket, {},
            {'kind': 'artwork', 'sha256': 'game-original'}, prepared=True))
        engine._faceplate_extension_output(values, GameState(620, 'Portal 2'), 'faceplate_extension', 7)
        wait_ready(engine.faceplate_extension)
        self.assertEqual(engine._faceplate_extension_output(values, GameState(620, 'Portal 2'), 'faceplate_extension', 7).frame, ((200, 80, 40),) * 17)
        self.assertFalse(engine._faceplate_extension_status()['faceplate_confirmed'])
        self.assertEqual(engine._faceplate_extension_status()['context'], 'game')
        self.assertEqual(engine._faceplate_extension_status()['appid'], 620)
        self.assertEqual(engine._faceplate_extension_source['sha256'], 'game-original')
        generation = engine.faceplate_extension.generation
        engine.faceplate.last_synchronized = True; engine.faceplate.last_asset = 'game-image'
        engine.faceplate.delivery = dict(scene='artwork-dashboard', signature='new-game', state='confirmed')
        engine._faceplate_extension_target['generation'] = 3
        self.assertTrue(engine._publish_faceplate_extension_source(payload, ticket, {},
            {'kind': 'artwork', 'sha256': 'game-original'}))
        engine._faceplate_extension_output(values, GameState(620, 'Portal 2'), 'faceplate_extension', 7)
        self.assertTrue(engine._faceplate_extension_status()['faceplate_confirmed'])
        self.assertEqual(engine.faceplate_extension.generation, generation)
        self.assertEqual(len(calls), 2)

    def test_prepared_old_home_wrong_game_and_late_originals_are_rejected(self):
        engine = self.make_engine(); self.configure_known_background(engine, 'game', 3)
        original = dict(engine._faceplate_extension_source)
        for key, context, appid in (('home', 'home', 0), ('old-game', 'game', 621), ('game', 'game', 621)):
            payload = {'kind': 'artwork-dashboard', 'appid': appid, '_extension_background_key': key}
            self.assertFalse(engine._publish_faceplate_extension_source(payload,
                SimpleNamespace(context=context, generation=1), {},
                {'kind': 'artwork', 'sha256': 'late-original'}, prepared=True))
            self.assertEqual(engine._faceplate_extension_source, original)

    def test_dashboard_original_is_published_before_render_and_missing_ack(self):
        engine = self.make_engine(); now = [5.0]
        engine.faceplate_extension.clock = lambda: now[0]
        engine.faceplate_extension.builder = lambda r: [(200, 80, 40)] * 17 if r['source'].get('sha256') == 'game-pack' else [(1, 2, 3)] * 17
        values = self.configure_known_background(engine, 'home', 1)
        now[0] = 6
        engine._faceplate_extension_source.update(context='home', route_appid=0)
        engine._faceplate_extension_target = dict(key='game', context='game', appid=620, generation=2)
        engine._lock = threading.RLock(); engine._faceplate_timer_end = None
        engine._stop = threading.Event(); engine._faceplate_suspended = False
        engine._display_panel_off = lambda: False; engine._write_faceplate_runtime_status = lambda: None
        engine.faceplate_router = SimpleNamespace(mark_preparing=lambda _: True,
            status=lambda: {'generation': 2},
            sent_unconfirmed=lambda *_: True, commit=lambda _: self.fail('missing ACK committed full scene'))
        engine.faceplate.steamgriddb = SimpleNamespace(artwork_root=self.temp.name,
            selected_dashboard_pack_reference=lambda _: ({'dashboard_pack_frames': 1,
                'dashboard_pack_sha256': 'game-pack'}, Path(self.temp.name) / 'artwork-dashboard.rgb'))
        def render(*_):
            self.assertEqual(engine._faceplate_extension_source['context'], 'game')
            self.assertTrue(engine._faceplate_extension_source['prepared'])
            return b'prepared-dashboard', {'signature': 'game-render', 'frames': 24}
        engine._render_faceplate_scene = render
        def upload(*_):
            engine.faceplate.last_synchronized = False
            engine.faceplate.delivery = dict(state='unconfirmed', scene='artwork-dashboard', signature='game-render')
            return {'sent_unconfirmed': True, 'error': 'no final ACK'}
        engine._synchronize_faceplate_handoff = upload
        result = engine._handle_faceplate_scene({'payload': {'kind': 'artwork-dashboard', 'appid': 620,
            '_extension_background_key': 'game', 'ticket': SimpleNamespace(context='game', generation=2)}})
        self.assertTrue(result['sent_unconfirmed'])
        engine._faceplate_extension_output(values, GameState(620, 'Portal 2'), 'faceplate_extension', 7)
        wait_ready(engine.faceplate_extension)
        self.assertEqual(engine._faceplate_extension_output(values, GameState(620, 'Portal 2'), 'faceplate_extension', 7).frame, ((200, 80, 40),) * 17)
        self.assertFalse(engine._faceplate_extension_status()['faceplate_confirmed'])

    def test_failed_game_projection_cannot_leave_home_colours_indefinitely(self):
        with tempfile.TemporaryDirectory() as folder:
            def build(request):
                if request['source'].get('context') == 'game': raise ValueError('missing original')
                return [(40, 80, 120)] * 17
            worker = FaceplateExtension(folder, builder=build, clock=lambda: 5)
            try:
                worker.configure(True, {'kind': 'artwork', 'sha256': 'home', 'context': 'home', 'route_appid': 0})
                wait_ready(worker)
                worker.configure(True, {'kind': 'artwork', 'sha256': 'game', 'context': 'game', 'route_appid': 620})
                wait_ready(worker, 'error')
                self.assertEqual(worker.output(6).frame, BLACK)
                self.assertFalse(worker.status()['holding'])
            finally: worker.stop()


if __name__ == '__main__': unittest.main()
