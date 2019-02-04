__version__ = "3.4.0"

## TO DO ##
# - Add a foreign key cleanup command; removes unused foreign keys in foreign tables

#Standard Modules
import re
import os
import sys
import time
import shutil

import io
import enum
import types
import decimal
import subprocess

# #Utility Modules
import warnings
import operator
import datetime
import traceback

import itertools
import functools
import contextlib
import collections

import inspect
import unidecode
import importlib

import urllib
import sqlalchemy
import sqlalchemy_utils
import sqlalchemy.ext.declarative

import alembic
import alembic.config
import alembic.command
from alembic.config import Config as alembic_config_Config

#For multi-threading
import threading
from forks.pypubsub.src.pubsub import pub as pubsub_pub #Use my own fork

import MyUtilities.common
import MyUtilities.logger
import MyUtilities.caching

from API_Database.utilities import json
import API_Database.db_config as db_config

sessionMaker = sqlalchemy.orm.sessionmaker(autoflush = False)

NULL = MyUtilities.common.NULL
NULL_private = MyUtilities.common.Singleton("NULL", state = False, private = True)
openPlus = MyUtilities.common.openPlus

#Required Modules
##py -m pip install
	# pyyaml
	# pyodbc
	# alembic
	# unidecode
	# sqlalchemy
	# sqlalchemy_utils

	# pynsist
	# wxPython
	# cachetools

##MySQL Installer #https://dev.mysql.com/downloads/installer/
	# MySQL Server
	# Connector/Python (3.6)

#Exceptions
class ReadOnlyError(Exception):
	pass

class InvalidSectionError(Exception):
	pass

class ValueExistsError(Exception):
	pass

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

sqlalchemy.sql.sqltypes.json._default_encoder = json._default_encoder
sqlalchemy.sql.sqltypes.json._default_decoder = json._default_decoder

class _JSON(sqlalchemy.TypeDecorator):
	"""Allows sqlite to use JSON files.
	Modified code from Xiwei Wang on: https://stackoverflow.com/questions/46712393/creating-json-type-column-in-sqlite-with-sqlalchemy/49933601#49933601
	See: https://docs.sqlalchemy.org/en/latest/core/custom_types.html#sqlalchemy.types.TypeDecorator
	"""

	@property
	def python_type(self):
		return object

	impl = sqlalchemy.types.String

	def process_bind_param(self, value, dialect):
		return json.dumps(value)

	def process_literal_param(self, value, dialect):
		return value

	def process_result_value(self, value, dialect):
		try:
			return json.loads(value)
		except (ValueError, TypeError):
			return None

#Utility Classes
class Base(MyUtilities.common.EnsureFunctions, MyUtilities.common.CommonFunctions):
	pass

class Base_Database(Base):
	# @classmethod
	# def getSchemaClass(cls, relation):
	#   """Returns the schema class for the given relation.
	#   Special thanks to OrangeTux for how to get schema class from tablename on: https://stackoverflow.com/questions/11668355/sqlalchemy-get-model-from-table-name-this-may-imply-appending-some-function-to/23754464#23754464

	#   relation (str) - What relation to return the schema class for

	#   Example Input: getSchemaClass("Customer")
	#   """

	#   # # table = Mapper.metadata.tables.get("Customer")
	#   # # column = table.columns["name"]
	#   # return Mapper._decl_class_registry[column.table.name]

	#Schema Factory Functions
	#https://stackoverflow.com/questions/1827063/mysql-error-key-specification-without-a-key-length/1827099#1827099
	dataType_catalogue = {
		int: sqlalchemy.Integer, "int": sqlalchemy.Integer, 
		"bigint": sqlalchemy.types.BigInteger, "int+": sqlalchemy.types.BigInteger, 
		"smallint": sqlalchemy.types.SmallInteger, "int-": sqlalchemy.types.SmallInteger, 
		
		float: sqlalchemy.Float(), "float": sqlalchemy.Float(), 
		decimal.Decimal: sqlalchemy.Numeric(), "decimal": sqlalchemy.Numeric(), "numeric": sqlalchemy.Numeric(), 
		
		bool: sqlalchemy.Boolean(), "bool": sqlalchemy.Boolean(), 

		str: sqlalchemy.String(256), "str": sqlalchemy.String(256), "text": sqlalchemy.Text(), 
		"unicode": sqlalchemy.Unicode(), "utext": sqlalchemy.UnicodeText(), 
		"json": sqlalchemy.JSON(), "json_2": _JSON, 
		
		datetime.date: sqlalchemy.Date, "date": sqlalchemy.Date, 
		datetime.datetime: sqlalchemy.DateTime(), "datetime": sqlalchemy.DateTime(), 
		datetime.time: sqlalchemy.Time(), "time": sqlalchemy.Time(), 
		datetime.timedelta: sqlalchemy.Interval(), "timedelta": sqlalchemy.Interval(), "delta": sqlalchemy.Interval(), "interval": sqlalchemy.Interval(), 

		bin: sqlalchemy.LargeBinary(), "bin": sqlalchemy.LargeBinary(), "blob": sqlalchemy.LargeBinary(), "pickle": sqlalchemy.PickleType(), 
	}

	dataType_numbers = (
		dataType_catalogue[int], 
		dataType_catalogue[bool].__class__, 
		dataType_catalogue["decimal"].__class__, 
		dataType_catalogue[float].__class__, 
		dataType_catalogue["bigint"], 
		dataType_catalogue["smallint"], 
	)

	@classmethod
	def getPrimaryKey(cls, relationHandle = None):
		if (relationHandle is None):
			return sqlalchemy.inspection.inspect(cls).primary_key[0].name
		return sqlalchemy.inspection.inspect(relationHandle).primary_key[0].name

	@classmethod
	def schema_column(cls, dataType = int, default = None, used = None,
		system = False, quote = None, docstring = None, comment = None, info = None, 
		foreignKey = None, foreign_update = True, foreign_delete = False, foreign_info = None,
		unique = None, notNull = None, autoIncrement = None, primary = None):
		"""Returns a schema column.

		dataType (type) - What data type the column will have
			~ int, float, bool, str, datetime.date
		default (any) - What default value to use for new entries
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
		used (handle) - What table.column contains a list of used items that should not be used again
		primary (bool) - Determines if this is a primary key
			- If True: If this is a primary key
			~ Defaults 'unique' and 'notNull' to True, but these can be overridden by their parameters


		Example Input: schema_column()
		Example Input: schema_column(primary = True)
		Example Input: schema_column(foreignKey = Choices_Job.databaseId)
		Example Input: schema_column(foreignKey = "Choices_Job.databaseId")
		Example Input: schema_column(dataType = str)
		"""

		#sqlalchemy.Enum #use: https://docs.sqlalchemy.org/en/latest/core/type_basics.html#sqlalchemy.types.Enum
		#money #use: https://docs.sqlalchemy.org/en/latest/core/type_basics.html#sqlalchemy.types.Numeric

		if (dataType in cls.dataType_catalogue):
			dataType = cls.dataType_catalogue[dataType]
		elif (dataType.__class__ is enum.EnumMeta):
			dataType = sqlalchemy.Enum(dataType)
		
		columnItems = [] #https://docs.sqlalchemy.org/en/latest/core/metadata.html#sqlalchemy.schema.Column.params.*args
		if (foreignKey):
			columnItems.append(sqlalchemy.ForeignKey(foreignKey, 
				# onupdate = {True: 'CASCADE', False: 'SET DEFAULT', None: 'RESTRICT'}[foreign_update], 
				# ondelete = {True: 'CASCADE', False: 'SET DEFAULT', None: 'RESTRICT'}[foreign_delete],
				info = foreign_info or {}))

		columnKwargs = {"info": info or {}}
		if (primary):
			columnKwargs.update({
				"primary_key": True, 
				"nullable": (notNull, False)[notNull is None], 
				"unique": (unique, True)[unique is None], 
				"autoincrement": (False, False)[autoIncrement is None],
			})
		else:
			if (unique):
				columnKwargs["unique"] = True
			
			if (notNull):
				columnKwargs["nullable"] = False
			elif (notNull is not None):
				columnKwargs["nullable"] = True

			# if (autoIncrement):
			#   columnKwargs["autoincrement"] = True #Use: https://docs.sqlalchemy.org/en/latest/core/metadata.html#sqlalchemy.schema.Column.params.autoincrement

		if (default is not None):
			columnKwargs["default"] = default
		if (system):
			columnKwargs["system"] = True
		if (docstring):
			columnKwargs["doc"] = docstring
		if (comment):
			columnKwargs["comment"] = comment

		if ((used is not None) and columnKwargs["unique"]):
			columnKwargs["used"] = used

		return MyColumn(dataType, *columnItems, **columnKwargs)

	@classmethod
	def printSQL(cls, query):
		print(sqlalchemy_utils.functions.render_statement(query))

class MyColumn(sqlalchemy.Column):
	def __init__(self, *args, used = None, **kwargs):
		super().__init__(*args, **kwargs)

		self._used = used 

class Utility_Base(Base_Database):
	#Context Managers
	@contextlib.contextmanager
	def makeSession(self, close = True):
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
			if (close):
				session.flush()
				session.close()

	@contextlib.contextmanager
	def makeConnection(self, asTransaction = True, raw = False):
		"""Provides a transactional scope for a direct connection.

		raw (bool) - Determiens what module the connection belongs to
			- If True: 'connection' is from the dialect
			- If False: 'connection' is from sqlalchemy
		"""

		if (raw):
			connection = self.engine.raw_connection()
			asTransaction = False
		else:
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
			return

		try:
			yield connection
		except:
			raise
		finally:
			connection.close()

	def yieldColumn_fromTable(self, relation, catalogueList, exclude, alias, foreignAsDict = False, foreignDefault = None):
		#Use: https://docs.sqlalchemy.org/en/latest/core/selectable.html#sqlalchemy.sql.expression.except_
		#Use: https://docs.sqlalchemy.org/en/latest/core/metadata.html#accessing-tables-and-columns

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

		######################################################

		exclude = self.ensure_container(exclude)

		if (isinstance(relation, str)):
			table = self.metadata.tables[relation]
		else:
			table = relation

		for catalogue in catalogueList:
			if (not isinstance(catalogue, dict)):
				if (catalogue in exclude):
					continue

				columnHandle = getattr(table.columns, catalogue)
				if (not columnHandle.foreign_keys):
					if (alias and (catalogue in alias)):
						yield columnHandle.label(alias[catalogue])
					else:
						yield columnHandle
					continue

				if (foreignDefault is None):
					if (len(columnHandle.foreign_keys) > 1):
						raise NotImplementedError()

					for foreignKey in columnHandle.foreign_keys: break
					catalogue = {catalogue: tuple(attribute for attribute in foreignKey.column.table.columns.keys() if (attribute not in exclude))}
				else:
					catalogue = {catalogue: foreignDefault}

			for attribute, foreignKeyList in catalogue.items():
				for foreignKey in self.ensure_container(foreignKeyList):
					yield getattr(table.columns, attribute).label(formatAttribute(foreignKey, attribute))

