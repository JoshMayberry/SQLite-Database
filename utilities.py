import json

#Expand JSON
class _JSONEncoder(json.JSONEncoder):
	"""Allows sets to be saved in JSON files.
	Modified code from Raymond Hettinger and simlmx on: https://stackoverflow.com/questions/8230315/how-to-json-serialize-sets/36252257#36252257

	Example Use: 
		json.dumps(["abc", {1, 2, 3}], cls = _JSONEncoder)

		json._default_encoder = _JSONEncoder()
		json.dumps(["abc", {1, 2, 3}])
	"""

	def __init__(self, *, tag_set = None, **kwargs):
		super().__init__(**kwargs)
		self.tag_set = tag_set or "_set"

	def default(self, item):
		if (isinstance(item, collections.Set)):
			return {self.tag_set: list(item)}
		else:
			return super().default(self, item)

class _JSONDecoder(json.JSONDecoder):
	"""Allows sets to be loaded from JSON files.
	Modified code from Raymond Hettinger and simlmx on: https://stackoverflow.com/questions/8230315/how-to-json-serialize-sets/36252257#36252257

	Example Use: 
		json.loads(encoded, cls = _JSONDecoder)

		json._default_decoder = _JSONDecoder()
		json.loads(encoded)
	"""

	def __init__(self, *, object_hook = None, tag_set = None, **kwargs):
		super().__init__(object_hook = object_hook or self.myHook, **kwargs)

		self.tag_set = tag_set or "_set"

	def myHook(self, catalogue):
		if (self.tag_set in catalogue):
			return set(catalogue[self.tag_set])
		return catalogue

json._default_encoder = _JSONEncoder()
json._default_decoder = _JSONDecoder()