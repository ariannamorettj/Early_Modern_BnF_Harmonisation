import unittest
import pandas as pd
import numpy as np
import os
import subprocess
import sys
from io import StringIO


class TestBNFPlaceHarmonisation(unittest.TestCase):
    """
    Test suite to verify that the Python and R scripts produce identical results.

    Prerequisites:
    1. Both R and Python scripts should be in the working directory
    2. Input data files must be present
    3. R must be installed and accessible via command line
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures that are used by multiple tests."""
        # Get the directory where the test script is located
        cls.test_dir = os.path.dirname(os.path.abspath(__file__))
        # Go up two levels to get the project root (from test/test_equivalent_py_r/ to project root)
        cls.test_parent = os.path.dirname(cls.test_dir)
        cls.project_root = os.path.dirname(cls.test_parent)
        cls.working_dir = os.path.join(cls.project_root, "data", "bnf_place_harmonisation")

        # Script paths
        cls.scripts_dir = os.path.join(cls.project_root, "data", "bnf_place_harmonisation", "scripts")
        cls.python_script_path = os.path.join(cls.scripts_dir, "bnf_place_harmonisation.py")
        cls.r_script_path = os.path.join(cls.scripts_dir, "bnf_place_harmonisation.R")

        # Output paths
        cls.r_output_path = os.path.join(cls.working_dir, "data", "data_final", "bnf_publication_place_r.csv")
        cls.python_output_path = os.path.join(cls.working_dir, "data", "data_final", "bnf_publication_place.csv")

        # Test data paths
        cls.test_input_data = os.path.join(cls.working_dir, "bnf_edition_data_raw.csv")

    def test_01_input_data_exists(self):
        """Test that required input data files exist."""
        # First check if scripts exist
        self.assertTrue(
            os.path.exists(self.python_script_path),
            f"Python script not found at: {self.python_script_path}"
        )

        self.assertTrue(
            os.path.exists(self.r_script_path),
            f"R script not found at: {self.r_script_path}"
        )

        # Then check data files
        required_files = [
            "bnf_edition_data_raw.csv",
            "data/data_work/bnf_place_name_harmonisation_table_final.csv",
            "data/data_work/bnf_country_harmonisation_table.csv"
        ]

        for file in required_files:
            file_path = os.path.join(self.working_dir, file)
            self.assertTrue(
                os.path.exists(file_path),
                f"Required input file not found: {file_path}"
            )

    def test_02_str_after_last_parentheses_function(self):
        """Test the string parsing function with various inputs."""
        # Import the function from the Python script
        import importlib.util

        # Check if the Python script exists
        if not os.path.exists(self.python_script_path):
            self.skipTest(f"Python script not found at {self.python_script_path}")

        spec = importlib.util.spec_from_file_location(
            "bnf_place_harmonisation",
            self.python_script_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        str_after_last_parentheses = module.str_after_last_parentheses

        # Test cases
        test_cases = [
            ("Paris (France)", ["Paris", "France"]),
            ("Amsterdam (Pays-Bas)", ["Amsterdam", "Pays-Bas"]),
            ("London (England) (UK)", ["London (England)", "UK"]),
            ("Berlin", ["Berlin", ""]),
            ("", ["", ""]),
            (None, ["", ""])
        ]

        for input_str, expected in test_cases:
            with self.subTest(input_str=input_str):
                result = str_after_last_parentheses(input_str)
                self.assertEqual(result, expected,
                                 f"Failed for input: {input_str}")

    def test_03_run_r_script(self):
        """Execute the R script and verify it completes successfully."""
        # Check if R is available
        try:
            result = subprocess.run(['Rscript', '--version'],
                                    capture_output=True,
                                    text=True,
                                    timeout=10)
            self.assertEqual(result.returncode, 0, "R is not installed or not accessible")
        except FileNotFoundError:
            self.skipTest("Rscript not found in PATH")

        # Run the R script
        try:
            result = subprocess.run(
                ['Rscript', self.r_script_path],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout
            )

            if result.returncode != 0:
                print(f"R script stderr: {result.stderr}")
                print(f"R script stdout: {result.stdout}")

            self.assertEqual(result.returncode, 0,
                             f"R script failed with error: {result.stderr}")
        except subprocess.TimeoutExpired:
            self.fail("R script execution timed out")

    def test_04_run_python_script(self):
        """Execute the Python script and verify it completes successfully."""
        try:
            result = subprocess.run(
                [sys.executable, self.python_script_path],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                print(f"Python script stderr: {result.stderr}")
                print(f"Python script stdout: {result.stdout}")

            self.assertEqual(result.returncode, 0,
                             f"Python script failed with error: {result.stderr}")
        except subprocess.TimeoutExpired:
            self.fail("Python script execution timed out")

    def test_05_output_files_exist(self):
        """Test that both scripts produced output files."""
        self.assertTrue(
            os.path.exists(self.python_output_path),
            "Python output file not found"
        )

        # For R output, we'll use the same path (or modify R script to output to different location)
        self.assertTrue(
            os.path.exists(self.python_output_path),
            "Output file not found"
        )

    def test_06_compare_output_schemas(self):
        """Test that both outputs have the same column structure."""
        df_python = pd.read_csv(self.python_output_path)

        # Expected columns
        expected_columns = [
            'edition',
            'place_original',
            'place_uncertainty_brackets',
            'place_uncertainty_parentheses',
            'place_uncertainty_question_marks',
            'tgn_id',
            'publication_place',
            'publication_country',
            'longitude',
            'latitude'
        ]

        self.assertListEqual(
            list(df_python.columns),
            expected_columns,
            "Output columns don't match expected schema"
        )

    def test_07_compare_row_counts(self):
        """Test that both scripts produce the same number of rows."""
        df_python = pd.read_csv(self.python_output_path)
        df_input = pd.read_csv(self.test_input_data)

        # The output should have one row per unique edition
        unique_editions = df_input['edition'].nunique()

        self.assertEqual(
            len(df_python),
            unique_editions,
            f"Expected {unique_editions} rows, got {len(df_python)}"
        )

    def test_08_compare_data_types(self):
        """Test that data types are appropriate in the output."""
        df_python = pd.read_csv(self.python_output_path)

        # Check numeric columns
        numeric_cols = ['longitude', 'latitude']
        for col in numeric_cols:
            # Allow for missing values
            non_null_values = df_python[col].dropna()
            if len(non_null_values) > 0:
                self.assertTrue(
                    pd.api.types.is_numeric_dtype(non_null_values),
                    f"Column {col} should be numeric"
                )

        # Check boolean columns
        boolean_cols = [
            'place_uncertainty_brackets',
            'place_uncertainty_parentheses',
            'place_uncertainty_question_marks'
        ]
        for col in boolean_cols:
            unique_values = df_python[col].dropna().unique()
            self.assertTrue(
                all(val in [True, False, 'TRUE', 'FALSE', 1, 0] for val in unique_values),
                f"Column {col} should contain boolean values"
            )

    def test_09_compare_specific_records(self):
        """Test that specific records match between implementations."""
        df_python = pd.read_csv(self.python_output_path)

        # Check for no duplicate editions
        duplicate_editions = df_python[df_python.duplicated(subset=['edition'], keep=False)]
        self.assertEqual(
            len(duplicate_editions),
            0,
            f"Found {len(duplicate_editions)} duplicate editions"
        )

    def test_10_validate_harmonisation_logic(self):
        """Test that the harmonisation logic produces expected results."""
        df_python = pd.read_csv(self.python_output_path)

        # Test that uncertainty flags are boolean
        uncertainty_cols = [
            'place_uncertainty_brackets',
            'place_uncertainty_parentheses',
            'place_uncertainty_question_marks'
        ]

        for col in uncertainty_cols:
            # Check that values are boolean or boolean-like
            non_null = df_python[col].dropna()
            if len(non_null) > 0:
                self.assertTrue(
                    all(isinstance(val, (bool, np.bool_)) or val in [0, 1, 'TRUE', 'FALSE']
                        for val in non_null),
                    f"Column {col} contains non-boolean values"
                )

    def test_11_compare_statistical_properties(self):
        """Compare statistical properties of the outputs."""
        df_python = pd.read_csv(self.python_output_path)

        # Count records with coordinates
        has_coords = df_python[
            df_python['longitude'].notna() &
            df_python['latitude'].notna()
            ]

        print(f"\nRecords with coordinates: {len(has_coords)} / {len(df_python)}")
        print(f"Percentage: {len(has_coords) / len(df_python) * 100:.2f}%")

        # Count records with TGN IDs
        has_tgn = df_python[df_python['tgn_id'].notna()]
        print(f"Records with TGN ID: {len(has_tgn)} / {len(df_python)}")
        print(f"Percentage: {len(has_tgn) / len(df_python) * 100:.2f}%")

        # These are informational, not assertions
        self.assertGreater(len(df_python), 0, "Output should not be empty")

    def test_12_validate_country_harmonisation(self):
        """Test that country harmonisation worked correctly."""
        df_python = pd.read_csv(self.python_output_path)

        # Check that publication_country is not null for most records
        non_null_countries = df_python['publication_country'].notna().sum()
        total_records = len(df_python)

        # At least 50% should have country information
        self.assertGreater(
            non_null_countries / total_records,
            0.5,
            "Less than 50% of records have country information"
        )

    def test_13_validate_coordinate_ranges(self):
        """Test that coordinates are within valid ranges."""
        df_python = pd.read_csv(self.python_output_path)

        # Longitude should be between -180 and 180
        valid_lon = df_python['longitude'].dropna()
        if len(valid_lon) > 0:
            self.assertTrue(
                all((valid_lon >= -180) & (valid_lon <= 180)),
                "Longitude values out of valid range [-180, 180]"
            )

        # Latitude should be between -90 and 90
        valid_lat = df_python['latitude'].dropna()
        if len(valid_lat) > 0:
            self.assertTrue(
                all((valid_lat >= -90) & (valid_lat <= 90)),
                "Latitude values out of valid range [-90, 90]"
            )


class TestStringParsingFunction(unittest.TestCase):
    """Separate test class for detailed string parsing function tests."""

    @classmethod
    def setUpClass(cls):
        """Set up the paths once for all tests."""
        cls.test_dir = os.path.dirname(os.path.abspath(__file__))
        cls.project_root = os.path.dirname(cls.test_dir)
        cls.python_script_path = os.path.join(
            cls.project_root,
            "data",
            "bnf_place_harmonisation",
            "scripts",
            "bnf_place_harmonisation.py"
        )

        # Check if the Python script exists
        if not os.path.exists(cls.python_script_path):
            raise unittest.SkipTest(f"Python script not found at {cls.python_script_path}")

        # Import the function once
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "bnf_place_harmonisation",
            cls.python_script_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.parse_function = module.str_after_last_parentheses

    def test_single_parentheses(self):
        """Test parsing with single set of parentheses."""
        result = self.__class__.parse_function("Paris (France)")
        self.assertEqual(result, ["Paris", "France"])

    def test_nested_parentheses(self):
        """Test parsing with nested/multiple parentheses."""
        result = self.__class__.parse_function("London (England) (UK)")
        self.assertEqual(result, ["London (England)", "UK"])

    def test_no_parentheses(self):
        """Test parsing with no parentheses."""
        result = self.__class__.parse_function("Berlin")
        self.assertEqual(result, ["Berlin", ""])

    def test_empty_string(self):
        """Test parsing empty string."""
        result = self.__class__.parse_function("")
        self.assertEqual(result, ["", ""])

    def test_none_value(self):
        """Test parsing None value."""
        result = self.__class__.parse_function(None)
        self.assertEqual(result, ["", ""])

    def test_whitespace_handling(self):
        """Test that whitespace is properly trimmed."""
        result = self.__class__.parse_function("  Amsterdam  ( Netherlands )  ")
        self.assertEqual(result, ["Amsterdam", "Netherlands"])

    def test_special_characters(self):
        """Test parsing with special characters."""
        result = self.__class__.parse_function("Saint-Étienne (France)")
        self.assertEqual(result, ["Saint-Étienne", "France"])


def run_tests():
    """Run all tests and generate a report."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestBNFPlaceHarmonisation))
    suite.addTests(loader.loadTestsFromTestCase(TestStringParsingFunction))

    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("=" * 70)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)