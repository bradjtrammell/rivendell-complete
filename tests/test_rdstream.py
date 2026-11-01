"""No-network checks for GlassCoder station streamer configuration."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "tools" / "rdstream.py"
spec = importlib.util.spec_from_file_location("rdstream_tested", path)
assert spec and spec.loader
rdstream = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rdstream
spec.loader.exec_module(rdstream)


def config(**overrides):
    data = dict(server_type="Shout2", server_url="http://127.0.0.1:8000/",
                audio_device="JACK", alsa_device="default",
                jack_client="glasscoder", bitrate=128, samplerate=44100,
                stream_name="Test", genre="Pop")
    data.update(overrides)
    return data


class StreamTests(unittest.TestCase):
    def test_command_uses_secret_file_never_inline_auth(self):
        command = rdstream.glasscoder_command(
            config(), Path("/tmp/testing-credentials.ini"))
        self.assertIn("--server-type=Shout2", command)
        self.assertIn("--audio-format=MP3", command)
        self.assertIn("--credentials-file=/tmp/testing-credentials.ini", command)
        self.assertFalse(any(x.startswith("--server-auth") for x in command))

    def test_reject_credentials_in_url(self):
        for url in ["http://admin:secret@localhost:8000/", "http://localhost",
                    "https://localhost:8000/", "http://localhost:abc/",
                    "http://localhost:8000/?password=secret"]:
            with self.subTest(url=url):
                with self.assertRaises((rdstream.StreamError, ValueError)):
                    rdstream.validate_config(config(server_url=url))

    def test_reject_invalid_server_and_audio(self):
        for bad in [config(server_type="Shout3"), config(bitrate=0),
                    config(audio_device="FILE"), config(jack_client="bad\nname")]:
            with self.assertRaises(rdstream.StreamError):
                rdstream.validate_config(bad)

    def test_config_writes_private_files_and_refuses_overwrites(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "private"
            args = argparse.Namespace(config_dir=root, server_type="Shout2",
                server_url="http://127.0.0.1:8000/", username="source",
                audio_device="JACK", alsa_device="default",
                jack_client="glasscoder", bitrate=128, samplerate=44100,
                stream_name="Test", genre="Pop")
            with patch.object(rdstream.getpass, "getpass", return_value="do-not-log"):
                self.assertEqual(rdstream.configure(args), 0)
            self.assertEqual((root / "credentials.ini").stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / "stream.json").stat().st_mode & 0o777, 0o600)
            self.assertIn("Password=do-not-log", (root / "credentials.ini").read_text())
            self.assertNotIn("do-not-log", (root / "stream.json").read_text())
            with self.assertRaises(rdstream.StreamError):
                rdstream.configure(args)
            with patch.object(rdstream.shutil, "which", return_value="/usr/bin/glasscoder"):
                self.assertEqual(rdstream.start(root, check_only=True), 0)


if __name__ == "__main__":
    unittest.main()
