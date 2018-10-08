import sys
import sqlalchemy
import sqlalchemy.ext.declarative

from datetime import datetime

import API_Database as Database

Mapper = Database.makeBase()

class Customer(Mapper, Database.Schema_Base):
	__tablename__ = 'Customer'

	# id 				= sqlalchemy.Column(sqlalchemy.Integer, primary_key = True, autoincrement = True)
	# name 			= sqlalchemy.Column(sqlalchemy.Unicode, nullable = False)

	id 				= sqlalchemy.Column(sqlalchemy.Integer, primary_key = True, autoincrement = True)
	first_name 		= sqlalchemy.Column(sqlalchemy.Unicode, nullable = False)
	last_name 		= sqlalchemy.Column(sqlalchemy.Unicode, nullable = False)

relationCatalogue = {item.__name__: item for item in Database.Schema_Base.__subclasses__()}
hasForeignCatalogue = {item.__name__: item for item in Database.Schema_AutoForeign.__subclasses__()}

for module in hasForeignCatalogue.values():
	module.formatForeign(relationCatalogue)

if __name__ == '__main__':
	#Follows https://www.youtube.com/watch?v=xzsbHMHYI5c
	database = Database.build("test_map_example.db", "test_map_2")

	def startOver():
		database.removeRelation()
		database.createRelation()
		database.resetRelation()

		database.addTuple({"Customer": ({"id": 1, "name": "Mickey Mouse"}, {"id": 2, "name": "Donald Duck"})})
		database.alembic.resetAlembic()

	def test(operation):
		column = operation.column
		if (column.name == "first_name"):
			def nested(*args):
				## START ##
				connection = op.get_bind()
				update_sql = sa.text("""UPDATE Customer
					SET first_name = :first
					WHERE id = :id""")

				for customer in connection.execute("SELECT name, id FROM Customer"):
					first, last = customer.name.split(' ', 1)
					connection.execute(update_sql, first = first, id = customer.id)
				## STOP ##
				return
		
		elif (column.name == "last_name"):
			def nested(*args):
				## START ##
				connection = op.get_bind()
				update_sql = sa.text("""UPDATE Customer
					SET last_name = :last
					WHERE id = :id""")

				for customer in connection.execute("SELECT name, id FROM Customer"):
					first, last = customer.name.split(' ', 1)
					connection.execute(update_sql, last = last, id = customer.id)
				## STOP ##
				return
		
		else:
			nested = ""
		
		return nested

	# startOver()
	# database.alembic.revision(message = "split name column")
	# database.alembic.upgrade(sql = True)
	# database.alembic.upgrade()
	# print(database.alembic.check())
	# print(database.alembic.check(returnDifference = True))

	# database.alembic.history()
	# database.alembic.history(indicate_current = True)

	# database.alembic.downgrade()
	# print(database.alembic.check())
	# print(database.alembic.check(returnDifference = True))

