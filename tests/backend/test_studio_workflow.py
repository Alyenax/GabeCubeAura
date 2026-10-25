"""Cutover keeps source/export artifacts and excludes retired runtime services."""
from pathlib import Path
import hashlib
import importlib.util
import unittest

ROOT=Path(__file__).resolve().parents[2]


class CutoverPackagingTests(unittest.TestCase):
    def test_revision4_coordinated_collection_contract_is_pinned(self):
        path=ROOT/'docs/JSAUX_BROKER_V1_CONTRACT.md'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
            '480b8abaa9ee5669106f55fae46bb9acf0213abf4d28eb05568c499eccc4c11f')

    def test_retired_services_are_external_and_hardware_broker_stays(self):
        spec=importlib.util.spec_from_file_location('separation_package',ROOT/'scripts/package_plugin.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        paths=[str(p.relative_to(ROOT)) for p in module.iter_files(require_build=False)]
        self.assertFalse(any(p.startswith(('py_modules/signalbar/studio/',
            'py_modules/signalbar/cinema/','assets/cinema-player/',
            'assets/animated-screensaver-player/')) for p in paths))
        self.assertIn('docs/JSAUX_BROKER_V1_CONTRACT.md',paths)
        self.assertTrue(any(p.startswith('py_modules/signalbar/jsaux_broker/') for p in paths))
        self.assertFalse((ROOT/'py_modules/signalbar/studio').exists())
        self.assertFalse((ROOT/'py_modules/signalbar/cinema').exists())
        self.assertFalse((ROOT/'assets/animated-screensaver-player').exists())
