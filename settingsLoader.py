import sys

import contextlib

from API_Database import db_config
import MyUtilities.common
import MyUtilities.logger
import MyUtilities.wxPython

NULL = MyUtilities.common.NULL

#Decorators
wrap_skipEvent = MyUtilities.wxPython.wrap_skipEvent

def build(*args, **kwargs):
	return LoadingController(*args, **kwargs)

class LoadingController(MyUtilities.common.EnsureFunctions, MyUtilities.common.CommonFunctions, MyUtilities.logger.LoggingFunctions):
	logger_config = {
		None: {
			"level": 1,
		},

		"console": {
			"type": "stream",
			"level": 1,
		},
	}

	def __init__(self, module = None, filePath = "settings.ini", section = "parameters", *, logger_name = None, logger_config = None, **configKwargs):
		MyUtilities.common.EnsureFunctions.__init__(self)
		MyUtilities.common.CommonFunctions.__init__(self)
		MyUtilities.logger.LoggingFunctions.__init__(self, label = logger_name or __name__, config = logger_config or self.logger_config, force_quietRoot = __name__ == "__main__")
	
		self.building = True

		self.databound_widgets = {} # {
			# settings variable (str): [
				# {
					# "widget": GUI_Maker widget, 
					# "variable": The settings variable this is used for (duplicate of parent key)
					# "displayOnly": If setting values can be modified (bool), 
					# "getter": What function to run to get the setting from the widget (function), 
					# "setter": What function to run to set the setting in the widget (function), 
					# "toggle": [
						# {
							# "widget": A widget to toggle,
							# "enable": If the enable state should be toggled (bool),
							# "show": If the show state should be toggled (bool),
							# "saveError": If an error means this value shoudl not be saled (bool),
							# "checkFunctions": List of functions to run that control the toggle state (function),
							# "updateFrames": Set of frames to update with status messages
						# }
					#],
				# }
			# ]
		# }

		self.module = self.ensure_default(module, default = self)
		self.database = db_config.build(default_filePath = filePath, default_section = section, **configKwargs)

		self.default_updateFrames = set()

		self.loadSettings()

	#User Functions
	def applyUserFunctions(self):
		self.module.getSetting = self.getSetting
		self.module.setSetting = self.setSetting
		self.module.addSettingWidget = self.addSettingWidget
		self.module.addToggleWidget = self.addToggleWidget

	def setBuilding(self, state):
		self.building = state

	@contextlib.contextmanager
	def isBuilding(self):
		current_building = self.building

		self.setBuilding(True)
		yield
		self.setBuilding(current_building)

	def finished(self):
		self.setBuilding(False)

	#Setting Functions
	def loadSettings(self):
		"""Returns the requested setting.

		Example Input: loadSettings()
		"""

		for variable, value in self.database.get(forceSetting = True).items():
			setattr(self.module, variable, value)

	def getSetting(self, variable):
		"""Returns the requested setting.

		Example Input: getSetting("offsets")
		"""

		return self.database.get(variable)

	def setSetting(self, variable, value, *, refreshGUI = True):
		"""Changes the provided setting.

		Example Input: setSetting("offsets", 3)
		"""

		self.log_warning(f"Changing Value", variable = variable, value = value)
		self.database.set(variable, value, save = True)
		
		if (refreshGUI):
			self.setGuiParameter(variable, value)
		setattr(self.module, variable, value)

	#Widget Functions
	def addSettingWidget(self, variable, myWidget, *, getter = None, setter = None, 
		displayOnly = False, updateGUI = True, checkAnother = None, check_onUpdate = None,
		autoSave = True, autoSave_check = NULL, autoSave_getterArgs = None, autoSave_getterKwargs = None,
		toggleWidget = None, checkFunction = None, toggle_enable = NULL, toggle_show = NULL, toggle_saveError = NULL):
		"""Connects the *myWidget* to *variable*.
		Returns the index for *myWidget* in the list of widgets for *variable*.

		variable (str) - What setting variable this widget connects to
		myWidget (guiWidget) - The widget that modifies this setting
		getter (function) - What function to run to get the value from *myWidget*
		setter (function) - What function to run to set the value for *myWidget*

		displayOnly (bool) - If the setting can be modified
		updateGUI (bool) - If *myWidget* should be updated with the new setting value
		autoSave (bool) - If the setting value should be saved after it is edited

		toggleWidget (guiWidget) - A widget to toggle the state of based on *checkFunction*
		checkFunction (function) - A function that controls the state of *toggleWidget*

		Example Input: addSettingWidget("current_quantity", myWidget)
		Example Input: addSettingWidget("current_quantity", myWidget, checkAnother = "current_job")
		Example Input: addSettingWidget("current_quantity", myWidget, checkAnother = ["current_job", "current_date"])
		Example Input: addSettingWidget("current_quantity", myWidget, autoSave_check = True, displayOnly = True)
		Example Input: addSettingWidget("current_date_use_override", myWidget, toggleWidget = "current_date", toggle_saveError = True, checkFunction = lambda value: not value)
		"""

		if (variable in self.databound_widgets):
			self.log_warning(f"Overwriting databound widget {variable}")
		else:
			self.databound_widgets[variable] = []

		widgetCatalogue = {
			"widget": myWidget,
			"displayOnly": displayOnly,
			"getter": (myWidget.getValue, getter)[getter is not None],
			"setter": (myWidget.setValue, setter)[setter is not None],
			"toggle": [],
			"variable": variable,
			"checkAnother": checkAnother,
		}

		myWidget._databoundSettingCatalogue = widgetCatalogue

		self.databound_widgets[variable].append(widgetCatalogue)
		index = len(self.databound_widgets[variable]) - 1

		if (autoSave):
			self.autoSave(variable = variable, widgetCatalogue = widgetCatalogue, check = autoSave_check, save = not displayOnly,
				getterArgs = autoSave_getterArgs, getterKwargs = autoSave_getterKwargs)

		if (toggleWidget is not None):
			if (checkFunction is not None):
				self.addToggleWidget(variable = variable, toggleWidget = toggleWidget, checkFunction = checkFunction, 
					widgetCatalogue = widgetCatalogue, enable = toggle_enable, show = toggle_show, saveError = toggle_saveError)
			else:
				self.log_error(f"Must provide 'checkFunction' along with 'toggleWidget' to add a toggle widget for {label}")
		else:
			if (checkFunction is not None):
				self.log_error(f"Must provide 'toggleWidget' along with 'checkFunction' to add a toggle widget for {label}")
		
		if (check_onUpdate and not autoSave_check):
			myWidget.setFunction_click(self.onCheckAll, myFunctionKwargs = { "variable": variable })

		if (checkAnother):
			myWidget.setFunction_click(self.onCheckAll, myFunctionKwargs = { "variable": checkAnother })

		if (updateGUI):
			self.updateGuiSettings(variable = variable, widgetCatalogue = widgetCatalogue)

		return index

	def _yieldWidgetCatalogue(self, variable = None, index = None, *, widgetCatalogue = None, exclude = ()):
		"""Yields the widget catalogue(s) for *variable*.

		variable (str) - What setting to yield the widget catalogue(s) for
			~ If None: Will yield for all variables
			~ If List: Will yield for all variables in the list

		index (int) - Which widget  yield the widget catalogue(s) for (in order added)
			~ If None: Will yield for all widgets for *variable*
			~ If List: Will yield for all widgets for *variable* in the list

		widgetCatalogue (dict) - If provided, will yield this instead of doing the normal yield routine

		Example Input: _yieldWidgetCatalogue()
		Example Input: _yieldWidgetCatalogue("current_quantity")
		Example Input: _yieldWidgetCatalogue("current_quantity", 2)
		Example Input: _yieldWidgetCatalogue(["current_quantity", "current_file"])
		Example Input: _yieldWidgetCatalogue(widgetCatalogue = widgetCatalogue)
		"""

		def yieldVariable():
			nonlocal variable

			if (variable is None):
				for item in self.databound_widgets.keys():
					yield item
				return

			for item in self.ensure_container(variable):
				if (item not in self.databound_widgets):
					self.log_error(f"'{item}' not found in databound widgets; cannot update GUI")
					continue

				yield item

		def yieldIndex(_variable):
			nonlocal index

			numberOfWidgets = len(self.databound_widgets[_variable])

			if (index is None):
				for item in range(numberOfWidgets):
					yield item
				return

			for item in self.ensure_container(index):
				if (item >= numberOfWidgets):
					self.log_error(f"There are less than '{item}' databound widgets for '{_variable}'; cannot update GUI")
					continue

				yield item

		######################################################

		if (widgetCatalogue != None):
			yield widgetCatalogue
			return

		for _variable in yieldVariable():
			if (_variable in exclude):
				continue

			for _index in yieldIndex(_variable):
				yield self.databound_widgets[_variable][_index]

	def yieldSettingsWidget(self, variable = None, index = None):
		"""Yields the settings widget for *variable* at the insert position of *index*

		Example Input: yieldSettingsWidget("current_quantity")
		"""

		for _widgetCatalogue in self._yieldWidgetCatalogue(variable = variable, index = index):
			yield _widgetCatalogue["widget"]

	def autoSave(self, variable = None, index = None, *, widgetCatalogue = None, 
		check = True, save = True, getterArgs = None, getterKwargs = None):
		"""Sets up *variable* to automatically save after it is interacted with.

		variable (str) - What setting to automatically save for
		index (int) - Which widget(s) to automatically save when interacted with (in order added)

		check (bool) - If check functions should all pass before it is allowed to save

		Example Input: autoSave()
		Example Input: autoSave("current_quantity")
		"""

		for _widgetCatalogue in self._yieldWidgetCatalogue(variable = variable, index = index, widgetCatalogue = widgetCatalogue):
			myWidget = _widgetCatalogue["widget"]

			myWidget.setFunction_click(myFunction = self.onChangeSetting, myFunctionKwargs = {
				"variable": self.ensure_default(variable, default = _widgetCatalogue["variable"]), "myWidget": myWidget, 
				"check": check, "save": save, "getterArgs": getterArgs, "getterKwargs": getterKwargs,
			})

	def addToggleWidget(self, toggleWidget, checkFunction, variable = None, index = None, *, widgetCatalogue = None, 
		enable = True, show = False, saveError = False, updateFrame = None):
		"""Allows the widget(s) for *variable* to toggle *toggleWidget* based on the results of *checkFunction*.

		toggleWidget (guiWidget) - The widget to toggle states on
		checkFunction (function) - A function to run to see if the state shoudl be toggled
			~ If returns Falsey: Will make the toggle state positive
			~ If returns Truthy: Will make the toggle state negative
			~ If returns a string: Will also display the string as a status message for *updateFrame*

		variable (str) - What setting to add a toggle widget to
		index (int) - Which widget(s) to connect the toggle widget

		saveError (bool) - If an error state means the setting should not be saved
		enable (bool) - If the enable state of *toggleWidget* should be toggled
		show (bool) - If the show state of *toggleWidget* should be toggled
		updateFrame (guiWindow) - The window(s) to update status text on

		Example Input: addToggleWidget(self.widget_submitButton, self.check_file, variable = "current_file")
		Example Input: addToggleWidget(self.widget_submitButton, self.check_file, variable = "current_file", saveError = True)
		Example Input: addToggleWidget(self.widget_submitButton, self.check_file, variable = "current_file", enable = False, show = True)
		"""

		def yieldToggleWidget(_widgetCatalogue):
			nonlocal toggleWidget

			if (isinstance(toggleWidget, str)):
				yielded = False
				for catalogue in self._yieldWidgetCatalogue(variable = toggleWidget, index = None):
					yield catalogue["widget"]
					yielded = True

				if (not yielded):
					self.log_error(f"Could not find toggle widget for '{toggleWidget}'")
				return

			yield toggleWidget

		#################################

		show = self.ensure_default(show, False, defaultFlag = NULL)
		enable = self.ensure_default(enable, True, defaultFlag = NULL)
		saveError = self.ensure_default(saveError, False, defaultFlag = NULL)

		_checkFunctions = self.ensure_container(checkFunction)
		_updateFrames = None if (updateFrame is None) else self.ensure_container(updateFrame)
		for _widgetCatalogue in self._yieldWidgetCatalogue(variable = variable, index = index, widgetCatalogue = widgetCatalogue):
			for _toggleWidget in yieldToggleWidget(_widgetCatalogue):
				_widgetCatalogue["toggle"].append({
					"toggleWidget": _toggleWidget,
					"saveError": saveError,
					"enable": enable,
					"show": show,
					"checkFunctions": _checkFunctions,
					"updateFrames": _updateFrames,
				})

	def _getWidgetValue(self, widgetCatalogue, *, getterArgs = None, getterKwargs = None):
		"""Returns the value of the widget in the widget catalogue. 

		Example Input: _getWidgetValue(widgetCatalogue)
		"""

		return self.runMyFunction(myFunction = widgetCatalogue["getter"], myFunctionArgs = getterArgs, myFunctionKwargs = getterKwargs)

	def changeSetting(self, variable, myWidget, *, check = False, save = False, checkBuilding = True,
		getterArgs = None, getterKwargs = None):
		"""An event for when a setting widget is modified.

		variable (str) - Which variable to change
		myWidget (guiWidget) - The widget to get the value from
		"""

		if (checkBuilding and self.building):
			return

		value = self._getWidgetValue(myWidget._databoundSettingCatalogue, getterArgs = getterArgs, getterKwargs = getterKwargs)
		if (check and (not self._checkSetting(variable = variable, value = value, widgetCatalogue = myWidget._databoundSettingCatalogue))):
			return

		if (save):
			self.setSetting(variable, value, refreshGUI = False)
		else:
			setattr(self.module, variable, value)

	@wrap_skipEvent()
	def onChangeSetting(self, event, *args, **kwargs):
		"""A wxEvent version of *changeSetting*."""

		self.changeSetting(*args, **kwargs)

	def resetSettings(self):
		"""Changes the all settings to their default values."""

		self.log_warning(f"Resetting Values")
		with self.isBuilding():
			self.database.set(self.database.get(section = "DEFAULT", forceSetting = True), section = "parameters", save = True)
			self.loadSettings()
			self.updateGuiSettings()

	@wrap_skipEvent()
	def onResetSettings(self, event, *args, **kwargs):
		"""A wxEvent version of *resetSettings*."""

		self.resetSettings(*args, **kwargs)

	#GUI Functions
	def updateGuiSettings(self, variable = None, index = None, *, widgetCatalogue = None):
		"""Updates the widget(s) for *variable*.

		variable (str) - What setting to update widgets for
		index (int) - Which widget to update (in order added)

		Example Input: updateGuiSettings()
		Example Input: updateGuiSettings("current_quantity")
		"""

		for _widgetCatalogue in self._yieldWidgetCatalogue(variable = variable, index = index, widgetCatalogue = widgetCatalogue):
			_widgetCatalogue["setter"](getattr(self.module, variable or _widgetCatalogue["variable"]))
	
	@wrap_skipEvent()
	def onUpdateGuiSettings(self, event, *args, **kwargs):
		"""A wxEvent version of *updateGuiSettings*."""

		self.updateGuiSettings(*args, **kwargs)

	def setDefaultUpdateWindow(self, myFrame = None):
		"""Adds *myFrame* to the list of default frames to push status messages to when check functions are run.

		myFrame (guiWindow) - Which window to update the status message of
			- If list: All windows in the list will be updated
			- If None: No window will be updated

		Example setDefaultUpdateWindow(self.frame_main)
		Example setDefaultUpdateWindow([self.frame_main, self.frame_html])
		"""

		self.default_updateFrames.update(self.ensure_container(myFrame))

	def _setStatusText(self, myFrame, text = None):
		"""Updates the status text for *myFrame*

		myFrame (guiWindow) - Which window to update the status message of
			- If list: All windows in the list will be updated
			- If None: Will update the windows in *default_updateFrames*

		text (str) - What the status text will say

		Example Input: _setStatusText(myFrame, text)
		"""

		if (myFrame is None):
			_updateFrames = self.default_updateFrames
		else:
			_updateFrames = self.ensure_container(myFrame)

		for myFrame in _updateFrames:
			myFrame.setStatusText(text)

	def yieldCheckFunctionResult(self, value, widgetCatalogue):
		for toggleCatalogue in widgetCatalogue["toggle"]:
			for checkFunction in toggleCatalogue["checkFunctions"]:
				yield checkFunction(value), toggleCatalogue

	def _checkSetting(self, variable, value, widgetCatalogue, *, updateGUI = True):
		windowCatalogue = {} # {updateFrame (guiWindow): Error Message (str)}
		toggleStateCatalogue = {} # {toggleWidget (guiWidget): {"state": If the state is positive or negative (bool), "enable": If the enable state can be changes (bool), "show": If the shown state can be changed (bool)}}

		noError = True
		for errorMessage, toggleCatalogue in self.yieldCheckFunctionResult(value, widgetCatalogue):
			toggleWidget = toggleCatalogue["toggleWidget"]

			if (not errorMessage):
				# Do not overwrite a negative
				if (toggleWidget not in toggleStateCatalogue):
					toggleStateCatalogue[toggleWidget] = {"state": True, "enable": toggleCatalogue["enable"], "show": toggleCatalogue["show"]}
				
				if (toggleCatalogue["updateFrames"] not in windowCatalogue):
					windowCatalogue[toggleCatalogue["updateFrames"]] = None
				continue

			#Account for saving on an error being ok
			noError = noError and toggleCatalogue["saveError"]

			# Only show the first error found for their respective window(s)
			if ((toggleCatalogue["updateFrames"] not in windowCatalogue) or (windowCatalogue[toggleCatalogue["updateFrames"]] is None)):
				windowCatalogue[toggleCatalogue["updateFrames"]] = errorMessage

			# Ensure a negative
			toggleStateCatalogue[toggleWidget] = {"state": False, "enable": toggleCatalogue["enable"], "show": toggleCatalogue["show"]}

		if (updateGUI):
			for toggleWidget, stateCatalogue in toggleStateCatalogue.items():
				if (stateCatalogue["enable"]):
					toggleWidget.setEnable(stateCatalogue["state"])

				if (stateCatalogue["show"]):
					toggleWidget.setShow(stateCatalogue["state"])


			for myFrame, text in windowCatalogue.items():
				if (isinstance(text, str)):
					self._setStatusText(myFrame, text)

		return noError

	def checkAll(self, exclude = (), *, updateGUI = True, getterArgs = None, getterKwargs = None, variable = None, index = None):
		"""Runs all check functions.

		Example Input: checkAll()
		Example Input: checkAll(variable = "current_job")
		"""

		noError = True
		for _widgetCatalogue in self._yieldWidgetCatalogue(exclude = exclude, variable = variable, index = index):
			variable = _widgetCatalogue["variable"]
			value = self._getWidgetValue(_widgetCatalogue, getterArgs = getterArgs, getterKwargs = getterKwargs)
			noError = noError and self._checkSetting(variable = variable, value = value, widgetCatalogue = _widgetCatalogue)

		if (noError and updateGUI):
			updateFrameList = set()
			for _widgetCatalogue in self._yieldWidgetCatalogue(exclude = exclude, variable = variable, index = index):
				if (_widgetCatalogue["toggle"]):
					for item in _widgetCatalogue["toggle"]:
						updateFrameList.add(item["updateFrames"])
				else:
					updateFrameList.add(None)

			for myFrame in updateFrameList:
				self._setStatusText(myFrame)

		return noError
	
	@wrap_skipEvent()
	def onCheckAll(self, event, *args, **kwargs):
		"""A wxEvent version of *checkAll*."""

		self.checkAll(*args, **kwargs)
	