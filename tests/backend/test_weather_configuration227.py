"""Independent rain preferences, migration and explicit previews through GCA."""
from datetime import datetime
from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import Mock

from signalbar.settings import SettingsStore
from signalbar.settings.store import DEFAULTS
from signalbar.providers.weather import WeatherProvider,weather_frame
from signalbar.backend.engine import Engine
from signalbar.faceplate.weather_artwork import WEATHER_ARTWORK_V2_THEME as THEME


class RainConfigurationTests(unittest.TestCase):
    def test_old_selection_seeds_both_periods_then_saves_independently(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            path.write_text(json.dumps({'weather_sequence_revision':12,'weather_rain_variant':1}))
            store=SettingsStore(path)
            self.assertEqual(store.all()['weather_rain_night_variant'],1)
            store.update({'weather_rain_variant':0})
            self.assertEqual(store.all()['weather_rain_night_variant'],1)
            reloaded=SettingsStore(path)
            self.assertEqual((reloaded.all()['weather_rain_variant'],reloaded.all()['weather_rain_night_variant']),(0,1))
            reloaded.update({'weather_rain_night_variant':0})
            self.assertEqual(reloaded.all()['weather_rain_variant'],0)

    def test_auto_route_chooses_day_and_night_variant_for_bar_and_faceplate(self):
        values=dict(DEFAULTS,weather_rain_variant=0,weather_rain_night_variant=1,weather_display='everywhere')
        provider=WeatherProvider(clock=lambda:100.3)
        provider._fetched_at=100
        engine=Engine.__new__(Engine);engine.weather=Mock()
        status=dict(condition='rain',temperature_c=12,phase='ready',faceplate_weather_state='fresh',
                    sunrise_at='2026-10-24T07:30:00',sunset_at='2026-10-24T18:30:00')
        engine.weather.status.return_value=status
        for daylight,variant in [(True,0),(False,1)]:
            provider._sample=dict(condition='rain',is_day=daylight)
            self.assertEqual(provider.output(values).frame,weather_frame('rain',variant,100.3,values,is_day=daylight))
            status['is_day']=daylight
            payload,_,error=engine._faceplate_weather_payload(values,False)
            self.assertFalse(error)
            self.assertEqual(payload['variant'],variant)
            self.assertEqual(payload['phase'],'day' if daylight else 'night')

    def test_bar_preview_uses_selected_phase_instead_of_current_weather(self):
        provider=WeatherProvider(clock=lambda:100)
        for selection,phase in [('rain_day',True),('rain_night',False)]:
            provider._sample=dict(condition='rain',is_day=not phase)
            self.assertTrue(provider.preview(selection,1))
            sample,variant,elapsed,preview=provider._current(DEFAULTS,100)
            self.assertTrue(preview)
            self.assertEqual(sample['condition'],'rain')
            self.assertEqual(sample['is_day'],phase)

    def test_matrix_preview_overrides_live_phase_before_cache_and_render(self):
        engine=Engine.__new__(Engine);engine.settings=Mock();engine.settings.all.return_value=DEFAULTS
        engine._lock=threading.RLock();engine._game=Mock(running=False)
        engine._faceplate_weather_payload=Mock(return_value=(dict(phase='night',temperature_c=12,unit='celsius'),{},''))
        engine._faceplate_playtime_facts=Mock(return_value={})
        engine._render_faceplate_scene=Mock(return_value=(b'GIF89a',{}))
        keys=[]
        for selection,phase in [('rain_day','day'),('rain_night','night')]:
            result=engine.faceplate_weather_preview(selection,1,THEME)
            payload,ticket=engine._render_faceplate_scene.call_args.args
            self.assertEqual(payload['condition'],'rain')
            self.assertEqual(payload['phase'],phase)
            self.assertEqual(result['phase'],phase)
            keys.append(ticket.content_key)
        self.assertNotEqual(*keys)

    def test_dashboard_preview_uses_selected_solar_period(self):
        engine=Engine.__new__(Engine);engine.settings=Mock();engine.settings.all.return_value=DEFAULTS
        engine._lock=threading.RLock();engine._game=Mock(running=False)
        engine.controllers=Mock();engine.controllers.primary_battery.return_value=None
        engine.faceplate_steam_state=Mock();engine.faceplate_steam_state.snapshot.return_value.render_payload.return_value={}
        engine._faceplate_artwork_dashboard_facts=Mock(return_value={})
        engine._faceplate_weather_payload=Mock(return_value=(dict(temperature_c=12,unit='celsius',now='2026-10-24T22:00:00',sunrise='2026-10-24T07:30:00',sunset='2026-10-24T18:30:00'),{},''))
        engine._render_faceplate_scene=Mock(return_value=(b'GIF89a',{}))
        for selection,daylight in [('rain_day',True),('rain_night',False)]:
            engine.faceplate_dashboard_preview(selection,1,THEME)
            payload,_=engine._render_faceplate_scene.call_args.args
            instant=datetime.fromisoformat(payload['display_at'])
            self.assertEqual(datetime.fromisoformat(payload['sunrise'])<=instant<datetime.fromisoformat(payload['sunset']),daylight)
