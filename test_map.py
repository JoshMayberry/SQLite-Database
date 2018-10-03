import sys
import contextlib

import sqlalchemy
import sqlalchemy.ext.declarative

from datetime import datetime

sessionMaker = sqlalchemy.orm.sessionmaker()
Mapper = sqlalchemy.ext.declarative.declarative_base()

#Utility Mixins
class Utility_Base():
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

	#Virtual Functions
	@classmethod
	def reset(cls):
		pass

class Utility_AutoForeign():
	def __init__(self, kwargs = {}, **foreignKeys):
		"""Automatically creates tuples for the provided relations if one does not exist.
		Special thanks to van for how to automatically add children on https://stackoverflow.com/questions/8839211/sqlalchemy-add-child-in-one-to-many-relationship
		"""

		for variable, (relationHandle, label, index, catalogue) in foreignKeys.items():
			# print("@Utility_AutoForeign.1", variable, (relationHandle, label, catalogue))
			if (label is None):
				continue

			with self.makeSession() as session:
				job = session.query(relationHandle).filter(relationHandle.label == label).one_or_none()
				if (job is None):
					job = relationHandle(label = label)
					session.add(job)
					session.commit()
					catalogue.append(job)
				kwargs[index] = job.id

#Mapper Mixins
class _Date():
	createdOn 	= sqlalchemy.Column(sqlalchemy.DateTime(), default = datetime.utcnow)
	lastModified = sqlalchemy.Column(sqlalchemy.DateTime(), default = datetime.utcnow)

	createdOn._creation_order = 1000
	lastModified._creation_order = 1001

class _Editable(_Date):
	
	archived 			= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	removePending 		= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	trackChangePending 	= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)

	archived._creation_order = 801
	removePending._creation_order = 800
	trackChangePending._creation_order = 802

class _Files():
	msds 			= sqlalchemy.Column(sqlalchemy.String(250), default = "[]")
	externalFiles 	= sqlalchemy.Column(sqlalchemy.String(250), default = "[]")

	msds._creation_order = 701
	externalFiles._creation_order = 700

class _Choice(_Editable):
	id 					= sqlalchemy.Column(sqlalchemy.Integer, primary_key = True, nullable = False, unique = True)
	label 				= sqlalchemy.Column(sqlalchemy.String(250), unique = True)
	alt_spelling_yes 	= sqlalchemy.Column(sqlalchemy.String(250))
	alt_spelling_no 	= sqlalchemy.Column(sqlalchemy.String(250))
	shared_spelling 	= sqlalchemy.Column(sqlalchemy.String(250))
	display_text 		= sqlalchemy.Column(sqlalchemy.String(250))

	id._creation_order = 1
	label._creation_order = 2
	display_text._creation_order = 3
	alt_spelling_yes._creation_order = 300
	alt_spelling_no._creation_order = 301
	shared_spelling._creation_order = 302

class _Setting(_Date):
	id 						= sqlalchemy.Column(sqlalchemy.Integer, primary_key = True, nullable = False, unique = True)
	label 					= sqlalchemy.Column(sqlalchemy.String(250), unique = True, nullable = False)
	value 					= sqlalchemy.Column(sqlalchemy.String(250))
	comments 				= sqlalchemy.Column(sqlalchemy.String(250))

	id._creation_order = 1
	label._creation_order = 2
	value._creation_order = 3
	comments._creation_order = 1500

#Tables - Choices
class Choices_Color(Mapper, _Choice, Utility_Base):
	__tablename__ = 'Choices_Color'

class Choices_Container(Mapper, _Choice, Utility_Base):
	__tablename__ = 'Choices_Container'

class Choices_Customer(Mapper, _Choice, Utility_Base):
	__tablename__ = 'Choices_Customer'

	phone 				= sqlalchemy.Column(sqlalchemy.String(250))
	address 			= sqlalchemy.Column(sqlalchemy.String(250))
	order_catalogue 	= sqlalchemy.Column(sqlalchemy.String(250))

	phone._creation_order = 100
	address._creation_order = 101
	order_catalogue._creation_order = 102

