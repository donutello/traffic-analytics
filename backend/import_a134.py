"""Entry point for importing A-134 analysis data into the database."""

from backend.importer.services.a134 import run_import

if __name__ == "__main__":
    run_import()
