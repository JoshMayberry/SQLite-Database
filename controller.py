__version__ = "3.4.0"

## TO DO ##
# - Add a foreign key cleanup command; removes unused foreign keys in foreign tables

import re
import sys
import time
import types
import pyodbc
import sqlite3
import warnings
import traceback
import functools
import itertools
import cachetools
import collections

#For multi-threading
# import sqlalchemy
import threading
from forks.pypubsub.src.pubsub import pub as pubsub_pub #Use my own fork

#Required Modules
##py -m pip install
	# sqlite3
	# pyodbc

threadLock = threading.RLock()

#Caching
# cacheLock = threading.RLock()
indexCache = cachetools.LFUCache(maxsize = 10)
valueCache = cachetools.LFUCache(maxsize = 1000)
definitionCache = cachetools.LFUCache(maxsize = 30)
valueCache_sub_1 = cachetools.LFUCache(maxsize = 1000)
valueCache_sub_2 = cachetools.LFUCache(maxsize = 1000)
connectionTypeCache = cachetools.LFUCache(maxsize = 2)

def hash_isSQLite(self):
	return cachetools.keys.hashkey(1)

def hash_isAccess(self):
	return cachetools.keys.hashkey(2)

def hash_formatValue(self, *args, formatter = None, **kwargs):
	if (not isinstance(formatter, dict)):
		return cachetools.keys.hashkey(*args, formatter = formatter, **kwargs)
	return cachetools.keys.hashkey(*args, formatter = tuple(sorted(formatter.items())), **kwargs)

def hash_noSelf(self, *args, **kwargs):
	return cachetools.keys.hashkey(*args, **kwargs)

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
		for filename, lineno, name, line in traceback.extract_stack(stack):
			code.append('File: "%s", line %d, in %s' % (filename,
														lineno, name))
			if line:
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
def wrap_connectionCheck(makeDialog = True, fileName = "error_log.log"):
	def decorator(function):
		@functools.wraps(function)
		def wrapper(self, *args, **kwargs):
			"""Makes sure that there is a connection before continuing.

			Example Usage: @wrap_connectionCheck()
			"""

			return function(self, *args, **kwargs)

			# if (self.connection is not None):
			# 	answer = function(self, *args, **kwargs)
			# else:
			# 	warnings.warn("No database is open", Warning, stacklevel = 2)
			# 	answer = None

			return answer
		return wrapper
	return decorator

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
				
				print(f"Previous Command: {self.previousCommand}")
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