class Choices_DMTE_Contact(Mapper, _Choice, Utility_Base):
	__tablename__ = 'Choices_DMTE_Contact'
	
	phone 				= sqlalchemy.Column(sqlalchemy.String(250))
	
	phone._creation_order = 100

class Choices_Item(Mapper, _Choice, Utility_Base):
	__tablename__ = 'Choices_Item'

class Choices_Job(Mapper, _Choice, Utility_Base):
	__tablename__ = 'Choices_Job'

	# containers = sqlalchemy.orm.relationship("Containers", back_populates = "jobNumber")

	@classmethod
	def reset(cls):
		"""Clears all jobs and places in default ones."""

		with cls.makeSession() as session:
			session.query(cls).delete()
			session.add(cls(id = 1, label = "unknown"))

class Choices_Material(Mapper, _Choice, Utility_Base):
	__tablename__ = 'Choices_Material'

class Choices_Supplier(Mapper, _Choice, Utility_Base):
	__tablename__ = 'Choices_Supplier'

class Choices_Vendor(Mapper, _Choice, Utility_Base):
	__tablename__ = 'Choices_Vendor'

	phone 				= sqlalchemy.Column(sqlalchemy.String(250))
	address 			= sqlalchemy.Column(sqlalchemy.String(250))
	product_catalogue 	= sqlalchemy.Column(sqlalchemy.String(250))

	phone._creation_order = 100
	address._creation_order = 101
	product_catalogue._creation_order = 102

#Tables - Settings
class Constructor_VariableNames(Mapper, Utility_Base):
	__tablename__ = 'Constructor_VariableNames'

	id 						= sqlalchemy.Column(sqlalchemy.Integer, primary_key = True, nullable = False, unique = True)
	table 					= sqlalchemy.Column(sqlalchemy.String(250), unique = True, nullable = False)
	filterName 				= sqlalchemy.Column(sqlalchemy.String(250))
	defaultName 			= sqlalchemy.Column(sqlalchemy.String(250))
	barcodeName 			= sqlalchemy.Column(sqlalchemy.String(250), unique = True)
	defaultChild 			= sqlalchemy.Column(sqlalchemy.String(250))
	defaultExport 			= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	constructor_order 		= sqlalchemy.Column(sqlalchemy.Integer)
	inventoryTitle 			= sqlalchemy.Column(sqlalchemy.String(250), unique = True)
	search_defaultSearchBy 	= sqlalchemy.Column(sqlalchemy.String(250))
	search_defaultOrderBy 	= sqlalchemy.Column(sqlalchemy.String(250))

	id._creation_order = 1
	table._creation_order = 2
	filterName._creation_order = 3
	defaultName._creation_order = 4
	barcodeName._creation_order = 5
	defaultChild._creation_order = 6
	defaultExport._creation_order = 7
	constructor_order._creation_order = 8
	inventoryTitle._creation_order = 9
	search_defaultSearchBy._creation_order = 10
	search_defaultOrderBy._creation_order = 11

class DatabaseInfo(Mapper, _Setting, Utility_Base):
	__tablename__ = 'DatabaseInfo'

class Settings_AutoSave(Mapper, _Setting, Utility_Base):
	__tablename__ = 'Settings_AutoSave'

class Settings_Barcode(Mapper, _Setting, Utility_Base):
	__tablename__ = 'Settings_Barcode'

class Settings_BugReport(Mapper, _Setting, Utility_Base):
	__tablename__ = 'Settings_BugReport'

class Settings_ChangeLog(Mapper, _Setting, Utility_Base):
	__tablename__ = 'Settings_ChangeLog'

class Settings_Comparer(Mapper, _Setting, Utility_Base):
	__tablename__ = 'Settings_Comparer'

