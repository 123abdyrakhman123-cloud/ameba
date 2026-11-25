"""Flat web representation of the bot's canonical faculty catalog."""

from faculty_catalog import FACULTIES as BOT_FACULTIES


def _web_subjects(nodes, groups=()):
    for node in nodes:
        if node.get("type") == "group":
            yield from _web_subjects(node.get("children", ()), (*groups, node["name"]))
        else:
            name = node["name"]
            if groups:
                name = " · ".join((*groups, name))
            yield {"key": node["key"], "name": name}


FACULTIES = {
    faculty_key: {
        "name": faculty["name"],
        "courses": faculty["courses"],
        "subjects": {
            str(course): list(_web_subjects(subjects))
            for course, subjects in sorted(faculty["subjects"].items())
        },
    }
    for faculty_key, faculty in BOT_FACULTIES.items()
}


def iter_subjects():
    for faculty in FACULTIES.values():
        for course_subjects in faculty["subjects"].values():
            yield from course_subjects


SUBJECT_KEYS = frozenset(subject["key"] for subject in iter_subjects())

RADIOLOGY_MODES = {
    "radiology_qa": {"name": "Вопрос–ответ", "subject_name": "Лучи · Вопрос–ответ"},
    "radiology_tf": {"name": "Правда или ложь", "subject_name": "Лучи · Правда или ложь"},
}
RADIOLOGY_SUBJECT_KEYS = frozenset(RADIOLOGY_MODES)
SUBJECT_KEYS = SUBJECT_KEYS | RADIOLOGY_SUBJECT_KEYS
