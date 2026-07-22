import os
import sys

# Ensure python runtime environment resolves packages seamlessly across cross-mounted sub-folders
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from job_portal.database import Base, engine
from job_portal.routes.seeker import router as seeker_router
from job_portal.routes.applications import router as applications_router  
from job_portal.routes.employer import router as employer_router
from job_portal.routes.messages import router as messages_router

app = FastAPI(title="Job Portal Architecture", version="0.1.0")

Base.metadata.create_all(bind=engine)


def _ensure_columns(table: str, columns: dict) -> None:
    """create_all() only creates *missing* tables — it never alters an
    existing one. Anyone with a job_portal.db from before a given column
    was added (e.g. Notification.employer_id from the messaging module, or
    the edit/delete/attachment columns added to Message afterwards) would
    otherwise hit a 500 on first use. This adds any missing columns and is
    a no-op every time after that.
    """
    if engine.dialect.name != "sqlite":
        return  # only needed for the local sqlite dev DB
    with engine.connect() as conn:
        existing_columns = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}")
        conn.commit()


_ensure_columns("notifications", {"employer_id": "INTEGER"})
_ensure_columns(
    "messages",
    {
        "edited_at": "DATETIME",
        "is_deleted": "INTEGER DEFAULT 0",
        "deleted_for_seeker": "INTEGER DEFAULT 0",
        "deleted_for_employer": "INTEGER DEFAULT 0",
        "attachment_filename": "VARCHAR(255)",
        "attachment_url": "VARCHAR(500)",
        "attachment_type": "VARCHAR(20)",
    },
)
_ensure_columns(
    "conversations",
    {
        "hidden_for_seeker": "INTEGER DEFAULT 0",
        "hidden_for_employer": "INTEGER DEFAULT 0",
    },
)

app.include_router(seeker_router)
app.include_router(applications_router)  
app.include_router(employer_router)
app.include_router(messages_router)

app.mount("/UI", StaticFiles(directory="UI"), name="UI")

os.makedirs("uploads/resumes", exist_ok=True)
os.makedirs("uploads/messages", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")