class Database():
	"""Used to create and interact with a database.
	To expand the functionality of this API, see: "https://www.sqlite.org/lang_select.html"
	"""

	def __init__(self, fileName = None, keepOpen = True, *args, **kwargs):
		"""Defines internal variables.
		A better way to handle multi-threading is here: http://code.activestate.com/recipes/526618/

		fileName (str) - If not None: Opens the provided database automatically
		keepOpen (bool) - Determines if the database is kept open or not
			- If True: The database will remain open until closed by the user or the program terminates
			- If False: The database will be opened only when it needs to be accessed, and closed afterwards

		Example Input: Database()
		Example Input: Database("emaildb")
		"""

		#Internal variables
		self.cursor = None
		self.waiting = False
		self.fileName = None
		self.connection = None
		self.connectionSetup = []
		self.keepOpen = keepOpen
		self.defaultCommit = None
		self.connectionType = None
		self.defaultFileExtension = ".db"
		self.previousCommand = (None, None) #(command (str), valueList (tuple))
		self.resultError_replacement = None
		self.aliasError_replacement = None

		self.foreignKeys_catalogue = {} #{relation (str): {attribute (str): [foreign_relation (str), foreign_attribute (str)]}}
		self.forigenKeys_used = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(int)))) 
								#{foreign_relation (str):       {foreign_attribute (str):       {index (int):                   {relation (str): count (int)}}}}

		self.sqlTypeCatalogue = {
			str: "TEXT", "TEXT": "TEXT",
			float: "REAL", "REAL": "REAL",
			int: "INTEGER", "INTEGER": "INTEGER", 
		}

		#Initialization functions
		if ((self.keepOpen) and (fileName is not None)):
			self.openDatabase(fileName = fileName, *args, **kwargs)

	def __repr__(self):
		representation = f"{type(self).__name__}(id = {id(self)})"
		return representation

	def __str__(self):
		output = f"{type(self).__name__}()\n-- id: {id(self)}\n"
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
	def setCacheSize_index(self, size = None):
		"""Sets the max size for the index cache.

		size (int) - How large the cache will be
			- If None: Will set the cache to it's default size

		Example Input: setCacheSize_index()
		Example Input: setCacheSize_index(15)
		"""
		global indexCache

		if (size is None):
			size = 10

		indexCache._Cache__maxsize = size

	def setCacheSize_value(self, size = None):
		"""Sets the max size for the value cache.

		size (int) - How large the cache will be
			- If None: Will set the cache to it's default size

		Example Input: setCacheSize_value()
		Example Input: setCacheSize_value(15)
		"""
		global valueCache

		if (size is None):
			size = 1000

		valueCache._Cache__maxsize = size

	def removeCache_value(self, *args, checkForeign = None, _raiseError = True, **kwargs):
		"""Removes the cached value for the value cache with the given args and kwargs.

		Example Input: removeCache_value()
		"""
		global valueCache, hash_formatValue

		if (_raiseError):
			extraArgs = ()
		else:
			extraArgs = (None,)

		if (checkForeign is None):
			valueCache.pop(hash_formatValue(self, *args, checkForeign = True, **kwargs), *extraArgs)
			valueCache.pop(hash_formatValue(self, *args, checkForeign = False, **kwargs), *extraArgs)
		else:
			valueCache.pop(hash_formatValue(self, *args, checkForeign = checkForeign, **kwargs), *extraArgs)

	def clearCache_value(self):
		"""Empties the value cache.

		Example Input: clearCache_value()
		"""
		global valueCache

		valueCache.clear()

	def clearCache_index(self):
		"""Empties the index cache.

		Example Input: clearCache_index()
		"""
		global indexCache

		indexCache.clear()

	#Event Functions
	def setFunction_cmd_startWaiting(self, function):
		"""Will trigger the given function when waiting for a database to unlock begins.

		function (function) - What function to run

		Example Input: setFunction_cmd_startWaiting(myFunction)
		"""

		pubsub_pub.subscribe(function, "event_cmd_startWaiting")

	#Utility Functions
	def ensure_set(self, item, convertNone = False):
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

	def ensure_list(self, item, convertNone = False):
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

	def ensure_container(self, item, evaluateGenerator = True, convertNone = False):
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

	@cachetools.cached(connectionTypeCache, key = hash_isSQLite)#, lock = cacheLock)
	def isSQLite(self):
		return self.connectionType == "sqlite3"
	
	@cachetools.cached(connectionTypeCache, key = hash_isAccess)#, lock = cacheLock)
	def isAccess(self):
		return self.connectionType == "access"

	@cachetools.cached(indexCache)#, lock = cacheLock)
	def getPrimaryKey(self, relation):
		"""Returns the primary key to use for the given relation.

		Example Input: getPrimaryKey()
		"""

		return next(iter(self.getSchema(relation)["primary"].keys()), None)

	def yieldKey(self, subject, catalogue = None, *, exclude = None):
		"""A convenience function for iterating over subject.

		subject (any) - Determines what is yielded
			- If None: Yields each key in 'catalogue'
			- If list: Yields a key in 'catalogue' for each item in 'subject'
			- If other: Yields 'subject' if it is a key in 'catalogue'

		exclude (set) - A list of keys to not yield from catalogue

		Example Input: yieldKey(relation, self.forigenKeys_used, exclude = exclude)
		Example Input: yieldKey(attribute, self.forigenKeys_used[_relation])
		"""
		assert catalogue is not None
		exclude = self.ensure_container(exclude, convertNone = True)

		if (subject is None):
			for key in catalogue:
				if (key in exclude):
					continue
				yield key
			return

		if (isinstance(subject, (collections.Iterable)) and (not isinstance(subject, str))):
			for key in subject:
				for item in self.yieldKey(key, catalogue = catalogue, exclude = exclude):
					yield item
			return

		if ((subject not in exclude) and (subject in catalogue)):
			yield subject

	def getDriverList(self, key = None):
		"""Returns a list of all drivers that can be accessed.

		Example Input: getDriverList()
		"""

		if (key is not None):
			return tuple(item for item in pyodbc.drivers() if (key in item))
		return tuple(pyodbc.drivers())

	@wrap_errorCheck()
	def getFileName(self, includePath = True):
		"""Returns the name of the database.

		Example Input: getFileName()
		Example Input: getFileName(includePath = False)
		"""

		return self.fileName

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getRelationNames(self, exclude = None, include = None, excludeFunction = None, includeFunction = None):
		"""Returns the names of all relations (tables) in the database.

		exclude (list) - A list of which relations to excude from the returned result

		Example Input: getRelationNames()
		Example Input: getRelationNames(["Users", "Names"])
		Example Input: getRelationNames(include = ["_Job"], includeFunction = lambda relation, myList: any(relation.startswith(item) for item in myList)
		"""

		if (self.isSQLite()):
			exclude = self.ensure_set(exclude, convertNone = True)
			exclude.add("sqlite_sequence")

			relationList = self.executeCommand("SELECT name FROM sqlite_master WHERE type = 'table'", transpose = True, filterTuple = True, exclude = exclude, excludeFunction = excludeFunction, include = include, includeFunction = includeFunction)
		else:
			exclude = self.ensure_set(exclude, convertNone = True)
			include = self.ensure_set(include, convertNone = True)
			
			if (excludeFunction is None):
				excludeFunction = lambda relation, myList: relation not in myList
			if (includeFunction is None):
				includeFunction = lambda relation, myList: relation in myList

			relationList = [table_info.table_name for tableType in ("TABLE", "ALIAS", "SYNONYM") for table_info in self.cursor.tables(tableType = tableType)]
			# relationList = [table_info.table_name for tableType in ("TABLE", "VIEW", "ALIAS", "SYNONYM") for table_info in self.cursor.tables(tableType = tableType)]
			# relationList = [table_info.table_name for tableType in ("TABLE", "VIEW", "SYSTEM TABLE", "ALIAS", "SYNONYM") for table_info in self.cursor.tables(tableType = tableType)]
			relationList = [relation for relation in relationList if (((not exclude) or excludeFunction(relation, exclude)) and ((not includ) or includeFunction(relation, include)))]


		return relationList

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getAttributeNames(self, relation, exclude = None):
		"""Returns the names of all attributes (columns) in the given relation (table).

		relation (str) - The name of the relation
		exclude (list) - A list of which attributes to excude from the returned result

		Example Input: getAttributeNames("Users")
		Example Input: getAttributeNames("Users", exclude = ["age", "height"])
		"""

		exclude = self.ensure_container(exclude)

		if (self.isSQLite()):
			table_info = self.executeCommand("PRAGMA table_info([{}])".format(relation))
			attributeList = tuple(attribute[1] for attribute in table_info if attribute[1] not in exclude)
		else:
			attributeList = tuple(item[3] for item in self.cursor.columns(table = relation) if (item[3] not in exclude))

		return attributeList

	@wrap_errorCheck()
	@wrap_connectionCheck()
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

		defaults = self.getSchema(relation)["default"]
		exclude = self.ensure_list(exclude)

		if (attribute is not None):
			attribute = self.ensure_container(attribute)
			for item in defaults.keys():
				if (item not in attribute):
					exclude.append(item)

		for item in exclude:
			defaults.pop(f"{item}", None)
		return defaults

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getTupleCount(self, relation):
		"""Returns the number of tuples (rows) in a relation (table).

		Example Input: getTupleCount("Users")
		"""

		count = self.executeCommand("SELECT COUNT(*) from [{}]".format(relation), filterTuple = True)[0]
		return count

	def getSchema(self, relation):
		"""Returns the SQL Schema for the given relation (table).
		Use: https://groups.google.com/forum/#!topic/comp.lang.python/l1UaZomqMSk

		Example Input: getSchema("Users")
		"""

		def search(raw_sql, state):
			"""Searches through the raw sql for the variable with the given type.

			raw_sql (str) - The sql string to look through
			state (str)   - What state to look for.

			Example Input: search(raw_sql, "UNIQUE")
			"""

			return re.findall(f"""(?:,|\()\s*?`?\[?((?#
				)(?<=\[)(?:[^,`\[\]]+)|(?#      variable with brackets
				)(?<!\[)(?:[^,`\[\]\s]+))\]?(?# variable without brackets
				)[^,\[\]]*?{state}""", raw_sql)

		################################################################
	
		#Setup
		data = collections.defaultdict(lambda: collections.defaultdict(bool))

		if (self.isSQLite()):
			#Get Schema Info
			raw_sql = self.executeCommand("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{}'".format(relation), filterTuple = True)
			if (not raw_sql):
				errorMessage = f"There is no relation {relation} in the database for {self.__repr__()}"
				raise KeyError(errorMessage)
			raw_sql = raw_sql[0]

			unique_list = search(raw_sql, "UNIQUE")
			unsigned_list = search(raw_sql, "UNSIGNED")
			autoIncrement_list = search(raw_sql, "AUTOINCREMENT")
			table_info = self.executeCommand("PRAGMA table_info([{}])".format(relation))
			foreign_key_list = self.executeCommand("PRAGMA foreign_key_list([{}])".format(relation))

			#Keys
			for item in table_info:
				columnName, dataType, null, default, primaryKey = item[1:6]

				data["schema"][columnName] = dataType
				data["notNull"][columnName] = bool(null)
				data["primary"][columnName] = bool(primaryKey)
				data["default"][columnName] = default

				if (columnName in autoIncrement_list):
					data["autoIncrement"][columnName] = True

				if (columnName in unsigned_list):
					data["unsigned"][columnName] = True

				if (columnName in unique_list):
					data["unique"][columnName] = True

			#Foreign
			for item in foreign_key_list:
				foreign_relation, attribute, foreign_attribute = item[2], item[3], item[4]

				data["foreign"][attribute] = {foreign_relation: foreign_attribute}
		else:
			for item in self.cursor.statistics(table = relation):
				non_unique    = item[3]
				primary       = item[5] == "PrimaryKey"
				# column        = item[7]
				attributeName = item[8]
				# rows          = item[10]
				# pages         = item[11]

				if (not non_unique):
					data["unique"][attributeName] = True
				if (primary):
					data["primary"][attributeName] = True

			for item in self.cursor.columns(table = relation):
				attributeName = item[3]
				# typeName      = item[5]
				canBeNull     = item[9]
				# columnSize    = item[6]
				default       = item[12]
				# includesNull  = item[17]

				if (not canBeNull):
					data["notNull"][attributeName] = True
				data["default"][attributeName] = True

			if (not self.isAccess()):
				primary_key_list = self.cursor.primaryKeys(table = relation)
				foreign_key_list = self.cursor.foreignKey(relation)
				jkjkhkhjkkj
			
		return data

	@cachetools.cached(definitionCache, key = hash_noSelf)#, lock = cacheLock)
	def getDefinition(self, attribute, dataType = str, default = None, notNull = None, primary = None, autoIncrement = None, unsigned = None, unique = None, autoPrimary = False):
		"""Returns the formatted column definition."""

		command = "[{}] {}".format(attribute, self.sqlTypeCatalogue[dataType])

		if (default is not None):
			command += " DEFAULT ({})".format(default)

		if ((notNull) or (autoPrimary)):
				command += " NOT NULL"

		if ((primary) or (autoPrimary)):
				command += " PRIMARY KEY"

		if (autoIncrement and (self.isSQLite())):
				command += " AUTOINCREMENT"

		# if ((unsigned) or (autoPrimary)):
		# 		command += " UNSIGNED"

		if ((unique) or (autoPrimary)):
				command += " UNIQUE"

		return command

	def formatForigen(self, foreign = None, schema = None, notNull = None, 
		primary = None, autoIncrement = None, unsigned = None, unique = None, default = None):
		"""Formats a forigen key
		More information at: http://www.sqlitetutorial.net/sqlite-foreign-key/
		"""

		unique = unique or {}
		foreign = foreign or {}
		notNull = notNull or {}
		primary = primary or {}
		default = default or {}
		unsigned = unsigned or {}
		autoIncrement = autoIncrement or {}

		schema = self.ensure_container(schema)

		#Parse foreign keys
		foreignInfo = []
		for attribute, foreign_dict in foreign.items():
			#Skip items that will be added in as foreign keys
			for schema_item in schema:
				if ((schema_item is not None) and (attribute in schema_item)):
					break
			else:
				if (type(foreign_dict) == dict):
					foreign_dataType = int
				else:
					foreign_dataType = foreign_dict

				foreignInfo.append(self.getDefinition(attribute, dataType = foreign_dataType, default = default.get(attribute, None),
					notNull = notNull.get(attribute, None), primary = primary.get(attribute, None), autoIncrement = autoIncrement.get(attribute, None),
					unsigned = unsigned.get(attribute, None), unique = unique.get(attribute, None), autoPrimary = False))

		#Link foreign keys
		for attribute, foreign_dict in foreign.items():
			#Account for non-foreign keys
			if (type(foreign_dict) == dict):
				foreign_relation, foreign_attribute = list(foreign_dict.items())[0]
				foreignInfo.append("FOREIGN KEY ([{}]) REFERENCES [{}]([{}])".format(attribute, foreign_relation, foreign_attribute))

		return ', '.join(foreignInfo)

	def formatSchema(self, schema = None, applyChanges = None, autoPrimary = False, notNull = None, 
		primary = None, autoIncrement = None, unsigned = None, unique = None, default = None, foreign = None):
		"""A sub-function that adds adds a column definition and foreign keys.
		Use: http://www.sqlitetutorial.net/sqlite-foreign-key/
		"""
		unique = unique or {}
		notNull = notNull or {}
		primary = primary or {}
		default = default or {}
		unsigned = unsigned or {}
		autoIncrement = autoIncrement or {}

		schema = self.ensure_container(schema)

		schemaFormatted = ""

		#Add given attributes
		definitionList = []
		for schema_item in schema:
			definitionList.append(", ".join(self.getDefinition(attribute, dataType = dataType, default = default.get(attribute, None),
					notNull = notNull.get(attribute, None), primary = primary.get(attribute, None), autoIncrement = autoIncrement.get(attribute, None),
					unsigned = unsigned.get(attribute, None), unique = unique.get(attribute, None), autoPrimary = autoPrimary)
					for attribute, dataType in schema_item.items()))
		schemaFormatted += ", ".join(item for item in definitionList if item)

		#Add foreign keys
		foreignList = []
		for foreign_item in self.ensure_container(foreign):
			if (foreign_item is not None):
				foreignList.append(self.formatForigen(foreign_item, schema = schema, notNull = notNull, primary = primary, 
					autoIncrement = autoIncrement, unsigned = unsigned, unique = unique, default = default))
		schemaFormatted = ", ".join(item for item in [schemaFormatted] + foreignList if item)
		return schemaFormatted

	def updateInternalforeignSchemas(self):
		"""Only remembers data from schema (1) is wanted and (2) that is tied to a foreign key.
		Special Thanks to Davoud Taghawi-Nejad for how to get a list of table names on https://stackoverflow.com/questions/305378/list-of-tables-db-schema-dump-etc-using-the-python-sqlite3-api
		"""

		self.foreignKeys_catalogue.clear()
		if (self.isAccess()):
			#ODBC Driver does not support Foreign Keys for MS Access
			return 

		#Get the foreign schema for each relation
		for relation in self.getRelationNames():
			if (self.isSQLite()):
				foreign_schemaList = self.executeCommand("PRAGMA foreign_key_list([{}])".format(relation))
			else:
				foreign_key_list = self.cursor.foreignKeys(table = relation)
				lkiuiulil

			#Do not check for relations with no foreign keys in their schema
			if (foreign_schemaList):
				if (relation not in self.foreignKeys_catalogue):
					self.foreignKeys_catalogue[relation] = {}

				#Connect for each foreign key in the schema
				for foreign_schema in foreign_schemaList:
					#Parse schema
					foreign_relation = foreign_schema[2]
					foreign_attribute = foreign_schema[4]
					attribute_connection = foreign_schema[3]

					#Remember this key to speed up future look ups
					self.foreignKeys_catalogue[relation][attribute_connection] = [foreign_relation, foreign_attribute]

	def insertForeign(self, relation, attribute, value, foreignNone = False):
		"""Adds a foreign key to the table if needed."""

		if (value in [None, NULL]):
			if ((not foreignNone) or (isinstance(foreignNone, dict) and foreignNone.get(attribute, False))):
				return value

		if ((relation not in self.foreignKeys_catalogue) or (attribute not in self.foreignKeys_catalogue[relation])):
			return value
		foreign_relation, foreign_attribute = self.foreignKeys_catalogue[relation][attribute]

		self.addTuple({foreign_relation: {foreign_attribute: value}}, unique = None, incrementForeign = False)
		foreign_id = self.getValue({foreign_relation: [self.getPrimaryKey(foreign_relation)]}, {foreign_attribute: value}, returnNull = False)
		return foreign_id

	def changeForeign(self, relation, attribute, newValue, currentValues, updateForeign = None):
		"""Adds a foreign key to the table if needed.

		updateForeign (bool) - Determines what happens to existing foreign keys
			- If True: Foreign keys will be updated to the new value
			- If False: A new foreign tuple will be inserted
			- If None: A foreign key will be updated to the new value if only one item is linked to it, otherwise a new foreign tuple will be inserted
		"""

		if ((relation not in self.foreignKeys_catalogue) or (attribute not in self.foreignKeys_catalogue[relation])):
			#The attribute has no foreign link
			return newValue
		if (newValue in [None, NULL]):
			#The value is not pointing to anything
			return newValue

		foreign_relation, foreign_attribute = self.foreignKeys_catalogue[relation][attribute]
		index = self.getPrimaryKey(foreign_relation)
		try:
			command = f"SELECT {self.getPrimaryKey(foreign_relation)} FROM [{foreign_relation}] WHERE ({foreign_attribute} = ?)"
			targetId = self.executeCommand(command, (newValue,), filterTuple = True)
			if (targetId):
				#Use existing key
				return targetId[0]

			#Should I create a new key or modify the current one?
			if (updateForeign):
				#I will modify one of the keys, regardless of who is using it
				self.changeTuple({foreign_relation: foreign_attribute}, {index: currentValues[0]}, newValue, forceMatch = True)
				return currentValues[0]

			elif (updateForeign is None):
				usedKeys = self.getForeignUses(foreign_relation, foreign_attribute, currentValues, excludeUser = relation, filterIndex = False, updateSchema = False)
				for _index in currentValues:
					if ((_index is None) or (usedKeys.get(_index))):
						continue
					#I found a key I can change, so I will use that one
					self.changeTuple({foreign_relation: foreign_attribute}, {index: _index}, newValue)
					return _index

			#I could not find a key I can change, so I will make a new one to use
			self.addTuple({foreign_relation: {foreign_attribute: newValue}}, unique = None)
			return self.executeCommand(command, (newValue,), filterTuple = True)[0]
		
		except Exception as error:
			raise error

		finally:
			for value in currentValues:
				self.removeCache_value(value, index, foreign_relation, _raiseError = False)

	# @cachetools.cached(attributeCache, key = hash_formatAttribute)#, lock = cacheLock)
	def formatAttribute(self, attribute, row = None, alias = None):
		"""Returns a formatted attribute.

		Example Input: formatValue(attribute, alias)
		"""

		if (alias is None):
			return attribute

		if (isinstance(alias, dict)):
			return alias.get(attribute, attribute)

		if (isinstance(alias, str)):
			return alias

		if (isinstance(alias, (types.GeneratorType, range))):
			try:
				return next(alias)
			except StopIteration as error:
				print("@formatAttribute", error)
				return self.aliasError_replacement

		try:
			return alias[row]
		except Exception as error:
			print("@formatAttribute", error)
			return self.aliasError_replacement

	@cachetools.cached(valueCache, key = hash_formatValue)#, lock = cacheLock)
	def formatValue(self, *args, formatter = None, **kwargs):
		"""Returns a formatted value.

		Example Input: formatValue(value, attribute, relation)
		"""

		@cachetools.cached(valueCache_sub_1)#, lock = cacheLock)
		def _eveluateValue(value, attribute, relation, returnNull = False, checkForeign = True):
			if (value is None):
				return (None, NULL)[returnNull]

			if ((not checkForeign) or (relation not in self.foreignKeys_catalogue) or (attribute not in self.foreignKeys_catalogue[relation])):
				return value

			foreign_relation, foreign_attribute = self.foreignKeys_catalogue[relation][attribute]
			command = f"SELECT [{foreign_attribute}] from [{foreign_relation}] WHERE ({self.getPrimaryKey(foreign_relation)} = ?)"
			subResults = self.executeCommand(command, (value,), filterTuple = True)
			if (not subResults):
				return value

			assert len(subResults) is 1
			return subResults[0]

		@cachetools.cached(valueCache_sub_2, key = hash_formatValue)#, lock = cacheLock)
		def _formatValue(value, _, attribute, relation, *args, formatter = None, **kwargs):
			if (formatter):
				if (isinstance(formatter, dict)):
					if (attribute in formatter):
						return formatter[attribute](value, attribute, relation)
					return value
				else:
					return formatter(value, attribute, relation)
			else:
				return value

		#################################################

		return _formatValue(_eveluateValue(*args, **kwargs), *args, **kwargs, formatter = formatter)

	def configureModifier(self, relation, includeDuplicates = False,
		maximum = None, minimum = None, average = None, summation = None):
		"""Sets up modifier sections of the SQL message.

		Example Input: configureModifier(relation, maximum = True)
		Example Input: configureModifier(relation, maximum = "label")
		"""

		if (not any((maximum is not None, minimum is not None, average is not None, summation is not None))):
			return " {}", None

		command = " {}"
		valueList = []
		locationList = []

		if (maximum):
			if (isinstance(maximum, bool)):
				command = " MAX({})"
			else:
				locationList.append(f"{maximum} = (SELECT MAX({maximum}) FROM {relation})")

		if (minimum):
			if (isinstance(minimum, bool)):
				command = " MIN({})"
			else:
				locationList.append(f"{minimum} = (SELECT MIN({minimum}) FROM {relation})")

		if (average):
			if (isinstance(average, bool)):
				command = f" AVG({['DISTINCT ', ''][includeDuplicates]}{{}})"
			else:
				pass
				# locationList.append(f"{average} = (SELECT AVG({['DISTINCT ', ''][includeDuplicates]}{average}) FROM {relation})")

		if (summation):
			if (isinstance(summation, bool)):
				command = f" SUM({['DISTINCT ', ''][includeDuplicates]}{{}})"
			else:
				pass
				# locationList.append(f"{summation} = (SELECT SUM({['DISTINCT ', ''][includeDuplicates]}{summation}) FROM {relation})")

		return command, (locationList, valueList)

	def configureOrder(self, relation, orderBy = None, direction = None):
		"""Sets up the ORDER BY portion of the SQL message.

		Example Input: configureOrder("Users", orderBy = "name")
		"""

		orderBy	= self.ensure_container(orderBy)

		if (not isinstance(direction, dict)):
			direction = {item: direction for item in orderBy}

		orderList = []
		for item in orderBy:
			condition = direction.get(item, None)
			orderList.append(f"[{relation}].[{item}]{ {None: '', True: ' ASC', False: ' DESC'}[direction.get(item, None)] }")

		return ', '.join(orderList)

	def configureLocation(self, relation, nextToCondition = True, nextToCondition_None = None, checkForeign = True, forceMatch = True, 
		nextTo = None, notNextTo = None, like = None, notLike = None, isNull = None, isNotNull = None, extra = None,
		isIn = None, isNotIn = None, isAny = None, isNotAny = None, isAll = None, isNotAll = None, 
		isBetween = None, isNotBetween = None, exists = None, notExists = None, exclude = None,
		greaterThan = None, lessThan = None, greaterThanOrEqualTo = None, lessThanOrEqualTo = None):
		"""Sets up the location portion of the SQL message.

		Example Input: configureLocation("Users", like = {"name": "or"})
		Example Input: configureLocation("Users", like = {"name": ["or", "em"]})

		Example Input: configureLocation("Users", isIn = {"name": "Lorem"})
		Example Input: configureLocation("Users", isIn = {"name": ["Lorem", "Ipsum"]})
		"""

		nextTo = nextTo or {}
		notNextTo = notNextTo or {}
		like = like or {}
		notLike = notLike or {}
		isNull = isNull or {}
		isNotNull = isNotNull or {}
		isIn = isIn or {}
		isNotIn = isNotIn or {}
		isAny = isAny or {}
		isNotAny = isNotAny or {}
		isAll = isAll or {}
		isNotAll = isNotAll or {}
		isBetween = isBetween or {}
		isNotBetween = isNotBetween or {}
		exists = exists or {}
		notExists = notExists or {}
		greaterThan = greaterThan or {}
		lessThan = lessThan or {}
		greaterThanOrEqualTo = greaterThanOrEqualTo or {}
		lessThanOrEqualTo = lessThanOrEqualTo or {}

		if (nextToCondition_None is None):
			nextToCondition_None = nextToCondition

		if (exclude):
			notNextTo = {**notNextTo, **{key: True for key in exclude}}

		if (extra):
			valueList = extra[1]
			locationList = extra[0]
		else:
			valueList = []
			locationList = []

		def yieldValue(catalogue, attribute, returnList = False, onlyNone = False):
			nonlocal relation, checkForeign, forceMatch

			if (onlyNone):
				if (None not in catalogue):
					return
				valueList = self.ensure_container(catalogue[None], convertNone = True)
			else:
				if (attribute not in catalogue):
					return
				valueList = self.ensure_container(catalogue[attribute], convertNone = True)

			if (not checkForeign):
				if (returnList):
					yield valueList
					return

				for value in valueList:
					yield value
				return

			if ((relation not in self.foreignKeys_catalogue) or (attribute not in self.foreignKeys_catalogue[relation])):
				if (returnList):
					yield valueList
					return

				for value in valueList:
					yield value
				return
				
			foreign_relation, foreign_attribute = self.foreignKeys_catalogue[relation][attribute]
			index = self.getPrimaryKey(foreign_relation)
			for value in valueList:
				command = f"SELECT {index} FROM [{foreign_relation}] WHERE [{foreign_relation}].[{foreign_attribute}] is ?"
				result = self.executeCommand(command, (value,), filterTuple = True)

				if (result):
					yield result[0]
					continue

				if (not forceMatch):
					errorMessage = f"There is no foreign key {foreign_attribute} with the value {value} in the relation {foreign_relation} for configureLocation()"
					raise KeyError(errorMessage)

				self.addTuple({foreign_relation: {foreign_attribute: value}}, unique = None, incrementForeign = False)
				yield self.executeCommand(command, (value,), filterTuple = True)[0]

		def compileLocations(attributeList, onlyNone = False):
			nonlocal relation, locationList, valueList

			for attribute in attributeList:
				for key, catalogue in {"IN": isIn, "NOT IN": isNotIn}.items():
					for value in yieldValue(catalogue, attribute, returnList = True, onlyNone = onlyNone):
						locationList.append(f"[{relation}].[{attribute}] {key} ({', '.join('?' for item in value)})")
						valueList.extend(value)

				for key, catalogue in {"IS NULL": isNull, "IS NOT NULL": isNotNull}.items():
					for value in yieldValue(catalogue, attribute, onlyNone = onlyNone):
						if (value):
							locationList.append(f"[{relation}].[{attribute}] {key}")

				for key, catalogue in {"EXISTS": exists, "NOT EXISTS": notExists}.items():
					for value in yieldValue(catalogue, attribute, onlyNone = onlyNone):
						if (value):
							locationList.append(f"[{relation}].[{value}] {key}")

				for key, (catalogue, positive) in {"=": (nextTo, True), "!=": (notNextTo, False), "LIKE": (like, True), "NOT LIKE": (notLike, False),
					">": (greaterThan, False), "<": (lessThan, True), ">=": (greaterThanOrEqualTo, True), "<=": (lessThanOrEqualTo, True)}.items():

					for value in yieldValue(catalogue, attribute, onlyNone = onlyNone):
						if (value in [None, NULL]):
							locationList.append(f"[{relation}].[{attribute}] IS {['NOT ', ''][positive]}NULL OR [{relation}].[{attribute}] {['!=', '='][positive]} ''")
						else:
							locationList.append(f"[{relation}].[{attribute}] {key} ?")
							valueList.append(value)

		################################################

		combined = {*nextTo.keys(), *notNextTo.keys(), *like.keys(), *notLike.keys(), *isNull.keys(), *isNotNull.keys(), 
			*isIn.keys(), *isNotIn.keys(), *isAny.keys(), *isNotAny.keys(), *isAll.keys(), *isNotAll.keys(), *isBetween.keys(), *isNotBetween.keys(), 
			*exists.keys(), *notExists.keys(),*greaterThan.keys(), *lessThan.keys(), *greaterThanOrEqualTo.keys(), *lessThanOrEqualTo.keys()}

		if (None in combined):
			combined.discard(None)
			compileLocations(self.getAttributeNames(relation), onlyNone = True)
			locationList = [f"""({f" {('OR', 'AND')[nextToCondition_None]} ".join(locationList)})"""]

		compileLocations(combined)

		return f" {('OR', 'AND')[nextToCondition]} ".join(locationList), valueList

	def executeCommand_add(self, relation, *args, add = True, **kwargs):
		"""Handles incrementing foreign key counts if needed."""

		if (relation not in self.foreignKeys_catalogue):
			return self.executeCommand(*args, **kwargs)

		attributeList = [self.getPrimaryKey(relation), *self.foreignKeys_catalogue[relation].keys()]
		command = f"SELECT DISTINCT {', '.join(attributeList)} FROM [{relation}]"
		oldRows = set(self.executeCommand(command))

		answer = self.executeCommand(*args, **kwargs)

		function = [self.subtractForeignUse, self.addForeignUse][add]
		for _attribute, rows in itertools.islice(zip(attributeList, zip(*(oldRows ^ set(self.executeCommand(command))))), 1, None):
			for item in rows:
				if (item is None):
					continue
				function(relation, item, *self.foreignKeys_catalogue[relation][_attribute])

		return answer

	def executeCommand_subtract(self, *args, **kwargs):
		"""Handles decrementing foreign key counts if needed."""

		return self.executeCommand_add(*args, add = False, **kwargs)

	def executeCommand(self, command, valueList = None, hackCheck = False, filterNone = False, transpose = False,
		valuesAsSet = False, printError_command = True, attributeFirst = False, filterTuple = False,
		exclude = None, excludeFunction = None, include = None, includeFunction = None, rowsAsList = False, 
		resultKeys = None, alias = None, relation = None, formatter = None, returnNull = None, checkForeign = None):
		"""Executes an SQL command. Allows for multi-threading.
		Special thanks to Joaquin Sargiotto for how to lock threads on https://stackoverflow.com/questions/26629080/python-and-sqlite3-programmingerror-recursive-use-of-cursors-not-allowed
		Use: https://stackoverflow.com/questions/5365451/problem-with-regexp-python-and-sqlite

		command (str)     - The SQL command to run
		valueList (tuple) - The variables to replace any '?' with in 'command'
		hackCheck (bool)  - Checks commands for common hacking tricks before it is executed
			- If True: Checks for commented out portions, escaped characters, and extra commands such as TABLE and SELECT
			- If False: Does not check the string.

		Example Input: executeCommand(command, value)
		Example Input: executeCommand(command, valueList)
		Example Input: executeCommand(command, [value] + valueList)
		"""

		exclude = self.ensure_set(exclude, convertNone = False)
		include = self.ensure_set(include, convertNone = False)
		resultKeys = self.ensure_container(resultKeys)

		def getCursor(command, valueList):
			attempts = 0
			self.waiting = False
			while True:
				try:
					return self.cursor.execute(command, valueList)

				except sqlite3.OperationalError as error:
					if ("database is locked" not in error.args):
						if (printError_command):
							print(f"-- {command}, {valueList}")
						raise error

					if (not attempts):
						self.waiting = True
						pubsub_pub.sendMessage("event_cmd_startWaiting")

					if (self.multiProcess is -1):
						time.sleep(self.multiProcess_delay / 1000)
						continue

					if ((self.multiProcess in [0, None]) or (attempts > self.multiProcess)):
						raise error

					time.sleep(self.multiProcess_delay / 1000)
					attempts += 1
					continue

				except Exception as error:
					if (printError_command):
						print(f"-- {command}, {valueList}")
					raise error
			
				finally:
					self.waiting = False
					self.previousCommand = (command, valueList)

		def yieldRow(command, valueList):
			resultCursor = getCursor(command, valueList)
			try:
				for row in resultCursor.fetchall():
					yield row
			except pyodbc.ProgrammingError:
				return
			except UnicodeDecodeError:
				fails = 0
				failThreshold = 10 #Keep it from spinning its wheels
				while (fails < failThreshold):
					try:
						row = resultCursor.fetchone()
					except pyodbc.ProgrammingError:
						return
					except Exception as error:
						fails += 1
						yield ("error" for error in range(n))
					if (row is None):
						break
					yield row

		if (resultKeys):
			assert relation
			def yieldValue(i, row):
				for attribute, value in zip(resultKeys, row):
					if (not checkFilter(value)):
						continue

					yield self.formatAttribute(attribute, row = i, alias = alias), self.formatValue(value, attribute, relation, returnNull = returnNull, checkForeign = checkForeign, formatter = formatter)
		else:
			def yieldValue(row):
				for value in row:
					if (not checkFilter(value)):
						continue

					yield value

		def checkFilter(value):
			if ((filterNone) and (value is None)):
				return False
				
			if (exclude):
				if (excludeFunction):
					if (excludeFunction(value, exclude)):
						return False
				elif (value in exclude):
					return False
				
			if (include):
				if (includeFunction):
					if (includeFunction(value, include)):
						return False
				elif (value not in include):
					return False

			return True

		#####################################################################

		# assert len(re.findall("\?", command)) == len(valueList)

		#Check for common hacking techniques
		## MAKE THIS MORE ROBUST ##
		if (hackCheck):
			#Check for comments
			if (("--" in command) or ("/*" in command)):
				errorMessage = f"Cannot comment out portions of the command: {command}"
				raise ValueError(errorMessage)

		#Filter NULL placeholder
		if (valueList is None):
			valueList = ()
		elif (isinstance(valueList, (str))):
			valueList = (valueList,)
		elif (isinstance(valueList, (int, float))):
			valueList = (f"{valueList}",)
		else:
			valueList = [f"{item}" if (item not in [None, NULL]) else None for item in valueList]

		#Run Command
		# print("@0.1", command, valueList)
		with threadLock:
			if (resultKeys):
				assert not transpose

				if (not attributeFirst):
					if (rowsAsList):
						return [{attribute: value for attribute, value in yieldValue(i, row)} for i, row in enumerate(yieldRow(command, valueList))]
					else:
						return tuple({attribute: value for attribute, value in yieldValue(i, row)} for i, row in enumerate(yieldRow(command, valueList)))
				
				if (valuesAsSet):
					result = collections.defaultdict(set)
					for i, row in enumerate(yieldRow(command, valueList)):
						for attribute, value in yieldValue(i, row): 
							result[attribute].add(value)
				else:
					result = collections.defaultdict(list)
					for i, row in enumerate(yieldRow(command, valueList)):
						for attribute, value in yieldValue(i, row): 
							result[attribute].append(value)
				return result

		iterator = yieldRow(command, valueList)
		if (transpose):
			iterator = zip(*iterator)

		if (filterTuple):
			if (valuesAsSet):
				return {value for item in iterator for value in yieldValue(item)}
			if (rowsAsList):
				return [value for item in iterator for value in yieldValue(item)]
			return tuple(value for item in iterator for value in yieldValue(item))

		if (rowsAsList):
			if (valuesAsSet):
				return [set(yieldValue(item)) for item in iterator]
			return [tuple(yieldValue(item)) for item in iterator]

		if (valuesAsSet):
			return tuple(set(yieldValue(item)) for item in iterator)
		return tuple(tuple(yieldValue(item)) for item in iterator)

	#Interaction Functions
	def quickOpen(self):
		assert self.connection is not None

		self.cursor = self.connection.cursor()

	def quickClose(self):
		if (self.connection is None):
			return

		self.cursor.close()
		print("@quickClose", "Connection Closed")

	def setDefaultCommit(self, state):
		self.defaultCommit = state

	def setMultiProcess(self, value):
		self.multiProcess = value

	def setMultiProcessDelay(self, value):
		self.multiProcess_delay = value

	@wrap_errorCheck()
	def openDatabase(self, fileName = "myDatabase", *args, applyChanges = True, multiThread = False, connectionType = None, 
		password = None, readOnly = False, keepOpen = None, multiProcess = -1, multiProcess_delay = 100,
		resultError_replacement = None, aliasError_replacement = None):

		"""Opens a database.If it does not exist, then one is created.
		Note: If a database is already opened, then that database will first be closed.
		Use: toLarry Lustig for help with multi-threading on http://stackoverflow.com/questions/22739590/how-to-share-single-sqlite-connection-in-multi-threaded-python-application
		Use: to culix for help with multi-threading on http://stackoverflow.com/questions/6297404/multi-threaded-use-of-sqlalchemy

		Use: https://stackoverflow.com/questions/31164610/connect-to-sqlite3-server-using-pyodbc-python
		Use: http://www.blog.pythonlibrary.org/2010/10/10/sqlalchemy-and-microsoft-access/

		fileName (str)      - The name of the database file
		applyChanges (bool) - Determines the default for when changes are saved to the database
			If True  - Save after every change. Slower, but more reliable because data will be saved in the database even if the program crashes
			If False - Save when the user tells the API to using saveDatabase() or the applyChanges parameter in an individual function. Faster, but data rentention is not ensured upon crashing
		multiThread (bool)  - If True: Will allow mnultiple threads to use the same database

		multiProcess (int) - Determines how many times to try executing a command if another process is using the database
			- If 0 or None: Do not retry
			- If -1: Retry forever
		multiProcess_delay (int) - How many milli-seconds to wait before trying to to execute a command again

		Example Input: openDatabase("emaildb")
		Example Input: openDatabase("emaildb.sqllite")
		Example Input: openDatabase("emaildb", applyChanges = False)
		Example Input: openDatabase("emaildb", multiThread = True)
		Example Input: openDatabase("emaildb", multiThread = True, multiProcess = 10)
		"""
		global connectionTypeCache

		if (not fileName):
			fileName = self.fileName
		if (keepOpen is None):
			keepOpen = self.keepOpen
		if (not keepOpen):
			self.fileName = fileName
			return

		#Check for another open database
		if (self.connection is not None):
			self.closeDatabase()

		#Check for file extension
		if ("." not in fileName):
			fileName += self.defaultFileExtension

		definitionCache.clear()
		connectionTypeCache.clear()
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

		#Establish connection
		if (self.isSQLite()):
			if (multiThread):
				#Temporary fix until I learn SQLAlchemy to do this right
				self.connection = sqlite3.connect(fileName, check_same_thread = False)
			else:
				self.connection = sqlite3.connect(fileName)
		elif (self.isAccess()):
			driverList = self.getDriverList("Microsoft Access Driver")
			if (not driverList):
				errorMessage = "You need to install 'Microsoft Access Database Engine 2010 Redistributable'. It can be found at: https://www.microsoft.com/en-US/download/details.aspx?id=13255"
				raise SyntaxError(errorMessage)

			if ("Microsoft Access Driver (*.mdb, *.accdb)" in driverList):
				driver = "Microsoft Access Driver (*.mdb, *.accdb)"

			elif (".accdb" in fileName):
				errorMessage = "You need to install 'Microsoft Access Database Engine 2010 Redistributable'. It can be found at: https://www.microsoft.com/en-US/download/details.aspx?id=13255"
				raise SyntaxError(errorMessage)

			else:
				driver = "Microsoft Access Driver (*.mdb)"

			self.connection = pyodbc.connect(driver = driver, dbq = fileName)

			#Use: https://github.com/mkleehammer/pyodbc/wiki/Unicode
			self.connection.setdecoding(pyodbc.SQL_CHAR, encoding = "utf-8")
			self.connection.setdecoding(pyodbc.SQL_WCHAR, encoding = "utf-8")
			self.connection.setencoding(encoding = "utf-8")
		else:
			errorMessage = f"Unknown connection type {connectionType}"
			raise KeyError(errorMessage)

		if (keepOpen):
			self.quickOpen()

		#Update internal values
		self.fileName = fileName

		#Update internal foreign schema catalogue
		self.updateInternalforeignSchemas()
		self.updateForeignUses(updateSchema = False)

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def closeDatabase(self):
		"""Closes the opened database.

		Example Input: closeDatabase()
		"""

		self.quickClose()

		self.connection = None
		self.cursor = None
		self.fileName = None

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def saveDatabase(self):
		"""Saves the opened database.

		Example Input: saveDatabase()
		"""
		if (self.connection is None):
			return

		#Save changes
		self.connection.commit()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def removeRelation(self, relation = None, applyChanges = None):
		"""Removes an entire relation (table) from the database if it exists.
		Special thanks to Jimbo for help with spaces in database names on http://stackoverflow.com/questions/10920671/how-do-you-deal-with-blank-spaces-in-column-names-in-sql-server

		relation (str)      - What the relation is called in the .db
			- If None: All tables will be removed from the .db
		applyChanges (bool) - Determines if the database will be saved after the change is made.
			- If None: The default flag set upon opening the database will be used

		Example Input: removeRelation()
		Example Input: removeRelation("Users")
		"""

		if (relation is None):
			relation = self.getRelationNames()
		else:
			relation = self.ensure_container(relation)

		for _relation in relation:
			if (self.isSQLite()):
				command = "DROP TABLE IF EXISTS [{}]".format(_relation)
			else:
				if (_relation not in self.getRelationNames()):
					return

				command = "DROP TABLE [{}]".format(_relation)
			self.executeCommand(command)
			self.subtractForeignUse(relation = _relation, n = None)

		#Save Changes
		if (applyChanges is None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

		#Update internal foreign schema catalogue
		self.updateInternalforeignSchemas()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def clearRelation(self, relation = None, applyChanges = None):
		"""Removes all rows in the given relation. The relation will still exist.

		relation (str)      - What the relation is called in the .db
			- If None: All relations will be cleared on the .db
		applyChanges (bool) - Determines if the database will be saved after the change is made.
			- If None: The default flag set upon opening the database will be used

		Example Input: clearRelation()
		"""

		#Update internal foreign schema catalogue
		self.updateInternalforeignSchemas()

		#Save Changes
		if (applyChanges is None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def renameRelation(self, relation, newName, applyChanges = None):
		"""Renames a relation (table) to the given name the user provides.

		relation (str)      - What the relation is called in the .db
		newName (str)       - What the relation will now be called in the .db
		applyChanges (bool) - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used

		Example Input: renameRelation("Users", "Customers")
		"""

		#Error Check
		if (relation != newName):
			#Build SQL command
			command = "ALTER TABLE [{}] RENAME TO [{}]".format(relation, newName)

			#Execute SQL
			self.executeCommand(command)

			#Save Changes
			if (applyChanges is None):
				applyChanges = self.defaultCommit

			if (applyChanges):
				self.saveDatabase()

			#Update internal foreign schema catalogue
			self.updateInternalforeignSchemas()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def setSchema(self, relation, schema = None, notNull = None, primary = None, autoIncrement = None, unsigned = None,
		 unique = None, default = None, foreign = None, remove = None, applyChanges = None, updateSchema = True, database = None):
		"""Renames a relation (table) to the given name the user provides.

		relation (str)      - What the relation is called in the .db
		applyChanges (bool) - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used

		Example Input: setSchema("Users", foreign = {"name": {"Names": "first_name"}})
		Example Input: setSchema("Users", schema = {"counter": int})
		Example Input: setSchema("Users", database = Database.build("data.db"))
		"""

		schema = schema or {}
		unique = unique or {}
		notNull = notNull or {}
		primary = primary or {}
		default = default or {}
		foreign = foreign or {}
		unsigned = unsigned or {}
		autoIncrement = autoIncrement or {}

		remove = self.ensure_container(remove)

		def modify(old_thing, mod_thing):
			"""Applies user modifications to the table settings."""
			nonlocal remove

			for new_key, new_value in mod_thing.items():
				old_thing[new_key] = new_value

			for item in remove:
				if (item in old_thing):
					del old_thing[item]

			return old_thing

		#Get current data
		data = self.getSchema(relation)
		table_contents = self.getAllValues(relation, orderBy = self.getPrimaryKey(relation), exclude = remove, checkForeign = True, 
			forceRelation = True, forceAttribute = True, forceTuple = True, attributeFirst = False, rowsAsList = True)

		#Determine changes
		new_schema = modify(data["schema"], schema)
		new_foreign = modify(data["foreign"], foreign)
		new_notNull = modify(data["notNull"], notNull)
		new_primary = modify(data["primary"], primary)
		new_autoIncrement = modify(data["autoIncrement"], autoIncrement)
		new_unsigned = modify(data["unsigned"], unsigned)
		new_unique = modify(data["unique"], unique)
		new_default = modify(data["default"], default)

		if (database is None):
			#Rename old table
			self.renameRelation(relation, "tempCopy_{}".format(relation))

			#Create new table
			self.createRelation(relation, schema = new_schema, notNull = new_notNull, primary = new_primary, 
				autoIncrement = new_autoIncrement, unsigned = new_unsigned, unique = new_unique, foreign = new_foreign, 
				applyChanges = applyChanges, default = new_default, autoPrimary = False)

			#Populate new table with old values
			self.addTuple(table_contents, applyChanges = applyChanges)
			
			#Remove renamed table
			self.removeRelation("tempCopy_{}".format(relation), applyChanges = applyChanges)

			if (updateSchema):
				self.updateInternalforeignSchemas()
			return

		if (not isinstance(database, Database)):
			database = Database(database)

		database.removeRelation(relation, applyChanges = applyChanges)
		database.createRelation(relation, schema = new_schema, notNull = new_notNull, primary = new_primary, 
			autoIncrement = new_autoIncrement, unsigned = new_unsigned, unique = new_unique, foreign = new_foreign, 
			applyChanges = applyChanges, default = new_default, autoPrimary = False)
		database.addTuple(table_contents, applyChanges = applyChanges)

		if (updateSchema):
			database.updateInternalforeignSchemas()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def createRelation(self, relation, schema = {}, applyChanges = None, autoPrimary = True, 
		notNull = {}, primary = {}, autoIncrement = {}, unsigned = {}, unique = {}, default = {},
		foreign = None, noReplication = True, index = None):
		"""Adds a relation (table) to the database.
		Special thanks to Jimbo for help with spaces in database names on http://stackoverflow.com/questions/10920671/how-do-you-deal-with-blank-spaces-in-column-names-in-sql-server
		
		relation (str)      - What the relation will be called in the .db
		schema (dict)       - The relation schema. {attribute (str): data type (type)}
			If a dictionary with multiple elements is given, the order will be randomized
			If a list of one element dictionaries is given, the order will be the order of the list
			If string is given, will use the full schema from the relation with this name
		applyChanges (bool) - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used
		autoPrimary (bool)   - Determines if a primary key will automatically be added to the new table. If notNull, primary, autoIncrement, or unsigned are given, they will override the defaults for this option

		notNull (dict)       - Determines how the initial value is assigned to a given attribute. {attribute (str): flag (bool)}
			- If True: Signals to the database that this will be used a lot
		primary (dict)       - Tells the database that this is the primary key (the relation id). {attribute (str): flag (bool)}
		autoIncrement (dict) - Determines if the attribute's value will increment every time it is written to. {attribute (str): flag (bool)}
		unsigned (dict)      - Determines if the attribute's value will be able to be negative. {attribute (str): flag (bool)}
		unique (dict)        - Signals to the database that there cannot be more than one attribute with this name
		
		foreign (str)        - If not None: Tells the database that this is the foreign key (a link to another relation). Can be a list if more than one foreign key is given. {attribute (str): foreign relation (str)}
		noReplication (bool) - If True: The table will not be created if it does not already exist
			- If None: Will delete the previously existing table if it exists

		Example Input: createRelation("Users", {"email": str, "count": int})
		Example Input: createRelation("Users", [{"email": str}, {"count": int}])
		Example Input: createRelation("Users", {"email": str, "count": int}, applyChanges = False)
		Example Input: createRelation("Users", {"id": int, "email": str, "count": int}, notNull = {"id": True}, primary = {"id": True}, autoIncrement = {"id": True}, unique = {"id": True}, autoPrimary = False)
		
		Example Input: createRelation("Names", [{"first_name": str}, {"extra_data": str}], unique = {"first_name": True})
		Example Input: createRelation("Users", {"age": int, "height": int}, foreign = {"name": {"Names": "first_name"}})
		Example Input: createRelation("Users", {"age": int, "height": int}, foreign = {"name": {"Names": "first_name"}, "address": {"Address": "street"}})
		
		Example Input: createRelation("Users", "Backup Users"})
		"""

		schema = schema or {}

		if (self.isAccess()):
			if (foreign):
				errorMessage = "The ODBC driver for MS Access does not support foreign keys"
				raise KeyError(errorMessage)
			if (primary):
				errorMessage = "The ODBC driver for MS Access does not support primary keys"
				raise KeyError(errorMessage)
			autoPrimary = False

		#Build SQL command
		command = "CREATE TABLE "

		if ((noReplication is not None) and (self.isSQLite())):
			command += "IF NOT EXISTS "
		else:
			self.removeRelation(relation)

		command += f"[{relation}]"

		if (isinstance(schema, str)):
			raw_sql = self.executeCommand("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{}'".format(schema), filterTuple = True)

			if (not raw_sql):
				errorMessage = f"There is no relation {schema} in the database for {self.__repr__()}"
				raise KeyError(errorMessage)
			raw_sql = raw_sql[0]

			command += re.sub("CREATE TABLE .*?\(", f"(", raw_sql)
			self.executeCommand(command)
		else:
			#Format schema
			commandList = []
			if (autoPrimary):
				commandList.append(self.getDefinition("id", dataType = int, autoPrimary = True))
			commandList.append(self.formatSchema(schema = schema, applyChanges = applyChanges, autoPrimary = False, notNull = notNull, 
				primary = primary, autoIncrement = autoIncrement, unsigned = unsigned, unique = unique, default = default, foreign = foreign))
			schemaFormatted = ", ".join(commandList)

			#Execute SQL
			self.executeCommand(command + "({})".format(schemaFormatted))

		if (index):
			self.createIndex(relation, index)

		#Save Changes
		if (applyChanges is None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

		#Update internal foreign schema catalogue
		self.updateInternalforeignSchemas()

	def copyAttribute(self, source_relation, source_attribute, destination_relation, destination_attribute = None):
		"""Copies an attribute from an existing table to another.

		Example Input: copyAttribute("Names", "extra_data", "Users"):
		"""

		if (destination_attribute is None):
			destination_attribute = source_attribute

		data = self.getSchema(source_relation)
		self.addAttribute(destination_relation, destination_attribute, 
			dataType = data["schema"].get(source_attribute, str),
			default = data["default"].get(source_attribute, None),
			notNull = data["notNull"].get(source_attribute, None),
			primary = data["primary"].get(source_attribute, None),
			autoIncrement = data["autoIncrement"].get(source_attribute, None),
			unsigned = data["unsigned"].get(source_attribute, None),
			unique = data["unique"].get(source_attribute, None),
			foreign = data["foreign"].get(source_attribute, None),
			)

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def removeAttribute(self, relation, attribute):
		"""Removes an attribute (column) from a relation (table).

		Example Input: removeAttribute("Users", "date created")
		Example Input: removeAttribute("Users", ["date created", "extra_data"])
		"""

		self.setSchema(relation, remove = attribute)

	@wrap_errorCheck()
	@wrap_connectionCheck()
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

		if (attribute in self.getAttributeNames(relation)):
			errorMessage = f"{attribute} already exists in {relation}"
			raise KeyError(errorMessage)

		if (primary and (True in self.getSchema(relation)["primary"].values())):
			errorMessage = f"{relation} already has a primary key"
			raise ValueError(errorMessage)

		if (foreign or unique or (notNull and (default is None)) or primary):
			#The desired behavior is not supported by "ALTER TABLE" in sqlite
			return self.setSchema(relation, schema = {attribute: dataType}, notNull = {attribute: notNull}, primary = {attribute: primary}, 
			autoIncrement = {attribute: autoIncrement}, unsigned = {attribute: unsigned}, unique = {attribute: unique}, 
			default = {attribute: default}, foreign = {attribute: foreign}, applyChanges = applyChanges)

		#Build SQL command
		command = "ALTER TABLE [{}] ADD COLUMN ".format(relation)

		command += self.formatSchema(schema = {attribute: dataType}, notNull = {attribute: notNull}, primary = {attribute: primary}, 
			autoIncrement = {attribute: autoIncrement}, unsigned = {attribute: unsigned}, unique = {attribute: unique}, 
			default = {attribute: default}, foreign = {attribute: foreign}, applyChanges = False, autoPrimary = False)

		#Execute SQL
		try:
			self.executeCommand(command, printError_command = False)
		except sqlite3.OperationalError as error:
			if (error.__str__() == "Cannot add a column with non-constant default"):
				return self.setSchema(relation, schema = {attribute: dataType}, notNull = {attribute: notNull}, primary = {attribute: primary}, 
			autoIncrement = {attribute: autoIncrement}, unsigned = {attribute: unsigned}, unique = {attribute: unique}, 
			default = {attribute: default}, foreign = {attribute: foreign}, applyChanges = applyChanges)
			else:
				print(f"-- {command}, []")
				raise error

		#Save Changes
		if (applyChanges is None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

		#Update internal foreign schema catalogue
		self.updateInternalforeignSchemas()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def addTuple(self, myTuple = None, applyChanges = None, autoPrimary = False, notNull = False, foreignNone = False,
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

		if (not myTuple):
			return

		for relation, rows in myTuple.items():
			if (isinstance(rows, dict)):
				rows = [rows]
			for attributeDict in rows:
				# if (unique is None):
				# 	#For the case of None, multiple items can be inserted even if the attribuite is 'unique' in the table's schema
				# 	uniqueState = self.getSchema(relation)["unique"]
				# 	for attribute, value in myTuple.items():
				# 		if ((attribute in uniqueState) and (uniqueState[attribute]) and (value is NULL)):
				# 			existsCheck = self.getValue({relation: attribute}, {attribute: value})[attribute]
				# 			if (existsCheck):
				# 				return

				# if ((self.isAccess()) and (unique in [True, None])):
				# 	removeCatalogue = {} 
				# 	for attribute, value in myTuple.items():
				# 		existsCheck = self.getValue({relation: attribute}, {attribute: value})[attribute]
				# 		if (existsCheck):
				# 			removeCatalogue["attribute"] = existsCheck[0]

				# 	for attribute, oldValue in removeCatalogue.items():
				# 		if (unique):
				# 			jkjhjkhjhk #There are no row ids, so find a way to ensure only the one row is changed?
				# 			self.changeTuple({relation: attribute}, {attribute: oldValue}, myTuple[attribute], checkForeign = checkForeign)
				# 		del myTuple[attribute]
					
				# 	if (not myTuple):
				# 		return

				#Build attribute side
				if (not checkForeign):
					attributeList, valueList = zip(*attributeDict.items())
				else:
					valueList = []
					attributeList = []
					for attribute, value in attributeDict.items():
						#Remember the associated value for the attribute
						valueList.append(self.insertForeign(relation, attribute, value, foreignNone = foreignNone))
						attributeList.append(attribute)

				if (self.isAccess()):
					command = f"INSERT INTO [{relation}] ({', '.join(attributeList)}) VALUES ({', '.join('?' for i in valueList)})"
				else:
					command = f"INSERT { {True: 'OR REPLACE ', False: '', None: 'OR IGNORE '}[unique] }INTO [{relation}] ({', '.join(attributeList)}) VALUES ({', '.join('?' for i in valueList)})"
				
				if (unique):
					for value, attribute in zip(valueList, attributeList):
						self.removeCache_value(value, attribute, relation, _raiseError = False)

				assert len(attributeList) is len(valueList)
				if (incrementForeign):
					self.executeCommand_add(relation, command, valueList)
				else:
					self.executeCommand(command, valueList)

		#Save Changes
		if (applyChanges is None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def changeTuple(self, myTuple, nextTo, value = None, forceMatch = None,
		applyChanges = None, checkForeign = True, updateForeign = None, **locationKwargs):
		"""Changes a tuple (row) for a given relation (table).
		Note: If multiple entries match the criteria, then all of those tuples will be chanegd.
		Special thanks to Jimbo for help with spaces in database names on http://stackoverflow.com/questions/10920671/how-do-you-deal-with-blank-spaces-in-column-names-in-sql-server

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

		def yieldValue(valueList):
			for _value in valueList:
				if (_value is None):
					yield NULL
				elif (_value in [True, "True"]):
					yield 1
				elif (_value in [False, "False"]):
					yield 0
				else:
					yield _value
				# elif (_value is NULL):
				# 	yield _value
				# else:
				# 	yield f"{_value}"

		def yieldChange(attributeList, valueList):
			if (not incrementForeign):
				for attribute, newValue in zip(attributeList, yieldValue(valueList)):
					yield attribute, newValue
				return

			for attribute, newValue in zip(attributeList, yieldValue(valueList)):
				newValue = self.changeForeign(relation, attribute, newValue, oldRows[attribute], updateForeign = updateForeign)
				yield attribute, newValue

		#############################################################################

		if (applyChanges is None):
			applyChanges = self.defaultCommit
				
		for relation, attributeDict in myTuple.items():
			if (not isinstance(attributeDict, dict)):
				if (isinstance(attributeDict, (list, tuple, set, range, types.GeneratorType))):
					attributeDict = {item: value for item in attributeDict}
				else:
					attributeDict = {attributeDict: value}
			attributeList, valueList = zip(*attributeDict.items())
			
			index = self.getPrimaryKey(relation)
			locationInfo, locationValues = self.configureLocation(relation, nextTo = nextTo, **locationKwargs)
			
			command = f"SELECT {index} FROM [{relation}]"
			if (locationInfo):
				command += f" WHERE ({locationInfo})"
			command += f" ORDER BY {index}"
			affected = self.executeCommand(command, locationValues, transpose = True)
			if (not affected):
				if (not forceMatch):
					errorMessage = f"There is no row in the relation {relation} with the criteria: { {'nextTo': nextTo, **locationKwargs} }"
					raise KeyError(errorMessage)
				self.addTuple({relation: {**nextTo, **locationKwargs, **attributeDict}}, unique = None)
				continue

			if ((checkForeign) and (relation in self.foreignKeys_catalogue)):
				foreign_attributeList = [index, *self.foreignKeys_catalogue[relation].keys()]
				selectCommand = f"SELECT {', '.join(foreign_attributeList)} FROM [{relation}] WHERE ({index} IN ({', '.join('?' for item in affected[0])})) ORDER BY {index}"
				oldRows = self.executeCommand(selectCommand, affected[0], resultKeys = foreign_attributeList, 
					filterNone = True, relation = relation, checkForeign = False, attributeFirst = True)
				incrementForeign = True
			else:
				incrementForeign = False
					
			_attributeList, newValues = zip(*yieldChange(attributeList, valueList))
			command = f"UPDATE [{relation}] SET {', '.join(f'{attribute} = ?' for attribute in _attributeList)}"
			if (locationInfo):
				command += f" WHERE ({locationInfo})"
			self.executeCommand(command, (*newValues, *locationValues))

			if (incrementForeign):
				newRows = self.executeCommand(selectCommand, affected[0], resultKeys = foreign_attributeList, filterNone = True, 
					relation = relation, checkForeign = False, attributeFirst = True)

				for attribute in itertools.islice(foreign_attributeList, 1, None):
					for old, new in itertools.zip_longest(oldRows[attribute], newRows[attribute]):
						if (old is new):
							continue

						if (old is not None):
							self.subtractForeignUse(relation, old, *self.foreignKeys_catalogue[relation][attribute])
						if (new is not None):
							self.addForeignUse(relation, new, *self.foreignKeys_catalogue[relation][attribute])

			if (applyChanges):
				self.saveDatabase()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def removeTuple(self, myTuple, applyChanges = None,	checkForeign = True, updateForeign = True, incrementForeign = True, **locationKwargs):
		"""Removes a tuple (row) for a given relation (table).
		Note: If multiple entries match the criteria, then all of those tuples will be removed.
		WARNING: Does not currently look for forigen keys.

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
		updateForeign (bool) - Determines what happens to existing foreign keys
			- If True: Foreign keys will be updated to the new value
			- If False: A new foreign tuple will be inserted
			- If None: A foreign key will be updated to the new value if only one item is linked to it, otherwise a new foreign tuple will be inserted
		exclude (list)       - A list of tables to exclude from the 'updateForeign' check

		Example Input: removeTuple({"Users": {"name": "John"}})
		Example Input: removeTuple({"Users": {"name": ["John", "Jane"]}})
		Example Input: removeTuple({"Users": {"name": "John", "age": 26}})
		Example Input: removeTuple({"Users": {"name": "John"}}, like = {"Users": {"email": "@gmail.com"}})
		"""

		#Account for multiple tuples to remove
		for relation, nextTo in myTuple.items():
			locationInfo, valueList = self.configureLocation(relation, nextTo = nextTo, **locationKwargs)

			for row in self.getValue({relation: None}, nextTo = nextTo, **locationKwargs, checkForeign = False, 
				forceAttribute = True, forceTuple = True, rowsAsList = True, attributeFirst = False):
				for attribute, value in row.items():
					self.removeCache_value(f"{value}", attribute, relation, _raiseError = False)

			command = "DELETE FROM [{}] WHERE ({})".format(relation, locationInfo)
			if (incrementForeign):
				self.executeCommand_subtract(relation, command, valueList)
			else:
				self.executeCommand(command, valueList)

		#Save Changes
		if (applyChanges is None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

	@wrap_errorCheck()
	@wrap_connectionCheck()
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
		"""

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
	@wrap_connectionCheck()
	def getValue(self, myTuple, nextTo = None, orderBy = None, limit = None, direction = None, alias = None, 
		returnNull = False, includeDuplicates = True, checkForeign = True, formatValue = None, 
		maximum = None, minimum = None, average = None, summation = None,
		forceRelation = False, forceAttribute = False, forceTuple = False, attributeFirst = True, rowsAsList = False, 
		filterForeign = True, filterNone = False, exclude = None, forceMatch = None, **locationKwargs):
		"""Gets the value of an attribute in a tuple for a given relation.
		If multiple attributes match the criteria, then all of the values will be returned.
		If you order the list and limit it; you can get things such as the 'top ten occurrences', etc.
		For more information on JOIN: https://www.techonthenet.com/sqlite/joins.php

		myTuple (dict)   - What to return {relation: attribute}
			- A list of attributes can be returned: {relation: [attribute 1, attribute 2]}
			- If an attribute is a foreign key: {relation: {foreign relation: foreign attribute}}
			- If list: [(myTuple 1, nextTo 1), (myTuple 2, nextTo 2)]. Will ignore 'nextTo'
		nextTo (dict)    - An attribute-value pair that is in the same tuple. {attribute: value}
			- If multiple keys are given, all will be used according to 'nextToCondition'
			- If an attribute is a foreign key: {value: {foreign relation: foreign attribute}}
			- If None: The whole column will be returned
			- If str: Will return for all columns where that value is present
		orderBy (any)    - Determines whether to order the returned values or not. A list can be given to establish priority for multiple things
			- If None: Do not order
			- If not None: Order the values by the given attribute
		limit (int)      - Determines whether to limit the number of values returned or not
			- If None: Do not limit the return results
			- If not None: Limit the return results to this many
		direction (bool) - Determines if a descending or ascending condition should be appled. Used for integers. If a list is given for 'orderBy', either
			(A) a list must be given with the same number of indicies, (B) a single bool given that will apply to all, or (C) a dictionary given where the 
			key is the item to adjust and the value is the bool for that item
			- If True: Ascending order
			- If False: Descending order
			- If None: No action taken
		exclude (list) - What values to not return
		forceMatch (any) - Determines what will happen in the case where 'nextTo' is not found
			- If True: Create a new row that contains the default values
			- If False: Do nothing
			- If None: Do nothing

		nextToCondition (bool) - Determines how to handle multiple nextTo criteria
			- If True: All of the criteria given must match
			- If False: Any of the criteria given must match
		checkForeign (bool)   - Determines if foreign keys will be take in account
		
		filterTuple (bool)     - Determines how the final result in the catalogue will be returned if there is only one column
			- If True: (value 1, value 2, value 3...)
			- If False: ((value 1, ), (value 2, ), (value 3. ),..)
		filterRelation (bool)  - Determines how catalogue will be returned
			- If True: {attribute 1: values, attribute 2: values}
				For multiple relations: {attribute 1 for relation 1: values, attribute 2 for relation 1: values, attribute 1 for relation 2: values}
			- If False: {relation: {attribute 1: values, attribute 2: values}}
				For multiple relations: {relation 1: {attribute 1 for relation 1: values, attribute 2 for relation 1: values}, {attribute 1 for relation 2: values}}
		filterForeign (bool)   - Determines how results of foreign attributes will be returned
			- If True: Returns only the values that have valid foreign keys
			- If False: Returns all values and replaces values that have valid foreign keys
			- If None:  Returns Replaces values that have valid foreign keys and fills in a None for values with invalid foreign keys
		filterAttribute (bool) - Determines how catalogue will be returned
			- If True: returns a list of all values
				For multiple attributes: [values for attribute 1 and 2]
			- If False: {attribute: values}
				For multiple attributes: {attribute 1: values for attribute 1, attribute 2: values for attribute 2}

		valuesAsList (bool)    - Determines if the values returned should be a list or a tuple
			- If True: Returned values will be in a list
			- If False: Returned values will be in a tuple
		valuesAsRows (bool)    - Determines if the values returned should be returned as rows or columns
			- If True: Returned values will be all the row values for that column {relation: {attribute 1: {row 1: value, row 2: value, row 3: value}}}
			- If False: Returned values will be all the column values for that row with the attribute names with each value {relation: {row 1: {attribute 1: value, attribute 2: value, attribute 3: value}}}

		greaterThan (int)          - Determines if returned values must be '>' another value. {attribute 1 (str): value (int), attribute 2 (str): value (int)}
			- If not None: Returned values will be '>' the given number
			- If None: Does nothing
		lessThan (int)             - Determines if returned values must be '<' another value. {attribute 1 (str): value (int), attribute 2 (str): value (int)}
			- If not None: Returned values will be '<' the given number
			- If None: Does nothing
		greaterThanOrEqualTo (int) - Determines if returned values must be '>=' another value. {attribute 1 (str): value (int), attribute 2 (str): value (int)}
			- If not None: Returned values will be '>=' the given number
			- If None: Does nothing
		lessThanOrEqualTo (int)    - Determines if returned values must be '<=' another value. {attribute 1 (str): value (int), attribute 2 (str): value (int)}
			- If not None: Returned values will be '<=' the given number
			- If None: Does nothing

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
		assert "filterTuple" not in locationKwargs
		assert "valuesAsRows" not in locationKwargs
		assert "valuesAsList" not in locationKwargs
		assert "filterRelation" not in locationKwargs
		assert "filterAttribute" not in locationKwargs
		
		exclude = self.ensure_container(exclude)


		if (isinstance(myTuple, dict)):
			forceRelation = forceRelation or (len(myTuple) > 1)
			myTuple = ((myTuple, nextTo or {}),)
		elif (isinstance(myTuple, str)):
			myTuple = (({myTuple: None}, nextTo or {}),)
		else:
			forceRelation = forceRelation or any((len(item[0]) > 1) for item in myTuple)

		answer = []
		for _myTuple, _nextTo in myTuple:
			results_catalogue = {}
			for relation, attributeList in _myTuple.items():
				_orderBy = orderBy or self.getPrimaryKey(relation)
				selectAll = attributeList is None
				if (selectAll):
					attributeList = self.getAttributeNames(relation)
				else:
					attributeList = self.ensure_container(attributeList)
				
				if (exclude):
					attributeList = tuple(attribute for attribute in attributeList if (attribute not in exclude))

				#Setup
				command = f"SELECT{(' DISTINCT', '')[includeDuplicates]}"

				modifierInfo, modifierLocation = self.configureModifier(relation, includeDuplicates = includeDuplicates, 
					maximum = maximum, minimum = minimum, average = average, summation = summation)
				if (selectAll):
					command += modifierInfo.format("*")
				else:
					command += modifierInfo.format(f"{', '.join(f'[{relation}].[{attribute}]' for attribute in attributeList)}")
				command += f" FROM [{relation}]"

				locationInfo, valueList = self.configureLocation(relation, nextTo = _nextTo, exclude = exclude, extra = modifierLocation, **locationKwargs)
				if (locationInfo):
					command += f" WHERE ({locationInfo})"

				orderInfo = self.configureOrder(relation, orderBy = _orderBy, direction = direction)
				if (orderInfo):
					command += f" ORDER BY {orderInfo}"

				if (self.isAccess()):
					result = self.executeCommand(command, valueList, resultKeys = attributeList, alias = alias, relation = relation, 
						formatter = formatValue, returnNull = returnNull, checkForeign = checkForeign, attributeFirst = attributeFirst)

					if (limit is not None):
						result = result[:limit]

					checkForeign = False
				else:
					if (limit is not None):
						command += " LIMIT {}".format(limit)

					result = self.executeCommand(command, valueList, resultKeys = attributeList, alias = alias, relation = relation, 
						formatter = formatValue, returnNull = returnNull, checkForeign = checkForeign, attributeFirst = attributeFirst)

				_forceAttribute = forceAttribute or (len(attributeList) > 1)
				if (not result):
					if (not forceMatch):
						if (attributeFirst):
							if (_forceAttribute):
								if (rowsAsList):
									results_catalogue[relation] = {attribute: [] for attribute in attributeList}
								else:
									results_catalogue[relation] = {attribute: {} for attribute in attributeList}
							else:
								if (rowsAsList):
									results_catalogue[relation] = []
								else:
									results_catalogue[relation] = {}
						else:
							if (_forceAttribute):
								if (rowsAsList):
									results_catalogue[relation] = [{}]
								else:
									results_catalogue[relation] = {}
							else:
								if (rowsAsList):
									results_catalogue[relation] = []
								else:
									results_catalogue[relation] = {}
						continue
					result = self.getValue({relation: attributeList}, _nextTo, forceMatch = True, checkForeign = checkForeign, 
						filterForeign = filterForeign, returnNull = returnNull, **locationKwargs)
					print(result)
					jkhhjkj
					return result

				if (attributeFirst):
					_forceTuple = forceTuple or (len(next(iter(result.values()), [])) > 1)
				else:
					_forceTuple = forceTuple or (len(result) > 1)

				if (attributeFirst):
					if (_forceTuple):
						if (_forceAttribute):
							if (rowsAsList):
								# results_catalogue[relation] = result # results_catalogue[relation] = {attribute: [value for value in row] for attribute, row in result.items()}
								results_catalogue[relation] = {**result} # results_catalogue[relation] = {attribute: [value for value in row] for attribute, row in result.items()}
							else:
								results_catalogue[relation] = {attribute: {i: value for i, value in enumerate(row)} for attribute, row in result.items()}
						else:
							if (rowsAsList):
								results_catalogue[relation] = list(result.values())[0]
							else:
								results_catalogue[relation] = {0: list(result.values())[0]}
					else:
						if (_forceAttribute):
							results_catalogue[relation] = {attribute: row[0] for attribute, row in result.items()}
						else:
							results_catalogue[relation] = next(iter(result.values()))[0]
				else:
					if (_forceTuple):
						if (_forceAttribute):
							if (rowsAsList):
								# results_catalogue[relation] = result # results_catalogue[relation] = [{attribute: value for attribute, value in row} for row in result]
								results_catalogue[relation] = result[:] # results_catalogue[relation] = [{attribute: value for attribute, value in row} for row in result]
							else:
								results_catalogue[relation] = {i: row for i, row in enumerate(result)}
						else:
							results_catalogue[relation] = [next(iter(row.values())) for row in result]
					else:
						if (_forceAttribute):
							results_catalogue[relation] = {**result[0]}
						else:
							results_catalogue[relation] = next(iter(result[0].values()))

				# print(result)
				if (not results_catalogue):
					print("\nattributeFirst:", attributeFirst, "\n_forceTuple:", _forceTuple, "\n_forceAttribute:", _forceAttribute, "\nrowsAsList:", rowsAsList, "\n")
					sys.exit()
				# print(results_catalogue)

			if (forceRelation):
				answer.append(results_catalogue)
			else:
				answer.append(results_catalogue[relation])

		if (len(answer) is 1):
			return answer[0]
		return answer

	def getForeignLinks(self, relation, updateSchema = True):
		"""Returns foreign keys that are linked attributes in the given relation.
		{foreign relation: {foreign attribute: {relation that links to it: [attributes that link to it]}}}

		Example Input: getForeignLinks("Users")
		"""

		if (updateSchema):
			self.updateInternalforeignSchemas()

		links = container.defaultdict(lambda: container.defaultdict(lambda: container.defaultdict(set)))
				#{foreign_relation (str):     {foreign_attribute (str):     {relation (str): {attribute (str)}}}}

		for relation in self.ensure_container(relation):
			if (relation in self.foreignKeys_catalogue):
				for attribute, (foreign_relation, foreign_attribute) in self.foreignKeys_catalogue[relation].items():
					links[foreign_relation][foreign_attribute][relation].add(attribute)
		return links

	def addForeignUse(self, relation, index, foreign_relation, foreign_attribute, n = 1):
		"""Marks a forigen key as used in one place.

		Example Input: addForeignUse(relation, index, foreign_relation, foreign_attribute)
		"""

		self.forigenKeys_used[foreign_relation][foreign_attribute][index][relation] += n

	def subtractForeignUse(self, relation = None, index = None, foreign_relation = None, foreign_attribute = None, 
		exclude = None, n = 1, filterEmpty = True):
		"""Marks a forigen key as not used in one place.

		Example Input: subtractForeignUse(relation, index, foreign_relation, foreign_attribute)
		"""

		exclude = self.ensure_container(exclude)

		removeList = []
		for _relation in self.yieldKey(foreign_relation, self.forigenKeys_used, exclude = exclude):
			for _attribute in self.yieldKey(foreign_attribute, self.forigenKeys_used[_relation]):
				for _index in self.yieldKey(index, self.forigenKeys_used[_relation][_attribute]):
					for _user in self.yieldKey(relation, self.forigenKeys_used[_relation][_attribute][_index]):
						if (n is None):
							removeList.append((_relation, _attribute, _index, _user))
						else:
							self.forigenKeys_used[_relation][_attribute][_index][_user] -= n
							if (filterEmpty and (self.forigenKeys_used[_relation][_attribute][_index][_user] <= 0)):
								removeList.append((_relation, _attribute, _index, _user))

		for _relation, _attribute, _index, _user in removeList:
			del self.forigenKeys_used[_relation][_attribute][_index][_user]
			if (not self.forigenKeys_used[_relation][_attribute][_index]):
				del self.forigenKeys_used[_relation][_attribute][_index]
				if (not self.forigenKeys_used[_relation][_attribute]):
					del self.forigenKeys_used[_relation][_attribute]
					if (not self.forigenKeys_used[_relation]):
						del self.forigenKeys_used[_relation]

	def updateForeignUses(self, exclude = None, updateSchema = True):
		"""Updates how many places each foreign key is used.

		Example Input: updateForeignUses()
		"""

		exclude = self.ensure_container(exclude)
	
		def yieldCommand():
			nonlocal self, exclude

			for relation in self.getRelationNames(exclude):
				if (relation not in self.foreignKeys_catalogue):
					continue
				for attribute in self.foreignKeys_catalogue[relation]:
					foreign_relation, foreign_attribute = self.foreignKeys_catalogue[relation][attribute]
					yield (f"SELECT {f'[{relation}].[{attribute}]'} FROM {f'[{relation}]'}", (relation, attribute, foreign_relation, foreign_attribute))

		###############################

		#Setup
		if (updateSchema):
			self.updateInternalforeignSchemas()

		self.forigenKeys_used.clear()
		for command, (relation, attribute, foreign_relation, foreign_attribute) in yieldCommand():
			for index in self.executeCommand(command):
				self.addForeignUse(relation, index[0], foreign_relation, foreign_attribute)
		
	def getForeignUses(self, relation = None, attribute = None, index = None, user = None, 
		updateForeign = False, updateSchema = False, showVariable = False, filterEmpty = True,
		filterRelation = True, filterAttribute = True, filterIndex = True, filterUser = True,
		excludeRelation = None, excludeAttribute = None, excludeIndex = None, excludeUser = None):
		"""Returns how many times the given forigen key entry is used.

		relation (str) - Which foreign relation to look for
			- If None: Will look for all foreign relations

		attribute (str) - Which foreign attribute to look for
			- If None: Will look for all foreign attributes

		index (int) - Which row id to look for
			- If None: Will return a sum of all uses per index

		user (str) - Which relation to look for
			- If None: Will return a sum of all uses per user

		Example Input: getForeignUses()
		Example Input: getForeignUses("Names")
		Example Input: getForeignUses("Names", "first_name")
		Example Input: getForeignUses("Names", "first_name", 3)
		Example Input: getForeignUses("Names", "first_name", 3, "Users")
		
		Example Input: getForeignUses(attribute = "first_name")
		"""

		excludeUser = self.ensure_container(excludeUser)
		excludeIndex = self.ensure_container(excludeIndex)
		excludeRelation = self.ensure_container(excludeRelation)
		excludeAttribute = self.ensure_container(excludeAttribute)

		if (showVariable and filterIndex):
			showVariable = False

		if (isinstance(index, (int))):
			def yieldIndex(*args):
				nonlocal index
				yield index

		elif (isinstance(index, (str, float))):
			def yieldIndex(_relation, _attribute):
				"""Allows the index to be the value instead of the id."""
				nonlocal self, index

				if (not index):
					yield index
					return
				_index = self.getPrimaryKey(_relation)
				command = f"SELECT {_index} FROM [{_relation}] WHERE ({_attribute} = ?)"
				result = self.executeCommand(command, index)
				for item in result:
					yield item[0]
		else:
			def yieldIndex(_relation, _attribute):
				"""Allows the index to be a list of values instead of the id."""
				nonlocal self, index

				if (not index):
					yield index
					return

				for _index in index:
					if (isinstance(_index, int)):
						yield _index
						continue

					_index = self.getPrimaryKey(_relation)
					command = f"SELECT {_index} FROM [{_relation}] WHERE ({_attribute} = ?)"
					result = self.executeCommand(command, _index)
					for item in result:
						yield item[0]

		def yieldUses(sumOnly = False):
			nonlocal self, showVariable

			if (sumOnly):
				for _relation in self.yieldKey(relation, self.forigenKeys_used, exclude = excludeRelation):
					for _attribute in self.yieldKey(attribute, self.forigenKeys_used[_relation], exclude = excludeAttribute):
						for _index in self.yieldKey(yieldIndex(_relation, _attribute), self.forigenKeys_used[_relation][_attribute], exclude = excludeIndex):
							for _user in self.yieldKey(user, self.forigenKeys_used[_relation][_attribute][_index], exclude = excludeUser):
								yield self.forigenKeys_used[_relation][_attribute][_index][_user]
				return

			if (showVariable):
				for _relation in self.yieldKey(relation, self.forigenKeys_used, exclude = excludeRelation):
					for _attribute in self.yieldKey(attribute, self.forigenKeys_used[_relation], exclude = excludeAttribute):
						for _index in self.yieldKey(yieldIndex(_relation, _attribute), self.forigenKeys_used[_relation][_attribute], exclude = excludeIndex):
							for _user in self.yieldKey(user, self.forigenKeys_used[_relation][_attribute][_index], exclude = excludeUser):
								command = f"SELECT [{_relation}].[{_attribute}] FROM [{_relation}] WHERE ({self.getPrimaryKey(_relation)} = {_index})"
								variable = self.executeCommand(command, filterTuple = True)
								if (variable):
									yield (_relation, _attribute, variable[0], _user, self.forigenKeys_used[_relation][_attribute][_index][_user])
				return

			for _relation in self.yieldKey(relation, self.forigenKeys_used, exclude = excludeRelation):
				for _attribute in self.yieldKey(attribute, self.forigenKeys_used[_relation], exclude = excludeAttribute):
					for _index in self.yieldKey(yieldIndex(_relation, _attribute), self.forigenKeys_used[_relation][_attribute], exclude = excludeIndex):
						for _user in self.yieldKey(user, self.forigenKeys_used[_relation][_attribute][_index], exclude = excludeUser):
							yield (_relation, _attribute, _index, _user, self.forigenKeys_used[_relation][_attribute][_index][_user])

		def nestedFactory():
			return collections.defaultdict(nestedFactory)

		if (not filterEmpty):
			def formatDict(catalogue):
				for key, value in catalogue.items():
					if (isinstance(value, dict)):
						value = formatDict(value)
					catalogue[key] = value
				return dict(catalogue)
		else:
			def formatDict(catalogue):
				removeList = set()
				for key, value in catalogue.items():
					if (isinstance(value, dict)):
						value = formatDict(value)
					
					if (not value):
						removeList.add(key)
						continue
					
					catalogue[key] = value

				for key in removeList:
					del catalogue[key]

				return dict(catalogue)

		###############################################

		if (updateSchema):
			self.updateInternalforeignSchemas()

		if (updateForeign):
			self.updateForeignUses(updateSchema = False)

		if (all((filterRelation, filterAttribute, filterIndex, filterUser))):
			return sum(yieldUses(sumOnly = True))

		nestList = []
		if (not filterUser):
			nestList.append('_user')
		if (not filterRelation):
			nestList.append('_relation')
		if (not filterAttribute):
			nestList.append('_attribute')
		if (not filterIndex):
			nestList.append('_index')

		if (len(nestList) is 1):
			uses = {}
			variable = nestList[0]
			for _relation, _attribute, _index, _user, n in yieldUses():
				key = locals()[variable]
				if (key not in uses):
					uses[key] = 0
				uses[key] += n
			return formatDict(uses)

		uses = nestedFactory()
		for _relation, _attribute, _index, _user, n in yieldUses():
			catalogue = uses
			for variable in nestList[:-1]:
				catalogue = catalogue[locals()[variable]]

			key = locals()[nestList[-1]]
			if (key not in catalogue):
				catalogue[key] = 0
			catalogue[key] += n

		return formatDict(uses)

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def cleanForeignKeys(self, cleanList = None, exclude = None, filterType = True, applyChanges = None):
		"""Removes unused foreign keys from foreign relations (tables) not in the provided exclude list.
		Special thanks to Alex Martelli for removing duplicates quickly from a list on https://www.peterbe.com/plog/uniqifiers-benchmark

		cleanList (list)  - A list of which relations to clean unused tuples from
			- If None: All tables will be evaluated
		exclude (list)    - A list of which relations to excude from the cleaning process
		filterType (bool) - Determines if value type matters in comparing
			- If True: Numbers and numbers as strings count as the same thing
			- If False: Numbers and numbers as strings are different things
		applyChanges (bool)  - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used

		Example Input: cleanForeignKeys()
		Example Input: cleanForeignKeys(['Lorem', 'Ipsum'])
		"""

		exclude = self.ensure_container(exclude)

		#Make sure the internal schema is up to date
		self.updateInternalforeignSchemas()

		#Get a values
		if (cleanList is None):
			cleanList = self.getRelationNames(exclude)
		else:
			cleanList = [item for item in cleanList if (item not in exclude)]

		jhkhkj
		usedKeys = self.getForeignUses(myTuple = {item: None for item in cleanList}, updateSchema = False, filterRelation = False, filterAttribute = False)

		#Determine which keys to remove
		removeKeys = {}
		for foreign_relation, item in usedKeys.items():
			index = self.getPrimaryKey(foreign_relation)
			for foreign_attribute, used in item.items():
				contents = self.getValue({foreign_relation: index}, checkForeign = False)

				for key, valueList in contents.items():
					if (filterType):
						removeList = [value for value in valueList if (f"{value}" not in (f"{item}" for item in used))]
					else:
						removeList = [value for value in valueList if (value not in used)]

					if (removeList):
						if (foreign_relation not in removeKeys):
							removeKeys[foreign_relation] = {}
						if (index not in removeKeys[foreign_relation]):
							removeKeys[foreign_relation][index] = []

						removeKeys[foreign_relation][index].extend(removeList)

		#Delete unused keys
		self.removeTuple(removeKeys, nextToCondition = False)

		#Return number of keys removed
		n = 0
		for key, value in removeKeys.items():
			for subKey, subValue in value.items():
				n += len(valueList)

		#Save Changes
		if (applyChanges is None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

		return n

	@wrap_errorCheck()
	@wrap_connectionCheck()
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


		if (self.isAccess()):
			errorMessage = "The ODBC driver for MS Access does not support adding triggers"
			raise KeyError(errorMessage)

		#Setup
		valueList = []
		command = "CREATE TRIGGER "
		if (noReplication is not None):
			command += "IF NOT EXISTS "
		else:
			self.removeTrigger(label)
		command += "[{}] ".format(label)

		#Ensure correct format
		event = event.lower()
		reaction = reaction.lower()
		event_when = event_when.lower()

		#Account for reaction specific events
		if (reaction[0] == "l"):
			event_when = "after"
			if (event[0] != "u"):
				event = "update"
				warnings.warn(f"the reaction {reaction} needs 'event' to be 'update'", Warning, stacklevel = 2)
		
		elif (reaction[0] == "l"):
			event_when = "after"
			if (event[0] != "i"):
				event = "insert"
				warnings.warn(f"the reaction {reaction} needs 'event' to be 'insert'", Warning, stacklevel = 2)
	
		#Create Condition
		if (event_when[0] == "b"):
			command += "BEFORE "
		elif (event_when[0] == "a"):
			command += "AFTER "
		else:
			command += "INSTEAD OF "
	
		if (event[0] == "u"):
			command += "UPDATE "
		elif (event[0] == "i"):
			command += "INSERT "
		else:
			command += "DELETE "

		if (event_attribute is not None):
			command += "OF [{}] ".format(event_attribute)
		
		if (event_relation is None):
			event_relation = relation
		command += "ON [{}] FOR EACH ROW ".format(event_relation)

		# if (reaction_when is not None):
		# 	condition = "WHEN "

		# 	#Apply Condition
		# 	command += condition

		#Create Reation
		if (reaction_relation is None):
			reaction_relation = relation
		
		if (reaction[0] == "l"):
			if (reaction_attribute is None):
				if ("lastModified" not in self.getAttributeNames(reaction_relation)):
					self.addAttribute(reaction_relation, "lastModified", dataType = str, default = "strftime('%m/%d/%Y %H:%M:%S:%s','now', 'localtime')")
				reaction_attribute = "lastModified"

			reaction = "UPDATE [{}] SET [{}] = strftime('%m/%d/%Y %H:%M:%S:%s','now', 'localtime') WHERE (rowid = new.rowid);".format(reaction_relation, reaction_attribute)
		
		elif (reaction[0] == "c"):
			if (reaction_attribute is None):
				if ("createdOn" not in self.getAttributeNames(reaction_relation)):
					self.addAttribute(reaction_relation, "createdOn", dataType = str, default = "strftime('%m/%d/%Y %H:%M:%S:%s','now', 'localtime')")
				reaction_attribute = "createdOn"

			reaction = "UPDATE [{}] SET [{}] = strftime('%m/%d/%Y %H:%M:%S:%s','now', 'localtime') WHERE (rowid = new.rowid);".format(reaction_relation, reaction_attribute)
		
		else:
			errorMessage = f"Unknown reaction {reaction} in createTrigger() for {self.__repr__()}"
			raise KeyError(errorMessage)

		#Apply Reaction
		command += f"\nBEGIN \n{reaction} \nEND;"

		#Execute SQL
		self.executeCommand(command)

		#Save Changes
		if (applyChanges is None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getTrigger(self, label = None, exclude = None):
		"""Returns an event trigger.

		label (str) - What the trigger will be called in the .db
			- If None: Will return the names of all triggers

		Example Input: getTrigger()
		Example Input: getTrigger("Users_lastModified")
		"""

		exclude = self.ensure_container(exclude)

		if (self.isAccess()):
			errorMessage = "The ODBC driver for MS Access does not support getting triggers"
			raise KeyError(errorMessage)

		triggerList = self.executeCommand("SELECT name FROM sqlite_master WHERE type = 'trigger'")
		triggerList = [trigger[0] for trigger in triggerList if trigger[0] not in exclude]

		if (label is not None):
			if (label not in triggerList):
				return
			else:
				return triggerList[triggerList.index(label)]
		return triggerList

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def removeTrigger(self, label = None, applyChanges = None):
		"""Removes an event trigger.

		label (str) - What the trigger will be called in the .db
			- If None: Will remove all triggers
		applyChanges (bool)  - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used

		Example Input: removeTrigger("Users_lastModified")
		"""

		if (self.isAccess()):
			errorMessage = "The ODBC driver for MS Access does not support removing triggers"
			raise KeyError(errorMessage)

		triggerList = self.getTrigger(label)
		if (triggerList is not None):
			if (not isinstance(triggerList, (list, tuple, range))):
				triggerList = [triggerList]

			for trigger in triggerList:
				#Execute SQL
				self.executeCommand("DROP TRIGGER IF EXISTS [{}]".format(trigger))

			#Save Changes
			if (applyChanges is None):
				applyChanges = self.defaultCommit

			if (applyChanges):
				self.saveDatabase()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def createIndex(self, relation, attribute, noReplication = None):
		"""Creates an index for the given attribute."""

		if (not isinstance(attribute, (list, tuple, set, range, types.GeneratorType))):
			attribute = [attribute]

		command = f"CREATE INDEX{['', ' IF NOT EXISTS'][noReplication]} {relation}_{attribute} ON [{relation}] ({', '.join(attribute)})"
		print("@createIndex", command)
		self.executeCommand(command)

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def removeIndex(self, relation, attribute, noReplication = None):
		"""Removes an index for the given attribute."""

		if (not isinstance(attribute, (list, tuple, set, range, types.GeneratorType))):
			attribute = [attribute]

		command = f"DROP INDEX{['', ' IF EXISTS'][noReplication]} [{relation}].{relation}_{attribute}"

def quiet(*args):
	pass
	print(*args)

def test_sqlite():
	quiet("sqlite3")
	#Create the database
	database_API = build()
	database_API.openDatabase("test.db")#, applyChanges = False)

	try:
		#Create Tables
		database_API.removeRelation()
		database_API.createRelation("Names", [{"first_name": str}, {"extra_data": str}], unique = {"first_name": True})
		database_API.createRelation("Address", {"street": str}, unique = {"street": True})
		database_API.createRelation("Users", {"age": int, "height": int}, foreign = {"name": {"Names": "first_name"}, "address": {"Address": "street"}})
		database_API.createRelation("Other Users", "Users")

		# database_API.createIndex("Users", "age")

		#Add Items
		database_API.addTuple({"Names": {"first_name": "Dolor", "extra_data": "Sit"}}, unique = None)
		
		database_API.addTuple({"Users": {"name": "Ipsum", "age": 26, "height": 5}}, unique = None)
		database_API.addTuple({"Users": {"name": "Lorem", "age": 26, "height": 6}}, unique = None)
		database_API.addTuple({"Users": {"name": "Lorem", "age": 24, "height": 3}}, unique = None)
		database_API.addTuple({"Users": {"name": "Dolor", "age": 21, "height": 4}}, unique = None)
		database_API.addTuple({"Users": {"name": "Sit", "age": None, "height": 1}}, unique = None)
		database_API.removeTuple({"Users": {"name": "Sit"}})
		database_API.addTuple({"Users": {"name": "Sit", "age": None, "height": 1}}, unique = None)

		database_API.addTuple({"Other Users": {"name": "Sit", "age": None, "height": 1}}, unique = None)

		#Simple Actions
		quiet("Simple Actions")
		quiet(database_API.getValue("Users"))
		quiet(database_API.getValue({"Users": "name"}))
		quiet(database_API.getValue({"Users": "name"}, checkForeign = False))
		quiet(database_API.getValue([({"Users": "name"}, {"age": 24}), ({"Users": "height"}, {"age": 26})]))

		quiet(database_API.getValue({"Users": ["name", "age"]}))
		quiet(database_API.getValue({"Users": ["name", "age"]}, maximum = "age"))
		quiet(database_API.getValue({"Users": ["name", "age"]}, minimum = "age"))
		quiet(database_API.getValue({"Users": "age"}, average = True))
		quiet(database_API.getValue({"Users": "age"}, summation = True))
		quiet(database_API.getValue({"Users": ["name", "age"]}, attributeFirst = False, rowsAsList = True))
		quiet(database_API.getValue({"Users": ["name", "age"]}, attributeFirst = False, alias = {"age": "login time"}))
		quiet(database_API.getValue({"Users": ["name", "age"]}, attributeFirst = False, formatValue = lambda value, *args: f"-- {value} --"))
		quiet(database_API.getValue({"Users": ["name", "age"]}, attributeFirst = False, formatValue = {"age": lambda value, *args: value if (value is None) else value * 2}))
		quiet(database_API.getValue({"Other Users": "name"}))
	
		quiet(database_API.getValue({"Users": "name"}, forceRelation = True, forceAttribute = True, forceTuple = True))
		quiet(database_API.getValue({"Users": "name"}, forceRelation = True, forceAttribute = True))
		quiet(database_API.getValue({"Users": "name"}, forceRelation = True))

		quiet(database_API.getValue({"Users": "name"}, {"name": "Lorem"}))
		quiet(database_API.getValue({"Users": "name"}, {"name": "Ipsum"}))
		quiet(database_API.getValue({"Users": "name"}, {"name": "Amet"}))
		quiet()

		#Ordering Data
		quiet("Ordering Data")
		quiet(database_API.getValue({"Users": "name"}, orderBy = "age"))
		quiet(database_API.getValue({"Users": "name"}, orderBy = "name"))
		quiet(database_API.getValue({"Users": ["name", "age"]}, orderBy = "age", limit = 2))
		quiet(database_API.getValue({"Users": ["name", "age"]}, orderBy = "age", limit = 2, direction = True))
		quiet(database_API.getValue({"Users": ["name", "age"]}, orderBy = "age", limit = 2, direction = False))

		quiet(database_API.getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"]))
		quiet(database_API.getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"], direction = {"height": False}))

		quiet(database_API.getValue({"Users": "name", "Names": "first_name"}))
		quiet(database_API.getValue({"Users": "name", "Names": ["first_name", "extra_data"]}))
		quiet()

		#Changing Attributes
		quiet("Changing Attributes")
		quiet(database_API.getValue({"Users": ["name", "age"]}, rowsAsList = True, attributeFirst = False))
		database_API.changeTuple({"Users": "name"}, {"age": 26}, "Ipsum")
		quiet(database_API.getValue({"Users": ["name", "age"]}, rowsAsList = True, attributeFirst = False))
		database_API.changeTuple({"Users": {"name": "Amet", "address": 123, "height": 1}}, {"name": "Sit"})
		quiet(database_API.getValue({"Other Users": "name"}, rowsAsList = True, attributeFirst = False))
		quiet(database_API.getValue({"Users": "name"}, rowsAsList = True, attributeFirst = False))
		database_API.changeTuple({"Users": "name"}, {"age": 27}, "Consectetur", forceMatch = True)
		quiet(database_API.getValue({"Users": ["name", "age"]}, rowsAsList = True, attributeFirst = False))
		quiet()


		#Triggers
		quiet("Triggers")
		database_API.createTrigger("Users_lastModified", "Users", reaction = "lastModified")
		quiet(database_API.getTrigger())
		quiet(database_API.getValue({"Users": ["name", "age", "lastModified"]}, {"age": 26}))
		time.sleep(1)
		database_API.changeTuple({"Users": "name"}, {"age": 26}, "Lorem")#, forceMatch = True)
		quiet(database_API.getValue({"Users": ["name", "age", "lastModified"]}, {"age": 26}))
		quiet()

		#Etc
		quiet("Etc")
		quiet(database_API.getValue({"Users": "name"}, forceRelation = True))
		quiet(database_API.getValue({"Other Users": "name"}, forceRelation = True))
		quiet(database_API.getForeignUses("Names", "first_name", filterIndex = False, filterUser = False, showVariable = True))
		quiet(database_API.getForeignUses("Names", "first_name"))
		quiet(database_API.getForeignUses("Names", "first_name", 3, "Users"))
		quiet(database_API.getForeignUses("Names", "first_name", "Sit", filterUser = False))
		quiet(database_API.getForeignUses("Names", "first_name", filterIndex = False))
		quiet(database_API.getForeignUses("Names", "first_name", filterRelation = False, filterAttribute = False))

	finally:
		database_API.saveDatabase()

def test_access():
	print("\n\naccess")
	#Create the database
	database_API = build()
	database_API.openDatabase("H:/Python/modules/API_Database/test.accdb", applyChanges = False)

	database_API.removeRelation()

	#Create tables from the bottom up
	# database_API.createRelation("Names", [{"first_name": str}, {"extra_data": str}], unique = {"first_name": True})
	# database_API.createRelation("Address", {"street": str}, unique = {"street": True})
	# database_API.saveDatabase()

	# database_API.addTuple({"Names": {"first_name": "Lorem", "extra_data": 4}}, unique = None)
	# database_API.addTuple({"Names": {"first_name": "Ipsum", "extra_data": 7}}, unique = None)
	# database_API.addTuple({"Names": {"first_name": "Dolor", "extra_data": 3}}, unique = None)
	# database_API.addTuple({"Names": {"first_name": "Sit",   "extra_data": 1}}, unique = None)
	# database_API.addTuple({"Names": {"first_name": "Amet",  "extra_data": 10}}, unique = None)
	
	#Simple Actions
	print("Simple Actions")
	print(database_API.getValue({"Names": "first_name"}))
	# print(database_API.getValue({"Names": "first_name"}, filterRelation = False))
	# print(database_API.getValue({"Names": ["first_name", "extra_data"]}))
	# print()

	# #Ordering Data
	# print("Ordering Data")
	# print(database_API.getValue({"Names": "first_name"}, orderBy = "first_name"))
	# print(database_API.getValue({"Names": ["first_name", "extra_data"]}, orderBy = "extra_data", limit = 2))
	# print(database_API.getValue({"Names": ["first_name", "extra_data"]}, orderBy = "extra_data", direction = True))
	# print()

	# #Changing Attributes
	# print("Changing Attributes")
	# print(database_API.getValue({"Names": "first_name"}))
	# database_API.changeTuple({"Names": "first_name"}, {"first_name": "Lorem"}, "Consectetur")
	# print(database_API.getValue({"Names": "first_name"}))
	# database_API.changeTuple({"Names": "first_name"}, {"first_name": "Adipiscing"}, "Elit", forceMatch = True)
	# print(database_API.getValue({"Names": "first_name"}))
	# print()

	# database_API.saveDatabase()

def main():
	"""The main program controller."""

	test_sqlite()
	# test_access()

	# filePath = "R:\\Material Log - Database\\Users\\Josh Mayberry\\User Database.mdb"
	# with build(filePath, resultError_replacement = "!!! Import Error !!!") as myImportDatabase:
	# 	try:
	# 		importCatalogue = myImportDatabase.getAllValues("tblMaterialLog", rowsAsList = True, forceRelation = True, forceAttribute = True, forceTuple = True, attributeFirst = False)
	# 	except Exception as error:
	# 		myImportDatabase.closeDatabase()
	# 		raise error

	# for key, value in importCatalogue.items():
	# 	for row in value:
	# 		print(row, "\n")



if __name__ == '__main__':
	main()
