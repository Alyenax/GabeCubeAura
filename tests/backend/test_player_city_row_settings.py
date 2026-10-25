"""City row choices persist independently from Dashboard presentation."""
import json
from pathlib import Path
import tempfile
import unittest

from signalbar.settings import SettingsStore
from signalbar.settings.export import read_configuration_import, write_configuration_export


class PlayerCityRowSettings(unittest.TestCase):
    def test_choices_reload_and_export_without_changing_dashboard(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'settings.json')
            store = SettingsStore(path)
            self.assertEqual(store.all()['faceplate_player_city_row'], 'count')
            contexts = {'game': {'game_row': 'e', 'battery_style': 'bar'}}
            store.update({'faceplate_dashboard_contexts': contexts})
            dashboard = store.all()['faceplate_dashboard_contexts']
            for choice in ('count', 'controllers', 'session', 'achievements', 'total', 'dashboard'):
                with self.subTest(choice=choice):
                    store.update({'faceplate_player_city_row': choice})
                    reloaded = SettingsStore(path)
                    self.assertEqual(reloaded.all()['faceplate_player_city_row'], choice)
                    self.assertEqual(reloaded.all()['faceplate_dashboard_contexts'], dashboard)
                    export = str(Path(folder) / 'export.json')
                    write_configuration_export(reloaded, export, 'test', {'appid': 620})
                    restored = SettingsStore(str(Path(folder) / 'restored.json'))
                    restored.replace_configuration(*read_configuration_import(export))
                    self.assertEqual(restored.all()['faceplate_player_city_row'], choice)
                    self.assertEqual(restored.all()['faceplate_dashboard_contexts'], dashboard)

    def test_city_dashboard_choices_and_battery_style_remain_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'settings.json')
            store = SettingsStore(path)
            self.assertEqual(store.all()['faceplate_player_city_dashboard_row'], 'controllers')
            self.assertEqual(store.all()['faceplate_player_city_battery_style'], 'percent')
            store.update({'faceplate_dashboard_contexts': {'game': {'game_row': 'b', 'battery_style': 'percent'}}})
            dashboard = store.all()['faceplate_dashboard_contexts']
            for choice in ('next_hour', 'today', 'controllers', 'a', 'b', 'c', 'd', 'e'):
                store.update({'faceplate_player_city_row': 'dashboard',
                    'faceplate_player_city_dashboard_row': choice, 'faceplate_player_city_battery_style': 'bar'})
                store.update({'faceplate_player_city_row': 'session'})
                reloaded = SettingsStore(path)
                self.assertEqual(reloaded.all()['faceplate_player_city_dashboard_row'], choice)
                self.assertEqual(reloaded.all()['faceplate_player_city_battery_style'], 'bar')
                self.assertEqual(reloaded.all()['faceplate_dashboard_contexts'], dashboard)
                export = str(Path(folder) / 'export.json')
                write_configuration_export(reloaded, export, 'test', {'appid': 620})
                restored = SettingsStore(str(Path(folder) / 'restored.json'))
                restored.replace_configuration(*read_configuration_import(export))
                self.assertEqual(restored.all()['faceplate_player_city_dashboard_row'], choice)
                self.assertEqual(restored.all()['faceplate_player_city_battery_style'], 'bar')
                self.assertEqual(restored.all()['faceplate_dashboard_contexts'], dashboard)

    def test_old_and_malformed_configurations_use_count_default(self):
        for value in (None, 'unknown', [], {}, True, 42):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'settings.json'
                path.write_text(json.dumps({key: value for key in (
                    'faceplate_player_city_row', 'faceplate_player_city_dashboard_row', 'faceplate_player_city_battery_style')}))
                result = SettingsStore(str(path)).all()
                self.assertEqual(result['faceplate_player_city_row'], 'count')
                self.assertEqual(result['faceplate_player_city_dashboard_row'], 'controllers')
                self.assertEqual(result['faceplate_player_city_battery_style'], 'percent')

    def test_new_default_does_not_replace_explicit_saved_rows(self):
        for choice in ('controllers', 'session', 'achievements', 'total', 'dashboard'):
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'settings.json'
                path.write_text(json.dumps({'faceplate_player_city_row': choice,
                    'faceplate_player_city_dashboard_row': 'e', 'faceplate_player_city_battery_style': 'bar'}))
                result = SettingsStore(str(path)).all()
                self.assertEqual(result['faceplate_player_city_row'], choice)
                self.assertEqual(result['faceplate_player_city_dashboard_row'], 'e')
                self.assertEqual(result['faceplate_player_city_battery_style'], 'bar')


if __name__ == '__main__':
    unittest.main()
