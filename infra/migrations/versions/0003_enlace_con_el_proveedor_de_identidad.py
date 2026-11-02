"""enlace con el proveedor de identidad

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('external_subject', sa.String(length=255), nullable=True))
        batch.create_unique_constraint('uq_users_external_subject', ['external_subject'])


def downgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.drop_constraint('uq_users_external_subject', type_='unique')
        batch.drop_column('external_subject')
