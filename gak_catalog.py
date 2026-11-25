"""Catalog of GAK sections and their question-bank keys."""

GAK_SECTIONS = (
    {"key": "surgery", "name": "🩺 Хирургия"},
    {"key": "therapy", "name": "🩻 Терапия"},
    {"key": "ozz", "name": "ОЗЗ"},
    {"key": "pediatrics", "name": "👶 Педиатрия"},
    {"key": "aig", "name": "🤰 АиГ"},
)

GAK_SUBJECTS_BY_SECTION = {
    "surgery": (
        {"key": "gakair", "name": "АиР", "file": "АиР.md"},
        {"key": "gakambsurg", "name": "Амбулаторная хирургия", "file": "Амбулаторная хирургия.md"},
        {"key": "gakhospitalsurg", "name": "Госпитальная хирургия", "file": "Госпитальная хирургия.md"},
        {"key": "gakchildsurg", "name": "Детская хирургия", "file": "Детская хирургия.md"},
        {"key": "gakcombustiologia", "name": "Комбустиология", "file": "Комбустиология.md"},
        {"key": "gaklor", "name": "ЛОР", "file": "ЛОР.md"},
        {"key": "gakoncology", "name": "Онкология", "file": "Онкология.md"},
        {"key": "gakophthalmology", "name": "Офтальмология", "file": "Офтальмология.md"},
        {"key": "gakpropsurg", "name": "Пропед хирургия", "file": "Пропед хирургия.md"},
        {"key": "gaktraumatology", "name": "Травматология", "file": "Травматология.md"},
        {"key": "gakurology", "name": "Урология", "file": "Урология.md"},
        {"key": "gakfaculty", "name": "Факультетская хирургия", "file": "Факультетская хирургия.md"},
        {"key": "gakhop", "name": "ХОП", "file": "ХОП.md"},
        {"key": "gakendosurg", "name": "Эндокринная хирургия", "file": "Эндокринная хирургия.md"},
    ),
    "therapy": (
        {"key": "gakgastroenterology", "name": "Гастроэнтерология"},
        {"key": "gakhematology", "name": "Гематология"},
        {"key": "gakdermatology", "name": "Дерматология"},
        {"key": "gakinfections", "name": "Инфекция"},
        {"key": "gakcardiology", "name": "Кардиология"},
        {"key": "gakneurology", "name": "Неврология"},
        {"key": "gaknephrology", "name": "Нефрология"},
        {"key": "gakpolyclinictherapy", "name": "Поликлиническая терапия"},
        {"key": "gakprofdiseases", "name": "Профессиональные болезни"},
        {"key": "gakpsychiatry", "name": "Психиатрия"},
        {"key": "gakpulmonology", "name": "Пульмонология"},
        {"key": "gakrheumatology", "name": "Ревматология"},
        {"key": "gakfamilymedicine", "name": "Семейная медицина"},
        {"key": "gakpharmacology", "name": "Фармакология"},
        {"key": "gakphthisiology", "name": "Фтизиатрия"},
    ),
    "ozz": ({"key": "gakozz", "name": "ОЗЗ"},),
    "pediatrics": (
        {"key": "gakallpediatrics", "name": "Вся педиатрия"},
        {"key": "gakchildinfections", "name": "Детские инфекции"},
    ),
    "aig": (
        {"key": "gakobstetrics", "name": "Акушерство"},
        {"key": "gakgynecology", "name": "Гинекология"},
    ),
}

GAK_SUBJECT_SECTION = {
    subject["key"]: section_key
    for section_key, subjects in GAK_SUBJECTS_BY_SECTION.items()
    for subject in subjects
}

GAK_SUBJECT_KEYS = tuple(
    subject["key"]
    for section_subjects in GAK_SUBJECTS_BY_SECTION.values()
    for subject in section_subjects
)
