"""Canonical faculty and course question-bank catalog for bot and web."""

from gak_catalog import GAK_SECTIONS, GAK_SUBJECTS_BY_SECTION, GAK_SUBJECT_KEYS


GAK_NODE = {
    "type": "group", "key": "gak", "name": "🎓 ГАК", "children": [
        {"type": "group", **section, "children": [
            {"type": "subject", **subject}
            for subject in GAK_SUBJECTS_BY_SECTION[section["key"]]
        ]}
        for section in GAK_SECTIONS
    ],
}


def _subject(key, name):
    return {"type": "subject", "key": key, "name": name}


def _mapped(key, name):
    return _subject(key, name)


FACULTIES = {
    "lech": {
        "name": "🏥 Лечебное дело", "courses": 6, "subjects": {
            1: [_subject("normanat_summer", "🦴 Нормальная анатомия (лето)"), _subject("normanat_winter", "🦴 Нормальная анатомия (зима)")],
            2: [_subject("histology", "🔬 Гистология"), _subject("microbiology", "🦠 Микробиология"), _subject("biochemistry", "⚗️ Биохимия"), _subject("normalphysiology", "🫀 Нормальная физиология")],
            3: [_subject("pharmacology", "💊 Фармакология"), _subject("therapy3", "🩻 Терапия 3"), _subject("pediatrics3", "👶 Педиатрия"), _subject("surgery3", "🩺 Хирургия 3"), _subject("hygiene", "🧼 Гигиена"), _subject("pathophysiology", "🫀 Патфиз")],
            4: [_subject("obstetrics", "🤰 Акушерство и гинекология"), _subject("therapy4", "🩻 Терапия 4"), _subject("dermatology", "🧴 Дерматовенерология"), _subject("lor", "👂 ЛОР"), _subject("neurology", "🧠 Неврология"), _subject("mmp", "💉 ВМП"), _subject("ophthalmology", "👁 Офтальмология")],
            5: [_subject("surgery5", "🩺 Хирургия 5"), _subject("psychiatry", "🧠 Психиатрия"), _subject("infections", "🦠 Инфекционные болезни"), _subject("therapy5", "🩻 Терапия 5"), _subject("pediatrics5", "👶 Педиатрия 5")],
            6: [GAK_NODE],
        },
    },
    "pediatrics": {
        "name": "👶 Педиатрия", "courses": 6, "subjects": {
            1: [_mapped("ped_normanat", "🦴 Нормальная анатомия")],
            2: [_mapped("ped_normalphysiology", "🫀 Нормальная физиология"), _mapped("ped_histology", "🔬 Гистология"), _mapped("ped_biochemistry", "⚗️ Биохимия"), _mapped("ped_microbiology", "🦠 Микробиология, вирусология и иммунология")],
            3: [_mapped("ped_pharmacology", "💊 Базисная фармакология"), _mapped("ped_pediatrics3", "👶 Педиатрия"), _mapped("ped_hygiene_children", "🧼 Гигиена детей и подростков"), _mapped("ped_propinternal", "🩻 Пропедевтика внутренних болезней"), _mapped("ped_proppediatrics", "👶 Пропедевтика детских болезней"), _mapped("ped_pathophysiology", "🫀 Патологическая физиология")],
            4: [_mapped("ped_lor", "👂 ЛОР"), _mapped("ped_faculty_pediatrics", "👶 Факультетская педиатрия"), _mapped("ped_ophthalmology", "👁 Офтальмология"), _mapped("ped_dermatology", "🧴 Дерматовенерология"), _mapped("ped_mmp", "💉 ВМП-ЭМ")],
            5: [_mapped("ped_obstetrics", "🤰 Акушерство и гинекология"), _mapped("ped_pediatrics5", "👶 Педиатрия 5"), _mapped("ped_epidemiology", "🦠 Эпидемиология"), _mapped("pediatrics_infections", "🦠 Детские инфекции"), _mapped("ped_infections", "🦠 Инфекционные болезни")],
        },
    },
    "dentistry": {
        "name": "🦷 Стоматология", "courses": 6, "subjects": {
            1: [_mapped("dent_normanat", "🦴 Нормальная анатомия"), _mapped("dent_normalphysiology", "🫀 Нормальная физиология")],
            2: [_mapped("dent_histology", "🔬 Гистология"), _mapped("dent_microbiology", "🦠 Микробиология, вирусология и иммунология")],
            4: [_mapped("dent_mmp", "💉 ВМП-ЭМ")],
        },
    },
    "mpd": {
        "name": "🏥 МПД", "courses": 6, "subjects": {
            1: [_mapped("mpd_normanat", "🦴 Нормальная анатомия")],
            2: [_mapped("mpd_normalphysiology", "🫀 Нормальная физиология"), _mapped("mpd_histology", "🔬 Гистология")],
            3: [_mapped("mpd_propinternal", "🩻 Пропедевтика внутренних болезней"), _mapped("mpd_pathophysiology", "🫀 Патологическая физиология"), _mapped("mpd_hygiene", "🧼 Общая гигиена"), _mapped("mpd_epidemiology", "🦠 Эпидемиология")],
            4: [_mapped("mpd_dermatology", "🧴 Дерматовенерология"), _mapped("mpd_obstetrics", "🤰 Акушерство и гинекология"), _mapped("mpd_mmp", "💉 ВМП-ЭМ")],
            5: [_mapped("mpd_infections", "🦠 Инфекционные болезни"), _mapped("mpd_hygiene_children", "🧼 Гигиена детей и подростков")],
        },
    },
    "pharmacy": {
        "name": "💊 Фармация", "courses": 6, "subjects": {
            1: [_mapped("pharm_normanat", "🦴 Нормальная анатомия"), _mapped("pharm_normalphysiology", "🫀 Нормальная физиология")],
            2: [_mapped("pharm_analytical_chemistry", "⚗️ Аналитическая химия")],
            3: [_mapped("pharm_biochemistry", "⚗️ Биохимия")],
            4: [_mapped("pharm_mmp", "💉 ВМП-ЭМ")],
        },
    },
}


