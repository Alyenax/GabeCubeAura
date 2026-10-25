"""Keep GPL code, identified CC graphics and third-party notices distinct."""
from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from check_license_scope import ART, GPL, REQUIRED, check_license_scope


def write_json(root, relative, data):
    (root / relative).write_text(json.dumps(data))


class TestLicenseScope(unittest.TestCase):
    def copy_scope_fixture(self, root):
        doc = json.loads((ROOT / "licenses/faceplate-scope.json").read_text())
        art = json.loads((ROOT / doc["asset_manifest"]).read_text())
        runtime = json.loads((ROOT / "scripts/runtime-files.json").read_text())
        paths = REQUIRED | {"package.json", "scripts/runtime-files.json"}
        paths |= {p for p in runtime if p.startswith("licenses/") or p.startswith("assets/faceplate/")}
        for group in ("gpl_source_paths", "inherited_bsd", "frontend_and_studio_source_paths"):
            paths.update(doc[group])
        paths.update(entry["source"] for entry in art["files"])
        for relative in paths:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        return doc, art, runtime

    def test_current_source_inventory_is_consistent(self):
        check_license_scope(ROOT, public_build=True)
        doc = json.loads((ROOT / "licenses/faceplate-scope.json").read_text())
        self.assertEqual(doc["future_default_license"], GPL)
        self.assertEqual(doc["faceplate_code_license"], GPL)
        self.assertEqual(doc["faceplate_asset_license"], ART)
        self.assertEqual(doc["publish_clearance"], "CLEARED")
        self.assertNotEqual((ROOT / "LICENSE").read_bytes(),
                            (ROOT / "licenses/BSD-3-Clause-previous.txt").read_bytes())

    def test_public_v140_did_not_license_faceplate_code(self):
        doc = json.loads((ROOT / "licenses/faceplate-scope.json").read_text())
        self.assertEqual(doc["public_v1_4_0_verified_source_ref"], "Alyenax/GabeCubeAura@v1.4.0")
        for key in ("public_v1_4_0_faceplate_source_files", "public_v1_4_0_jsaux_broker_files", "public_v1_4_0_faceplate_assets"):
            self.assertEqual(doc[key], 0)
        self.assertIs(doc["public_v1_4_0_faceplate_covered_by_bsd"], False)

    def test_public_build_rejects_missing_or_pending_clearance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc, _, _ = self.copy_scope_fixture(root)
            for clearance in ("BLOCKED_PEND_REVIEW", "", "CLEARED "):
                doc["publish_clearance"] = clearance
                write_json(root, "licenses/faceplate-scope.json", doc)
                with self.assertRaisesRegex(ValueError, "Public release blocked"):
                    check_license_scope(root, public_build=True)

    def test_bsd_root_cannot_return(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_scope_fixture(root)
            shutil.copyfile(ROOT / "licenses/BSD-3-Clause-previous.txt", root / "LICENSE")
            with self.assertRaisesRegex(ValueError, "Official licence text changed: LICENSE"):
                check_license_scope(root)

    def test_cannot_put_noncommercial_conditions_back_on_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc, _, _ = self.copy_scope_fixture(root)
            doc["faceplate_code_license"] = "PolyForm-Noncommercial-1.0.0"
            write_json(root, "licenses/faceplate-scope.json", doc)
            with self.assertRaisesRegex(ValueError, "must remain GPL"):
                check_license_scope(root)

    def test_noncommercial_source_header_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc, _, _ = self.copy_scope_fixture(root)
            target = root / doc["gpl_source_paths"][0]
            target.write_text("# SPDX-License-Identifier: CC-BY-NC-SA-4.0\n" + target.read_text())
            with self.assertRaisesRegex(ValueError, "incorrectly applied to code"):
                check_license_scope(root)

    def test_changed_cc_legal_text_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_scope_fixture(root)
            (root / "licenses/CC-BY-NC-SA-4.0.txt").write_text("Restricted for one named company")
            with self.assertRaisesRegex(ValueError, "Official licence text changed"):
                check_license_scope(root)

    def test_new_bundled_graphic_needs_explicit_inventory_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, runtime = self.copy_scope_fixture(root)
            relative = "assets/faceplate/weather/unreviewed.gif"
            (root / relative).write_bytes(b"new graphic")
            write_json(root, "scripts/runtime-files.json", runtime + [relative])
            with self.assertRaisesRegex(ValueError, "Unclassified or duplicate bundled Faceplate artwork"):
                check_license_scope(root)

    def test_modified_graphic_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, art, _ = self.copy_scope_fixture(root)
            (root / art["files"][0]["path"]).write_bytes(b"different pixels")
            with self.assertRaisesRegex(ValueError, "Artwork bytes changed"):
                check_license_scope(root)

    def test_duplicate_graphic_entry_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, art, _ = self.copy_scope_fixture(root)
            art["files"].append(art["files"][0])
            write_json(root, "licenses/faceplate-assets.json", art)
            with self.assertRaisesRegex(ValueError, "Unclassified or duplicate"):
                check_license_scope(root)

    def test_missing_attribution_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, art, _ = self.copy_scope_fixture(root)
            art["files"][0]["attribution"] = ""
            write_json(root, "licenses/faceplate-assets.json", art)
            with self.assertRaisesRegex(ValueError, "Missing artwork attribution"):
                check_license_scope(root)

    def test_technical_catalogue_cannot_be_added_as_nc_graphic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, art, _ = self.copy_scope_fixture(root)
            art["files"].append(dict(art["files"][0], path=art["technical_metadata_excluded"][0]))
            write_json(root, "licenses/faceplate-assets.json", art)
            with self.assertRaisesRegex(ValueError, "Unclassified or duplicate"):
                check_license_scope(root)

    def test_missing_runtime_licence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, runtime = self.copy_scope_fixture(root)
            runtime.remove("licenses/CC-BY-NC-SA-4.0.txt")
            write_json(root, "scripts/runtime-files.json", runtime)
            with self.assertRaisesRegex(ValueError, "Runtime omits required licensing"):
                check_license_scope(root)

    def test_starter_cannot_silently_return(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, runtime = self.copy_scope_fixture(root)
            write_json(root, "scripts/runtime-files.json", runtime + ["assets/faceplate/calibrated-home/faceplate.gif"])
            with self.assertRaisesRegex(ValueError, "Stray starter must not be bundled"):
                check_license_scope(root)

    def test_changed_upstream_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_scope_fixture(root)
            (root / "licenses/decky-api-1.1.3/src/index.ts").write_text("// changed upstream")
            with self.assertRaisesRegex(ValueError, "Third-party notice/source changed"):
                check_license_scope(root)

    def test_private_lab_cannot_be_relabelled_as_public_distribution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc, _, _ = self.copy_scope_fixture(root)
            doc["release_history"]["private_lab_220_publicly_distributed"] = True
            write_json(root, "licenses/faceplate-scope.json", doc)
            with self.assertRaisesRegex(ValueError, "Labs including Lab 220 stayed private"):
                check_license_scope(root)

    def test_private_metadata_cannot_be_treated_as_a_third_party_grant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc, _, _ = self.copy_scope_fixture(root)
            doc["release_history"]["infer_grants_from_private_license_file"] = True
            write_json(root, "licenses/faceplate-scope.json", doc)
            with self.assertRaisesRegex(ValueError, "Do not infer a third-party grant"):
                check_license_scope(root)

    def test_staged_policy_must_match_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc, _, _ = self.copy_scope_fixture(root)
            check_license_scope(ROOT, root)
            doc["faceplate_asset_license"] = "CC0-1.0"
            write_json(root, "licenses/faceplate-scope.json", doc)
            with self.assertRaisesRegex(ValueError, "Bundled licensing material differs"):
                check_license_scope(ROOT, root)

    def test_staged_graphics_must_match_reviewed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, art, _ = self.copy_scope_fixture(root)
            (root / art["files"][0]["path"]).write_bytes(b"different packaged pixels")
            with self.assertRaisesRegex(ValueError, "Bundled code/artwork differs"):
                check_license_scope(ROOT, root)

    def test_staged_missing_upstream_notice_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_scope_fixture(root)
            (root / "licenses/Tabler-Icons-MIT.txt").unlink()
            with self.assertRaisesRegex(ValueError, "Missing/unsafe licence inventory file"):
                check_license_scope(ROOT, root)


if __name__ == "__main__":
    unittest.main()
