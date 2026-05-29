import os

TARGET_DIR = "shopsage"

def fix_timezone():
    count = 0
    for root, dirs, files in os.walk(TARGET_DIR):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # if file has datetime.now(timezone.utc) but doesn't import timezone
                if 'timezone.utc' in content:
                    lines = content.split('\n')
                    has_timezone_import = any('import timezone' in line or 'from datetime import timezone' in line for line in lines)
                    
                    if not has_timezone_import:
                        # Find the first 'import ' or 'from ' line and insert before it, 
                        # or just put it after docstring
                        
                        # simpler approach: just add it at the top of the file (after imports block is fine, or literal top)
                        # Let's find first import of datetime
                        for i, line in enumerate(lines):
                            if 'from datetime import' in line:
                                lines[i] = line + ', timezone'
                                break
                        else:
                            # if no 'from datetime import', put it after first line
                            lines.insert(0, "from datetime import timezone")
                        
                        new_content = '\n'.join(lines)
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        print(f"Fixed timezone import in {filepath}")
                        count += 1
    print(f"Fixed {count} files.")

if __name__ == '__main__':
    fix_timezone()
