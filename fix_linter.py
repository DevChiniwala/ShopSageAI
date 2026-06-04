import re

def fix_file(filepath, replacements):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    for old, new in replacements:
        content = content.replace(old, new)
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

# Fix f-strings without placeholders
fix_file(r'shopsage\history\exporter.py', [
    ('f"timestamp"', '"timestamp"'),
    ('f"role"', '"role"'),
    ('f"content"', '"content"'),
    ('f"route"', '"route"'),
    ('f"---"', '"---"'),
    ('f"Session Start"', '"Session Start"'),
    ('f"**"', '"**"'),
    ('f"\n"', '"\n"'),
])

fix_file(r'shopsage\monitoring\sentry_integration.py', [
    ('f"ShopSage Backend started"', '"ShopSage Backend started"'),
])

fix_file(r'shopsage\tool\price_scraper.py', [
    ('f"Could not extract products"', '"Could not extract products"'),
])

# Fix unused vars
fix_file(r'shopsage\workers\tasks.py', [
    ('store = WebhookStore(db_path=settings.DB_PATH)', '# WebhookStore not needed here'),
])

fix_file(r'shopsage\tool\preference_tool.py', [
    ('profile = profile_store.get_profile(session_id)', '# profile fetched implicitly or not needed'),
])

print("Fixes applied.")
