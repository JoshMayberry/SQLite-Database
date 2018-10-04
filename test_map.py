import sys
import sqlalchemy
import sqlalchemy.ext.declarative

from datetime import datetime

import API_Database as Database

Mapper = sqlalchemy.ext.declarative.declarative_base()

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
class Choices_Color(Mapper, _Choice, Database.Schema_Base):
	__tablename__ = 'Choices_Color'

	defaultRows = (
		{"id": 0, "label": "n/a"},
	)

class Choices_Container(Mapper, _Choice, Database.Schema_Base):
	__tablename__ = 'Choices_Container'

	defaultRows = (
		{"id": 0, "label": "n/a"},
	)

class Choices_Customer(Mapper, _Choice, Database.Schema_Base):
	__tablename__ = 'Choices_Customer'

	phone 				= sqlalchemy.Column(sqlalchemy.String(250))
	address 			= sqlalchemy.Column(sqlalchemy.String(250))
	order_catalogue 	= sqlalchemy.Column(sqlalchemy.String(250))

	phone._creation_order = 100
	address._creation_order = 101
	order_catalogue._creation_order = 102

	defaultRows = (
		{"id": 0, "label": "unknown"},
	)

class Choices_DMTE_Contact(Mapper, _Choice, Database.Schema_Base):
	__tablename__ = 'Choices_DMTE_Contact'
	
	phone 				= sqlalchemy.Column(sqlalchemy.String(250))
	
	phone._creation_order = 100

	defaultRows = (
		{"id": 0, "label": "unknown"},
	)

class Choices_Item(Mapper, _Choice, Database.Schema_Base):
	__tablename__ = 'Choices_Item'

	defaultRows = (
		{"id": 0, "label": "unknown"},
	)

class Choices_Job(Mapper, _Choice, Database.Schema_Base):
	__tablename__ = 'Choices_Job'

	defaultRows = (
		{"id": 0, "label": "unknown"},
	)

class Choices_Material(Mapper, _Choice, Database.Schema_Base):
	__tablename__ = 'Choices_Material'

	defaultRows = (
		{"id": 0, "label": "n/a"},
	)

class Choices_Supplier(Mapper, _Choice, Database.Schema_Base):
	__tablename__ = 'Choices_Supplier'

	defaultRows = (
		{"id": 0, "label": "n/a"},
	)

class Choices_Vendor(Mapper, _Choice, Database.Schema_Base):
	__tablename__ = 'Choices_Vendor'

	phone 				= sqlalchemy.Column(sqlalchemy.String(250))
	address 			= sqlalchemy.Column(sqlalchemy.String(250))
	product_catalogue 	= sqlalchemy.Column(sqlalchemy.String(250))

	phone._creation_order = 100
	address._creation_order = 101
	product_catalogue._creation_order = 102

	defaultRows = (
		{"id": 0, "label": "n/a"},
	)

#Tables - Settings
class Constructor_VariableNames(Mapper, Database.Schema_Base):
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

	defaultRows = (
		{"id": 0, "table": "unknown"},
		{"table": "Users", 					"filterName": "user", 					"defaultName": "User", 				"defaultChild": "guest"},
		{"table": "Containers", 			"filterName": "container", 				"defaultName": "Container", 		"inventoryTitle": "Containers", 	"constructor_order": 1, 	"defaultExport": True},
		
		{"table": "Choices_Job", 			"filterName": "choice_job", 			"defaultName": "Job", 				"inventoryTitle": "Jobs", 			"constructor_order": 2},
		{"table": "Choices_Customer", 		"filterName": "choice_customer", 		"defaultName": "Customer", 			"inventoryTitle": "Customers", 		"constructor_order": 3},
		{"table": "Choices_Vendor", 		"filterName": "choice_vendor", 			"defaultName": "Vendor", 			"inventoryTitle": "Vendors", 		"constructor_order": 4},
		{"table": "Choices_Container", 		"filterName": "choice_container", 		"defaultName": "Container Type"},
		{"table": "Choices_Item", 			"filterName": "choice_item", 			"defaultName": "Contents Type"},
		{"table": "Choices_DMTE_Contact", 	"filterName": "choice_dmte_contact", 	"defaultName": "DMTE Contact"},
		{"table": "Choices_Material", 		"filterName": "choice_material", 		"defaultName": "Material"},
		{"table": "Choices_Supplier", 		"filterName": "choice_supplier", 		"defaultName": "Supplier"},
		{"table": "Choices_Color", 			"filterName": "choice_color", 			"defaultName": "Color"},
		
		{"table": "Settings_ChangeLog", 	"filterName": "setting_changeLog"},
		{"table": "Settings_BugReport", 	"filterName": "setting_bugReport"},
		{"table": "Settings_Converter", 	"filterName": "setting_converter"},
		{"table": "Settings_Comparer", 		"filterName": "setting_comparer"},
		{"table": "Settings_AutoSave", 		"filterName": "setting_autoSave"},
		{"table": "Settings_Scanner", 		"filterName": "setting_scanner"},
		{"table": "Settings_Frames", 		"filterName": "setting_frame"},
		{"table": "Settings_Barcode", 		"filterName": "setting_barcode"},
	)

