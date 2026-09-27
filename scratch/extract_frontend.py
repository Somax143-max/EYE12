import os

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
index_path = os.path.join(base_dir, 'index.html')
frontend_dir = os.path.join(base_dir, 'frontend')

with open(index_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find <style> and </style> and <script>
style_start = None
style_end = None
script_start = None

for i, line in enumerate(lines):
    if '<style>' in line and style_start is None:
        style_start = i
    elif '</style>' in line and style_end is None:
        style_end = i
    elif '<script>' in line and script_start is None:
        script_start = i

print(f"style_start: {style_start}, style_end: {style_end}, script_start: {script_start}")

# Extract CSS
css_content = "".join(lines[style_start + 1:style_end])
with open(os.path.join(frontend_dir, 'style.css'), 'w', encoding='utf-8') as f:
    f.write(css_content)

# Extract HTML
html_content = "".join(lines[0:style_start])
html_content += '    <link rel="stylesheet" href="style.css">\n'
html_content += '</head>\n'
html_content += "".join(lines[style_end + 1:script_start])
html_content += '    <script src="portal_engine.js"></script>\n'
html_content += '</body>\n</html>\n'

with open(os.path.join(frontend_dir, 'index.html'), 'w', encoding='utf-8') as f:
    f.write(html_content)

# Copy portal_engine.js
with open(os.path.join(base_dir, 'portal_engine.js'), 'r', encoding='utf-8') as f:
    js_content = f.read()

with open(os.path.join(frontend_dir, 'portal_engine.js'), 'w', encoding='utf-8') as f:
    f.write(js_content)

print("Extracted style.css, index.html, and portal_engine.js successfully!")
