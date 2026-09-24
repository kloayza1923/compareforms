"""Bind each Roboti origin import to a single CompareForms review."""
from alembic import op
import sqlalchemy as sa

revision = "0003_roboti_origin"
down_revision = "0002_aitrol_identity"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("batches", sa.Column("source_batch_id", sa.String(100), nullable=True))
    op.create_unique_constraint("uq_batch_roboti_source", "batches", ["organization_id", "source_batch_id"])

def downgrade():
    raise RuntimeError("Conservar la trazabilidad del origen Roboti; restauración solo mediante plan aprobado.")
