__version__ = "3.2.0"

## TO DO ##
# - Add a foreign key cleanup command; removes unused foreign keys in foreign tables

import re
import json #For the example in main()
import sqlite3

#For multi-threading
# import sqlalchemy
import threading

threadLock = threading.Lock()

#Controllers
def build(*args, **kwargs):
	"""Starts the GUI making process."""

	return Database(*args, **kwargs)

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
			print("Add", pythonType, "to getType()")

		return sqlType

	def getFileName(self, includePath = True):
		"""Returns the name of the database.

		Example Input: getFileName()
		Example Input: getFileName(includePath = False)
		"""

		return self.fileName

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

	def getAttributeNames(self, relation, exclude = []):
		"""Returns the names of all attributes (columns) in the given relation (table).

		relation (str) - The name of the relation
		exclude (list) - A list of which attributes to excude from the returned result

		Example Input: getAttributeNames("Users")
		Example Input: getAttributeNames("Users", ["age", "height"])
		"""

		table_info = list(self.executeCommand("PRAGMA table_info([{}])".format(relation)))
		attributeList = [attribute[1] for attribute in table_info if attribute[1] not in exclude]

		return attributeList

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
		schema = []
		notNull = {}
		primary = {}
		autoIncrement = {}
		unsigned = {}
		unique = {}
		foreign = []

		#Get Schema Info
		table_info = list(self.executeCommand("PRAGMA table_info([{}])".format(relation)))

		foreign_key_list = list(self.executeCommand("PRAGMA foreign_key_list([{}])".format(relation)))
		foreign_key_list.reverse()

		raw_sql = self.executeCommand("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{}'".format(relation))
		raw_sql = raw_sql[0][0]
		autoIncrement_list = re.findall("`(.*?)`.*?AUTOINCREMENT", raw_sql)
		unsigned_list = re.findall("`(.*?)`.*?UNSIGNED", raw_sql)
		unique_list = re.findall("`(.*?)`.*?UNIQUE", raw_sql)

		#Keys
		for item in table_info:
			columnName, dataType, null, default, primaryKey = item[1], item[2], item[3], item[4], item[5]

			schema.append({columnName: dataType})
			notNull[columnName] = bool(null)
			primary[columnName] = bool(primaryKey)

			if (columnName in autoIncrement_list):
				autoIncrement[columnName] = True

			if (columnName in unsigned_list):
				unsigned[columnName] = True

			if (columnName in unique_list):
				unique[columnName] = True

		#Foreign
		for item in foreign_key_list:
			foreign_relation, attribute, foreign_attribute = item[2], item[3], item[4]

			foreign.append({attribute: {foreign_relation: foreign_attribute}})

			for subItem in schema:
				if (attribute in subItem):
					del subItem[attribute]

		# schema = list(self.executeCommand("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = '{}'".format(relation)))

		# if (len(schema) == 0):
		# 	schema = None
		# else:
		# 	schema = schema[0]

		return schema, notNull, primary, autoIncrement, unsigned, unique, foreign

	def updateInternalforeignSchemas(self):
		"""Only remembers data from schema (1) is wanted and (2) that is tied to a foreign key.
		Special Thanks to Davoud Taghawi-Nejad for how to get a list of table names on https://stackoverflow.com/questions/305378/list-of-tables-db-schema-dump-etc-using-the-python-sqlite3-api
		"""

		#Get the table names
		relationList = self.getRelationNames()

		#Get the foreign schema for each relation
		for relation in relationList:
			foreign_schemaList = list(self.executeCommand("PRAGMA foreign_key_list([{}])".format(relation)))

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

	def executeCommand(self, command, valueList = (), hackCheck = True):
		"""Executes an SQL command. Allows for multi-threading.
		Special thanks to Joaquin Sargiotto for how to lock threads on https://stackoverflow.com/questions/26629080/python-and-sqlite3-programmingerror-recursive-use-of-cursors-not-allowed

		command (str)     - The SQL command to run
		valueList (tuple) - The variables to replace any '?' with in 'command'
		hackCheck (bool)  - Checks commands for common hacking tricks before it is executed
			- If True: Checks for commented out portions, escaped characters, and extra commands such as TABLE and SELECT
			- If False: Does not check the string.

		Example Input: executeCommand(command, value)
		Example Input: executeCommand(command, valueList)
		Example Input: executeCommand(command, [value] + valueList)
		"""

		#Check for common hacking techniques
		## MAKE THIS MORE ROBUST ##
		if (hackCheck):
			#Check for comments
			if (("--" in command) or ("/*" in command)):
				print("ERROR: Cannot comment out portions of the command")
				print(command)
				return None

		#Ensure correct format
		if (not isinstance(valueList, tuple)):
			if (isinstance(valueList, list)):
				valueList = tuple(valueList)
			else:
				valueList = (valueList,)

		#Run Command
		# print("@0.1", command, valueList)
		try:
			threadLock.acquire(True)
			result = list(self.cursor.execute(command, valueList))
		finally:
			threadLock.release()

		# print("@0.2", result)

		return result

	#Interaction Functions
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

	def closeDatabase(self):
		"""Closes the opened database.

		Example Input: closeDatabase()
		"""

		#Error check
		if (self.connection != None):
			self.cursor.close()

			self.connection = None
			self.cursor = None
			self.fileName = None
		else:
			print("ERROR: No database is open")

	def saveDatabase(self):
		"""Saves the opened database.

		Example Input: saveDatabase()
		"""

		#Save changes
		self.connection.commit()

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

		#Error check
		if (self.connection != None):
			if (relation != None):
				#Ensure correct spaces format
				command = "DROP TABLE IF EXISTS [{}]".format(relation)
				self.executeCommand(command)
			else:
				pass

			#Save Changes
			if (applyChanges == None):
				applyChanges = self.defaultCommit

			if (applyChanges):
				self.saveDatabase()

			#Update internal foreign schema catalogue
			self.updateInternalforeignSchemas()
		else:
			print("ERROR: No database is open")

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

	def renameRelation(self, relation, newName, applyChanges = None):
		"""Renames a relation (table) to the given name the user provides.

		relation (str)      - What the relation is called in the .db
		newName (str)       - What the relation will now be called in the .db
		applyChanges (bool) - Determines if the database will be saved after the change is made
			- If None: The default flag set upon opening the database will be used

		Example Input: renameRelation("Users", "Customers")
		"""

		#Error check
		if (self.connection != None):
			#Error Check
			if (relation != newName):
				#Build SQL command
				command = "ALTER TABLE [{}] RENAME TO [{}]".format(relation, newName)

				#Execute SQL
				# print("@0", command)
				self.executeCommand(command)

				#Save Changes
				if (applyChanges == None):
					applyChanges = self.defaultCommit

				if (applyChanges):
					self.saveDatabase()

				#Update internal foreign schema catalogue
				self.updateInternalforeignSchemas()

		else:
			print("ERROR: No database is open")

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

		#Error check
		if (self.connection != None):

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
			old_schema, old_notNull, old_primary, old_autoIncrement, old_unsigned, old_unique, old_foreign = self.getSchema(relation)
			table_contents = self.getAllValues(relation, orderBy = "id", filterRelation = False, valuesAsList = True, valuesAsRows = None, checkForeigen = False)

			#Rename old table
			self.renameRelation(relation, "tempCopy_{}".format(relation))

			#Apply changes
			new_schema = applyChanges(old_schema, schemaList)
			new_notNull = applyChanges(old_notNull, notNull)
			new_primary = applyChanges(old_primary, primary)
			new_autoIncrement = applyChanges(old_autoIncrement, autoIncrement)
			new_unsigned = applyChanges(old_unsigned, unsigned)
			new_unique = applyChanges(old_unique, unique)
			new_foreign = applyChanges(old_foreign, foreignList)

			# #Create new table
			self.createRelation(relation, schema = new_schema, notNull = new_notNull, primary = new_primary, 
				autoIncrement = new_autoIncrement, unsigned = new_unsigned, unique = new_unique, foreign = new_foreign, 
				applyChanges = applyChanges, autoPrimary = False)

			#Populate new table with old values
			for i in range(len(table_contents[relation])):
				self.addTuple(relation, table_contents[relation][i], applyChanges = applyChanges, checkForeigen = False)
			
			#Remove renamed table
			self.removeRelation("tempCopy_{}".format(relation), applyChanges = applyChanges)


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
			# print("@1", foreignList)
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

					# print("@7", command + "({})".format(schemaFormatted))

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

					# print("@8", command + "({})".format(schemaFormatted))

			#Remove trailing comma
			schemaFormatted = schemaFormatted[:-2]

			return schemaFormatted

		#Error check
		if (self.connection != None):
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

			# print("@5", command + "({})".format(schemaFormatted))
			#Add given attributes
			for schema in schemaList:
				for i, item in enumerate(schema.items()):
					if (schemaFormatted != ""):
						schemaFormatted += ", "

					attribute, dataType = item
					schemaFormatted += "[{}] {}".format(attribute, self.getType(dataType))
				
					schemaFormatted = formatSchema(schemaFormatted, attribute, False)

					# print("@6", command + "({})".format(schemaFormatted))

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
			# print("@0", command + "({})".format(schemaFormatted))
			self.executeCommand(command + "({})".format(schemaFormatted))

			#Save Changes
			if (applyChanges == None):
				applyChanges = self.defaultCommit

			if (applyChanges):
				self.saveDatabase()

			#Update internal foreign schema catalogue
			self.updateInternalforeignSchemas()

		else:
			print("ERROR: No database is open")

	def addTuple(self, relation, myTuple = {}, applyChanges = None, autoPrimary = False, notNull = False, 
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

		Example Input: addTuple("Lorem", autoPrimary = True)
		Example Input: addTuple("Lorem", {"Ipsum": "Dolor", "Sit": 5})
		Example Input: addTuple("Lorem", {"Ipsum": "Dolor", "Sit": 5}, unique = None)
		"""

		def configureForeign(self, command, valueList, relation, attribute, value):
			"""Allows the user to use foreign keys."""

			#Look for foreign keys
			foreign_results = self.findForeign(relation, attribute)

			if (len(foreign_results) != 0):
				foreign_relation, foreign_attribute = foreign_results

				#Add new line to the foreign key
				##Build SQL command

				foreign_command = "INSERT OR IGNORE INTO [{}] ({}) VALUES (?)".format(foreign_relation, foreign_attribute)

				##Run SQL command
				# print("@2", foreign_command, value)
				self.executeCommand(foreign_command, value)
				# self.saveDatabase()

				#Get the new foreign tuple's id
				foreign_tuple_id = self.getValue({foreign_relation: "id"}, {foreign_attribute: value}, filterRelation = True)
				foreign_tuple_id = foreign_tuple_id["id"][0]

				#Put the foreign id in for tuple in instead of the value
				valueList.append(foreign_tuple_id)


			else:
				#No foreign key found
				valueList.append(value)

			return valueList

		##Build SQL command
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
		for i, item in enumerate(itemList):
			attribute, value = item

			#Remember the associated value for the attribute
			if (checkForeigen):
				valueList = configureForeign(self, command, valueList, relation, attribute, value)
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
		# print("@1", command, valueList)
		self.executeCommand(command, valueList)

		#Save Changes
		if (applyChanges == None):
			applyChanges = self.defaultCommit

		if (applyChanges):
			self.saveDatabase()

	def changeTuple(self, myTuple, nextTo, value, forceMatch = None, defaultValues = {}, applyChanges = None, checkForeigen = True, updateForeign = None, exclude = [], nextToCondition = True):
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

		def configureForeign(valueList, relation, attribute):
			"""Allows the user to use foreign keys."""
			nonlocal self, nextTo, updateForeign, exclude, value

			#Look for foreign keys
			foreign_results = self.findForeign(relation, attribute)

			if (len(foreign_results) != 0):
				foreign_relation, foreign_attribute = foreign_results

				#Determien how to update the foreign key
				if (updateForeign == None):
					#Get the current foreign value
					# print("\n@3.1", relation, attribute, nextTo)
					currentValue = self.getValue({relation: attribute}, nextTo = nextTo, checkForeigen = False)
					currentValue = currentValue[attribute][0]
					
					#Get all instances of that value for this attribute
					command = "SELECT [{}] FROM [{}] WHERE [{}] = ?".format(attribute, relation, attribute)
					results = list(self.executeCommand(command, currentValue))

					#Check for unique key
					if (len(results) > 1):
						#Add a new foreign key
						updateForeign = False
					else:
						futureValue = self.getValue({foreign_relation: "id"}, {foreign_attribute: value}, filterRelation = True)

						#Check if the new value already exists
						column = self.getValue({foreign_relation: foreign_attribute})
						if (value in column[foreign_attribute]):
							#Add a new foreign key
							updateForeign = False
						else:
							#Check against other relations that link to this as well
							for other_relation, other_foreign_keys in self.foreignKeys_catalogue.items():
								#Skip the current relation and relations to exclude
								if ((other_relation != relation) and (other_relation not in exclude)):
									#Check the link for each attribute
									for other_attribute, other_item in other_foreign_keys.items():
										other_foreign_relation, other_foreign_attribute = other_item

										if (foreign_relation == other_foreign_relation):
											#Check for the same value in the other attribute
											column = self.getValue({other_relation: other_attribute}, checkForeigen = False)
											if (currentValue in column[other_attribute]):
												updateForeign = False
												break
											elif (len(futureValue["id"]) != 0):
												if (futureValue["id"][0] in column[other_attribute]):
													updateForeign = False
													break
									else:
										continue
									break

							else:
								#Check for if this value already exists in another foreign key
								column = self.getValue({relation: attribute}, {attribute: value})
								if (len(column[attribute]) > 0):
									#Change your id to the other foreign key
									updateForeign = None

								else:
									#Update the existing foreign key
									updateForeign = True

				if (updateForeign != None):
					#Update existing key
					if (updateForeign):
						#Get the current foreign value
						rowId = self.getValue({relation: attribute}, nextTo = nextTo, checkForeigen = False)

						#Build SQL command
						if (attribute in rowId):
							# #Check if another key has this value already
							# command = "SELECT [{}] FROM [{}] WHERE [{}] = ?".format(foreign_attribute, foreign_relation, "value")
							# print("@5", command, rowId[attribute])
							# self.executeCommand(command, (rowId[attribute][0], ))

							foreign_command = "UPDATE [{}] SET [{}] = ? WHERE [{}] = ?".format(foreign_relation, foreign_attribute, "id")

							#Run SQL command
							# print("@6", foreign_command, value, rowId[attribute][0])
							try:
								self.executeCommand(foreign_command, (value, rowId[attribute][0]))
							except:
								print("ERROR: Command Failed")
								print(foreign_command, (value, rowId[attribute][0]))
								raise

						else:
							foreign_command = "INSERT OR IGNORE INTO [{}] ({}) VALUES (?)".format(foreign_relation, foreign_attribute)

							#Run SQL command
							# print("@7", foreign_command, value)
							self.executeCommand(foreign_command, value)
					
					#Add new key
					else:
						#Build SQL command
						foreign_command = "INSERT OR IGNORE INTO [{}] ({}) VALUES (?)".format(foreign_relation, foreign_attribute)

						#Run SQL command
						# print("@8", foreign_command, value)
						self.executeCommand(foreign_command, value)

				#Get the new foreign tuple's id
				foreign_tuple_id = self.getValue({foreign_relation: "id"}, {foreign_attribute: value}, filterRelation = True)
				foreign_tuple_id = foreign_tuple_id["id"][0]

				#Put the foreign id in for tuple in instead of the value
				value = foreign_tuple_id

			else:
				#No foreign key found
				value = value

			return value

		def configureMatching(attribute, relation):
			"""Allows the user to control what happens if no match is found."""
			nonlocal value, checkForeigen, nextTo

			#Remember the associated value for the attribute
			valueList = []
			if (checkForeigen):
				value = configureForeign(valueList, relation, attribute)
				# print("@2.1", value, valueList, relation, attribute)

			#Determine location
			locationInfo = ""
			# print("@3", nextTo)
			for i, item in enumerate(nextTo.items()):
				criteriaAttribute, criteriaValue = item

				#Account for multiple references
				if (i != 0):
					if (nextToCondition):
						locationInfo += " AND "
					else:
						locationInfo += " OR "

				locationInfo += "[{}].[{}] = ?".format(relation, criteriaAttribute)

				if (checkForeigen):
					foreign_results = self.findForeign(relation, criteriaAttribute)
					# print("@2.2", criteriaValue)
					if (len(foreign_results) != 0):
						foreign_relation, foreign_attribute = foreign_results

						criteriaValue = self.getValue({foreign_relation: "id"}, {foreign_attribute: criteriaValue})["id"]

					# print("@2.3", criteriaValue)

				if (isinstance(criteriaValue, (tuple, list))):
					valueList.append(criteriaValue[0])
				else:
					valueList.append(criteriaValue)

			#Add or update
			if (forceMatch != None):
				#Select where match should be
				command = "SELECT [{}] FROM [{}] WHERE ({})".format(attribute, relation, locationInfo)
				# print("@9", command, criteriaValue)
				self.executeCommand(command, criteriaValue)
				row = self.cursor.fetchone()

				#Check if that spot exits
				if (row is None):
					#Match found
					for criteriaAttribute, criteriaValue in nextTo.items():
						defaultValues[criteriaAttribute] = criteriaValue
					
					defaultValues[attribute] = value

					self.addTuple(relation, defaultValues, applyChanges = False)
					return

			#No match found
			command = "UPDATE [{}] SET [{}] = ? WHERE ({})".format(relation, attribute, locationInfo)
			# print("@4", command, tuple([value] + valueList))

			self.executeCommand(command, tuple([value] + valueList))

		#Error check
		if (self.connection != None):
			# print("@0", myTuple, nextTo, value, forceMatch, defaultValues, applyChanges, checkForeigen, updateForeign, exclude, nextToCondition)
			#Account for multiple tuples to change
			for relation, attribute in myTuple.items():
				#Configure options
				configureMatching(attribute, relation)
				
				#Save Changes
				if (applyChanges == None):
					applyChanges = self.defaultCommit

				if (applyChanges):
					self.saveDatabase()

		else:
			print("ERROR: No database is open")

	def removeTuple(self, myTuple, nextTo = None, like = {}, applyChanges = None,
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
		Example Input: removeTuple({"Users": {"name": "John"}}, like = {"email": "@gmail.com"})
		"""

		#Error check
		if (self.connection != None):
			if (nextTo == None):
				nextTo = {}

			#Account for multiple tuples to remove
			for relation, item in myTuple.items():
				#Build SQL
				command = "DELETE FROM [{}] WHERE ".format(relation)
				valueList = []

				for i, subItem in enumerate(item.items()):
					attribute, value = subItem

					#Account for multiple references
					if (i != 0):
						if (nextToCondition):
							command += " AND "
						else:
							command += " OR "

					#Ensure correct format
					if ((type(value) != list) and (type(value) != tuple)):
						value = [value]

					for j, subValue in enumerate(value):
						#Account for multiple attributes
						if (j != 0):
							if (nextToCondition):
								command += " AND "
							else:
								command += " OR "

						command += "[{}].[{}] ".format(relation, attribute)
						valueList.append(subValue)

						#Account for partial match
						if (relation in like):
							if (attribute in like[relation]):
								## NOT WORKING YET ##
								command += "LIKE ?"
							else:
								command += "= ?"
						else:
							command += "= ?"

				#Run SQL
				# print("@3", command, valueList)
				self.executeCommand(command, valueList)

			#Save Changes
			if (applyChanges == None):
				applyChanges = self.defaultCommit

			if (applyChanges):
				self.saveDatabase()

		else:
			print("ERROR: No database is open")

	def getAllValues(self, relation, exclude = [], orderBy = None, nextTo = None, limit = None, direction = None, nextToCondition = True, guessType = False,
		checkForeigen = True, filterTuple = True, filterRelation = True, filterForeign = None, valuesAsList = False, valuesAsRows = True,
		greaterThan = {}, lessThan = {}, greaterThanOrEqualTo = {}, lessThanOrEqualTo = {}):
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
			greaterThan = greaterThan, lessThan = lessThan, greaterThanOrEqualTo = greaterThanOrEqualTo, lessThanOrEqualTo = lessThanOrEqualTo)

		return results_catalogue

	def getValue(self, myTuple, nextTo = {}, orderBy = None, limit = None, direction = None, nextToCondition = True, guessType = False, 
		checkForeigen = True, filterTuple = True, filterRelation = True, filterForeign = None, valuesAsList = False, valuesAsRows = True,
		greaterThan = {}, lessThan = {}, greaterThanOrEqualTo = {}, lessThanOrEqualTo = {}):
		"""Gets the value of an attribute in a tuple for a given relation.
		If multiple attributes match the criteria, then all of the values will be returned.
		If you order the list and limit it; you can get things such as the 'top ten occurrences', etc.

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
		Example Input: getValue({"Users": "name"}, filterForeign = True)
		Example Input: getValue({"Users": "name"}, filterForeign = False)

		Example Input: getValue({"Users": "name"}, {"age": 24})
		Example Input: getValue({"Users": "name"}, {"age": 24, height: 6})
		Example Input: getValue({"Users": "name"}, {"age": 24, height: 6}, nextToCondition = False)

		Example Input: getValue({"Users": "age"}, {"name": "John"})
		Example Input: getValue({"Users": "age"}, {"name": ["John", "Jane"]})
		

		Example Input: getValue({"Users": "name"}, greaterThan = {"age": 20})
		"""

		def configureSelection(self, relation, attribute):
			"""Allows the user to choose what attribute to search for."""

			#Ensure correct format
			if ((type(attribute) != list) or (type(attribute) != tuple)):
				attribute = [attribute]

			##Build SQL command
			command = "SELECT "

			#Account for multiple attributes
			for i, item in enumerate(attribute):
				command += "[{}].[{}]".format(relation, item) 

				#Account for the last element not having a comma
				if (i < len(attribute) - 1):
					command += ", "

			# print("@1", command)
			return command

		def configureSource(self, command, relation):
			"""Allows the user to choose the relation to search for the attribute in."""

			##Build SQL command
			command += " FROM [" + str(relation) + "]"

			# print("@2", command)

			return command

		def configureOrder(self, command, orderBy, direction):
			"""Allows the user to change the order in which the result is returned."""
			nonlocal relation

			def configureDirection(self, command, direction):
				"""Sets up the SQL command for the correct direction"""

				#Configure display direction
				if (type(direction) != dict):
					if (len(direction) == 1):
						if (direction[0] != None):
							if (direction[0]):
								command += " ASC"
							else:
								command += " DESC"
					else:
						if (direction[i] != None):
							if (direction[i]):
								command += " ASC"
							else:
								command += " DESC"
				else:
					condition = direction.get(item, None)						
					if (condition != None):
						if (condition):
							command += " ASC"
						else:
							command += " DESC"

				return command

			if (orderBy != None):
				##Build SQL
				command += " ORDER BY "

				#Ensure correct format
				if ((type(orderBy) != list) and (type(orderBy) != tuple)):
					orderBy = [orderBy]
				if ((type(direction) != list) and (type(direction) != tuple) and (type(direction) != dict)):
					direction = [direction]

				#Error checking
				if (type(direction) != dict):
					if (len(direction) != 1):
						if (len(direction) != len(orderBy)):
							print("ERROR: 'orderBy' and 'direction' size do not match.")
							return

				#Account for multiple conditions
				for i, item in enumerate(orderBy):
					##Build SQL
					command += "[{}].[{}]".format(relation, item)

					command = configureDirection(self, command, direction)

					#Account for the last element not having a ','
					if (i < len(orderBy) - 1):
						command += ", "

			return command

		def configureLimit(self, command, limit):
			"""Allows the user to limit how many results are returned."""

			##Number of items displayed
			if (limit != None):
				command += " LIMIT {}".format(limit)

			return command

		def configureForeign_command(self, relation, attributeList, checkForeigen):
			"""Allows the user to use foreign keys.
			For more information on JOIN: https://www.techonthenet.com/sqlite/joins.php
			"""

			commandSegment = ""
			if (checkForeigen):
				#Ensure correct format
				if ((type(attributeList) != list) and (type(attributeList) != tuple)):
					attributeList = [attributeList]

				#Account for multiple attributes
				for attribute in attributeList:
					#Look for foreign keys
					foreign_results = self.findForeign(relation, attribute)
					# print("@2", foreign_results, relation, attribute)

					if (len(foreign_results) != 0):
						foreign_relation, foreign_attribute = foreign_results
									
						#Build on the command
						#Choose how to filter results
						if (filterForeign == True):
							foreign_method = "INNER"
						else:
							foreign_method = "LEFT OUTER"

						#Building the command string
						commandSegment += " {} JOIN [{}] ON [{}].[{}] = [{}].[id]".format(foreign_method, foreign_relation, relation, attribute, foreign_relation)

			return commandSegment

		def configureForeign_results(self, results, relation, attribute, checkForeigen, filterTuple, filterForeign, valuesAsList):
			"""Allows the user to use foreign keys.
			For more information on JOIN: https://www.techonthenet.com/sqlite/joins.php
			"""

			valueList = []
			if (checkForeigen):
				foreign_results = self.findForeign(relation, attribute)

				if (len(foreign_results) != 0):
					foreign_relation, foreign_attribute = foreign_results

					#Account for foreign keys having foreign keys
					while True:
						valueList = []
						#Account for multiple results
						for item in results:
							#Skip empty cells
							if (item != None):
								#Modifying the results catalogue
								foreign_command = "SELECT [{}].[{}] FROM [{}] WHERE [id] = ?".format(foreign_relation, foreign_attribute, foreign_relation)

								#Format results
								if (filterTuple):
									# print("@1", foreign_command, item)
									result = self.executeCommand(foreign_command, item)
									result = tuple(result)

									#Account for value not existing
									if (len(result[0]) != 0):
										result = result[0][0]
									else:
										if (filterForeign != None):
											if (filterForeign):
												result = []
											else:
												result = item
										else:
											result = None
								else:
									result = self.executeCommand(foreign_command, item[0])
									result = tuple(result)

									#Account for value not existing
									if (len(result[0]) != 0):
										result = result[0]
									else:
										if (filterForeign != None):
											if (filterForeign):
												result = []
											else:
												result = item
										else:
											result = None
							else:
								result = None

							if (result != None):
								# if (len(str(result)) != 0):
								valueList.append(result)
							else:
								valueList.append(result)

						#Account for foreign keys having foreign keys
						foreign_results = self.findForeign(foreign_relation, foreign_attribute)
						if (len(foreign_results) != 0):
							foreign_relation, foreign_attribute = foreign_results
							results = valueList[:]
						else:
							break

			if (valuesAsList):
				valueList = list(valueList)
			else:
				valueList = tuple(valueList)

			return valueList

		def configureConditions(self, command, nextTo, filterTuple, relation, attribute, valuesAsList):
			"""Allows the user to select tuples based on conditions."""
			nonlocal greaterThan, lessThan, greaterThanOrEqualTo, lessThanOrEqualTo

			def configureForeign_location(self, i, relation, attribute, sign):
				"""Allows the user to use foreign keys with the 'next to' filter."""
				nonlocal nextToCondition, valueList, locationInfo, checkForeigen, greaterThan, lessThan, greaterThanOrEqualTo, lessThanOrEqualTo

				if (checkForeigen):
					foreign_results = self.findForeign(relation, attribute)

					#Account for no foreign keys found
					if (len(foreign_results) != 0):
						foreign_relation, foreign_attribute = foreign_results

						#Account for 'next to' filter
						locationInfo += "[{}].[{}] {} ?".format(foreign_relation, foreign_attribute, sign)
						
					else:
						locationInfo += "[{}].[{}] {} ?".format(relation, attribute, sign)
				else:
					locationInfo += "[{}].[{}] {} ?".format(relation, attribute, sign)

			def configure(catalogue, sign):
				"""
				Example Input: configure(nextTo, "=")
				"""
				nonlocal self, checkForeigen, nextToCondition, locationInfo

				for item in list(catalogue.items()):
					key, value = item

					#Account for foreign keys
					if (key != attribute):
						commandSegment = configureForeign_command(self, relation, key, checkForeigen)
						foreign_commandSegmentList.append(commandSegment)

					##Account for multiple references
					if (len(locationInfo) != 0):
						if (nextToCondition):
							locationInfo += " AND "
						else:
							locationInfo += " OR "

					valueList.append(value)
					configureForeign_location(self, i, relation, key, sign)

			#Ensure correct format
			if (nextTo == None):
				nextTo = {}
			elif ((type(nextTo) == list) or (type(nextTo) == tuple)):
				print("A", type(nextTo), "cannot be given for nextTo")
				return None

			if (greaterThan == None):
				greaterThan = {}
			elif ((type(greaterThan) == list) or (type(greaterThan) == tuple)):
				print("A", type(greaterThan), "cannot be given for greaterThan")
				return None

			if (greaterThanOrEqualTo == None):
				greaterThanOrEqualTo = {}
			elif ((type(greaterThanOrEqualTo) == list) or (type(greaterThanOrEqualTo) == tuple)):
				print("A", type(greaterThanOrEqualTo), "cannot be given for greaterThanOrEqualTo")
				return None

			if (lessThan == None):
				lessThan = {}
			elif ((type(lessThan) == list) or (type(lessThan) == tuple)):
				print("A", type(lessThan), "cannot be given for lessThan")
				return None

			if (lessThanOrEqualTo == None):
				lessThanOrEqualTo = {}
			elif ((type(lessThanOrEqualTo) == list) or (type(lessThanOrEqualTo) == tuple)):
				print("A", type(lessThanOrEqualTo), "cannot be given for lessThanOrEqualTo")
				return None

			#Setup conditions
			locationInfo = "" #Where the filter code is stored
			foreign_commandSegmentList = [] #Where the foreign keys are stored

			commandSegment = configureForeign_command(self, relation, attribute, checkForeigen)
			if ((commandSegment != "") and (commandSegment not in foreign_commandSegmentList)):
				foreign_commandSegmentList.append(commandSegment)

			#Apply condition configurations
			configure(nextTo, "=")
			configure(greaterThan, ">")
			configure(greaterThanOrEqualTo, ">=")
			configure(lessThan, "<")
			configure(lessThanOrEqualTo, "<=")

			#Account for foreign keys
			for commandSegment in foreign_commandSegmentList:
				command += "{} ".format(commandSegment)

			if (len(valueList) != 0):
				#Account for 'next to' filter
				if (len(locationInfo) != 0):
					command += "WHERE ({})".format(locationInfo)

			return command

		def runSQL():
			"""Runs the final sql command."""
			nonlocal self, command, valueList, filterTuple, valuesAsList

			# print("@4", command, valueList)
			if (len(valueList) != 0):
				##Run SQL command
				results = self.executeCommand(command, valueList)
		
			else:
				##Run SQL command
				results = self.executeCommand(command)

			results = list(results)

			#Format results
			if (filterTuple):
				# results = list(results)
				if (len(results) > 0):
					if (len(results[0]) == 1):
						for i, item in enumerate(results):
							results[i] = item[0]
			
			if (valuesAsList):
				results = list(results)
			else:
				results = tuple(results)
			
			# print("@6", results)
			return results

		def catalogueResults(self, results, relation, attribute, checkForeigen, filterTuple, filterForeign, valuesAsList):
			"""Allows the user to recieve a dictionary of all requested values."""
			nonlocal results_catalogue, guessType
			
			#Account for foreign keys
			configuredResults = configureForeign_results(self, results, relation, attribute, checkForeigen, filterTuple, filterForeign, valuesAsList)

			#Account for no foreign keys
			if (len(configuredResults) != 0):
				results = configuredResults

			if (guessType):
				for i, item in enumerate(results):
					if (type(item) == str):
						#Containers
						if (len(item) > 0):
							if ((item[0] in ["[", "{", "("]) or (item in ["True", "False"]) or (item.isdigit())):
								results[i] = eval(item)
				print(results)

			#Add results to catalogue
			if (filterRelation):
				if (attribute not in results_catalogue):
					results_catalogue[attribute] = []

				results_catalogue[attribute].extend(list(results))
			else:
				if (relation not in results_catalogue):
					results_catalogue[relation] = {}
				if (attribute not in results_catalogue[relation]):
					results_catalogue[relation][attribute] = []

				results_catalogue[relation][attribute].extend(list(results))

		#Error check
		if (self.connection != None):
			itemList = myTuple.items()

			results_catalogue = {}
			for i, item in enumerate(itemList):
				relation, attributeList = item

				#Ensure correct format
				if ((type(attributeList) != list) and (type(attributeList) != tuple)):
					attributeList = [attributeList]

				#Account for multiple items
				for attribute in attributeList:
					valueList = [] #Where the values to replace the '?'s are stored

					#Select Items
					command = configureSelection(self, relation, attribute)
					command = configureSource(self, command, relation)
					
					#Add final options
					command = configureConditions(self, command, nextTo, filterTuple, relation, attribute, valuesAsList)
					command = configureOrder(self, command, orderBy, direction)
					command = configureLimit(self, command, limit)
					
					#Finish
					results = runSQL()
					catalogueResults(self, results, relation, attribute, checkForeigen, filterTuple, filterForeign, valuesAsList)

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

		else:
			print("ERROR: No database is open")
			return None

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

	#User-friendly functions	
	def removeTable(self, table = None, applyChanges = None):
		"""User-friendly function for removeRelation()."""

		self.removeRelation(relation = table, applyChanges = applyChanges)

	def clearTable(self, table = None, applyChanges = None):
		"""User-friendly function for clearRelation()."""

		self.clearRelation(relation = table, applyChanges = applyChanges)

	def renameTable(self, oldName, newName, applyChanges = None):
		"""User-friendly function for renameRelation()."""

		self.renameRelation(oldName, newName, applyChanges = applyChanges)

	def createTable(self, name, contract = {}, applyChanges = None, autoPrimary = True, notNull = {}, default = {}, 
		primary = {}, autoIncrement = {}, unsigned = {}, unique = {}, foreign = None, noReplication = True):
		"""User-friendly function for createRelation()."""

		self.createRelation(name, schema = contract, applyChanges = applyChanges, autoPrimary = autoPrimary, notNull = notNull, default = default,
			primary = primary, autoIncrement = autoIncrement, unsigned = unsigned, unique = unique, foreign = foreign, noReplication = noReplication)

	def addRow(self, table, addThis, applyChanges = None, autoPrimary = False, notNull = False, 
		primary = False, autoIncrement = False, unsigned = True, unique = False, checkForeigen = True):
		"""User-friendly function for addTuple()."""

		self.addTuple(table, addThis, applyChanges = applyChanges, autoPrimary = autoPrimary, notNull = notNull, 
		primary = primary, autoIncrement = autoIncrement, unsigned = unsigned, unique = unique, checkForeigen = checkForeigen)

	def removeRow(self, removeThis, nextToThis = None, like = {}, applyChanges = None,
		checkForeigen = True, updateForeign = True, exclude = [], nextToCondition = True):
		"""User-friendly function for removeTuple()."""

		self.removeTuple(removeThis, nextToThis = nextToThis, like = like, applyChanges = applyChanges,
		checkForeigen = checkForeigen, updateForeign = updateForeign, exclude = exclude, nextToCondition = nextToCondition)

	def changeCell(self, changeThis, nextToThis, toThis, forceMatch = None, defaultValues = {}, applyChanges = None, 
		checkForeigen = True, updateForeign = None, exclude = []):
		"""User-friendly function for changeTuple()."""

		self.changeTuple(changeThis, nextToThis, toThis, forceMatch = forceMatch, defaultValues = defaultValues, 
			checkForeigen = checkForeigen, applyChanges = applyChanges, updateForeign = updateForeign, exclude = exclude)

	def getTableNames(self, exclude = []):
		"""User-friendly function for getRelationNames()."""

		tableNames = self.getRelationNames(exclude = exclude)
		return tableNames

	def getColumnNames(self, table, exclude = []):
		"""User-friendly function for getAttributeNames()."""

		columnNames = self.getAttributeNames(table, exclude = exclude)
		return columnNames

	def getRowCount(self, table):
		"""User-friendly function for getTupleCount()."""

		count = self.getTupleCount(table)
		return count

	def onCleanForeignKeys(self, event, cleanList = None, exclude = [], filterType = True):
		"""An event function in the wxPython format for cleanForeignKeys()."""

		self.cleanForeignKeys(cleanList = cleanList, exclude = exclude, filterType = filterType)
		event.Skip()

