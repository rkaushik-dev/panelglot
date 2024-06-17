from googletrans import Translator, LANGUAGES
from openpyxl import Workbook

# Initialize the Translator
translator = Translator()

dest_language = 'zh-tw'

resource_src_file = '../../V4T-TIJ/V4T/V4T.rc'

# Create a new workbook and select the active worksheet
wb = Workbook()
ws = wb.active

# Writing words into the Excel file
# Write a header row
ws.append(['English', 'Taiwan'])

# open resource file as read mode
with open(resource_src_file, 'r') as file:
    lines = file.readlines()

# Optionally, strip the newline character from each line
lines = [line.strip() for line in lines]

resource_words = []

skip_resource_words = [
    "h :",
    "1.",
    "2.",
    "3.",
    "3.",
    "5.",
    "0 ms",
    "mm",
    "2015/1/5",
    "hh:mm",
    "YY",
    "YYYY",
    "MM",
    "MMM",
    "MMMM",
    "DD",
    "DDD",
    "DDDD",
    "hh",
    "HH",
    "SS",
    "tt",
    "WW",
    "JJJ",
    "UU",
]
def add_resource_words(word):
    word = word[1:-1]
    if (word in skip_resource_words):
        return
    if (len(word) <= 1) or (word in resource_words):
        return
    resource_words.append(word)
    #print(word)
    return

# Dialog resource type for support caption. It needs for translating
dlg_control_types = [
    "PUSHBUTTON",
    "DEFPUSHBUTTON",
    "RTEXT",
    "LTEXT",
    "CTEXT",
    "GROUPBOX",
    ]

def handle_dialog_line(line):
    parts = line.split(maxsplit=1)
    if len(parts) <= 0:
        return

    control_type = parts[0]
    control_content = parts[1] if len(parts) > 1 else ""

    if not control_type in dlg_control_types:
        return

    control_caption = control_content.split(',')[0]
    add_resource_words(control_caption)

def handle_table_line(line):
    parts = line.split(maxsplit=1)
    if len(parts) <= 1:
        return

    table_type = parts[0]
    table_content = parts[1] if len(parts) > 1 else ""
    if table_type == "STRINGTABLE" or table_type == "BEGIN" or table_type == "END" or table_type == "#endif":
        return

    add_resource_words(table_content)

line_mode = "default_mode"

for line in lines:
    if line == "// Dialog":
        #print("Starting the dialog part")
        line_mode = "dialog_mode"
        continue
    elif line == "// String Table":
        #print("Starting the string table part")
        line_mode = "table_mode"
        continue
    elif line == "/////////////////////////////////////////////////////////////////////////////":
        #print("Default part")
        line_mode = "default_mode"
        continue

    if line_mode == "dialog_mode":
        handle_dialog_line(line)
    elif line_mode == "table_mode":
        handle_table_line(line)
    else:
        continue

for word in resource_words:
    translated_word = translator.translate(word, dest=dest_language)
    print(word, ':', translated_word.text)
    ws.append([word, translated_word.text])

# Set column widths
ws.column_dimensions['A'].width = 50
ws.column_dimensions['B'].width = 80

# Save the workbook
wb.save("Translation - V4T-TIJ - Taiwan.xlsx")
