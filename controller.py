__version__ = "3.4.0"

## TO DO ##
# - Add a foreign key cleanup command; removes unused foreign keys in foreign tables

#Standard Modules
import re
import os
import sys
import time
import shutil

import types
import decimal

#Utility Modules
import inspect
import datetime
import warnings
import traceback
import importlib
import itertools
import functools
import cachetools
import contextlib
import collections

#Database Modules
import pyodbc
import sqlite3
import sqlalchemy
import sqlalchemy.ext.declarative

import alembic
import alembic.config
import alembic.command
from alembic.config import Config as alembic_config_Config

#For multi-threading
import threading
from forks.pypubsub.src.pubsub import pub as pubsub_pub #Use my own fork

sessionMaker = sqlalchemy.orm.sessionmaker()

#Required Modules
##py -m pip install
	# sqlite3
	# pyodbc
	# sqlalchemy
	# alembic

#Debugging functions
def printCurrentTrace(printout = True, quitAfter = False):
	"""Prints out the stack trace for the current place in the program.
	Modified Code from codeasone on https://stackoverflow.com/questions/1032813/dump-stacktraces-of-all-active-threads

	Example Input: printCurrentTrace()
	Example Input: printCurrentTrace(quitAfter = True)
	"""

	code = []
	for threadId, stack in sys._current_frames().items():
		code.append("\n# ThreadID: %s" % threadId)
		for fileName, lineno, name, line in traceback.extract_stack(stack):
			code.append('File: "%s", line %d, in %s' % (fileName,
														lineno, name))
			if (line):
				code.append("  %s" % (line.strip()))

	try:
		if (printout):
			for line in code:
				print (line)
		else:
			return code
	finally:
		if (quitAfter):
			sys.exit()

#Iterators
class Iterator(object):
	"""Used by handle objects to iterate over their nested objects."""

	def __init__(self, data, filterNone = False):
		if (not isinstance(data, (list, dict))):
			data = data[:]

		self.data = data
		if (isinstance(self.data, dict)):
			self.order = list(self.data.keys())

			if (filterNone):
				self.order = [key for key in self.data.keys() if key is not None]
			else:
				self.order = [key if key is not None else "" for key in self.data.keys()]

			self.order.sort()

			self.order = [key if key != "" else None for key in self.order]

	def __iter__(self):
		return self

	def __next__(self):
		if (not isinstance(self.data, dict)):
			if not self.data:
				raise StopIteration

			return self.data.pop()
		else:
			if not self.order:
				raise StopIteration

			key = self.order.pop()
			return self.data[key]

#Decorators
def wrap_errorCheck(fileName = "error_log.log", timestamp = True, raiseError = True):
	def decorator(function):
		@functools.wraps(function)
		def wrapper(self, *args, **kwargs):
			"""Logs errors.

			Example Usage: @wrap_errorCheck()
			"""

			try:
				answer = function(self, *args, **kwargs)
			except SystemExit:
				self.closeDatabase()
				sys.exit()
			except Exception as error:
				answer = None
				errorMessage = traceback.format_exc()
				
				if (not raiseError):
					print(errorMessage)
				try:
					with open(fileName, "a") as fileHandle:
						if (timestamp):
							content = f"{time.strftime('%Y/%m/%d %H:%M:%S', time.localtime())} --- "
						else:
							content = ""

						content += "\n\targs: "
						content += ", " .join([f"{item}" for item in args])
						
						content += "\n\tkwargs: "
						content += ", " .join([f"{key}: {value}" for key, value in kwargs.items()])
						
						content += "\n\terror: "
						content += errorMessage
						
						fileHandle.write(content)
						fileHandle.write("\n")
				except:
					traceback.print_exc()

				if (raiseError):
					self.closeDatabase()
					raise error

			return answer
		return wrapper
	return decorator

#Custom Types
class _set(set):
	def append(self, *args, **kwargs):
		return self.add(*args, **kwargs)

#Utility Classes
class Base():
	@classmethod
	def ensure_set(cls, item, convertNone = False):
		"""Makes sure the given item is a set.

		Example Input: ensure_set(exclude)
		Example Input: ensure_set(exclude, convertNone = True)
		"""

		if (item is not None):
			if (isinstance(item, (str, int, float))):
				return {item}
			elif (not isinstance(item, set)):
				return set(item)
			return item

		if (convertNone):
			return set()

	@classmethod
	def ensure_list(cls, item, convertNone = False):
		"""Makes sure the given item is a list.

		Example Input: ensure_list(exclude)
		Example Input: ensure_list(exclude, convertNone = True)
		"""

		if (item is not None):
			if (isinstance(item, (str, int, float))):
				return [item]
			elif (not isinstance(item, list)):
				return list(item)
			return item

		if (convertNone):
			return []

	@classmethod
	def ensure_container(cls, item, evaluateGenerator = True, convertNone = False):
		"""Makes sure the given item is a container.

		Example Input: ensure_container(valueList)
		Example Input: ensure_container(valueList, convertNone = True)
		Example Input: ensure_container(valueList, evaluateGenerator = False)
		"""

		if (item is None):
			if (convertNone):
				return (None,)
			return ()
		
		if (isinstance(item, (str, int, float, dict))):
			return (item,)

		if (not isinstance(item, (list, tuple, set))):
			if (evaluateGenerator):
				return tuple(item)
			return item
		return item

	@classmethod
	def getSchema(cls):
		"""Returns the functions needed to migrate the data from the old schema to the new one."""

		return []

	@classmethod
	def getSchemaClass(cls, relation):
		"""Returns the schema class for the given relation.
		Special thanks to OrangeTux for how to get schema class from tablename on: https://stackoverflow.com/questions/11668355/sqlalchemy-get-model-from-table-name-this-may-imply-appending-some-function-to/23754464#23754464

		relation (str) - What relation to return the schema class for

		Example Input: getSchemaClass("Customer")
		"""

		# # table = Mapper.metadata.tables.get("Customer")
		# # column = table.columns["name"]
		# return Mapper._decl_class_registry[column.table.name]

	#Schema Factory Functions
	dataType_catalogue = {
		int: sqlalchemy.Integer, "int": sqlalchemy.Integer,
		"bigint": sqlalchemy.types.BigInteger, "int+": sqlalchemy.types.BigInteger,
		"smallint": sqlalchemy.types.SmallInteger, "int-": sqlalchemy.types.SmallInteger,
		
		float: sqlalchemy.Float(), "float": sqlalchemy.Float(),
		decimal.Decimal: sqlalchemy.Numeric(), "decimal": sqlalchemy.Numeric(), "numeric": sqlalchemy.Numeric(), 
		
		bool: sqlalchemy.Boolean(), "bool": sqlalchemy.Boolean(),

		str: sqlalchemy.Text(), "str": sqlalchemy.String(256), "text": sqlalchemy.Text(), 
		"unicode": sqlalchemy.Unicode(), "utext": sqlalchemy.UnicodeText(),
		"json": sqlalchemy.JSON(),
		
		datetime.date: sqlalchemy.Date, "date": sqlalchemy.Date,
		datetime.datetime: sqlalchemy.DateTime(), "datetime": sqlalchemy.DateTime(), 
		datetime.time: sqlalchemy.Time(), "time": sqlalchemy.Time(), 
		datetime.timedelta: sqlalchemy.Interval(), "timedelta": sqlalchemy.Interval(), "delta": sqlalchemy.Interval(), "interval": sqlalchemy.Interval(),

		bin: sqlalchemy.LargeBinary(), "bin": sqlalchemy.LargeBinary(), "blob": sqlalchemy.LargeBinary(), "pickle": sqlalchemy.PickleType(),
	}

	@classmethod
	def schema_column(cls, dataType = int, default = None, key = None, 
		system = False, quote = None, docstring = None, comment = None, info = None, 
		foreignKey = None, foreign_update = True, foreign_delete = False, foreign_info = None,
		unique = None, notNull = None, autoIncrement = None, primary = None):
		"""Returns a schema column.

		dataType (type) - What data type the column will have
			~ int, float, bool, str, datetime.date
		default (any) - What default value to use for new entries
		key (str) - What to refer to this column as in the column handle
			- If None, will use the SQL name for it (The variable name for this column in the class structure)
		system (bool) - Marks this column as one that should not appear in the CREATE TABLE statement
		quote (bool) - Determines if quoting names should be forced or not
			- If None: Will quote the SQL name for this column if it has atleast one uppercase letter or is reserved
			- If True: Will always quote the SQL name for this column
			- If False: Will never quote the SQL name for this column
		docstring (str)     - What docstring to give the column handle
		comment (str) - What comment to give the SQL column
		info (dict)   - Extra information attached to the column handle

		foreignKey (str) - What relation and attribute to link to
			~ Can be a string like: "relation.attribute"
			~ Can be an sqlalchemy column handle of an existing column belonging to another table
		foreign_update (bool) - Determines what happens if the foreign key is updated while children are still referencing it
			- True: Updates all connected children as well
			- False: Updates the foreign key and sets the connected children to it's default value
			- None: Throws an error if any children are still connected
		foreign_delete (bool) - Determines what happens if the foreign key is deleted while children are still referencing it
			- True: Deletes all connected children as well
			- False: Deletes the foreign key and sets the connected chilrend to it's default value
			- None: Throws an error if any children are still connected
		foreign_info (dict) - Extra information for the foreign key attached to the column handle

		unique (bool) - If this column must be unique
		notNull (bool) - If this column cannot be NULL
		autoIncrement (bool) - If this column should have an unused and unique integer as a value
		primary (bool) - Determines if this is a primary key
			- If True: If this is a primary key
			~ Defaults 'unique' and 'notNull' to True, but these can be overridden by their parameters


		Example Input: schema_column()
		Example Input: schema_column(primary = True)
		Example Input: schema_column(foreignKey = Choices_Job.id)
		Example Input: schema_column(foreignKey = "Choices_Job.id")
		Example Input: schema_column(dataType = str)
		"""

		#sqlalchemy.Enum #use: https://docs.sqlalchemy.org/en/latest/core/type_basics.html#sqlalchemy.types.Enum
		#money #use: https://docs.sqlalchemy.org/en/latest/core/type_basics.html#sqlalchemy.types.Numeric

		if (dataType in cls.dataType_catalogue):
			dataType = cls.dataType_catalogue[dataType]
		
		columnItems = [] #https://docs.sqlalchemy.org/en/latest/core/metadata.html#sqlalchemy.schema.Column.params.*args
		if (foreignKey):
			columnItems.append(sqlalchemy.ForeignKey(foreignKey, 
				onupdate = {True: 'CASCADE', False: 'SET DEFAULT', None: 'RESTRICT'}[foreign_update], 
				ondelete = {True: 'CASCADE', False: 'SET DEFAULT', None: 'RESTRICT'}[foreign_delete],
				info = foreign_info or {}))

		columnKwargs = {"info": info or {}}
		if (primary):
			columnKwargs.update({"primary_key": True, "nullable": (notNull, False)[notNull is None], "unique": (unique, True)[unique is None]})
		else:
			if (unique):
				columnKwargs["unique"] = True
			
			if (notNull):
				columnKwargs["nullable"] = False
			elif (notNull is not None):
				columnKwargs["nullable"] = True

		# if (autoIncrement):
		# 	columnKwargs["autoIncrement"] = True #Use: https://docs.sqlalchemy.org/en/latest/core/metadata.html#sqlalchemy.schema.Column.params.autoincrement
		if (default is not None):
			columnKwargs["default"] = default
		if (system):
			columnKwargs["system"] = True
		if (docstring):
			columnKwargs["doc"] = docstring
		if (comment):
			columnKwargs["comment"] = comment

		return sqlalchemy.Column(dataType, *columnItems, **columnKwargs)

