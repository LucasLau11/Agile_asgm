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


def _ensure_notifications_employer_id_column() -> None:
    """create_all() only creates *missing* tables — it never alters an
    existing one. Anyone with a job_portal.db from before the messaging
    module (which added Notification.employer_id) would otherwise hit a
    500 ("table notifications has no column named employer_id") on their
    first message send. This adds the column if it's missing, and is a
    no-op every time after that.
    """
    if not engine.dialect.name == "sqlite":
        return  # only needed for the local sqlite dev DB
    with engine.connect() as conn:
        existing_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(notifications)")
        }
        if "employer_id" not in existing_columns:
            conn.exec_driver_sql("ALTER TABLE notifications ADD COLUMN employer_id INTEGER")
            conn.commit()


_ensure_notifications_employer_id_column()

app.include_router(seeker_router)
app.include_router(applications_router)  
app.include_router(employer_router)
app.include_router(messages_router)

app.mount("/UI", StaticFiles(directory="UI"), name="UI")

os.makedirs("uploads/resumes", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")