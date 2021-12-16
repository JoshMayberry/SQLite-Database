import os
import ast
import datetime
import configparser
import MyUtilities.common


NULL = MyUtilities.common.NULL
openPlus = MyUtilities.common.openPlus

#Monkey Patches
configparser.ConfigParser.optionxform = str

class Configuration(MyUtilities.common.EnsureFunctions, MyUtilities.common.CommonFunctions):
	"""Used to handle .ini files.

	- Both keys and values can have spaces
	- Multi-line values must have extra lines indented one line deeper
	- Sections and single-line values can be indented with no consequence

	- Keys can be separated from values by either = or :
	- Keys without values can have no separator
	- The separator can have spaces on each side

	- Comments can be done using # or ;

	___________________ EXAMPLE INI FILE ___________________

	[DEFAULT]
	scanDelay = %(delay) %(units)
	units = ms

	[main]
	startup_user = admin

	[AutoSave]
	delay = 1
	units = s

	[GUI]
	delay = 500
	________________________________________________________

	Use: https://pymotw.com/3/configparser/
	Use: https://docs.python.org/3.6/library/configparser.html
	Use: https://martin-thoma.com/configuration-files-in-python/#configparser
	Use: https://www.blog.pythonlibrary.org/2010/01/01/a-brief-configobj-tutorial/
	use: https://www.blog.pythonlibrary.org/2013/10/25/python-101-an-intro-to-configparser/
	"""

	def __init__(self, default_filePath = None, *, default_values = None, default_section = None, forceExists = False, forceCondition = None,
		allowNone = True, interpolation = True, valid_section = None, readOnly = False, defaultFileExtension = None, backup_filePath = None,
		knownTypes = None, knownTypesSection = "knownTypes", knownTypeDefault = None, version = None):
		"""

		allowNone (bool) - Determines what happens if a setting does not have a set value
			- If True: Will use None
			- If False: Will raise an error during load()

		interpolation (bool) - Determines what kind of interpolation can be done in get()
			- If True: Extended Interpolation
			- If False: Basic Interpolation
			- If None: No Interpolation

		valid_section (list) - Which sections (excluding DEFAULT) to load
			- If str: Will load only that section
			- If None: Will load all sections
			~ Optionally, variables can be defined in the section given to 'knownTypesSection'

		knownTypesSection (str) - Which section is used to store knownTypes
			- If None: Will not use a section to get knownTypes from

		version (str) - What version the config file must have
			- If None: Will not do a version check
			- If different: Will replace the config file with the one from *default_filePath*

		Example Input: Configuration(self)
		Example Input: Configuration(self, source_directory = "database")
		Example Input: Configuration(self, defaults = {"startup_user": "admin"})
		"""

		self.defaultFileExtension = defaultFileExtension or "ini"
		self.default_section = default_section or "main"
		self.default_filePath = default_filePath or f"settings.{self.defaultFileExtension}"
		self.backup_filePath = backup_filePath
		self.version = version

		if (interpolation):
			interpolation = self.MyExtendedInterpolation()
		elif (interpolation is not None):
			interpolation = configparser.BasicInterpolation()

		self.setReset(converters = self.converters, allow_no_value = allowNone, 
			defaults = default_values or {}, interpolation = interpolation)
		self.reset()

		# self.config.optionxform = str

		self.knownTypeDefault = knownTypeDefault or "_default_"
		self.knownTypesSection = knownTypesSection or None
		self.knownTypes = knownTypes or {}
		self.readOnly = readOnly

		self.set_validSection(valid_section)

		if (default_filePath):
			self.load(forceExists = forceExists, forceCondition = forceCondition)

	def setReset(self, *args, **kwargs):
		self._reset = (args, kwargs)

	def _eval(self, *args, **kwargs):
		value = self.config.get(*args, **kwargs)
		return ast.literal_eval(value)

	def reset(self):
		self.config = configparser.ConfigParser(*self._reset[0], **self._reset[1])

		self.dataType_catalogue = {
			None: self.config.get,
			eval: self._eval, "eval": self._eval, 
			str: self.config.get, "str": self.config.get,
			int: self.config.getint, "int": self.config.getint,
			float: self.config.getfloat, "float": self.config.getfloat,
			bool: self.config.getboolean, "bool": self.config.getboolean,
			datetime.datetime: self.config.getdatetime, "datetime": self.config.getdatetime,
		}

	def __repr__(self):
		representation = f"{type(self).__name__}(id = {id(self)})"
		return representation

	def __str__(self):
		output = f"{type(self).__name__}()\n-- id: {id(self)}\n"
		return output

	def __enter__(self):
		return self.config

	def __exit__(self, exc_type, exc_value, traceback):
		if (traceback is not None):
			print(exc_type, exc_value)
			return False

	def __getitem__(self, key):
		self.check_invalidSection(key)

		return self.config[key]

	def __setitem__(self, key, value):
		if (self.readOnly):
			raise ReadOnlyError(self)
		self.check_invalidSection(key)

		self.config[key] = value

	def __delitem__(self, key):
		if (self.readOnly):
			raise ReadOnlyError(self)
		self.check_invalidSection(key)

		del self.config[key]

	def __contains__(self, key):
		if (self.check_invalidSection(key, raiseError = False)):
			return False

		return key in self.config

	def keys(self):
		if (self.valid_section is None):
			return tuple(self.config.keys())
		return tuple(section for section in self.config.keys() if (section in self.valid_section))

	def values(self):
		if (self.valid_section is None):
			return tuple(self.config.values())
		return tuple(handle for section, handle in self.config.items() if (section in self.valid_section))

	def items(self):
		if (self.valid_section is None):
			return tuple(self.config.items())
		return tuple((section, handle) for section, handle in self.config.items() if (section in self.valid_section))

	def _asdict(self):
		if (self.valid_section is None):
			return dict(self.config)
		return {key: value for key, value in self.items()}

	def check_invalidSection(self, section, *, raiseError = True, valid_section = NULL):
		if (valid_section is NULL):
			valid_section = self.valid_section
		if ((valid_section is not None) and (section not in valid_section) and (not self.has_section(section, valid_section = None))):
			if (raiseError):
				raise InvalidSectionError(self, section)
			return True

	def _getType(self, variable, section = None, *, dataType = None):
		"""Returns what type to use for the given variable.

		Example Input: _getType("delay")
		"""

		if (dataType is None):
			section = section or self.default_section
			check_section = False
			if ((self.knownTypesSection is not None) and (self.knownTypesSection in self.config.sections())):
				if (self.has_setting(variable, self.knownTypesSection)):
					function = self.dataType_catalogue.get(self.config[self.knownTypesSection][variable], None)
					if (function is not None):
						return function
				check_section = True

			if ((section in self.knownTypes) and (variable in self.knownTypes[section])):
				return self.dataType_catalogue[self.knownTypes[section][variable]]

			default_section = self.config.default_section
			if ((default_section in self.knownTypes) and (variable in self.knownTypes[default_section])):
				return self.dataType_catalogue[self.knownTypes[default_section][variable]]

			if (variable in self.knownTypes):
				return self.dataType_catalogue[self.knownTypes[variable]]


			if (check_section and self.has_setting(self.knownTypeDefault, self.knownTypesSection)):
				function = self.dataType_catalogue.get(self.config[self.knownTypesSection][self.knownTypeDefault], None)
				if (function is not None):
					return function

		return self.dataType_catalogue[dataType]

	def get(self, variable = None, section = None, *, dataType = None, default_values = None, include_defaults = True,
		fallback = configparser._UNSET, raw = False, forceSection = False, forceSetting = False, valid_section = NULL):
		"""Returns a setting from the given section.

		variable (str) - What setting to get
			- If list: Will return a dictionary of all settings in the list
			- If None: Will return a dictionary of all settings in the section

		section (str) - What section to write this setting in
			- If None: Will use the default section

		dataType (type) - What type the data should be in
			- If None: Will read as str, unless the variable is logged in self.knownTypes under 'section' or DEFAULT

		default_values (dict) - Local default values; overrides the global default values temporarily
		include_defaults (bool) - Determines if the default section should be used as a fallback
		raw (bool) - Determines if the value should be returned without applying interpolation

		___________________ BASIC INTERPOLATION ___________________
		Variables are denoted with a single '%', followed by closed paren
			Example: scanDelay = %(delay) %(units)

		To use an escaped %: %%
			Example: units = %%

		___________________ EXTENDED INTERPOLATION ___________________
		Variables are denoted with a '$', followed by braces
			Example: scanDelay = ${delay} ${units}

		Variables from other sections can be used with a ':'
			Example: scanDelay = ${delay} ${general:units}


		Example Input: get()
		Example Input: get("startup_user")
		Example Input: get("scanDelay", section = "AutoSave")
		Example Input: get("scanDelay", section = "AutoSave", dataType = int)
		Example Input: get("startup_window", defaults = {"startup_window": "inventory"})
		
		Example Input: get(("user", "password", "port"), section = "Database_Admin")
		Example Input: get({"Database_Admin": ("user", "password", "port")})
		Example Input: get(include_defaults = False)
		"""

		section = section or self.default_section
		self.check_invalidSection(section, valid_section = valid_section)
		if (not self.has_section(section)):
			section = self.config.default_section

		if (variable is None):
			if (include_defaults):
				variableList = tuple(self[section].keys())
			else:
				variableList = tuple(self.config._sections[section].keys())
			return self.get(variableList, section = section, dataType = dataType, default_values = default_values, fallback = fallback,
				raw = raw, forceSetting = forceSetting, forceSection = forceSection, include_defaults = include_defaults, valid_section = valid_section)

		if (isinstance(variable, dict)):
			answer = {_section: self.get(_variable, section = _section, dataType = dataType, default_values = default_values, fallback = fallback,
				raw = raw, forceSetting = forceSetting, forceSection = forceSection, include_defaults = include_defaults, valid_section = valid_section) for _section, _variable in variable.items()}

			if (forceSection or len(answer) > 1):
				return answer
			elif (not answer):
				return
			return next(iter(answer.values()))

		if (not isinstance(variable, (str, int, float))):
			answer = {_variable: self.get(_variable, section = section, dataType = dataType, default_values = default_values, fallback = fallback,
				raw = raw, forceSetting = forceSetting, forceSection = forceSection, include_defaults = include_defaults, valid_section = valid_section) for _variable in variable}

			if (forceSetting or len(answer) > 1):
				return answer
			elif (not answer):
				return
			return next(iter(answer.values()))

		function = self._getType(variable, section, dataType = dataType)

		try:
			return function(section, variable, vars = default_values or {}, raw = raw, fallback = fallback)

		except (configparser.InterpolationDepthError, configparser.InterpolationMissingOptionError) as error:
			print("@Configuration.get", error)
			return function(section, variable, vars = default_values or {}, raw = True, fallback = fallback)

		except Exception as error:
			print("ERROR", [function, section, variable, default_values or {}, raw, fallback])
			raise error

	def set(self, variable, value = None, section = None, *, valid_section = NULL, save = False):
		"""Adds a setting to the given section.

		variable (str) - What setting to get
			- If list: Wil set each variable in the list to 'value'
			- If dict: Will ignore 'value' and set each key to it's given value

		section (str) - What section to write this setting in
			- If None: Will use the default section

		Example Input: set("startup_user", "admin")
		Example Input: set("scanDelay", 1000, section = "AutoSave")

		Example Input: set({"startup_user": "admin"})
		Example Input: set({"AutoSave": {"scanDelay": 1000}})
		"""
		if (self.readOnly):
			raise ReadOnlyError(self)
		self.check_invalidSection(section, valid_section = valid_section)

		if (isinstance(variable, dict)):
			for _variable, _value in variable.items():
				if (isinstance(_value, dict)):
					for __variable, __value in _value.items():
						self.set(__variable, value = __value, section = _variable, valid_section = valid_section, save = save)
				else:
					self.set(_variable, value = _value, section = section, valid_section = valid_section, save = save)
			return

		if (not isinstance(variable, (str, int, float))):
			for _variable in variable:
				self.set(_variable, value = value, section = section, valid_section = valid_section, save = save)
			return

		section = section or self.default_section

		if (not self.config.has_section(section)):
			self.config.add_section(section)

		if (value is None):
			self.config.set(section, variable, "")
		else:
			self.config.set(section, variable, f"{value}")

		if (save):
			self.save()

	def replaceWithDefault(self, filePath = None, *, forceExists = False, allowBackup = True, mustRead = False):
		"""Replaces the file with the backup file, or throws an error

		Example Input: replaceWithDefault()
		Example Input: replaceWithDefault("database/settings_user.ini")
		"""
		global openPlus

		filePath = filePath or self.default_filePath

		if (allowBackup and (self.backup_filePath is not None)):
			if (not os.path.exists(self.backup_filePath)):
				raise FileExistsError(self.backup_filePath)

			self.config.read(self.backup_filePath)

		elif (mustRead):
			raise ValueError("Could not read from a backup file")

		if (forceExists and isinstance(forceExists, dict)):
			self.set(forceExists, valid_section = None)

		with openPlus(filePath) as config_file:
			self.config.write(config_file)

	def load(self, filePath = None, *, version = NULL, valid_section = NULL, forceExists = False, forceCondition = None, allowBackup = True):
		"""Loads the configuration file.

		filePath (str) - Where to load the config file from
			- If None: Will use the default file path

		valid_section (list) - Updates self.valid_section if not NULL

		Example Input: load()
		Example Input: load("database/settings_user.ini")
		Example Input: load("database/settings_user.ini", valid_section = ("testing",))
		"""

		if (valid_section is not NULL):
			self.set_validSection(valid_section)

		if (version is NULL):
			version = self.version

		filePath = filePath or self.default_filePath
		if (not os.path.exists(filePath)):
			if ((not allowBackup) or (self.backup_filePath is None)):
				raise FileExistsError(filePath)

			self.replaceWithDefault(filePath, forceExists = forceExists, allowBackup = allowBackup)

		self.config.read(filePath)

		if (version is not None):
			_version = self.config["DEFAULT"].get("_version_", None)
			if (_version != version):
				self.replaceWithDefault(filePath, forceExists = forceExists, allowBackup = allowBackup, mustRead = True)
				self.config.read(filePath)

				__version = self.config["DEFAULT"].get("_version_", None)
				if (__version != version):
					raise KeyError(f"Reset config, but version still does not match; old: {__version}; new: {_version}; match: {version}")

		if (forceCondition is not None):
			for variable, value in forceCondition.items():
				var_mustBe = self.tryInterpolation(variable, value)
				var_isActually = self.get(variable)
				if (var_mustBe != var_isActually):
					print(f"Forced conditions not met: '{var_mustBe}' is not '{var_isActually}'. Replacing config file with 'forceMatch'")
					os.remove(filePath)
					self.reset()

					return self.load(filePath = filePath, valid_section = valid_section, forceExists = forceExists, forceCondition = None)

	def tryInterpolation(self, variable, value, section = None):
		return self.config._interpolation.before_get(self.config, section or "DEFAULT", variable, value, self.config.defaults())

	def save(self, filePath = None, override_readOnly = False, **kwargs):
		"""Saves changes to config file.

		filePath (str) - Where to save the config file to
			- If None: Will use the default file path

		Example Input: save()
		Example Input: save("database/settings_user.ini")
		"""
		global openPlus

		if ((not override_readOnly) and self.readOnly):
			raise ReadOnlyError(self)
		
		filePath = filePath or self.default_filePath
		with openPlus(filePath or self.default_filePath, **kwargs) as config_file:
			self.config.write(config_file)

	def has_section(self, section = None, *, valid_section = NULL):
		"""Returns True if the section exists in the config file, otherwise returns False.

		section (str) - What section to write this setting in
			- If None: Will use the default section

		Example Input: has_section()
		Example Input: has_section(section = "AutoSave")
		"""

		section = section or self.default_section

		if (section == self.config.default_section):
			return True

		return section in self.getSections(valid_section = valid_section, skip_knownTypes = False)

	def has_setting(self, variable, section = None, *, checkDefault = False, valid_section = NULL):
		"""Returns True if the setting exists in given section of the config file, otherwise returns False.

		section (str) - What section to write this setting in
			- If None: Will use the default section

		checkDefault (bool) - Determines if the section DEFAULT is taken into account

		Example Input: has_setting("startup_user")
		Example Input: has_setting("scanDelay", section = "AutoSave")

		Example Input: has_setting("startup_user", checkDefault = True)
		"""

		section = section or self.default_section
		self.check_invalidSection(section, valid_section = valid_section)

		if (checkDefault):
			return self.config.has_option(section, variable)
		else:
			return variable in self.config._sections.get(section, ())

	def remove_section(self, section = None, *, valid_section = NULL):
		"""Removes a section.

		section (str) - What section to write this setting in
			- If None: Will remove all sections

		Example Input: remove_section("startup_user")
		Example Input: remove_section("scanDelay", section = "AutoSave")
		"""

		if (self.readOnly):
			raise ReadOnlyError(self)

		if (section is None):
			for section in self.getSections():
				self.config.remove_section(section)
			return

		self.check_invalidSection(section, valid_section = valid_section)
		self.config.remove_section(section or self.default_section)

	def remove_setting(self, variable, section = None, *, valid_section = NULL):
		"""Removes a setting from the given section.

		section (str) - What section to write this setting in
			- If None: Will use the default section

		Example Input: remove_setting("startup_user")
		Example Input: remove_setting("scanDelay", section = "AutoSave")
		"""

		if (self.readOnly):
			raise ReadOnlyError(self)
		self.check_invalidSection(section, valid_section = valid_section)

		self.config.remove_option(section or self.default_section, variable)

	def getSections(self, *, valid_section = NULL, skip_knownTypes = True):
		"""Returns a list of existing sections.

		Example Input: getSections()
		"""

		def yieldSection():
			nonlocal self, valid_section, skip_knownTypes

			for section in self.config.sections():
				if (self.check_invalidSection(section, raiseError = False, valid_section = valid_section)):
					continue

				if (skip_knownTypes and (section == self.knownTypesSection)):
					continue

				yield section

		###################################

		return tuple(yieldSection())

	def getDefaults(self):
		"""Returns the defaults that will be used if a setting does not exist.

		section (str) - What section to write this setting in
			- If None: Will use the default section

		Example Input: getDefaults()
		"""

		return self.config.defaults()

	def extraBool(self, value, state):
		"""Adds a value as an extra possible bool.
		Default cases (case-insensative): yes/no, on/off, true/false, 1/0

		Example Input: extraBool("sure", True)
		Example Input: extraBool("nope", False)
		"""

		self.ConfigParser.BOOLEAN_STATES.update({value: state})

	def set_validSection(self, valid_section = None):
		if (valid_section is None):
			self.valid_section = None
		else:
			self.valid_section = (self.config.default_section, *((self.knownTypesSection,) if (self.knownTypesSection is not None) else ()), *self.ensure_container(valid_section))

	#Converters
	@staticmethod
	def convert_datetime(value):
		return datetime.datetime.strptime(s, "%Y/%m/%d %H:%M:%S.%f")

	converters = {
		"datetime": convert_datetime,
	}

	#Interpolators
	class MyExtendedInterpolation(configparser.ExtendedInterpolation):
		"""Modified ExtendedInterpolation from configparser.py"""

		def _interpolate_some(self, parser, option, accum, rest, section, mapping, depth):
			"""The default ExtendedInterpolation does not account for default values in nested interpolations.
			ie: The following does not work when get() is given the kwargs 'section = "debugging"' and 'vars = {"filePath_versionDir": "C:/"}').
				[admin]
				alembicPath = ${filePath_versionDir}/Schema/main/

				[debugging]
				alembicPath = ${admin:alembicPath}
			"""

			rawval = parser.get(section, option, raw = True, fallback = rest)
			if (depth > configparser.MAX_INTERPOLATION_DEPTH):
				raise InterpolationDepthError(option, section, rawval)
			while rest:
				p = rest.find("$")
				if p < 0:
					accum.append(rest)
					return
				if p > 0:
					accum.append(rest[:p])
					rest = rest[p:]
				# p is no longer used
				c = rest[1:2]
				if c == "$":
					accum.append("$")
					rest = rest[2:]
				elif c == "{":
					m = self._KEYCRE.match(rest)
					if m is None:
						raise InterpolationSyntaxError(option, section,
							"bad interpolation variable reference %r" % rest)
					path = m.group(1).split(':')
					rest = rest[m.end():]
					sect = section
					opt = option
					try:
						if (len(path) is 1):
							opt = parser.optionxform(path[0])
							v = mapping[opt]

						elif (len(path) is 2):
							sect = path[0]
							opt = parser.optionxform(path[1])
							v = parser.get(sect, opt, raw = True)

						else:
							raise configparser.InterpolationSyntaxError(option, section, "More than one ':' found: %r" % (rest,))

					except (KeyError, NoSectionError, NoOptionError):
						raise configparser.InterpolationMissingOptionError(option, section, rawval, ":".join(path)) from None
					
					if ("$" in v):
						self._interpolate_some(parser, opt, accum, v, sect, {**mapping, **dict(parser.items(sect, raw = True))}, depth + 1) # <- This was the only change
					else:
						accum.append(v)
				else:
					raise InterpolationSyntaxError(
						option, section,
						"'$' must be followed by '$' or '{', "
						"found: %r" % (rest,))

def build(*args, **kwargs):
	"""Creates a Configuration object."""

	return Configuration(*args, **kwargs)

def quiet(*args):
	pass
	print(*args)

def sandbox():
	# config_API = build_configuration()
	# # config_API.set("startup_user", "admin")
	# # config_API.save("test/test.ini")

	# config_API.load("test/test.ini")
	# # quiet(config_API.get("startup_user"))
	
	# with config_API as config:
	#   for section, sectionHandle in config.items():
	#       for key, value in sectionHandle.items():
	#           quiet(section, key, value)

	user = os.environ.get('username')
	config_API = build("M:/Versions/dev/Settings/settings_user.ini", valid_section = user, default_section = user, knownTypes = {"x": bool, "y": bool})

	value = config_API.get("startup_user")
	print(value, type(value))

	# value = config_API.get("x")
	# print(value, type(value))

	# value = config_API.get("y")
	# print(value, type(value))

def main():
	"""The main program controller."""

	sandbox()

if __name__ == '__main__':
	main()