def main():
	"""The main program controller."""

	#Create the database
	database_API = Database()
	database_API.openDatabase("test.db", applyChanges = False)
	# database_API.removeTable("Users")
	# database_API.removeTable("Names")
	# database_API.removeTable("Address")

	# #Create tables from the bottom up
	# database_API.createTable("Names", [{"first_name": str}, {"extra_data": str}], unique = {"first_name": True})
	# database_API.createTable("Address", {"street": str}, unique = {"street": True})
	# database_API.saveDatabase()
	# database_API.createTable("Users", {"age": int, "height": int}, foreign = {"name": {"Names": "first_name"}, "address": {"Address": "street"}})

	# database_API.addRow("Names", {"first_name": "Dolor", "extra_data": "Sit"}, unique = None)
	
	# database_API.addRow("Users", {"name": "Ipsum", "age": 26, "height": 5}, unique = None)
	# database_API.addRow("Users", {"name": "Lorem", "age": 26, "height": 6}, unique = None)
	# database_API.addRow("Users", {"name": "Lorem", "age": 24, "height": 3}, unique = None)
	# database_API.addRow("Users", {"name": "Dolor", "age": 21, "height": 4}, unique = None)
	# database_API.addRow("Users", {"name": "Sit", "age": None, "height": 1}, unique = None)

	# # # Simple actions
	# # print(database_API.getValue({"Users": "name"}))
	# # print(database_API.getValue({"Users": "name"}, filterRelation = False))
	# # print(database_API.getValue({"Users": ["name", "age"]}))

	# # #Ordering data
	# # print(database_API.getValue({"Users": "name"}, orderBy = "age"))
	# # print(database_API.getValue({"Users": ["name", "age"]}, orderBy = "age", limit = 2))
	# # print(database_API.getValue({"Users": ["name", "age"]}, orderBy = "age", direction = True))

	# # print(database_API.getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"]))
	# # print(database_API.getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"], direction = [None, False]))
	# # print(database_API.getValue({"Users": ["name", "age"]}, orderBy = ["age", "height"], direction = {"height": False}))

	# # #Multiple Relations
	# # print(database_API.getValue({"Users": "name", "Names": "first_name"}))
	# # print(database_API.getValue({"Users": "name", "Names": "first_name"}, filterRelation = False))
	# # print(database_API.getValue({"Users": "name", "Names": ["first_name", "extra_data"]}))

	# # #Changing attributes
	# # print(database_API.getValue({"Users": "name"}))
	# # database_API.changeCell({"Names": "first_name"}, {"first_name": "Lorem"}, "Amet")
	# # print(database_API.getValue({"Users": "name"}))
	# # print(database_API.getValue({"Users": "name"}, filterForeign = True))

	# # database_API.changeCell({"Users": "name"}, {"age": 26}, "Consectetur", forceMatch = True)
	# print(database_API.getValue({"Users": "name"}))
	# print(database_API.getValue({"Users": "name"}, valuesAsList = True))
	# # print(database_API.getValue({"Users": "name"}, filterForeign = True))
	# # print(database_API.getValue({"Users": "name"}, filterForeign = False))

	# # database_API.changeCell({"Users": "name"}, {"age": 26}, "Amet")

	database_API.saveDatabase()

if __name__ == '__main__':
	main()
