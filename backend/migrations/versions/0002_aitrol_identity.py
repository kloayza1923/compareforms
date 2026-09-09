"""Read-only Aitrol identity memberships; never migrate external passwords."""
from alembic import op
import sqlalchemy as sa

revision = "0002_aitrol_identity"
down_revision = "0001_portal"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("organizations", sa.Column("external_company_id", sa.String(100), nullable=True))
    op.create_unique_constraint("organizations_external_company_id_key", "organizations", ["external_company_id"])
    op.add_column("users", sa.Column("auth_provider", sa.String(24), nullable=False, server_default="local"))
    op.add_column("users", sa.Column("external_user_id", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("external_email", sa.String(254), nullable=True))
    op.create_unique_constraint("uq_user_external_membership", "users", ["auth_provider", "external_user_id", "organization_id"])

def downgrade():
    raise RuntimeError("Conservar trazabilidad de identidades externas; restauración solo mediante plan aprobado.")
