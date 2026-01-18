"""Helper script to launch the Streamlit UI."""

import os
import subprocess
import sys
from pathlib import Path


def main():
    """Launch the Streamlit application."""
    app_path = Path(__file__).parent / "app.py"
    project_root = Path(__file__).parent.parent

    # Set up environment with project root in PYTHONPATH
    env = os.environ.copy()
    python_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{project_root}{os.pathsep}{python_path}" if python_path else str(project_root)

    # Run streamlit with the app
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
        ],
        env=env,
    )


if __name__ == "__main__":
    main()
