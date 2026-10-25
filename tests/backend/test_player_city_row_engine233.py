"""Real Engine routing, timer reversal and failed row uploads with ACKed City."""
import copy
from unittest.mock import Mock, patch
import unittest
import test_player_city as fixtures
from signalbar.faceplate.playtime import timer_facts


class CityRowEngineTests(unittest.TestCase):
    setUp = fixtures.PlayerCityEngineIntegration.setUp

    def confirm(self):
        self.engine._reconcile_faceplate('routing-change', force=True)
        self.assertTrue(self.result['synchronized'])
        return copy.deepcopy(self.engine.player_city.confirmed)

    def test_timer_changes_then_restores_choice_without_accepting_fresh_count(self):
        original = self.confirm()
        self.sample['players'] = 90000
        bodies = self.panel.bodies
        self.engine._faceplate_playtime_facts = Mock(return_value=timer_facts(299))
        self.engine._reconcile_faceplate()
        shown = self.engine.player_city.status()['displayed']
        self.assertEqual(shown['players'], original['players'])
        self.assertEqual(shown['at'], original['at'])
        self.assertEqual(shown['row'], {'countdown': timer_facts(299)})
        self.assertGreater(self.panel.bodies, bodies)
        self.assertEqual(self.engine.faceplate_worker.submit.call_args.args[2]['upload_interval_seconds'], 60)
        bodies = self.panel.bodies
        self.engine._faceplate_playtime_facts.return_value = timer_facts(298)
        self.engine._reconcile_faceplate()
        self.assertEqual(self.panel.bodies, bodies, 'Seconds never create City GIF writes')
        self.engine._faceplate_playtime_facts.return_value = {}
        self.engine._reconcile_faceplate()
        self.assertEqual(self.engine.player_city.confirmed['row']['mode'], 'count')
        self.assertEqual(self.engine.player_city.confirmed['at'], original['at'])

    def test_timer_cancelled_before_reserve_supersedes_the_queued_timer(self):
        self.confirm()
        requests = []
        self.engine.faceplate_worker.submit.side_effect = lambda scene, payload, meta: requests.append((payload, meta)) or 1
        self.engine._faceplate_playtime_facts = Mock(return_value=timer_facts(300))
        self.engine._reconcile_faceplate()
        timer = requests[-1][0]
        self.engine._faceplate_playtime_facts.return_value = {}
        self.engine._reconcile_faceplate()
        normal = requests[-1][0]
        self.assertNotEqual(timer['ticket'].generation, normal['ticket'].generation)
        self.assertEqual(normal['row']['mode'], 'count')
        outcome = self.engine._handle_faceplate_scene({'payload': timer, 'metadata': {}, '_cancelled': None})
        self.assertTrue(outcome['superseded'])

    def test_row_failure_does_not_delay_hourly_count_and_exception_can_retry(self):
        original = self.confirm()
        self.clock.advance(3590)
        self.engine.settings.update({'faceplate_player_city_row':'session'})
        with patch.object(self.engine, '_synchronize_faceplate_handoff', side_effect=OSError('USB failed')):
            with self.assertRaises(OSError):
                self.engine._reconcile_faceplate('dashboard-layout-change', force=True)
        self.assertEqual(self.engine.player_city.row_attempt['outcome'], 'failed')
        self.assertEqual(self.engine.player_city.confirmed['at'], original['at'])
        self.assertEqual(self.engine.player_city.attempt['at'], original['at'])
        self.sample['players'] = 90000
        self.clock.advance(10)
        self.engine._reconcile_faceplate()
        self.assertEqual(self.engine.player_city.confirmed['players'], 90000)

    def test_only_the_visible_fact_is_sampled_and_unknown_session_is_not_zero(self):
        values = self.engine.settings.all()
        self.engine._faceplate_playtime_facts = Mock(return_value=timer_facts(1000))
        with patch.object(self.engine.dashboard_stats, 'snapshot', side_effect=AssertionError('hidden stats')), \
             patch.object(self.engine.controllers, 'faceplate_batteries', side_effect=AssertionError('hidden battery')):
            self.assertEqual(self.engine._faceplate_player_city_facts(values), {'countdown': timer_facts(1000)})
        self.engine._faceplate_playtime_facts.return_value = {}
        self.engine._session_start_known = False
        self.assertEqual(self.engine._faceplate_player_city_facts({**values, 'faceplate_player_city_row':'session'}),
                         {'mode':'session','session_minutes':None})

    def test_incomplete_row_transfer_keeps_the_known_city_led_projection(self):
        import time
        self.confirm()
        values = self.engine.settings.all()
        self.engine._faceplate_extension_present = True
        self.engine._faceplate_extension_output(values, self.engine._game, 'faceplate_extension', time.monotonic())
        provider = self.engine.faceplate_extension
        with provider.condition:
            self.assertTrue(provider.condition.wait_for(lambda: provider.phase == 'ready', timeout=5))
        before = self.engine._faceplate_extension_output(values, self.engine._game, 'faceplate_extension', time.monotonic()+1)
        self.engine._faceplate_playtime_facts = Mock(return_value=timer_facts(300))
        def incomplete(*_):
            self.coordinator.delivery = dict(state='unconfirmed', scene='player-city', signature='incomplete-row')
            self.coordinator.last_synchronized = False
            return dict(sent_unconfirmed=True, error='ACK absent')
        with patch.object(self.engine, '_synchronize_faceplate_handoff', side_effect=incomplete):
            self.engine._reconcile_faceplate()
        after = self.engine._faceplate_extension_output(values, self.engine._game, 'faceplate_extension', time.monotonic()+1)
        self.assertEqual(after.frame, before.frame)
        self.assertNotEqual(after.frame, ((0,0,0),)*17)
