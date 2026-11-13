"""Create a named source archive without local settings, logs or build outputs."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from bulk_mailer import APP_NAME, APP_VERSION


def main():
    root = Path(__file__).resolve().parent
    folder = f"{APP_NAME}-v{APP_VERSION}"
    output = root / 'downloads' / f'{folder}.zip'
    output.parent.mkdir(exist_ok=True)
    files = [root / name for name in (
        'main.py', 'setup.bat', 'start.bat', 'build_exe.py', 'build_exe.bat',
        'build_source_zip.py', 'OutlookMailDesk.spec', 'requirements.txt',
        'requirements-build.txt', 'README.md')]
    for directory in ('bulk_mailer', 'hooks', 'samples', 'docs', 'tests', 'tools'):
        files.extend(p for p in (root / directory).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc')
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, folder + '/' + path.relative_to(root).as_posix())
    print(output)


if __name__ == '__main__':
    main()
