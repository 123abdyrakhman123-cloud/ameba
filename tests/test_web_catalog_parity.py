import unittest

from faculty_catalog import FACULTIES as BOT_FACULTIES, iter_leaf_subjects
from webapp_catalog import FACULTIES


class WebCatalogParityTests(unittest.TestCase):
    def test_catalog_exposes_all_101_bot_question_banks_as_flat_course_subjects(self):
        subjects = [
            subject
            for faculty in FACULTIES.values()
            for course_subjects in faculty["subjects"].values()
            for subject in course_subjects
        ]
        keys = {subject["key"] for subject in subjects}
        bot_keys = {
            subject["key"]
            for faculty in BOT_FACULTIES.values()
            for course_subjects in faculty["subjects"].values()
            for subject in iter_leaf_subjects(course_subjects)
        }

        self.assertEqual(len(keys), 101)
        self.assertEqual(len(subjects), 101)
        self.assertEqual(keys, bot_keys)
        self.assertIn("pediatrics", FACULTIES)
        self.assertIn("dentistry", FACULTIES)
        self.assertIn("mpd", FACULTIES)
        self.assertIn("pharmacy", FACULTIES)
        self.assertIn("normanat_summer", keys)
        self.assertIn("normanat_winter", keys)
        self.assertIn("pediatrics_infections", keys)
        self.assertIn("gakchildinfections", keys)
        self.assertIn("ped_hygiene_children", keys)
        self.assertIn("mpd_hygiene_children", keys)
        self.assertIn("ped_faculty_pediatrics", keys)
        self.assertIn("ped_epidemiology", keys)
        self.assertIn("mpd_epidemiology", keys)
        self.assertIn("pharm_analytical_chemistry", keys)
        self.assertTrue(any("ГАК" in item["name"] and "Хирургия" in item["name"] for item in subjects))

    def test_radiology_is_a_separate_free_section_with_two_question_banks(self):
        from webapp_catalog import RADIOLOGY_MODES, RADIOLOGY_SUBJECT_KEYS

        self.assertEqual(RADIOLOGY_SUBJECT_KEYS, {"radiology_qa", "radiology_tf"})
        self.assertEqual(set(RADIOLOGY_MODES), RADIOLOGY_SUBJECT_KEYS)
        self.assertEqual(RADIOLOGY_MODES["radiology_qa"]["name"], "Вопрос–ответ")
        self.assertEqual(RADIOLOGY_MODES["radiology_tf"]["name"], "Правда или ложь")
        self.assertFalse(RADIOLOGY_SUBJECT_KEYS & {subject["key"] for subject in [
            subject for faculty in FACULTIES.values()
            for course_subjects in faculty["subjects"].values()
            for subject in course_subjects
        ]})

    def test_every_course_subject_is_renderable_by_the_existing_web_contract(self):
        for faculty in FACULTIES.values():
            for course_subjects in faculty["subjects"].values():
                for subject in course_subjects:
                    self.assertEqual(set(subject), {"key", "name"})
                    self.assertIsInstance(subject["key"], str)
                    self.assertIsInstance(subject["name"], str)


if __name__ == "__main__":
    unittest.main()
