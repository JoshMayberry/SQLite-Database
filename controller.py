__version__ = "3.4.0"

## TO DO ##
# - Add a foreign key cleanup command; removes unused foreign keys in foreign tables

#Standard Modules
import re
import os
import sys
import abc
import time
import shutil

import io
import enum
import types
import decimal
import subprocess

#Utility Modules
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

#Database Modules
import yaml
import json
import pyodbc
import sqlite3
import configparser

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

import Utilities as MyUtilities

sessionMaker = sqlalchemy.orm.sessionmaker(autoflush = False)

NULL = MyUtilities.common.NULL
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

#Expand JSON
class _JSONEncoder(json.JSONEncoder):
	"""Allows sets to be saved in JSON files.
	Modified code from Raymond Hettinger and simlmx on: https://stackoverflow.com/questions/8230315/how-to-json-serialize-sets/36252257#36252257

	Example Use: 
		json.dumps(["abc", {1, 2, 3}], cls = _JSONEncoder)

		json._default_encoder = _JSONEncoder()
		json.dumps(["abc", {1, 2, 3}])
	"""

	def __init__(self, *, tag_set = None, **kwargs):
		super().__init__(**kwargs)
		self.tag_set = tag_set or "_set"

	def default(self, item):
		if (isinstance(item, collections.Set)):
			return {self.tag_set: list(item)}
		else:
			return super().default(self, item)

class _JSONDecoder(json.JSONDecoder):
	"""Allows sets to be loaded from JSON files.
	Modified code from Raymond Hettinger and simlmx on: https://stackoverflow.com/questions/8230315/how-to-json-serialize-sets/36252257#36252257

	Example Use: 
		json.loads(encoded, cls = _JSONDecoder)

		json._default_decoder = _JSONDecoder()
		json.loads(encoded)
	"""

	def __init__(self, *, object_hook = None, tag_set = None, **kwargs):
		super().__init__(object_hook = object_hook or self.myHook, **kwargs)

		self.tag_set = tag_set or "_set"

	def myHook(self, catalogue):
		if (self.tag_set in catalogue):
			return set(catalogue[self.tag_set])
		return catalogue

json._default_encoder = _JSONEncoder()
json._default_decoder = _JSONDecoder()

sqlalchemy.sql.sqltypes.json._default_encoder = json._default_encoder
sqlalchemy.sql.sqltypes.json._default_decoder = json._default_decoder

#Utility Classes
class Base(MyUtilities.common.EnsureFunctions, MyUtilities.common.CommonFunctions):
	pass

class Base_Database(Base):
	# @classmethod
	# def getSchemaClass(cls, relation):
	# 	"""Returns the schema class for the given relation.
	# 	Special thanks to OrangeTux for how to get schema class from tablename on: https://stackoverflow.com/questions/11668355/sqlalchemy-get-model-from-table-name-this-may-imply-appending-some-function-to/23754464#23754464

	# 	relation (str) - What relation to return the schema class for

	# 	Example Input: getSchemaClass("Customer")
	# 	"""

	# 	# # table = Mapper.metadata.tables.get("Customer")
	# 	# # column = table.columns["name"]
	# 	# return Mapper._decl_class_registry[column.table.name]

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
		"json": sqlalchemy.JSON(),
		
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
			# 	columnKwargs["autoincrement"] = True #Use: https://docs.sqlalchemy.org/en/latest/core/metadata.html#sqlalchemy.schema.Column.params.autoincrement

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

		def formatAttribute(foreignKey, attribute):
			raise NotImplementedError() #Untested
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

				raise NotImplementedError() #Untested
				if (foreignDefault is None):
					catalogue = {catalogue: tuple(attribute for attribute in columnHandle.foreign_keys[catalogue].__mapper__.columns.keys() if (attribute not in exclude))}
				else:
					catalogue = {catalogue: foreignDefault}

			raise NotImplementedError() #Untested
			for foreignKey, attributeList in catalogue.items():
				for attribute in cls.ensure_container(attributeList):
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

	return build_database(*args, **kwargs)

def build_database(*args, **kwargs):
	"""Creates a Database object."""

	return Database(*args, **kwargs)

def build_configuration(*args, **kwargs):
	"""Creates a Configuration object."""

	return Configuration(*args, **kwargs)

def build_json(*args, **kwargs):
	"""Creates a JSON_Aid object."""

	return JSON_Aid(*args, **kwargs)

