import os
import abc

import contextlib
import collections

import MyUtilities.common

from utilities import json

NULL = MyUtilities.common.NULL
openPlus = MyUtilities.common.openPlus

class Config_Base(MyUtilities.common.EnsureFunctions, MyUtilities.common.CommonFunctions, metaclass = abc.ABCMeta):
	"""Utility API for json and yaml scripts."""

	def __init__(self, default_filePath = None, *, defaultFileExtension = None, override = None, overrideIsSave = None, forceExists = False):
		"""
		Example Input: JSON_Aid()
		Example Input: YAML_Aid()
		"""

		self.defaultFileExtension = defaultFileExtension
		self.default_filePath = default_filePath or f"settings.{self.defaultFileExtension}"
		self.filePath_lastLoad = self.default_filePath

		self.dirty = None
		self.contents = {}
		self.contents_override = {}

		self.setOverride(override = override, overrideIsSave = overrideIsSave)

		if (default_filePath):
			self.load(default_filePath, forceExists = forceExists)

	def __repr__(self):
		representation = f"{type(self).__name__}(id = {id(self)})"
		return representation

	def __str__(self):
		output = f"{type(self).__name__}()\n-- id: {id(self)}\n"
		return output

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		if (traceback is not None):
			print(exc_type, exc_value)
			return False

	def __getitem__(self, key):
		return self.contents[key]

	def __setitem__(self, key, value):
		self.contents[key] = value

	def __delitem__(self, key):
		del self.contents[key]

	def __contains__(self, key):
		return key in self.contents

	def read(self, default = None):
		for section, catalogue in self.contents.items():
			for setting, value in catalogue.items():
				if (isinstance(value, dict)):
					yield section, setting, value.get("value", default)
				else:
					yield section, setting, value

	def setOverride(self, override = None, overrideIsSave = None):
		"""Applies override settings for advanced save and load managment.

		override (str) - A .json file that will override sections in the given filePath
			- If None: Will ignore all override conditions
			- If dict: Will use the given dictionary instead of a .json file for saving and loading; can be empty
			- If str: Will use the .json file located there (it will be created if neccissary)

		overrideIsSave (bool) - Determines what happens when no file path is given to save()
			- If True: Saves any changes to 'override', unless that value exists in 'default_filePath' in which case it will be removed from 'override'
			- If False: Saves any changes to 'override'
			- If None: Saves any changes to 'default_filePath'
			~ Removed sections or settings are ignored

		Example Input: setOverride()
		Example Input: setOverride(override = "")
		Example Input: setOverride(override = "settings_user_override.json")
		Example Input: setOverride(override = {"Lorem": {"ipsum": 1}})
		Example Input: setOverride(override = {}, overrideIsSave = True)
		Example Input: setOverride(override = {}, overrideIsSave = False)
		"""

		if (override is None):
			self.override = None
			self.overrideIsSave = None
			self.contents_override = {}
			self.default_filePath_override = None
			return

		self.overrideIsSave = overrideIsSave
		if (isinstance(override, dict)):
			self.override = False
			self.contents_override = override
			self.default_filePath_override = None
			return

		self.override = True
		self.default_filePath_override = override or f"settings_override.{self.defaultFileExtension}"
		self.contents_override = {}

	@contextlib.contextmanager
	def _load(self, filePath = None, removeDirty = True, applyOverride = True, forceExists = False):
		"""Loads the json file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		Example Input: load()
		Example Input: load("database/settings_user.json")
		"""

		if (isinstance(filePath, dict)):
			self.contents = {**filePath}
			self.filePath_lastLoad = None
			yield None
		else:
			filePath = filePath or self.default_filePath
			self.filePath_lastLoad = filePath

			if (not os.path.exists(filePath)):
				if (not forceExists):
					raise FileExistsError(filePath)

				if (isinstance(forceExists, dict)):
					self.set(forceExists, valid_section = None)

				self.save(filePath = filePath, applyOverride = False, removeDirty = False)

			with open(filePath) as fileHandle:
				yield fileHandle
		
		if (removeDirty):
			self.dirty = False

		if (applyOverride):
			self.load_override()

	@contextlib.contextmanager
	def _load_override(self, filePath = None):
		"""Loads the override json file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		Example Input: load_override()
		Example Input: load_override("database/settings_user_override.json")
		"""

		if (self.override is None):
			yield None
			return

		filePath = filePath or self.default_filePath_override
		if (isinstance(filePath, dict)):
			self.contents_override = {**filePath}
			yield None
		else:
			if (self.override and (os.path.exists(filePath))):
				with open(filePath) as fileHandle:
					yield fileHandle
			else:
				yield None

		MyUtilities.common.nestedUpdate(self.contents, self.contents_override, preserveNone = False)

	@contextlib.contextmanager
	def _save(self, filePath = None, ifDirty = True, removeDirty = True, 
		applyOverride = True, overrideKwargs = None, **kwargs):
		"""Saves changes to json file.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		ifDirty (bool) - Determines if the file should be saved only if changes have been made

		Example Input: save()
		Example Input: save("database/settings_user.json")
		"""
		global openPlus

		filePath = filePath or self.default_filePath
		if (ifDirty and (not self.dirty) and (os.path.exists(filePath))):
			yield None
			return

		try:
			if (applyOverride and self.save_override(**(overrideKwargs or {}))):
				yield None
				return

			with openPlus(filePath, **kwargs) as fileHandle:
				yield fileHandle

		except Exception as error:
			raise error

		finally:
			if (removeDirty):
				self.dirty = False

	@contextlib.contextmanager
	def _save_override(self, filePath = None, *, base = None):
		"""Saves changes to json file.
		Note: Only looks at changes and additions, not removals.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		Example Input: save_override()
		Example Input: save_override("database/settings_user_override.json")
		"""
		global openPlus

		def formatCatalogue(catalogue):
			if (not isinstance(catalogue, dict)):
				return {"value": catalogue}
			return catalogue

		#######################################

		if (self.overrideIsSave is None):
			yield None
			return

		base = base or {}
		changes = collections.defaultdict(lambda: collections.defaultdict(dict))
		for section, new in self.contents.items():
			old = base.get(section, {})

			for setting, new_catalogue in new.items():
				new_catalogue = formatCatalogue(new_catalogue)
				old_catalogue = formatCatalogue(old.get(setting, {}))

				for option, new_value in new_catalogue.items():
					old_value = old_catalogue.get(option, NULL)

					if ((new_value or (option != "comment")) and ((old_value is NULL) or (new_value != old_value))):
						changes[section][setting][option] = new_value

		self.contents_override.clear()
		MyUtilities.common.nestedUpdate(self.contents_override, changes) #Filter out defaultdict

		if (self.override):
			with openPlus(filePath or self.default_filePath_override) as fileHandle:
				yield fileHandle
		else:
			yield None

	def _ensure(self, section, variable = None, value = None, *, comment = None, 
		forceAttribute = False, makeDirty = True):
		"""Makes sure that the given variable exists in the given section.

		section (str) - Which section to ensure 'variable' for
			- If list: Will ensure all given sections have 'variable'
			- If dict: Will ignore 'variable' and 'value'

		variable (str) - Which variable to ensure
			- If list: Will ensure all given variables
			- If dict: Will ignore 'value' and use the key as 'variable' and the value as 'value'

		value (any) - The default value that 'variable' should have if it does not exist
		comment (str) - Optional comment string for 'variable'

		Example Input: ensure("containers", "label", value = False)
		Example Input: ensure("containers", {"label": False})
		Example Input: ensure({"containers": {"label": False}})
		"""

		for sectionCatalogue in self.ensure_container(section):
			for _section, variableCatalogue in self.ensure_dict(sectionCatalogue, variable).items():
				if (not self.has_section(_section)):
					self.contents[_section] = {}

				for _variableCatalogue in self.ensure_container(variableCatalogue):
					for _variable, _value in self.ensure_dict(_variableCatalogue, value).items():

						if (not self.has_setting(_variable, _section)):
							if (makeDirty):
								self.dirty = True
							if (comment):
								yield _section, _variable, {"value": _value, "comment": comment}
							elif (forceAttribute):
								yield _section, _variable, {"value": _value}
							else:
								yield _section, _variable, {_value}

	@abc.abstractmethod
	def load(self, *args, **kwargs):
		pass

	@abc.abstractmethod
	def load_override(self, *args, **kwargs):
		pass

	@abc.abstractmethod
	def save(self, *args, **kwargs):
		pass

	@abc.abstractmethod
	def save_override(self, *args, **kwargs):
		pass

	@abc.abstractmethod
	def ensure(self, *args, **kwargs):
		pass

	def get(self, section, setting = None, default = None, *, 
		forceAttribute = None, forceTuple = False, 
		filterNone = False, useForNone = None):
		"""Returns the value of the given setting in the given section.

		setting (str) - What variable to look for
			- If list: Will return the value for each variable given

		Example Input: get("lorem", "ipsum")
		Example Input: get("lorem", ("ipsum", "dolor"))
		"""

		def formatValue(value):
			nonlocal default

			if (isinstance(value, dict)):
				return value.get("value", default)
			return value

		def yieldValue():
			nonlocal self, section, setting, filterNone, useForNone

			for _setting in self.ensure_container(setting):
				value = formatValue(self.contents[section][_setting])
				if (filterNone and (value is useForNone)):
					continue

				yield _setting, value

		####################

		setting = self.ensure_default(setting, lambda: self.getSettings(section))

		answer = {key: value for key, value in yieldValue()}
		if ((forceAttribute is not None) and (forceAttribute or (len(answer) is not 1))):
			return answer
		else:
			return self.oneOrMany(answer.values(), forceTuple = forceTuple)

	def set(self, contents = None, update = True, makeDirty = True):
		"""Adds a section to the internal contents.

		contents (dict) - What to add
		update (bool) - Determines what happens if a key already exists for the given 'contents'
			- If True: Will update nested dictionaries
			- If False: Will replace nested dictionaries
			- If None: Will replace entire self.contents

		Example Input: set()
		Example Input: set({"lorem": 1})
		Example Input: set({"ipsum": {"dolor": 4}})
		Example Input: set({"ipsum": {"dolor": 5}}, update = False)
		Example Input: set({"lorem": 1, "ipsum": {"dolor": 2, "sit": 3}}, update = None)
		"""

		contents = contents or {}

		assert isinstance(contents, dict)

		if (update is None):
			self.contents = contents
		elif (not update):
			self.contents.update(contents)
		else:
			MyUtilities.common.nestedUpdate(self.contents, contents)

		if (makeDirty):
			self.dirty = True

	def apply(self, handle, section, include = None, exclude = None, handleTypes = None):
		"""Places default values into the supplied handle.

		___________________ REQUIRED FORMAT ___________________

		self.contents = {
			section (str): {
				variable (str): value (any),

				variable (str): {
					"value": value (any),
					"comment": docstring (str), #optional
				},
			},
		}
		_______________________________________________________

		section (str) - Which section to apply variables for
			- If list: Will apply all given sections

		handle (object) - What to apply the given sections to
			- If list: will apply to all

		include (str) - What variable is allowed to be applied
			- If list: Will apply all variables in the section

		handleTypes (list) - Place the type for 'section' here

		Example Input: apply(test_1, "GUI_Manager", handleTypes = Test)
		Example Input: apply(test_2, ("DatabaseInfo", "Users"), handleTypes = (Test,))
		Example Input: apply(self, {"FrameSettings": self.label}, handleTypes = (self.__class__,))
		Example Input: apply(self, {"FrameSettings": {self.label: "title"}}, handleTypes = (self.__class__,))
		Example Input: apply((test1, test_2), {"Settings": ("debugging_default", "debugging_enabled")}, handleTypes = Test)
		"""

		def yieldApplied():
			nonlocal self, handle, section, handleTypes

			for _handle in self.ensure_container(handle, elementTypes = handleTypes):
				for _section in self.ensure_container(section):
					for item in setValue(_handle, _section, self.contents):
						yield item

		def setValue(_handle, _section, catalogue):
			nonlocal self, include, exclude

			if (isinstance(_section, dict)):
				for key, value in _section.items():
					for item in setValue(_handle, value, catalogue.get(key)):
						yield item
				return 
			
			if (_section not in catalogue):
				print("@apply", f"{_section} does not exist in catalogue\n  -- keys: {tuple(catalogue.keys())}")
				raise NotImplementedError()
				return

			for variable, _catalogue in catalogue[_section].items():
				if (include and (variable not in include)):
					continue
				if (exclude and (variable in exclude)):
					continue

				if ((not isinstance(_catalogue, dict) or ("value" not in _catalogue))):
					setattr(_handle, variable, _catalogue)
				else:
					setattr(_handle, variable, _catalogue["value"])

				yield variable

		#######################################################
		
		include = self.ensure_container(include)
		exclude = self.ensure_container(exclude)

		return tuple(yieldApplied())

	def has_section(self, section = None):
		"""Returns True if the section exists in the config file, otherwise returns False.

		section (str) - What section to write this setting in
			- If None: Will use the default section

		Example Input: has_section()
		Example Input: has_section(section = "AutoSave")
		"""

		return (section or self.default_section) in self.contents

	def has_setting(self, variable, section = None):
		"""Returns True if the setting exists in given section of the config file, otherwise returns False.

		section (str) - What section to write this setting in
			- If None: Will use the default section

		Example Input: has_setting("startup_user")
		Example Input: has_setting("scanDelay", section = "AutoSave")
		"""

		return variable in self.contents.get(section or self.default_section, {})

	def is_dirty(self):
		"""Returns True if changes have been made that are not yet saved, otherwise returns False.

		Example Input: is_dirty()
		"""

		return self.dirty

	def getSections(self, variable = None):
		"""Returns a list of existing sections.

		variable (str) - What variable must exist in the section
			- If None: Will not search for sections by variable

		Example Input: getSections()
		Example Input: getSections(variable = "debugging_default")
		"""

		if (variable is None):
			return tuple(self.contents.keys())

		return tuple(key for key, catalogue in self.contents.items() if (variable in catalogue.keys()))

	def getSettings(self, section = None, valuesAsSet = False):
		"""Returns a list of existing settings for the given section.

		section (str) - What section to write this setting in
			- If list: Will use all in list
			- If None: Will use all existing sections

		Example Input: getSettings()
		Example Input: getSettings("AutoSave")
		"""

		if (valuesAsSet):
			container = set
		else:
			container = tuple

		return container(variable for key in (self.ensure_container(section) or self.contents.keys()) for variable in self.contents[key].keys())