class Schema_Base(Base_Database):
	foreignKeys = {}
	defaultRows = ()

	def __init__(self, kwargs = {}):
		"""Automatically creates tuples for the provided relations if one does not exist."""

		session = kwargs.pop("session", None)

		#Increment primary key to lowest unique value
		index = self.getPrimaryKey()
		if (index not in kwargs):
			kwargs[index] = self.uniqueMinimum(relation = self.__tablename__, attribute = index, session = session)

		if (self.checkUsed(catalogue = kwargs, session = session, autoAdd = True, returnOnPass = True, useForFail = None)):
			raise ValueExistsError(kwargs)

	@classmethod
	def uniqueMinimum(cls, relation = None, attribute = None, *, session = None, minimum = None, default = 1, forceAttribute = False):
		"""Returns the lowest unique value that is greater than the first entry on the table.
		Special thanks to shamittomar for how to do custom auto-incrementing on https://stackoverflow.com/questions/5016907/mysql-find-smallest-unique-id-available/5016969#5016969

		relation (str) - Which relation (table) to look in
			- If None: Will use the relation belonging to this class

		attribute (str) - Which attribute (column) to look in
			- If None: Will use the primary column

		minimum (int) - What value any answer must be greater than or equal to
			- If None: Will not apply a minimum

		default (int) - What value to start at if the relation is empty

		Example Input: uniqueMinimum()
		Example Input: uniqueMinimum(relation = "Dictionary")
		Example Input: uniqueMinimum(relation = "Dictionary", attribute = "pageNumber")
		"""

		def yieldLocation():
			nonlocal attribute, minimum

			yield f"(t2.{attribute} is NULL)"
			yield f"(t1.{attribute} > {minimum or 0})"

			for key, foreignHandle in cls.usedCatalogue.items():
				yield f"(t1.{attribute} + 1 NOT IN (SELECT {foreignHandle.getPrimaryKey()} FROM {foreignHandle.__tablename__}))"

		#################################################

		relation = relation or cls.__tablename__
		attribute = attribute or cls.getPrimaryKey()

		if (session is not None):
			#Changes must be applied to account for recently added items
			session.commit()

		command = f"SELECT MIN(t1.{attribute} + 1) FROM {relation} as t1 "
		command += f"LEFT JOIN {relation} as t2 ON t1.{attribute} + 1 = t2.{attribute} "
		command += f"WHERE ({' AND '.join(yieldLocation())})"

		answer = int((cls.metadata.bind.execute(command).first() or (None,))[0] or default)
		
		if ((minimum is not None) and (answer < minimum)):
			answer = minimum

		if (forceAttribute):
			return {attribute: answer}
		return answer

	@classmethod
	def checkExists(cls, catalogue = None, *, session = None, forceAttribute = False):
		"""Returns if the value exists or not.
		Special thanks to Laurent W for how to quickly check if a row exists on https://stackoverflow.com/questions/1676551/best-way-to-test-if-a-row-exists-in-a-mysql-table/10688065#10688065

		catalogue (dict) - {attribute (str): value (any)}
			- If not dict or None for key: Will check all attributes for the given value

		Example Input: checkExists()
		Example Input: checkExists({"word": "lorem"})
		"""

		if (session is not None):
			#Changes must be applied to account for recently added items
			session.commit()

		answer = {}
		assert catalogue is not None
		for attribute, value in cls.ensure_dict(catalogue).items():
			attribute = cls.ensure_default(attribute, default = cls.getPrimaryKey)
			answer[attribute] = cls.metadata.bind.execute(f"SELECT EXISTS(SELECT 1 FROM {cls.__tablename__} WHERE ({attribute} = %s) LIMIT 1)", (value,)).first()[0]

		if (forceAttribute or (len(answer) is not 1)):
			return answer
		else:
			return next(iter(answer.values()), {})

	@classmethod
	def checkUsed(cls, catalogue = None, *, session = None, autoAdd = False, forceAttribute = False, 
		returnOnPass = False, returnOnFail = False, useForPass = True, useForFail = False, **kwargs):
		"""Returns if the given value is used or not.

		catalogue (dict) - {attribute (str): value (any)}
			- If not dict or None for key: Will check all attributes for the given value

		autoAdd (bool) - Determines if the given value is automatically added to any linked catalogues
		returnOnPass (bool) - Determines if True should be returned immidiately after a success
		returnOnFail (bool) - Determines if False should be returned immidiately after a failure
		
		useForPass (any) - What should be used to signify a success
			- If None: Will not record
		useForFail (any) - What should be used to signify a failure
			- If None: Will not record

		forceAttribute (bool) - Determines if the attribute is returned in the answer
			- If True: Answers will always contain the attribute
			- If False: Answers will omit the attribute if there is only one in the answer

		Example Input: checkUsed(1234)
		Example Input: checkUsed({None: 1234})
		Example Input: checkUsed({"label": 1234})
		Example Input: checkUsed(kwargs, autoAdd = True)
		"""

		if (not cls.usedCatalogue):
			if (forceAttribute):
				return {}
			return

		answer = {}
		catalogue = cls.ensure_dict(catalogue, default = None, useAsKey = False, convertNone = False)
		for attribute, usedColumn in cls.usedCatalogue.items():
			if (attribute in catalogue):
				value = catalogue[attribute]
			elif (None in catalogue):
				value = catalogue[None]
			else:
				continue

			index = usedColumn.getPrimaryKey()
			if (usedColumn.checkExists({index: value}, session = session, **kwargs)):
				if (returnOnPass):
					return useForPass
				elif (useForPass is not None):
					answer[attribute] = useForPass
			else:
				if (returnOnFail):
					return useForFail
				elif (useForPass is not None):
					answer[attribute] = useForFail

			if (autoAdd):
				with cls.makeSession() as session:
					session.add(usedColumn(**{index: value}))

		if (forceAttribute or (len(answer) is not 1)):
			return answer
		else:
			return next(iter(answer.values()), {})

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
	def reset(cls, *, override_resetBypass = False):
		"""Clears all rows and places in default ones."""

		if (cls.defaultRows is NULL):
			if (not override_resetBypass):
				return
			defaultRows = ()
		else:
			defaultRows = cls.defaultRows

		with cls.makeSession() as session:              
			session.query(cls).delete()
			for catalogue in cls.ensure_container(defaultRows):
				if (not catalogue):
					continue
				child = cls(**catalogue, session = session)
				session.add(child)

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

	def change(self, session, values = {}, **kwargs):
		for variable, newValue in values.items():
			setattr(self, variable, newValue)

class Schema_Used(Schema_Base):
	
	@classmethod
	def reset(cls, *args, **kwargs):
		"""Overridden to populate with existing values.
		Special thanks to Eric for how to get a list of unincluded items on https://stackoverflow.com/questions/1001144/mysql-select-x-from-a-where-not-in-select-x-from-b-unexpected-result/1001180#1001180
		"""

		super().reset(*args, **kwargs)

		#Find missing rows and add them
		index = cls.getPrimaryKey()
		with cls.makeSession() as session:  
			for foreignHandle, attributeList in cls.usedBy.items():
				for foreign_attribute in attributeList:
					for result in tuple(zip(*cls.metadata.bind.execute(f"SELECT t1.{foreign_attribute} FROM {foreignHandle.__tablename__} as t1 LEFT OUTER JOIN {cls.__tablename__} as t2 ON t1.{foreign_attribute} = t2.{index} AND t2.{index} IS NOT NULL WHERE t2.{index} IS NULL"))):
						for item in result:
							child = cls(**{index: item}, session = session)
							session.add(child)

class Schema_AutoForeign(Schema_Base):
	_foreignInfo = {}

	def __init__(self, kwargs = {}):
		"""Automatically creates tuples for the provided relations if one does not exist.
		Special thanks to van for how to automatically add children on https://stackoverflow.com/questions/8839211/sqlalchemy-add-child-in-one-to-many-relationship
		"""

		super().__init__(kwargs = kwargs)

		forcedCatalogue = {}
		for variable, relationHandle in self.foreignKeys.items():
			catalogue = kwargs.pop(variable, None)
			if (not catalogue):
				continue
			if (not isinstance(catalogue, dict)):
				catalogue = {"label": catalogue}

			with self.makeSession() as session:
				child = session.query(relationHandle).filter(sqlalchemy.and_(getattr(relationHandle, key) == value for key, value in catalogue.items())).one_or_none()
				if (child is None):
					child = relationHandle(**catalogue, session = session)
					session.add(child)
					forcedCatalogue[variable] = child
					session.commit()
				kwargs[f"{variable}_id"] = getattr(child, self.getPrimaryKey(relationHandle))

		for variable, child in forcedCatalogue.items():
			setattr(self, variable, child)


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

				setattr(cls, variable, sqlalchemy.orm.relationship(relationHandle, backref = cls.__name__.lower(), info = cls._foreignInfo.get(variable, {}))) #Many to One 
				#cascade="all, delete, delete-orphan" #https://docs.sqlalchemy.org/en/latest/orm/tutorial.html

	# @classmethod
	# def _yieldColumn_noForeign(cls, attribute, exclude, alias):
	#   if (attribute in exclude):
	#       return

	#   columnHandle = getattr(cls, attribute)
	#   if (alias and (attribute in alias)):
	#       columnHandle = columnHandle.label(alias[attribute])
	#   yield columnHandle

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
					catalogue = {catalogue: tuple(attribute for attribute in cls.foreignKeys[catalogue].__mapper__.columns.keys() if (attribute not in (exclude or ())))}
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

		forcedCatalogue = {}
		for variable, catalogue in values.items():
			if (variable not in self.foreignKeys):
				setattr(self, variable, catalogue)
				continue

			if (not isinstance(catalogue, dict)):
				catalogue = {"label": catalogue}
			elif (not catalogue):
				continue

			relationHandle = self.foreignKeys[variable]
			if ("label" in catalogue):
				existing = session.query(relationHandle).filter(relationHandle.label == catalogue["label"]).one_or_none()
				if (existing is None):
					current = getattr(self, variable, None)
					if ((current is not None) and (len(getattr(current, self.__class__.__name__.lower())) is 1)):
						#Change current
						for key, value in catalogue.items():
							setattr(current, key, value)
						continue

					#Create new
					child = self.foreignKeys[variable](**catalogue, session = session)
					session.add(child)
					setattr(self, variable, child)
					forcedCatalogue[variable] = child
					continue

				if (len(catalogue) is 1):
					#Use existing
					setattr(self, variable, existing)
					continue

				for key, value in catalogue.items():
					if (getattr(existing, key) != value):
						break
				else:
					#Use existing
					setattr(self, variable, existing)
					continue

				if (len(getattr(existing, self.__class__.__name__.lower())) is 0):
					#Change existing
					setattr(self, variable, existing)
					for key, value in catalogue.items():
						setattr(existing, key, value)
					continue

			#Create new unique
			n = 1
			title = catalogue.get('label', variable.title())
			while f"{title}_{n}" in {row.label for row in session.query(relationHandle).all()}:
				n += 1

			child = self.foreignKeys[variable](**{**catalogue, "label": f"{title}_{n}"}, session = session)
			session.add(child)
			setattr(self, variable, child)
			forcedCatalogue[variable] = child

migrationCatalogue = {}
class CustomMetaData(sqlalchemy.MetaData, Base):
	migrationCatalogue = migrationCatalogue

	@classmethod
	def getAlembic(cls):

		raise NotImplementedError()

class CustomBase(Base_Database):
	pass

def makeBase():
	return sqlalchemy.ext.declarative.declarative_base(cls = CustomBase, metadata = CustomMetaData())

class EmptySchema():
	Mapper = makeBase()
	relationCatalogue = {}
	hasForeignCatalogue = {}

#Controllers
def build(*args, **kwargs):
	"""Creates a Database object."""

	return Database(*args, **kwargs)


#Dialects
sqlalchemy.dialects.registry.register("access.fixed", "forks.sqlalchemy.dialects.access.base", "AccessDialect")

#Main API
class Alembic(Base):
	"""Used to handle database migrations and schema changes.
	If you want to generate SQL script: 
		Use: https://alembic.zzzcomputing.com/en/latest/offline.html
		Use: https://alembic.zzzcomputing.com/en/latest/batch.html#batch-offline-mode
		Use: https://bitbucket.org/zzzeek/alembic/issues/323/better-exception-when-attempting

	Modified code from: https://stackoverflow.com/questions/24622170/using-alembic-api-from-inside-application-code/43530495#43530495
	Modified code from: https://www.youtube.com/watch?v=xzsbHMHYI5c
	"""

	def __init__(self, parent, assertCompatability = False, **kwargs):
		"""Loads in the alembic directory and creates an alembic handler.

		Example Input: Alembic(self)
		Example Input: Alembic(self, source_directory = "database")
		"""

		self.parent = parent

		self._applyMonkeyPatches()
		self.loadConfig(**kwargs)

		if (assertCompatability):
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

