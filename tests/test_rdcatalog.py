"""Read-only music catalog export safety tests."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
spec=importlib.util.spec_from_file_location("rdcatalog_tests",ROOT/"tools"/"rdcatalog.py")
assert spec and spec.loader
rd=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=rd
spec.loader.exec_module(rd)

class CatalogTests(unittest.TestCase):
    def test_missing_external_config_is_empty(self):
        with tempfile.TemporaryDirectory() as t:
            file=Path(t)/"rd.conf"
            file.write_text("[mySQL]\nHostname=localhost\n")
            root,refs=rd.load_external_map(file)
            self.assertIsNone(root)
            self.assertEqual(refs,{})
    def test_external_file_map_preserves_relative_filename(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)
            root=base/"music"
            root.mkdir()
            refs=base/"refs"
            refs.mkdir()
            (root/"Artist").mkdir()
            (root/"Artist"/"Song.mp3").write_bytes(b"test")
            (refs/"123456_001.ref").write_bytes(b"Artist/Song.mp3\n")
            cfg=base/"rd.conf"
            cfg.write_text(f"[ExternalAudio]\nRoot={root}\nReferences={refs}\n")
            resolved,mapping=rd.load_external_map(cfg)
            self.assertEqual(resolved,root)
            self.assertEqual(mapping,{123456:"Artist/Song.mp3"})
    def test_symlink_reference_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)
            root=base/"music";root.mkdir()
            refs=base/"refs";refs.mkdir()
            original=base/"song.ref";original.write_bytes(b"Artist/Song.mp3\n")
            (refs/"123456_001.ref").symlink_to(original)
            cfg=base/"rd.conf"
            cfg.write_text(f"[ExternalAudio]\nRoot={root}\nReferences={refs}\n")
            with self.assertRaises(rd.CatalogError):
                rd.load_external_map(cfg)

if __name__=="__main__":
    unittest.main()