class JSON_Aid(Config_Base):
	"""Utility API for json scripts.

	Use: https://martin-thoma.com/configuration-files-in-python/#json
	"""

	def __init__(self, default_filePath = None, **kwargs):
		"""
		Example Input: JSON_Aid()
		"""

		super().__init__(default_filePath = default_filePath or "settings.json", defaultFileExtension = "json", **kwargs)

	def load(self, *args, **kwargs):
		"""Loads the json file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		Example Input: load()
		Example Input: load("database/settings_user.json")
		"""

		with self._load(*args, **kwargs) as fileHandle:
			if (fileHandle is not None):
				self.contents = json.load(fileHandle) or {}
			
		return self.contents

	def load_override(self, *args, **kwargs):
		"""Loads the override json file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		Example Input: load_override()
		Example Input: load_override("database/settings_user_override.json")
		"""

		with self._load_override(*args, **kwargs) as fileHandle:
			if (fileHandle is not None):
				self.contents_override = json.load(fileHandle) or {}

	def save(self, *args, **kwargs):
		"""Saves changes to json file.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		ifDirty (bool) - Determines if the file should be saved only if changes have been made

		Example Input: save()
		Example Input: save("database/settings_user.json")
		"""

		with self._save(*args, **kwargs) as fileHandle:
			if (fileHandle is not None):
				json.dump(self.contents or None, fileHandle, indent = "\t")

	def save_override(self, *args, base = None, **kwargs):
		"""Saves changes to json file.
		Note: Only looks at changes and additions, not removals.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		Example Input: save_override()
		Example Input: save_override("database/settings_user_override.json")
		"""

		if (base is None):
			with open(self.filePath_lastLoad) as fileHandle:
				base = json.load(fileHandle) or {}

		with self._save_override(*args, base = base, **kwargs) as fileHandle:
			if (fileHandle is not None):
				json.dump(self.contents_override or None, fileHandle, indent = "\t")

		return True

	def ensure(self, *args, saveToOverride = None, **kwargs):
		"""Makes sure that the given variable exists in the given section.

		Example Input: ensure("containers", "label", value = False)
		Example Input: ensure("containers", "label", value = False, saveToOverride = True)
		Example Input: ensure("containers", "label", value = False, saveToOverride = False)
		"""
		global openPlus

		if (saveToOverride is None):
			for section, variable, value in self._ensure(*args, **kwargs):
				self.contents[section][variable] = value
			return True

		filePath = (self.filePath_lastLoad, self.default_filePath_override)[saveToOverride]
		with open(filePath) as fileHandle:
			base = json.load(fileHandle) or {}

		changed = False
		for section, variable, value in self._ensure(*args, **kwargs):
			self.contents[section][variable] = value
			changed = True

			if (section not in base):
				base[section] = {}
			base[section][variable] = value

		if (changed):
			with openPlus(filePath) as fileHandle:
				json.dump(base or None, fileHandle, indent = "\t")

		return True

