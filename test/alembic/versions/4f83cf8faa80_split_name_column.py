"""split name column

Revision ID: 4f83cf8faa80
Revises: 
Create Date: 2018-10-05 15:53:12.996932

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4f83cf8faa80'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
	with op.batch_alter_table('Customer', schema = None) as batch_op:
		batch_op.add_column(sa.Column('first_name', sa.Unicode(), nullable = True))
		batch_op.add_column(sa.Column('last_name', sa.Unicode(), nullable = True))
		
	connection = op.get_bind()
	if (False):
		#One way to do it, but cant generate SQL for you
		update_sql = sa.text("""UPDATE Customer
			SET first_name = :first, last_name = :last
			WHERE id = :id""")

		for customer in connection.execute("SELECT name, id FROM Customer"):
			first, last = customer.name.split(' ', 1)
			connection.execute(update_sql, last = last, first = first, id = customer.id)
	else:
		#Better way: Don't use results from a SELECT statement
		connection.execute("""UPDATE Customer
			SET first_name = SUBSTR(name, 0, instr(name, ' ')),
			last_name = SUBSTR(name, instr(name, ' ') + 1)""")


	with op.batch_alter_table('Customer', schema = None) as batch_op:
		batch_op.alter_column('first_name', existing_type = sa.Unicode(), nullable = False)
		batch_op.alter_column('last_name', existing_type = sa.Unicode(), nullable = False)

def downgrade():
	with op.batch_alter_table('Customer', schema=None) as batch_op:
		batch_op.drop_column('last_name')
		batch_op.drop_column('first_name')
