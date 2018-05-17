__version__ = "3.2.0"

## TO DO ##
# - Add a foreign key cleanup command; removes unused foreign keys in foreign tables

import re
import time
import sqlite3
import warnings
import traceback
import functools

#For multi-threading
# import sqlalchemy
import threading

threadLock = threading.Lock()

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
def wrap_errorCheck(fileName = "error_log.log", timestamp = True):
	def decorator(function):
		@functools.wraps(function)
		def wrapper(*args, **kwargs):
			"""Logs errors.

			Example Usage: @wrap_errorCheck()
			"""

			try:
				answer = function(*args, **kwargs)
			except SystemExit:
				sys.exit()
			except:
				answer = None
				error = traceback.format_exc()
				print(error)

				try:
					with open(fileName, "a") as fileHandle:
						if (timestamp):
							content = f"{time.strftime('%Y/%m/%d %H:%M:%S', time.localtime())} --- "
						else:
							content = ""
						content += " " .join([str(item) for item in args])
						fileHandle.write(content)
						fileHandle.write("\n")
				except:
					traceback.print_exc()

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

	def __init__(self, fileName = None, applyChanges = True, multiThread = False):
		"""Defines internal variables.
		A better way to handle multi-threading is here: http://code.activestate.com/recipes/526618/

		fileName (str) - If not None: Opens the provided database automatically

		Example Input: Database()
		Example Input: Database("emaildb")
		"""

		#Internal variables
		self.defaultFileExtension = ".db"
		self.connection = None
		self.cursor = None
		self.defaultCommit = None
		self.fileName = None

		self.foreignKeys_catalogue = {} #A dictionary of already found foreign keys. {relation: {attribute: [foreign_relation, foreign_attribute]}}

		#Initialization functions
		if (fileName != None):
			self.openDatabase(fileName = fileName , applyChanges = applyChanges, multiThread = multiThread)

	def __del__(self):
		"""Makes sure that the opened database has been closed."""

		if (self.connection != None):
			self.closeDatabase()

	#Utility Functions
	def getType(self, pythonType):
		"""Translates a python data type into an SQL data type.
		These types are: INTEGER, TEXT, BLOB, REAL, and NUMERIC.
		https://sqlite.org/datatype3.html

		pythonType (type) - The data type to translate

		Example Input: getType(str)
		"""

		sqlType = None
		if (pythonType in ["TEXT", "INTEGER"]):
			sqlType = pythonType

		elif (pythonType == str):
			sqlType = "TEXT"

		elif (pythonType == int):
			sqlType = "INTEGER"

		#I am not sure if this is correct
		# elif (pythonType == float):
		# 	sqlType = "REAL"

		else:
			errorMessage = f"Add {pythonType} to getType()"
			raise KeyError(errorMessage)

		return sqlType

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
	def getRelationNames(self, exclude = []):
		"""Returns the names of all relations (tables) in the database.

		exclude (list) - A list of which relations to excude from the returned result

		Example Input: getRelationNames()
		Example Input: getRelationNames(["Users", "Names"])
		"""

		exclude.append("sqlite_sequence")

		relationList = self.executeCommand("SELECT name FROM sqlite_master WHERE type = 'table'")
		relationList = [relation[0] for relation in relationList if relation[0] not in exclude]

		return relationList

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getAttributeNames(self, relation, exclude = []):
		"""Returns the names of all attributes (columns) in the given relation (table).

		relation (str) - The name of the relation
		exclude (list) - A list of which attributes to excude from the returned result

		Example Input: getAttributeNames("Users")
		Example Input: getAttributeNames("Users", ["age", "height"])
		"""

		table_info = self.executeCommand("PRAGMA table_info([{}])".format(relation), valuesAsList = True)
		attributeList = [attribute[1] for attribute in table_info if attribute[1] not in exclude]

		return attributeList

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

		Example Input: getSchema("Users")
		"""

		#Setup
		data = {}
		data["schema"] = []
		data["notNull"] = {}
		data["primary"] = {}
		data["autoIncrement"] = {}
		data["unsigned"] = {}
		data["unique"] = {}
		data["foreign"] = []

		#Get Schema Info
		table_info = self.executeCommand("PRAGMA table_info([{}])".format(relation), valuesAsList = True)

		foreign_key_list = self.executeCommand("PRAGMA foreign_key_list([{}])".format(relation), valuesAsList = True)
		foreign_key_list.reverse()

		raw_sql = self.executeCommand("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{}'".format(relation))
		raw_sql = raw_sql[0][0]
		autoIncrement_list = re.findall("`(.*?)`.*?AUTOINCREMENT", raw_sql)
		unsigned_list = re.findall("`(.*?)`.*?UNSIGNED", raw_sql)
		unique_list = re.findall("`(.*?)`.*?UNIQUE", raw_sql)

		#Keys
		for item in table_info:
			columnName, dataType, null, default, primaryKey = item[1], item[2], item[3], item[4], item[5]

			data["schema"].append({columnName: dataType})
			data["notNull"][columnName] = bool(null)
			data["primary"][columnName] = bool(primaryKey)

			if (columnName in autoIncrement_list):
				data["autoIncrement"][columnName] = True

			if (columnName in unsigned_list):
				data["unsigned"][columnName] = True

			if (columnName in unique_list):
				data["unique"][columnName] = True

		#Foreign
		for item in foreign_key_list:
			foreign_relation, attribute, foreign_attribute = item[2], item[3], item[4]

			data["foreign"].append({attribute: {foreign_relation: foreign_attribute}})

			for subItem in data["schema"]:
				if (attribute in subItem):
					del subItem[attribute]

		# data["schema"] = list(self.executeCommand("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{}'".format(relation)))

		# if (len(data["schema"]) == 0):
		# 	data["schema"] = None
		# else:
		# 	data["schema"] = data["schema"][0]

		return data

	def updateInternalforeignSchemas(self):
		"""Only remembers data from schema (1) is wanted and (2) that is tied to a foreign key.
		Special Thanks to Davoud Taghawi-Nejad for how to get a list of table names on https://stackoverflow.com/questions/305378/list-of-tables-db-schema-dump-etc-using-the-python-sqlite3-api
		"""

		#Get the table names
		relationList = self.getRelationNames()

		#Get the foreign schema for each relation
		for relation in relationList:
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

	def changeForeign(self, relation, attribute, nextTo, value, valueList, forceMatch):
		"""Adds a foreign key to the table if needed."""

		foreign_results = self.findForeign(relation, attribute)
		if (len(foreign_results) != 0):
			foreign_relation, foreign_attribute = foreign_results

			currentValue = self.getValue({relation: attribute}, nextTo = nextTo, checkForeigen = False, returnNull = False)[attribute]
			foreign_id = self.getValue({foreign_relation: "id"}, {foreign_attribute: currentValue}, filterRelation = True, returnNull = False)["id"]

			if (len(foreign_id) == 0):
				if (not forceMatch):
					errorMessage = f"There is no foreign key {foreign_attribute} with the value {currentValue} in the relation {foreign_relation} for changeForeign()"
					raise KeyError(errorMessage)
				self.addTuple(foreign_relation, myTuple = {foreign_attribute: currentValue}, unique = None)
				foreign_id = self.getValue({foreign_relation: "id"}, {foreign_attribute: currentValue}, filterRelation = True, returnNull = False)["id"]
			else:
				self.changeTuple({foreign_relation: foreign_attribute}, {"id": foreign_id[0]}, value, unique = None)
			valueList.append(foreign_id[0])
		else:
			valueList.append(value)

		return valueList

	def configureForeign(self, results, relation, attribute, filterTuple = True, filterForeign = False, valuesAsList = True, returnNull = False):
		"""Allows the user to use foreign keys.
		For more information on JOIN: https://www.techonthenet.com/sqlite/joins.php
		"""

		foreign_results = self.findForeign(relation, attribute)
		if (len(foreign_results) != 0):
			foreign_relation, foreign_attribute = foreign_results

			valueList = []
			for value in results:
				# print("@5", results, relation, attribute, returnNull, value)
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

	def executeCommand(self, command, valueList = (), hackCheck = True, valuesAsList = None, filterTuple = False):
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
		try:
			threadLock.acquire(True)
			result = list(self.cursor.execute(command, valueList))
		except Exception as error:
			print(f"-- {command}, {valueList}")
			raise error
		finally:
			threadLock.release()

		# print("@0.2", result)

		#Configure results
		if (valuesAsList != None):
			result = list(result)

			if (filterTuple and (len(result) > 0) and (len(result[0]) == 1)):
				for i, item in enumerate(result):
					result[i] = item[0]

			if (not valuesAsList):
				result = tuple(result)

		return result

	#Interaction Functions
	@wrap_errorCheck()
	def openDatabase(self, fileName = "myDatabase", applyChanges = True, multiThread = False):
		"""Opens a database.If it does not exist, then one is created.
		Note: If a database is already opened, then that database will first be closed.
		Special thanks toLarry Lustig for help with multi-threading on http://stackoverflow.com/questions/22739590/how-to-share-single-sqlite-connection-in-multi-threaded-python-application
		# Special thanks to culix for help with multi-threading on http://stackoverflow.com/questions/6297404/multi-threaded-use-of-sqlalchemy

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

		#Configure Options
		self.defaultCommit = applyChanges

		#Establish connection
		if (multiThread):
			#Temporary fix until I learn SQLAlchemy to do this right
			self.connection = sqlite3.connect(fileName, check_same_thread = False)
		else:
			self.connection = sqlite3.connect(fileName)

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
			command = "DROP TABLE IF EXISTS [{}]".format(relation)
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
		unsigned = {}, unique = {}, foreign = None, applyChanges = None):
		"""Renames a relation (table) to the given name the user provides.

		relation (str)      - What the relation is called in the .db
		applyChanges (bool) - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used

		Example Input: setSchema("Users", foreign = {"name": {"Names": "first_name"}})
		"""

		def applyChanges(old_thing, mod_thing):
			"""Applies user modifications to the table settings."""

			if (type(old_thing) == list):
				#Apply Changes
				for old_item in old_thing:
					for old_key, old_value in old_item.items():
						#Determine if the value should be re-defined
						for item in mod_thing:
							for new_key, new_value in item.items():
								if (new_key == old_key):
									old_item[old_key] = new_value
									break
			else:
				for old_key, old_value in old_thing.items():
					#Determine if the value should be re-defined
					for new_key, new_value in mod_thing.items():
						if (new_key == old_key):
							old_thing[old_key] = new_value
							break

			return old_thing

		#Ensure correct format
		if ((type(schema) != list) and (type(schema) != tuple)):
			schemaList = [schema]
		else:
			schemaList = schema

		if ((type(foreign) != list) and (type(foreign) != tuple)):
			foreignList = [foreign]
		else:
			foreignList = foreign

		#Get current data
		data = self.getSchema(relation)
		table_contents = self.getAllValues(relation, orderBy = "id", filterRelation = False, valuesAsList = True, valuesAsRows = None, checkForeigen = False)

		#Rename old table
		self.renameRelation(relation, "tempCopy_{}".format(relation))

		#Apply changes
		new_schema = applyChanges(data["schema"], schemaList)
		new_notNull = applyChanges(data["notNull"], notNull)
		new_primary = applyChanges(data["primary"], primary)
		new_autoIncrement = applyChanges(data["autoIncrement"], autoIncrement)
		new_unsigned = applyChanges(data["unsigned"], unsigned)
		new_unique = applyChanges(data["unique"], unique)
		new_foreign = applyChanges(data["foreign"], foreignList)

		# #Create new table
		self.createRelation(relation, schema = new_schema, notNull = new_notNull, primary = new_primary, 
			autoIncrement = new_autoIncrement, unsigned = new_unsigned, unique = new_unique, foreign = new_foreign, 
			applyChanges = applyChanges, autoPrimary = False)

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

		def addforeign(schemaFormatted, foreignList):
			"""A sub-function that adds a foreign key for the user.
			More information at: http://www.sqlitetutorial.net/sqlite-foreign-key/
			"""

			#Parse foreign keys
			# schema_foreign = {} #
			for foreign in foreignList:
				for attribute, foreign_dict in foreign.items():
					#Account for non-foreign keys
					if (type(foreign_dict) == dict):
						#Add the foreign key to the table
						foreign_relation, foreign_attribute = list(foreign_dict.items())[0]
						schemaFormatted += "[{}] INTEGER".format(attribute)
					else:
						#Add local key to the table
						schemaFormatted += "[{}] {}".format(attribute, self.getType(foreign_dict))

					schemaFormatted = formatSchema(schemaFormatted, attribute, False)

					#Account for multiple attributes
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

		#Build SQL command
		command = "CREATE TABLE "

		if (noReplication != None):
			command += "IF NOT EXISTS "

		else:
			self.removeRelation(relation)

		command += "[" + str(relation) + "]"


		#Ensure correct format
		if ((type(schema) != list) and (type(schema) != tuple)):
			schemaList = [schema]
		else:
			schemaList = schema

		#Format schema
		firstRun = True
		schemaFormatted = ""

		#Add primary key
		if (autoPrimary):
			schemaFormatted += "id INTEGER"
			schemaFormatted = formatSchema(schemaFormatted, "id", autoPrimary)

		#Add given attributes
		for schema in schemaList:
			for i, (attribute, dataType) in enumerate(schema.items()):
				if (schemaFormatted != ""):
					schemaFormatted += ", "

				schemaFormatted += "[{}] {}".format(attribute, self.getType(dataType))
				schemaFormatted = formatSchema(schemaFormatted, attribute, False)

		#Add foreign keys
		if (foreign != None):
			#Ensure correct format
			if ((type(foreign) != list) and (type(foreign) != tuple)):
				foreignList = [foreign]
			else:
				foreignList = foreign

			#Account for primary key
			if (schemaFormatted != ""):
				schemaFormatted += ", "

			schemaFormatted = addforeign(schemaFormatted, foreignList)

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
	def addTuple(self, relation, myTuple = {}, applyChanges = None, autoPrimary = False, notNull = False, foreignNone = False,
		primary = False, autoIncrement = False, unsigned = True, unique = False, checkForeigen = True):
		"""Adds a tuple to the given relation.
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
					existsCheck = self.getValue({relation: "id"}, {attribute: value})["id"]
					# print("@3", existsCheck, relation, myTuple)
					if (len(existsCheck) != 0):
						return

		command = "INSERT "
		if (unique != None):
			if (unique):
				command += "OR REPLACE "
		else:
			command += "OR IGNORE "

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
	def changeTuple(self, myTuple, nextTo, value, forceMatch = None, defaultValues = {}, applyChanges = None, checkForeigen = True, updateForeign = None, exclude = [], nextToCondition = True, like = {}):
		"""Changes a tuple for a given relation.
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

		#Account for multiple tuples to change
		for relation, attribute in myTuple.items():
			valueList = []
			if (checkForeigen):
				valueList = self.changeForeign(relation, attribute, nextTo, value, valueList, forceMatch)

			currentValue = self.getValue({relation: attribute}, nextTo, filterRelation = True)[attribute]
			if (len(currentValue) == 0):
				if (not forceMatch):
					errorMessage = f"There is no key {attribute} with the nextTo {nextTo} in the relation {relation}"
					raise KeyError(errorMessage)
				self.addTuple(relation, myTuple = {**{attribute: value}, **nextTo}, unique = None)
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
		"""Removes a tuple for a given relation.
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
	def getAllValues(self, relation, exclude = [], orderBy = None, nextTo = None, limit = None, direction = None, nextToCondition = True, guessType = False,
		checkForeigen = True, filterTuple = True, filterRelation = True, filterForeign = None, valuesAsList = False, valuesAsRows = True,
		greaterThan = {}, lessThan = {}, greaterThanOrEqualTo = {}, lessThanOrEqualTo = {}, like = {}):
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

		results_catalogue = self.getValue(myTuple, nextTo = nextTo, orderBy = orderBy, limit = limit, direction = direction, nextToCondition = nextToCondition, valuesAsRows = valuesAsRows,
			checkForeigen = checkForeigen, filterTuple = filterTuple, filterRelation = filterRelation, filterForeign = filterForeign, valuesAsList = valuesAsList, guessType = guessType,
			greaterThan = greaterThan, lessThan = lessThan, greaterThanOrEqualTo = greaterThanOrEqualTo, lessThanOrEqualTo = lessThanOrEqualTo, like = like)

		return results_catalogue

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def getValue(self, myTuple, nextTo = {}, orderBy = None, limit = None, direction = None, nextToCondition = True, returnNull = False,
		checkForeigen = True, filterTuple = True, filterRelation = True, filterForeign = True, filterAttribute = False, filterNone = False,
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
		guessType (bool)       - Determines if returned values should try being non-strings. WARNING: Not secure yet
			- If True: Returned values that would have been strings may be lists, tuples, dictionaries, integers, floats, bools, etc.
			- If False: Returned values will not be interpreted

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

		# print("@7", myTuple, nextTo, returnNull)

		if (filterRelation and filterAttribute):
			results_catalogue = []
		else:
			results_catalogue = {}
	
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

				if (limit != None):
					command += " LIMIT {}".format(limit)

				result = self.executeCommand(command, valueList, filterTuple = filterTuple, valuesAsList = valuesAsList)

				#Check Foreign
				if (checkForeigen):
					# print("@6.1", result, relation, attribute)
					result = self.configureForeign(result, relation, attribute, filterTuple = filterTuple, filterForeign = filterForeign, valuesAsList = valuesAsList, returnNull = returnNull)

					# print("@6.2", result, relation, attribute)

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
					pathway.append(result)
				else:
					pathway.extend(result)

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

	def onCleanForeignKeys(self, event, cleanList = None, exclude = [], filterType = True):
		"""An event function in the wxPython format for cleanForeignKeys()."""

		self.cleanForeignKeys(cleanList = cleanList, exclude = exclude, filterType = filterType)
		event.Skip()

	@wrap_errorCheck()
	@wrap_connectionCheck()
	def cleanForeignKeys(self, cleanList = None, exclude = [], filterType = True):
		"""Removes unused foreign keys from foreign relations (tables) not in the provided exclude list.
		Special thanks to Alex Martelli for removing duplicates quickly from a list on https://www.peterbe.com/plog/uniqifiers-benchmark

		cleanList (list)  - A list of which relations to clean unused tuples from
			- If None: All tables will be evaluated
		exclude (list)    - A list of which relations to excude from the cleaning process
		filterType (bool) - Determines if value type matters in comparing
			- If True: Numbers and numbers as strings count as the same thing
			- If False: Numbers and numbers as strings are different things

		Example Input: cleanForeignKeys()
		Example Input: cleanForeignKeys(['Lorem', 'Ipsum'])
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

		#Make sure the internal schema is up to date
		self.updateInternalforeignSchemas()

		#Get a values
		if (cleanList == None):
			cleanList = self.getRelationNames(exclude)
		else:
			cleanList = [item for item in cleanList if (item not in exclude)]

		cleanDict = {} #{foreign relation: {foreign attribute: {relation that links to it: [attributes that link to it]}}}

		#Look for relations in the list that are a foreign relation
		for relation, foreign_key_list in self.foreignKeys_catalogue.items():
			for attribute, foreign_key in foreign_key_list.items():
				foreign_relation, foreign_attribute = foreign_key
				if (foreign_relation in cleanList):
					#Error Check
					if (foreign_relation not in cleanDict):
						cleanDict[foreign_relation] = {}
					if (foreign_attribute not in cleanDict[foreign_relation]):
						cleanDict[foreign_relation][foreign_attribute] = {}
					if (relation not in cleanDict[foreign_relation][foreign_attribute]):
						cleanDict[foreign_relation][foreign_attribute][relation] = []

					#Catalogue how things are linked
					if (attribute not in cleanDict[foreign_relation][foreign_attribute][relation]):
						cleanDict[foreign_relation][foreign_attribute][relation].append(attribute)
				
		#Get all usages of the foreign keys
		usedKeys = {} #{foreign relation: {foreign attribute: list of keys used}}
		for foreign_relation, item in cleanDict.items():
			if (foreign_relation not in usedKeys):
				usedKeys[foreign_relation] = {}
			
			for foreign_attribute, myTuple in item.items():
				if (foreign_attribute not in usedKeys[foreign_relation]):
					usedKeys[foreign_relation][foreign_attribute] = []

				#Catalogue useage
				results = self.getValue(myTuple, checkForeigen = False)
				for attribute, valueList in results.items():
					usedKeys[foreign_relation][foreign_attribute].extend(valueList)

				#Clear out duplicates
				usedKeys[foreign_relation][foreign_attribute] = removeDuplicates(usedKeys[foreign_relation][foreign_attribute])

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

		return n

