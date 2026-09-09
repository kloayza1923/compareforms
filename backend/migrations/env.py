from alembic import context
from app.config import Settings
from app.db import Base, connect

engine, _ = connect(Settings())
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction(): context.run_migrations()