class Utility_Base(Base):
	#Context Managers
	@contextlib.contextmanager
	def makeSession(self):
		"""Provides a transactional scope around a series of operations.
		Modified code from: https://docs.sqlalchemy.org/en/latest/orm/session_basics.html
		"""
		global sessionMaker
		
		session = sessionMaker(bind = self.engine)
		try:
			yield session
			session.commit()
		except:
			session.rollback()
			raise
		finally:
			session.close()

	@contextlib.contextmanager
	def makeConnection(self, asTransaction = True):

		connection = self.engine.connect()
		if (asTransaction):
			transaction = connection.begin()
			try:
				yield connection
				transaction.commit()
			except:
				transaction.rollback()
				raise
			finally:
				connection.close()
		else:
			try:
				yield connection
			except:
				raise
			finally:
				connection.close()

class Schema_Base(Base):
	defaultRows = ()

	#Context Managers
	@classmethod
	@contextlib.contextmanager
	def makeSession(cls):
		"""Provides a transactional scope around a series of operations.
		Modified code from: https://docs.sqlalchemy.org/en/latest/orm/session_basics.html
		"""
		global sessionMaker
		
		session = sessionMaker(bind = cls.metadata.bind)
		try:
			yield session
			session.commit()
		except:
			session.rollback()
			raise
		finally:
			session.close()

	@classmethod
	@contextlib.contextmanager
	def makeConnection(cls, asTransaction = True):

		connection = cls.metadata.bind.connect()
		if (asTransaction):
			transaction = connection.begin()
			try:
				yield connection
				transaction.commit()
			except:
				transaction.rollback()
				raise
			finally:
				connection.close()
		else:
			try:
				yield connection
			except:
				raise
			finally:
				connection.close()

	#Virtual Functions
	@classmethod
	def reset(cls):
		"""Clears all rows and places in default ones."""

		with cls.makeSession() as session:
			session.query(cls).delete()
			for catalogue in cls.defaultRows:
				session.add(cls(**catalogue))

	@classmethod
	def yieldColumn(cls, attributeList, exclude, alias, **kwargs):
		#Use: https://docs.sqlalchemy.org/en/latest/core/selectable.html#sqlalchemy.sql.expression.except_

		for attribute in attributeList:
			for answer in cls._yieldColumn_noForeign(attribute, exclude, alias):
				yield answer

	@classmethod
	def _yieldColumn_noForeign(cls, attribute, exclude, alias):
		if (attribute in exclude):
			return

		columnHandle = getattr(cls, attribute)
		if (alias and (attribute in alias)):
			columnHandle = columnHandle.label(alias[attribute])
		yield columnHandle

	def change(self, values = {}, **kwargs):
		for variable, newValue in values.items():
			setattr(self, variable, newValue)

class Schema_AutoForeign():
	foreignKeys = {}

	def __init__(self, kwargs = {}):
		"""Automatically creates tuples for the provided relations if one does not exist.
		Special thanks to van for how to automatically add children on https://stackoverflow.com/questions/8839211/sqlalchemy-add-child-in-one-to-many-relationship
		"""

		for variable, relationHandle in self.foreignKeys.items():
			catalogue = kwargs.pop(variable, None)
			if (not catalogue):
				continue
			if (not isinstance(catalogue, dict)):
				catalogue = {"label": catalogue}

			with self.makeSession() as session:
				child = session.query(relationHandle).filter(sqlalchemy.and_(getattr(relationHandle, key) == value for key, value in catalogue.items())).one_or_none()
				if (child is None):
					child = relationHandle(**catalogue)
					session.add(child)
					session.commit()
					setattr(self, variable, child)
				kwargs[f"{variable}_id"] = child.id

	@classmethod
	def formatForeign(cls, schema):
		"""Automatically creates the neccissary things to accommodate the foreign keys.
		Special thanks to Cecil Curry fro the quickest way to get the first item in a set on: https://stackoverflow.com/questions/59825/how-to-retrieve-an-element-from-a-set-without-removing-it
		
		Example Input: formatForeign(self.schema)
		_______________________________________________________________

		Example Usage: 
			for module in Schema_AutoForeign.__subclasses__():
				module.formatForeign(hasForeignCatalogue)
		_______________________________________________________________
		"""

		cls.foreignKeys = {}
		for attribute, columnHandle in cls.__mapper__.columns.items():
			if (attribute.endswith("_id")):
				assert columnHandle.foreign_keys
				for foreignKey in columnHandle.foreign_keys: break

				variable = attribute.rstrip('_id')
				relationHandle = schema[foreignKey._table_key()]
				cls.foreignKeys[variable] = relationHandle

				setattr(cls, variable, sqlalchemy.orm.relationship(relationHandle, backref = cls.__name__.lower())) #Many to One 
				#cascade="all, delete, delete-orphan" #https://docs.sqlalchemy.org/en/latest/orm/tutorial.html

	# @classmethod
	# def _yieldColumn_noForeign(cls, attribute, exclude, alias):
	# 	if (attribute in exclude):
	# 		return

	# 	columnHandle = getattr(cls, attribute)
	# 	if (alias and (attribute in alias)):
	# 		columnHandle = columnHandle.label(alias[attribute])
	# 	yield columnHandle

	@classmethod
	def yieldColumn(cls, catalogueList, exclude, alias, foreignAsDict = False, foreignDefault = None):
		#Use: https://docs.sqlalchemy.org/en/latest/core/selectable.html#sqlalchemy.sql.expression.except_

		def formatAttribute(foreignKey, attribute):
			if (alias and (foreignKey in alias) and (attribute in alias[foreignKey])):
				if (foreignAsDict):
					return f"zfk_{foreignKey}_zfk_{alias[foreignKey][attribute]}"
				else:
					return alias[foreignKey][attribute]
			else:
				if (foreignAsDict):
					return f"zfk_{foreignKey}_zfk_{attribute}"
				else:
					return f"{foreignKey}_{attribute}"

		#######################################################

		for catalogue in catalogueList:
			if (not isinstance(catalogue, dict)):
				if (catalogue not in cls.foreignKeys):
					for answer in cls._yieldColumn_noForeign(catalogue, exclude, alias):
						yield answer
					continue

				if (foreignDefault is None):
					catalogue = {catalogue: tuple(attribute for attribute in cls.foreignKeys[catalogue].__mapper__.columns.keys() if (attribute not in {"id", *(exclude or ())}))}
				else:
					catalogue = {catalogue: foreignDefault}

			for foreignKey, attributeList in catalogue.items():
				relationHandle = cls.foreignKeys[foreignKey]

				for attribute in cls.ensure_container(attributeList):
					yield getattr(relationHandle, attribute).label(formatAttribute(foreignKey, attribute))

	def change(self, session, values = {}, updateForeign = None, checkForeign = True):
		"""
		checkForeign (bool) - Determines if foreign keys will be take in account
		updateForeign (bool) - Determines what happens to existing foreign keys
			- If True: Foreign keys will be updated to the new value
			- If False: A new foreign tuple will be inserted
			- If None: A foreign key will be updated to the new value if only one item is linked to it, otherwise a new foreign tuple will be inserted
		"""

		if (not checkForeign):
			super().change(session, values = values)

		for variable, catalogue in values.items():
			if (variable not in self.foreignKeys):
				setattr(self, variable, catalogue)
				continue

			handle = getattr(self, variable)
			if (not isinstance(catalogue, dict)):
				catalogue = {"label": catalogue}

			if (handle is None):
				#I have no foreign key, so I will make a new one
				child = handle.__class__(**catalogue)
				session.add(child)
				setattr(self, variable, child)

			elif (updateForeign or ((updateForeign is None) and (len(getattr(handle, self.__class__.__name__.lower())) is 1))):
				#I am the only one using this foreign key, so I can change it; I was told to force the change on this foreign key
				for subVariable, newValue in catalogue.items():
					setattr(handle, subVariable, newValue)
			else:
				#Someone else is using that foreign key, so I will make a new one; I was told to force no change on this foreign key
				child = handle.__class__(**catalogue)
				session.add(child)
				setattr(self, variable, child)

migrationCatalogue = {}
class CustomMetaData(sqlalchemy.MetaData, Base):
	migrationCatalogue = migrationCatalogue

	@classmethod
	def getAlembic(cls):

		assert False

class CustomBase(Base):
	pass

def makeBase():
	return sqlalchemy.ext.declarative.declarative_base(cls = CustomBase, metadata = CustomMetaData())

#Controllers
def build(*args, **kwargs):
	"""Starts the GUI making process."""

	return Database(*args, **kwargs)

class Singleton():
	"""Used to get values correctly."""

	def __init__(self, label = "Singleton"):
		self.label = label

	def __repr__(self):
		return f"{self.label}()"

