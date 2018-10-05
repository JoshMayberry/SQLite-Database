import sys
import sqlalchemy
import sqlalchemy.ext.declarative

from datetime import datetime

import API_Database as Database

Mapper = Database.makeBase()

class Customer(Mapper, Database.Schema_Base):
	__tablename__ = 'Customer'

	id 				= sqlalchemy.Column(sqlalchemy.Integer, primary_key = True, autoincrement = True)
	# name 			= sqlalchemy.Column(sqlalchemy.Unicode, nullable = False)
	first_name 		= sqlalchemy.Column(sqlalchemy.Unicode, nullable = False)
	last_name 		= sqlalchemy.Column(sqlalchemy.Unicode, nullable = False)

relationCatalogue = {item.__name__: item for item in Database.Schema_Base.__subclasses__()}
hasForeignCatalogue = {item.__name__: item for item in Database.Schema_AutoForeign.__subclasses__()}

for module in hasForeignCatalogue.values():
	module.formatForeign(relationCatalogue)

if __name__ == '__main__':
	"""
	Special thanks to OrangeTux for how to get schema class from tablename on: https://stackoverflow.com/questions/11668355/sqlalchemy-get-model-from-table-name-this-may-imply-appending-some-function-to/23754464#23754464
	Modified code from: https://stackoverflow.com/questions/24622170/using-alembic-api-from-inside-application-code/43530495#43530495
	Modified code from: https://www.youtube.com/watch?v=xzsbHMHYI5c
	"""

	import os
	import inspect
	import argparse
	import alembic.config
	import alembic.command

	from alembic.config import Config as alembic_config_Config

	#Monkey Patches
	def mp_get_template_directory(self):
		return "H:/Python/modules/API_Database/alembic_templates"
	alembic_config_Config.get_template_directory = mp_get_template_directory

	def mp__generate_template(self, source, destination, **kwargs):
		if (source.endswith("alembic.ini.mako")):
			kwargs["database_location"] = database_location
		return old__generate_template(self, source, destination, **kwargs)
	old__generate_template = alembic.command.ScriptDirectory._generate_template
	alembic.command.ScriptDirectory._generate_template = mp__generate_template

	def mp__copy_file(self, source, destination):
		"""Special thanks to shackra for how to import metadata correctly on https://stackoverflow.com/questions/32032940/how-to-import-the-own-model-into-myproject-alembic-env-py/32218546#32218546"""
		
		if (not source.endswith('env.py.mako')):
			return old__copy_file(self, source, destination)

		imports = f'sys.path.insert(0, "{this_file_directory}")\nimport test_map_2\ntarget_metadata = test_map_2.Mapper.metadata'

		old__generate_template(self, source, destination.rstrip(".mako"), imports = imports)
	old__copy_file = alembic.command.ScriptDirectory._copy_file
	alembic.command.ScriptDirectory._copy_file = mp__copy_file

	def mp_rev_id():
		"""Make Revision IDs sequential"""
		answer = old_rev_id()
		print("@1", answer)
		n = len(tuple(None for item in os.scandir(version_directory) if (item.is_file())))
		return f"{n:03d}_{answer}"
	old_rev_id= alembic.util.rev_id
	alembic.util.rev_id = mp_rev_id


	#Setup
	this_file_directory = os.path.dirname(os.path.abspath(inspect.stack()[0][1]))
	alembic_directory   = os.path.join(this_file_directory, "alembic")
	version_directory   = os.path.join(alembic_directory, "versions")
	ini_path            = os.path.join(this_file_directory, "alembic.ini")
	database_location = "sqlite:///test_map_example.db"

	config = alembic_config_Config(ini_path)
	config.set_main_option("script_location", alembic_directory)
	config.set_main_option("sqlalchemy.url", database_location)

	def createNew():
		### FOR DEBUGGING ###
		engine = sqlalchemy.create_engine(database_location)
		Mapper.metadata.bind = engine
		Mapper.metadata.reflect()

		Mapper.metadata.drop_all()
		Mapper.metadata.create_all()
		for relationHandle in relationCatalogue.values():
			relationHandle.reset()

		sessionMaker = sqlalchemy.orm.sessionmaker()
		DBSession = sqlalchemy.orm.sessionmaker(bind = engine)
		session = DBSession()

		session.add(Customer(id = 1, name = "Mickey Mouse"))
		session.add(Customer(id = 2, name = "Donald Duck"))
		session.commit()
		### END DEBUGGING ###

		alembic.command.init(config, alembic_directory, template = "custom")

	def revision(migrationCatalogue = None, autoStamp = False):
		"""
		Example Input: revision()
		Example Input: revision(migrationCatalogue = {"Customer": ("print(123)", "print(456)",)})
		Example Input: revision(migrationCatalogue = {"Customer": (("print(123)", "print(456)"),)})
		Example Input: revision(migrationCatalogue = {"Customer": (("print('Lorem')", "print('Ipsum')"), ("print('Dolor')"))})
		Example Input: revision(migrationCatalogue = {"Customer": (test,)})
		"""

		if (autoStamp):
			stamp("head")

		Mapper.metadata.migrationCatalogue.clear()
		Mapper.metadata.migrationCatalogue.update(migrationCatalogue or {})
		alembic.command.revision(config, autogenerate = True, message = "split name column")

	def upgrade(target = "+1", sql = False):
		"""
		Example Input: upgrade()
		Example Input: upgrade("head")
		Example Input: upgrade("+2")
		Example Input: upgrade("4f83cf8faa80")
		Example Input: upgrade("4f8")
		Example Input: upgrade("4f8+2")
		"""
		alembic.command.upgrade(config, target, sql = sql, tag = None)

	def downgrade(target = "-1", sql = False):
		"""
		Example Input: downgrade()
		Example Input: downgrade("base")
		Example Input: downgrade("-2")
		"""
		alembic.command.downgrade(config, target, sql = sql, tag = None)

	def history():
		alembic.command.history(config, rev_range = None, verbose = False, indicate_current = False)

	def stamp(revision, sql = False):
		alembic.command.stamp(config, revision, sql = sql, tag = None)


	def test(operation):
		column = operation.column
		if (column.name == "first_name"):
			def nested(*args):
				## START ##
				connection = op.get_bind()
				update_sql = sa.text("""UPDATE Customer
					SET first_name = :first
					WHERE id = :id""")

				for customer in connection.execute("SELECT name, id FROM Customer"):
					first, last = customer.name.split(' ', 1)
					connection.execute(update_sql, first = first, id = customer.id)
				## STOP ##
				return
		
		elif (column.name == "last_name"):
			def nested(*args):
				## START ##
				connection = op.get_bind()
				update_sql = sa.text("""UPDATE Customer
					SET last_name = :last
					WHERE id = :id""")

				for customer in connection.execute("SELECT name, id FROM Customer"):
					first, last = customer.name.split(' ', 1)
					connection.execute(update_sql, last = last, id = customer.id)
				## STOP ##
				return
		
		else:
			nested = ""
		
		return nested

	# createNew()
	revision()
	# upgrade()
	# upgrade(sql = True)
	# history()
	# downgrade()


	# engine = sqlalchemy.create_engine(database_location)
	# Mapper.metadata.bind = engine
	# Mapper.metadata.reflect()

	# table = Mapper.metadata.tables.get("Customer")
	# column = table.columns["name"]



	# print(column.table.metadata.migrationCatalogue)










	# columnSchema = Mapper._decl_class_registry[column.table.name]
	# print(columnSchema.getMigrationFunctions())






	# sessionMaker = sqlalchemy.orm.sessionmaker()
	# DBSession = sqlalchemy.orm.sessionmaker(bind = engine)
	# session = DBSession()

	# query = session.query(Customer)
	# container = query.first()
	# print([container.name])