class DatabaseInfo(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'DatabaseInfo'

	defaultRows = (
		{"label": "programVersion", "value": "2.1.0", "comments": "The program release version this was built for"},
		{"label": "barcodeVersion", "value": "1.1.0", "comments": "The barcode version used in this program"},
	)

class Settings_AutoSave(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'Settings_AutoSave'

	defaultRows = (
		{"label": "save_autoSave", "value": 1, "comments": "-- deprecated --"},
		{"label": "save_autoCommit", "value": 1, "comments": "-- deprecated --"},
		{"label": "save_autoSave_scanDelay", "value": 100, "comments": "-- deprecated --"},
		
		{"label": "save_importDelay", "value": 0, "comments": "-- deprecated --"},
		{"label": "save_autoSave_importDelay", "value": 0, "comments": "-- deprecated --"},
		
		{"label": "save_saveStatus_scanDelay", "value": 100, "comments": "How long to wait between checking the save status of the database"},
		
		{"label": "save_multiProcess_retryAttempts", "value": -1, "comments": "Determines how many times to try executing a command if another process is using the database\n0 or None: Do not retry\n-1: Retry forever"},
		{"label": "save_multiProcess_retryDelay", "value": 100, "comments": "How many milli-seconds to wait before trying to to execute a command again"},
	)

class Settings_Barcode(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'Settings_Barcode'

	defaultRows = (
		{"label": "barcodeType", "value": "qr", "comments": "What type of barcode to create/read"},
		{"label": "barcodeKey_barcodeVersion", "value": "*", "comments": "What key to use for the barcode version"},
		{"label": "barcodeKey_barcodeName", "value": "@", "comments": "What key to use for what handle to search in"},
	)

class Settings_BugReport(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'Settings_BugReport'

	defaultRows = (
		{"label": "email_fromAddress", "value": "material.tracker@decaturmold.com", "comments": "The email to send the bug report from"},
		{"label": "email_fromPassword", "value": "f@tfr3ddy$c@t", "comments": "The password for the email to send the bug report from"},
		{"label": "email_to", "value": "josh.mayberry@decaturmold.com", "comments": "The email to send the bug report to"},
		
		{"label": "attach_errorLog", "value": 1, "comments": "If the error log should be attached to the bug report"},
		{"label": "server", "value": "194.2.1.1", "comments": "What server to send the email from"},
		{"label": "port", "value": 587, "comments": "What port to send the email from"},
	)

class Settings_ChangeLog(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'Settings_ChangeLog'

	defaultRows = (
		{"label": "filePath", "value": "_CHANGELOG.md", "comments": "The path to the changelog file"},
	)

class Settings_Comparer(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'Settings_Comparer'

class Settings_Container(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'Settings_Container'

class Settings_Converter(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'Settings_Converter'

class Settings_Filter(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'Settings_Filter'

class Settings_General(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'Settings_General'

	defaultRows = (
		{"label": "startup_user", "value": "Admin", "comments": "What user will be logged in when the program first launches"},
		{"label": "autoLogout", "value": -1, "comments": "How long to wait in seconds before the current user is logged out.\n-1: Disable Feature"},
		{"label": "startup_window", "value": "Inventory", "comments": "What window will show up when the program first launches"},
		{"label": "debugging_default", "value": None, "comments": ""},
		{"label": "debugging_enabled", "value": 1, "comments": ""},
		{"label": "toolTip_delayAppear", "value": 0, "comments": ""},
		{"label": "toolTip_delayDisappear", "value": 6000, "comments": ""},
		{"label": "toolTip_delayReappear", "value": 500, "comments": ""},
		{"label": "toolTip_enabled", "value": 1, "comments": ""},
		{"label": "save_backup", "value": 0, "comments": ""},
		{"label": "debugging_lastState", "value": 1, "comments": ""},
		{"label": "frameSetting_saveDelay", "value": 3000, "comments": ""},
	)

class Settings_Inventory(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'Settings_Inventory'

	defaultRows = (
		{"label": "export_excelFileName", "value": "inventory", "comments": ""},
		{"label": "inventory_startup_table", "value": "--Last Opened--", "comments": ""},
		{"label": "inventory_currentTable", "value": "['container', True, False, None]", "comments": ""},
		{"label": "inventory_search_caseSensitive", "value": 0, "comments": ""},
		{"label": "inventory_search_useWildcards", "value": 0, "comments": ""},
		{"label": "inventory_showArchived", "value": 1, "comments": ""},
		{"label": "inventory_startup_listFull_collapseState", "value": 1, "comments": ""},
		{"label": "inventory_currentTable_saveDelay", "value": 1000, "comments": ""},
	)

class Settings_Printer(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'Settings_Printer'

	defaultRows = (
		{"label": "printer_showSetup", "value": 0, "comments": ""},
		{"label": "printer_showPreview", "value": 1, "comments": ""},
		{"label": "printer_color", "value": 1, "comments": ""},
		{"label": "printer_file", "value": "", "comments": ""},
		{"label": "printer_paperSize", "value": "(215, 279)", "comments": ""},
		{"label": "printer_printerName", "value": "KONICA MINOLTA C658SeriesPCL", "comments": ""},
		{"label": "printer_bin", "value": "auto", "comments": ""},
		{"label": "printer_duplex", "value": None, "comments": ""},
		{"label": "printer_quality", "value": 600, "comments": ""},
		{"label": "printer_paperId", "value": "Letter; 8 1/2 by 11 in", "comments": ""},
		{"label": "printer_printMode", "value": "Send to printer", "comments": ""},
		{"label": "printer_vertical", "value": 1, "comments": ""},
		{"label": "printer_collate", "value": 0, "comments": ""},
		{"label": "printer_min", "value": 0, "comments": ""},
		{"label": "printer_max", "value": 0, "comments": ""},
		{"label": "printer_copies", "value": 1, "comments": ""},
		{"label": "printer_printToFile", "value": 0, "comments": ""},
		{"label": "printer_selected", "value": 0, "comments": ""},
		{"label": "printer_printAll", "value": 1, "comments": ""},
		{"label": "printer_from", "value": 0, "comments": ""},
		{"label": "printer_to", "value": 0, "comments": ""},
	)

class Settings_Scanner(Mapper, _Setting, Database.Schema_Base):
	__tablename__ = 'Settings_Scanner'

	defaultRows = (
		{"label": "scanner_id", "value": "0000000927C4", "comments": ""},
		{"label": "barcodeType", "value": "qr", "comments": ""},
		{"label": "disableOnError", "value": 1, "comments": ""},
		{"label": "connectDelay", "value": 1000, "comments": ""},
		{"label": "connectAttempts", "value": 10, "comments": ""},
		{"label": "modifyBarcodeOverride", "value": 1, "comments": ""},
		{"label": "readLength", "value": 10000, "comments": ""},
		{"label": "timeout", "value": 1000, "comments": ""},
		{"label": "enableScanner_default", "value": None, "comments": ""},
		{"label": "enableScanner", "value": 0, "comments": ""},
		{"label": "connect_flushRecieve", "value": 1, "comments": ""},
		{"label": "connect_flushSend", "value": 1, "comments": ""},
		{"label": "unknownDelay", "value": 30, "comments": ""},
		{"label": "defaultReason", "value": "Weight", "comments": ""},
		{"label": "confirmRemove", "value": 1, "comments": ""},
		{"label": "functionKeys_requireScan", "value": 0, "comments": ""},
		{"label": "usb_vendorId", "value": 1529, "comments": ""},
		{"label": "usb_productId", "value": 16900, "comments": ""},
		{"label": "autoPrint_changeLocation", "value": 1, "comments": ""},
		{"label": "printDelay", "value": 100, "comments": ""},
		{"label": "importDelay", "value": 2000, "comments": ""},
	)

class Settings_Frames(Mapper, _Date, Database.Schema_Base):
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

	defaultRows = (
		{"label": "inventory", 			"title": "Inventory", 			"size": "(1563, 578)", 	"position": "(1719, 76)", 	"defaultStatus_label": "Current User"},
		{"label": "settings", 			"title": "Settings", 			"size": "(712, 696)", 	"position": "(682, 81)", 	"defaultStatus_label": "Current User"},
		{"label": "login", 				"title": "Login", 				"size": None, 			"position": None, 			"defaultStatus_label": "Current User"},
		{"label": "changePassword", 	"title": "Change Password", 	"size": None, 			"position": None, 			"defaultStatus_label": "Current User"},
		{"label": "modifyBarcode", 		"title": "Modify Barcode", 		"size": "(686, 225)", 	"position": None, 			"defaultStatus_label": "Current User"},
		{"label": "testScanner", 		"title": "Test Scanner", 		"size": "(2061, 146)", 	"position": None, 			"defaultStatus_label": "Current User"},
		{"label": "showLocation", 		"title": "Show Location", 		"size": "(216, 111)", 	"position": None, 			"defaultStatus_label": "Current User"},
		{"label": "externalFiles", 		"title": "External Files", 		"size": "(603, 304)", 	"position": None, 			"defaultStatus_label": "Current User"},
		{"label": "filterSettings", 	"title": "Filter Settings", 	"size": "(2225, 303)", 	"position": None, 			"defaultStatus_label": "Current User"},
		{"label": "advancedSearch", 	"title": "Advanced Search", 	"size": "(68, 44)", 	"position": None, 			"defaultStatus_label": "Current User"},
		{"label": "finalRemove", 		"title": "Pending Removals", 	"size": "(511, 155)", 	"position": None, 			"defaultStatus_label": "Current User"},
		{"label": "bugReport", 			"title": "Bug Report", 			"size": None, 			"position": None, 			"defaultStatus_label": "Current User"},
		{"label": "changeLog", 			"title": "Change Log", 			"size": "(483, 537)", 	"position": "(68, 44)", 	"defaultStatus_label": "Current User"},
	)

class Users(Mapper, _Date, Database.Schema_Base):
	__tablename__ = 'Users'
	id 				= sqlalchemy.Column(sqlalchemy.Integer, primary_key = True, nullable = False, unique = True)
	label 			= sqlalchemy.Column(sqlalchemy.String(250), unique = True, nullable = False)
	password 		= sqlalchemy.Column(sqlalchemy.String(250))
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

	defaultRows = (
		{"id": 0, "label": "guest"},
		{"label": "admin", "password": "Admin", **{key: True for key, value in locals().items() if (isinstance(value, sqlalchemy.Column) and (key not in {"id", "label", "password", "removePending"}))}}
	)

#Tables - Main
class Containers(Mapper, _Editable, _Files, Database.Schema_AutoForeign, Database.Schema_Base):#, metaclass = AutoForeign_meta):
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
	
	job_id 				= sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey(Choices_Job.id, onupdate = "CASCADE", ondelete = "SET NULL"), default = 0)
	item_type_id 		= sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey(Choices_Item.id, onupdate = "CASCADE", ondelete = "SET NULL"), default = 0)
	color_id 			= sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey(Choices_Color.id, onupdate = "CASCADE", ondelete = "SET NULL"), default = 0)
	vendor_id 			= sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey(Choices_Vendor.id, onupdate = "CASCADE", ondelete = "SET NULL"), default = 0)
	material_id 		= sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey(Choices_Material.id, onupdate = "CASCADE", ondelete = "SET NULL"), default = 0)
	customer_id 		= sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey(Choices_Customer.id, onupdate = "CASCADE", ondelete = "SET NULL"), default = 0)
	type_id 			= sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey(Choices_Container.id, onupdate = "CASCADE", ondelete = "SET NULL"), default = 0)
	dmte_contact_id 	= sqlalchemy.Column(sqlalchemy.Integer, sqlalchemy.ForeignKey(Choices_DMTE_Contact.id, onupdate = "CASCADE", ondelete = "SET NULL"), default = 0)

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

	job_id._creation_order = 2
	type_id._creation_order = 8
	material_id._creation_order = 9
	color_id._creation_order = 10
	item_type_id._creation_order = 11
	vendor_id._creation_order = 12
	customer_id._creation_order = 13
	dmte_contact_id._creation_order = 14

	def __init__(self, **kwargs):
		Database.Schema_AutoForeign.__init__(self, kwargs = kwargs)
		super().__init__(**kwargs)

relationCatalogue = {item.__name__: item for item in Database.Schema_Base.__subclasses__()}
hasForeignCatalogue = {item.__name__: item for item in Database.Schema_AutoForeign.__subclasses__()}

for module in hasForeignCatalogue.values():
	module.formatForeign(relationCatalogue)

if __name__ == '__main__':
	engine = sqlalchemy.create_engine('sqlite:///test_map_example.db')
	Mapper.metadata.bind = engine

	Mapper.metadata.drop_all()
	Mapper.metadata.create_all()
	for relationHandle in relationCatalogue.values():
		relationHandle.reset()
	# inspector = sqlalchemy.inspect(engine)
	# print(inspector.get_table_names())


	sessionMaker = sqlalchemy.orm.sessionmaker()
	DBSession = sqlalchemy.orm.sessionmaker(bind = engine)
	session = DBSession()

	newContainer = Containers(label = "lorem", job = 12345, poNumber = 123)
	session.add(newContainer)
	session.commit()

	# container = session.query(Containers).filter(Containers.poNumber == 123).first()
	# print(container, container.job.label)

	query = session.query(Containers)
	query = query.join(Containers.job)
	# query = query.filter(Containers.job.has(label = 12345))
	query = query.filter_by(label = 12345)

	# print(session.query(Containers).filter(Containers.job.label == "12345"))
	container = query.first()
	print(container)

	# for item in dir(Containers):
	# 	print(item)


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

