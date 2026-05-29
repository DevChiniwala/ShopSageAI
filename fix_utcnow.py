import os
import re

TARGET_DIR = "shopsage"

def fix_utcnow():
    pattern = re.compile(r'datetime\.utcnow\(\)')
    replacement = r'datetime.now(datetime.UTC)'
    import_pattern = re.compile(r'(from datetime import.*)(datetime)(.*)')
    
    count = 0
    for root, dirs, files in os.walk(TARGET_DIR):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if 'datetime.utcnow()' in content:
                    # Also make sure to import datetime or adjust the import if it's just `from datetime import datetime`
                    # The easiest robust way is just replacing `datetime.utcnow()` with `datetime.now(timezone.utc)`
                    # and ensuring `from datetime import timezone` exists.
                    
                    # Wait, if we use `datetime.UTC` (Python 3.11+), it doesn't need timezone import if datetime is imported!
                    # Actually `datetime.now(timezone.utc)` is safer for older pythons.
                    # Let's use `datetime.now(timezone.utc)` and inject `from datetime import timezone`.
                    
                    new_content = content.replace('datetime.utcnow()', 'datetime.now(timezone.utc)')
                    if 'from datetime import timezone' not in new_content and 'timezone' not in new_content:
                        # try to add it near the other datetime imports
                        if 'from datetime import' in new_content:
                            new_content = re.sub(r'(from datetime import.*)', r'\1, timezone', new_content, count=1)
                        else:
                            new_content = 'from datetime import timezone\n' + new_content

                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"Fixed {filepath}")
                    count += 1
    print(f"Fixed {count} files.")

if __name__ == '__main__':
    fix_utcnow()
