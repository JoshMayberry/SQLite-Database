import sys
import alembic 
import sqlalchemy
import logging.config

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = alembic.context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
logging.config.fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
sys.path.insert(0, "H:\Python\modules\API_Database\test")
import test_map_2
target_metadata = test_map_2.Mapper.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

writer = alembic.autogenerate.rewriter.Rewriter()

@writer.rewrites(alembic.operations.ops.AddColumnOp)
def add_column(context, revision, op):
	"""
	Modified code from: https://alembic.zzzcomputing.com/en/latest/api/autogenerate.html#fine-grained-autogenerate-generation-with-rewriters

	op.column Equivalent:
		table = Mapper.metadata.tables.get("Customer")
		column = table.columns["name"]
	"""
	column = op.column

	# # print("@2.1", op.column.table.metadata.migrationCatalogue.get(op.table_name, ()))
	# print("@2.2", alembic.operations.ops.AlterColumnOp(op.table_name, column.name, modify_nullable = False, existing_type = column.type))
	# print("@2.3", [alembic.op.execute(command) for command in op.column.table.metadata.migrationCatalogue.get(op.table_name, ())])
	# print("@2.3", [alembic.operations.ops.ExecuteSQLOp(command) for command in op.column.table.metadata.migrationCatalogue.get(op.table_name, ())])
	# # print(dir(alembic.operations.ops))

	# print("@5", list(alembic.operations.ops.PlainText(command) for command in op.column.table.metadata.migrationCatalogue.get(op.table_name, ())))
	# sys.exit()

	if (column.nullable):
		return op
	else:
		column.nullable = True
		
		if (column.table.metadata.bind):
			return [
				op, 
				*(alembic.operations.ops.PlainText(command, args = (op,)) for command in column.table.metadata.migrationCatalogue.get(op.table_name, ())), 
				alembic.operations.ops.AlterColumnOp(op.table_name, column.name, modify_nullable = False, existing_type = column.type)
			]
		else:
			return [
				op, 
				alembic.operations.ops.AlterColumnOp(op.table_name, column.name, modify_nullable = False, existing_type = column.type)
			]

def run_migrations_offline():
	"""Run migrations in 'offline' mode.

	This configures the context with just a URL
	and not an Engine, though an Engine is acceptable
	here as well.  By skipping the Engine creation
	we don't even need a DBAPI to be available.

	Calls to context.execute() here emit the given string to the
	script output.

	"""
	alembic.context.configure(
		url = config.get_main_option("sqlalchemy.url"), 
		target_metadata = target_metadata, 
		literal_binds = True, 
		process_revision_directives = writer,
		render_as_batch = config.get_main_option('sqlalchemy.url').startswith('sqlite:///'),
		)

	with alembic.context.begin_transaction():
		alembic.context.run_migrations()


def run_migrations_online():
	"""Run migrations in 'online' mode.

	In this scenario we need to create an Engine
	and associate a connection with the context.

	"""
	connectable = sqlalchemy.engine_from_config(
		config.get_section(config.config_ini_section),
		prefix='sqlalchemy.',
		poolclass=sqlalchemy.pool.NullPool)

	with connectable.connect() as connection:
		alembic.context.configure(
			connection = connection,
			target_metadata = target_metadata,
			process_revision_directives = writer,
			render_as_batch = config.get_main_option('sqlalchemy.url').startswith('sqlite:///'),
		)

		with alembic.context.begin_transaction():
			alembic.context.run_migrations()

if alembic.context.is_offline_mode():
	run_migrations_offline()
else:
	run_migrations_online()

