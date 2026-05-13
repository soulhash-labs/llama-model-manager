import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class InstalledWheelCliSmokeTests(unittest.TestCase):
    """
    End-to-end installed-wheel smoke test.

    This test intentionally builds a wheel, installs it into a temporary venv,
    and exercises the `glyphos-route` console script.
    """

    def test_installed_wheel_cli(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent

        with tempfile.TemporaryDirectory(prefix="glyphos-wheel-smoke-") as tmp:
            tmp_path = Path(tmp)
            venv_dir = tmp_path / "venv"
            dist_dir = repo_root / "dist"

            if dist_dir.exists():
                shutil.rmtree(dist_dir)

            subprocess.run(
                [sys.executable, "-m", "venv", str(venv_dir)],
                check=True,
                cwd=repo_root,
            )

            if os.name == "nt":
                python_bin = venv_dir / "Scripts" / "python.exe"
                pip_bin = venv_dir / "Scripts" / "pip.exe"
                glyphos_route = venv_dir / "Scripts" / "glyphos-route.exe"
            else:
                python_bin = venv_dir / "bin" / "python"
                pip_bin = venv_dir / "bin" / "pip"
                glyphos_route = venv_dir / "bin" / "glyphos-route"

            subprocess.run(
                [str(python_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", "build"],
                check=True,
                cwd=repo_root,
            )

            subprocess.run(
                [str(python_bin), "-m", "build"],
                check=True,
                cwd=repo_root,
            )

            wheels = sorted(dist_dir.glob("*.whl"))
            self.assertTrue(wheels, "No wheel produced in dist/")
            wheel_path = wheels[-1]

            subprocess.run(
                [str(pip_bin), "install", str(wheel_path)],
                check=True,
                cwd=repo_root,
            )

            self.assertTrue(glyphos_route.exists(), "glyphos-route entry point missing")

            status_out = subprocess.run(
                [str(glyphos_route), "--status", "--json"],
                check=True,
                capture_output=True,
                text=True,
                cwd=repo_root,
            ).stdout
            status = json.loads(status_out)
            self.assertIn("preferred_local_backend", status)
            self.assertIn("available_backends", status)

            route_out = subprocess.run(
                [
                    str(glyphos_route),
                    "--action",
                    "QUERY",
                    "--destination",
                    "MODEL",
                    "--psi",
                    "0.8",
                    "--time-slot",
                    "7",
                    "--show-prompt",
                    "--show-structured",
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=repo_root,
            ).stdout
            route_payload = json.loads(route_out)
            self.assertEqual(route_payload["decoded_packet"]["action"], "QUERY")
            self.assertEqual(route_payload["decoded_packet"]["destination"], "MODEL")
            self.assertNotIn("[CONTEXT_ANCHOR]", route_payload["prompt"])

            ctx_json = json.dumps(
                {
                    "content": "LANE_STATE(AURORA): healthy",
                    "locality": "orion-local",
                    "routing_hints": {"preferred_backend": "llamacpp", "token_budget": 2048},
                }
            )

            route_ctx_out = subprocess.run(
                [
                    str(glyphos_route),
                    "--action",
                    "QUERY",
                    "--destination",
                    "MODEL",
                    "--psi",
                    "0.8",
                    "--time-slot",
                    "7",
                    "--upstream-context-json",
                    ctx_json,
                    "--show-prompt",
                    "--show-structured",
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=repo_root,
            ).stdout
            route_ctx_payload = json.loads(route_ctx_out)

            self.assertTrue(route_ctx_payload["upstream_context_provided"])
            self.assertIn("[CONTEXT_ANCHOR]", route_ctx_payload["prompt"])
            self.assertIn("LANE_STATE(AURORA): healthy", route_ctx_payload["prompt"])
            self.assertEqual(
                route_ctx_payload["structured"]["routing"]["preferred_backend"],
                "llamacpp",
            )


if __name__ == "__main__":
    unittest.main()
