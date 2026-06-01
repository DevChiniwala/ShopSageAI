import os
import re

def refactor_config_imports(directory):
    # Matches `from shopsage.config import VAR, VAR2` 
    # But strictly expects only uppercase variables or specific known ones
    import_pattern = re.compile(r'^from\s+shopsage\.config\s+import\s+((?:[A-Za-z0-9_]+(?:\s*,\s*)?)+)$', re.MULTILINE)
    
    count = 0
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py') and file != 'config.py':
                filepath = os.path.join(root, file)
                
                # skip venv
                if 'venv' in filepath or '.venv' in filepath:
                    continue
                    
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # We need to only process files that actually have the import to avoid infinite loops
                if 'from shopsage.config import settings' in content:
                    continue
                    
                match = import_pattern.search(content)
                if match:
                    vars_str = match.group(1)
                    vars_list = [v.strip() for v in vars_str.split(',')]
                    
                    # replace the entire matched line exactly
                    # instead of string replacement which could match incorrectly
                    content = content[:match.start()] + "from shopsage.config import settings" + content[match.end():]
                    
                    for v in vars_list:
                        if not v: continue
                        v_pattern = re.compile(rf'\b{v}\b')
                        content = v_pattern.sub(f'settings.{v}', content)
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content)
                    print(f"Refactored {filepath}")
                    count += 1
                    
    print(f"Total files refactored: {count}")

if __name__ == '__main__':
    refactor_config_imports('.')
