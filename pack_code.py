import os

EXTENSIONS = {'.py', '.txt', '.sql', '.md'}
IGNORE_DIRS = {'.git', '__pycache__', '.venv', '.idea', 'sprites', 'images', '.vscode'}

with open("full_project_code.txt", "w", encoding="utf-8") as outfile:
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for file in files:
            ext = os.path.splitext(file)[1]
            if ext in EXTENSIONS and file != "pack_code.py":
                filepath = os.path.join(root, file)
                outfile.write(f"\n{'='*50}\nFILE: {filepath}\n{'='*50}\n\n")
                with open(filepath, "r", encoding="utf-8", errors="ignore") as infile:
                    outfile.write(infile.read())
print("Готово! Создан файл full_project_code.txt")