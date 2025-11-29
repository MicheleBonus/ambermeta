from pathlib import Path
import unittest

from ambermeta.parsers import (
    InpcrdParser,
    MdcrdParser,
    MdinParser,
    MdoutParser,
    PrmtopParser,
)


DATA_DIR = Path(__file__).resolve().parent.parent / "md_test_files"


class ParserSmokeTest(unittest.TestCase):
    def test_prmtop_parser(self):
        prmtop_file = DATA_DIR / "CH3L1_HUMAN_6NAG.top"
        result = PrmtopParser(str(prmtop_file)).parse()
        self.assertEqual(result.filename, str(prmtop_file))
        self.assertIsNotNone(result.details)

    def test_inpcrd_parser(self):
        inpcrd_file = DATA_DIR / "CH3L1_HUMAN_6NAG.crd"
        result = InpcrdParser(str(inpcrd_file)).parse()
        self.assertEqual(result.filename, str(inpcrd_file))
        self.assertIsNotNone(result.details)
        self.assertTrue(result.details.file_format)

    def test_mdin_parser(self):
        mdin_file = DATA_DIR / "ntp_prod_0001.mdin"
        result = MdinParser(str(mdin_file)).parse()
        self.assertEqual(result.filename, str(mdin_file))
        self.assertIsNotNone(result.details)

    def test_mdout_parser(self):
        mdout_file = DATA_DIR / "ntp_prod_0001.mdout"
        result = MdoutParser(str(mdout_file)).parse()
        self.assertEqual(result.filename, str(mdout_file))
        self.assertIsNotNone(result.details)

    def test_mdcrd_parser(self):
        trajectory_file = DATA_DIR / "CH3L1_HUMAN_6NAG.crd"
        result = MdcrdParser(str(trajectory_file)).parse()
        self.assertEqual(result.filename, str(trajectory_file))
        self.assertIsNotNone(result.details)


if __name__ == "__main__":
    unittest.main()
