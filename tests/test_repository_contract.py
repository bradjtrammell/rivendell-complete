"""Guard the public product definition, links and complete acceptance scope."""
from __future__ import annotations
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_readme_is_valid_markdown(self):
        text=(ROOT/"README.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Rivendell Complete\n"))
        self.assertEqual(text.count("```") % 2, 0, "unclosed code fence")
        self.assertNotIn("\\`", text, "literal escapes corrupt GitHub markdown")
        self.assertIn("internet stations", text)
        self.assertIn("broadcast stations", text)
        self.assertIn("listener requests", text)
        self.assertIn("SHOUTcast", text)
        self.assertIn("NAS", text)
        self.assertIn("not yet a production release", text)
        self.assertIn("docs/complete/ACCEPTANCE.md", text)

    def test_all_relative_readme_links_exist(self):
        text=(ROOT/"README.md").read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if re.match(r"^(https?://|mailto:|#)", link):
                continue
            target=(ROOT/link.split("#",1)[0]).resolve()
            with self.subTest(link=link):
                self.assertTrue(target.is_relative_to(ROOT), "path traversal")
                self.assertTrue(target.exists(), f"Broken relative link: {link}")

    def test_all_acceptance_ids_are_unique_and_reported(self):
        text=(ROOT/"docs/complete/ACCEPTANCE.md").read_text(encoding="utf-8")
        ids=re.findall(r"^\|\s*((?:ST|NAS|AUTO|REQ|STR|OPS)-\d{2})\s*\|",
                       text, flags=re.M)
        self.assertEqual(len(ids), 56, "Unexpected change in project requirements")
        self.assertEqual(len(set(ids)), len(ids), "Duplicate acceptance requirement ID")
        self.assertNotIn("\\`", text)
        for topic in ("internet-only", "broadcast", "NAS", "listener",
                      "SHOUTcast", "Icecast", "backtiming", "commercial",
                      "Ubuntu 26.04", "FLAC", "recovery"):
            with self.subTest(topic=topic):
                self.assertIn(topic.lower(), text.lower())

    def test_installer_package_dependencies_and_source_protection(self):
        installer=(ROOT/"tools/install-ubuntu26.sh").read_text(encoding="utf-8")
        postinst=(ROOT/"debian/postinst").read_text(encoding="utf-8")
        rules=(ROOT/"debian/rules.src").read_text(encoding="utf-8")
        self.assertIn("libid3-3.8.3-dev", installer)
        self.assertNotIn("libid3-dev ", installer)
        self.assertIn("PKG_WEB=", installer)
        self.assertIn('apt-get install -y "$PKG_WEB" "$PKG"', installer)
        self.assertIn("binary: build", rules)
        self.assertIn("chmod 750 /etc/rivendell.d", postinst)
        self.assertIn("mountpoint -q /var/snd", installer)


if __name__=="__main__":
    unittest.main()