class Settings_Container(Mapper, _Setting, Utility_Base):
	__tablename__ = 'Settings_Container'

class Settings_Converter(Mapper, _Setting, Utility_Base):
	__tablename__ = 'Settings_Converter'

class Settings_Filter(Mapper, _Setting, Utility_Base):
	__tablename__ = 'Settings_Filter'

class Settings_General(Mapper, _Setting, Utility_Base):
	__tablename__ = 'Settings_General'

class Settings_Inventory(Mapper, _Setting, Utility_Base):
	__tablename__ = 'Settings_Inventory'

class Settings_Printer(Mapper, _Setting, Utility_Base):
	__tablename__ = 'Settings_Printer'

class Settings_Scanner(Mapper, _Setting, Utility_Base):
	__tablename__ = 'Settings_Scanner'

class Settings_Frames(Mapper, _Date, Utility_Base):
	__tablename__ = 'Settings_Frames'

	id 						= sqlalchemy.Column(sqlalchemy.Integer, primary_key = True, nullable = False, unique = True)
	label 					= sqlalchemy.Column(sqlalchemy.String(250), unique = True, nullable = False)
	title 					= sqlalchemy.Column(sqlalchemy.String(250), unique = True, nullable = False)
	size 					= sqlalchemy.Column(sqlalchemy.String(250))
	position 				= sqlalchemy.Column(sqlalchemy.String(250))
	sash_position 			= sqlalchemy.Column(sqlalchemy.Integer)
	defaultStatus_label 	= sqlalchemy.Column(sqlalchemy.String(250), default = "Current User")

	id._creation_order = 1
	label._creation_order = 2
	title._creation_order = 3
	size._creation_order = 4
	position._creation_order = 5
	sash_position._creation_order = 6
	defaultStatus_label._creation_order = 7

class Users(Mapper, _Date, Utility_Base):
	__tablename__ = 'Users'
	id 				= sqlalchemy.Column(sqlalchemy.Integer, primary_key = True, nullable = False, unique = True)
	label 			= sqlalchemy.Column(sqlalchemy.String(250), unique = True, nullable = False)
	password 		= sqlalchemy.Column(sqlalchemy.String(250), nullable = False)
	removePending 	= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)

	inventory_addJob 			= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	inventory_removeJob 		= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	inventory_editJob 			= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	inventory_addContainer 		= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	inventory_removeContainer 	= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	inventory_editContainer 	= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	inventory_export 			= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	inventory_import_append 	= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	inventory_import_replace 	= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	inventory_archive 			= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	inventory_unarchive 		= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	type_addItem 				= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	type_removeItem 			= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	type_editItem 				= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	externalFile_addItem 		= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	externalFile_removeItem 	= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	externalFile_editItem 		= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	externalFile_openItem 		= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	approveRemoval 				= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	approveTrackedChange 		= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	viewRemoval 				= sqlalchemy.Column(sqlalchemy.Boolean(), default = True)
	viewTrackedChange 			= sqlalchemy.Column(sqlalchemy.Boolean(), default = True)
	search_changeSettings 		= sqlalchemy.Column(sqlalchemy.Boolean(), default = True)