def build_yaml(*args, **kwargs):
	"""Creates a YAML_Aid object with YAML notation."""

	return YAML_Aid(*args, **kwargs)

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
		# 	print(column.name, column.__class__)
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
				# 	if (nullFirst):
				# 		criteria = criteria.nullsfirst()
				# 	else:
				# 		criteria = criteria.nullslast()

		def yieldOrder():
			for _orderBy in self.ensure_container(orderBy):
				criteria = getBase(_orderBy)

				if (direction is not None):
					criteria = getDirection(criteria, _orderBy)

				yield criteria

		###############################################

		return handle.order_by(*yieldOrder())

	def configureJoin(self, query, relation, schema, table, attribute, fromSchema = False):
		"""Sets up the JOIN portion of the SQL message."""

		def augmentHandle(_handle, attributeList):
			for variable in self.ensure_container(attributeList):
				if (isinstance(variable, dict)):
					_handle = augmentHandle(_handle, variable.keys())
					continue
				if (variable not in schema.foreignKeys):
					continue

				_handle = _handle.join(schema.foreignKeys[variable])
			return _handle

		###############################################

		if (schema is None):
			if (not table.foreign_keys):
				return query
			raise NotImplementedError() #Untested

		elif (fromSchema or (not schema.foreignKeys)):
			return query

		if (fromSchema is None):
			handle = self.metadata.tables[relation]
		else:
			handle = query

		handle = augmentHandle(handle, attribute)
		
		if (fromSchema is None):
			return query.select_from(handle)
		return handle
	
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

		config = build_configuration(default_filePath = filePath, default_section = section)
		return self.openDatabase(**{**config.get({section: ("port", "host", "user", "password", "fileName", "readOnly", "schemaPath", 
			"alembicPath", "openAlembic", "connectionType", "reset", "override_resetBypass")}, fallback = None, default_values = settingsKwargs or {}), **kwargs})

	@wrap_errorCheck()
	def openDatabase(self, fileName = None, schemaPath = None, alembicPath = None, *, applyChanges = True, multiThread = False, connectionType = None, 
		openAlembic = False, readOnly = False, multiProcess = -1, multiProcess_delay = 100, forceExtension = False, reset = None, override_resetBypass = False,
		port = None, host = None, user = None, password = None, echo = False,
		resultError_replacement = None, aliasError_replacement = None):

		"""Opens a database.If it does not exist, then one is created.
		Note: If a database is already opened, then that database will first be closed.
		Use: toLarry Lustig for help with multi-threading on http://stackoverflow.com/questions/22739590/how-to-share-single-sqlite-connection-in-multi-threaded-python-application
		Use: to culix for help with multi-threading on http://stackoverflow.com/questions/6297404/multi-threaded-use-of-sqlalchemy
		
		Use: https://stackoverflow.com/questions/9233912/connecting-sqlalchemy-to-msaccess/13849359#13849359
		Use: https://docs.sqlalchemy.org/en/latest/core/connections.html#registering-new-dialects
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

		@contextlib.contextmanager
		def makeEngine():
			global sessionMaker
			nonlocal self, user, password, host, port, fileName, schemaPath, openAlembic, alembicPath

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
				raise NotImplementedError()
				engineKwargs = {}
				self.fileName = f"mssql+pyodbc://{user}:{password}@{host or localhost}:{port or 3306}/{fileName}?driver=SQL+Server+Native+Client+11.0"

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

			self.loadSchema(schemaPath)

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
		# 	self.resultError_replacement = "!!! SELECT ERROR !!!"

		with makeEngine() as engineKwargs:
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

	def loadSchema(self, schemaPath = None):
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
			schema = self.loadSchema(schemaPath)

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
	def removeTuple(self, myTuple, applyChanges = None,	checkForeign = True, incrementForeign = True, fromSchema = None, **locationKwargs):
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
		Example Input: getAllValues(["Users", "Names"], orderBy = "databaseId")

		database_API.getAllValues("Containers", foreignAsDict = True, foreignDefault = ("label", "archived"))
		database_API.getAllValues("Containers", foreignDefault = ("label", "archived"))
		"""

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

		return self.getValue(myTuple, exclude = excludeList, **kwargs)

	@wrap_errorCheck()
	def getValue(self, myTuple, nextTo = None, orderBy = None, limit = None, direction = None, nullFirst = None, alias = None, 
		returnNull = False, includeDuplicates = True, checkForeign = True, formatValue = None, valuesAsSet = False, count = False,
		maximum = None, minimum = None, average = None, summation = None, variableLength = True, variableLength_default = None,
		forceRelation = False, forceAttribute = False, forceTuple = False, attributeFirst = False,  
		filterForeign = True, filterNone = False, exclude = None, forceMatch = None, fromSchema = False, onlyOne = False,
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
			- If None: Will return all foreign attributes
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

		fromSchema (bool)     - Determines from what source the query is compiled
			- If True: Uses the schema and returns a schema item
			- If False: Uses the schema and returns a dictionary
			- If None: Uses the metadata and returns a dictionary (fastest)

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

		if ((self.schema is None) or (isinstance(self.schema, EmptySchema))):
			fromSchema = None

		if (fromSchema is None):
			contextmanager = self.makeConnection(asTransaction = True)
			def startQuery(relation, attributeList, schema, table):
				nonlocal self, excludeList, alias

				if (schema is not None):
					return sqlalchemy.select(columns = schema.yieldColumn(attributeList, excludeList, alias, foreignAsDict = foreignAsDict, foreignDefault = foreignDefault))
				return sqlalchemy.select(columns = self.yieldColumn_fromTable(table, attributeList, excludeList, alias, foreignAsDict = foreignAsDict, foreignDefault = foreignDefault))
					
			def yieldRow(query):
				nonlocal connection

				catalogue = self.engine.url.query
				if (("charset" in catalogue) and (catalogue["charset"] != "utf8")):
					def yieldResult():
						nonlocal connection, query

						def _yieldResult():
							nonlocal connection, query
							if (onlyOne):
								yield connection.execute(query).first()
								return

							for item in connection.execute(query).fetchall():
								yield item

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
				else:
					def yieldResult():
						nonlocal connection, query
						if (onlyOne):
							yield connection.execute(query).first()
							return

						for item in connection.execute(query).fetchall():
							yield item

				###################################

				for result in yieldResult():
					if (result is None):
						continue
					elif ((not forceAttribute) and (len(result) <= 1)):
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

		elif (fromSchema):
			contextmanager = self.makeSession()
			def startQuery(relation, attributeList, schema, table):
				assert connection, schema is not None

				return connection.query(schema)

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
			contextmanager = self.makeSession()
			def startQuery(relation, attributeList, schema, table):
				nonlocal connection, excludeList, alias
				assert schema is not None

				return connection.query(*schema.yieldColumn(attributeList, excludeList, alias, foreignAsDict = foreignAsDict, foreignDefault = foreignDefault)).select_from(schema)

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
						catalogue = collections.defaultdict(dict)
						for key, value in result._asdict().items():
							foreignMatch = re.search("zfk_(.*)_zfk_(.*)", key)
							if (not foreignMatch):
								catalogue[key] = value
							else:
								catalogue[foreignMatch.group(1)][foreignMatch.group(2)] = value
						yield dict(catalogue)

		container = (tuple, set)[valuesAsSet]

		def getResult(query):
			nonlocal forceTuple, container

			answer = container(yieldRow(query))

			if (not answer):
				return container()
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

		if (not isinstance(exclude, dict)):
			excludeList = self.ensure_container(exclude, convertNone = True)

		assert myTuple
		results_catalogue = {}
		with contextmanager as connection:
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
				query = self.configureJoin(query, relation, schema, table, attributeList, fromSchema = fromSchema)
				query = self.configureOrder(query, relation, schema, table, orderBy = orderBy, direction = direction, nullFirst = nullFirst)
				query = self.configureLocation(query, schema, table, fromSchema = fromSchema, nextTo = nextTo, **locationKwargs)

				if (limit is not None):
					query = query.limit(limit)
				if (not includeDuplicates):
					query = query.distinct()
				if (count and (fromSchema is None)):
					query = query.count()

				results_catalogue[relation] = getResult(query)
		
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

#Monkey Patches
configparser.ConfigParser.optionxform = str

class Configuration(Base):
	"""Used to handle .ini files.

	- Both keys and values can have spaces
	- Multi-line values must have extra lines indented one line deeper
	- Sections and single-line values can be indented with no consequence

	- Keys can be separated from values by either = or :
	- Keys without values can have no separator
	- The separator can have spaces on each side

	- Comments can be done using # or ;

	___________________ EXAMPLE INI FILE ___________________

	[DEFAULT]
	scanDelay = %(delay) %(units)
	units = ms

	[main]
	startup_user = admin

	[AutoSave]
	delay = 1
	units = s

	[GUI]
	delay = 500
	________________________________________________________

	Use: https://pymotw.com/3/configparser/
	Use: https://docs.python.org/3.6/library/configparser.html
	Use: https://martin-thoma.com/configuration-files-in-python/#configparser
	Use: https://www.blog.pythonlibrary.org/2010/01/01/a-brief-configobj-tutorial/
	use: https://www.blog.pythonlibrary.org/2013/10/25/python-101-an-intro-to-configparser/
	"""

	def __init__(self, default_filePath = None, *, default_values = None, default_section = None, forceExists = False, forceCondition = None,
		allowNone = True, interpolation = True, valid_section = None, readOnly = False, defaultFileExtension = None,
		knownTypes = None, knownTypesSection = "knownTypes", knownTypeDefault = None):
		"""

		allowNone (bool) - Determines what happens if a setting does not have a set value
			- If True: Will use None
			- If False: Will raise an error during load()

		interpolation (bool) - Determines what kind of interpolation can be done in get()
			- If True: Extended Interpolation
			- If False: Basic Interpolation
			- If None: No Interpolation

		valid_section (list) - Which sections (excluding DEFAULT) to load
			- If str: Will load only that section
			- If None: Will load all sections
			~ Optionally, variables can be defined in the section given to 'knownTypesSection'

		knownTypesSection (str) - Which section is used to store knownTypes
			- If None: Will not use a section to get knownTypes from

		Example Input: Configuration(self)
		Example Input: Configuration(self, source_directory = "database")
		Example Input: Configuration(self, defaults = {"startup_user": "admin"})
		"""

		self.defaultFileExtension = defaultFileExtension or "ini"
		self.default_section = default_section or "main"
		self.default_filePath = default_filePath or f"settings.{self.defaultFileExtension}"

		if (interpolation):
			interpolation = self.MyExtendedInterpolation()
		elif (interpolation is not None):
			interpolation = configparser.BasicInterpolation()

		self.setReset(converters = self.converters, allow_no_value = allowNone, 
			defaults = default_values or {}, interpolation = interpolation)
		self.reset()

		# self.config.optionxform = str

		self.knownTypeDefault = knownTypeDefault or "_default_"
		self.knownTypesSection = knownTypesSection or None
		self.knownTypes = knownTypes or {}
		self.readOnly = readOnly

		self.set_validSection(valid_section)

		if (default_filePath):
			self.load(forceExists = forceExists, forceCondition = forceCondition)

	def setReset(self, *args, **kwargs):
		self._reset = (args, kwargs)

	def reset(self):
		self.config = configparser.ConfigParser(*self._reset[0], **self._reset[1])

		self.dataType_catalogue = {
			None: self.config.get,
			str: self.config.get, "str": self.config.get,
			int: self.config.getint, "int": self.config.getint,
			float: self.config.getfloat, "float": self.config.getfloat,
			bool: self.config.getboolean, "bool": self.config.getboolean,
			datetime.datetime: self.config.getdatetime, "datetime": self.config.getdatetime,
		}

	def __repr__(self):
		representation = f"{type(self).__name__}(id = {id(self)})"
		return representation

	def __str__(self):
		output = f"{type(self).__name__}()\n-- id: {id(self)}\n"
		return output

	def __enter__(self):
		return self.config

	def __exit__(self, exc_type, exc_value, traceback):
		if (traceback is not None):
			print(exc_type, exc_value)
			return False

	def __getitem__(self, key):
		self.check_invalidSection(key)

		return self.config[key]

	def __setitem__(self, key, value):
		if (self.readOnly):
			raise ReadOnlyError(self)
		self.check_invalidSection(key)

		self.config[key] = value

	def __delitem__(self, key):
		if (self.readOnly):
			raise ReadOnlyError(self)
		self.check_invalidSection(key)

		del self.config[key]

	def __contains__(self, key):
		if (self.check_invalidSection(key, raiseError = False)):
			return False

		return key in self.config

	def keys(self):
		if (self.valid_section is None):
			return tuple(self.config.keys())
		return tuple(section for section in self.config.keys() if (section in self.valid_section))

	def values(self):
		if (self.valid_section is None):
			return tuple(self.config.values())
		return tuple(handle for section, handle in self.config.items() if (section in self.valid_section))

	def items(self):
		if (self.valid_section is None):
			return tuple(self.config.items())
		return tuple((section, handle) for section, handle in self.config.items() if (section in self.valid_section))

	def _asdict(self):
		if (self.valid_section is None):
			return dict(self.config)
		return {key: value for key, value in self.items()}

	def check_invalidSection(self, section, *, raiseError = True, valid_section = NULL):
		if (valid_section is NULL):
			valid_section = self.valid_section
		if ((valid_section is not None) and (section not in valid_section) and (not self.has_section(section, valid_section = None))):
			if (raiseError):
				raise InvalidSectionError(self, section)
			return True

	def _getType(self, variable, section = None, *, dataType = None):
		"""Returns what type to use for the given variable.

		Example Input: _getType("delay")
		"""

		if (dataType is None):
			section = section or self.default_section
			check_section = False
			if ((self.knownTypesSection is not None) and (self.knownTypesSection in self.config.sections())):
				if (self.has_setting(variable, self.knownTypesSection)):
					function = self.dataType_catalogue.get(self.config[self.knownTypesSection][variable], None)
					if (function is not None):
						return function
				check_section = True

			if ((section in self.knownTypes) and (variable in self.knownTypes[section])):
				return self.dataType_catalogue[self.knownTypes[section][variable]]

			default_section = self.config.default_section
			if ((default_section in self.knownTypes) and (variable in self.knownTypes[default_section])):
				return self.dataType_catalogue[self.knownTypes[default_section][variable]]

			if (variable in self.knownTypes):
				return self.dataType_catalogue[self.knownTypes[variable]]


			if (check_section and self.has_setting(self.knownTypeDefault, self.knownTypesSection)):
				function = self.dataType_catalogue.get(self.config[self.knownTypesSection][self.knownTypeDefault], None)
				if (function is not None):
					return function

		return self.dataType_catalogue[dataType]

	def get(self, variable = None, section = None, *, dataType = None, default_values = None, include_defaults = True,
		fallback = configparser._UNSET, raw = False, forceSection = False, forceSetting = False, valid_section = NULL):
		"""Returns a setting from the given section.

		variable (str) - What setting to get
			- If list: Will return a dictionary of all settings in the list
			- If None: Will return a dictionary of all settings in the section

		section (str) - What section to write this setting in
			- If None: Will use the default section

		dataType (type) - What type the data should be in
			- If None: Will read as str, unless the variable is logged in self.knownTypes under 'section' or DEFAULT

		default_values (dict) - Local default values; overrides the global default values temporarily
		include_defaults (bool) - Determines if the default section should be used as a fallback
		raw (bool) - Determines if the value should be returned without applying interpolation

		___________________ BASIC INTERPOLATION ___________________
		Variables are denoted with a single '%', followed by closed paren
			Example: scanDelay = %(delay) %(units)

		To use an escaped %: %%
			Example: units = %%

		___________________ EXTENDED INTERPOLATION ___________________
		Variables are denoted with a '$', followed by braces
			Example: scanDelay = ${delay} ${units}

		Variables from other sections can be used with a ':'
			Example: scanDelay = ${delay} ${general:units}


		Example Input: get()
		Example Input: get("startup_user")
		Example Input: get("scanDelay", section = "AutoSave")
		Example Input: get("scanDelay", section = "AutoSave", dataType = int)
		Example Input: get("startup_window", defaults = {"startup_window": "inventory"})
		
		Example Input: get(("user", "password", "port"), section = "Database_Admin")
		Example Input: get({"Database_Admin": ("user", "password", "port")})
		Example Input: get(include_defaults = False)
		"""

		section = section or self.default_section
		self.check_invalidSection(section, valid_section = valid_section)
		if (not self.has_section(section)):
			section = self.config.default_section

		if (variable is None):
			if (include_defaults):
				variableList = tuple(self[section].keys())
			else:
				variableList = tuple(self.config._sections[section].keys())
			return self.get(variableList, section = section, dataType = dataType, default_values = default_values, fallback = fallback,
				raw = raw, forceSetting = forceSetting, forceSection = forceSection, include_defaults = include_defaults, valid_section = valid_section)

		if (isinstance(variable, dict)):
			answer = {_section: self.get(_variable, section = _section, dataType = dataType, default_values = default_values, fallback = fallback,
				raw = raw, forceSetting = forceSetting, forceSection = forceSection, include_defaults = include_defaults, valid_section = valid_section) for _section, _variable in variable.items()}

			if (forceSection or len(answer) > 1):
				return answer
			elif (not answer):
				return
			return next(iter(answer.values()))

		if (not isinstance(variable, (str, int, float))):
			answer = {_variable: self.get(_variable, section = section, dataType = dataType, default_values = default_values, fallback = fallback,
				raw = raw, forceSetting = forceSetting, forceSection = forceSection, include_defaults = include_defaults, valid_section = valid_section) for _variable in variable}

			if (forceSetting or len(answer) > 1):
				return answer
			elif (not answer):
				return
			return next(iter(answer.values()))

		function = self._getType(variable, section, dataType = dataType)

		try:
			return function(section, variable, vars = default_values or {}, raw = raw, fallback = fallback)

		except (configparser.InterpolationDepthError, configparser.InterpolationMissingOptionError) as error:
			print("@Configuration.get", error)
			return function(section, variable, vars = default_values or {}, raw = True, fallback = fallback)

	def set(self, variable, value = None, section = None, *, valid_section = NULL):
		"""Adds a setting to the given section.

		variable (str) - What setting to get
			- If list: Wil set each variable in the list to 'value'
			- If dict: Will ignore 'value' and set each key to it's given value

		section (str) - What section to write this setting in
			- If None: Will use the default section

		Example Input: set("startup_user", "admin")
		Example Input: set("scanDelay", 1000, section = "AutoSave")

		Example Input: set({"startup_user": "admin"})
		Example Input: set({"AutoSave": {"scanDelay": 1000}})
		"""
		if (self.readOnly):
			raise ReadOnlyError(self)
		self.check_invalidSection(section, valid_section = valid_section)

		if (isinstance(variable, dict)):
			for _variable, _value in variable.items():
				if (isinstance(_value, dict)):
					for __variable, __value in _value.items():
						self.set(__variable, value = __value, section = _variable, valid_section = valid_section)
				else:
					self.set(_variable, value = _value, section = section, valid_section = valid_section)
			return

		if (not isinstance(variable, (str, int, float))):
			for _variable in variable:
				self.set(_variable, value = value, section = section, valid_section = valid_section)
			return

		section = section or self.default_section

		if (not self.config.has_section(section)):
			self.config.add_section(section)

		if (value is None):
			self.config.set(section, variable, "")
		else:
			self.config.set(section, variable, f"{value}")

	def load(self, filePath = None, *, valid_section = NULL, forceExists = False, forceCondition = None):
		"""Loads the configuration file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		valid_section (list) - Updates self.valid_section if not NULL

		Example Input: load()
		Example Input: load("database/settings_user.ini")
		Example Input: load("database/settings_user.ini", valid_section = ("testing",))
		"""
		global openPlus

		if (valid_section is not NULL):
			self.set_validSection(valid_section)

		filePath = filePath or self.default_filePath
		if (not os.path.exists(filePath)):
			if (not forceExists):
				raise FileExistsError(filePath)

			if (isinstance(forceExists, dict)):
				self.set(forceExists, valid_section = None)

			with openPlus(filePath) as config_file:
				self.config.write(config_file)

		self.config.read(filePath)

		if (forceCondition is not None):
			for variable, value in forceCondition.items():
				var_mustBe = self.tryInterpolation(variable, value)
				var_isActually = self.get(variable)
				if (var_mustBe != var_isActually):
					print(f"Forced conditions not met: {var_mustBe} is not {var_isActually}. Replacing config file with 'forceMatch")
					os.remove(filePath)
					self.reset()

					return self.load(filePath = filePath, valid_section = valid_section, forceExists = forceExists, forceCondition = None)

	def tryInterpolation(self, variable, value, section = None):
		return self.config._interpolation.before_get(self.config, section or "DEFAULT", variable, value, self.config.defaults())

	def save(self, filePath = None, override_readOnly = False, **kwargs):
		"""Saves changes to config file.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		Example Input: save()
		Example Input: save("database/settings_user.ini")
		"""
		global openPlus

		if ((not override_readOnly) and self.readOnly):
			raise ReadOnlyError(self)
		
		filePath = filePath or self.default_filePath
		with openPlus(filePath or self.default_filePath, **kwargs) as config_file:
			self.config.write(config_file)

	def has_section(self, section = None, *, valid_section = NULL):
		"""Returns True if the section exists in the config file, otherwise returns False.

		section (str) - What section to write this setting in
			- If None: Will use the default section

		Example Input: has_section()
		Example Input: has_section(section = "AutoSave")
		"""

		section = section or self.default_section

		if (section == self.config.default_section):
			return True

		return section in self.getSections(valid_section = valid_section, skip_knownTypes = False)

	def has_setting(self, variable, section = None, *, checkDefault = False, valid_section = NULL):
		"""Returns True if the setting exists in given section of the config file, otherwise returns False.

		section (str) - What section to write this setting in
			- If None: Will use the default section

		checkDefault (bool) - Determines if the section DEFAULT is taken into account

		Example Input: has_setting("startup_user")
		Example Input: has_setting("scanDelay", section = "AutoSave")

		Example Input: has_setting("startup_user", checkDefault = True)
		"""

		section = section or self.default_section
		self.check_invalidSection(section, valid_section = valid_section)

		if (checkDefault):
			return self.config.has_option(section, variable)
		else:
			return variable in self.config._sections.get(section, ())

	def remove_section(self, section = None, *, valid_section = NULL):
		"""Removes a section.

		section (str) - What section to write this setting in
			- If None: Will remove all sections

		Example Input: remove_section("startup_user")
		Example Input: remove_section("scanDelay", section = "AutoSave")
		"""

		if (self.readOnly):
			raise ReadOnlyError(self)

		if (section is None):
			for section in self.getSections():
				self.config.remove_section(section)
			return

		self.check_invalidSection(section, valid_section = valid_section)
		self.config.remove_section(section or self.default_section)

	def remove_setting(self, variable, section = None, *, valid_section = NULL):
		"""Removes a setting from the given section.

		section (str) - What section to write this setting in
			- If None: Will use the default section

		Example Input: remove_setting("startup_user")
		Example Input: remove_setting("scanDelay", section = "AutoSave")
		"""

		if (self.readOnly):
			raise ReadOnlyError(self)
		self.check_invalidSection(section, valid_section = valid_section)

		self.config.remove_option(section or self.default_section, variable)

	def getSections(self, *, valid_section = NULL, skip_knownTypes = True):
		"""Returns a list of existing sections.

		Example Input: getSections()
		"""

		def yieldSection():
			nonlocal self, valid_section, skip_knownTypes

			for section in self.config.sections():
				if (self.check_invalidSection(section, raiseError = False, valid_section = valid_section)):
					continue

				if (skip_knownTypes and (section == self.knownTypesSection)):
					continue

				yield section

		###################################

		return tuple(yieldSection())

	def getDefaults(self):
		"""Returns the defaults that will be used if a setting does not exist.

		section (str) - What section to write this setting in
			- If None: Will use the default section

		Example Input: getDefaults()
		"""

		return self.config.defaults()

	def extraBool(self, value, state):
		"""Adds a value as an extra possible bool.
		Default cases (case-insensative): yes/no, on/off, true/false, 1/0

		Example Input: extraBool("sure", True)
		Example Input: extraBool("nope", False)
		"""

		self.ConfigParser.BOOLEAN_STATES.update({value: state})

	def set_validSection(self, valid_section = None):
		if (valid_section is None):
			self.valid_section = None
		else:
			self.valid_section = (self.config.default_section, *((self.knownTypesSection,) if (self.knownTypesSection is not None) else ()), *self.ensure_container(valid_section))

	#Converters
	@staticmethod
	def convert_datetime(value):
		return datetime.datetime.strptime(s, "%Y/%m/%d %H:%M:%S.%f")

	converters = {
		"datetime": convert_datetime,
	}

	#Interpolators
	class MyExtendedInterpolation(configparser.ExtendedInterpolation):
		"""Modified ExtendedInterpolation from configparser.py"""

		def _interpolate_some(self, parser, option, accum, rest, section, mapping, depth):
			"""The default ExtendedInterpolation does not account for default values in nested interpolations.
			ie: The following does not work when get() is given the kwargs 'section = "debugging"' and 'vars = {"filePath_versionDir": "C:/"}').
				[admin]
				alembicPath = ${filePath_versionDir}/Schema/main/

				[debugging]
				alembicPath = ${admin:alembicPath}
			"""

			rawval = parser.get(section, option, raw = True, fallback = rest)
			if (depth > configparser.MAX_INTERPOLATION_DEPTH):
				raise InterpolationDepthError(option, section, rawval)
			while rest:
				p = rest.find("$")
				if p < 0:
					accum.append(rest)
					return
				if p > 0:
					accum.append(rest[:p])
					rest = rest[p:]
				# p is no longer used
				c = rest[1:2]
				if c == "$":
					accum.append("$")
					rest = rest[2:]
				elif c == "{":
					m = self._KEYCRE.match(rest)
					if m is None:
						raise InterpolationSyntaxError(option, section,
							"bad interpolation variable reference %r" % rest)
					path = m.group(1).split(':')
					rest = rest[m.end():]
					sect = section
					opt = option
					try:
						if (len(path) is 1):
							opt = parser.optionxform(path[0])
							v = mapping[opt]

						elif (len(path) is 2):
							sect = path[0]
							opt = parser.optionxform(path[1])
							v = parser.get(sect, opt, raw = True)

						else:
							raise configparser.InterpolationSyntaxError(option, section, "More than one ':' found: %r" % (rest,))

					except (KeyError, NoSectionError, NoOptionError):
						raise configparser.InterpolationMissingOptionError(option, section, rawval, ":".join(path)) from None
					
					if ("$" in v):
						self._interpolate_some(parser, opt, accum, v, sect, {**mapping, **dict(parser.items(sect, raw = True))}, depth + 1) # <- This was the only change
					else:
						accum.append(v)
				else:
					raise InterpolationSyntaxError(
						option, section,
						"'$' must be followed by '$' or '{', "
						"found: %r" % (rest,))

class Config_Base(Base, metaclass = abc.ABCMeta):
	"""Utility API for json and yaml scripts."""

	def __init__(self, default_filePath = None, *, defaultFileExtension = None, override = None, overrideIsSave = None, forceExists = False):
		"""
		Example Input: JSON_Aid()
		Example Input: YAML_Aid()
		"""

		self.defaultFileExtension = defaultFileExtension
		self.default_filePath = default_filePath or f"settings.{self.defaultFileExtension}"
		self.filePath_lastLoad = self.default_filePath

		self.dirty = None
		self.contents = {}
		self.contents_override = {}

		self.setOverride(override = override, overrideIsSave = overrideIsSave)

		if (default_filePath):
			self.load(default_filePath, forceExists = forceExists)

	def __repr__(self):
		representation = f"{type(self).__name__}(id = {id(self)})"
		return representation

	def __str__(self):
		output = f"{type(self).__name__}()\n-- id: {id(self)}\n"
		return output

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		if (traceback is not None):
			print(exc_type, exc_value)
			return False

	def __getitem__(self, key):
		return self.contents[key]

	def __setitem__(self, key, value):
		self.contents[key] = value

	def __delitem__(self, key):
		del self.contents[key]

	def __contains__(self, key):
		return key in self.contents

	def read(self, default = None):
		for section, catalogue in self.contents.items():
			for setting, value in catalogue.items():
				if (isinstance(value, dict)):
					yield section, setting, value.get("value", default)
				else:
					yield section, setting, value

	def setOverride(self, override = None, overrideIsSave = None):
		"""Applies override settings for advanced save and load managment.

		override (str) - A .json file that will override sections in the given filePath
			- If None: Will ignore all override conditions
			- If dict: Will use the given dictionary instead of a .json file for saving and loading; can be empty
			- If str: Will use the .json file located there (it will be created if neccissary)

		overrideIsSave (bool) - Determines what happens when no file path is given to save()
			- If True: Saves any changes to 'override', unless that value exists in 'default_filePath' in which case it will be removed from 'override'
			- If False: Saves any changes to 'override'
			- If None: Saves any changes to 'default_filePath'
			~ Removed sections or settings are ignored

		Example Input: setOverride()
		Example Input: setOverride(override = "")
		Example Input: setOverride(override = "settings_user_override.json")
		Example Input: setOverride(override = {"Lorem": {"ipsum": 1}})
		Example Input: setOverride(override = {}, overrideIsSave = True)
		Example Input: setOverride(override = {}, overrideIsSave = False)
		"""

		if (override is None):
			self.override = None
			self.overrideIsSave = None
			self.contents_override = {}
			self.default_filePath_override = None
			return

		self.overrideIsSave = overrideIsSave
		if (isinstance(override, dict)):
			self.override = False
			self.contents_override = override
			self.default_filePath_override = None
			return

		self.override = True
		self.default_filePath_override = override or f"settings_override.{self.defaultFileExtension}"
		self.contents_override = {}

	@contextlib.contextmanager
	def _load(self, filePath = None, removeDirty = True, applyOverride = True, forceExists = False):
		"""Loads the json file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		Example Input: load()
		Example Input: load("database/settings_user.json")
		"""

		if (isinstance(filePath, dict)):
			self.contents = {**filePath}
			self.filePath_lastLoad = None
			yield None
		else:
			filePath = filePath or self.default_filePath
			self.filePath_lastLoad = filePath

			if (not os.path.exists(filePath)):
				if (not forceExists):
					raise FileExistsError(filePath)

				if (isinstance(forceExists, dict)):
					self.set(forceExists, valid_section = None)

				self.save(filePath = filePath, applyOverride = False, removeDirty = False)

			with open(filePath) as fileHandle:
				yield fileHandle
		
		if (removeDirty):
			self.dirty = False

		if (applyOverride):
			self.load_override()

	@contextlib.contextmanager
	def _load_override(self, filePath = None):
		"""Loads the override json file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		Example Input: load_override()
		Example Input: load_override("database/settings_user_override.json")
		"""

		if (self.override is None):
			yield None
			return

		filePath = filePath or self.default_filePath_override
		if (isinstance(filePath, dict)):
			self.contents_override = {**filePath}
			yield None
		else:
			if (self.override and (os.path.exists(filePath))):
				with open(filePath) as fileHandle:
					yield fileHandle
			else:
				yield None

		MyUtilities.common.nestedUpdate(self.contents, self.contents_override, preserveNone = False)

	@contextlib.contextmanager
	def _save(self, filePath = None, ifDirty = True, removeDirty = True, 
		applyOverride = True, overrideKwargs = None, **kwargs):
		"""Saves changes to json file.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		ifDirty (bool) - Determines if the file should be saved only if changes have been made

		Example Input: save()
		Example Input: save("database/settings_user.json")
		"""
		global openPlus

		filePath = filePath or self.default_filePath
		if (ifDirty and (not self.dirty) and (os.path.exists(filePath))):
			yield None
			return

		try:
			if (applyOverride and self.save_override(**(overrideKwargs or {}))):
				yield None
				return

			with openPlus(filePath, **kwargs) as fileHandle:
				yield fileHandle

		except Exception as error:
			raise error

		finally:
			if (removeDirty):
				self.dirty = False

	@contextlib.contextmanager
	def _save_override(self, filePath = None, *, base = None):
		"""Saves changes to json file.
		Note: Only looks at changes and additions, not removals.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		Example Input: save_override()
		Example Input: save_override("database/settings_user_override.json")
		"""
		global openPlus

		def formatCatalogue(catalogue):
			if (not isinstance(catalogue, dict)):
				return {"value": catalogue}
			return catalogue

		#######################################

		if (self.overrideIsSave is None):
			yield None
			return

		base = base or {}
		changes = collections.defaultdict(lambda: collections.defaultdict(dict))
		for section, new in self.contents.items():
			old = base.get(section, {})

			for setting, new_catalogue in new.items():
				new_catalogue = formatCatalogue(new_catalogue)
				old_catalogue = formatCatalogue(old.get(setting, {}))

				for option, new_value in new_catalogue.items():
					old_value = old_catalogue.get(option, NULL)

					if ((new_value or (option != "comment")) and ((old_value is NULL) or (new_value != old_value))):
						changes[section][setting][option] = new_value

		self.contents_override.clear()
		MyUtilities.common.nestedUpdate(self.contents_override, changes) #Filter out defaultdict

		if (self.override):
			with openPlus(filePath or self.default_filePath_override) as fileHandle:
				yield fileHandle
		else:
			yield None

	def _ensure(self, section, variable = None, value = None, *, comment = None, 
		forceAttribute = False, makeDirty = True):
		"""Makes sure that the given variable exists in the given section.

		section (str) - Which section to ensure 'variable' for
			- If list: Will ensure all given sections have 'variable'
			- If dict: Will ignore 'variable' and 'value'

		variable (str) - Which variable to ensure
			- If list: Will ensure all given variables
			- If dict: Will ignore 'value' and use the key as 'variable' and the value as 'value'

		value (any) - The default value that 'variable' should have if it does not exist
		comment (str) - Optional comment string for 'variable'

		Example Input: ensure("containers", "label", value = False)
		Example Input: ensure("containers", {"label": False})
		Example Input: ensure({"containers": {"label": False}})
		"""

		for sectionCatalogue in self.ensure_container(section):
			for _section, variableCatalogue in self.ensure_dict(sectionCatalogue, variable).items():
				if (not self.has_section(_section)):
					self.contents[_section] = {}

				for _variableCatalogue in self.ensure_container(variableCatalogue):
					for _variable, _value in self.ensure_dict(_variableCatalogue, value).items():

						if (not self.has_setting(_variable, _section)):
							if (makeDirty):
								self.dirty = True
							if (comment):
								yield _section, _variable, {"value": _value, "comment": comment}
							elif (forceAttribute):
								yield _section, _variable, {"value": _value}
							else:
								yield _section, _variable, {_value}

	@abc.abstractmethod
	def load(self, *args, **kwargs):
		pass

	@abc.abstractmethod
	def load_override(self, *args, **kwargs):
		pass

	@abc.abstractmethod
	def save(self, *args, **kwargs):
		pass

	@abc.abstractmethod
	def save_override(self, *args, **kwargs):
		pass

	@abc.abstractmethod
	def ensure(self, *args, **kwargs):
		pass

	def get(self, section, setting, default = None):
		"""Returns the value of the given setting in the given section.

		Example Input: get("lorem", "ipsum")
		"""

		value = self.contents[section][setting]
		if (isinstance(value, dict)):
			return value.get("value", default)
		return value

	def set(self, contents = None, update = True, makeDirty = True):
		"""Adds a section to the internal contents.

		contents (dict) - What to add
		update (bool) - Determines what happens if a key already exists for the given 'contents'
			- If True: Will update nested dictionaries
			- If False: Will replace nested dictionaries
			- If None: Will replace entire self.contents

		Example Input: set()
		Example Input: set({"lorem": 1})
		Example Input: set({"ipsum": {"dolor": 4}})
		Example Input: set({"ipsum": {"dolor": 5}}, update = False)
		Example Input: set({"lorem": 1, "ipsum": {"dolor": 2, "sit": 3}}, update = None)
		"""

		contents = contents or {}

		assert isinstance(contents, dict)

		if (update is None):
			self.contents = contents
		elif (not update):
			self.contents.update(contents)
		else:
			MyUtilities.common.nestedUpdate(self.contents, contents)

		if (makeDirty):
			self.dirty = True

	def apply(self, handle, section, include = None, exclude = None, handleTypes = None):
		"""Places default values into the supplied handle.

		___________________ REQUIRED FORMAT ___________________

		self.contents = {
			section (str): {
				variable (str): value (any),

				variable (str): {
					"value": value (any),
					"comment": docstring (str), #optional
				},
			},
		}
		_______________________________________________________

		section (str) - Which section to apply variables for
			- If list: Will apply all given sections

		handle (object) - What to apply the given sections to
			- If list: will apply to all

		include (str) - What variable is allowed to be applied
			- If list: Will apply all variables in the section

		handleTypes (list) - Place the type for 'section' here

		Example Input: apply(test_1, "GUI_Manager", handleTypes = Test)
		Example Input: apply(test_2, ("DatabaseInfo", "Users"), handleTypes = (Test,))
		Example Input: apply(self, {"FrameSettings": self.label}, handleTypes = (self.__class__,))
		Example Input: apply(self, {"FrameSettings": {self.label: "title"}}, handleTypes = (self.__class__,))
		Example Input: apply((test1, test_2), {"Settings": ("debugging_default", "debugging_enabled")}, handleTypes = Test)
		"""

		def yieldApplied():
			nonlocal self, handle, section, handleTypes

			for _handle in self.ensure_container(handle, elementTypes = handleTypes):
				for _section in self.ensure_container(section):
					for item in setValue(_handle, _section, self.contents):
						yield item

		def setValue(_handle, _section, catalogue):
			nonlocal self, include, exclude

			if (isinstance(_section, dict)):
				for key, value in _section.items():
					for item in setValue(_handle, value, catalogue.get(key)):
						yield item
				return 
			
			if (_section not in catalogue):
				print("@apply", f"{_section} does not exist in catalogue\n  -- keys: {tuple(catalogue.keys())}")
				raise NotImplementedError()
				return

			for variable, _catalogue in catalogue[_section].items():
				if (include and (variable not in include)):
					continue
				if (exclude and (variable in exclude)):
					continue

				if ((not isinstance(_catalogue, dict) or ("value" not in _catalogue))):
					setattr(_handle, variable, _catalogue)
				else:
					setattr(_handle, variable, _catalogue["value"])

				yield variable

		#######################################################
		
		include = self.ensure_container(include)
		exclude = self.ensure_container(exclude)

		return tuple(yieldApplied())

	def has_section(self, section = None):
		"""Returns True if the section exists in the config file, otherwise returns False.

		section (str) - What section to write this setting in
			- If None: Will use the default section

		Example Input: has_section()
		Example Input: has_section(section = "AutoSave")
		"""

		return (section or self.default_section) in self.contents

	def has_setting(self, variable, section = None):
		"""Returns True if the setting exists in given section of the config file, otherwise returns False.

		section (str) - What section to write this setting in
			- If None: Will use the default section

		Example Input: has_setting("startup_user")
		Example Input: has_setting("scanDelay", section = "AutoSave")
		"""

		return variable in self.contents.get(section or self.default_section, {})

	def is_dirty(self):
		"""Returns True if changes have been made that are not yet saved, otherwise returns False.

		Example Input: is_dirty()
		"""

		return self.dirty

	def getSections(self, variable = None):
		"""Returns a list of existing sections.

		variable (str) - What variable must exist in the section
			- If None: Will not search for sections by variable

		Example Input: getSections()
		Example Input: getSections(variable = "debugging_default")
		"""

		if (variable is None):
			return tuple(self.contents.keys())

		return tuple(key for key, catalogue in self.contents.items() if (variable in catalogue.keys()))

	def getSettings(self, section = None, valuesAsSet = False):
		"""Returns a list of existing settings for the given section.

		section (str) - What section to write this setting in
			- If list: Will use all in list
			- If None: Will use all existing sections

		Example Input: getSettings()
		Example Input: getSettings("AutoSave")
		"""

		if (valuesAsSet):
			container = set
		else:
			container = tuple

		return container(variable for key in (self.ensure_container(section) or self.contents.keys()) for variable in self.contents[key].keys())

class JSON_Aid(Config_Base):
	"""Utility API for json scripts.

	Use: https://martin-thoma.com/configuration-files-in-python/#json
	"""

	def __init__(self, default_filePath = None, **kwargs):
		"""
		Example Input: JSON_Aid()
		"""

		super().__init__(default_filePath = default_filePath or "settings.json", defaultFileExtension = "json", **kwargs)

	def load(self, *args, **kwargs):
		"""Loads the json file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		Example Input: load()
		Example Input: load("database/settings_user.json")
		"""

		with self._load(*args, **kwargs) as fileHandle:
			if (fileHandle is not None):
				self.contents = json.load(fileHandle) or {}
			
		return self.contents

	def load_override(self, *args, **kwargs):
		"""Loads the override json file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		Example Input: load_override()
		Example Input: load_override("database/settings_user_override.json")
		"""

		with self._load_override(*args, **kwargs) as fileHandle:
			if (fileHandle is not None):
				self.contents_override = json.load(fileHandle) or {}

	def save(self, *args, **kwargs):
		"""Saves changes to json file.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		ifDirty (bool) - Determines if the file should be saved only if changes have been made

		Example Input: save()
		Example Input: save("database/settings_user.json")
		"""

		with self._save(*args, **kwargs) as fileHandle:
			if (fileHandle is not None):
				json.dump(self.contents or None, fileHandle, indent = "\t")

	def save_override(self, *args, base = None, **kwargs):
		"""Saves changes to json file.
		Note: Only looks at changes and additions, not removals.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		Example Input: save_override()
		Example Input: save_override("database/settings_user_override.json")
		"""

		if (base is None):
			with open(self.filePath_lastLoad) as fileHandle:
				base = json.load(fileHandle) or {}

		with self._save_override(*args, base = base, **kwargs) as fileHandle:
			if (fileHandle is not None):
				json.dump(self.contents_override or None, fileHandle, indent = "\t")

		return True

	def ensure(self, *args, saveToOverride = None, **kwargs):
		"""Makes sure that the given variable exists in the given section.

		Example Input: ensure("containers", "label", value = False)
		Example Input: ensure("containers", "label", value = False, saveToOverride = True)
		Example Input: ensure("containers", "label", value = False, saveToOverride = False)
		"""
		global openPlus

		if (saveToOverride is None):
			for section, variable, value in self._ensure(*args, **kwargs):
				self.contents[section][variable] = value
			return True

		filePath = (self.filePath_lastLoad, self.default_filePath_override)[saveToOverride]
		with open(filePath) as fileHandle:
			base = json.load(fileHandle) or {}

		changed = False
		for section, variable, value in self._ensure(*args, **kwargs):
			self.contents[section][variable] = value
			changed = True

			if (section not in base):
				base[section] = {}
			base[section][variable] = value

		if (changed):
			with openPlus(filePath) as fileHandle:
				json.dump(base or None, fileHandle, indent = "\t")

		return True

class YAML_Aid(Config_Base):
	"""Utility API for yaml scripts.

	Use: https://pyyaml.org/wiki/PyYAMLDocumentation
	Use: https://martin-thoma.com/configuration-files-in-python/#yaml
	"""

	def __init__(self, default_filePath = None, **kwargs):
		"""
		Example Input: YAML_Aid()
		"""

		super().__init__(default_filePath = default_filePath or "settings.yaml", defaultFileExtension = "yaml", **kwargs)

	def load(self, *args, **kwargs):
		"""Loads the yaml file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		Example Input: load()
		Example Input: load("database/settings_user.yaml")
		"""

		with self._load(*args, **kwargs) as fileHandle:
			if (fileHandle is not None):
				self.contents = yaml.load(fileHandle) or {}
			
		return self.contents

	def load_override(self, *args, **kwargs):
		"""Loads the override yaml file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		Example Input: load_override()
		Example Input: load_override("database/settings_user_override.yaml")
		"""

		with self._load_override(*args, **kwargs) as fileHandle:
			if (fileHandle is not None):
				self.contents_override = yaml.load(fileHandle) or {}

	def save(self, *args, explicit_start = True, explicit_end = True, width = None, indent = 4, 
		default_style = None, default_flow_style = None, canonical = None, line_break = None, 
		encoding = None, allow_unicode = None, version = None, tags = None, **kwargs):
		"""Saves changes to yaml file.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		ifDirty (bool) - Determines if the file should be saved only if changes have been made

		Example Input: save()
		Example Input: save("database/settings_user.yaml")
		"""

		with self._save(*args, overrideKwargs = {"explicit_start": explicit_start, "width": width, "indent": indent, 
			"canonical": canonical, "default_flow_style": default_flow_style}, **kwargs) as fileHandle:

			if (fileHandle is not None):
				yaml.dump(self.contents or None, fileHandle, explicit_start = explicit_start, explicit_end = explicit_end, width = width, 
					default_style = default_style, default_flow_style = default_flow_style, canonical = canonical, indent = indent, 
					encoding = encoding, allow_unicode = allow_unicode, version = version, tags = tags, line_break = line_break)

	def save_override(self, *args, base = None, explicit_start = True, explicit_end = True, width = None, indent = 4, 
		default_style = None, default_flow_style = None, canonical = None, line_break = None, 
		encoding = None, allow_unicode = None, version = None, tags = None, **kwargs):
		"""Saves changes to yaml file.
		Note: Only looks at changes and additions, not removals.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		Example Input: save_override()
		Example Input: save_override("database/settings_user_override.yaml")
		"""

		if (base is None):
			with open(self.filePath_lastLoad) as fileHandle:
				base = yaml.load(fileHandle) or {}

		with self._save_override(*args, base = base, **kwargs) as fileHandle:
			if (fileHandle is not None):
				yaml.dump(self.contents_override or None, fileHandle, explicit_start = explicit_start, explicit_end = explicit_end, width = width, 
					default_style = default_style, default_flow_style = default_flow_style, canonical = canonical, indent = indent, 
					encoding = encoding, allow_unicode = allow_unicode, version = version, tags = tags, line_break = line_break)

		return True

	def ensure(self, *args, saveToOverride = None, explicit_start = True, explicit_end = True, width = None, indent = 4, 
		default_style = None, default_flow_style = None, canonical = None, line_break = None, 
		encoding = None, allow_unicode = None, version = None, tags = None, **kwargs):
		"""Makes sure that the given variable exists in the given section.

		Example Input: ensure("containers", "label", value = False)
		Example Input: ensure("containers", "label", value = False, saveToOverride = True)
		Example Input: ensure("containers", "label", value = False, saveToOverride = False)
		"""

		global openPlus

		if (saveToOverride is None):
			for section, variable, value in self._ensure(*args, **kwargs):
				self.contents[section][variable] = value
			return True

		filePath = (self.filePath_lastLoad, self.default_filePath_override)[saveToOverride]
		with open(filePath) as fileHandle:
			base = yaml.load(fileHandle) or {}

		changed = False
		for section, variable, value in self._ensure(*args, **kwargs):
			self.contents[section][variable] = value
			changed = True

			if (section not in base):
				base[section] = {}
			base[section][variable] = value

		if (changed):
			with openPlus(filePath) as fileHandle:
				yaml.dump(base or None, fileHandle, explicit_start = explicit_start, explicit_end = explicit_end, width = width, 
					default_style = default_style, default_flow_style = default_flow_style, canonical = canonical, indent = indent, 
					encoding = encoding, allow_unicode = allow_unicode, version = version, tags = tags, line_break = line_break)

		return True

def quiet(*args):
	pass
	print(*args)

def sandbox():
	def test_yaml():
		class Test(): pass
		test_1 = Test()
		test_2 = Test()

		# yaml_api = build_yaml(default_filePath = "test/settings.yaml", forceExists = True)
		# print(yaml_api)

		# yaml_api = build_yaml(default_filePath = "M:/Versions/dev/Settings/default_user.yaml", override = {"GUI_Manager": {"startup_window": "settings"}})
		yaml_api = build_yaml(default_filePath = "M:/Versions/dev/Settings/default_user.yaml", override = "M:/Versions/dev/Settings/temp_default_user.yaml", overrideIsSave = True)
		quiet(yaml_api.apply(test_1, "GUI_Manager", handleTypes = Test))
		quiet(yaml_api.apply(test_2, ("Barcodes", "Users"), handleTypes = (Test,)))
		quiet(yaml_api.apply((test_1, test_2), "Settings", ("debugging_default", "debugging_enabled"), handleTypes = (Test,)))

		quiet(vars(test_1))
		quiet(vars(test_2))
		quiet(yaml_api.getSettings())
		quiet(yaml_api.getSettings("Users"))
		quiet(yaml_api.getSections(variable = "debugging_default"))

		yaml_api.set({"GUI_Manager": {"startup_window": "main"}})
		yaml_api.save()

	def test_json():
		class Test(): pass
		test_1 = Test()
		test_2 = Test()

		# json_API = build_json(default_filePath = "M:/Versions/dev/Settings/default_user.json", override = {"GUI_Manager": {"startup_window": "settings"}})
		json_API = build_json(default_filePath = "M:/Versions/dev/Settings/default_user.json", override = "M:/Versions/dev/Settings/temp_default_user.json", overrideIsSave = True)
		json_API.apply(test_1, "GUI_Manager", handleTypes = Test)
		json_API.apply(test_2, ("Barcodes", "Users"), handleTypes = (Test,))
		json_API.apply((test_1, test_2), "Settings", ("debugging_default", "debugging_enabled"), handleTypes = (Test,))

		quiet(vars(test_1))
		quiet(vars(test_2))
		quiet(json_API.getSettings("Users"))
		quiet(json_API.getSections(variable = "debugging_default"))

		json_API.set({"GUI_Manager": {"startup_window": "main"}})
		json_API.save()

	def test_config():
		# config_API = build_configuration()
		# # config_API.set("startup_user", "admin")
		# # config_API.save("test/test.ini")

		# config_API.load("test/test.ini")
		# # quiet(config_API.get("startup_user"))
		
		# with config_API as config:
		# 	for section, sectionHandle in config.items():
		# 		for key, value in sectionHandle.items():
		# 			quiet(section, key, value)

		user = os.environ.get('username')
		config_API = build_configuration("M:/Versions/dev/Settings/settings_user.ini", valid_section = user, default_section = user, knownTypes = {"x": bool, "y": bool})

		value = config_API.get("startup_user")
		print(value, type(value))

		# value = config_API.get("x")
		# print(value, type(value))

		# value = config_API.get("y")
		# print(value, type(value))

	def test_sqlite():
		database_API = build()
		# database_API.openDatabase(None, "M:/Schema/main/schema_main.py") 
		# database_API.openDatabase("test/test_map_example.db", "M:/Schema/main/schema_main.py", openAlembic = False)
		# database_API.openDatabase("M:/Versions/dev/Settings/data.db", "M:/Schema/main/schema_main.py", openAlembic = False)
		database_API.openDatabase(None, "M:/Schema/main/schema_main.py", openAlembic = False)
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
		database_API.backup(username = "backup", password = "KHG7Suh*X+cvb#Y5")

	# test_json()
	# test_yaml()
	# test_config()
	# test_sqlite()
	# test_access()
	test_mysql()

def main():
	"""The main program controller."""

	sandbox()

if __name__ == '__main__':
	main()
