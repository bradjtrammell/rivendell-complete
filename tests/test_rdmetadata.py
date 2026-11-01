"""GlassCoder now-playing metadata endpoint: local only, no secrets."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import os
import sys
import tempfile
import unittest

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("rdmetadata_testing",root/"tools"/"rdmetadata.py")
assert spec and spec.loader
m=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=m
spec.loader.exec_module(m)


class MetadataTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(m.normalize("Artist","Title"),b"Artist - Title\n")
        for a,t in (("","track"),("a",""),("a\nb","t"),("a","b\x00c")):
            with self.assertRaises(m.MetadataError):
                m.normalize(a,t)
    def test_named_pipe_receiver(self):
        with tempfile.TemporaryDirectory() as temp:
            fifo=Path(temp)/"meta.fifo"
            os.mkfifo(fifo,0o600)
            reader=os.open(fifo,os.O_RDONLY|os.O_NONBLOCK)
            try:
                m.publish(fifo,"Foo","Bar")
                self.assertEqual(os.read(reader,512),b"Foo - Bar\n")
            finally:
                os.close(reader)
    def test_not_a_regular_file_or_public_pipe(self):
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/"file"
            f.write_text("not a pipe")
            with self.assertRaises(m.MetadataError):
                m.publish(f,"Foo","Bar")
            f.unlink()
            os.mkfifo(f,0o666)
            with self.assertRaises(m.MetadataError):
                m.publish(f,"Foo","Bar")

if __name__=="__main__":
    unittest.main()
