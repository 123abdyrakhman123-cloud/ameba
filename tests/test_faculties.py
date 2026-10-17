import ast
import unittest
from pathlib import Path

from gak_catalog import GAK_SURGERY_SUBJECTS


def load_faculties():
    source_path = Path(__file__).resolve().parents[1] / "main.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    assignment = next(
        node for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "FACULTIES" for target in node.targets)
    )
    functions = [
        node for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"faculty_menu_inline", "course_menu_inline"}
    ]

    class Button:
        def __init__(self, text, callback_data):
            self.text = text
            self.callback_data = callback_data

    class Markup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

    isolated_module = ast.Module(body=[assignment, *functions], type_ignores=[])
    namespace = {
        "GAK_SURGERY_SUBJECTS": GAK_SURGERY_SUBJECTS,
        "FACULTIES": None,
        "InlineKeyboardButton": Button,
        "InlineKeyboardMarkup": Markup,
    }
    exec(compile(isolated_module, str(source_path), "exec"), namespace)
    return namespace


class FacultyMenuTests(unittest.TestCase):
    def test_pediatrics_is_a_separate_faculty_with_existing_subjects(self):
        namespace = load_faculties()
        faculties = namespace["FACULTIES"]

        self.assertIn("pediatrics", faculties)
        pediatrics = faculties["pediatrics"]
        self.assertEqual(pediatrics["course_numbers"], (3, 5))
        self.assertEqual(
            [subject["key"] for subjects in pediatrics["subjects"].values() for subject in subjects],
            ["pediatrics3", "pediatrics5"],
        )
        self.assertEqual(
            [subject["key"] for subject in faculties["lech"]["subjects"][3]],
            ["pharmacology", "therapy3", "pediatrics3", "surgery3", "hygiene", "pathophysiology"],
        )
        self.assertIn("pediatrics5", [subject["key"] for subject in faculties["lech"]["subjects"][5]])
        self.assertEqual(
            [row[0].callback_data for row in namespace["faculty_menu_inline"]().inline_keyboard[:2]],
            ["fac_lech", "fac_pediatrics"],
        )
        self.assertEqual(
            [row[0].callback_data for row in namespace["course_menu_inline"]("pediatrics").inline_keyboard[:2]],
            ["course_pediatrics_3", "course_pediatrics_5"],
        )


if __name__ == "__main__":
    unittest.main()
