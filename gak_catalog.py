"""Каталог предметов государственной аттестации лечебного дела."""

GAK_SECTIONS = (
    {"key": "surgery", "name": "🩺 Хирургия"},
    {"key": "therapy", "name": "🩻 Терапия"},
    {"key": "ozz", "name": "ОЗЗ"},
    {"key": "pediatrics", "name": "👶 Педиатрия"},
    {"key": "aig", "name": "🤰 АиГ"},
)

GAK_SURGERY_SUBJECTS = (
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
)

GAK_SUBJECTS_BY_SECTION = {
    "surgery": GAK_SURGERY_SUBJECTS,
    "therapy": (),
    "ozz": (),
    "pediatrics": (),
    "aig": (),
}

GAK_SUBJECT_SECTION = {
    subject["key"]: section_key
    for section_key, subjects in GAK_SUBJECTS_BY_SECTION.items()
    for subject in subjects
}