class Database(Utility_Base, MyUtilities.logger.LoggingFunctions):
	"""Used to create and interact with a database.
	To expand the functionality of this API, see: "https://www.sqlite.org/lang_select.html"

	To backup database on schedule: https://www.redolive.com/utah-web-designers-blog/automated-mysql-backup-for-windows/
	"""

	logger_config = {
		None: {
			"level": 1,
		},

		"console": {
			"type": "stream",
			"level": 1,
		},
	}

	def __init__(self, fileName = None, logger_name = None, logger_config = None, defaultFileExtension = None, **kwargs):
		"""Defines internal variables.
		A better way to handle multi-threading is here: http://code.activestate.com/recipes/526618/

		fileName (str) - If not None: Opens the provided database automatically
		keepOpen (bool) - Determines if the database is kept open or not
			- If True: The database will remain open until closed by the user or the program terminates
			- If False: The database will be opened only when it needs to be accessed, and closed afterwards

		Example Input: Database()
		Example Input: Database("emaildb")
		"""

		MyUtilities.logger.LoggingFunctions.__init__(self, label = logger_name or __name__, config = logger_config or self.logger_config, force_quietRoot = __name__ == "__main__")

		self._applyMonkeyPatches()

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
		self.baseFileName = None
		self.defaultCommit = None
		self.connectionType = None
		self.defaultFileExtension = defaultFileExtension or "db"
		self.aliasError_replacement = None
		self.resultError_replacement = None

		#Initialization functions
		if (fileName is not None):
			if (fileName.endswith(".ini")):
				self.openDatabase_fromConfig(filePath = fileName, **kwargs)
			else:
				self.openDatabase(fileName = fileName, **kwargs)

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

	def _applyMonkeyPatches(self):
		#Ensure the MySQL dialect is imported
		sqlalchemy.create_engine("mysql+mysqlconnector://")

		def mp_mysql__show_create_table(mp_self, connection, table, charset = None, full_name = None):
			"""Fixes the lowercase foreign key tables and references."""
			sql = old_mysql__show_create_table(mp_self, connection, table, charset = charset, full_name = full_name)

			if (self.schema is None):
				return sql

			relationHandle = self.schema.relationCatalogue.get(full_name.strip("`"))
			if (relationHandle is None):
				return sql

			if (re.search("FOREIGN KEY.*REFERENCES", sql)):
				for foreignKey, foreignHandle in relationHandle.foreignKeys.items():
					sql = re.sub(f"FOREIGN KEY \(`?({foreignKey}_id)`?\) REFERENCES `?([^`]*)`? \(`?([^`]*)`?\)",
						f"FOREIGN KEY (`{foreignKey}_id`) REFERENCES `{foreignHandle.__tablename__}` (`{foreignHandle._primaryKeys[0]}`)", sql)

			return sql

		self.dataType_catalogue["int_unsigned"] = sqlalchemy.dialects.mysql.INTEGER(unsigned = True)

		old_mysql__show_create_table = sqlalchemy.dialects.mysql.base.MySQLDialect._show_create_table
		sqlalchemy.dialects.mysql.base.MySQLDialect._show_create_table = mp_mysql__show_create_table

	#Caches
	cache_info = MyUtilities.caching.LFUCache(maxsize = 100000)
	cache_defaults = MyUtilities.caching.LFUCache(maxsize = 100000)
	cache_relations = MyUtilities.caching.LFUCache(maxsize = 100000)
	cache_primaryKey = MyUtilities.caching.LFUCache(maxsize = 100000)
	cache_attributes = MyUtilities.caching.LFUCache(maxsize = 100000)
	cache_creationOrder = MyUtilities.caching.LFUCache(maxsize = 100000)

	#Event Functions
	def setFunction_cmd_startWaiting(self, function):
		"""Will trigger the given function when waiting for a database to unlock begins.

		function (function) - What function to run

		Example Input: setFunction_cmd_startWaiting(myFunction)
		"""

		pubsub_pub.subscribe(function, "event_cmd_startWaiting")

	#Utility Functions
	@MyUtilities.caching.cached(cache_primaryKey)
	def getPrimaryKey(self, relation):
		"""Returns the primary key to use for the given relation.

		Example Input: getPrimaryKey()
		"""

		## TO DO ##
		#Account for composite primary keys

		inspector = sqlalchemy.inspect(self.engine)
		catalogue = inspector.get_pk_constraint(relation)
		return catalogue["constrained_columns"][0]

	@wrap_errorCheck()
	@MyUtilities.caching.cached(cache_relations)
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
	@MyUtilities.caching.cached(cache_attributes)
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

		Example Input: getAttributeNames("Containers", foreignAsDict = None)
		Example Input: getAttributeNames("Containers", foreignAsDict = True)
		"""

		exclude = self.ensure_container(exclude)
		inspector = sqlalchemy.inspect(self.engine)

		if (foreignAsDict is not None):
			relationHandle = self.schema.relationCatalogue.get(relation)
			if (relationHandle is None):
				foreignAsDict = None

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
							yield {foreignKey: tuple(self.getAttributeNames(relationHandle.foreignKeys[foreignKey].__name__))} 
						else:
							yield foreignKey
						continue

				yield key

		##########################################

		return tuple(yieldAttribute())

	@wrap_errorCheck()
	@MyUtilities.caching.cached(cache_defaults)
	def getAttributeDefaults(self, relation, attribute = None, *, exclude = None, foreignAsDict = False, forceAttribute = False):
		"""Returns the defaults of the requested attribute (columns) in the given relation (table).

		relation (str) - The name of the relation
		attribute (str) - The name of the attribute to get the default for. Can be a list of attributes
			- If None: Will get the defaults for all attributes
		exclude (list) - A list of which attributes to excude from the returned result
		
		foreignAsDict (bool) - Determines how values for foreign keys are returned
			- If True: {foreign key (str): default value (any)}
			- If False: default value for primary key (any)

		forceAttribute (bool) - Determines if the attribute is returned in the answer
			- If True: Answers will always contain the attribute
			- If False: Answers will omit the attribute if there is only one in the answer

		Example Input: getAttributeDefaults("Users")
		Example Input: getAttributeDefaults("Users", ["age", "height"])
		Example Input: getAttributeDefaults("Users", exclude = ["databaseId"])
		Example Input: getAttributeDefaults("Users", foreignAsDict = True)
		"""

		def formatValue(columnHandle):
			value = columnHandle.default
			if (value is None):
				return
			if (callable(value.arg)):
				try:
					return value.arg()
				except TypeError:
					return value.arg(None)
			return value.arg

		#######################

		exclude = self.ensure_container(exclude, convertNone = True)

		answer = {}
		relationHandle = self.schema.relationCatalogue[relation]
		for variable in self.ensure_container(self.ensure_default(attribute, lambda: self.getAttributeNames(relation))):
			if (variable in exclude):
				continue

			columnHandle = getattr(relationHandle, variable)
			if (variable not in relationHandle.foreignKeys):
				answer[variable] = formatValue(columnHandle)
				continue

			foreignRelation = relationHandle.foreignKeys[variable].__name__
			foreignHandle = self.schema.relationCatalogue[foreignRelation]
			if (foreignAsDict):
				answer[variable] = {foreign_attribute: formatValue(getattr(foreignHandle, foreign_attribute)) for foreign_attribute in self.getAttributeNames(foreignRelation)}
			else:
				answer[variable] = formatValue(getattr(foreignHandle, self.getPrimaryKey(foreignRelation)))

		if (forceAttribute or (len(answer) is not 1)):
			return answer
		else:
			return next(iter(answer.values()), ())

	@wrap_errorCheck()
	def getTupleCount(self, relation):
		"""Returns the number of tuples (rows) in a relation (table).

		Example Input: getTupleCount("Users")
		"""

	@wrap_errorCheck()
	@MyUtilities.caching.cached(cache_info)
	def getInfo(self, relation, attribute = None, exclude = None, forceAttribute = False):
		"""Returns the info dict for the given columns in 'relation' in the form: {attribute (str): info (dict)}

		relation (str) - The name of the relation
		attribute (str) - The name of the attribute to get the info for. Can be a list of attributes
			- If None: Will get the info for all attributes
		exclude (list) - A list of which attributes to excude from the returned result

		forceAttribute (bool) - Determines if the attribute is returned in the answer
			- If True: Answers will always contain the attribute
			- If False: Answers will omit the attribute if there is only one in the answer

		Example Input: getInfo("Users")
		Example Input: getInfo("Users", ["age", "height"])
		Example Input: getInfo("Users", exclude = ["databaseId"])
		"""

		def yieldInfo():
			nonlocal exclude, relationHandle

			for item in self.ensure_container(attribute, convertNone = False):
				if (item in exclude):
					continue

				if (item is not None):
					yield item, getattr(relationHandle, item).info
					continue

				for subItem in self.getAttributeNames(relation, exclude = exclude):
					yield subItem, getattr(relationHandle, subItem).info

		###########################

		exclude = self.ensure_container(exclude, convertNone = True)
		relationHandle = self.schema.relationCatalogue[relation]

		answer = {key: value for key, value in yieldInfo()}
		if (forceAttribute or (len(answer) is not 1)):
			return answer
		else:
			return next(iter(answer.values()), ())

	@wrap_errorCheck()
	@MyUtilities.caching.cached(cache_creationOrder)
	def getCreationOrder(self, relation, attribute = None, exclude = None, forceAttribute = False):
		"""Returns the order that the columns were created in the schema in the form: {attribute (str): order (int)}

		relation (str) - The name of the relation
		attribute (str) - The name of the attribute to get the creation order for. Can be a list of attributes
			- If None: Will get the creation order for all attributes
		exclude (list) - A list of which attributes to excude from the returned result

		forceAttribute (bool) - Determines if the attribute is returned in the answer
			- If True: Answers will always contain the attribute
			- If False: Answers will omit the attribute if there is only one in the answer

		Example Input: getCreationOrder("Users")
		Example Input: getCreationOrder("Users", ["age", "height"])
		Example Input: getCreationOrder("Users", exclude = ["databaseId"])
		"""

		def yieldOrder():
			nonlocal exclude, relationHandle

			for item in self.ensure_container(attribute, convertNone = False):
				if (item in exclude):
					continue

				if (item is not None):
					yield item, getattr(relationHandle, item)._creation_order
					continue

				for subItem in self.getAttributeNames(relation, exclude = exclude):
					if (subItem in relationHandle.foreignKeys):
						subItem = f"{subItem}_id"
					yield subItem, getattr(relationHandle, subItem)._creation_order

		###########################

		exclude = self.ensure_container(exclude, convertNone = True)
		relationHandle = self.schema.relationCatalogue[relation]

		answer = {key: value for key, value in yieldOrder()}
		if (forceAttribute or (len(answer) is not 1)):
			return answer
		else:
			return next(iter(answer.values()), ())

	@wrap_errorCheck()
	def getSchema(self, relation, forceMatch = False):
		"""Returns the schema handle for the given relation"""

		if (relation in self.schema.relationCatalogue):
			return self.schema.relationCatalogue[relation]
		
		elif (not forceMatch):
			return

		table = self.metadata.tables[relation]

		# schema = type("Facsimile_Schema", (EmptySchema.Mapper, Schema_Base,), {"__tablename__": relation, **{column.name: column for column in table.columns}})()
		
		# for column in table.columns:
		#   print(column.name, column.__class__)
		# print(dir(column))

		# sys.exit()

		
		return schema

	@wrap_errorCheck()
	def getForeignSchema(self, relation, foreignKey = None, forceAttribute = False):
		"""Returns the schema handle for the given foreign key in the given relation.

		relation (str) - The name of the relation
		foreignKey (str) - The name of the foreignKey to get the default for. Can be a list of foreign keys
			- If None: Will get the schema handle for all foreign keys

		forceAttribute (bool) - Determines if the attribute is returned in the answer
			- If True: Answers will always contain the attribute
			- If False: Answers will omit the attribute if there is only one in the answer

		Example Input: getForeignSchema("Users")
		Example Input: getForeignSchema("Users", ["age", "height"])
		Example Input: getForeignSchema("Users", exclude = ["databaseId"])
		"""
		
		catalogue = self.schema.relationCatalogue[relation].foreignKeys

		if (foreignKey is None):
			return catalogue

		answer = {key: catalogue.get(key, None) for key in self.ensure_container(foreignKey)}
		if (not answer):
			return
		elif (forceAttribute or (len(answer) > 1)):
			return answer
		else:
			return next(iter(answer.values()), ())

	def executeCommand(self, command, valueList = None):
		"""Executes raw SQL to the engine.
		Yields each row returned from the command.

		command (str) - The sql to execute

		Example Input: executeCommand("SELECT * FROM Users")
		"""

		def yieldResult(result):
			for row in result:
				yield row

		##############################

		with self.makeConnection() as connection:
			return yieldResult(connection.execute(command, valueList or ()))

	def checkExists(self, myTuple, *, forceRelation = False, **kwargs):
		"""Returns if the given value currently exists or not.

		Example Input: checkExists({"Containers": 1234})
		Example Input: checkExists({"Containers": {None: 1234}})
		Example Input: checkExists({"Containers": {"label": 1234}})
		Example Input: checkExists({"Containers": 1234}, forceRelation = True, forceAttribute = True)
		"""

		answer = {}
		for relation, catalogue in myTuple.items():
			schema = self.schema.relationCatalogue[relation]
			answer[relation] = schema.checkExists(catalogue, **kwargs)

		if (forceRelation or (len(myTuple) > 1)):
			return answer
		return next(iter(answer.values()), ())

	def checkUsed(self, myTuple, *, forceRelation = False, **kwargs):
		"""Returns if the given value is used or not.

		Example Input: checkUsed({"Containers": 1234})
		Example Input: checkUsed({"Containers": {None: 1234}})
		Example Input: checkUsed({"Containers": {"label": 1234}})
		Example Input: checkUsed({"Containers": 1234}, forceRelation = True, forceAttribute = True)
		"""

		answer = {}
		for relation, catalogue in myTuple.items():
			schema = self.schema.relationCatalogue[relation]
			answer[relation] = schema.checkUsed(catalogue, **kwargs)

		if (forceRelation or (len(myTuple) > 1)):
			return answer
		return next(iter(answer.values()), ())

	def uniqueMinimum(self, myTuple, *, forceRelation = False, **kwargs):
		"""Returns the lowest positive unique value.

		Example Input: uniqueMinimum({"Containers": "label"})
		Example Input: uniqueMinimum({"Containers": "label"}, minimum = 10000)
		Example Input: uniqueMinimum({"Containers": "label"}, forceRelation = True, forceAttribute = True)
		"""

		answer = {}
		for relation, attribute in myTuple.items():
			schema = self.schema.relationCatalogue[relation]
			answer[relation] = schema.uniqueMinimum(relation = relation, attribute = attribute, **kwargs)

		if (forceRelation or (len(myTuple) > 1)):
			return answer
		return next(iter(answer.values()), ())

	#Configure SQL functions
	def configureLocation(self, handle, schema, table, fromSchema = False, nextToCondition = True, nextToCondition_None = None, checkForeign = True, forceMatch = True, 
		nextTo = None, notNextTo = None, like = None, notLike = None, isNull = None, isNotNull = None, extra = None, like_caseSensative = False,
		isIn = None, isNotIn = None, isAny = None, isNotAny = None, isAll = None, isNotAll = None, 
		isBetween = None, isNotBetween = None, between_symetric = False, exclude = None,
		greaterThan = None, lessThan = None, greaterThanOrEqualTo = None, lessThanOrEqualTo = None):
		"""Sets up the WHERE portion of the SQL message.

		Example Input: configureLocation("Users", like = {"name": "or"})
		Example Input: configureLocation("Users", like = {"name": ["or", "em"]})

		Example Input: configureLocation("Users", isIn = {"name": "Lorem"})
		Example Input: configureLocation("Users", isIn = {"name": ["Lorem", "Ipsum"]})
		"""

		def yieldValue(_schema, key, value, function, mode = 1, asList = False):

			if (isinstance(value, dict)):
				for _key, _value in value.items():
					for answer in yieldValue(_schema.foreignKeys[key], _key, _value, function, mode = mode, asList = asList):
						yield answer
				return
			
			if (asList):
				value = self.ensure_container(value)

			elif (not isinstance(value, (str, int, float))):
				for _value in value:
					for answer in yieldValue(_schema, key, _value, function, mode = mode, asList = asList):
						yield answer
				return

			if (_schema is None):
				handle = getattr(table.columns, key)
			else:
				handle = getattr(_schema, key)

			if (mode is 1):
				yield function(handle, value)
			else:
				yield getattr(handle, function)(value)

		def yieldLocation():
			if (nextTo):
				for key, value in nextTo.items():
					for answer in yieldValue(schema, key, value, operator.eq): # yield getattr(schema, key) == value
						yield answer
			if (notNextTo):
				for key, value in notNextTo.items():
					for answer in yieldValue(schema, key, value, operator.ne): # yield getattr(schema, key) != value
						yield answer
			if (isNull):
				for key, value in isNull.items():
					for answer in yieldValue(key, None, operator.is_): # yield getattr(schema, key) is None
						yield answer
			if (isNotNull):
				for key, value in isNotNull.items():
					for answer in yieldValue(schema, key, value, operator.is_not): # yield getattr(schema, key) is not None
						yield answer
			if (greaterThan):
				for key, value in greaterThan.items():
					for answer in yieldValue(schema, key, value, operator.gt): # yield getattr(schema, key) > value
						yield answer
			if (greaterThanOrEqualTo):
				for key, value in greaterThanOrEqualTo.items():
					for answer in yieldValue(schema, key, value, operator.ge): # yield getattr(schema, key) >= value
						yield answer
			if (lessThan):
				for key, value in lessThan.items():
					for answer in yieldValue(schema, key, value, operator.lt): # yield getattr(schema, key) < value
						yield answer
			if (lessThanOrEqualTo):
				for key, value in lessThanOrEqualTo.items():
					for answer in yieldValue(schema, key, value, operator.le): # yield getattr(schema, key) <= value
						yield answer

			if (isIn):
				for key, value in isIn.items():
					for answer in yieldValue(schema, key, value, "in_", mode = 2, asList = True): # yield getattr(schema, key).in_(value)
						yield answer
			if (isNotIn):
				for key, value in isNotIn.items():
					for answer in yieldValue(schema, key, value, "in_", mode = 2, asList = True): # yield ~(getattr(schema, key).in_(value))
						yield ~answer
			if (isAll):
				for key, value in isAll.items():
					for answer in yieldValue(schema, key, value, "all_", mode = 2, asList = True): # yield getattr(schema, key).all_(value)
						yield answer
			if (isNotAll):
				for key, value in isNotAll.items():
					for answer in yieldValue(schema, key, value, "all_", mode = 2, asList = True): # yield ~(getattr(schema, key).all_(value))
						yield ~answer
			if (isAny):
				for key, value in isAny.items():
					for answer in yieldValue(schema, key, value, "any_", mode = 2, asList = True): # yield getattr(schema, key).any_(value)
						yield answer
			if (isNotAny):
				for key, value in isNotAny.items():
					for answer in yieldValue(schema, key, value, "any_", mode = 2, asList = True): # yield ~(getattr(schema, key).any_(value))
						yield ~answer

			if (like):
				if (like_caseSensative):
					for key, value in like.items():
						for answer in yieldValue(schema, key, value, "like", mode = 2): # yield getattr(schema, key).like(value)
							yield answer
				else:
					for key, value in like.items():
						for answer in yieldValue(schema, key, value, "ilike", mode = 2): # yield getattr(schema, key).ilike(value)
							yield answer
			if (notLike):
				if (like_caseSensative):
					for key, value in notLike.items():
						for answer in yieldValue(schema, key, value, "like", mode = 2): # yield ~(getattr(schema, key).like(value))
							yield ~answer
				else:
					for key, value in notLike.items():
						for answer in yieldValue(schema, key, value, "ilike", mode = 2): # yield ~(getattr(schema, key).ilike(value))
							yield ~answer

			if (isBetween):
				for key, (left, right) in isBetween.items():
					for answer in yieldValue(schema, key, value, "between", mode = 2): # yield getattr(schema, key).between(left, right, symetric = between_symetric)
						yield answer
			if (isNotBetween):
				for key, (left, right) in isNotBetween.items():
					for answer in yieldValue(schema, key, value, "between", mode = 2): # yield ~(getattr(schema, key).between(left, right, symetric = between_symetric))
						yield ~answer


		######################################################

		if (fromSchema is None):
			locationFunction = handle.where
		else:
			locationFunction = handle.filter

		if (nextToCondition):
			return locationFunction(sqlalchemy.and_(*yieldLocation()))
		else:
			return locationFunction(sqlalchemy.or_(*yieldLocation()))

	def configureOrder(self, handle, relation, schema, table, orderBy = None, direction = None, nullFirst = None):
		"""Sets up the ORDER BY portion of the SQL message."""

		if (schema is None):
			def getBase(_orderBy):
				return getattr(table.columns, _orderBy or self.getPrimaryKey(relation))
		else:
			def getBase(_orderBy):
				return getattr(schema, _orderBy or self.getPrimaryKey(relation))

		if (isinstance(direction, dict)):
			def getDirection(criteria, attribute):
				if (attribute in direction):
					if (direction[attribute]):
						criteria = sqlalchemy.asc(criteria)
					else:
						criteria = sqlalchemy.desc(criteria)
				return criteria
		else:
			def getDirection(criteria, attribute):
				if (direction):
					return sqlalchemy.asc(criteria)
				else:
					return sqlalchemy.desc(criteria)

				# if (nullFirst is not None):
				#   if (nullFirst):
				#       criteria = criteria.nullsfirst()
				#   else:
				#       criteria = criteria.nullslast()

		def yieldOrder():
			for _orderBy in self.ensure_container(orderBy):
				criteria = getBase(_orderBy)

				if (direction is not None):
					criteria = getDirection(criteria, _orderBy)

				yield criteria

		###############################################

		return handle.order_by(*yieldOrder())

	def configureJoinForeign(self, query, relation, schema, table, attribute, fromSchema = False):
		"""Sets up the JOIN portion of the SQL message (with respect to foreign keys)."""

		if (schema is None):
			if (not table.foreign_keys):
				return query
		elif (fromSchema or (not schema.foreignKeys)):
			return query

		###############################################

		if (schema is None):
			foreignCatalogue = {foreignKey.column.name: foreignKey.column.table for foreignKey in table.foreign_keys}
		else:
			foreignCatalogue = schema.foreignKeys

		def augmentHandle(_handle, attributeList):
			for variable in self.ensure_container(attributeList):
				if (isinstance(variable, dict)):
					_handle = augmentHandle(_handle, variable.keys())
					continue
				if (variable not in foreignCatalogue):
					continue

				_handle = _handle.join(foreignCatalogue[variable])
			return _handle

		###############################################
		
		if (fromSchema is None):
			return query.select_from(augmentHandle(self.metadata.tables[relation], attribute))
		return augmentHandle(query, attribute)

	def configureJoinDomestic(self, query, relation, schema, table, connection, fromSchema, join, foreignAsDict):
		"""Sets up the JOIN portion of the SQL message (with respect to other relations).

		join (tuple) - Joins the yielded queries when this dictionary is given to yieldValueQuery() as kwargs
			~ (variable from this relation (str), relation to join with (str), variable from joined relation (str), what variables from joined relation to take (tuple of strings))
		"""

		if (join is None):
			return query

		# if (schema is None):
		# 	_handle = self.metadata.tables[relation]
		# 	relationHandle = self.metadata.tables[relation].columns
		# else:
		# 	_handle = query
		# 	relationHandle = schema.relationCatalogue[relation]

		relationHandle = self.metadata.tables[relation]
		_handle = relationHandle
		for attribute, foreign_relation, foreign_attribute, attributeList in self.ensure_container(join, elementCriteria = (4, (str, str, str, tuple))):
			foreignRelationHandle = self.metadata.tables[foreign_relation]
			_handle = _handle.join(foreignRelationHandle, getattr(relationHandle.columns, attribute) == getattr(foreignRelationHandle.columns, foreign_attribute))

		return query.select_from(_handle)


			# attributeHandle = getattr(relationHandle, attribute)
			# kwargs["fromSchema"] = fromSchema
			# kwargs["connection"] = connection
			# kwargs["foreignAsDict"] = foreignAsDict
			# print("@1", attribute, join_attribute)
			# print([query])
			# print(query)
			# print()

			# relationHandle.

















			# for _query in self.yieldValueQuery(**kwargs, yieldQueryOnly = True):

			# 	print([_query])
			# 	print(_query)
			# 	print()

			# 	# __query = _query.join(query)
			# 	# print([__query])
			# 	# print(__query)
			# 	# print()
			# 	# return query.select_from(__query)

			# 	with self.makeSession(close = True) as session:
			# 		__query = session.query(_query)
					
			# 		print([__query])
			# 		print(__query)
			# 		print()

			# 		subquery = __query.subquery()

			# 		___query = _handle.join(subquery)
					
			# 		print([___query])
			# 		print(___query)
			# 		print()

			# 		return query.select_from(___query)



			# 	# raise NotImplementedError()

			# 	# if (isinstance(join_attribute, str)):
			# 	# 	foreign_attribute = None
			# 	# else:
			# 	# 	join_attribute, foreign_attribute = join_attribute

			# 	# if (join_attribute in _query.columns):
			# 	# 	foreignHandle = _query.columns[join_attribute]
			# 	# else:
			# 	# 	for column in _query.columns:
			# 	# 		foreignMatch = re.search("zfk_(.*)_zfk_(.*)", column.name)
			# 	# 		if (not foreignMatch):
			# 	# 			continue

			# 	# 		if (foreign_attribute is None):
			# 	# 			_foreign_attribute = column.table.name
			# 	# 		else:
			# 	# 			_foreign_attribute = foreign_attribute

			# 	# 		if ((foreignMatch.group(1) == join_attribute) and (foreignMatch.group(1) == _foreign_attribute)):
			# 	# 			foreignHandle = column
			# 	# 			break
			# 	# 	else:
			# 	# 		raise NotImplementedError()



			# 	# # print("@5", tuple(yieldAttribute(_query)))

			# 	# # print("@5", _query.where(attributeHandle == getattr(_query.columns, join_attribute)))

			# 	# if (fromSchema is None):
			# 	# 	print()
			# 	# 	print(_query)
			# 	# 	print()
			# 	# 	print(_query.where(attributeHandle == foreignHandle))
			# 	# 	print()
			# 	# 	handle = handle.join(_query.where(attributeHandle == foreignHandle))
			# 	# 	print(handle) #Not working yet. Gives a syntax error. I am doing something wrong with how these two are joined.
			# 	# 	raise NotImplementedError()
			# 	# else:
			# 	# 	subquery = _query.subquery()
			# 	# 	handle = handle.join(subquery, attributeHandle == getattr(subquery.columns, join_attribute))
		
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
	def openDatabase_fromConfig(self, filePath, section = None, settingsKwargs = None, **kwargs):
		"""Opens a database as directed to from the given config file.

		___________________ REQUIRED FORMAT ___________________

		[{section}]
		port = {}
		host = {}
		user = {}
		password = {}
		fileName = {}

		readOnly = {} #Optional
		schemaPath = {} #Optional
		alembicPath = {} #Optional
		openAlembic = {} #Optional
		connectionType = {} #Optional
		_______________________________________________________

		filePath (str) - Where the config file is located
		section (str) - What section in the config file to use

		Example Input: openDatabase_fromConfig("settings.ini")
		"""

		self.log_info("Opening Database from config file", filePath = filePath, section = section)

		config = db_config.build(default_filePath = filePath, default_section = section)
		return self.openDatabase(**{**config.get({section: ("port", "host", "user", "password", "fileName", "readOnly", "schemaPath", 
			"alembicPath", "openAlembic", "connectionType", "reset", "override_resetBypass", "refresh_metaData")}, fallback = None, default_values = settingsKwargs or {}), **kwargs})

	@wrap_errorCheck()
	def openDatabase(self, fileName = None, schemaPath = None, alembicPath = None, *, applyChanges = True, multiThread = False, connectionType = None, 
		openAlembic = False, readOnly = False, multiProcess = -1, multiProcess_delay = 100, forceExtension = False, reset = None, override_resetBypass = False,
		port = None, host = None, user = None, password = None, echo = False, refresh_metaData = True, 
		resultError_replacement = None, aliasError_replacement = None):

		"""Opens a database.If it does not exist, then one is created.
		Note: If a database is already opened, then that database will first be closed.
		Use: toLarry Lustig for help with multi-threading on http://stackoverflow.com/questions/22739590/how-to-share-single-sqlite-connection-in-multi-threaded-python-application
		Use: to culix for help with multi-threading on http://stackoverflow.com/questions/6297404/multi-threaded-use-of-sqlalchemy
		
		Use: https://stackoverflow.com/questions/9233912/connecting-sqlalchemy-to-msaccess/13849359#13849359
		Use: https://docs.sqlalchemy.org/en/latest/core/connections.html#registering-new-dialects
		Use: http://www.blog.pythonlibrary.org/2010/10/10/sqlalchemy-and-microsoft-access/

		Special thanks to jmagnusson for how to connect to a mssql database on: https://stackoverflow.com/questions/4493614/sqlalchemy-equivalent-of-pyodbc-connect-string-using-freetds/7399585#7399585

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

		openAlembic(bool) - Determines if the alembicPath should be used
			- If True: Will start alembic
			- If False: Will not start alembic
			- If None: Will start alembic if fileName is not None

		Example Input: openDatabase()
		Example Input: openDatabase("emaildb")
		Example Input: openDatabase("emaildb.sqllite")
		Example Input: openDatabase("emaildb", "test_map")
		Example Input: openDatabase("emaildb", applyChanges = False)
		Example Input: openDatabase("emaildb", multiThread = True)
		Example Input: openDatabase("emaildb", multiThread = True, multiProcess = 10)
		"""

		assert not isinstance(reset, str)

		@contextlib.contextmanager
		def makeEngine():
			global sessionMaker
			nonlocal self, user, password, host, port, fileName, schemaPath, openAlembic, alembicPath, refresh_metaData

			self.isAccess = self.connectionType == "access"
			self.isSQLite = self.connectionType == "sqlite3"
			self.isMySQL = self.connectionType == "mysql"
			self.isMsSQL = self.connectionType == "mssql"

			self.baseFileName = fileName

			if (self.isMySQL):
				engineKwargs = {"connect_args": {"time_zone": "+00:00"}, "pool_recycle": 3600}
				self.fileName = f"mysql+mysqlconnector://{user}:{password}@{host or 'localhost'}:{port or 3306}/{fileName}"

			elif (self.isSQLite):
				engineKwargs = {}
				self.fileName = f"sqlite:///{fileName}"
			
			elif (self.isAccess):
				engineKwargs = {"encoding": "latin1", "convert_unicode": True}
				self.fileName = f"access+fixed:///{fileName}?charset={engineKwargs['encoding']}"

			elif (self.isMsSQL):
				engineKwargs = {}
				self.fileName = "mssql+pyodbc:///?odbc_connect={}".format(urllib.parse.quote_plus(f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={host or localhost};PORT={port or 3306};DATABASE={fileName};UID={user};PWD={password}"))

			else:
				errorMessage = f"Unknown connection type {connectionType}"
				raise KeyError(errorMessage)

			if (reset is False):
				_reset = False
			else:
				if (self.isMySQL):
					_reset = not sqlalchemy_utils.database_exists(self.fileName)
				else:
					_reset = not os.path.exists(fileName)

			yield engineKwargs
			sessionMaker.configure(bind = self.engine)

			if (self.isSQLite):
				sqlalchemy.event.listen(self.engine, 'connect', self._fk_pragma_on_connect)

			if (_reset):
				self.createDatabase()
			elif (reset):
				self.removeDatabase()
				self.createDatabase()
				_reset = True

			self.loadSchema(schemaPath, refresh_metaData = refresh_metaData)

			if (openAlembic or ((openAlembic is None) and fileName)):
				self.loadAlembic(alembicPath)
			else:
				self.alembic = None

			if (_reset):
				print(f"Creating Fresh Database for {fileName}")
				self.createRelation()
				self.resetRelation(override_resetBypass = override_resetBypass)

				if (self.alembic):
					self.alembic.stamp()

		#########################

		self.log_info("Opening Database", fileName = fileName, schemaPath = schemaPath, openAlembic = openAlembic)

		if (not fileName):
			fileName = "" #":memory:"
			connectionType = "sqlite3"
		else:
			#Check for file extension
			if (forceExtension and ("." not in fileName)):
				fileName += f".{self.defaultFileExtension}"

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
		#   self.resultError_replacement = "!!! SELECT ERROR !!!"

		with makeEngine() as engineKwargs:
			self.log_info("Creating Engine", fileName = self.fileName, **engineKwargs)
			self.engine = sqlalchemy.create_engine(self.fileName, **engineKwargs, echo = echo)

	def _fk_pragma_on_connect(self, connection, record):
		"""Turns foreign keys on for SQLite.
		Modified code from conny on: https://stackoverflow.com/questions/2614984/sqlite-sqlalchemy-how-to-enforce-foreign-keys
		"""

		connection.execute('pragma foreign_keys=ON')

	@wrap_errorCheck()
	def removeDatabase(self, filePath = None):
		"""Removes an entire database file
		filePath (str) - Where the database is located
			- If None: will use the current database's file path

		Example Input: removeDatabase()
		Example Input: removeDatabase("material_database")
		"""

		if (filePath is None):
			sqlalchemy_utils.drop_database(self.engine.url)
		else:
			sqlalchemy_utils.drop_database(filePath)

	@wrap_errorCheck()
	def createDatabase(self, filePath = None, encoding = "utf8"):
		"""Creates a new database file
		filePath (str) - Where the database will be located
			- If None: will use the current database's file path

		Example Input: createDatabase()
		Example Input: createDatabase("material_database")
		Example Input: createDatabase("material_database", encoding = "latin1")
		"""

		if (filePath is None):
			sqlalchemy_utils.create_database(self.engine.url, encoding = encoding)
		else:
			sqlalchemy_utils.create_database(filePath, encoding = encoding)

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

	def loadSchema(self, schemaPath = None, refresh_metaData = True):
		"""Loads in a schema from the given schemaPath.

		Example Input: loadSchema(schemaPath)
		"""

		#Get Schema
		if (not schemaPath):
			self.schema = EmptySchema
			# self.metadata = sqlalchemy.MetaData(bind = self.engine)
			# self.refresh()
			# return

		elif (os.path.isfile(schemaPath)):
			sys.path.append(os.path.dirname(schemaPath))
			schemaPath = os.path.splitext(os.path.basename(schemaPath))[0]
			self.schema = importlib.import_module(schemaPath)
		else:
			self.schema = importlib.import_module(schemaPath)

		#Finish Schema Catalogues
		self.schema.usedByCatalogue = {}
		if (__name__ == "__main__"):
			self.schema.relationCatalogue = {}
			self.schema.hasForeignCatalogue = {}

			filterFunction = MyUtilities.common.yieldBaseClass
			for variable, cls in vars(self.schema).items():
				if (getattr(cls, "__module__", None) != self.schema.__name__):
					continue
				if (any(True for item in filterFunction(cls, include = Schema_Used.__name__, filterByModule = False, onlyName = True))):
					cls.usedBy = collections.defaultdict(set)
					self.schema.usedByCatalogue[cls.__tablename__] = None
				if (any(True for item in filterFunction(cls, include = Schema_Base.__name__, filterByModule = False, onlyName = True))):
					self.schema.relationCatalogue[cls.__tablename__] = cls
				if (any(True for item in filterFunction(cls, include = Schema_AutoForeign.__name__, filterByModule = False, onlyName = True))):
					self.schema.hasForeignCatalogue[cls.__tablename__] = cls
		else:
			self.schema.relationCatalogue = {cls.__tablename__: cls for cls in Schema_Base.yieldSubClass(include = self.schema.__name__)}
			self.schema.hasForeignCatalogue = {cls.__tablename__: cls for cls in Schema_AutoForeign.yieldSubClass(include = self.schema.__name__)}

			for cls in Schema_Used.yieldSubClass(include = self.schema.__name__):
				cls.usedBy = collections.defaultdict(set)
				self.schema.usedByCatalogue[cls.__tablename__] = None
		
		##Fill usedCatalogue
		self.schema.usedCatalogue = {}
		for relation, relationHandle in self.schema.relationCatalogue.items():
			relationHandle.usedCatalogue = {}
			for column, columnHandle in relationHandle.__mapper__.columns.items():
				_used = columnHandle._used
				if (_used is None):
					continue

				relationHandle.usedCatalogue[column] = _used
				_used.usedBy[relationHandle].add(column)

			relationHandle.usedCatalogue = {column: columnHandle._used for column, columnHandle in relationHandle.__mapper__.columns.items() if (columnHandle._used is not None)}
			self.schema.usedCatalogue[relation] = relationHandle.usedCatalogue

		for relation in self.schema.usedByCatalogue.keys():
			relationHandle = self.schema.relationCatalogue[relation]
			relationHandle.usedBy = dict(relationHandle.usedBy) #Remove defaultdict
			self.schema.usedByCatalogue[relation] = relationHandle.usedBy

		##Finalize Foreign Relations
		for module in self.schema.hasForeignCatalogue.values():
			module.formatForeign(self.schema.relationCatalogue)

		##Record Primary Keys
		for module in self.schema.relationCatalogue.values():
			module._primaryKeys = tuple(attribute for attribute, columnHandle in module.__mapper__.columns.items() if (columnHandle.primary_key))

		#Bind Schema
		self.schemaPath = schemaPath
		self.schema.Mapper.metadata.bind = self.engine
		self.metadata = self.schema.Mapper.metadata
		
		if (refresh_metaData is not False):
			self.refresh()

	def checkSchema(self):
		"""Checks the loaded schema against what is in the meta data."""

		raise NotImplementedError()

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
	def resetRelation(self, relation = None, *, override_resetBypass = False):
		"""Resets the relation to factory default, as described in the schema.

		relation (str) - What the relation is called in the .db
			- If None: All tables will be reset from the .db

		Example Input: resetRelation()
		Example Input: resetRelation("Users")
		"""

		def filterFunction(relationHandle):
			nonlocal self

			first = relationHandle.__tablename__ not in self.schema.hasForeignCatalogue #Do these first
			second = issubclass(relationHandle, Schema_Used) #Do these last

			return (first, second)

		###############################################

		if (relation is None):
			for relationHandle in sorted(self.schema.relationCatalogue.values(), key = filterFunction):
				relationHandle.reset(override_resetBypass = override_resetBypass)
		else:
			relationHandle = self.schema.relationCatalogue[relation]
			relationHandle.reset(override_resetBypass = override_resetBypass)

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
		#   table = self.metadata.tables.get(relation)
		#   if (table is None):
		#       errorMessage = f"There is no table {relation} in {self.metadata.__repr__()} for removeRelation()"
		#       raise KeyError(errorMessage)

		#   try:
		#       table.drop()
		#   except sqlalchemy.exc.UnboundExecutionError:
		#       table.drop(self.engine)

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
	def createRelation(self, relation = None, schemaPath = None, refresh_metaData = True):
		"""Adds a relation (table) to the database.
		Special thanks to Jimbo for help with spaces in database names on http://stackoverflow.com/questions/10920671/how-do-you-deal-with-blank-spaces-in-column-names-in-sql-server
		
		relation (str)      - What the relation will be called in the .db
			- If None: Will create all tables in 'schemaPath'
		schemaPath (str)    - What path to take to get the schema for this relation
			- If None: Will use the default schema given to openDatabase()

		Example Input: createRelation("Users", {"email": str, "count": int})
		Example Input: createRelation("Users", [{"email": str}, {"count": int}])
		Example Input: createRelation("Users", {"email": str, "count": int}, applyChanges = False)
		Example Input: createRelation("Users", {"databaseId": int, "email": str, "count": int}, notNull = {"databaseId": True}, primary = {"databaseId": True}, autoIncrement = {"databaseId": True}, unique = {"databaseId": True}, autoPrimary = False)
		
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

		raise NotImplementedError()

		if (schemaPath is None):
			schema = self.schema
		else:
			schema = self.loadSchema(schemaPath, refresh_metaData = refresh_metaData)

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
	def addTuple(self, myTuple = None, applyChanges = None, autoPrimary = False, notNull = False, foreignNone = False, fromSchema = False,
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

		if (fromSchema is None):
			with self.makeConnection(asTransaction = True) as connection:
				for relation, rows in myTuple.items():
					#Does not handle foreign keys
					table = self.metadata.tables[relation]
					for attributeDict in self.ensure_container(rows):
						connection.execute(table.insert(values = attributeDict))
		else:
			with self.makeSession() as session:
				for relation, rows in myTuple.items():
					schema = self.schema.relationCatalogue[relation]
					for attributeDict in self.ensure_container(rows):
						session.add(schema(**attributeDict, session = session))

	@wrap_errorCheck()
	def changeTuple(self, myTuple, nextTo, value = None, forceMatch = None, applyChanges = None, checkForeign = True, updateForeign = None, fromSchema = False, **locationKwargs):
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
			- If None: Raise error

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

		if (fromSchema is None):
			with self.makeConnection(asTransaction = True) as connection:
				for relation, rows in myTuple.items():
					table = self.metadata.tables[relation]
					for attributeDict in self.ensure_container(rows):
						#Does not handle foreign keys
						query = table.update(values = attributeDict)
						query = self.configureLocation(query, table.columns, table, fromSchema = fromSchema, nextTo = nextTo, **locationKwargs)
						connection.execute(query)
		else:
			forcedList = []
			with self.makeSession() as session:
				for relation, rows in myTuple.items():
					schema = self.schema.relationCatalogue[relation]
					for attributeDict in self.ensure_container(rows):
						query = session.query(schema)
						query = self.configureLocation(query, schema, None, fromSchema = fromSchema, nextTo = nextTo, **locationKwargs)

						if ((forceMatch is not False) and (query.count() is 0)):
							if (forceMatch is None):
								self.printSQL(query)
								errorMessage = f"There is no row in {relation} that matches the criteria {attributeDict}, {nextTo}, and {locationKwargs}"
								raise KeyError(errorMessage)

							forcedList.append({**attributeDict, **(nextTo or {})})
							continue

						for row in query.all():
							try:
								row.change(session, values = attributeDict, updateForeign = updateForeign)

							except Exception as error:
								print("--", attributeDict, updateForeign)
								traceback.print_exc()
								continue

			if (forcedList):
				with self.makeSession() as session:
					session.add_all(schema(**catalogue, session = session) for catalogue in forcedList)

	@wrap_errorCheck()
	def removeTuple(self, myTuple, applyChanges = None, checkForeign = True, incrementForeign = True, fromSchema = None, **locationKwargs):
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

		if (fromSchema is None):
			with self.makeConnection(asTransaction = True) as connection:
				for relation, rows in myTuple.items():
					table = self.metadata.tables[relation]
					for nextTo in self.ensure_container(rows):
						query = table.delete()
						query = self.configureLocation(query, table.columns, table, fromSchema = fromSchema, nextTo = nextTo, **locationKwargs)
						connection.execute(query)
		else:
			with self.makeSession() as session:
				for relation, rows in myTuple.items():
					schema = self.schema.relationCatalogue[relation]
					for nextTo in self.ensure_container(rows):
						query = session.query(schema)
						query = self.configureLocation(query, schema, None, fromSchema = fromSchema, nextTo = nextTo, **locationKwargs)
						query.delete()

	def _setupYieldAllValues(self, relation = None, attribute = None, exclude = None):
		if (relation is None):
			relation = self.getRelationNames()
		else:
			relation = self.ensure_container(relation)

		if (isinstance(exclude, dict)):
			excludeList = {item for _relation in relation for item in exclude.get(_relation, ())}
		else:
			excludeList = self.ensure_container(exclude, convertNone = True)

		myTuple = {}
		for _relation in relation:
			if (attribute):
				if (isinstance(attribute, dict)):
					myTuple[_relation] = attribute.get(_relation, None)
				else:
					myTuple[_relation] = attribute
			else:
				myTuple[_relation] = None

		return myTuple, excludeList

	@wrap_errorCheck()
	def yieldAllValues(self, relation = None, attribute = None, exclude = None, **kwargs):
		"""
		Example Use:
			for relation, attributeList, query in database_API.yieldAllValues(None):
				print([relation, attributeList, query])
				for result in query.all():
					print("   ", result)

		Example Use:
			with database_API._yieldValue_getConnection(fromSchema = None) as connection:
				for relation, attributeList, query in database_API.yieldAllValues(None, fromSchema = None, connection = connection):
					print([relation, attributeList, query])
					for result in connection.execute(query).fetchall():
						print("   ", result)
		"""
		myTuple, excludeList = self._setupYieldAllValues(relation = relation, attribute = attribute, exclude = exclude)
		for item in self.yieldValueQuery(myTuple, exclude = excludeList, **kwargs):
			yield item

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
		Example Input: getAllValues(["Users", "Names"], orderBy = "databaseId")

		database_API.getAllValues("Containers", foreignAsDict = True, foreignDefault = ("label", "archived"))
		database_API.getAllValues("Containers", foreignDefault = ("label", "archived"))
		"""

		myTuple, excludeList = self._setupYieldAllValues(relation = relation, attribute = attribute, exclude = exclude)
		return self.getValue(myTuple, exclude = excludeList, **kwargs)

	def _yieldValue_getConnection(self, fromSchema):
		if (fromSchema is None or (self.schema is None) or (isinstance(self.schema, EmptySchema))):
			return self.makeConnection(asTransaction = True)
		return self.makeSession(close = not fromSchema)

	@wrap_errorCheck()
	def yieldValueQuery(self, myTuple, nextTo = None, *, connection = None, yieldQueryOnly = False,
		count = False, fromSchema = False, foreignAsDict = False, includeSession = None, 
		orderBy = None, limit = None, direction = None, nullFirst = None, alias = None, join = None,
		includeDuplicates = True, exclude = None, forceMatch = None, foreignDefault = None, **locationKwargs):
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
			- If None: Will return all foreign attributes
			- If str: Will return only that foreign attribute
			- If list: Will return all foreign attributes in list

		forceRelation (bool)  - Determines if the relation is returned in the answer
			- If True: Answers will always contain the relation
			- If False: Answers will omit the relation if there is only one in the answer
		forceAttribute (bool) - Determines if the attribute is returned in the answer
			- If True: Answers will always contain the attribute
			- If False: Answers will omit the attribute if there is only one in the answer
		forceTuple (bool) - Determines if the row separator is returned in the answer
			- If True: Answers will always contain the row separator
			- If False: Answers will omit the row separator if there is only one in the answer
		attributeFirst (bool) - Determines if the attribute is first in the answer
			- If True: {relation: {attribute: {row: value}}}
			- If False: {relation: {row: {attribute: value}}}

		fromSchema (bool) - Determines from what source the query is compiled
			- If True: Uses the schema and returns a schema item (slowest)
				~ All values are lazy loaded by default, so be sure to use 'includeSession' correctly
			- If False: Uses the schema and returns a dictionary
			- If None: Uses the metadata and returns a dictionary (fastest)

		includeSession (bool) - Determines how the session is given to the user
			- If True: The session is in the catalogue under the relation key [None], so 'forceRelation' will be ignored
			- If False: The returned value is a tuple where the first element is the session and the second is the answer
			- If None: The session is not returned
				~ If 'fromSchema' is True: All values in 'myTuple' will be eagerly loaded before the session is closed

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

		if (connection is None):
			with self._yieldValue_getConnection(fromSchema = fromSchema) as _connection:
				for item in self.yieldValueQuery(myTuple, nextTo, connection = _connection, yieldQueryOnly = yieldQueryOnly, 
					count = count, fromSchema = fromSchema, foreignAsDict = foreignAsDict, includeSession = includeSession, 
					orderBy = orderBy, limit = limit, direction = direction, nullFirst = nullFirst, alias = alias, join = join, 
					includeDuplicates = includeDuplicates, exclude = exclude, forceMatch = forceMatch, foreignDefault = foreignDefault, **locationKwargs):
					
					yield item
			return

		#####################################################################

		if ((self.schema is None) or (isinstance(self.schema, EmptySchema))):
			fromSchema = None

		if (fromSchema is None):
			def startQuery(relation, attributeList, schema, table):
				nonlocal self, excludeList, alias

				if (schema is not None):
					return sqlalchemy.select(columns = schema.yieldColumn(attributeList, excludeList, alias, foreignAsDict = foreignAsDict, foreignDefault = foreignDefault))
				return sqlalchemy.select(columns = self.yieldColumn_fromTable(table, attributeList, excludeList, alias, foreignAsDict = foreignAsDict, foreignDefault = foreignDefault))

		elif (fromSchema):
			def startQuery(relation, attributeList, schema, table):
				nonlocal connection, includeSession
				assert schema is not None

				query = connection.query(schema)
				if (includeSession is None):
					query = query.options(sqlalchemy.orm.selectinload("*"))
				return query
		else:
			def startQuery(relation, attributeList, schema, table):
				nonlocal connection, excludeList, alias
				assert schema is not None

				return connection.query(*schema.yieldColumn(attributeList, excludeList, alias, foreignAsDict = foreignAsDict, foreignDefault = foreignDefault)).select_from(schema)

		########################################################################

		if (not isinstance(exclude, dict)):
			excludeList = self.ensure_container(exclude, convertNone = True)

		assert myTuple
		for relation, attributeList in myTuple.items():
			if (fromSchema):
				attributeList = ()
			else:
				if (isinstance(exclude, dict)):
					excludeList = {item for _relation in relation for item in exclude.get(_relation, ())}
				attributeList = self.ensure_container(attributeList) or self.getAttributeNames(relation, foreignAsDict = foreignAsDict)

			schema = self.getSchema(relation)#, forceMatch = True)
			table = self.metadata.tables[relation]

			query = startQuery(relation, attributeList, schema, table)
			query = self.configureJoinForeign(query, relation, schema, table, attributeList, fromSchema = fromSchema)
			query = self.configureJoinDomestic(query, relation, schema, table, connection, fromSchema, join, foreignAsDict)
			query = self.configureOrder(query, relation, schema, table, orderBy = orderBy, direction = direction, nullFirst = nullFirst)
			query = self.configureLocation(query, schema, table, fromSchema = fromSchema, nextTo = nextTo, **locationKwargs)

			if (limit is not None):
				query = query.limit(limit)
			if (not includeDuplicates):
				query = query.distinct()
			if (count and (fromSchema is None)):
				query = query.count()

			if (yieldQueryOnly):
				yield query
			else:
				yield relation, attributeList, query

	def getValue(self, myTuple, nextTo = None, *args, 
		count = False, fromSchema = False, foreignAsDict = False, includeSession = None, 
		valuesAsSet = False, onlyOne = False, attributeFirst = False, noAnswer = NULL_private, 
		forceRelation = False, forceAttribute = False, forceTuple = False, **kwargs):
		if ((self.schema is None) or (isinstance(self.schema, EmptySchema))):
			fromSchema = None



		def _makeCatalogue(result):
			nonlocal attributeList

			class _dict(dict):
				"""Used to allow value to be a dict without messing up the process below."""
			class _list(list):
				"""Used to allow value to be a list without messing up the process below."""

			def _formatValue(existingValue, newValue):

				if (isinstance(existingValue, _list)):
					existingValue.append(newValue)
				else:
					existingValue = _list(existingValue, newValue)
				return existingValue

			############################################
			
			catalogue = collections.defaultdict(_dict)
			if (fromSchema is None):
				iterator = result.items()
			else:
				iterator = result._asdict().items()

			for key, value in iterator:
				foreignMatch = re.search("zfk_(.*)_zfk_(.*)", key)

				if (foreignMatch):
					attribute = foreignMatch.group(1)
					foreign_attribute = foreignMatch.group(2)
				else:
					attribute = key
					foreign_attribute = None

				# if (attribute not in attributeList):
				# 	continue

				if (attribute not in catalogue):
					if (foreign_attribute is None):
						catalogue[attribute] = value
					else:
						catalogue[attribute][foreign_attribute] = value
					continue

				if (not isinstance(catalogue[attribute], _dict)):
					_value = catalogue[attribute]
					catalogue[attribute] = _dict()
					catalogue[attribute][foreign_attribute] = _formatValue(_value, value)
					continue

				if (foreign_attribute not in catalogue[attribute]):
					catalogue[attribute][foreign_attribute] = value
				else:
					catalogue[attribute][foreign_attribute] = _formatValue(catalogue[attribute][foreign_attribute], value)
			return dict(catalogue)

		if (fromSchema is None):
			def yieldRow(query):
				nonlocal connection, attributeList

				catalogue = self.engine.url.query
				if (("charset" in catalogue) and (catalogue["charset"] != "utf8")):
					def yieldResult():
						nonlocal connection, query

						if (onlyOne):
							def _yieldResult():
								yield connection.execute(query).first()
						else:
							_yieldResult = connection.execute(query).fetchall

						##############################

						#Search for invalid strings, and fix them
						for result in _yieldResult():
							replacement_catalogue = {}
							for key, value in result.items():
								if (isinstance(value, str)):
									try:
										value.encode('ascii')
									except UnicodeEncodeError as error:
										replacement_catalogue[key] = unidecode.unidecode_expect_nonascii(value)
							if (replacement_catalogue):
								result = dict(result)
								result.update(replacement_catalogue)

							yield result
			
				elif (onlyOne):
					def yieldResult():
						yield connection.execute(query).first()
				else:
					yieldResult = connection.execute(query).fetchall

				###################################

				for result in itertools.filterfalse(lambda x: x is None, yieldResult()):
					if ((not forceAttribute) and (len(result) <= 1)):
						yield result[0]

					elif (not foreignAsDict):
						yield dict(result)

					else:
						yield _makeCatalogue(result)

		elif (fromSchema):
			def yieldRow(query):
				nonlocal count              

				if (count):
					yield (query.count(),)
					return

				if (onlyOne):
					yield query.first()
					return

				for result in query.all():
					yield result

		else:
			def yieldRow(query):
				nonlocal count

				if (count):
					yield (query.count(),)
					return

				if (onlyOne):
					answer = (query.first(),)
				else:
					answer = query.all()

				for result in answer:
					if (result is None):
						continue

					elif ((not forceAttribute) and (len(result) <= 1)):
						yield result[0]

					elif (not foreignAsDict):
						yield result._asdict()

					else:
						yield _makeCatalogue(result)

		container = (tuple, set)[valuesAsSet]
		def getResult(query):
			nonlocal forceTuple, container, noAnswer

			answer = container(yieldRow(query))

			if (not answer):
				if (noAnswer is NULL_private):
					return container()
				elif (callable(noAnswer)):
					return noAnswer()
				return noAnswer

			elif (forceTuple or (len(answer) > 1)):
				if ((not attributeFirst) or (not isinstance(answer[-1], dict))):
					return answer

				catalogue = collections.defaultdict(list)
				for row in answer:
					for key, value in row.items():
						catalogue[key].append(value)
				return {key: container(value) for key, value in catalogue.items()}

			else:
				return answer[0]

		########################################################################

		results_catalogue = {}
		with self._yieldValue_getConnection(fromSchema = fromSchema) as connection:
			if (includeSession):
				results_catalogue[None] = connection

			for relation, attributeList, query in self.yieldValueQuery(myTuple, nextTo, *args, connection = connection, count = count, fromSchema = fromSchema, foreignAsDict = foreignAsDict, includeSession = includeSession, **kwargs):
				results_catalogue[relation] = getResult(query)
		
			if (includeSession is False):
				return connection, self.oneOrMany(results_catalogue, forceTuple = forceRelation, isDict = True)
		return self.oneOrMany(results_catalogue, forceTuple = forceRelation, isDict = True)

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

	def backup(self, destination = None, *, username = None, password = None, closeIO = None):
		"""Backs up the database to the given destination.
		If 'destination' is None, returns an io stream with the backup in it.

		Modified code from Jeremy Brown on: https://stackoverflow.com/questions/3600948/python-subprocess-mysqldump-and-pipes/3601157#3601157
		Special thanks to Cristian Porta for how to run mysqldump without generating password warnings on: https://stackoverflow.com/questions/20751352/suppress-warning-messages-using-mysql-from-within-terminal-but-password-written/20854048#20854048
		Use: https://lyceum-allotments.github.io/2017/03/python-and-pipes-part-5-subprocesses-and-pipes/

		Example Input: backup()
		"""
		global openPlus

		def dump_mySQL():
			nonlocal self, username, password

			if ((username is None) or (password is None)):
				username, password =  re.search("mysql\+mysqlconnector://(.*):(.*)@", self.fileName).groups()
			domain, port, target = re.search("@([\d\.]*):(\d*)/(.*)", self.fileName).groups()

			command = ("C:\\Program Files\\MySQL\\MySQL Server 8.0\\bin\\mysqldump.exe", f"--host={domain}", f"--port={port}", f"--user={username}", f"--password={password}", target)
			with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
				yield f"--{process.communicate()[0].decode()}"

		def dump_sqlite():
			nonlocal self

			with self.makeConnection(raw = True) as connection:
				for item in connection.iterdump():
					yield f"{item}\n"

		##########################################################################

		if (self.isMySQL):
			dumpRoutine = dump_mySQL()
		elif (self.isSQLite):
			dumpRoutine = dump_sqlite()
		else:
			raise NotImplementedError(self.fileName)

		with openPlus(destination, closeIO = self.ensure_default(closeIO, default = lambda: (not isinstance(destination, (io.IOBase, type(None)))))) as fileHandle:
			for item in dumpRoutine:
				fileHandle.write(item)

		if (destination is None):
			return fileHandle

	def restore(self, backupFile):
		"""Restores a backup.

		Example Input: restore()
		"""

		raise NotImplementedError()

	#Alias Functions
	save = backup
	load = restore



def sandbox():
	def test_sqlite_2():
		database_API = build()
		# database_API.openDatabase("test/test_map_example.db", "M:/Versions/dev/Schema/config/schema_config.py", openAlembic = False)
		database_API.openDatabase(None, "M:/Versions/dev/Schema/config/schema_config.py", openAlembic = False)
		database_API.removeRelation()
		database_API.createRelation()
		database_API.resetRelation()

		# print(database_API.getValue({"Maintainance": None}))

		# print()
		# for item in database_API.yieldValueQuery({"Maintainance": None}):
		# 	print(item)

		# print()
		# for relation, attributeList, query in database_API.yieldAllValues(None):
		# 	print([relation, attributeList, query])
		# 	for result in query.all():
		# 		print("   ", result)


		with database_API._yieldValue_getConnection(fromSchema = None) as connection:
			for relation, attributeList, query in database_API.yieldAllValues(None, fromSchema = None, connection = connection):
				print([relation, attributeList, query])
				for result in connection.execute(query).fetchall():
					print("   ", result)

	def test_sqlite():
		database_API = build()
		# database_API.openDatabase(None, "M:/Schema/main/schema_main.py") 
		# database_API.openDatabase("test/test_map_example.db", "M:/Schema/main/schema_main.py", openAlembic = False)
		# database_API.openDatabase("M:/Versions/dev/Settings/data.db", "M:/Schema/main/schema_main.py", openAlembic = False)
		database_API.openDatabase(None, "M:/Versions/dev/Schema/main/schema_main.py", openAlembic = False)
		database_API.removeRelation()
		database_API.createRelation()
		database_API.resetRelation()

		#Add Items
		# database_API.addTuple({"Containers": ({"label": "lorem", "weight_total": 123, "poNumber": 123456, "job": {"label": 1234, "display_text": "12 34"}}, {"label": "ipsum", "job": 1234})})
		# database_API.addTuple({"Containers": {"label": "dolor", "weight_total": 123, "poNumber": 123456}})
		# database_API.addTuple({"Containers": {"label": "sit", "weight_total": 123, "poNumber": 123456, "job": 678, "color": "red"}})
		
		# #Get Items
		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}))
		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, fromSchema = None))
		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, fromSchema = True))
		# quiet(database_API.getValue({"Containers": None}, {"weight_total": 123, "poNumber": 123456}))

		# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}))
		# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, foreignAsDict = True))
		# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, foreignDefault = "label"))
		# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, foreignDefault = "label", foreignAsDict = True))
		# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, foreignDefault = "label", foreignAsDict = True, fromSchema = None))

		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, alias = {"label": "containerNumber"}))

		# quiet(database_API.getValue({"Containers": ("job", "label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, alias = {"job": {"label": "jobNumber"}, "label": "containerNumber"}))
		# quiet(database_API.getValue({"Containers": ("job", "label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, alias = {"job": {"label": "jobNumber"}, "label": "containerNumber"}, fromSchema = None))

		# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, forceRelation = True, forceAttribute = True, forceTuple = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, forceRelation = True, forceAttribute = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, forceRelation = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}))

		# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, fromSchema = None, forceRelation = True, forceAttribute = True, forceTuple = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, fromSchema = None, forceRelation = True, forceAttribute = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, fromSchema = None, forceRelation = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": "dolor"}, fromSchema = None))

		# quiet(database_API.getValue({"Containers": "job"}, {"weight_total": 123, "poNumber": 123456}))
		# quiet(database_API.getValue({"Containers": "job"}, {"job": {"label": 1234}}))
		# quiet(database_API.getValue({"Containers": "job"}, {"job": {"label": 1234}}, alias = {"job": {"label": "jobNumber"}}))

		# quiet(database_API.getValue({"Containers": {"job": "databaseId"}}))
		# quiet(database_API.getValue({"Containers": {"job": ("databaseId", "label")}}))
		# quiet(database_API.getValue({"Containers": {"job": "databaseId"}}, {"job": {"label": 1234}}))
		# quiet(database_API.getValue({"Containers": {"job": "databaseId"}}, onlyOne = True))

		# quiet(database_API.getAllValues("Containers"))
		# quiet(database_API.getAllValues("Containers", fromSchema = None))
		# quiet(database_API.getAllValues("Containers", fromSchema = True))
		# quiet(database_API.getAllValues("Containers", foreignAsDict = True, foreignDefault = ("label", "archived")))
		# quiet(database_API.getAllValues("Containers", foreignDefault = ("label", "archived")))

		#Change Items
		# quiet(database_API.getValue({"Choices_Job": "label"}))
		# database_API.changeTuple({"Containers": {"job": 5678, "location": "A2"}}, {"label": "lorem"})
		# quiet(database_API.getValue({"Choices_Job": "label"}))
		# database_API.changeTuple({"Containers": {"job": 90, "location": "A2"}}, {"label": "lorem"})
		# quiet(database_API.getValue({"Choices_Job": "label"}))
		# database_API.changeTuple({"Containers": {"job": {"label": 5678, "progress": 10}, "location": "A2"}}, {"label": "lorem"})
		# quiet(database_API.getValue({"Choices_Job": ("label", "progress")}))
		# database_API.changeTuple({"Containers": {"job": {"progress": 20}, "location": "A2"}}, {"label": "lorem"})
		# quiet(database_API.getValue({"Choices_Job": ("label", "progress")}))

		# quiet(database_API.getValue({"Choices_Job": "label"}))
		# database_API.changeTuple({"Containers": {"job": 90, "location": "A2"}}, {"label": "amet"}, forceMatch = True)
		# quiet(database_API.getValue({"Choices_Job": "label"}))


		quiet(database_API.getValue({"Containers": "label"}))
		database_API.changeTuple({"Containers": {"job": "09109", "label": "1272"}}, {"label": "1272"}, forceMatch = True)
		database_API.changeTuple({"Containers": {"type": "Bags"}}, {"label": "1272"}, forceMatch = True)
		database_API.changeTuple({"Containers": {"job": "09109", "type": "Bags", "color": "red"}}, {"label": "amet"}, forceMatch = True)
		database_API.changeTuple({"Containers": {"job": "09109", "type": "Bags", "color": "red"}}, {"label": "lorem"}, forceMatch = True)


		database_API.changeTuple({"Containers": {'job': '09109', 'label': '1272', 'poNumber': 'Cust Supplied', 'weight_total': 386.0, 'location': 'AA-5', 'type': 'Bags', 'material': 'TPE SANTOPRENE 123-50', 'color': 'BK Phe303', 'item_type': 'Resin', 'customer': 'Remotec', 'dmte_contact': 'ROGER R', 'dmte_owned': False, 'comments': '( 6 @ 55# EACH ) ( 1 @ 17# ) ( 1 @ 39# ) WEIGHT CONFIRMED 6/5/17 LOT#N/A', 'createdOn': datetime.datetime(2007, 7, 19, 0, 0), 'lastModified': datetime.datetime(2017, 9, 29, 15, 4, 42)}}, {'label': '1272'}, forceMatch = True)
		database_API.changeTuple({"Containers": {'job': 'S4692 - 86592 - 86593', 'label': '1498', 'poNumber': 'Cust Supplied', 'weight_total': 144.0, 'location': 'F-7', 'type': 'BARREL - T', 'material': 'VYDYNE M344-01', 'color': 'Grey', 'item_type': 'Resin', 'customer': 'FAURECIA INTERIORS', 'dmte_contact': 'ALAN M', 'dmte_owned': False, 'comments': 'WEIGHT CONFIRMED 6/5/17', 'createdOn': datetime.datetime(2006, 6, 9, 0, 0), 'lastModified': datetime.datetime(2018, 7, 2, 9, 12, 31)}}, {'label': '1498'}, forceMatch = True)
		quiet(database_API.getValue({"Containers": "label"}))






		
		# #Remove Items
		# database_API.removeTuple({"Containers": {"label": "dolor"}})
		# database_API.removeTuple({"Containers": {"label": "sit"}})
		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"label": "dolor"}))

		# #Etc
		# quiet(database_API.getInfo("Containers", "databaseId"))
		# quiet(database_API.getInfo("Containers", "databaseId", forceAttribute = True))
		# quiet(database_API.getInfo("Containers", ("databaseId", "archived")))
		# quiet(database_API.getInfo("Containers", "job", forceAttribute = True))
		# quiet(database_API.getInfo("Users", forceAttribute = True))

		# quiet(database_API.getForeignSchema("Containers", "job"))


		# #Update Schema
		# database_API.openDatabase("test_map_example.db", "test_map_2")
		# database_API.checkSchema()

	def test_access():
		database_API = build()
		database_API.openDatabase("R:/Material Log - Database/Users/Josh Mayberry/User Database.mdb", openAlembic = False)

		# quiet(database_API.getRelationNames())
		# quiet(database_API.getAllValues("tblMaterialLog", fromSchema = None))

		quiet(database_API.getValue({"tblMaterialLog": "ContainerID"}, isIn = {"ContainerID": ("1272", "1498", "2047")}, fromSchema = None))

	def test_mysql():
		global timeStart

		MyUtilities.logger.getLogger("__main__").quiet()
		database_API = build(fileName = "M:/Versions/dev/Settings/config_mysql.ini", section = "debugging", reset = False, openAlembic = False, settingsKwargs = {"filePath_versionDir": "M:/Versions/dev"})

		answer = database_API.getAllValues("Containers")
		print(len(answer))
		answer = database_API.getAllValues("Containers", fromSchema = None)
		print(len(answer))

		# timeStart = time.perf_counter()
		# answer = database_API.getAllValues('Containers', [], None, **{'valuesAsSet': False, 'attributeFirst': False, 'forceAttribute': True, 'forceTuple': True, 
		#   'filterNone': False, 'nextToCondition': True, 'nextToCondition_None': False, 'notNextTo': collections.defaultdict(list, {'removePending': [1], 'archived': [1]}), 
		#   'alias': {}, 'direction': True, 'foreignAsDict': True, 'foreignDefault': None, 'fromSchema': None})
		# print(f"@__main__, {time.perf_counter() - timeStart:.6f}\n") #0.8802
		# print(len(answer))

		# timeStart = time.perf_counter()
		# answer = database_API.getAllValues('Containers', [], None, **{'valuesAsSet': False, 'attributeFirst': False, 'forceAttribute': True, 'forceTuple': True, 
		#   'filterNone': False, 'nextToCondition': True, 'nextToCondition_None': False, 'notNextTo': collections.defaultdict(list, {'removePending': [1], 'archived': [1]}), 
		#   'alias': {}, 'direction': True, 'foreignAsDict': True, 'foreignDefault': None, 'fromSchema': None})
		# print(f"@__main__, {time.perf_counter() - timeStart:.6f}") #0.8587

		# for item in answer:
		#   print(item.label)
		#   break

		# session.flush()
		# session.close()

		# print(item.label)
		# print(item.job)

		sys.exit()




		database_API = build(fileName = "M:/Versions/dev/Settings/config_mysql.ini", section = "debugging", reset = True, openAlembic = False, settingsKwargs = {"filePath_versionDir": "M:/Versions/dev"})
		# database_API.removeRelation()
		# database_API.createRelation()
		# database_API.resetRelation()

		#Add Items
		database_API.addTuple({"Containers": {"label": 10, "weight_total": 123, "location": 5, "poNumber": 123456}})
		database_API.addTuple({"Containers": {"label": 20, "weight_total": 123, "location": 3, "poNumber": 123456, "job": 678, "color": "red"}})
		database_API.addTuple({"Containers": ({"label": 30, "weight_total": 123, "location": 3, "poNumber": 123456, "job": {"label": 1234, "display_text": "12 34"}}, {"label": 40, "location": 8, "job": 1234})})

		#Get Items
		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}))
		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, fromSchema = None))
		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, fromSchema = True))
		# quiet(database_API.getValue({"Containers": None}, {"weight_total": 123, "poNumber": 123456}))

		# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}))
		# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, foreignAsDict = True))
		# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, foreignDefault = "label"))
		# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, foreignDefault = "label", foreignAsDict = True))
		# quiet(database_API.getValue({"Containers": ("label", "job", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, foreignDefault = "label", foreignAsDict = True, fromSchema = None))
		
		# quiet(database_API.getAttributeNames("Containers", foreignAsDict = None))
		# quiet(database_API.getAttributeNames("Containers", foreignAsDict = False))
		# quiet(database_API.getAttributeNames("Containers", foreignAsDict = True))
		# quiet(database_API.getAllValues("Containers", foreignAsDict = None))
		# quiet(database_API.getAllValues("Containers", foreignAsDict = False))
		# quiet(database_API.getAllValues("Containers", foreignAsDict = True))

		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, alias = {"label": "containerNumber"}))

		# quiet(database_API.getValue({"Containers": ("job", "label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, alias = {"job": {"label": "jobNumber"}, "label": "containerNumber"}))
		# quiet(database_API.getValue({"Containers": ("job", "label", "weight_total")}, {"weight_total": 123, "poNumber": 123456}, alias = {"job": {"label": "jobNumber"}, "label": "containerNumber"}, fromSchema = None))

		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"label": 10}, attributeFirst = True, forceRelation = True, forceAttribute = True, forceTuple = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, attributeFirst = True, forceRelation = True, forceAttribute = True, forceTuple = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, attributeFirst = True, forceRelation = True, forceAttribute = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, attributeFirst = True, forceRelation = True, forceTuple = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, attributeFirst = True, forceRelation = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, attributeFirst = True))
		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, attributeFirst = True))
		# quiet()

		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"label": 10}, forceRelation = True, forceAttribute = True, forceTuple = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, forceRelation = True, forceAttribute = True, forceTuple = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, forceRelation = True, forceAttribute = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, forceRelation = True, forceTuple = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, forceRelation = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}))
		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}))
		# quiet()

		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, forceRelation = True, forceAttribute = True, forceTuple = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, forceRelation = True, forceAttribute = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, forceRelation = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}))

		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, fromSchema = None, forceRelation = True, forceAttribute = True, forceTuple = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, fromSchema = None, forceRelation = True, forceAttribute = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, fromSchema = None, forceRelation = True))
		# quiet(database_API.getValue({"Containers": "label"}, {"label": 10}, fromSchema = None))

		# quiet(database_API.getValue({"Containers": "job"}, {"weight_total": 123, "poNumber": 123456}))
		# quiet(database_API.getValue({"Containers": "job"}, {"job": {"label": 1234}}))
		# quiet(database_API.getValue({"Containers": "job"}, {"job": {"label": 1234}}, alias = {"job": {"label": "jobNumber"}}))

		# quiet(database_API.getValue({"Containers": {"job": "databaseId"}}))
		# quiet(database_API.getValue({"Containers": {"job": ("databaseId", "label")}}))
		# quiet(database_API.getValue({"Containers": {"job": "databaseId"}}, {"job": {"label": 1234}}))
		# quiet(database_API.getValue({"Containers": {"job": "databaseId"}}, onlyOne = True))

		# quiet(database_API.getValue({"Containers": ("label", "location")}, foreignDefault = "label"))
		# quiet(database_API.getValue({"Containers": ("label", "location")}, foreignDefault = "label", orderBy = "location"))
		# quiet(database_API.getValue({"Containers": ("label", "location")}, foreignDefault = "label", orderBy = "location", direction = False))
		# quiet(database_API.getValue({"Containers": ("label", "location")}, foreignDefault = "label", orderBy = ("location", "label")))
		# quiet(database_API.getValue({"Containers": ("label", "location")}, foreignDefault = "label", orderBy = ("location", "label"), direction = False))
		# quiet(database_API.getValue({"Containers": ("label", "location")}, foreignDefault = "label", orderBy = ("location", "label"), direction = {"label": True}))
		# quiet(database_API.getValue({"Containers": ("label", "location")}, foreignDefault = "label", orderBy = ("location", "label"), direction = {"label": False}))

		# Example Input: getValue({"Users": "name"}, orderBy = "age")
		# Example Input: getValue({"Users": ["name", "age"]}, orderBy = "age", limit = 2)
		# Example Input: getValue({"Users": ["name", "age"]}, orderBy = "age", direction = True)

		# Example Input: getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"])
		# Example Input: getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"], direction = [None, False])
		# Example Input: getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"], direction = {"height": False})

		# quiet(database_API.getAllValues("Containers"))
		# quiet(database_API.getAllValues("Containers", fromSchema = None))
		# quiet(database_API.getAllValues("Containers", fromSchema = True))
		# quiet(database_API.getAllValues("Containers", foreignAsDict = True, foreignDefault = ("label", "archived")))
		# quiet(database_API.getAllValues("Containers", foreignDefault = ("label", "archived")))

		# #Change Items
		# quiet(database_API.getValue({"Choices_Job": "label"}))
		# database_API.changeTuple({"Containers": {"job": 5678, "location": "A2"}}, {"label": 30})
		# quiet(database_API.getValue({"Choices_Job": "label"}))
		# database_API.changeTuple({"Containers": {"job": 90, "location": "A2"}}, {"label": 30})
		# quiet(database_API.getValue({"Choices_Job": "label"}))
		# database_API.changeTuple({"Containers": {"job": {"label": 5678, "progress": 10}, "location": "A2"}}, {"label": 30})
		# quiet(database_API.getValue({"Choices_Job": "label"}))
		# database_API.changeTuple({"Containers": {"job": {"progress": 20}, "location": "A2"}}, {"label": 30})
		# quiet(database_API.getValue({"Choices_Job": "label"}))
		# database_API.changeTuple({"Containers": {"job": 90, "location": "A2"}}, {"label": "amet"}, forceMatch = True)
		# quiet(database_API.getValue({"Choices_Job": "label"}))

		# quiet(database_API.getValue({"Containers": "label"}))
		# database_API.changeTuple({"Containers": {"job": "09109", "label": "1272"}}, {"label": "1272"}, forceMatch = True)
		# database_API.changeTuple({"Containers": {"type": "Bags"}}, {"label": "1272"}, forceMatch = True)
		# database_API.changeTuple({"Containers": {"job": "09109", "type": "Bags", "color": "red"}}, {"label": "amet"}, forceMatch = True)
		# database_API.changeTuple({"Containers": {"job": "09109", "type": "Bags", "color": "red"}}, {"label": 30}, forceMatch = True)
		# quiet(database_API.getValue({"Containers": "label"}))

		# #Remove Items
		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"label": 10}))
		# database_API.removeTuple({"Containers": {"label": 10}})
		# database_API.removeTuple({"Containers": {"label": 20}})
		# quiet(database_API.getValue({"Containers": ("label", "weight_total")}, {"label": 10}))

		# #Etc
		# quiet(database_API.getInfo("Containers", "databaseId"))
		# quiet(database_API.getInfo("Containers", "databaseId", forceAttribute = True))
		# quiet(database_API.getInfo("Containers", ("databaseId", "archived")))
		# quiet(database_API.getInfo("Containers", "job", forceAttribute = True))
		# quiet(database_API.getInfo("Users", forceAttribute = True))

		# quiet(database_API.getForeignSchema("Containers", "job"))

		# quiet(database_API.getAttributeDefaults("Containers", "msds"))
		# quiet(database_API.getAttributeDefaults("Containers", "msds", forceAttribute = True))
		# quiet(database_API.getAttributeDefaults("Containers"))
		# quiet(database_API.getAttributeDefaults("Containers", foreignAsDict = True))

		# #Update Schema
		# database_API.openDatabase("test_map_example.db", "test_map_2")
		# database_API.checkSchema()

		#Backup and Restore
		# database_API.backup(username = "backup", password = "KHG7Suh*X+cvb#Y5")

	# test_sqlite()
	test_sqlite_2()
	# test_access()
	# test_mysql()

def main():
	"""The main program controller."""

	sandbox()

if __name__ == '__main__':
	main()
