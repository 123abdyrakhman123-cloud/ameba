import re

with open('therapy4.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Мы ищем пустые шаблоны:
# add_question(
#     "therapy4",  # subject
#     "",  # вопрос
#     ["", "", "", "", ""],  # варианты
#     1,  # номер правильного варианта (1-5)
#     ""  # объяснение
# )
# И удаляем их.

pattern = re.compile(
    r'add_question\(\s*'
    r'\"therapy4\",\s*# subject\s*'
    r'\"\",\s*# вопрос\s*'
    r'\[\"\", \"\", \"\", \"\", \"\"\],\s*# варианты\s*'
    r'1,\s*# номер правильного варианта \(1-5\)\s*'
    r'\"\"\s*# объяснение\s*'
    r'\)\s*',
    re.MULTILINE
)

new_text = pattern.sub('', text)

with open('therapy4.py', 'w', encoding='utf-8') as f:
    f.write(new_text.strip() + '\n')

print("Очистка завершена.")
