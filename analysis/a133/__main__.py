"""Road module a133: read analysis/data/raw/a133/, write analysis/output/a133/.

Run it with: uv run python -m analysis.a133
"""

from .pipeline import run

if __name__ == "__main__":
    run()
