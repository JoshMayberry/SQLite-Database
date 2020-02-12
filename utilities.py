import json
import datetime
import collections

#Expand JSON
class _JSONEncoder(json.JSONEncoder):
	"""Allows sets to be saved in JSON files.
	Use: https://stackoverflow.com/questions/8230315/how-to-json-serialize-sets/36252257#36252257
	Use: https://gist.github.com/majgis/4200488

	Example Use: 
		json.dumps(["abc", {1, 2, 3}], cls = _JSONEncoder)

		json._default_encoder = _JSONEncoder()
		json.dumps(["abc", {1, 2, 3}])
	"""

	def __init__(self, *, tag_set = None, tag_timedelta = None, tag_datetime = None, **kwargs):
		super().__init__(**kwargs)
		self.tag_set = tag_set or "_set"
		self.tag_timedelta = tag_timedelta or "_timedelta"
		self.tag_datetime = tag_datetime or "_datetime"

	def default(self, item):
		if (isinstance(item, collections.Set)):
			return {self.tag_set: list(item)}

		if isinstance(item, datetime.datetime):
			return {
				self.tag_datetime: {
					'year' : item.year,
					'month' : item.month,
					'day' : item.day,
					'hour' : item.hour,
					'minute' : item.minute,
					'second' : item.second,
					'microsecond' : item.microsecond,
				}
			}

		if (isinstance(item, datetime.timedelta)):
			return {
				self.tag_timedelta: {
					'days' : item.days,
					'seconds' : item.seconds,
					'microseconds' : item.microseconds,
				}
			}

		return super().default(item)

class _JSONDecoder(json.JSONDecoder):
	"""Allows sets to be loaded from JSON files.
	Use: https://stackoverflow.com/questions/8230315/how-to-json-serialize-sets/36252257#36252257
	Use: https://gist.github.com/majgis/4200488

	Example Use: 
		json.loads(encoded, cls = _JSONDecoder)

		json._default_decoder = _JSONDecoder()
		json.loads(encoded)
	"""

	def __init__(self, *, object_hook = None, tag_set = None, tag_timedelta = None, tag_datetime = None, **kwargs):
		super().__init__(object_hook = object_hook or self.myHook, **kwargs)

		self.tag_set = tag_set or "_set"
		self.tag_timedelta = tag_timedelta or "_timedelta"
		self.tag_datetime = tag_datetime or "_datetime"

	def myHook(self, catalogue):
		if (self.tag_set in catalogue):
			return set(catalogue[self.tag_set])

		if (self.tag_datetime in catalogue):
			return datetime.datetime(catalogue[self.tag_datetime])

		if (self.tag_timedelta in catalogue):
			return datetime.timedelta(catalogue[self.tag_timedelta])

		return catalogue

json._default_encoder = _JSONEncoder()
json._default_decoder = _JSONDecoder()