def main():
	"""The main program controller."""

	#Create the database
	database_API = Database()
	database_API.openDatabase("test.db", applyChanges = False)
	database_API.removeTable("Users")
	database_API.removeTable("Names")
	database_API.removeTable("Address")

	# #Create tables from the bottom up
	database_API.createTable("Names", [{"first_name": str}, {"extra_data": str}], unique = {"first_name": True})
	database_API.createTable("Address", {"street": str}, unique = {"street": True})
	database_API.createTable("Users", {"age": int, "height": int}, foreign = {"name": {"Names": "first_name"}, "address": {"Address": "street"}})
	database_API.saveDatabase()

	database_API.addRow("Names", {"first_name": "Dolor", "extra_data": "Sit"}, unique = None)
	
	database_API.addRow("Users", {"name": "Ipsum", "age": 26, "height": 5}, unique = None)
	database_API.addRow("Users", {"name": "Lorem", "age": 26, "height": 6}, unique = None)
	database_API.addRow("Users", {"name": "Lorem", "age": 24, "height": 3}, unique = None)
	database_API.addRow("Users", {"name": "Dolor", "age": 21, "height": 4}, unique = None)
	database_API.addRow("Users", {"name": "Sit", "age": None, "height": 1}, unique = None)

	# # Simple actions
	# print(database_API.getValue({"Users": "name"}))
	# print(database_API.getValue({"Users": "name"}, filterRelation = False))
	# print(database_API.getValue({"Users": ["name", "age"]}))

	# #Ordering data
	# print(database_API.getValue({"Users": "name"}, orderBy = "age"))
	# print(database_API.getValue({"Users": ["name", "age"]}, orderBy = "age", limit = 2))
	# print(database_API.getValue({"Users": ["name", "age"]}, orderBy = "age", direction = True))

	# print(database_API.getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"]))
	# print(database_API.getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"], direction = [None, False]))
	# print(database_API.getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"], direction = {"height": False}))

	# #Multiple Relations
	# print(database_API.getValue({"Users": "name", "Names": "first_name"}))
	# print(database_API.getValue({"Users": "name", "Names": "first_name"}, filterRelation = False))
	# print(database_API.getValue({"Users": "name", "Names": ["first_name", "extra_data"]}))

	# #Changing attributes
	# print(database_API.getValue({"Users": "name"}))
	# database_API.changeCell({"Names": "first_name"}, {"first_name": "Lorem"}, "Amet")
	# print(database_API.getValue({"Users": "name"}))
	# print(database_API.getValue({"Users": "name"}, filterForeign = True))

	# database_API.changeCell({"Users": "name"}, {"age": 26}, "Consectetur", forceMatch = True)
	print(database_API.getValue({"Users": "name"}))
	print(database_API.getValue({"Users": "name"}, filterForeign = None))
	print(database_API.getValue({"Users": "name"}, filterForeign = False))
	print(database_API.getValue({"Users": "name"}, checkForeigen = False))

	# database_API.changeCell({"Users": "name"}, {"age": 26}, "Amet")

	database_API.saveDatabase()

if __name__ == '__main__':
	main()
