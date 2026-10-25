"""Package installable resources and the repository license; omit runtime data."""
import argparse
from pathlib import Path
import json
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'skills/campus-news-collect'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'dist/campus-news-collect.zip'))
    args = parser.parse_args()
    out = Path(args.output).resolve()
    if out.suffix.lower() != '.zip':
        raise ValueError('输出文件必须使用 .zip 扩展名')
    if not (SOURCE / 'SKILL.md').is_file() or not (ROOT / 'LICENSE').is_file():
        raise ValueError('缺少Skill入口或许可证')
    if out.is_relative_to(SOURCE.resolve()):
        raise ValueError('请将生成的压缩包放在Skill源目录之外')
    files = [p for p in SOURCE.rglob('*') if p.is_file()
        and not p.is_symlink() and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo')]
    out.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(out, 'w', compression=ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, str(Path(SOURCE.name) / path.relative_to(SOURCE)))
        archive.write(ROOT / 'LICENSE', str(Path(SOURCE.name) / 'LICENSE'))
    with ZipFile(out) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('压缩包完整性检查失败')
    print(json.dumps({'package': str(out), 'skill_files': len(files), 'license_included': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
