"""Import the road modules' results from analysis/output/ into the database.

    uv run python -m backend.load            # every road directory under analysis/output/
    uv run python -m backend.load _example   # one road by name

This file is only the command; the work is in backend/importer/ (docs/adr/0009).
A road is read with contract.validate.read_road and loaded only when its files follow the
contract: errors are printed and nothing at all is loaded for that road. Loading a road
first deletes its old rows, so running the import twice changes nothing, and every road
is loaded inside one transaction: either all of its rows are in, or none.

corporate_anomalies.json is optional (read_road checks it only when the file is there).
When it is, its items are imported like ours, only with source='corporate'.
"""

import sys

from backend.importer.services import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
