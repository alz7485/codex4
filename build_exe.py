"""Build a windowed Windows application as a PyInstaller onedir distribution."""
from pathlib import Path
import shutil
import sys


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Windows上で実行してください。Windows EXEのクロスビルドには対応していません。")
    try:
        from PyInstaller.__main__ import run
    except ImportError:
        raise SystemExit("先に pip install -r requirements-build.txt を実行してください。")
    root = Path(__file__).resolve().parent
    run(["--noconfirm", "--clean", "--distpath", str(root / "dist"),
         "--workpath", str(root / "build"), str(root / "OutlookMailDesk.spec")])
    output = root / "dist" / "OutlookMailDesk"
    if not (output / "OutlookMailDesk.exe").is_file() or not (output / "_internal").is_dir():
        raise SystemExit("onedirの出力が確認できません。ビルドログを確認してください。")
    shutil.copy2(root / "README.md", output / "README.md")
    shutil.copytree(root / "samples", output / "samples", dirs_exist_ok=True)
    shutil.copytree(root / "docs", output / "docs", dirs_exist_ok=True)
    archive = shutil.make_archive(str(root / "dist" / "OutlookMailDesk-windows-onedir"), "zip",
                                  root_dir=output.parent, base_dir=output.name)
    print(f"\nCreated: {output / 'OutlookMailDesk.exe'}")
    print(f"Distribution ZIP: {archive}")
    print("Distribute the entire OutlookMailDesk folder, including _internal.")


if __name__ == "__main__":
    main()