NULL = Singleton("NULL")
FLAG = Singleton("FLAG")

#Main API
class Alembic():
	"""Used to handle database migrations and schema changes.
	If you want to generate SQL script: 
		Use: https://alembic.zzzcomputing.com/en/latest/offline.html
		Use: https://alembic.zzzcomputing.com/en/latest/batch.html#batch-offline-mode
		Use: https://bitbucket.org/zzzeek/alembic/issues/323/better-exception-when-attempting

	Modified code from: https://stackoverflow.com/questions/24622170/using-alembic-api-from-inside-application-code/43530495#43530495
	Modified code from: https://www.youtube.com/watch?v=xzsbHMHYI5c
	"""

	def __init__(self, parent, ensureCompatability = False, **kwargs):
		"""Loads in the alembic directory and creates an alembic handler.

		Example Input: loadAlembic(self)
		Example Input: loadAlembic(self, source_directory = "database")
		"""

		self.parent = parent

		self._applyMonkeyPatches()
		self.loadConfig(**kwargs)

		if (ensureCompatability):
			assert self.check()

	def __repr__(self):
		representation = f"{type(self).__name__}(id = {id(self)})"
		return representation

	def __str__(self):
		output = f"{type(self).__name__}()\n-- id: {id(self)}\n"
		if (self.parent is not None):
			output += f"-- Database: {id(self.parent)}\n"
			if (self.parent.schema is not None):
				output += f"-- Schema Name: {self.parent.schema.__name__}\n"
			if (self.parent.fileName is not None):
				output += f"-- File Name: {self.parent.fileName}\n"

		if (self.source_directory is not None):
			output += f"-- Source Directory: {self.source_directory}\n"
		if (self.alembic_directory is not None):
			output += f"-- Alembic Directory: {self.alembic_directory}\n"
		if (self.version_directory is not None):
			output += f"-- Version Directory: {self.version_directory}\n"
		if (self.ini_path is not None):
			output += f"-- .ini Path: {self.ini_path}\n"
		return output

	def __enter__(self):			
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		if (traceback is not None):
			print(exc_type, exc_value)
			return False

	def loadConfig(self, source_directory = None, template_directory = None, ini_filename = None):
		"""Creates a config object for the given 'alembic_directory'.

		source_directory (str) - Where the alembic folder and configuration settings are kept
		template_directory (str) - Where the alembic templates are kept
		ini_filename (str) - The name of the configuration settings file in the source_directory
			- If this file does not exist, the alembic directory will be (re)made in source_directory and this file will be created

		Example Input: loadConfig()
		Example Input: loadConfig(source_directory = "database")
		"""

		self.template_directory = os.path.abspath(template_directory or os.path.join(os.path.dirname(__file__), "alembic_templates"))
		self.source_directory   = os.path.abspath(source_directory  or os.curdir)
		self.alembic_directory  = os.path.abspath(os.path.join(self.source_directory, "alembic"))
		self.version_directory  = os.path.abspath(os.path.join(self.alembic_directory, "versions"))
		self.ini_path           = os.path.abspath(os.path.join(self.source_directory, ini_filename or "alembic.ini"))

		self.config = alembic_config_Config(self.ini_path)
		self.config.set_main_option("script_location", self.alembic_directory)
		self.config.set_main_option("sqlalchemy.url", self.parent.fileName)

		if (any(not os.path.exists(item) for item in (self.ini_path, self.alembic_directory))):
			self.resetAlembic()

	def resetAlembic(self, template = "custom"):
		"""Creates a fresh Alembic environment.
		NOTE: This will completely remove the alembic directory and create a new one.

		template (str) - Which template folder to use to create the alembic directory

		Example Input: resetAlembic()
		"""

		if ("alembic_version" in self.parent.getRelationNames()):
			self.parent.clearRelation("alembic_version")

		if (os.path.exists(self.ini_path)):
			os.remove(self.ini_path)

		if (not self.ini_path.endswith("alembic.ini")):
			default_ini_path = os.path.abspath(os.path.join(self.source_directory, "alembic.ini"))
			if (os.path.exists(default_ini_path)):
				os.remove(default_ini_path)

		if (os.path.exists(self.alembic_directory)):
			import stat
			def onerror(function, path, exc_info):
				"""An Error handler for shutil.rmtree.
				Modified code from Justin Peel on https://stackoverflow.com/questions/2656322/shutil-rmtree-fails-on-windows-with-access-is-denied
				"""
				if (not os.access(path, os.W_OK)):
					os.chmod(path, stat.S_IWUSR)
					function(path)
				else:
					raise
			shutil.rmtree(self.alembic_directory, ignore_errors = False, onerror = onerror)

		alembic.command.init(self.config, self.alembic_directory, template = template)

	def history(self, indicate_current = False):
		"""Prints out the revision history.

		Example Input: history()
		"""

		alembic.command.history(self.config, rev_range = None, verbose = False, indicate_current = indicate_current)

	def stamp(self, revision = "head", sql = False):
		"""Marks the current revision in the database.

		sql (bool) - Determines if the changes are actually applied
			- If True: Prints out an SQL statement that should cause the needed changes
			- If False: Applies the needed changes to the database

		Example Input: stamp()
		"""

		alembic.command.stamp(self.config, revision, sql = sql, tag = None)

	def revision(self, message = None, migrationCatalogue = None, autoStamp = False, sql = False):
		"""Creates a revision script for modifying the current database to what the schema currently looks like.
		NOTE: Make sure you proof read the generated revision script before running it.

		message (str) - A short discription of what the schema change is
		
		migrationCatalogue (dict) - Extra functions to use for the autogenerate step
			~ {relation (str): [custom line to put in the script]}
			~ Custom lines can be a string, a function that returns a string, a function that returns None, or a list of a combination of those
				If a function returns None, all the source code for that function between "## START ##" and "## STOP ##" will be used

		sql (bool) - Determines if the changes are actually applied
			- If True: Prints out an SQL statement that should cause the needed changes
			- If False: Applies the needed changes to the database

		autoStamp (bool) - Determines if the current database is assumed to be the most recent version

		Example Input: revision("split name column")
		Example Input: revision("split name column", migrationCatalogue = {"Customer": ("print(123)", "print(456)",)})
		Example Input: revision("split name column", migrationCatalogue = {"Customer": (("print(123)", "print(456)"),)})
		Example Input: revision("split name column", migrationCatalogue = {"Customer": (("print('Lorem')", "print('Ipsum')"), ("print('Dolor')"))})
		Example Input: revision("split name column", migrationCatalogue = {"Customer": (test,)})
		"""

		if (autoStamp):
			self.stamp()

		self.parent.metadata.migrationCatalogue.clear()
		self.parent.metadata.migrationCatalogue.update(migrationCatalogue or {})
		alembic.command.revision(self.config, autogenerate = True, message = message, sql = sql)

	def upgrade(self, target = "+1", sql = False):
		"""
		Runs the upgrade function in the revision script for 'target'.
		Will only commit changes made by the script if the function does not have any errors during execution.

		target (str) - Which revision to upgrade to
			- If "head": The most recent up-to-date revision
			- If "+n": How many revision levels to go up
			- If str: The name of the revision, or a partial section of it
			~ The options above can be combined

		sql (bool) - Determines if the changes are actually applied
			- If True: Prints out an SQL statement that should cause the needed changes
			- If False: Applies the needed changes to the database

		Example Input: upgrade()
		Example Input: upgrade("head")
		Example Input: upgrade("+2")
		Example Input: upgrade("4f83cf8faa80")
		Example Input: upgrade("4f8")
		Example Input: upgrade("4f8+2")
		Example Input: upgrade("head-1")
		"""
		alembic.command.upgrade(self.config, target, sql = sql, tag = None)

	def downgrade(self, target = "-1", sql = False):
		"""
		Runs the downgrade function in the revision script for 'target'.
		Will only commit changes made by the script if the function does not have any errors during execution.

		target (str) - Which revision to upgrade to
			- If "base": The state it was in before any revisions
			- If "-n": How many revision levels to go down
			- If str: The name of the revision, or a partial section of it
			~ The options above can be combined

		sql (bool) - Determines if the changes are actually applied
			- If True: Prints out an SQL statement that should cause the needed changes
			- If False: Applies the needed changes to the database

		Example Input: downgrade()
		Example Input: downgrade("base")
		Example Input: downgrade("-2")
		"""
		alembic.command.downgrade(self.config, target, sql = sql, tag = None)

	def check(self, returnDifference = False):
		"""Makes sure the current database matches the current schema.

		returnDifference (bool) - Determines what is returned
			If True: Returns the differences between the schema and the current database
			If False: Returns True if they match, and False if they don't

		Example Input: check()
		Example Input: check(returnDifference = True)
		"""

		context = alembic.migration.MigrationContext.configure(self.parent.engine.connect())
		
		if (returnDifference):
			return tuple(alembic.autogenerate.compare_metadata(context, self.parent.metadata))
		return not bool(alembic.autogenerate.compare_metadata(context, self.parent.metadata))

	def _applyMonkeyPatches(self):
		def mp_get_template_directory(mp_self):
			return self.template_directory
		alembic_config_Config.get_template_directory = mp_get_template_directory

		def mp__generate_template(mp_self, source, destination, **kwargs):
			if (source.endswith("alembic.ini.mako")):
				kwargs["database_location"] = self.parent.fileName
			return old__generate_template(mp_self, source, destination, **kwargs)
		old__generate_template = alembic.command.ScriptDirectory._generate_template
		alembic.command.ScriptDirectory._generate_template = mp__generate_template

		def mp__copy_file(mp_self, source, destination):
			"""Special thanks to shackra for how to import metadata correctly on https://stackoverflow.com/questions/32032940/how-to-import-the-own-model-into-myproject-alembic-env-py/32218546#32218546"""
			
			if (not source.endswith('env.py.mako')):
				return old__copy_file(mp_self, source, destination)

			schema = self.parent.schemaPath.split(".")[-1]
			imports = f'sys.path.insert(0, "{os.path.dirname(self.parent.schema.__file__)}")\nimport {schema}\ntarget_metadata = {schema}.Mapper.metadata'
			old__generate_template(mp_self, source, destination.rstrip(".mako"), imports = imports)
		old__copy_file = alembic.command.ScriptDirectory._copy_file
		alembic.command.ScriptDirectory._copy_file = mp__copy_file

		def mp_rev_id():
			"""Make Revision IDs sequential"""
			answer = old_rev_id()
			n = len(tuple(None for item in os.scandir(self.version_directory) if (item.is_file())))
			return f"{n:03d}_{answer}"
		old_rev_id= alembic.util.rev_id
		alembic.util.rev_id = mp_rev_id

		class mp_PlainText(alembic.operations.ops.MigrateOperation):
			def __init__(mp_self, command = None, args = None, kwargs = None):
				"""Used to insert plain text into the generated alembic files.

				Example Input: PlainText()
				Example Input: PlainText("print(123)")
				Example Input: PlainText(("print('Lorem')", "print('Ipsum')"), ("print('Dolor')"))
				"""

				mp_self.command = command or ""
				mp_self.args = args or ()
				mp_self.kwargs = kwargs or {}

			def formatText(mp_self, command):
				"""Formats the given command.

				Example Input: formatText("print(123)")
				Example Input: formatText(("print('Lorem')", "print('Ipsum')"), ("print('Dolor')"))
				Example Input: formatText(myFunction)
				"""

				if (isinstance(command, str)):
					return command
				elif (callable(command)):
					try:
						answer = command(*mp_self.args, **mp_self.kwargs)
					except Exception as error:
						# raise error
						print(error)
						answer = None

					if (answer is None):
						match = re.search("## START ##\n?(.*)## STOP ##", inspect.getsource(command), re.DOTALL)
						assert match
						lines = match.group(1).rstrip().split("\n")
						indent = len(lines[0]) - len(lines[0].lstrip('\t'))
						return "\n## START PLAIN TEXT ##\n{}\n## END PLAIN TEXT ##\n".format('\n'.join(item[indent:] for item in lines))
					else:
						return mp_self.formatText(answer)
				else:
					return "\n".join(mp_self.formatText(item) for item in command)
		alembic.operations.ops.PlainText = mp_PlainText

		@alembic.autogenerate.renderers.dispatch_for(alembic.operations.ops.PlainText)
		def _setPlainText(context, operation):
			"""
			Use: https://groups.google.com/d/msg/sqlalchemy-alembic/U8DS6CJsdRs/XIhSkj6xBgAJ
			Use: https://alembic.zzzcomputing.com/en/latest/api/autogenerate.html#creating-a-render-function
			"""

			return operation.formatText(operation.command)

