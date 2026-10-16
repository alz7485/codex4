"""Check distribution orchestration with a fake builder, not a Windows build."""
import runpy
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

import build_exe


class DistributionAuditTests(unittest.TestCase):
    def test_windows_only_build_refuses_other_platforms(self):
        with patch.object(build_exe.sys, "platform", "linux"), self.assertRaisesRegex(SystemExit, "Windows"):
            build_exe.main()

    def test_spec_has_collect_and_excludes_binaries_from_windowed_exe(self):
        root = Path(build_exe.__file__).resolve().parent
        analysis = Mock(return_value=SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[]))
        exe, collect = Mock(), Mock()
        runpy.run_path(str(root / "OutlookMailDesk.spec"), init_globals={
            "SPECPATH": str(root), "Analysis": analysis, "PYZ": Mock(), "EXE": exe, "COLLECT": collect,
        })
        self.assertTrue(exe.call_args.kwargs["exclude_binaries"])
        self.assertFalse(exe.call_args.kwargs["console"])
        self.assertEqual(exe.call_args.kwargs["contents_directory"], "_internal")
        self.assertEqual(collect.call_args.kwargs["name"], "OutlookMailDesk")
        self.assertTrue(Path(exe.call_args.kwargs["icon"]).is_file())
        for source, _ in analysis.call_args.kwargs["datas"]:
            self.assertTrue(Path(source).exists())
        self.assertIn(str(root / "hooks"), analysis.call_args.kwargs["hookspath"])

    def test_dnd_hook_collects_native_libraries_and_tcl_scripts(self):
        try:
            import PyInstaller.utils.hooks
        except ImportError:
            self.skipTest("Native dependency collection requires requirements-build.txt")
        root = Path(build_exe.__file__).resolve().parent
        result = runpy.run_path(str(root / "hooks" / "hook-tkinterdnd2.py"))
        destinations = set()
        for source, folder in result["datas"]:
            self.assertTrue(Path(source).is_file())
            destinations.add((Path(folder) / Path(source).name).as_posix())
        for architecture in ("win-x64", "win-x86", "win-arm64"):
            prefix = f"tkinterdnd2/tkdnd/{architecture}/"
            self.assertIn(prefix + "pkgIndex.tcl", destinations)
            self.assertIn(prefix + "tkdnd.tcl", destinations)
            self.assertTrue(any(path.startswith(prefix) and path.endswith(".dll") for path in destinations))

    def test_packaged_readme_samples_docs_and_runtime_are_in_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "samples").mkdir()
            (root / "docs" / "previews").mkdir(parents=True)
            (root / "README.md").write_text("test documentation", encoding="utf-8")
            (root / "samples" / "example.txt").write_text("test sample", encoding="utf-8")
            (root / "docs" / "previews" / "review.png").write_bytes(b"test fixture, not a real image")

            def fake_build(_):
                output = root / "dist" / "OutlookMailDesk"
                (output / "_internal").mkdir(parents=True)
                (output / "OutlookMailDesk.exe").write_bytes(b"test fixture, not a real executable")
                (output / "_internal" / "fixture.dll").write_bytes(b"test library fixture")

            module = ModuleType("PyInstaller.__main__")
            module.run = fake_build
            with patch.dict("sys.modules", {"PyInstaller": ModuleType("PyInstaller"), "PyInstaller.__main__": module}), \
                 patch.object(build_exe, "__file__", str(root / "build_exe.py")), \
                 patch.object(build_exe.sys, "platform", "win32"), patch("builtins.print"):
                build_exe.main()
            with ZipFile(root / "dist" / "OutlookMailDesk-windows-onedir.zip") as archive:
                for name in ("OutlookMailDesk.exe", "_internal/fixture.dll", "README.md",
                             "samples/example.txt", "docs/previews/review.png"):
                    self.assertIn("OutlookMailDesk/" + name, archive.namelist())
