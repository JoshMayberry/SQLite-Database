__version__ = "3.4.0"

## TO DO ##
# - Add a foreign key cleanup command; removes unused foreign keys in foreign tables

import re
import sys
import time
import types
import pyodbc
import sqlite3
import sqlalchemy
import sqlalchemy.ext.declarative
import warnings
import traceback
import functools
import itertools
import cachetools
import collections
import contextlib
import importlib

#For multi-threading
# import sqlalchemy
import threading
from forks.pypubsub.src.pubsub import pub as pubsub_pub #Use my own fork

#Required Modules
##py -m pip install
	# sqlite3
	# pyodbc
	# sqlalchemy

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

#Custom Types
class _set(set):
	def append(self, *args, **kwargs):
		return self.add(*args, **kwargs)

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

class Database():
	"""Used to create and interact with a database.
	To expand the functionality of this API, see: "https://www.sqlite.org/lang_select.html"
	"""

	def __init__(self, fileName = None, *args, **kwargs):
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
		self.sessionMaker = sqlalchemy.orm.sessionmaker()
		self.TableBase = sqlalchemy.ext.declarative.declarative_base()

		#Internal variables
		self.schema = None
		self.cursor = None
		self.waiting = False
		self.fileName = None
		self.defaultCommit = None
		self.connectionType = None
		self.defaultFileExtension = ".db"
		self.previousCommand = (None, None) #(command (str), valueList (tuple))
		self.resultError_replacement = None
		self.aliasError_replacement = None

		#Initialization functions
		if (fileName is not None):
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

	#Context Managers
	@contextlib.contextmanager
	def makeSession(self):
		"""Provides a transactional scope around a series of operations.
		Modified code from: https://docs.sqlalchemy.org/en/latest/orm/session_basics.html
		"""
		
		session = self.sessionMaker()
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
	def getAttributeNames(self, relation, exclude = None):
		"""Returns the names of all attributes (columns) in the given relation (table).

		relation (str) - The name of the relation
		exclude (list) - A list of which attributes to excude from the returned result

		Example Input: getAttributeNames("Users")
		Example Input: getAttributeNames("Users", exclude = ["age", "height"])
		"""

		exclude = self.ensure_container(exclude)
		inspector = sqlalchemy.inspect(self.engine)
		return tuple(catalogue["name"] for catalogue in inspector.get_columns(relation) if (catalogue["name"] not in exclude))

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

	# @cachetools.cached(attributeCache, key = hash_formatAttribute)#, lock = cacheLock)
	def formatAttribute(self, attribute, row = None, alias = None):
		"""Returns a formatted attribute.

		Example Input: formatValue(attribute, alias)
		"""

	def formatValue(self, *args, formatter = None, **kwargs):
		"""Returns a formatted value.

		Example Input: formatValue(value, attribute, relation)
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
			handle = locationFunction(sqlalchemy.and_(*yieldLocation()))
		else:
			handle = locationFunction(sqlalchemy.or_(*yieldLocation()))

		return handle

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
	def openDatabase(self, fileName = None, schemaPath = None, *, applyChanges = True, multiThread = False, connectionType = None, 
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

		if (self.isSQLite):
			self.engine = sqlalchemy.create_engine(f"sqlite:///{fileName}")
			sqlalchemy.event.listen(self.engine, 'connect', self._fk_pragma_on_connect)
		else:
			errorMessage = f"Unknown connection type {connectionType}"
			raise KeyError(errorMessage)

		self.sessionMaker.configure(bind = self.engine)
		# self.metadata = sqlalchemy.MetaData(bind = self.engine)
		self.loadSchema(schemaPath)

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
		"""loads in a schema from the given schemaPath.

		Example Input: loadSchema(schemaPath)
		"""

		self.schema = importlib.import_module(schemaPath)
		self.schema.Mapper.metadata.bind = self.engine
		self.metadata = self.schema.Mapper.metadata
		self.refresh()

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
					parent = getattr(self.schema, relation)
					for attributeDict in self.ensure_container(rows):
						handle = session.add(parent(**attributeDict))
		else:
			with self.makeConnection(asTransaction = True) as connection:
				for relation, rows in myTuple.items():
					table = self.metadata.tables[relation]
					for attributeDict in self.ensure_container(rows):
						connection.execute(table.insert(values = attributeDict))

	@wrap_errorCheck()
	def changeTuple(self, myTuple, nextTo, value = None, forceMatch = None, applyChanges = None, checkForeign = True, updateForeign = None, **locationKwargs):
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

		print("@changeTuple.1", myTuple, nextTo)

	@wrap_errorCheck()
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
		"""

	@wrap_errorCheck()
	def getValue(self, myTuple, nextTo = None, orderBy = None, limit = None, direction = None, nullFirst = None, alias = None, 
		returnNull = False, includeDuplicates = True, checkForeign = True, formatValue = None, valuesAsSet = False, count = False,
		maximum = None, minimum = None, average = None, summation = None, variableLength = True, variableLength_default = None,
		forceRelation = False, forceAttribute = False, forceTuple = False, attributeFirst = True, rowsAsList = False, 
		filterForeign = True, filterNone = False, exclude = None, forceMatch = None, fromSchema = True, **locationKwargs):
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

		startTime = time.perf_counter()

		if (fromSchema):
			contextmanager = self.makeSession()
		else:
			contextmanager = self.makeConnection(asTransaction = True)

		results_catalogue = {}
		with contextmanager as connection:
			for relation, attributeList in myTuple.items():
				if (fromSchema):
					schema = getattr(self.schema, relation)
					handle = connection.query(schema)
				else:
					table = self.metadata.tables[relation]
					handle = table.select()
					schema = table.columns

				selectAll = attributeList is None
				if (selectAll):
					attributeList = self.getAttributeNames(relation, exclude = exclude)
				else:
					exclude = self.ensure_container(exclude)
					attributeList = tuple(attribute for attribute in self.ensure_container(attributeList) if (attribute not in exclude))

				_orderBy = sqlalchemy.text(orderBy or self.getPrimaryKey(relation))
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
				handle = handle.order_by(_orderBy)

				if (not includeDuplicates):
					handle = handle.distinct()

				handle = self.configureLocation(handle, schema, fromSchema = fromSchema, nextTo = nextTo, **locationKwargs)

				if (limit is not None):
					handle = handle.limit(limit)

				if (fromSchema):
					if (count):
						results_catalogue[relation] = handle.count()
					else:
						results_catalogue[relation] = tuple(handle)
				else:
					if (count):
						handle = handle.count()
					results_catalogue[relation] = tuple(connection.execute(handle))

		print(f"@getValue.9", f"{time.perf_counter() - startTime:.6f}")
		return results_catalogue

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
	# database_API.openDatabase(None, "test_map")
	database_API.openDatabase("test_map_example.db", "test_map")
	database_API.removeRelation()
	database_API.createRelation()
	database_API.resetRelation()

	database_API.addTuple({"Containers": ({"label": "lorem", "weight_total": 123, "poNumber": 123456, "jobNumber": 1234}, {"label": "ipsum", "jobNumber": 1234})})
	print(database_API.getValue({"Containers": None}, {"weight_total": 123, "poNumber": 123456}))
	database_API.addTuple({"Containers": {"label": "dolor", "weight_total": 123, "poNumber": 123456}})
	print(database_API.getValue({"Containers": None}, {"weight_total": 123, "poNumber": 123456}))

	# database_API.changeTuple({"Containers": {"jobNumber": 5678}}, {"label": "lorem"})
	# print(database_API.getValue({"Containers": None}, {"weight_total": 123, "poNumber": 123456}))



	# from test_map import Address, Base, Person

	# # Base = sqlalchemy.ext.declarative.declarative_base()
	# engine = sqlalchemy.create_engine('sqlite:///sqlalchemy_example.db')
	# # Bind the engine to the metadata of the Base class so that the
	# # declaratives can be accessed through a DBSession instance
	# # Base.metadata.bind = engine
	 
	# DBSession = sqlalchemy.orm.sessionmaker(bind=engine)
	# # A DBSession() instance establishes all conversations with the database
	# # and represents a "staging zone" for all the objects loaded into the
	# # database session object. Any change made against the objects in the
	# # session won't be persisted into the database until you call
	# # session.commit(). If you're not happy about the changes, you can
	# # revert all of them back to the last commit by calling
	# # session.rollback()
	# session = DBSession()
	 
	# # Insert a Person in the person table
	# new_person = Person(name='new person')
	# session.add(new_person)
	# session.commit()
	 
	# # Insert an Address in the address table
	# new_address = Address(post_code='00000', person=new_person)
	# session.add(new_address)
	# session.commit()


	# DBSession.bind = engine
	# session = DBSession()
	# # Make a query to find all Persons in the database
	# print(session.query(Person).all())
	# # Return the first Person from all Persons in the database
	# person = session.query(Person).first()
	# print(person.name)
	# # Find all Address whose person field is pointing to the person object
	# print(session.query(Address).filter(Address.person == person).all())
	# # Retrieve one Address whose person field is point to the person object
	# print(session.query(Address).filter(Address.person == person).one())
	# address = session.query(Address).filter(Address.person == person).one()
	# print(address.post_code)

def main():
	"""The main program controller."""

	sandbox()

if __name__ == '__main__':
	main()
