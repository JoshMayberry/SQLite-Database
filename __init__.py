import lazyLoad
lazyLoad.load(
	"unidecode", 
	"importlib", 
	"cachetools", 

	"yaml", 
	"json", 
	"pyodbc", 
	"alembic", 
	"sqlite3", 
	"sqlalchemy", 
	"configparser", 
	
	"forks.pypubsub.src.pubsub", 
) 

from . import version
__version__ = version.VERSION_STRING

#Import the controller module as this namespace
from .controller import *
del controller