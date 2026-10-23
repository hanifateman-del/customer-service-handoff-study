"""只更新项目状态和实验目录表，不进行筛选、标注或摘要生成。"""
from pathlib import Path
from readable_records import refresh_project_indexes


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    refresh_project_indexes(root)
    print("已根据现有文件更新当前状态.md和04_实验记录/README.md。")
