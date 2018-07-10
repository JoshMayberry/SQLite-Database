__version__ = "3.2.0"

## TO DO ##
# - Add a foreign key cleanup command; removes unused foreign keys in foreign tables

import re
import time
import types
import pyodbc
import sqlite3
import warnings
import traceback
import functools

#For multi-threading
# import sqlalchemy
import threading

#Required Modules
##py -m pip install
	# sqlite3
	# pyodbc

threadLock = threading.RLock()

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
				self.order = [key for key in self.data.keys() if key != None]
			else:
				self.order = [key if key != None else "" for key in self.data.keys()]

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

			if (self.connection != None):
				answer = function(self, *args, **kwargs)
			else:
				warnings.warn("No database is open", Warning, stacklevel = 2)
				answer = None

			return answer
		return wrapper
	return decorator

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
					raise error

			return answer
		return wrapper
	return decorator

#Controllers
def build(*args, **kwargs):
	"""Starts the GUI making process."""

	return Database(*args, **kwargs)

class NULL():
	"""Used to get values correctly."""

	def __init__(self):
		pass

class Database():
	"""Used to create and interact with a database.
	To expand the functionality of this API, see: "https://www.sqlite.org/lang_select.html"
	"""

	def __init__(self, fileName = None, *args, **kwargs):
		"""Defines internal variables.
		A better way to handle multi-threading is here: http://code.activestate.com/recipes/526618/

		fileName (str) - If not None: Opens the provided database automatically

		Example Input: Database()
		Example Input: Database("emaildb")
		"""

		#Internal variables
		self.defaultFileExtension = ".db"
		self.connectionType = None
		self.connection = None
		self.cursor = None
		self.defaultCommit = None
		self.fileName = None
		self.previousCommand = (None, None, None) #(command (str), valueList (tuple), result (any))
		self.resultError_replacement = None

		self.foreignKeys_catalogue = {} #A dictionary of already found foreign keys. {relation: {attribute: [foreign_relation, foreign_attribute]}}

		#Initialization functions
		if (fileName != None):
			self.openDatabase(fileName = fileName, *args, **kwargs)

	def __repr__(self):
		representation = f"{type(self).__name__}(id = {id(self)})"
		return representation

	def __str__(self):
		output = f"{type(self).__name__}()\n-- id: {id(self)}\n"
		if (self.fileName != None):
			output += f"-- File Name: {self.fileName}\n"
		return output

	# def __len__(self):
	# 	return len(self[:])

	# def __contains__(self, key):
	# 	return self._get(key, returnExists = True)

	# def __iter__(self):
	# 	return Iterator(self.childCatalogue)

	# def __getitem__(self, key):
	# 	return self._get(key)

	# def __setitem__(self, key, value):
	# 	self.childCatalogue[key] = value

	# def __delitem__(self, key):
	# 	del self.childCatalogue[key]

	def __enter__(self):			
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		if (traceback != None):
			print(exc_type, exc_value)
			return False

	#Utility Functions
	def getType(self, pythonType):
		"""Translates a python data type into an SQL data type.
		These types are: INTEGER, TEXT, BLOB, REAL, and NUMERIC.
		https://sqlite.org/datatype3.html

		pythonType (type) - The data type to translate

		Example Input: getType(str)
		"""

		sqlType = None
		if (pythonType in ["TEXT", "INTEGER", "REAL"]):
			sqlType = pythonType

		elif (pythonType == str):
			sqlType = "TEXT"

		elif (pythonType == int):
			sqlType = "INTEGER"

		elif (pythonType == float):
			sqlType = "REAL"

		else:
			errorMessage = f"Add {pythonType} to getType()"
			raise KeyError(errorMessage)

		return sqlType

	def getDriverList(self, key = None):
		"""Returns a list of all drivers that can be accessed.

		Example Input: getDriverList()
		"""

		if (key != None):
			return [item for item in pyodbc.drivers() if (key in item)]
		return list(pyodbc.drivers())

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getFileName(self, includePath = True):
		"""Returns the name of the database.

		Example Input: getFileName()
		Example Input: getFileName(includePath = False)
		"""

		return self.fileName

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getRelationNames(self, exclude = [], include = [], excludeFunction = None, includeFunction = None):
		"""Returns the names of all relations (tables) in the database.

		exclude (list) - A list of which relations to excude from the returned result

		Example Input: getRelationNames()
		Example Input: getRelationNames(["Users", "Names"])
		"""

		if (exclude == None):
			exclude = []
		elif (not isinstance(exclude, (list, tuple, range, types.GeneratorType))):
			exclude = [exclude]

		if (include == None):
			include = []
		elif (not isinstance(include, (list, tuple, range, types.GeneratorType))):
			include = [include]

		if (excludeFunction == None):
			excludeFunction = lambda relation, myList: relation not in myList
		if (includeFunction == None):
			includeFunction = lambda relation, myList: relation in myList

		if (isinstance(self.cursor, sqlite3.Cursor)):
			exclude.append("sqlite_sequence")
			relationList = self.executeCommand("SELECT name FROM sqlite_master WHERE type = 'table'")
			relationList = [relation[0] for relation in relationList if (((len(exclude) == 0) or excludeFunction(relation[0], exclude)) and ((len(include) == 0) or includeFunction(relation[0], include)))]
		else:
			relationList = [table_info.table_name for tableType in ("TABLE", "ALIAS", "SYNONYM") for table_info in self.cursor.tables(tableType = tableType)]
			# relationList = [table_info.table_name for tableType in ("TABLE", "VIEW", "ALIAS", "SYNONYM") for table_info in self.cursor.tables(tableType = tableType)]
			# relationList = [table_info.table_name for tableType in ("TABLE", "VIEW", "SYSTEM TABLE", "ALIAS", "SYNONYM") for table_info in self.cursor.tables(tableType = tableType)]
			relationList = [relation for relation in relationList if (((len(exclude) == 0) or excludeFunction(relation, exclude)) and ((len(include) == 0) or includeFunction(relation, include)))]


		return relationList

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getAttributeNames(self, relation, exclude = []):
		"""Returns the names of all attributes (columns) in the given relation (table).

		relation (str) - The name of the relation
		exclude (list) - A list of which attributes to excude from the returned result

		Example Input: getAttributeNames("Users")
		Example Input: getAttributeNames("Users", exclude = ["age", "height"])
		"""

		if (isinstance(self.cursor, sqlite3.Cursor)):
			table_info = self.executeCommand("PRAGMA table_info([{}])".format(relation), valuesAsList = True)
			attributeList = [attribute[1] for attribute in table_info if attribute[1] not in exclude]
		else:
			attributeList = [item[3] for item in self.cursor.columns(table = relation) if (item[3] not in exclude)]

		return attributeList

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getAttributeDefaults(self, relation, attribute = None, exclude = []):
		"""Returns the defaults of the requested attribute (columns) in the given relation (table).

		relation (str) - The name of the relation
		attribute (str) - The name of the attribute to get the default for. Can be a list of attributes
			- If None: Will get the defaults for all attributes
		exclude (list) - A list of which attributes to excude from the returned result

		Example Input: getAttributeDefaults("Users")
		Example Input: getAttributeDefaults("Users", ["age", "height"])
		Example Input: getAttributeDefaults("Users", exclude = ["id"])
		"""

		if (not isinstance(exclude, (list, tuple, range))):
			exclude = [exclude]
		exclude = [str(item) for item in exclude]

		if (attribute != None):
			if (not isinstance(attribute, (list, tuple, range, ))):
				attribute = [attribute]
			attribute = [str(item) for item in attribute]

		defaults = self.getSchema(relation)["default"]

		if (attribute != None):
			for item in defaults:
				if (item not in attribute):
					exclude.append(item)

		for item in exclude:
			if (str(item) in defaults):
				del defaults[str(item)]

		return defaults


	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getTupleCount(self, relation):
		"""Returns the number of tuples (rows) in a relation (table).

		Example Input: getTupleCount("Users")
		"""

		count = self.executeCommand("SELECT COUNT(*) from [{}]".format(relation))[0][0]
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

			return re.findall(f"""(?:, |\()\[?((?#
				)(?<=\[)(?:[^,\[\]]+)|(?#      variable with brackets
				)(?<!\[)(?:[^,\[\]\s]+))\]?(?# variable without brackets
				)[^,\[\]]*?{state}""", raw_sql)

		################################################################
	
		#Setup
		data = {}
		data["schema"] = {}
		data["notNull"] = {}
		data["primary"] = {}
		data["autoIncrement"] = {}
		data["unsigned"] = {}
		data["unique"] = {}
		data["foreign"] = {}
		data["default"] = {}

		if (self.connectionType == "sqlite3"):
			#Get Schema Info
			table_info = self.executeCommand("PRAGMA table_info([{}])".format(relation), valuesAsList = True)

			foreign_key_list = self.executeCommand("PRAGMA foreign_key_list([{}])".format(relation), valuesAsList = True)
			foreign_key_list.reverse()

			raw_sql = self.executeCommand("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{}'".format(relation))

			if (len(raw_sql) == 0):
				errorMessage = f"There is no relation {relation} in the database for {self.__repr__()}"
				raise KeyError(errorMessage)
			raw_sql = raw_sql[0][0]

			autoIncrement_list = search(raw_sql, "AUTOINCREMENT")
			unsigned_list = search(raw_sql, "UNSIGNED")
			unique_list = search(raw_sql, "UNIQUE")

			#Keys
			for item in table_info:
				columnName, dataType, null, default, primaryKey = item[1], item[2], item[3], item[4], item[5]

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
				column        = item[7]
				attributeName = item[8]
				rows          = item[10]
				pages         = item[11]

				if (not non_unique):
					data["unique"][attributeName] = True

			for item in self.cursor.columns(table = relation):
				attributeName = item[3]
				typeName      = item[5]
				canBeNull     = item[9]
				columnSize    = item[6]
				default       = item[12]
				includesNull  = item[17]

				if (not canBeNull):
					data["notNull"][attributeName] = True
				data["default"][attributeName] = True

			if (self.connectionType != "access"):
				primary_key_list = self.cursor.primaryKeys(table = relation)
				foreign_key_list = self.cursor.foreignKey(relation)
				jkjkhkhjkkj
			
		return data

	def updateInternalforeignSchemas(self):
		"""Only remembers data from schema (1) is wanted and (2) that is tied to a foreign key.
		Special Thanks to Davoud Taghawi-Nejad for how to get a list of table names on https://stackoverflow.com/questions/305378/list-of-tables-db-schema-dump-etc-using-the-python-sqlite3-api
		"""

		if (self.connectionType == "access"):
			#ODBC Driver does not support Foreign Keys for MS Access
			self.foreignKeys_catalogue = {}
			return 

		#Get the table names
		relationList = self.getRelationNames()

		#Get the foreign schema for each relation
		for relation in relationList:
				
			if (self.connectionType != "sqlite3"):
				foreign_key_list = self.cursor.foreignKeys(table = relation)
				lkiuiulil
			elif (self.connectionType == "sqlite3"):
				foreign_schemaList = self.executeCommand("PRAGMA foreign_key_list([{}])".format(relation), valuesAsList = True)

			#Do not check for relations with no foreign keys in their schema
			if (len(foreign_schemaList) > 0):
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

	def findForeign(self, relation, attribute):
		"""Determines if and how a key is connected to a foreign table."""

		foreignKey = []
		if (relation in self.foreignKeys_catalogue):
			if (attribute in self.foreignKeys_catalogue[relation]):
				foreignKey = (self.foreignKeys_catalogue[relation][attribute])
		return foreignKey

	def insertForeign(self, relation, attribute, value, valueList, foreignNone = False):
		"""Adds a foreign key to the table if needed."""

		foreign_results = self.findForeign(relation, attribute)
		if (len(foreign_results) != 0):
			foreign_relation, foreign_attribute = foreign_results

			if (value == None):
				value = NULL()
			if ((isinstance(value, NULL)) and ((isinstance(foreignNone, dict) and (attribute not in foreignNone) and foreignNone[attribute]) or (not foreignNone))):
				valueList.append(value)
				return valueList

			self.addTuple(foreign_relation, myTuple = {foreign_attribute: value}, unique = None)

			foreign_id = self.getValue({foreign_relation: "id"}, {foreign_attribute: value}, filterRelation = True, returnNull = False)["id"]
			valueList.append(foreign_id[0])
		else:
			valueList.append(value)

		return valueList

	def changeForeign(self, relation, attribute, nextTo, value, valueList, forceMatch, updateForeign):
		"""Adds a foreign key to the table if needed.

		updateForeign (bool) - Determines what happens to existing foreign keys
			- If True: Foreign keys will be updated to the new value
			- If False: A new foreign tuple will be inserted
			- If None: A foreign key will be updated to the new value if only one item is linked to it, otherwise a new foreign tuple will be inserted
		"""

		#Determine if a foreign link exists
		foreign_results = self.findForeign(relation, attribute)
		if (len(foreign_results) != 0):
			foreign_relation, foreign_attribute = foreign_results

			#Determine if foreign key already exists
			foreign_id = self.getValue({foreign_relation: "id"}, {foreign_attribute: value}, filterRelation = True, returnNull = False)["id"]
			if (len(foreign_id) == 0):
				if (not forceMatch):
					errorMessage = f"There is no foreign key {foreign_attribute} with the value {value} in the relation {foreign_relation} for changeForeign()"
					raise KeyError(errorMessage)

				#Determine if current value already exists as a foreign key instead
				checkValue = self.getValue({relation: attribute}, nextTo = nextTo, returnNull = False)[attribute]#, returnForeign = False)[attribute]
				if (len(checkValue) == 0):
					if (not forceMatch):
						errorMessage = f"There is no key {attribute} with the nextTo {nextTo} in the relation {relation} for changeForeign()"
						raise KeyError(errorMessage)
					
					#Add a new foreign key
					updateForeign = False
				else:
					checkValue = checkValue[0]
					foreign_id = self.getValue({foreign_relation: "id"}, {foreign_attribute: checkValue}, filterRelation = True, returnNull = False)["id"]
					
					if (len(foreign_id) == 0):
						#Add a new foreign key
						updateForeign = False
			else:
				checkValue = value

			#Determine how to modify the foreign relation
			if (updateForeign == None):
				#Determine if the foreign key is used in other places
				command = "SELECT [{}] FROM [{}] WHERE [{}] = ?".format(attribute, relation, attribute)
				results = self.executeCommand(command, checkValue, valuesAsList = True)
				
				if (len(results) > 1):
					#Add a new foreign key
					updateForeign = False
				else:
					#Determine if the foreign key is used in other tables
					usedKeys = self.getForeignUses(attributeList = attribute, keepDuplicates = True, exclude = relation, updateSchema = False)
					if (len(usedKeys) != 0):
						#Add a new foreign key
						updateForeign = False
					else:
						#Update the existing foreign key
						updateForeign = True

			#Modify the foreign relation
			if (updateForeign):
				self.changeTuple({foreign_relation: foreign_attribute}, {"id": foreign_id[0]}, value)
			else:
				self.addTuple(foreign_relation, myTuple = {foreign_attribute: value}, unique = None)
				foreign_id = self.getValue({foreign_relation: "id"}, {foreign_attribute: value}, filterRelation = True, returnNull = False)["id"]

			#Apply foreign id in place of value
			valueList.append(foreign_id[0])
		else:
			valueList.append(value)

		return valueList

	def configureForeign(self, results, relation, attribute, filterTuple = True, filterForeign = False, valuesAsList = True, returnNull = False, returnForeign = True):
		"""Allows the user to use foreign keys.
		-		For more information on JOIN: https://www.techonthenet.com/sqlite/joins.php
		"""

		if (not returnForeign):
			return results

		foreign_results = self.findForeign(relation, attribute)
		if (len(foreign_results) != 0):
			foreign_relation, foreign_attribute = foreign_results

			valueList = []
			for value in results:
				if (value == None):
					if (returnNull):
						value = NULL()
					else:
						valueList.append(value)
						continue

				subResults = self.getValue({foreign_relation: foreign_attribute}, {"id": value}, nextToCondition = False, filterRelation = filterForeign, filterAttribute = True, returnNull = True)

				if (isinstance(subResults, dict) and len(subResults[foreign_relation]) != 0):
					subList = subResults[foreign_relation]
				elif(isinstance(subResults, (list, tuple)) and len(subResults) != 0):
					subList = subResults[0]
				else:
					subList = value

				if (returnNull):
					valueList.append(subList)
				else:
					if (isinstance(subList, (list, tuple))):
						valueList.append([item if not isinstance(item, NULL) else None for item in subList])
					else:
						valueList.append(subList if not isinstance(subList, NULL) else None)

			return valueList
		return results

	def configureLocation(self, relation, nextTo, valueList, nextToCondition = True, checkForeigen = True, like = {}, greaterThan = {}, lessThan = {}, greaterThanOrEqualTo = {}, lessThanOrEqualTo = {}, forceMatch = True):
		"""Sets up the location portion of the SQL message."""

		locationInfo = ""
		for i, (criteriaAttribute, item) in enumerate(nextTo.items()):
			if (not isinstance(item, (list, tuple))):
				item = [item]
			for j, criteriaValue in enumerate(item):
				#Account for multiple references
				if ((i != 0) or (j != 0)):
					if (nextToCondition):
						locationInfo += " AND "
					else:
						locationInfo += " OR "

				if (checkForeigen):
					foreign_results = self.findForeign(relation, criteriaAttribute)
					if (len(foreign_results) != 0):
						foreign_relation, foreign_attribute = foreign_results
						result = self.getValue({foreign_relation: "id"}, {foreign_attribute: criteriaValue})["id"]

						if (len(result) == 0):
							if (not forceMatch):
								errorMessage = f"There is no foreign key {foreign_attribute} with the value {criteriaValue} in the relation {foreign_relation} for configureLocation()"
								raise KeyError(errorMessage)
							self.addTuple(foreign_relation, myTuple = {foreign_attribute: criteriaValue}, unique = None)
							result = self.getValue({foreign_relation: "id"}, {foreign_attribute: criteriaValue})["id"]

						criteriaValue = result[0]

				if ((criteriaValue == None) or (isinstance(criteriaValue, NULL))):
					locationInfo += "[{}].[{}] is null or [{}].[{}] = ''".format(relation, criteriaAttribute, relation, criteriaAttribute)
				else:
					locationInfo += "[{}].[{}] ".format(relation, criteriaAttribute)

					if ((relation in like) and (criteriaAttribute in like[relation])):
						locationInfo += "LIKE "
					elif ((relation in greaterThan) and (criteriaAttribute in greaterThan[relation])):
						locationInfo += "> "
					elif ((relation in lessThan) and (criteriaAttribute in lessThan[relation])):
						locationInfo += "< "
					elif ((relation in greaterThanOrEqualTo) and (criteriaAttribute in greaterThanOrEqualTo[relation])):
						locationInfo += ">= "
					elif ((relation in lessThanOrEqualTo) and (criteriaAttribute in lessThanOrEqualTo[relation])):
						locationInfo += "<= "
					else:
						locationInfo += "= "
					locationInfo += "?"
					valueList.append(criteriaValue)

		return locationInfo, valueList

	def executeCommand(self, command, valueList = (), hackCheck = True, valuesAsList = None, filterTuple = False, printError_command = True):
		"""Executes an SQL command. Allows for multi-threading.
		Special thanks to Joaquin Sargiotto for how to lock threads on https://stackoverflow.com/questions/26629080/python-and-sqlite3-programmingerror-recursive-use-of-cursors-not-allowed

		command (str)     - The SQL command to run
		valueList (tuple) - The variables to replace any '?' with in 'command'
		hackCheck (bool)  - Checks commands for common hacking tricks before it is executed
			- If True: Checks for commented out portions, escaped characters, and extra commands such as TABLE and SELECT
			- If False: Does not check the string.
		valuesAsList (bool)    - Determines if the values returned should be a list or a tuple
			- If True: Returned values will be in a list
			- If False: Returned values will be in a tuple
			- If None: Returned values will be an sqlite3 object
		filterTuple (bool)     - Determines how the final result in the catalogue will be returned if there is only one column
			- If True: (value 1, value 2, value 3...)
			- If False: ((value 1, ), (value 2, ), (value 3. ),..)

		Example Input: executeCommand(command, value)
		Example Input: executeCommand(command, valueList)
		Example Input: executeCommand(command, [value] + valueList)
		Example Input: executeCommand(command, value, valuesAsList = valuesAsList, filterTuple = filterTuple)
		"""

		#Check for common hacking techniques
		## MAKE THIS MORE ROBUST ##
		if (hackCheck):
			#Check for comments
			if (("--" in command) or ("/*" in command)):
				errorMessage = f"Cannot comment out portions of the command: {command}"
				raise ValueError(errorMessage)

		#Ensure correct format
		if (not isinstance(valueList, tuple)):
			if (isinstance(valueList, list)):
				valueList = tuple(valueList)
			else:
				valueList = (valueList,)

		#Filter NULL placeholder
		valueList = [item if not isinstance(item, NULL) else None for item in valueList]
		valueList = tuple(valueList)

		#Run Command
		# print("@0.1", command, valueList)
		with threadLock:
			result = []
			try:
				resultCursor = self.cursor.execute(command, valueList)
				try:
					while True:
						try:
							item = resultCursor.fetchone()
							if (item == None):
								break
						except:
							item = (self.resultError_replacement,)
						result.append(item)
				except pyodbc.ProgrammingError:
					pass

			except Exception as error:
				if (printError_command):
					print(f"-- {command}, {valueList}")
				raise error

		# print("@0.2", result)

		#Configure results
		if (valuesAsList != None):
			result = list(result)

			if (filterTuple and (len(result) > 0) and (len(result[0]) == 1)):
				for i, item in enumerate(result):
					result[i] = item[0]

			if (not valuesAsList):
				result = tuple(result)

		self.previousCommand = (command, valueList, result)
		return result

	#Interaction Functions
	@wrap_errorCheck()
	def openDatabase(self, fileName = "myDatabase", *args, applyChanges = True, multiThread = False, connectionType = None, 
		password = None, readOnly = False, resultError_replacement = None):

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

		Example Input: openDatabase("emaildb")
		Example Input: openDatabase("emaildb.sqllite")
		Example Input: openDatabase("emaildb", applyChanges = False)
		Example Input: openDatabase("emaildb", multiThread = True)
		"""

		#Check for another open database
		if (self.connection != None):
			self.closeDatabase()

		#Check for file extension
		if ("." not in fileName):
			fileName += self.defaultFileExtension

		if (connectionType == None):
			if (fileName.endswith(("mdb", "accdb"))):
				connectionType = "access"
			else:
				connectionType = "sqlite3"

		#Configure Options
		self.defaultCommit = applyChanges
		self.connectionType = connectionType
		self.resultError_replacement = resultError_replacement

		if (self.resultError_replacement == None):
			self.resultError_replacement = "!!! SELECT ERROR !!!"

		#Establish connection
		if (connectionType == "sqlite3"):
			if (multiThread):
				#Temporary fix until I learn SQLAlchemy to do this right
				self.connection = sqlite3.connect(fileName, check_same_thread = False)
			else:
				self.connection = sqlite3.connect(fileName)
		elif (connectionType == "access"):
			driverList = self.getDriverList("Microsoft Access Driver")
			if (len(driverList) == 0):
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

		self.cursor = self.connection.cursor()

		#Update internal values
		self.fileName = fileName

		#Update internal foreign schema catalogue
		self.updateInternalforeignSchemas()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def closeDatabase(self):
		"""Closes the opened database.

		Example Input: closeDatabase()
		"""

		self.cursor.close()

		self.connection = None
		self.cursor = None
		self.fileName = None

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def saveDatabase(self):
		"""Saves the opened database.

		Example Input: saveDatabase()
		"""

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

		if (relation != None):
			#Ensure correct spaces format
			if (self.connectionType == "sqlite3"):
				command = "DROP TABLE IF EXISTS [{}]".format(relation)
			else:
				if (relation not in self.getRelationNames()):
					return

				command = "DROP TABLE [{}]".format(relation)
			self.executeCommand(command)

			#Save Changes
			if (applyChanges == None):
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
		if (applyChanges == None):
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
			if (applyChanges == None):
				applyChanges = self.defaultCommit

			if (applyChanges):
				self.saveDatabase()

			#Update internal foreign schema catalogue
			self.updateInternalforeignSchemas()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def setSchema(self, relation, schema = {}, notNull = {}, primary = {}, autoIncrement = {},
		unsigned = {}, unique = {}, default = {}, foreign = {}, applyChanges = None):
		"""Renames a relation (table) to the given name the user provides.

		relation (str)      - What the relation is called in the .db
		applyChanges (bool) - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used

		Example Input: setSchema("Users", foreign = {"name": {"Names": "first_name"}})
		Example Input: setSchema("Users", schema = {"counter": int})
		"""

		def applyChanges(old_thing, mod_thing):
			"""Applies user modifications to the table settings."""

			for new_key, new_value in mod_thing.items():
				old_thing[new_key] = new_value

			return old_thing

		#Get current data
		data = self.getSchema(relation)
		table_contents = self.getAllValues(relation, orderBy = "id", filterRelation = False, valuesAsList = True, valuesAsRows = None, checkForeigen = False)

		#Rename old table
		self.renameRelation(relation, "tempCopy_{}".format(relation))

		#Apply changes
		new_schema = applyChanges(data["schema"], schema)
		new_foreign = applyChanges(data["foreign"], foreign)
		new_notNull = applyChanges(data["notNull"], notNull)
		new_primary = applyChanges(data["primary"], primary)
		new_autoIncrement = applyChanges(data["autoIncrement"], autoIncrement)
		new_unsigned = applyChanges(data["unsigned"], unsigned)
		new_unique = applyChanges(data["unique"], unique)
		new_default = applyChanges(data["default"], default)

		#Create new table
		self.createRelation(relation, schema = new_schema, notNull = new_notNull, primary = new_primary, 
			autoIncrement = new_autoIncrement, unsigned = new_unsigned, unique = new_unique, foreign = new_foreign, 
			applyChanges = applyChanges, default = new_default, autoPrimary = False)

		#Populate new table with old values
		for i in range(len(table_contents[relation])):
			self.addTuple(relation, table_contents[relation][i], applyChanges = applyChanges, checkForeigen = False)
		
		#Remove renamed table
		self.removeRelation("tempCopy_{}".format(relation), applyChanges = applyChanges)

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def createRelation(self, relation, schema = {}, applyChanges = None, autoPrimary = True, 
		notNull = {}, primary = {}, autoIncrement = {}, unsigned = {}, unique = {}, default = {},
		foreign = None, noReplication = True):
		"""Adds a relation (table) to the database.
		Special thanks to Jimbo for help with spaces in database names on http://stackoverflow.com/questions/10920671/how-do-you-deal-with-blank-spaces-in-column-names-in-sql-server
		
		relation (str)      - What the relation will be called in the .db
		schema (dict)       - The relation schema. {attribute (str): data type (type)}
			If a dictionary with multiple elements is given, the order will be randomized
			If a list of one element dictionaries is given, the order will be the order of the list
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
		"""

		def formatSchema(schemaFormatted, item, autoPrimary_override):
			"""A sub-function that formats the schema for the user."""

			if ((len(default) != 0) and (item in default)):
				if (default[item] != None):
					schemaFormatted += " DEFAULT ({})".format(default[item])

			if ((len(notNull) != 0) or (autoPrimary_override)):
				if (item in notNull):
					if (notNull[item]):
						schemaFormatted += " NOT NULL"
				elif(autoPrimary_override):
					schemaFormatted += " NOT NULL"

			if ((len(primary) != 0) or (autoPrimary_override)):
				if (item in primary):
					if (primary[item]):
						schemaFormatted += " PRIMARY KEY"
				elif(autoPrimary_override):
					schemaFormatted += " PRIMARY KEY"
				
			if (self.connectionType == "sqlite3"):
				if ((len(autoIncrement) != 0) or (autoPrimary_override)):
					if (item in autoIncrement):
						if (autoIncrement[item]):
							schemaFormatted += " AUTOINCREMENT"
					elif(autoPrimary_override):
						schemaFormatted += " AUTOINCREMENT"
				
				# if (len(unsigned) != 0):
					# if (item in unsigned):
					# 	if (unsigned[item]):
					# 		schemaFormatted += " UNSIGNED"
					# elif(autoPrimary_override):
					# 	schemaFormatted += " UNSIGNED"
				
			if ((len(unique) != 0) or (autoPrimary_override)):
				if (item in unique):
					if (unique[item]):
						schemaFormatted += " UNIQUE"
				elif(autoPrimary_override):
					schemaFormatted += " UNIQUE"

			return schemaFormatted

		def addforeign(schemaFormatted, foreignList, schema):
			"""A sub-function that adds a foreign key for the user.
			More information at: http://www.sqlitetutorial.net/sqlite-foreign-key/
			"""

			#Parse foreign keys
			# schema_foreign = {} #
			for foreign in foreignList:
				for attribute, foreign_dict in foreign.items():
					#Skip items that will be added in as foreign keys
					for schema_item in schema:
						if ((schema_item != None) and (attribute in schema_item)):
							break
					else:

						if (type(foreign_dict) == dict):
							schemaFormatted += "[{}] INTEGER".format(attribute)
						else:
							schemaFormatted += "[{}] {}".format(attribute, self.getType(foreign_dict))

						schemaFormatted = formatSchema(schemaFormatted, attribute, False)

						if (schemaFormatted != ""):
							schemaFormatted += ", "

			#Link foreign keys
			for i, foreign in enumerate(foreignList):
				for attribute, foreign_dict in foreign.items():
					#Account for non-foreign keys
					if (type(foreign_dict) == dict):
						foreign_relation, foreign_attribute = list(foreign_dict.items())[0]
						schemaFormatted += "FOREIGN KEY ([{}]) REFERENCES [{}]([{}])".format(attribute, foreign_relation, foreign_attribute)

						#Account for multiple attributes
						if (schemaFormatted != ""):
							schemaFormatted += ", "

			#Remove trailing comma
			schemaFormatted = schemaFormatted[:-2]

			return schemaFormatted

		################################

		if (self.connectionType == "access"):
			if ((foreign != None) and (len(foreign) != 0)):
				errorMessage = "The ODBC driver for MS Access does not support foreign keys"
				raise KeyError(errorMessage)
			if ((primary != None) and (len(primary) != 0)):
				errorMessage = "The ODBC driver for MS Access does not support primary keys"
				raise KeyError(errorMessage)
			autoPrimary = False

		#Ensure correct format
		if (not isinstance(schema, (list, tuple))):
			schema = [schema]
		if (not isinstance(foreign, (list, tuple))):
			foreign = [foreign]

		#Build SQL command
		command = "CREATE TABLE "

		if ((noReplication != None) and (self.connectionType == "sqlite3")):
			command += "IF NOT EXISTS "

		else:
			self.removeRelation(relation)

		command += "[" + str(relation) + "]"

		#Format schema
		firstRun = True
		schemaFormatted = ""

		#Add primary key
		if (autoPrimary):
			schemaFormatted += "id INTEGER"
			schemaFormatted = formatSchema(schemaFormatted, "id", autoPrimary)

		#Add given attributes
		for schema_item in schema:
			for i, (attribute, dataType) in enumerate(schema_item.items()):
				if (schemaFormatted != ""):
					schemaFormatted += ", "
				schemaFormatted += "[{}] {}".format(attribute, self.getType(dataType))
				schemaFormatted = formatSchema(schemaFormatted, attribute, False)

		#Add foreign keys
		for foreign_item in foreign:
			if (foreign_item != None):
				#Account for primary key
				if (schemaFormatted != ""):
					schemaFormatted += ", "

				schemaFormatted = addforeign(schemaFormatted, [foreign_item], schema)

		#Execute SQL
		self.executeCommand(command + "({})".format(schemaFormatted))

		#Save Changes
		if (applyChanges == None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

		#Update internal foreign schema catalogue
		self.updateInternalforeignSchemas()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def addAttribute(self, relation, attribute, dataType = str, default = None, applyChanges = None):
		"""Adds an attribute (column) to a relation (table).

		relation (str)      - What the relation is called in the .db
		attribute (str)     - What the attribute will be called
		dataType (type)     - What type the attribute will be
		applyChanges (bool) - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used

		Example Input: addAttribute("Users", "date created", dataType = int)
		"""

		#Build SQL command
		command = "ALTER TABLE [{}] ADD COLUMN [{}] {} ".format(relation, attribute, self.getType(dataType))

		if (default != None):
			# command += "DEFAULT [{}]".format(default)
			command += "DEFAULT ({})".format(default)
			# command += "DEFAULT {}".format(default)

		#Execute SQL
		try:
			self.executeCommand(command, printError_command = False)
		except Exception as error:
			if (error.__str__() == "Cannot add a column with non-constant default"):
				self.setSchema(relation, schema = {attribute: self.getType(dataType)}, default = {attribute: default})
			else:
				print(f"-- {command}, []")
				raise error

		#Save Changes
		if (applyChanges == None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

		#Update internal foreign schema catalogue
		self.updateInternalforeignSchemas()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def addTuple(self, relation, myTuple = {}, applyChanges = None, autoPrimary = False, notNull = False, foreignNone = False,
		primary = False, autoIncrement = False, unsigned = True, unique = False, checkForeigen = True):
		"""Adds a tuple (row) to the given relation (table).
		Special thanks to DSM for how to check if a key exists in a list of dictionaries on http://stackoverflow.com/questions/14790980/how-can-i-check-if-key-exists-in-list-of-dicts-in-python
		Special thanks to Jimbo for help with spaces in database names on http://stackoverflow.com/questions/10920671/how-do-you-deal-with-blank-spaces-in-column-names-in-sql-server

		relation (str)      - What the relation is called in the .db
		myTuple (dict)      - What will be written to the tuple. {attribute: value}
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
		checkForeigen (bool) - Determines if foreign keys will be take in account
		foreignNone (bool)   - Determines what to do if an attribute with a foreign key will be None. Can be a dict of {attribute (str): state (bool)}
			- If True: Will place the None in the foreign key relation
			- If False: Will place the None in the domestic relation

		Example Input: addTuple("Lorem", autoPrimary = True)
		Example Input: addTuple("Lorem", {"Ipsum": "Dolor", "Sit": 5})
		Example Input: addTuple("Lorem", {"Ipsum": "Dolor", "Sit": 5}, unique = None)
		"""

		if (unique == None):
			#For the case of None, multiple items can be inserted even if the attribuite is 'unique' in the table's schema
			uniqueState = self.getSchema(relation)["unique"]
			for attribute, value in myTuple.items():
				if ((attribute in uniqueState) and (uniqueState[attribute]) and (isinstance(value, NULL))):
					existsCheck = self.getValue({relation: attribute}, {attribute: value})[attribute]
					if (len(existsCheck) != 0):
						return

		command = "INSERT "
		if (self.connectionType != "access"):
			if (unique != None):
				if (unique):
					command += "OR REPLACE "
			else:
				command += "OR IGNORE "
		else:
			if (unique in [True, None]):
				removeCatalogue = {} 
				for attribute, value in myTuple.items():
					existsCheck = self.getValue({relation: attribute}, {attribute: value})[attribute]
					if (len(existsCheck) != 0):
						removeCatalogue["attribute"] = existsCheck[0]

				for attribute, oldValue in removeCatalogue.items():
					if (unique):
						jkjhjkhjhk #There are no row ids, so find a way to ensure only the one row is changed?
						self.changeTuple({relation: attribute}, {attribute: oldValue}, myTuple[attribute], checkForeigen = checkForeigen)
					del myTuple[attribute]
				
				if (len(myTuple) == 0):
					return

		command += "INTO [{}] (".format(relation)

		#Build attribute side
		itemList = myTuple.items()
		valueList = []
		for i, (attribute, value) in enumerate(itemList):
			#Remember the associated value for the attribute
			if (checkForeigen):
				valueList = self.insertForeign(relation, attribute, value, valueList, foreignNone = foreignNone)
			else:
				valueList.append(value)
			command += "[{}]".format(attribute)

			#Account for multiple items
			if (i != len(itemList) - 1):
				command += ", "

		#Build value side
		command += ") VALUES ("
		for i, value in enumerate(valueList):
			command += "?"

			#Account for multiple items
			if (i != len(itemList) - 1):
				command += ", "

		command += ")"

		##Run SQL command
		self.executeCommand(command, valueList)

		#Save Changes
		if (applyChanges == None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def changeTuple(self, myTuple, nextTo, value, forceMatch = None, defaultValues = {}, applyChanges = None, checkForeigen = True, 
		updateForeign = None, exclude = [], nextToCondition = True, like = {}):
		"""Changes a tuple (row) for a given relation (table).
		Note: If multiple entries match the criteria, then all of those tuples will be chanegd.
		Special thanks to Jimbo for help with spaces in database names on http://stackoverflow.com/questions/10920671/how-do-you-deal-with-blank-spaces-in-column-names-in-sql-server

		myTuple (dict)   - What will be written to the tuple. {relation: attribute to change}
		nextTo (dict)    - An attribute-value pair that is in the same tuple. {attribute next to one to change: value of this attribute}
			- If more than one attribute is given, it will look for all cases
		value (any)      - What will be written to the tuple
		forceMatch (any) - Determines what will happen in the case where 'nextTo' is not found
			- If None: Do nothing
			- If not None: Create a new row that contains the default values

		nextToCondition (bool) - Determines how to handle multiple nextTo criteria
			- If True: All of the criteria given must match
			- If False: Any of the criteria given must match

		defaultValues (dict) - A catalogue of what defaults to give attributes. If no default is found, the attribute's value will be None
		applyChanges (bool)  - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used
		checkForeigen (bool) - Determines if foreign keys will be take in account
		updateForeign (bool) - Determines what happens to existing foreign keys
			- If True: Foreign keys will be updated to the new value
			- If False: A new foreign tuple will be inserted
			- If None: A foreign key will be updated to the new value if only one item is linked to it, otherwise a new foreign tuple will be inserted
		exclude (list)       - A list of tables to exclude from the 'updateForeign' check

		Example Input: changeTuple({"Users": "name"}, {"age": 26}, "Amet")
		"""

		if (value == None):
			value = NULL()
		elif (not isinstance(value, NULL)):
			value = f"{value}"

		#Account for multiple tuples to change
		for relation, attribute in myTuple.items():
			valueList = []
			if (checkForeigen):
				valueList = self.changeForeign(relation, attribute, nextTo, value, valueList, forceMatch, updateForeign)

			currentValue = self.getValue({relation: attribute}, nextTo, filterRelation = True)[attribute]
			if (len(currentValue) == 0):
				if (not forceMatch):
					errorMessage = f"There is no key {attribute} with the nextTo {nextTo} in the relation {relation}"
					raise KeyError(errorMessage)
				self.addTuple(relation, myTuple = {**nextTo, **{attribute: value}}, unique = None)
			else:
				locationInfo, valueList = self.configureLocation(relation, nextTo, valueList, nextToCondition, checkForeigen, like)

				command = "UPDATE [{}] SET [{}] = ? WHERE ({})".format(relation, attribute, locationInfo)
				self.executeCommand(command, valueList)
			
			if (applyChanges == None):
				applyChanges = self.defaultCommit
			if (applyChanges):
				self.saveDatabase()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def removeTuple(self, myTuple, like = {}, applyChanges = None,
		checkForeigen = True, updateForeign = True, exclude = [], nextToCondition = True):
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
		checkForeigen (bool) - Determines if foreign keys will be take in account
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
			valueList = []
			locationInfo, valueList = self.configureLocation(relation, nextTo, valueList, nextToCondition, checkForeigen, like)
			command = "DELETE FROM [{}] WHERE ({})".format(relation, locationInfo)
			self.executeCommand(command, valueList)

		#Save Changes
		if (applyChanges == None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getAllValues(self, relation, exclude = [], **kwargs):
		"""Returns all values in the given relation (table) that match the filter conditions.

		relation (str) - Which relation to look in
			- If a list is given, it will look in each table. 
		exclude (list) - A list of which tables to excude from the returned result
			- If multiple tables are required, provide a dictionary for the tabel elements. {table 1: [attribute 1, attribute 2], table 2: attribute 3}
			- If a list or single value is given, it will apply to all tables given

		Example Input: getAllValues("Users")
		Example Input: getAllValues("Users", orderBy = ["age"])
		
		Example Input: getAllValues(["Users"])
		Example Input: getAllValues(["Users", "Names"])
		Example Input: getAllValues(["Users", "Names"], orderBy = {"Users": "age"})
		Example Input: getAllValues(["Users", "Names"], orderBy = {"Users": ["age", "height"]})
		Example Input: getAllValues(["Users", "Names"], orderBy = {"Users": ["age", "height"], "Names": "extra_data"})
		Example Input: getAllValues(["Users", "Names"], orderBy = "id")
		"""

		#Ensure correct format
		if ((type(relation) != list) and (type(relation) != tuple)):
			relationList = [relation]
		else:
			relationList = relation

		myTuple = {}
		for relation in relationList:
			#Ensure correct format
			if (type(exclude) == dict):
				if (relation in exclude):
					excludeList = exclude[relation]
				else:
					excludeList = []
			
			if ((type(exclude) != list) and (type(exclude) != tuple)):
				excludeList = [exclude]
			else:
				excludeList = exclude[:]

			#Build getValue query
			attributeNames = self.getAttributeNames(relation, excludeList)
			myTuple[relation] = attributeNames

		results_catalogue = self.getValue(myTuple, **kwargs)

		return results_catalogue

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getValue(self, myTuple, nextTo = {}, orderBy = None, limit = None, direction = None, nextToCondition = True, returnNull = False, returnForeign = True,
		checkForeigen = True, filterTuple = True, filterRelation = True, filterForeign = True, filterAttribute = False, filterNone = False, exclude = [],
		valuesAsList = False, valuesAsRows = True, greaterThan = {}, lessThan = {}, greaterThanOrEqualTo = {}, lessThanOrEqualTo = {}, like = {}):
		"""Gets the value of an attribute in a tuple for a given relation.
		If multiple attributes match the criteria, then all of the values will be returned.
		If you order the list and limit it; you can get things such as the 'top ten occurrences', etc.
		For more information on JOIN: https://www.techonthenet.com/sqlite/joins.php

		myTuple (dict)   - What to return. {relation: attribute}. A list of attributes can be returned. {relation: [attribute 1, attribute 2]}
			- If an attribute is a foreign key: {relation: {foreign relation: foreign attribute}}
		nextTo (dict)    - An attribute-value pair that is in the same tuple. {attribute: value}
			- If multiple keys are given, one will be 'chosen at random'
			- If an attribute is a foreign key: {value: {foreign relation: foreign attribute}}
			- If None: The whole column will be returned
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

		nextToCondition (bool) - Determines how to handle multiple nextTo criteria
			- If True: All of the criteria given must match
			- If False: Any of the criteria given must match
		checkForeigen (bool)   - Determines if foreign keys will be take in account
		
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
			- If True: Returned values will be all the row values for that column {relation: {attribute 1: [row 1 value, row 2 value, row 3 value]}
			- If False: Returned values will be all the column values for that row with the attribute names as a separate key {relation: {row 1: [attribute 1 value, attribute 2 value, attribute 3 value], "attributeNames": [name for attribute 1, name for attribute 2, name for attribute 3]}
			- If None: Returned values will be all the column values for that row with the attribute names with each value {relation: {row 1: {attribute 1: value, attribute 2: value, attribute 3: value}}}

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

		Example Input: getValue({"Users": "name"}, filterTuple = False)
		Example Input: getValue({"Users": "name"}, filterForeign = None)
		Example Input: getValue({"Users": "name"}, filterForeign = False)

		Example Input: getValue({"Users": "name"}, {"age": 24})
		Example Input: getValue({"Users": "name"}, {"age": 24, height: 6})
		Example Input: getValue({"Users": "name"}, {"age": 24, height: 6}, nextToCondition = False)

		Example Input: getValue({"Users": "age"}, {"name": "John"})
		Example Input: getValue({"Users": "age"}, {"name": ["John", "Jane"]})

		Example Input: getValue({"Users": "name"}, greaterThan = {"age": 20})
		"""

		if (filterRelation and filterAttribute):
			results_catalogue = []
		else:
			results_catalogue = {}

		if (nextTo == None):
			nextTo = {}
	
		for i, (relation, attributeList) in enumerate(myTuple.items()):
			#Account for multiple items
			if (not isinstance(attributeList, (list, tuple))):
				attributeList = [attributeList]
			if (valuesAsList == None):
				valuesAsList = False
			for attribute in attributeList:
				valueList = []
				command = "SELECT [{}].[{}] FROM [{}]".format(relation, attribute, relation)

				locationInfo, valueList = self.configureLocation(relation, nextTo, valueList, nextToCondition = nextToCondition, checkForeigen = checkForeigen, like = like, greaterThan = greaterThan, lessThan = lessThan, greaterThanOrEqualTo = greaterThanOrEqualTo, lessThanOrEqualTo = lessThanOrEqualTo)
				if (len(valueList) != 0):
					command += " WHERE ({})".format(locationInfo)

				if (orderBy != None):
					command += " ORDER BY "

					if (not isinstance(orderBy, (list, tuple))):
						orderBy = [orderBy]
					if (not isinstance(direction, (list, tuple, dict))):
						direction = [direction]
					if ((not isinstance(direction, dict)) and (len(direction) != 1) and (len(direction) != len(orderBy))):
						errorMessage = "'orderBy' and 'direction' size do not match"
						raise KeyError(errorMessage)

					for i, item in enumerate(orderBy):
						if (i != 0):
							command += ", "

						command += "[{}].[{}]".format(relation, item)

						if (type(direction) == dict):
							condition = direction.get(item, None)
						else:
							condition = direction[0] if len(direction) == 1 else direction[i]
						if (condition != None):
							command += " ASC" if condition else " DESC"

				if ((limit != None) and (self.connectionType != "access")):
					command += " LIMIT {}".format(limit)

				result = self.executeCommand(command, valueList, filterTuple = filterTuple, valuesAsList = valuesAsList)
				
				if ((limit != None) and (self.connectionType == "access")):
					result = result[:limit]

				#Check Foreign
				if (checkForeigen):
					result = self.configureForeign(result, relation, attribute, filterTuple = filterTuple, filterForeign = filterForeign, valuesAsList = valuesAsList, returnNull = returnNull, returnForeign = returnForeign)

				#Add result to catalogue
				if (filterRelation):
					if (filterAttribute):
						pathway = results_catalogue
					else:
						if (attribute not in results_catalogue):
							results_catalogue[attribute] = []
						pathway = results_catalogue[attribute]
				else:
					if (filterAttribute):
						if (relation not in results_catalogue):
							results_catalogue[relation] = []
						pathway = results_catalogue[relation]
					else:
						if (relation not in results_catalogue):
							results_catalogue[relation] = {}
						if (attribute not in results_catalogue[relation]):
							results_catalogue[relation][attribute] = []
						pathway = results_catalogue[relation][attribute]

				if (isinstance(result, dict)):
					print("@1", result)
					ujhjkhk
					pathway.append(result)
				else:
					for item in result:
						if (item not in exclude):
							pathway.append(item)


		#Determine output orientation
		if (valuesAsRows != None):
			if (valuesAsRows):
				return results_catalogue

		#Account for different formats
		if (filterRelation):
			temp_results_catalogue = {relation: results_catalogue}
		else:
			temp_results_catalogue = results_catalogue

		#Switch rows and columns
		new_results_catalogue = {}
		for item_relation, item_catalogue in temp_results_catalogue.items():
			if (valuesAsRows != None):
				#Setup rows
				new_results_catalogue[item_relation] = {"attributeNames": []}
				for i in range(len(list(item_catalogue.values())[0])):
					new_results_catalogue[item_relation][i] = []

				#Change item order
				for item_attribute, item_value in item_catalogue.items():
					new_results_catalogue[item_relation]["attributeNames"].append(item_attribute)

					for i, subItem in enumerate(item_value):
						new_results_catalogue[item_relation][i].append(subItem)
			else:
				#Setup rows
				new_results_catalogue[item_relation] = {}
				for i in range(len(list(item_catalogue.values())[0])):
					new_results_catalogue[item_relation][i] = {}

				#Change item order
				for item_attribute, item_value in item_catalogue.items():
					for i, subItem in enumerate(item_value):
						new_results_catalogue[item_relation][i][item_attribute] = subItem


		#Account for different formats
		if (filterRelation):
			new_results_catalogue = new_results_catalogue[relation]

		return new_results_catalogue

	def getForeignLinks(self, relationList, updateSchema = True):
		"""Returns foreign keys that are linked attributes in the given relation.
		{foreign relation: {foreign attribute: {relation that links to it: [attributes that link to it]}}}

		Example Input: getForeignLinks("Users")
		"""

		if (updateSchema):
			self.updateInternalforeignSchemas()
		if (not isinstance(relationList, (list, tuple, range))):
			relationList = [relationList]

		links = {}
		for relation in relationList:
			if (relation in self.foreignKeys_catalogue):
				for attribute, (foreign_relation, foreign_attribute) in self.foreignKeys_catalogue[relation].items():
					if (foreign_relation not in links):
						links[foreign_relation] = {}
					if (foreign_attribute not in links[foreign_relation]):
						links[foreign_relation][foreign_attribute] = {}
					if (relation not in links[foreign_relation][foreign_attribute]):
						links[foreign_relation][foreign_attribute][relation] = []

					if (attribute not in links[foreign_relation][foreign_attribute][relation]):
						links[foreign_relation][foreign_attribute][relation].append(attribute)
		return links

	def getForeignUses(self, relationList = None, attributeList = None, updateSchema = True, keepDuplicates = False, exclude = []):
		"""Returns how many places this foreign key is used.
		{foreign relation: {foreign attribute: list of keys used}}

		Example Input: getForeignUses("Users")
		Example Input: getForeignUses("Users", "name")
		"""

		def removeDuplicates(seq, idFunction=None):
			"""Removes duplicates from a list while preserving order.
			Created by Alex Martelli. From https://www.peterbe.com/plog/uniqifiers-benchmark

			Example Input: removeDuplicates()
			"""

			if idFunction is None:
				def idFunction(x): 
					return x

			seen = {}
			result = []
			for item in seq:
				marker = idFunction(item)
				if marker in seen: 
					continue
				seen[marker] = 1
				result.append(item)
			return result

		#Setup
		if (updateSchema):
			self.updateInternalforeignSchemas()

		if (not isinstance(exclude, (list, tuple, range))):
			exclude = [exclude]

		if (relationList == None):
			relationList = self.getRelationNames(exclude)
		elif (not isinstance(relationList, (list, tuple, range))):
			relationList = [relationList] if (item not in exclude) else []
		else:
			relationList = [item for item in relationList if (item not in exclude)]

		if ((attributeList != None) and (not isinstance(attributeList, (list, tuple, range)))):
			attributeList = [attributeList]

		#Look for relations in the list that are a foreign relation
		links = self.getForeignLinks(relationList, updateSchema = False)
				
		#Get all usages of the foreign keys
		existing = {} #{foreign relation: {foreign attribute: list of keys used}}
		for foreign_relation, item in links.items():
			if (foreign_relation not in existing):
				existing[foreign_relation] = {}
			
			for foreign_attribute, myTuple in item.items():
				if (foreign_attribute not in existing[foreign_relation]):
					existing[foreign_relation][foreign_attribute] = []

				#Catalogue useage
				results = self.getValue(myTuple, checkForeigen = False)
				for attribute, valueList in results.items():
					if ((attributeList == None) or (attribute in attributeList)):
						existing[foreign_relation][foreign_attribute].extend(valueList)

				#Clear out duplicates
				if (not keepDuplicates):
					existing[foreign_relation][foreign_attribute] = removeDuplicates(existing[foreign_relation][foreign_attribute])

		#Remove blank items
		used = {}
		for foreign_relation, item in existing.items():
			for foreign_attribute, myTuple in item.items():
				if (len(myTuple) != 0):
					if (foreign_relation not in used):
						used[foreign_relation] = {}
					used[foreign_relation][foreign_attribute] = myTuple

		return used

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def cleanForeignKeys(self, cleanList = None, exclude = [], filterType = True, applyChanges = None):
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

		#Make sure the internal schema is up to date
		self.updateInternalforeignSchemas()

		#Get a values
		if (not isinstance(exclude, (list, tuple, range))):
			exclude = [exclude]
		
		if (cleanList == None):
			cleanList = self.getRelationNames(exclude)
		else:
			cleanList = [item for item in cleanList if (item not in exclude)]

		usedKeys = self.getForeignUses(cleanList, updateSchema = False)

		#Determine which keys to remove
		removeKeys = {}
		for foreign_relation, item in usedKeys.items():
			for foreign_attribute, used in item.items():
				contents = self.getValue({foreign_relation: "id"}, checkForeigen = False)

				for key, valueList in contents.items():
					if (filterType):
						removeList = [value for value in valueList if (str(value) not in [str(item) for item in used])]
					else:
						removeList = [value for value in valueList if (value not in used)]

					if (len(removeList) != 0):
						if (foreign_relation not in removeKeys):
							removeKeys[foreign_relation] = {}
						if ("id" not in removeKeys[foreign_relation]):
							removeKeys[foreign_relation]["id"] = []

						removeKeys[foreign_relation]["id"].extend(removeList)

		#Delete unused keys
		self.removeTuple(removeKeys, nextToCondition = False)

		#Return number of keys removed
		n = 0
		for key, value in removeKeys.items():
			for subKey, subValue in value.items():
				n += len(valueList)

		#Save Changes
		if (applyChanges == None):
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


		if (self.connectionType == "access"):
			errorMessage = "The ODBC driver for MS Access does not support adding triggers"
			raise KeyError(errorMessage)

		#Setup
		valueList = []
		command = "CREATE TRIGGER "
		if (noReplication != None):
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

		if (event_attribute != None):
			command += "OF [{}] ".format(event_attribute)
		
		if (event_relation == None):
			event_relation = relation
		command += "ON [{}] FOR EACH ROW ".format(event_relation)

		# if (reaction_when != None):
		# 	condition = "WHEN "

		# 	#Apply Condition
		# 	command += condition

		#Create Reation
		if (reaction_relation == None):
			reaction_relation = relation
		
		if (reaction[0] == "l"):
			if (reaction_attribute == None):
				if ("lastModified" not in self.getAttributeNames(reaction_relation)):
					self.addAttribute(reaction_relation, "lastModified", dataType = str, default = "strftime('%m/%d/%Y %H:%M:%S:%s','now', 'localtime')")
				reaction_attribute = "lastModified"

			reaction = "UPDATE [{}] SET [{}] = strftime('%m/%d/%Y %H:%M:%S:%s','now', 'localtime') WHERE (rowid = new.rowid);".format(reaction_relation, reaction_attribute)
		
		elif (reaction[0] == "c"):
			if (reaction_attribute == None):
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
		if (applyChanges == None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getTrigger(self, label = None, exclude = []):
		"""Returns an event trigger.

		label (str) - What the trigger will be called in the .db
			- If None: Will return the names of all triggers

		Example Input: getTrigger()
		Example Input: getTrigger("Users_lastModified")
		"""


		if (self.connectionType == "access"):
			errorMessage = "The ODBC driver for MS Access does not support getting triggers"
			raise KeyError(errorMessage)

		triggerList = self.executeCommand("SELECT name FROM sqlite_master WHERE type = 'trigger'")
		triggerList = [trigger[0] for trigger in triggerList if trigger[0] not in exclude]

		if (label != None):
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

		if (self.connectionType == "access"):
			errorMessage = "The ODBC driver for MS Access does not support removing triggers"
			raise KeyError(errorMessage)

		triggerList = self.getTrigger(label)
		if (triggerList != None):
			if (not isinstance(triggerList, (list, tuple, range))):
				triggerList = [triggerList]

			for trigger in triggerList:
				#Execute SQL
				self.executeCommand("DROP TRIGGER IF EXISTS [{}]".format(trigger))

			#Save Changes
			if (applyChanges == None):
				applyChanges = self.defaultCommit

			if (applyChanges):
				self.saveDatabase()

def test_sqlite():
	print("sqlite3")
	#Create the database
	database_API = build()
	database_API.openDatabase("test.db", applyChanges = False)

	database_API.removeRelation("Users")
	database_API.removeRelation("Names")
	database_API.removeRelation("Address")

	#Create tables from the bottom up
	database_API.createRelation("Names", [{"first_name": str}, {"extra_data": str}], unique = {"first_name": True})
	database_API.createRelation("Address", {"street": str}, unique = {"street": True})
	database_API.createRelation("Users", {"age": int, "height": int}, foreign = {"name": {"Names": "first_name"}, "address": {"Address": "street"}})
	database_API.saveDatabase()

	database_API.addTuple("Names", {"first_name": "Dolor", "extra_data": "Sit"}, unique = None)
	
	database_API.addTuple("Users", {"name": "Ipsum", "age": 26, "height": 5}, unique = None)
	database_API.addTuple("Users", {"name": "Lorem", "age": 26, "height": 6}, unique = None)
	database_API.addTuple("Users", {"name": "Lorem", "age": 24, "height": 3}, unique = None)
	database_API.addTuple("Users", {"name": "Dolor", "age": 21, "height": 4}, unique = None)
	database_API.addTuple("Users", {"name": "Sit", "age": None, "height": 1}, unique = None)

	#Simple Actions
	print("Simple Actions")
	print(database_API.getValue({"Users": "name"}))
	print(database_API.getValue({"Users": "name"}, filterRelation = False))
	print(database_API.getValue({"Users": ["name", "age"]}))
	print()

	#Ordering Data
	print("Ordering Data")
	print(database_API.getValue({"Users": "name"}, orderBy = "age"))
	print(database_API.getValue({"Users": ["name", "age"]}, orderBy = "age", limit = 2))
	print(database_API.getValue({"Users": ["name", "age"]}, orderBy = "age", direction = True))

	print(database_API.getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"]))
	print(database_API.getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"], direction = [None, False]))
	print(database_API.getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"], direction = {"height": False}))

	print(database_API.getValue({"Users": "name", "Names": "first_name"}))
	print(database_API.getValue({"Users": "name", "Names": "first_name"}, filterRelation = False))
	print(database_API.getValue({"Users": "name", "Names": ["first_name", "extra_data"]}))
	print()

	#Changing Attributes
	print("Changing Attributes")
	print(database_API.getValue({"Users": "name"}))
	database_API.changeTuple({"Names": "first_name"}, {"first_name": "Lorem"}, "Amet")
	print(database_API.getValue({"Users": "name"}))
	print(database_API.getValue({"Users": "name"}, filterForeign = True))

	database_API.changeTuple({"Users": "name"}, {"age": 26}, "Consectetur", forceMatch = True)
	print(database_API.getValue({"Users": "name"}))
	print(database_API.getValue({"Users": "name"}, filterForeign = None))
	print(database_API.getValue({"Users": "name"}, filterForeign = False))
	print(database_API.getValue({"Users": "name"}, checkForeigen = False))
	print()

	#Triggers
	database_API.createTrigger("Users_lastModified", "Users", reaction = "lastModified")
	print(database_API.getTrigger())
	database_API.changeTuple({"Users": "name"}, {"age": 26}, "Amet", forceMatch = True)
	print(database_API.getValue({"Users": ["name", "lastModified"]}))

	database_API.saveDatabase()

def test_access():
	print("\n\naccess")
	#Create the database
	database_API = build()
	database_API.openDatabase("H:/Python/Material_Tracker/empty.accdb", applyChanges = False)

	database_API.removeRelation("Names")
	database_API.removeRelation("Address")

	#Create tables from the bottom up
	database_API.createRelation("Names", [{"first_name": str}, {"extra_data": str}], unique = {"first_name": True})
	database_API.createRelation("Address", {"street": str}, unique = {"street": True})
	database_API.saveDatabase()

	database_API.addTuple("Names", {"first_name": "Lorem", "extra_data": 4}, unique = None)
	database_API.addTuple("Names", {"first_name": "Ipsum", "extra_data": 7}, unique = None)
	database_API.addTuple("Names", {"first_name": "Dolor", "extra_data": 3}, unique = None)
	database_API.addTuple("Names", {"first_name": "Sit",   "extra_data": 1}, unique = None)
	database_API.addTuple("Names", {"first_name": "Amet",  "extra_data": 10}, unique = None)
	
	#Simple Actions
	print("Simple Actions")
	print(database_API.getValue({"Names": "first_name"}))
	print(database_API.getValue({"Names": "first_name"}, filterRelation = False))
	print(database_API.getValue({"Names": ["first_name", "extra_data"]}))
	print()

	#Ordering Data
	print("Ordering Data")
	print(database_API.getValue({"Names": "first_name"}, orderBy = "first_name"))
	print(database_API.getValue({"Names": ["first_name", "extra_data"]}, orderBy = "extra_data", limit = 2))
	print(database_API.getValue({"Names": ["first_name", "extra_data"]}, orderBy = "extra_data", direction = True))
	print()

	#Changing Attributes
	print("Changing Attributes")
	print(database_API.getValue({"Names": "first_name"}))
	database_API.changeTuple({"Names": "first_name"}, {"first_name": "Lorem"}, "Consectetur")
	print(database_API.getValue({"Names": "first_name"}))
	database_API.changeTuple({"Names": "first_name"}, {"first_name": "Adipiscing"}, "Elit", forceMatch = True)
	print(database_API.getValue({"Names": "first_name"}))
	print()

	database_API.saveDatabase()

def main():
	"""The main program controller."""

	test_sqlite()
	test_access()

if __name__ == '__main__':
	main()
