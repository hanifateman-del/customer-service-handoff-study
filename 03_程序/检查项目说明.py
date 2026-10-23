"""检查当前阅读材料的本地链接、旧目录引用和历史运行文件完整性。"""
from pathlib import Path
import json
import re
import sys
import hashlib


def check(root):
    errors = []
    documents = []
    for path in root.rglob('*.md'):
        parts = path.relative_to(root).parts
        if any(v in parts for v in ('.git', '__pycache__')):
            continue
        if '修改前' in parts and path.name != '历史原件说明.md':
            continue
        if parts[0] == '99_临时文件' and path != root / '99_临时文件/README.md':
            continue
        documents.append(path)
        text = path.read_text(encoding='utf-8-sig')
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if target.startswith(('https:', 'http:', '#', 'mailto:')):
                continue
            target = target.split('#', 1)[0]
            if not (path.parent / target).exists():
                errors.append(f'{path.relative_to(root)}：链接不存在 {target}')
    # 历史说明允许保留旧名称；当前操作手册不得依赖原持有者电脑的路径。
    active = [root/'README.md', root/'03_程序/运行说明.md', root/'05_人工标注/README.md', root/'05_人工标注/标注怎么填.md']
    for path in active:
        if re.search(r'[A-Za-z]:[\\/]Users[\\/]', path.read_text(encoding='utf-8')):
            errors.append(f'{path.relative_to(root)}：当前操作说明仍含个人电脑绝对路径')
    verified = 0
    for path in root.rglob('run_record.json'):
        parts = path.relative_to(root).parts
        if '修改前' in parts or parts[0] == '99_临时文件':
            continue
        record = json.loads(path.read_text(encoding='utf-8-sig'))
        expected = set()
        for item in record.get('files', []):
            target = (path.parent / item['path']).resolve()
            if not target.is_relative_to(path.parent.resolve()):
                errors.append(f'{path.relative_to(root)}：清单路径越界')
                continue
            expected.add(target)
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != item['sha256']:
                errors.append(f'{target.relative_to(root)}：与运行清单不一致')
        actual = {p.resolve() for p in path.parent.rglob('*') if p.is_file() and p != path}
        if actual != expected:
            errors.append(f'{path.parent.relative_to(root)}：文件数量与运行清单不一致')
        verified += 1
    return errors, len(documents), verified


if __name__ == '__main__':
    root = Path(__file__).resolve().parent.parent
    errors, docs, runs = check(root)
    if errors:
        print('\n'.join(errors))
        raise SystemExit(1)
    print(f'检查通过：{docs}份当前阅读材料链接有效，{runs}份运行清单一致；当前使用说明没有个人电脑绝对路径。')
