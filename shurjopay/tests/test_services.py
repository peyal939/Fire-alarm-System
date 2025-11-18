from __future__ import annotations

import os
import tempfile
from unittest import TestCase
from unittest.mock import patch

from shurjopay import services


class ShurjoPayServiceTests(TestCase):
    def test_prepare_log_path_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            desired = os.path.join(tmpdir, "nested", "logs", "sp.log")
            normalized = services._prepare_log_path(desired)
            self.assertTrue(normalized.endswith("sp.log"))
            self.assertTrue(os.path.isdir(os.path.dirname(normalized)))

    @patch("shurjopay.services.os.makedirs", side_effect=OSError("boom"))
    def test_prepare_log_path_fallback_on_error(self, _):
        path = services._prepare_log_path("C:/does/not/matter.log")
        self.assertEqual(path, "")
