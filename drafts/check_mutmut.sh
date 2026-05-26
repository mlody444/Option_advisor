#!/usr/bin/env bash
# Run mutation testing. Must be run from the project root.
# Venv lives in ~/.venv-option-advisor (WSL native filesystem — avoids /mnt/ limitations).

set -e

VENV="$HOME/.venv-option-advisor"
PYTHON_VERSION=$(cut -d. -f1-2 .python-version)

# find WSL-native python — skip Windows shims mounted under /mnt/
PYTHON_BIN=$(which -a "python${PYTHON_VERSION}" 2>/dev/null | grep -v '^/mnt/' | head -1)
if [ -z "$PYTHON_BIN" ]; then
    echo "FAILED - python${PYTHON_VERSION} not found in WSL. Install it with: sudo apt install python${PYTHON_VERSION} python${PYTHON_VERSION}-venv"
    exit 1
fi

if [ ! -d "$VENV" ]; then
    echo "Creating WSL virtual environment using $PYTHON_BIN..."
    "$PYTHON_BIN" -m venv "$VENV"
fi

# always sync dev dependencies from pyproject.toml — fast when nothing changed
echo "Syncing dev dependencies from pyproject.toml..."
"$VENV/bin/python" - <<'EOF'
import tomllib, subprocess, sys
with open("pyproject.toml", "rb") as f:
    dev = tomllib.load(f)["project"]["optional-dependencies"]["dev"]
subprocess.run([sys.executable, "-m", "pip", "install", "--quiet"] + dev, check=True)
EOF

source "$VENV/bin/activate"
set +e
python -m mutmut run
MUTMUT_EXIT=$?
set -e

python - <<'PYEOF'
import subprocess, re, ast
from collections import defaultdict

def parse_ids(text):
    ids = []
    for part in text.replace(' ', '').split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            if a.isdigit() and b.isdigit():
                ids.extend(range(int(a), int(b) + 1))
        elif part.isdigit():
            ids.append(int(part))
    return ids

def build_func_map(source_file):
    with open(source_file) as f:
        tree = ast.parse(f.read())
    funcs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((node.lineno, node.end_lineno, node.name))
    return sorted(funcs)

def func_at_line(func_map, line_no):
    for start, end, name in func_map:
        if start <= line_no <= end:
            return name
    return 'module_level'

func_map = build_func_map('drafts/ibkr_utils.py')

def parse_show(mid):
    out = subprocess.run(["mutmut", "show", str(mid)], capture_output=True, text=True).stdout
    func_name = 'module_level'
    diff = []
    for line in out.splitlines():
        if line.startswith('@@'):
            m = re.search(r'@@ -(\d+)', line)
            if m:
                func_name = func_at_line(func_map, int(m.group(1)))
        elif (line.startswith('-') or line.startswith('+')) \
                and not line.startswith('---') and not line.startswith('+++'):
            diff.append(line)
    return mid, func_name, diff

def fetch_all(ids):
    from concurrent.futures import ThreadPoolExecutor
    results = {}
    with ThreadPoolExecutor(max_workers=16) as executor:
        for mid, func_name, diff in executor.map(parse_show, ids):
            results[mid] = (func_name, diff)
    return results

results = subprocess.run(["mutmut", "results"], capture_output=True, text=True).stdout

survived, suspicious = [], []
current = None
for line in results.splitlines():
    if 'Survived' in line:
        current = survived
    elif 'Suspicious' in line:
        current = suspicious
    elif current is not None and '----' not in line and line.strip():
        current.extend(parse_ids(line.strip()))

all_ids = survived + suspicious
show_data = fetch_all(all_ids) if all_ids else {}

def print_group(ids, label):
    if not ids:
        return {}
    func_counts = defaultdict(int)
    print(f"\n  {label}:\n")
    for mid in ids:
        func_name, diff = show_data[mid]
        func_counts[func_name] += 1
        print(f"  #{mid}  {func_name}")
        for line in diff:
            print(f"      {line}")
        print()
    return func_counts

print()
print("=" * 60)
print("  Mutation Testing Summary")
print("=" * 60)
print(f"  Survived:    {len(survived)}  (tests need to be expanded)")
print(f"  Suspicious:  {len(suspicious)}  (tests ran slow)")
print(f"  Killed:      see run output above")
print("=" * 60)

survived_counts = print_group(survived, "Survived mutations -- add tests to kill these")
suspicious_counts = print_group(suspicious, "Suspicious mutations")

all_counts = defaultdict(int)
for counts in [survived_counts, suspicious_counts]:
    for fn, n in counts.items():
        all_counts[fn] += n

if all_counts:
    print("=" * 60)
    print("  Issues per function")
    print("=" * 60)
    for fn, n in sorted(all_counts.items(), key=lambda x: -x[1]):
        print(f"  {fn:<30} {n} issue{'s' if n != 1 else ''}")
    print("=" * 60)
PYEOF

exit $MUTMUT_EXIT