class YAML_Aid(Config_Base):
	"""Utility API for yaml scripts.

	Use: https://pyyaml.org/wiki/PyYAMLDocumentation
	Use: https://martin-thoma.com/configuration-files-in-python/#yaml
	"""

	def __init__(self, default_filePath = None, **kwargs):
		"""
		Example Input: YAML_Aid()
		"""

		super().__init__(default_filePath = default_filePath or "settings.yaml", defaultFileExtension = "yaml", **kwargs)

	def load(self, *args, **kwargs):
		"""Loads the yaml file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		Example Input: load()
		Example Input: load("database/settings_user.yaml")
		"""

		with self._load(*args, **kwargs) as fileHandle:
			if (fileHandle is not None):
				self.contents = yaml.load(fileHandle) or {}
			
		return self.contents

	def load_override(self, *args, **kwargs):
		"""Loads the override yaml file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		Example Input: load_override()
		Example Input: load_override("database/settings_user_override.yaml")
		"""

		with self._load_override(*args, **kwargs) as fileHandle:
			if (fileHandle is not None):
				self.contents_override = yaml.load(fileHandle) or {}

	def save(self, *args, explicit_start = True, explicit_end = True, width = None, indent = 4, 
		default_style = None, default_flow_style = None, canonical = None, line_break = None, 
		encoding = None, allow_unicode = None, version = None, tags = None, **kwargs):
		"""Saves changes to yaml file.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		ifDirty (bool) - Determines if the file should be saved only if changes have been made

		Example Input: save()
		Example Input: save("database/settings_user.yaml")
		"""

		with self._save(*args, overrideKwargs = {"explicit_start": explicit_start, "width": width, "indent": indent, 
			"canonical": canonical, "default_flow_style": default_flow_style}, **kwargs) as fileHandle:

			if (fileHandle is not None):
				yaml.dump(self.contents or None, fileHandle, explicit_start = explicit_start, explicit_end = explicit_end, width = width, 
					default_style = default_style, default_flow_style = default_flow_style, canonical = canonical, indent = indent, 
					encoding = encoding, allow_unicode = allow_unicode, version = version, tags = tags, line_break = line_break)

	def save_override(self, *args, base = None, explicit_start = True, explicit_end = True, width = None, indent = 4, 
		default_style = None, default_flow_style = None, canonical = None, line_break = None, 
		encoding = None, allow_unicode = None, version = None, tags = None, **kwargs):
		"""Saves changes to yaml file.
		Note: Only looks at changes and additions, not removals.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		Example Input: save_override()
		Example Input: save_override("database/settings_user_override.yaml")
		"""

		if (base is None):
			with open(self.filePath_lastLoad) as fileHandle:
				base = yaml.load(fileHandle) or {}

		with self._save_override(*args, base = base, **kwargs) as fileHandle:
			if (fileHandle is not None):
				yaml.dump(self.contents_override or None, fileHandle, explicit_start = explicit_start, explicit_end = explicit_end, width = width, 
					default_style = default_style, default_flow_style = default_flow_style, canonical = canonical, indent = indent, 
					encoding = encoding, allow_unicode = allow_unicode, version = version, tags = tags, line_break = line_break)

		return True

	def ensure(self, *args, saveToOverride = None, explicit_start = True, explicit_end = True, width = None, indent = 4, 
		default_style = None, default_flow_style = None, canonical = None, line_break = None, 
		encoding = None, allow_unicode = None, version = None, tags = None, **kwargs):
		"""Makes sure that the given variable exists in the given section.

		Example Input: ensure("containers", "label", value = False)
		Example Input: ensure("containers", "label", value = False, saveToOverride = True)
		Example Input: ensure("containers", "label", value = False, saveToOverride = False)
		"""

		global openPlus

		if (saveToOverride is None):
			for section, variable, value in self._ensure(*args, **kwargs):
				self.contents[section][variable] = value
			return True

		filePath = (self.filePath_lastLoad, self.default_filePath_override)[saveToOverride]
		with open(filePath) as fileHandle:
			base = yaml.load(fileHandle) or {}

		changed = False
		for section, variable, value in self._ensure(*args, **kwargs):
			self.contents[section][variable] = value
			changed = True

			if (section not in base):
				base[section] = {}
			base[section][variable] = value

		if (changed):
			with openPlus(filePath) as fileHandle:
				yaml.dump(base or None, fileHandle, explicit_start = explicit_start, explicit_end = explicit_end, width = width, 
					default_style = default_style, default_flow_style = default_flow_style, canonical = canonical, indent = indent, 
					encoding = encoding, allow_unicode = allow_unicode, version = version, tags = tags, line_break = line_break)

		return True