FACULTY_SUBJECT_SOURCES = {
    "ped_normanat": "normanat_summer", "ped_normalphysiology": "normalphysiology",
    "ped_histology": "histology", "ped_biochemistry": "biochemistry",
    "ped_microbiology": "microbiology", "ped_pharmacology": "pharmacology",
    "ped_pediatrics3": "pediatrics3", "ped_pediatrics5": "pediatrics5",
    "ped_hygiene_children": "ped_hygiene_children",
    "ped_faculty_pediatrics": "ped_faculty_pediatrics",
    "ped_epidemiology": "ped_epidemiology",
    "ped_propinternal": "therapy3", "ped_proppediatrics": "pediatrics3",
    "ped_pathophysiology": "pathophysiology", "ped_lor": "lor",
    "ped_ophthalmology": "ophthalmology", "ped_dermatology": "dermatology",
    "ped_mmp": "mmp", "ped_obstetrics": "obstetrics", "ped_infections": "infections",
    "dent_normanat": "normanat_summer", "dent_normalphysiology": "normalphysiology",
    "dent_histology": "histology", "dent_microbiology": "microbiology", "dent_mmp": "mmp",
    "mpd_normanat": "normanat_summer", "mpd_normalphysiology": "normalphysiology",
    "mpd_histology": "histology", "mpd_propinternal": "therapy3",
    "mpd_pathophysiology": "pathophysiology", "mpd_hygiene": "hygiene",
    "mpd_hygiene_children": "ped_hygiene_children",
    "mpd_epidemiology": "ped_epidemiology",
    "mpd_dermatology": "dermatology", "mpd_obstetrics": "obstetrics",
    "mpd_mmp": "mmp", "mpd_infections": "infections",
    "pharm_normanat": "normanat_summer", "pharm_normalphysiology": "normalphysiology",
    "pharm_biochemistry": "biochemistry", "pharm_mmp": "mmp",
    "pharm_analytical_chemistry": "pharm_analytical_chemistry",
}


def iter_leaf_subjects(node_or_nodes):
    if isinstance(node_or_nodes, (list, tuple)):
        for node in node_or_nodes:
            yield from iter_leaf_subjects(node)
    elif node_or_nodes.get("type") == "subject":
        yield node_or_nodes
    elif node_or_nodes.get("type") == "group":
        yield from iter_leaf_subjects(node_or_nodes.get("children", ()))
