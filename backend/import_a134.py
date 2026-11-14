"""Entry point for importing A-134 analysis data into the database."""

from backend.services.import_service import run_import

if __name__ == "__main__":
    run_import()