def quiet(*args):
	pass
	print(*args)

def sandbox():
	def test_yaml():
		class Test(): pass
		test_1 = Test()
		test_2 = Test()

		# yaml_api = build_yaml(default_filePath = "test/settings.yaml", forceExists = True)
		# print(yaml_api)

		# yaml_api = build_yaml(default_filePath = "M:/Versions/dev/Settings/default_user.yaml", override = {"GUI_Manager": {"startup_window": "settings"}})
		yaml_api = build_yaml(default_filePath = "M:/Versions/dev/Settings/default_user.yaml", override = "M:/Versions/dev/Settings/temp_default_user.yaml", overrideIsSave = True)
		quiet(yaml_api.apply(test_1, "GUI_Manager", handleTypes = Test))
		quiet(yaml_api.apply(test_2, ("Barcodes", "Users"), handleTypes = (Test,)))
		quiet(yaml_api.apply((test_1, test_2), "Settings", ("debugging_default", "debugging_enabled"), handleTypes = (Test,)))

		quiet(vars(test_1))
		quiet(vars(test_2))
		quiet(yaml_api.getSettings())
		quiet(yaml_api.getSettings("Users"))
		quiet(yaml_api.getSections(variable = "debugging_default"))

		yaml_api.set({"GUI_Manager": {"startup_window": "main"}})
		yaml_api.save()

	def test_json():
		class Test(): pass
		test_1 = Test()
		test_2 = Test()

		# json_API = build_json(default_filePath = "M:/Versions/dev/Settings/default_user.json", override = {"GUI_Manager": {"startup_window": "settings"}})
		json_API = build_json(default_filePath = "M:/Versions/dev/Settings/default_user.json", override = "M:/Versions/dev/Settings/temp_default_user.json", overrideIsSave = True)
		json_API.apply(test_1, "GUI_Manager", handleTypes = Test)
		json_API.apply(test_2, ("Barcodes", "Users"), handleTypes = (Test,))
		json_API.apply((test_1, test_2), "Settings", ("debugging_default", "debugging_enabled"), handleTypes = (Test,))

		quiet(vars(test_1))
		quiet(vars(test_2))
		quiet(json_API.getSettings("Users"))
		quiet(json_API.getSections(variable = "debugging_default"))

		json_API.set({"GUI_Manager": {"startup_window": "main"}})
		json_API.save()

	###############################

	test_json()
	# test_yaml()

def build(*args, **kwargs):
	"""Creates a YAML_Aid object."""

	return build_yaml(*args, **kwargs)

def build_json(*args, **kwargs):
	"""Creates a JSON_Aid object."""

	return JSON_Aid(*args, **kwargs)

def build_yaml(*args, **kwargs):
	"""Creates a YAML_Aid object."""

	return YAML_Aid(*args, **kwargs)

def main():
	"""The main program controller."""

	sandbox()

if __name__ == '__main__':
	main()
