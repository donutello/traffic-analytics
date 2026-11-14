"""Query parameter helpers shared by the feature controllers."""

from typing import Annotated

import libsql
from fastapi import Depends, Query

from backend.db import get_db

Db = Annotated[libsql.Connection, Depends(get_db)]
FromParam = Annotated[str | None, Query(alias="from", description="date or ISO 8601 time")]
ToParam = Annotated[str | None, Query(alias="to", description="date or ISO 8601 time")]
