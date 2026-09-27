"""Check that the versioned Kaggle notebook stays parseable and fail-closed."""

import json
import unittest
from pathlib import Path


NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "packsense-ai.ipynb"
METADATA = Path(__file__).resolve().parents[1] / "notebooks" / "kernel-metadata.json"


class KaggleNotebookTests(unittest.TestCase):
    def test_code_cells_compile_and_no_model_fit_is_claimed(self):
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        metadata = json.loads(METADATA.read_text(encoding="utf-8"))
        self.assertEqual(notebook["nbformat"], 4)
        self.assertEqual(metadata["id"], "aspirant200715/packsense-ai")
        code = []
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                source = cell["source"]
                source = "".join(source) if isinstance(source, list) else source
                compile(source, str(NOTEBOOK), "exec")
                code.append(source)
        joined = "\n".join(code)
        self.assertIn('"model_trained": False', joined)
        self.assertIn('"status": "not_ready"', joined)
        self.assertIn('"material-suitability-labels.json"', joined)


if __name__ == "__main__":
    unittest.main()