class Database(Utility_Base):
	"""Used to create and interact with a database.
	To expand the functionality of this API, see: "https://www.sqlite.org/lang_select.html"
	"""

	def __init__(self, fileName = None, schemaPath = None, alembicPath = None, **kwargs):
		"""Defines internal variables.
		A better way to handle multi-threading is here: http://code.activestate.com/recipes/526618/

		fileName (str) - If not None: Opens the provided database automatically
		keepOpen (bool) - Determines if the database is kept open or not
			- If True: The database will remain open until closed by the user or the program terminates
			- If False: The database will be opened only when it needs to be accessed, and closed afterwards

		Example Input: Database()
		Example Input: Database("emaildb")
		"""

		self.threadLock = threading.RLock()
		self.TableBase = sqlalchemy.ext.declarative.declarative_base()

		#Internal variables
		self.cursor = None
		self.schema = None
		self.alembic = None
		self.waiting = False
		self.fileName = None
		self.schemaPath = None
		self.alembicPath = None
		self.defaultCommit = None
		self.connectionType = None
		self.defaultFileExtension = ".db"
		self.aliasError_replacement = None
		self.resultError_replacement = None

		#Initialization functions
		if (fileName is not None):
			self.openDatabase(fileName = fileName, schemaPath = schemaPath, alembicPath = alembicPath, **kwargs)

	def __repr__(self):
		representation = f"{type(self).__name__}(id = {id(self)})"
		return representation

	def __str__(self):
		output = f"{type(self).__name__}()\n-- id: {id(self)}\n"
		if (self.alembic is not None):
			output += f"-- Alembic: {id(self.alembic)}\n"
		if (self.schema is not None):
			output += f"-- Schema Name: {self.schema.__name__}\n"
		if (self.fileName is not None):
			output += f"-- File Name: {self.fileName}\n"
		return output

	def __enter__(self):			
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		if (traceback is not None):
			print(exc_type, exc_value)
			return False

	#Cache Functions
	indexCache = cachetools.LFUCache(maxsize = 10)

	def setCacheSize_index(self, size = None):
		"""Sets the max size for the index cache.

		size (int) - How large the cache will be
			- If None: Will set the cache to it's default size

		Example Input: setCacheSize_index()
		Example Input: setCacheSize_index(15)
		"""

		if (size is None):
			size = 10

		self.indexCache._Cache__maxsize = size

	def clearCache_index(self):
		"""Empties the index cache.

		Example Input: clearCache_index()
		"""

		self.indexCache.clear()

	#Event Functions
	def setFunction_cmd_startWaiting(self, function):
		"""Will trigger the given function when waiting for a database to unlock begins.

		function (function) - What function to run

		Example Input: setFunction_cmd_startWaiting(myFunction)
		"""

		pubsub_pub.subscribe(function, "event_cmd_startWaiting")

	#Utility Functions
	@cachetools.cached(indexCache)
	def getPrimaryKey(self, relation):
		"""Returns the primary key to use for the given relation.

		Example Input: getPrimaryKey()
		"""

		inspector = sqlalchemy.inspect(self.engine)
		catalogue = inspector.get_pk_constraint(relation)
		return catalogue["constrained_columns"][0]

	@wrap_errorCheck()
	def getRelationNames(self, exclude = None, include = None, excludeFunction = None, includeFunction = None):
		"""Returns the names of all relations (tables) in the database.

		exclude (list) - A list of which relations to excude from the returned result

		Example Input: getRelationNames()
		Example Input: getRelationNames(["Users", "Names"])
		Example Input: getRelationNames(include = ["_Job"], includeFunction = lambda relation, myList: any(relation.startswith(item) for item in myList)
		"""

		inspector = sqlalchemy.inspect(self.engine)
		return tuple(inspector.get_table_names())

	@wrap_errorCheck()
	def getAttributeNames(self, relation, exclude = None, foreignAsDict = False):
		"""Returns the names of all attributes (columns) in the given relation (table).

		relation (str) - The name of the relation
		exclude (list) - A list of which attributes to excude from the returned result
		foreignAsDict (bool) - Determines how foreign keys are returned
			- If True: {foreign key (str): [foreign attribute (str)]}
			- If False: foreign key (str)
			- If None: domestic id for foreign key (str)

		Example Input: getAttributeNames("Users")
		Example Input: getAttributeNames("Users", exclude = ["age", "height"])

		Example Input: getAttributeNames("Containers", foreignAsDict = True)
		Example Input: getAttributeNames("Containers", foreignAsDict = None)
		"""

		exclude = self.ensure_container(exclude)
		inspector = sqlalchemy.inspect(self.engine)

		if (foreignAsDict is not None):
			relationHandle = self.schema.relationCatalogue[relation]


		def yieldAttribute():
			nonlocal self, relation, exclude, foreignAsDict

			for catalogue in inspector.get_columns(relation):
				key = catalogue["name"]
				if (key in exclude):
					continue

				if ((foreignAsDict is not None) and (key.endswith("_id"))):
					foreignKey = key.rstrip('_id')
					if (foreignKey in relationHandle.foreignKeys):
						if (foreignAsDict):
							yield {foreignKey: tuple(self.getAttributeNames(relationHandle.foreignKeys[foreignKey]).__name__)} 
						else:
							yield foreignKey
						continue

				yield key

		##########################################

		return tuple(yieldAttribute())

	@wrap_errorCheck()
	def getAttributeDefaults(self, relation, attribute = None, exclude = None):
		"""Returns the defaults of the requested attribute (columns) in the given relation (table).

		relation (str) - The name of the relation
		attribute (str) - The name of the attribute to get the default for. Can be a list of attributes
			- If None: Will get the defaults for all attributes
		exclude (list) - A list of which attributes to excude from the returned result

		Example Input: getAttributeDefaults("Users")
		Example Input: getAttributeDefaults("Users", ["age", "height"])
		Example Input: getAttributeDefaults("Users", exclude = ["id"])
		"""

	@wrap_errorCheck()
	def getTupleCount(self, relation):
		"""Returns the number of tuples (rows) in a relation (table).

		Example Input: getTupleCount("Users")
		"""

	def configureLocation(self, handle, schema, fromSchema = False, nextToCondition = True, nextToCondition_None = None, checkForeign = True, forceMatch = True, 
		nextTo = None, notNextTo = None, like = None, notLike = None, isNull = None, isNotNull = None, extra = None, like_caseSensative = False,
		isIn = None, isNotIn = None, isAny = None, isNotAny = None, isAll = None, isNotAll = None, 
		isBetween = None, isNotBetween = None, between_symetric = False, exclude = None,
		greaterThan = None, lessThan = None, greaterThanOrEqualTo = None, lessThanOrEqualTo = None):
		"""Sets up the location portion of the SQL message.

		Example Input: configureLocation("Users", like = {"name": "or"})
		Example Input: configureLocation("Users", like = {"name": ["or", "em"]})

		Example Input: configureLocation("Users", isIn = {"name": "Lorem"})
		Example Input: configureLocation("Users", isIn = {"name": ["Lorem", "Ipsum"]})
		"""

		def yieldLocation():
			if (nextTo):
				for key, value in nextTo.items():
					yield getattr(schema, key) == value
			if (notNextTo):
				for key, value in notNextTo.items():
					yield getattr(schema, key) != value
			if (isNull):
				for key, value in isNull.items():
					yield getattr(schema, key) == None
			if (isNotNull):
				for key, value in isNotNull.items():
					yield getattr(schema, key) != None
			if (greaterThan):
				for key, value in greaterThan.items():
					yield getattr(schema, key) > value
			if (greaterThanOrEqualTo):
				for key, value in greaterThanOrEqualTo.items():
					yield getattr(schema, key) >= value
			if (lessThan):
				for key, value in lessThan.items():
					yield getattr(schema, key) < value
			if (lessThanOrEqualTo):
				for key, value in lessThanOrEqualTo.items():
					yield getattr(schema, key) <= value

			if (isIn):
				for key, value in isIn.items():
					yield getattr(schema, key).in_(value)
			if (isNotIn):
				for key, value in isNotIn.items():
					yield ~(getattr(schema, key).in_(value))
			if (isAll):
				for key, value in isAll.items():
					yield getattr(schema, key).all_(value)
			if (isNotAll):
				for key, value in isNotAll.items():
					yield ~(getattr(schema, key).all_(value))
			if (isAny):
				for key, value in isAny.items():
					yield getattr(schema, key).any_(value)
			if (isNotAny):
				for key, value in isNotAny.items():
					yield ~(getattr(schema, key).any_(value))

			if (like):
				if (like_caseSensative):
					for key, value in like.items():
						yield getattr(schema, key).like(value)
				else:
					for key, value in like.items():
						yield getattr(schema, key).ilike(value)
			if (notLike):
				if (like_caseSensative):
					for key, value in notLike.items():
						yield ~(getattr(schema, key).like(value))
				else:
					for key, value in notLike.items():
						yield ~(getattr(schema, key).ilike(value))

			if (isBetween):
				for key, (left, right) in isBetween.items():
					yield getattr(schema, key).between(left, right, symetric = between_symetric)
			if (isNotBetween):
				for key, (left, right) in isNotBetween.items():
					yield ~(getattr(schema, key).between(left, right, symetric = between_symetric))


		######################################################

		if (fromSchema):
			locationFunction = handle.filter
		else:
			locationFunction = handle.where

		if (nextToCondition):
			return locationFunction(sqlalchemy.and_(*yieldLocation()))
		else:
			return locationFunction(sqlalchemy.or_(*yieldLocation()))

	def configureOrder(self, handle, relation, schema, orderBy = None, direction = None, nullFirst = None):

		_orderBy = getattr(schema, orderBy or self.getPrimaryKey(relation))
		if (direction is not None):
			if (direction):
				_orderBy = sqlalchemy.asc(_orderBy)
			else:
				_orderBy = sqlalchemy.desc(_orderBy)
		
			# if (nullFirst is not None):
			# 	if (nullFirst):
			# 		_orderBy = _orderBy.nullsfirst()
			# 	else:
			# 		_orderBy = _orderBy.nullslast()

		return handle.order_by(_orderBy)

	def configureJoin(self, query, relation, schema, attributeList, fromSchema = True):

		if (fromSchema):
			handle = query
		else:
			handle = self.metadata.tables[relation]

		for attribute in attributeList:
			foreignHandle = schema.foreignKeys.get(attribute)
			if (foreignHandle is None):
				continue
			handle = handle.join(foreignHandle)

		if (fromSchema):
			return handle

		return query.select_from(handle)

	def executeCommand(self, command):
		"""Executes raw SQL to the engine.
		Yields each row returned from the command.

		command (str) - The sql to execute

		Example Input: executeCommand("SELECT * FROM Users")
		"""

		with self.makeConnection() as connection:
			result = connection.execute(command)
			for row in result:
				yield row
	
	#Interaction Functions
	def setDefaultCommit(self, state):
		self.defaultCommit = state

	def setMultiProcess(self, value):
		self.multiProcess = value

	def setMultiProcessDelay(self, value):
		self.multiProcess_delay = value

	def refresh(self):
		"""Ensures that the metadata is up to date with what is in the database.

		Example Input: refresh()
		"""

		self.metadata.reflect()

	@wrap_errorCheck()
	def openDatabase(self, fileName = None, schemaPath = None, alembicPath = None, *, applyChanges = True, multiThread = False, connectionType = None, 
		password = None, readOnly = False, keepOpen = None, multiProcess = -1, multiProcess_delay = 100,
		resultError_replacement = None, aliasError_replacement = None):

		"""Opens a database.If it does not exist, then one is created.
		Note: If a database is already opened, then that database will first be closed.
		Use: toLarry Lustig for help with multi-threading on http://stackoverflow.com/questions/22739590/how-to-share-single-sqlite-connection-in-multi-threaded-python-application
		Use: to culix for help with multi-threading on http://stackoverflow.com/questions/6297404/multi-threaded-use-of-sqlalchemy
		use: https://stackoverflow.com/questions/9233912/connecting-sqlalchemy-to-msaccess

		Use: https://stackoverflow.com/questions/31164610/connect-to-sqlite3-server-using-pyodbc-python
		Use: http://www.blog.pythonlibrary.org/2010/10/10/sqlalchemy-and-microsoft-access/

		fileName (str)      - The name of the database file
			- If None: Will create a new database that only exists in RAM and not on ROM
		applyChanges (bool) - Determines the default for when changes are saved to the database
			If True  - Save after every change. Slower, but more reliable because data will be saved in the database even if the program crashes
			If False - Save when the user tells the API to using saveDatabase() or the applyChanges parameter in an individual function. Faster, but data rentention is not ensured upon crashing
		multiThread (bool)  - If True: Will allow mnultiple threads to use the same database

		multiProcess (int) - Determines how many times to try executing a command if another process is using the database
			- If 0 or None: Do not retry
			- If -1: Retry forever
		multiProcess_delay (int) - How many milli-seconds to wait before trying to to execute a command again

		Example Input: openDatabase()
		Example Input: openDatabase("emaildb")
		Example Input: openDatabase("emaildb.sqllite")
		Example Input: openDatabase("emaildb", "test_map")
		Example Input: openDatabase("emaildb", applyChanges = False)
		Example Input: openDatabase("emaildb", multiThread = True)
		Example Input: openDatabase("emaildb", multiThread = True, multiProcess = 10)
		"""

		if (not fileName):
			fileName = ":memory:"
			connectionType = "sqlite3"
		else:
			#Check for file extension
			if ("." not in fileName):
				fileName += self.defaultFileExtension

			if (connectionType is None):
				if (fileName.endswith(("mdb", "accdb"))):
					connectionType = "access"
				else:
					connectionType = "sqlite3"

		#Configure Options
		self.multiProcess = multiProcess
		self.defaultCommit = applyChanges
		self.connectionType = connectionType
		self.multiProcess_delay = multiProcess_delay
		self.resultError_replacement = resultError_replacement

		# if (self.resultError_replacement is None):
		# 	self.resultError_replacement = "!!! SELECT ERROR !!!"

		self.isAccess = self.connectionType == "access"
		self.isSQLite = self.connectionType == "sqlite3"
		self.isMySQL = self.connectionType == "mysql"

		reset = not os.path.exists(fileName)

		if (self.isSQLite):
			self.fileName = f"sqlite:///{fileName}"
			self.engine = sqlalchemy.create_engine(self.fileName)
			sqlalchemy.event.listen(self.engine, 'connect', self._fk_pragma_on_connect)
		else:
			errorMessage = f"Unknown connection type {connectionType}"
			raise KeyError(errorMessage)

		sessionMaker.configure(bind = self.engine)
		
		if (schemaPath):
			self.loadSchema(schemaPath)

		if (fileName != ":memory:"):
			self.loadAlembic(alembicPath)

		if (reset):
			print(f"Creating Fresh Database for {fileName}")
			self.createRelation()
			self.resetRelation()

			if (self.alembic):
				self.alembic.stamp()

	def _fk_pragma_on_connect(self, connection, record):
		"""Turns foreign keys on for SQLite.
		Modified code from conny on: https://stackoverflow.com/questions/2614984/sqlite-sqlalchemy-how-to-enforce-foreign-keys
		"""

		connection.execute('pragma foreign_keys=ON')

	@wrap_errorCheck()
	def closeDatabase(self):
		"""Closes the opened database.

		Example Input: closeDatabase()
		"""

	@wrap_errorCheck()
	def saveDatabase(self):
		"""Saves the opened database.

		Example Input: saveDatabase()
		"""

	def autoSave(self, applyChanges):
		"""
		applyChanges (bool) - Determines if the database will be saved after the change is made.
			- If None: The default flag set upon opening the database will be used

		Example Input: autoSave(applyChanges)
		"""
		if (applyChanges or ((applyChanges is None) and self.defaultCommit)):
			self.saveDatabase()

	def loadSchema(self, schemaPath):
		"""Loads in a schema from the given schemaPath.

		Example Input: loadSchema(schemaPath)
		"""


		if (os.path.isfile(schemaPath)):
			sys.path.append(os.path.dirname(schemaPath))
			schemaPath = os.path.splitext(os.path.basename(schemaPath))[0]

		self.schemaPath = schemaPath
		self.schema = importlib.import_module(self.schemaPath)
		self.schema.Mapper.metadata.bind = self.engine
		self.metadata = self.schema.Mapper.metadata
		self.refresh()

	def checkSchema(self):
		"""Checks the loaded schema against what is in the meta data."""

		assert False

	def loadAlembic(self, alembicPath = None, **kwargs):
		"""Loads in the alembic directory and creates an alembic handler.

		alembicPath (str) - Where the alembic folder and configuration settings are kept

		Example Input: loadAlembic()
		Example Input: loadAlembic("database")
		"""

		self.alembic = Alembic(self, source_directory = alembicPath)

	@wrap_errorCheck()
	def removeRelation(self, relation = None):
		"""Removes an entire relation (table) from the database if it exists.
		Special thanks to Jimbo for help with spaces in database names on http://stackoverflow.com/questions/10920671/how-do-you-deal-with-blank-spaces-in-column-names-in-sql-server
		Special thanks to daveoncode for what to do when you get an sqlalchemy.exc.UnboundExecutionError error on: https://stackoverflow.com/questions/35918605/how-to-delete-a-table-in-sqlalchemy

		relation (str) - What the relation is called in the .db
			- If None: All tables will be removed from the .db

		Example Input: removeRelation()
		Example Input: removeRelation("Users")
		"""

		if (relation is None):
			self.metadata.drop_all()
		else:
			table = self.metadata.tables.get(relation)
			if (table is None):
				errorMessage = f"There is no table {relation} in {self.metadata.__repr__()} for removeRelation()"
				raise KeyError(errorMessage)

			try:
				table.drop()
			except sqlalchemy.exc.UnboundExecutionError:
				table.drop(self.engine)

	@wrap_errorCheck()
	def resetRelation(self, relation = None):
		"""Resets the relation to factory default, as described in the schema.

		relation (str) - What the relation is called in the .db
			- If None: All tables will be removed from the .db

		Example Input: resetRelation()
		Example Input: resetRelation("Users")
		"""

		if (relation is None):
			for relationHandle in self.schema.relationCatalogue.values():
				relationHandle.reset()
		else:
			relationHandle = self.schema.relationCatalogue[relation]
			relationHandle.reset()

	@wrap_errorCheck()
	def clearRelation(self, relation = None, applyChanges = None):
		"""Removes all rows in the given relation. The relation will still exist.

		relation (str)      - What the relation is called in the .db
			- If None: All relations will be cleared on the .db
		applyChanges (bool) - Determines if the database will be saved after the change is made.
			- If None: The default flag set upon opening the database will be used

		Example Input: clearRelation()
		"""

		# if (relation is None):
			
		# else:
		# 	table = self.metadata.tables.get(relation)
		# 	if (table is None):
		# 		errorMessage = f"There is no table {relation} in {self.metadata.__repr__()} for removeRelation()"
		# 		raise KeyError(errorMessage)

		# 	try:
		# 		table.drop()
		# 	except sqlalchemy.exc.UnboundExecutionError:
		# 		table.drop(self.engine)

	@wrap_errorCheck()
	def renameRelation(self, relation, newName, applyChanges = None):
		"""Renames a relation (table) to the given name the user provides.

		relation (str)      - What the relation is called in the .db
		newName (str)       - What the relation will now be called in the .db
		applyChanges (bool) - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used

		Example Input: renameRelation("Users", "Customers")
		"""
	
	@wrap_errorCheck()
	def createRelation(self, relation = None, schemaPath = None):
		"""Adds a relation (table) to the database.
		Special thanks to Jimbo for help with spaces in database names on http://stackoverflow.com/questions/10920671/how-do-you-deal-with-blank-spaces-in-column-names-in-sql-server
		
		relation (str)      - What the relation will be called in the .db
			- If None: Will create all tables in 'schemaPath'
		schemaPath (str)    - What path to take to get the schema for this relation
			- If None: Will use the default schema given to openDatabase()

		Example Input: createRelation("Users", {"email": str, "count": int})
		Example Input: createRelation("Users", [{"email": str}, {"count": int}])
		Example Input: createRelation("Users", {"email": str, "count": int}, applyChanges = False)
		Example Input: createRelation("Users", {"id": int, "email": str, "count": int}, notNull = {"id": True}, primary = {"id": True}, autoIncrement = {"id": True}, unique = {"id": True}, autoPrimary = False)
		
		Example Input: createRelation("Names", [{"first_name": str}, {"extra_data": str}], unique = {"first_name": True})
		Example Input: createRelation("Users", {"age": int, "height": int}, foreign = {"name": {"Names": "first_name"}})
		Example Input: createRelation("Users", {"age": int, "height": int}, foreign = {"name": {"Names": "first_name"}, "address": {"Address": "street"}})
		
		Example Input: createRelation("Users", "Backup Users"})
		"""

		if (relation is None):
			self.metadata.create_all()

			if (self.alembic):
				self.alembic.stamp()
			return

		if (schemaPath is None):
			schema = self.schema
		else:
			schema = self.loadSchema(schemaPath)

		gjhgjhgjh


	def copyAttribute(self, source_relation, source_attribute, destination_relation, destination_attribute = None):
		"""Copies an attribute from an existing table to another.

		Example Input: copyAttribute("Names", "extra_data", "Users"):
		"""

	@wrap_errorCheck()
	def removeAttribute(self, relation, attribute):
		"""Removes an attribute (column) from a relation (table).

		Example Input: removeAttribute("Users", "date created")
		Example Input: removeAttribute("Users", ["date created", "extra_data"])
		"""

	@wrap_errorCheck()
	def addAttribute(self, relation, attribute, dataType = str, default = None, notNull = None, 
		primary = None, autoIncrement = None, unsigned = None, unique = None, foreign = None, applyChanges = None):
		"""Adds an attribute (column) to a relation (table).

		relation (str)      - What the relation is called in the .db
		attribute (str)     - What the attribute will be called
		dataType (type)     - What type the attribute will be
		applyChanges (bool) - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used

		Example Input: addAttribute("Users", "date created", dataType = int)
		Example Input: addAttribute("_Job_1, "customer", dataType = str, foreign = {"Choices_Customer": "label"})
		"""

	@wrap_errorCheck()
	def addTuple(self, myTuple = None, applyChanges = None, autoPrimary = False, notNull = False, foreignNone = False, fromSchema = True,
		primary = False, autoIncrement = False, unsigned = True, unique = False, checkForeign = True, incrementForeign = True):
		"""Adds a tuple (row) to the given relation (table).
		Special thanks to DSM for how to check if a key exists in a list of dictionaries on http://stackoverflow.com/questions/14790980/how-can-i-check-if-key-exists-in-list-of-dicts-in-python
		Special thanks to Jimbo for help with spaces in database names on http://stackoverflow.com/questions/10920671/how-do-you-deal-with-blank-spaces-in-column-names-in-sql-server

		myTuple (dict)      - What will be written to the tuple. {relation: {attribute: value}}
		applyChanges (bool) - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used
		autoPrimary (bool)   - Determines if this is a primary key. Will use the primary key defaults. If notNull, primary, autoIncrement, or unsigned are given, they will override the defaults for this option

		notNull (bool)       - Determines how the initial value is assigned to the attribute
			- If True: Signals to the database that this will be used a lot
		primary (bool)       - Tells the database that this is the primary key (the relation id)
		autoIncrement (bool) - Determines if the attribute's value will increment every time it is written to
		unsigned (bool)      - Determines if the attribute's value will be able to be negative
		unique (bool)        - Determines how a unique attribute's value is handled in the case that it already exists in the relation.
			- If True:  Will replace the value of the attribute 
			- If False: Will not account for the value being a unique attribute
			- If None:  Will only insert if that value for the attribute does not yet exist
		checkForeign (bool) - Determines if foreign keys will be take in account
		foreignNone (bool)   - Determines what to do if an attribute with a foreign key will be None. Can be a dict of {attribute (str): state (bool)}
			- If True: Will place the None in the foreign key relation
			- If False: Will place the None in the domestic relation

		Example Input: addTuple({"Lorem": None}, autoPrimary = True)
		Example Input: addTuple({"Lorem": {"Ipsum": "Dolor", "Sit": 5}})
		Example Input: addTuple({"Lorem": {"Ipsum": "Dolor", "Sit": 5}}, unique = None)
		Example Input: addTuple({"Lorem": [{"Ipsum": "Dolor", "Sit": 5}, {"Ipsum": "Amet", "Sit": 6}]})
		"""

		if (fromSchema):
			with self.makeSession() as session:
				for relation, rows in myTuple.items():
					parent = self.schema.relationCatalogue[relation]
					for attributeDict in self.ensure_container(rows):
						handle = session.add(parent(**attributeDict))
		else:
			with self.makeConnection(asTransaction = True) as connection:
				for relation, rows in myTuple.items():
					table = self.metadata.tables[relation]
					for attributeDict in self.ensure_container(rows):
						connection.execute(table.insert(values = attributeDict))

	@wrap_errorCheck()
	def changeTuple(self, myTuple, nextTo, value = None, forceMatch = None, applyChanges = None, checkForeign = True, updateForeign = None, fromSchema = True, **locationKwargs):
		"""Changes a tuple (row) for a given relation (table).
		Note: If multiple entries match the criteria, then all of those tuples will be chanegd.
		Special thanks to Jimbo for help with spaces in database names on http://stackoverflow.com/questions/10920671/how-do-you-deal-with-blank-spaces-in-column-names-in-sql-server
		Use: https://stackoverflow.com/questions/9667138/how-to-update-sqlalchemy-row-entry/26920108#26920108

		myTuple (dict)   - What will be written to the tuple. {relation: attribute to change} or {relation: {attribute to change: value}}
		nextTo (dict)    - An attribute-value pair that is in the same tuple. {attribute next to one to change: value of this attribute}
			- If more than one attribute is given, it will look for all cases
		value (any)      - What will be written to the tuple
			- If a value for 'myTuple' is a dict, this will be ignored
		forceMatch (any) - Determines what will happen in the case where 'nextTo' is not found
			- If True: Create a new row that contains the default values
			- If False: Do nothing
			- If None: Do nothing

		nextToCondition (bool) - Determines how to handle multiple nextTo criteria
			- If True: All of the criteria given must match
			- If False: Any of the criteria given must match

		applyChanges (bool)  - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used
		checkForeign (bool) - Determines if foreign keys will be take in account
		updateForeign (bool) - Determines what happens to existing foreign keys
			- If True: Foreign keys will be updated to the new value
			- If False: A new foreign tuple will be inserted
			- If None: A foreign key will be updated to the new value if only one item is linked to it, otherwise a new foreign tuple will be inserted

		Example Input: changeTuple({"Users": "name"}, {"age": 26}, "Amet")
		Example Input: changeTuple({"Users": {"name": "Amet"}}, {"age": 26})
		Example Input: changeTuple({"Users": {"name": "Amet", "extra_data": 2}, {"age": 26})
		"""

		if (fromSchema):
			with self.makeSession() as session:
				for relation, rows in myTuple.items():
					parent = self.schema.relationCatalogue[relation]
					for attributeDict in self.ensure_container(rows):
						query = session.query(parent)
						query = self.configureLocation(query, parent, fromSchema = fromSchema, nextTo = nextTo, **locationKwargs)
						for row in query.all():
							row.change(session, values = attributeDict, updateForeign = updateForeign)
		else:
			with self.makeConnection(asTransaction = True) as connection:
				for relation, rows in myTuple.items():
					table = self.metadata.tables[relation]
					for attributeDict in self.ensure_container(rows):
						#Does not handle foreign keys
						query = table.update(values = attributeDict)
						query = self.configureLocation(query, table.columns, fromSchema = fromSchema, nextTo = nextTo, **locationKwargs)
						connection.execute(query)


	@wrap_errorCheck()
	def removeTuple(self, myTuple, applyChanges = None,	checkForeign = True, incrementForeign = True, fromSchema = True, **locationKwargs):
		"""Removes a tuple (row) for a given relation (table).
		Note: If multiple entries match the criteria, then all of those tuples will be removed.

		myTuple (dict) - What will be removed. {relation: attribute: value to look for to delete the row}
		like (dict)    - Flags things to search for something containing the item- not exactly like it. {relation: attribute: (bool) True or False}
			- If True: Search for anything containing this item
			- If False: Search for an exact match

		nextToCondition (bool) - Determines how to handle multiple nextTo criteria
			- If True: All of the criteria given must match
			- If False: Any of the criteria given must match

		applyChanges (bool)  - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used
		checkForeign (bool) - Determines if foreign keys will be take in account
		removeForeign (bool) - Determines what happens to existing foreign keys
			- If True: Foreign keys will be removed also
			- If False: Foreign keys will be left alone
			- If None: A foreign key will be removed if only one item is linked to it, otherwise it will be left alone
		exclude (list)       - A list of tables to exclude from the 'updateForeign' check

		Example Input: removeTuple({"Users": {"name": "John"}})
		Example Input: removeTuple({"Users": {"name": ["John", "Jane"]}})
		Example Input: removeTuple({"Users": {"name": "John", "age": 26}})
		Example Input: removeTuple({"Users": {"name": "John"}}, like = {"Users": {"email": "@gmail.com"}})
		"""

		if (fromSchema):
			with self.makeSession() as session:
				for relation, rows in myTuple.items():
					parent = self.schema.relationCatalogue[relation]
					for nextTo in self.ensure_container(rows):
						query = session.query(parent)
						query = self.configureLocation(query, parent, fromSchema = fromSchema, nextTo = nextTo, **locationKwargs)
						query.delete()
		else:
			with self.makeConnection(asTransaction = True) as connection:
				for relation, rows in myTuple.items():
					table = self.metadata.tables[relation]
					for nextTo in self.ensure_container(rows):
						query = table.delete()
						query = self.configureLocation(query, table.columns, fromSchema = fromSchema, nextTo = nextTo, **locationKwargs)
						connection.execute(query)

	@wrap_errorCheck()
	def getAllValues(self, relation = None, attribute = None, exclude = None, **kwargs):
		"""Returns all values in the given relation (table) that match the filter conditions.

		relation (str) - Which relation to look in
			- If a list is given, it will look in each relation
			- If None: Will return all values for each relation in the database
		exclude (list) - A list of which tables to excude from the returned result
			- If multiple tables are required, provide a dictionary for the tabel elements. {table 1: [attribute 1, attribute 2], table 2: attribute 3}
			- If a list or single value is given, it will apply to all tables given

		Example Input: getAllValues()
		Example Input: getAllValues("Users")
		Example Input: getAllValues("Users", orderBy = ["age"])
		
		Example Input: getAllValues(["Users"])
		Example Input: getAllValues(["Users", "Names"])
		Example Input: getAllValues(["Users", "Names"], orderBy = {"Users": "age"})
		Example Input: getAllValues(["Users", "Names"], orderBy = {"Users": ["age", "height"]})
		Example Input: getAllValues(["Users", "Names"], orderBy = {"Users": ["age", "height"], "Names": "extra_data"})
		Example Input: getAllValues(["Users", "Names"], orderBy = "id")

		database_API.getAllValues("Containers", foreignAsDict = True, foreignDefault = ("label", "archived"))
		database_API.getAllValues("Containers", foreignDefault = ("label", "archived"))
		"""

		relation = self.ensure_container(relation)

		if (isinstance(exclude, dict)):
			excludeList = {item for _relation in relation for item in exclude.get(_relation, ())}
		else:
			excludeList = self.ensure_container(exclude, convertNone = False)

		myTuple = {}
		for _relation in relation:
			if (attribute):
				if (isinstance(attribute, dict)):
					myTuple[_relation] = attribute.get(_relation, None)
				else:
					myTuple[_relation] = attribute
			else:
				myTuple[_relation] = None

		return self.getValue(myTuple, exclude = excludeList, **kwargs)

	@wrap_errorCheck()
	def getValue(self, myTuple, nextTo = None, orderBy = None, limit = None, direction = None, nullFirst = None, alias = None, 
		returnNull = False, includeDuplicates = True, checkForeign = True, formatValue = None, valuesAsSet = False, count = False,
		maximum = None, minimum = None, average = None, summation = None, variableLength = True, variableLength_default = None,
		forceRelation = False, forceAttribute = False, forceTuple = False, attributeFirst = True, rowsAsList = False, 
		filterForeign = True, filterNone = False, exclude = None, forceMatch = None, fromSchema = True,
		foreignAsDict = False, foreignDefault = None, **locationKwargs):
		"""Gets the value of an attribute in a tuple for a given relation.
		If multiple attributes match the criteria, then all of the values will be returned.
		If you order the list and limit it; you can get things such as the 'top ten occurrences', etc.
		For more information on JOIN: https://www.techonthenet.com/sqlite/joins.php
		Use: https://stackoverflow.com/questions/11530196/flask-sqlalchemy-query-specify-column-names/45905714#45905714

		myTuple (dict)   - What to return {relation: attribute}
			- A list of attributes can be returned: {relation: [attribute 1, attribute 2]}
			- If an attribute is a foreign key: {relation: {foreign relation: foreign attribute}}
			- If list: [(myTuple 1, nextTo 1), (myTuple 2, nextTo 2)]. Will ignore 'nextTo'
		nextTo (dict)    - An attribute-value pair that is in the same tuple. {attribute: value}
			- If multiple keys are given, all will be used according to 'nextToCondition'
			- If an attribute is a foreign key: {value: {foreign relation: foreign attribute}}
			- If None: The whole column will be returned
			- If str: Will return for all columns where that value is present
		forceMatch (any) - Determines what will happen in the case where 'nextTo' is not found
			- If True: Create a new row that contains the default values
			- If False: Do nothing
			- If None: Do nothing
		
		orderBy (any)    - Determines whether to order the returned values or not. A list can be given to establish priority for multiple things
			- If None: Do not order
			- If not None: Order the values by the given attribute
		direction (bool) - Determines if a descending or ascending condition should be appled. Used for integers. If a list is given for 'orderBy', either
			(A) a list must be given with the same number of indicies, (B) a single bool given that will apply to all, or (C) a dictionary given where the 
			key is the item to adjust and the value is the bool for that item
			- If True: Ascending order
			- If False: Descending order
			- If None: No action taken
		limit (int)      - Determines whether to limit the number of values returned or not
			- If None: Do not limit the return results
			- If not None: Limit the return results to this many

		checkForeign (bool)  - Determines if foreign keys will be take in account
			- If True: Will check foreign keys
			- If False: Will not check foreign keys
		foreignAsDict (bool) - Determines how results for foreignKeys are returned
			- If True: {domestic attribute: {foreign attribute: foreign value}}
			- If False: {domestic attribute's foreign attribute: domestic attribute's foreign value}
			- If None: {foreign id: domestic value}
		foreignDefault (str) - What foreign key to look for when an attribute is a foreign key, but not a dictionary
			- If None: Will return all foreign attributes that are not primary keys
			- If str: Will return only that foreign attribute
			- If list: Will return all foreign attributes in list

		forceRelation (bool)  - Determines if the relation is returned in the answer
			- If True: Answers will always contain the relation
			- If False: Answers will omit the relation if there is only one in the answer
		forceAttribute (bool) - Determines if the attribute is returned in the answer
			- If True: Answers will always contain the attribute
			- If False: Answers will omit the attribute if there is only one in the answer
		forceTuple (bool)     - Determines if the row separator is returned in the answer
			- If True: Answers will always contain the row separator
			- If False: Answers will omit the row separator if there is only one in the answer
		attributeFirst (bool) - Determines if the attribute is first in the answer
			- If True: {relation: {attribute: {row: value}}}
			- If False: {relation: {row: {attribute: value}}}
		rowsAsList (bool)     - Determines how rows are separated
			- If True: Rows are a tuple of dictionaries
			- If False: Rows are dictionary keys that hold dictionaries as values

		Example Input: getValue({"Users": "name"})
		Example Input: getValue({"Users": "name"}, valuesAsList = True)
		Example Input: getValue({"Users": "name"}, valuesAsRows = None)
		Example Input: getValue({"Users": "name"}, filterRelation = False)
		Example Input: getValue({"Users": ["name", "age"]})

		Example Input: getValue({"Users": "name"}, orderBy = "age")
		Example Input: getValue({"Users": ["name", "age"]}, orderBy = "age", limit = 2)
		Example Input: getValue({"Users": ["name", "age"]}, orderBy = "age", direction = True)

		Example Input: getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"])
		Example Input: getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"], direction = [None, False])
		Example Input: getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"], direction = {"height": False})

		Example Input: getValue({"Users": "name", "Names": "first_name"})
		Example Input: getValue({"Users": "name", "Names": "first_name"}, filterRelation = False)
		Example Input: getValue({"Users": "name", "Names": ["first_name", "extra_data"]})

		Example Input: getValue({"Users": "name"}, filterForeign = None)
		Example Input: getValue({"Users": "name"}, filterForeign = False)

		Example Input: getValue({"Users": "name"}, {"age": 24})
		Example Input: getValue({"Users": "name"}, {"age": 24, height: 6})
		Example Input: getValue({"Users": "name"}, {"age": 24, height: 6}, nextToCondition = False)

		Example Input: getValue({"Users": "age"}, {"name": "John"})
		Example Input: getValue({"Users": "age"}, {"name": ["John", "Jane"]})

		Example Input: getValue({"Users": "name"}, greaterThan = {"age": 20})
		Example Input: getValue({"Constructor_VariableNames": "table"}, isNotNull = {"inventoryTitle": True}, exclude = ["_Job"])
		
		Example Input: getValue("Users", {"age": 24})
		Example Input: getValue({"Users": None}, {"age": 24})
		Example Input: getValue([({"Users": "name"}, {"age": 24}), ({"Users": "height"}, {"age": 25})])
		"""
		# startTime = time.perf_counter()
		
		if (fromSchema):
			contextmanager = self.makeSession()
			
			def startQuery(relation, attributeList, schema):
				nonlocal self, excludeList, alias

				return connection.query(*schema.yieldColumn(attributeList, excludeList, alias, foreignAsDict = foreignAsDict, foreignDefault = foreignDefault)).select_from(schema)

			def yieldRow(query):
				nonlocal count

				if (count):
					yield (query.count(),)
					return

				for result in query.all():
					if ((not forceAttribute) and (len(result) <= 1)):
						yield result[0]

					elif (not foreignAsDict):
						yield result._asdict()

					else:
						catalogue = collections.defaultdict(dict)
						for key, value in result._asdict().items():
							foreignMatch = re.search("zfk_(.*)_zfk_(.*)", key)
							if (not foreignMatch):
								catalogue[key] = value
							else:
								catalogue[foreignMatch.group(1)][foreignMatch.group(2)] = value
						yield dict(catalogue)

		else:
			contextmanager = self.makeConnection(asTransaction = True)
			
			def startQuery(relation, attributeList, schema):
				nonlocal self, excludeList, alias

				return sqlalchemy.select(columns = schema.yieldColumn(attributeList, excludeList, alias, foreignAsDict = foreignAsDict, foreignDefault = foreignDefault))

			def yieldRow(query):
				for result in connection.execute(query).fetchall():
					if ((not forceAttribute) and (len(result) <= 1)):
						yield result[0]

					elif (not foreignAsDict):
						yield dict(result)

					else:
						catalogue = collections.defaultdict(dict)
						for key, value in result.items():
							foreignMatch = re.search("zfk_(.*)_zfk_(.*)", key)
							if (not foreignMatch):
								catalogue[key] = value
							else:
								catalogue[foreignMatch.group(1)][foreignMatch.group(2)] = value
						yield dict(catalogue)

		def getResult(query, connection):
			nonlocal forceTuple

			answer = tuple(yieldRow(query))
			if (not answer):
				return ()
			elif (forceTuple or (len(answer) > 1)):
				return answer
			else:
				return answer[0]

		########################################################################

		if (not isinstance(exclude, dict)):
			excludeList = self.ensure_container(exclude, convertNone = False)

		results_catalogue = {}
		with contextmanager as connection:
			for relation, attributeList in myTuple.items():
				if (isinstance(exclude, dict)):
					excludeList = {item for _relation in relation for item in exclude.get(_relation, ())}
				attributeList = self.ensure_container(attributeList) or self.getAttributeNames(relation, foreignAsDict = foreignAsDict is None)

				schema = self.schema.relationCatalogue[relation]
				
				query = startQuery(relation, attributeList, schema)
				query = self.configureJoin(query, relation, schema, attributeList, fromSchema = fromSchema)
				query = self.configureOrder(query, relation, schema, orderBy = orderBy, direction = direction, nullFirst = nullFirst)
				query = self.configureLocation(query, schema, fromSchema = fromSchema, nextTo = nextTo, **locationKwargs)

				if (limit is not None):
					query = query.limit(limit)
				if (not includeDuplicates):
					query = query.distinct()
				if (count and (not fromSchema)):
					query = query.count()

				results_catalogue[relation] = getResult(query, connection)
		
		# print(f"@getValue.9", fromSchema, f"{time.perf_counter() - startTime:.6f}")

		if (forceRelation or (len(myTuple) > 1)):
			return results_catalogue
		return results_catalogue[relation]

	@wrap_errorCheck()
	def createTrigger(self, label, relation,

		event = "update", event_when = "before", event_relation = None, event_attribute = None,
		reaction = "ignore", reaction_when = None, reaction_relation = None, reaction_attribute = None,
		
		noReplication = None, applyChanges = None):
		"""Creates an event trigger.
		See: http://www.sqlitetutorial.net/sqlite-trigger/
		See: https://www.tutlane.com/tutorial/sqlite/sqlite-triggers

		label (str)    - What the trigger will be called in the .db
		relation (str) - Which relation this applies to
		
		event (str)           - What will fire the trigger. Only the first letter matters
			~ 'insert', 'update', 'delete'
			- If 'reaction' requires a specific one to work, then it will use that instead
		event_when (str)      - At what time in relation to 'event' the trigger will fire. Only the first letter matters
			~ 'before', 'after', 'instead'
		event_relation (str)  - What table the event applies to
			- If None: Will use 'relation'
		event_attribute (str) - What attribute the event applies to
			- If None: Will apply to all attributes in the table
		
		
		reaction_when (str) - The condition that causes the trigger to fire. Only the first letter matters
			~ 'before', 'after', 'instead'
			- If None: Will fire for every time the 'event' happens
		reaction (str) - What will happen when the trigger fires. Only the first letter matters
			~ 'foreign' - Uses 'reaction_attribute' in 'reaction_relation' instead of 'event_attribute' in 'event_relation'
				- 'event_attribute' in 'event_relation' will have the primary key for 'reaction_attribute' instead of any value

			~ 'lastModified' - Updates 'reaction_attribute' in 'reaction_relation' to the current date
				- reaction_attribute default: 'lastModified'
				- Only works for the event 'update'

			~ 'createdOn' - Marks when the row was first created 
				- reaction_attribute default: 'createdOn'
				- Only works for the event 'insert'

			~ 'ignore'

			~ 'validate'

		- reaction_relation (str)  - What table the reaction applies to
			- If None: Will use 'relation'
		- reaction_attribute (str) - What attribute the reaction applies to
			- If None: Will use the appropriate default name listed in the comments for 'reaction'. If this does not exist, it will create it

		noReplication (bool) - If True: The trigger will not be created if it does not already exist
			- If None: Will delete the previously existing trigger if it exists
		applyChanges (bool)  - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used

		Example Input: createTrigger("Users_lastModified", "Users", reaction = "lastModified")
		"""

	@wrap_errorCheck()
	def getTrigger(self, label = None, exclude = None):
		"""Returns an event trigger.

		label (str) - What the trigger is be called in the .db
			- If None: Will return the names of all triggers

		Example Input: getTrigger()
		Example Input: getTrigger("Users_lastModified")
		"""

	@wrap_errorCheck()
	def removeTrigger(self, label = None, applyChanges = None):
		"""Removes an event trigger.

		label (str) - What the trigger will be called in the .db
			- If None: Will remove all triggers
		applyChanges (bool)  - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used

		Example Input: removeTrigger("Users_lastModified")
		"""

	@wrap_errorCheck()
	def createIndex(self, relation, attribute, name = None, noReplication = False):
		"""Creates an index for the given attribute."""

	@wrap_errorCheck()
	def getIndex(self, label = None, exclude = None):
		"""Returns an index.

		label (str) - What the index is be called in the .db
			- If None: Will return the names of all indexs

		Example Input: getIndex()
		Example Input: getIndex("Users_lastModified")
		"""

	@wrap_errorCheck()
	def removeIndex(self, relation = None, attribute = None, name = None, noReplication = False):
		"""Removes an index for the given attribute."""

