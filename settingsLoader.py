
import sys

from API_Database import db_config
import MyUtilities.common
import MyUtilities.logger
import MyUtilities.wxPython

NULL = MyUtilities.common.NULL


#Decorators
wrap_skipEvent = MyUtilities.wxPython.wrap_skipEvent

def build(*args, **kwargs):
	return Controller(*args, **kwargs)

class Controller(MyUtilities.common.EnsureFunctions):
	def __init__(self, module = None, filePath = "settings.ini", section = "parameters"):

		self.building = True
		self.updateFrames = None
		self.app_widgets = {} #Widgets that access setting values, but do not modify them
		self.setting_widgets = {} #Widgets that modify setting values
		self.checkFunctions = {} #{setting_widgets label (str): function}
		
		self.module = self.ensure_default(module, default = self)
		self.database = db_config.build(default_filePath = filePath, default_section = section)

		self.loadSettings()

	#User Functions
	def applyUserFunctions(self):
		self.module.getSetting = self.getSetting
		self.module.setSetting = self.setSetting
		self.module.loadSettings = self.loadSettings
		self.module.addAppWidget = self.addAppWidget
		self.module.getAppWidget = self.getAppWidget
		self.module.getFirstError = self.getFirstError
		self.module.onGUIParameter = self.onGUIParameter
		self.module.setGuiParameter = self.setGuiParameter
		self.module.onChangeSetting = self.onChangeSetting
		self.module.onResetSettings = self.onResetSettings
		self.module.setUpdateWindow = self.setUpdateWindow
		self.module.addSettingWidget = self.addSettingWidget
		self.module.addCheckFunction = self.addCheckFunction
		self.module.refresh_settings = self.refresh_settings
		self.module.getCheckFunction = self.getCheckFunction
		self.module.refreshAppWidgets = self.refreshAppWidgets
		self.module.refresh_parameters = self.refresh_parameters
		self.module.getSettingAppWidget = self.getSettingAppWidget
		self.module.onRefreshAppWidgets = self.onRefreshAppWidgets
		self.module.refreshSettingsWidgets = self.refreshSettingsWidgets
		self.module.onRefreshSettingsWidgets = self.onRefreshSettingsWidgets

	def setBuilding(self, state):
		self.building = state

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

	def onChangeSetting(self, event, myWidget, *, save = True, getIndex = False, **kwargs):
		"""Changes a setting for this application."""

		variable = myWidget.getLabel()
		if (variable in self.setting_widgets):
			return self.onGUIParameter(event, variable, myWidget, save = save, getIndex = getIndex, **kwargs)

		if (getIndex):
			value = myWidget.getIndex()
		else:
			value = myWidget.getValue()

		self.setSetting(variable, value)
		event.Skip()

	def onResetSettings(self, event):
		"""Changes the all settings to their default values."""

		self.log_warning(f"Resetting Values")
		with self.isBuilding():
			self.database.set(self.database.get(section = "DEFAULT", forceSetting = True), section = "parameters", save = True)
			self.loadSettings()
			self.refresh_settings()
			self.refresh_parameters()
		event.Skip()

	#GUI Functions
	def setUpdateWindow(self, myFrame = None):
		"""The given window will have it's status message updated when necissary.

		myFrame (wxFrame) - Which window to update the status message of
			- If list: All windows in the list will be updated
			- If None: No window will be updated

		Example setUpdateWindow(self, self.frame_main)
		Example setUpdateWindow(self, (self.frame_main, self.frame_html))
		"""

		self.updateFrames = self.ensure_container(myFrame)

	def _setStatusText(self, text):
		for myFrame in self.updateFrames:
			myFrame.setStatusText(text)

	def addAppWidget(self, variable, myWidget, *, checkFunction = None, toggleWidget = None, updateGUI = True):
		"""Marks the given widget as one that can NOT change settings, but accesses it's value by default.

		Example Input: addAppWidget("offsets", myWidget)
		"""

		if (variable in self.app_widgets):
			self.log_warning(f"Overwriting app widget {variable}")
		self.app_widgets[variable] = myWidget

		if (updateGUI):
			myWidget.setValue(getattr(self.module, variable))

	def addSettingWidget(self, variable, myWidget, *, checkFunction = None, toggleWidget = None, updateGUI = True):
		"""Marks the given widget as one that can change settings.

		variable (str) - What setting variable this widget connects to
		myWidget (wxWidget) - The widget that modifys this setting

		Example Input: addSettingWidget("offsets", myWidget, window = self.frame_settings, toggleWidget = self.widget_generateButton)
		"""

		if (variable in self.setting_widgets):
			self.log_warning(f"Overwriting setting widget {variable}")

		self.setting_widgets[variable] = {"myWidget": myWidget, "toggleWidget": toggleWidget}

		if (checkFunction is not None):
			self.addCheckFunction(variable = variable, myFunction = checkFunction)

		if (updateGUI):
			myWidget.setValue(getattr(self.module, variable))

	def onRefreshAppWidgets(self, event):
		self.refreshAppWidgets()
		if (event is not None):
			event.Skip()

	def onRefreshSettingsWidgets(self, event):
		self.refreshSettingsWidgets()
		if (event is not None):
			event.Skip()

	def refreshAppWidgets(self):
		for variable, myWidget in self.app_widgets.items():
			myWidget.setValue(getattr(self.module, variable))

	def refreshSettingsWidgets(self):
		for variable, catalogue in self.setting_widgets.items():
			catalogue["myWidget"].setValue(getattr(self.module, variable))

	def addCheckFunction(self, variable, myFunction):
		"""Adds a function to check if a setting is valid before modifying the setting.

		myFunction (function) - A function that takes the value of the setting as the first parameter
			~ Returns None if no error, otherwise returns a string that is an error message
		"""

		if (variable not in self.setting_widgets):
			errorMessage = f"There must be a settings widget for the variable {variable} first."
			raise KeyError(errorMessage)
	
		if (variable in self.checkFunctions):
			self.log_warning(f"Overwriting check function {variable}")
		self.checkFunctions[variable] = myFunction

	def getAppWidget(self, label):
		return self.app_widgets.get(label, None)

	def getSettingAppWidget(self, label):
		if (label in self.setting_widgets):
			return self.setting_widgets[label]["myWidget"]

	def getCheckFunction(self, label):
		return self.checkFunctions.get(label, None)

	def yieldCheckError(self):
		"""Yields the current errors."""

		for function in self.checkFunctions.values():
			errorMessage = function(self)
			if (errorMessage):
				yield errorMessage

	def _yieldToggleWidget(self):
		for catalogue in self.setting_widgets.values():
			toggleWidget = catalogue["toggleWidget"]
			if (toggleWidget is None):
				continue
			yield toggleWidget

	def getFirstError(self, toggle = False):
		"""Returns the first error (if there are any).

		Example Input: getFirstError()
		"""

		errorMessage = next(self.yieldCheckError(), None)

		if (not toggle):
			return errorMessage

		state = errorMessage is None
		for toggleWidget in set(_yieldToggleWidget()):
			toggleWidget.setEnable(state = state)

		return errorMessage

	def _canContinue(self, variable, value):
		toggleWidget = self.setting_widgets[variable]["toggleWidget"]
		errorMessage = self.checkFunctions[variable](value)
		
		if (errorMessage):
			if (toggleWidget is not None):
				toggleWidget.disable()
			self._setStatusText(errorMessage)
			return False

		elif ((toggleWidget is not None) and (toggleWidget.checkEnabled())):
			self._setStatusText()
		return True

	@wrap_skipEvent()
	def onGUIParameter(self, event, variable, myWidget, *, check = False, save = False, getIndex = False, checkBuilding = True):
		"""The GUI is modifying a parameter."""

		if (checkBuilding and self.building):
			return

		if (getIndex):
			value = myWidget.getIndex()
		else:
			value = myWidget.getValue()

		if (check and (not self._canContinue(variable, value))):
			return

		if (save):
			self.setSetting(variable, value, refreshGUI = False)
		else:
			setattr(self.module, variable, value)

	def setGuiParameter(self, variable, value):
		"""Update the GUI to reflect the correct parameter value."""

		if (variable in self.app_widgets):
			self.app_widgets[variable].setValue(value)

		if (variable in self.setting_widgets):
			self.setting_widgets[variable]["myWidget"].setValue(value)

	def refresh_parameters(self):
		"""Loads the settings for each parameter and places it in the GUI and Modifier."""
	
		for variable, myWidget in self.app_widgets.items():
			value = getattr(self.module, variable)
			myWidget.setValue(value)
			if (variable in self.setting_widgets):
				self.setting_widgets[variable].setValue(value)

	def refresh_settings(self):
		"""Loads the settings for each parameter and places it in the GUI and Modifier."""

		for variable, myWidget in self.setting_widgets.items():
			myWidget.setValue(getattr(self.module, variable))
