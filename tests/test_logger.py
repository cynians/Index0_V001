import unittest
from unittest.mock import patch

from engine.logger import Logger


class LoggerTests(unittest.TestCase):
    def test_info_accepts_and_applies_rate_limit(self):
        logger = Logger(level="DEBUG")

        with (
            patch("engine.logger.time.time", side_effect=[10.0, 10.25, 10.75]),
            patch("builtins.print") as output,
        ):
            logger.info("first", key="map_notice", interval=0.5)
            logger.info("suppressed", key="map_notice", interval=0.5)
            logger.info("second", key="map_notice", interval=0.5)

        self.assertEqual(2, output.call_count)
        self.assertIn("first", output.call_args_list[0].args[0])
        self.assertIn("second", output.call_args_list[1].args[0])

    def test_unkeyed_info_remains_unlimited(self):
        logger = Logger(level="INFO")

        with patch("builtins.print") as output:
            logger.info("first")
            logger.info("second")

        self.assertEqual(2, output.call_count)


if __name__ == "__main__":
    unittest.main()
