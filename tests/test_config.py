import os
import tempfile
import unittest
from pathlib import Path

from drawbot.config import AppConfig, ConfigStore, default_config_path


class ConfigStoreTests(unittest.TestCase):
    def test_default_config_path_prefers_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "custom-config.json"
            previous = os.environ.get("DRAWBOT_CONFIG_PATH")
            os.environ["DRAWBOT_CONFIG_PATH"] = str(config_path)
            try:
                self.assertEqual(default_config_path(), config_path)
            finally:
                if previous is None:
                    os.environ.pop("DRAWBOT_CONFIG_PATH", None)
                else:
                    os.environ["DRAWBOT_CONFIG_PATH"] = previous

    def test_save_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConfigStore(Path(temp_dir) / "drawbot" / "config.json")
            config = AppConfig(
                api_key="test-key",
                base_url="https://example.test/v1",
                model="gpt-test",
            )

            store.save(config)

            self.assertEqual(store.load(), config)

    def test_load_missing_file_returns_empty_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConfigStore(Path(temp_dir) / "missing.json")
            self.assertEqual(store.load(), AppConfig())


if __name__ == "__main__":
    unittest.main()
