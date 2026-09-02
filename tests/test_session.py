"""Sticky visitor per country."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desk import session as sess


class SessionStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "session.json"
        self.patch = patch.object(sess, "SESSION_FILE", self.path)
        self.patch.start()
        patch.object(sess, "DATA", Path(self.tmp.name)).start()

    def tearDown(self):
        patch.stopall()
        self.tmp.cleanup()

    def test_default_us(self):
        cur = sess.current()
        self.assertEqual(cur["gl"], "US")
        self.assertEqual(cur["hl"], "en")

    def test_country_and_visitor(self):
        sess.set_country("EG")
        self.assertEqual(sess.current()["hl"], "ar")
        sess.remember_visitor("EG", "VISITORTOKEN")
        self.assertEqual(sess.visitor_for("EG"), "VISITORTOKEN")
        self.assertEqual(sess.visitor_for("US"), "")

    def test_watch_count(self):
        sess.set_country("BR")
        sess.remember_watch("BR", "vid11111111")
        sess.remember_watch("BR", "vid22222222")
        sess.remember_watch("BR", "vid11111111")
        self.assertEqual(sess.watch_count("BR"), 2)
        self.assertEqual(sess.watch_count("EG"), 0)


if __name__ == "__main__":
    unittest.main()
