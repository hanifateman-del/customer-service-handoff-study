r"""兼容整理前的 python .\csds_screen.py 命令；实际程序在03_程序。"""
from pathlib import Path
import runpy
import sys


def forward_arguments(arguments, root):
    """旧 experiments 输出归入04_实验记录，其余参数原样转交。"""
    forwarded = list(arguments)
    changes = []
    for i, argument in enumerate(arguments):
        if argument == "--output" and i + 1 < len(arguments):
            index, value, equals = i + 1, arguments[i + 1], False
        elif argument.startswith("--output="):
            index, value, equals = i, argument.split("=", 1)[1], True
        else:
            continue
        path = Path(value)
        if path.is_absolute():
            try:
                path = path.relative_to(root)
            except ValueError:
                continue
        if path.parts and path.parts[0].lower() == "experiments":
            target = root / "04_实验记录" / Path(*path.parts[1:])
            forwarded[index] = f"--output={target}" if equals else str(target)
            changes.append({"original": value, "resolved": str(target)})
    return forwarded, changes


def main():
    root = Path(__file__).resolve().parent
    program = root / "03_程序" / "csds_screen.py"
    if not program.is_file():
        raise SystemExit(f"找不到实际程序：{program}，请保留项目目录结构。")
    original = list(sys.argv)
    forwarded, changes = forward_arguments(sys.argv[1:], root)
    for change in changes:
        print(f"旧输出目录 {change['original']} 已归入 {change['resolved']}")
    sys.path.insert(0, str(program.parent))
    sys.argv = [str(program), *forwarded]
    runpy.run_path(str(program), run_name="__main__", init_globals={
        "COMPAT_ORIGINAL_ARGV": original,
        "COMPAT_PATH_CHANGES": changes,
    })


if __name__ == "__main__":
    main()