def quiet(*args):
	pass
	print(*args)

def sandbox():

	database_API = build()
	database_API.openDatabase(None, "H:\Python\Material_Tracker\database\schema.py") # database_API.openDatabase("test_map_example.db", "test_map")
	database_API.removeRelation()
	database_API.createRelation()
	database_API.resetRelation()

	#Add Items
	database_API.addTuple({"Containers": ({"label": "lorem", "weight_total": 123, "poNumber": 123456, "job": {"label": 1234, "display_text": "12 34"}}, {"label": "ipsum", "job": 1234})})
	database_API.addTuple({"Containers": {"label": "dolor", "weight_total": 123, "poNumber": 123456}})
	database_API.addTuple({"Containers": {"label": "sit", "weight_total": 123, "poNumber": 123456, "job": 678}})
	
	#Get Items
	# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}))
	# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, fromSchema = False))
	# quiet(database_API.getValue({"Containers": None}, {"weight_total": 123, "poNumber": 123456}))

	# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}))
	# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, foreignAsDict = True))
	# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, foreignDefault = "label"))
	quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, foreignDefault = "label", foreignAsDict = True))
	quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, foreignDefault = "label", foreignAsDict = True, fromSchema = False))

	# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, alias = {"label": "containerNumber"}))
	# quiet(database_API.getValue({"Containers": ("job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, alias = {"job": {"label": "jobNumber"}}))

	# quiet(database_API.getValue({"Containers": ("job", "label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, alias = {"job": {"label": "jobNumber"}, "label": "containerNumber"}))
	# quiet(database_API.getValue({"Containers": ("job", "label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, alias = {"job": {"label": "jobNumber"}, "label": "containerNumber"}, fromSchema = False))

	# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, forceRelation = True, forceAttribute = True, forceTuple = True))
	# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, forceRelation = True, forceAttribute = True))
	# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, forceRelation = True))
	# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}))

	# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, fromSchema = False, forceRelation = True, forceAttribute = True, forceTuple = True))
	# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, fromSchema = False, forceRelation = True, forceAttribute = True))
	# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, fromSchema = False, forceRelation = True))
	# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, fromSchema = False))

	# quiet(database_API.getAllValues("Containers", fromSchema = False))
	# quiet(database_API.getAllValues("Containers"))
	# quiet(database_API.getAllValues("Containers", foreignAsDict = True, foreignDefault = ("label", "archived")))
	# quiet(database_API.getAllValues("Containers", foreignDefault = ("label", "archived")))


	# #Change Items
	# quiet(database_API.getValue({"Containers": ("label", "job", "location")}, {"weight_total": 123, "poNumber": 123456}))
	# database_API.changeTuple({"Containers": {"job": 5678, "location": "A2"}}, {"label": "lorem"})
	# quiet(database_API.getValue({"Containers": ("label", "job", "location")}, {"weight_total": 123, "poNumber": 123456}))
	
	# #Remove Items
	# database_API.removeTuple({"Containers": {"label": "dolor"}})
	# database_API.removeTuple({"Containers": {"label": "sit"}})
	# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"label": "dolor"}))

	# #Update Schema
	# database_API.openDatabase("test_map_example.db", "test_map_2")
	# database_API.checkSchema()

def main():
	"""The main program controller."""

	sandbox()

if __name__ == '__main__':
	main()
