import subprocess
import shutil
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9 compatibility
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def test_pyproject_has_release_metadata(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        project = data["project"]

        self.assertEqual(project["name"], "linkray")
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(project["license-files"], ["LICENSE"])
        self.assertIn("authors", project)
        self.assertIn("urls", project)
        self.assertIn("Repository", project["urls"])
        self.assertIn("Issues", project["urls"])

    def test_manifest_lists_release_assets(self):
        manifest = (ROOT / "MANIFEST.in").read_text()

        for item in [
            "include README.md LICENSE install.sh",
            "recursive-include scripts *.sh",
            "recursive-include docs *.md",
            "recursive-include examples *.json",
            "recursive-include templates *",
            "recursive-include patches *",
            "recursive-include assets *",
        ]:
            self.assertIn(item, manifest)

    def test_release_script_builds_and_smoke_tests_wheel(self):
        script = (ROOT / "scripts/build-release.sh").read_text()

        self.assertIn("python3 -m build --sdist --wheel", script)
        self.assertIn('rm -rf "${DIST_DIR}" build *.egg-info', script)
        self.assertIn("python3 -m venv", script)
        self.assertIn("--no-index", script)
        self.assertIn("/venv/bin/pip\" install", script)
        self.assertIn("/venv/bin/linkray\" --help", script)

    def test_build_outputs_include_runtime_and_release_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            shutil.rmtree(ROOT / "build", ignore_errors=True)
            for egg_info in ROOT.glob("*.egg-info"):
                shutil.rmtree(egg_info, ignore_errors=True)
            subprocess.run(
                [sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(out)],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            sdist = next(out.glob("linkray-*.tar.gz"))
            wheel = next(out.glob("linkray-*.whl"))

            with tarfile.open(sdist) as archive:
                sdist_names = set(archive.getnames())
            sdist_suffixes = {"/".join(name.split("/")[1:]) for name in sdist_names}
            for item in [
                "README.md",
                "LICENSE",
                "install.sh",
                "scripts/deploy-rendered-master.sh",
                "docs/DEPLOYMENT.md",
                "examples/master.example.json",
                "templates/marzban/clash/default.yml",
                "patches/marzban-dashboard/current/index.linkray.js",
                "patches/marzban-dashboard/current/linkray-logo.png",
                "patches/marzban-dashboard/source/linkray-dashboard.patch",
                "linkray/assets/marzban-node-host/main.py",
                "linkray/assets/marzban-node-host/xray.py",
            ]:
                self.assertIn(item, sdist_suffixes)

            with zipfile.ZipFile(wheel) as archive:
                wheel_names = set(archive.namelist())
            for item in [
                "linkray/assets/templates/marzban/clash/default.yml",
                "linkray/assets/patches/marzban-dashboard/current/index.linkray.js",
                "linkray/assets/patches/marzban-dashboard/current/linkray-logo.png",
                "linkray/assets/source-patches/marzban-dashboard/linkray-dashboard.patch",
                "linkray/assets/patches/marzban-subscription/current/clash.py",
                "linkray/assets/marzban-node-host/main.py",
                "linkray/assets/marzban-node-host/xray.py",
                "linkray/assets/marzban-node-host/requirements.txt",
            ]:
                self.assertIn(item, wheel_names)
            self.assertNotIn("linkray/assets/marzban-node-host/marzban.service", wheel_names)
            self.assertTrue(any(name.endswith(".dist-info/entry_points.txt") for name in wheel_names))


if __name__ == "__main__":
    unittest.main()