#Tables - Main
class Containers(Mapper, _Editable, _Files, Utility_AutoForeign, Utility_Base):
	__tablename__ = 'Containers'

	id 				= sqlalchemy.Column(sqlalchemy.Integer, primary_key = True, nullable = False, unique = True)
	label 			= sqlalchemy.Column(sqlalchemy.String(250), unique = True)
	poNumber 		= sqlalchemy.Column(sqlalchemy.String(250))
	weight_total 	= sqlalchemy.Column(sqlalchemy.String(30))
	weight_needed 	= sqlalchemy.Column(sqlalchemy.String(30))
	weight_units 	= sqlalchemy.Column(sqlalchemy.String(250))
	cost_total 		= sqlalchemy.Column(sqlalchemy.String(10))
	cost_units 		= sqlalchemy.Column(sqlalchemy.String(250))
	location 		= sqlalchemy.Column(sqlalchemy.String(250))
	moving 			= sqlalchemy.Column(sqlalchemy.Boolean(), default = False)
	dmte_owned 		= sqlalchemy.Column(sqlalchemy.Boolean())
	orderableBy 	= sqlalchemy.Column(sqlalchemy.String(250))
	comments 		= sqlalchemy.Column(sqlalchemy.String(250))
	
	# jobNumber 		= sqlalchemy.Column(sqlalchemy.String(250), default = 1)
	jobNumber_id 	= sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey("Choices_Job.id", onupdate = "CASCADE", ondelete = "SET NULL"), default = 1)
	type 			= sqlalchemy.Column(sqlalchemy.String(250))
	material 		= sqlalchemy.Column(sqlalchemy.String(250))
	color 			= sqlalchemy.Column(sqlalchemy.String(250))
	item_type 		= sqlalchemy.Column(sqlalchemy.String(250))
	vendor 			= sqlalchemy.Column(sqlalchemy.String(250))
	customer 		= sqlalchemy.Column(sqlalchemy.String(250))
	dmte_contact 	= sqlalchemy.Column(sqlalchemy.String(250))

	jobNumber_catalogue = sqlalchemy.orm.relationship(Choices_Job, backref = "containers", uselist=True)

	id._creation_order = 1
	label._creation_order = 3
	poNumber._creation_order = 4
	weight_total._creation_order = 5
	weight_needed._creation_order = 15
	cost_total._creation_order = 16
	location._creation_order = 6
	moving._creation_order = 7
	dmte_owned._creation_order = 17
	weight_units._creation_order = 18
	cost_units._creation_order = 19
	orderableBy._creation_order = 20
	comments._creation_order = 21

	jobNumber_id._creation_order = 2
	type._creation_order = 8
	material._creation_order = 9
	color._creation_order = 10
	item_type._creation_order = 11
	vendor._creation_order = 12
	customer._creation_order = 13
	dmte_contact._creation_order = 14

	def __init__(self, *args, jobNumber = None, **kwargs):
		Utility_AutoForeign.__init__(self, jobNumber = (Choices_Job, jobNumber, "jobNumber_id", self.jobNumber_catalogue), kwargs = kwargs)

		super().__init__(*args, **kwargs)

relationCatalogue = {item.__name__: item for item in Utility_Base.__subclasses__()}

if __name__ == '__main__':
	engine = sqlalchemy.create_engine('sqlite:///test_map_example.db')
	Mapper.metadata.bind = engine

	Mapper.metadata.drop_all()
	Mapper.metadata.create_all()
	# inspector = sqlalchemy.inspect(engine)
	# print(inspector.get_table_names())

	Choices_Job.reset()

	DBSession = sqlalchemy.orm.sessionmaker(bind = engine)
	session = DBSession()

	newContainer = Containers(label = "lorem", jobNumber = 12345, poNumber = 123)
	session.add(newContainer)
	session.commit()

	container = session.query(Containers).filter(Containers.poNumber == 123).first()
	print(container.jobNumber_id, container.jobNumber_catalogue)


	# import time
	# startTime = time.perf_counter()
	# for i in range(3):
	# 	x = Containers(label = f"{i}")
	# 	session.add(x)
	# print("@add", f"{time.perf_counter() - startTime:.6f}")

	# # print(x.label)

	# # print(session.dirty)
	# # print(session.new)

	# startTime = time.perf_counter()
	# session.commit()
	# print("@commit", f"{time.perf_counter() - startTime:.6f}")

	# x.poNumber = 1234

	# # print(session.dirty)
	# # print(session.new)

	# startTime = time.perf_counter()
	# query = session.query(Containers)
	# print(id(query))
	# query = query.all()
	# print(id(query))
	# print(query)
	# print("@query", f"{time.perf_counter() - startTime:.6f}")

