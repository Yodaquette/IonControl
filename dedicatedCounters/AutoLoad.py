# *****************************************************************
# IonControl:  Copyright 2016 Sandia Corporation
# This Software is released under the GPL license detailed
# in the file "license.txt" in the top-level IonControl directory
# *****************************************************************
"""
This is the GUI for the autoload program. Includes start/stop button for loading,
a record of all loads, and an interlock to the laser frequencies returned by
the wavemeter.
"""

import copy
import functools
import operator

import logging
import os
from datetime import datetime, timedelta
import pytz

import PyQt5.uic
from PyQt5 import QtCore, QtNetwork, QtWidgets
from pyqtgraph.parametertree.Parameter import Parameter

from dedicatedCounters.LoadingHistoryModel import LoadingHistoryModel
from dedicatedCounters.WavemeterInterlockTableModel import WavemeterInterlockTableModel
from gui.TodoListSettingsTableModel import TodoListSettingsTableModel
from modules import iteratortools
from modules.AttributeComparisonEquality import AttributeComparisonEquality
from modules.GuiAppearance import restoreGuiState, saveGuiState #@UnresolvedImport
from modules.PyqtUtility import updateComboBoxItems
from modules.SequenceDict import SequenceDict
from pulseProgram.ShutterDictionary import ShutterDictionary
from modules.Utility import unique
from modules.firstNotNone import firstNotNone
from modules.formatDelta import formatDelta
from modules.quantity import Q
from modules.aggregates import max_iterable
from modules.statemachine import Statemachine, timedeltaToMagnitude
from dedicatedCounters.AutoLoadTableModel import AutoLoadSettingsTableModel
from dedicatedCounters.CounterTableModel import AutoLoadCounterTableModel
from uiModules.ComboBoxDelegate import ComboBoxDelegate
from uiModules.MultiSelectDelegate import MultiSelectDelegate
from uiModules.KeyboardFilter import KeyFilter
from uiModules.MagnitudeSpinBoxDelegate import MagnitudeSpinBoxDelegate
from pyqtgraph.parametertree.Parameter import Parameter
from modules.GuiAppearance import restoreGuiState, saveGuiState #@UnresolvedImport
import copy
from modules.PyqtUtility import updateComboBoxItems
from persist.LoadingEvent import LoadingEvent, LoadingHistory
from pyqtgraph.dockarea import Dock, DockArea
from modules.firstNotNone import firstNotNone
from pulseProgram.PulseProgramUi import PulseProgramUi
from pulser.ShutterUi import ShutterUi
from gui.ExpressionValue import ExpressionValue
from enum import Enum
from modules.descriptor import SetterProperty
from modules import iteratortools
from dedicatedCounters.OverrideRecord import OverrideRecord
from collections import defaultdict
from dedicatedCounters.CounterSetting import AdjustType
from ProjectConfig.Project import getProject

uipath = os.path.join(os.path.dirname(__file__), '..', 'ui/AutoLoad.ui')
UiForm, UiBase = PyQt5.uic.loadUiType(uipath)


def now():
    return datetime.now(pytz.utc)


class AutoLoadSettings(object):
    def __init__(self):
        # All dicts necessary
        self.shutterDict = None
        self.interlock = SequenceDict()
        self.adjustDisplayData = list()
        self.counterDisplayData = list()
        # ints to be used in multiple functions
        self.counterMask = 0
        self.adcMask = 0
        self.maxFailedAutoload = 5
        # Lists fpr changes to be populated/manipulated in multiple functions
        self.shuttlingNodes = list()
        self.previousShuttlingNode = 'Loading'
        # Bool for statemachine transitions
        self.useInterlock = False
        self.autoReload = False
        # Time Parameters for the Autoloader statemachine
        self.integrationTime = Q(100, 'ms')
        self.waitForComebackTime = Q(10, 's')
        self.postSequenceWaitTime = Q(5, 's')
        self.historyLength = Q(30, 'day')
        self.checkTime = Q(10, 's')
        self.periodicCheck = Q(5, 's')
        self.periodicLoad = Q(1, 's')
        self.preheatTime = Q(120, 's')
        self.maxTime = Q(600, 's')
        self.beyondThresholdTime = Q(3, 's')
        self.dumpTime = Q(3, 's')

    def paramDef(self):
        """
        return the parameter definition used by pyqtgraph parametertree to show the gui
        """
        return [{'name': 'Check time', 'type': 'magnitude', 'value': self.checkTime, 'tip': "Time ions need to be present before switching to trapped", 'field': 'checkTime', 'dimension': 's'},
                {'name': 'Periodic check', 'type': 'magnitude', 'value': self.periodicCheck, 'tip': "Time until a periodic check is made from loading", 'field': 'periodicCheck', 'dimension': 's'},
                {'name': 'Periodic load', 'type': 'magnitude', 'value': self.periodicLoad, 'tip': "Time until a periodic load attemp checking", 'field': 'periodicLoad', 'dimension': 's'},
                {'name': 'Preheat Time', 'type': 'magnitude', 'value': self.preheatTime, 'tip': "Time until a periodic load attemp is made from idle (Preheat)", 'field': 'preheatTime', 'dimension': 's'},
                {'name': 'Max time', 'type': 'magnitude', 'value': self.maxTime, 'tip': "Maximum time oven is on during one attempt", 'field': 'maxTime', 'dimension': 's'},
                {'name': 'Wait for comeback', 'type': 'magnitude', 'value': self.waitForComebackTime, 'tip': "time to wait for re-appearance of an ion after it is lost", 'field': 'waitForComebackTime', 'dimension': 's'},
                {'name': 'Post sequence wait', 'type': 'magnitude', 'value': self.postSequenceWaitTime, 'tip': "wait time after running sequence is finished", 'field': 'postSequenceWaitTime', 'dimension': 's'},
                {'name': 'Max failed autoload', 'type': 'magnitude', 'value': self.maxFailedAutoload, 'tip': "maximum number of consecutive failed loading attempts", 'field': 'maxFailedAutoload'},
                {'name': 'Beyond threshold time', 'type': 'magnitude', 'value': self.beyondThresholdTime, 'tip': "Time in the state BeyondThreshold before dumping ions", 'field': 'dumpTime', 'dimension': 's'},
                {'name': 'Dump time', 'type': 'magnitude', 'value': self.dumpTime, 'tip': "Time in the state dump to reset (kick out) the ions", 'field': 'beyondThresholdTime', 'dimension': 's'},
                {'name': 'History timespan', 'type': 'magnitude', 'value': self.historyLength, 'tip': "Time range to display loading history", 'field': 'historyLength'}]

    def update(self, param, changes):
        """
        update the parameter, called by the signal of pyqtgraph parametertree
        """
        logger = logging.getLogger(__name__)
        logger.debug( "ExternalParameterBase.update" )
        for param, change, data in changes:
            if change=='value':
                logger.debug( " ".join( [str(self), "update", param.name(), str(data)] ) )
                setattr( self, param.opts['field'], data)
            elif change=='activated':
                getattr( self, param.opts['field'] )()

    def __setstate__(self, state):
        """this function ensures that the given fields are present in the class object
        after unpickling. Only new class attributes need to be added here.
        """
        self.__dict__ = state
        self.shutterDict = None
        self.__dict__.setdefault( 'adjustDisplayData', list() )
        self.__dict__.setdefault( 'counterDisplayData', list() )
        self.__dict__.setdefault( 'counterMask', 0 )
        self.__dict__.setdefault( 'adcMask', 0 )
        self.__dict__.setdefault( 'maxFailedAutoload', 5 )
        self.__dict__.setdefault( 'shuttlingNodes', list())
        self.__dict__.setdefault( 'previousShuttlingNode', 'Loading')
        self.__dict__.setdefault( 'useInterlock', False )
        self.__dict__.setdefault( 'autoReload', False )
        self.__dict__.setdefault('integrationTime', Q(100,'ms'))
        self.__dict__.setdefault('waitForComebackTime', Q(10, 's'))
        self.__dict__.setdefault('postSequenceWaitTime', Q(5, 's'))
        self.__dict__.setdefault('historyLength', Q(30, 'day'))
        self.__dict__.setdefault('checkTime', Q(10, 's'))
        self.__dict__.setdefault('periodicCheck', Q(5, 's'))
        self.__dict__.setdefault('periodicLoad', Q(5, 's'))
        self.__dict__.setdefault('preheatTime', Q(120, 's'))
        self.__dict__.setdefault('maxTime', Q(600, 's'))
        self.__dict__.setdefault('beyondThresholdTime', Q(10, 's'))
        self.__dict__.setdefault('dumpTime', Q(10, 's'))

    stateFields = ['maxTime', 'checkTime', 'useInterlock', 'interlock',
                   'autoReload', 'waitForComebackTime', 'maxFailedAutoload', 'postSequenceWaitTime', 'historyLength',
                   'adjustDisplayData', 'counterDisplayData', 'beyondThresholdTime', 'dumpTime']

    def __eq__(self, other):
        return isinstance(other, AutoLoadSettings) and tuple(getattr(self,field) for field in self.stateFields) == \
                                                       tuple(getattr(other,field) for field in self.stateFields)

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(tuple(getattr(self, field) for field in self.stateFields))

    @SetterProperty
    def globalDict(self, newglobaldict):
        for data in self.counterDisplayData:
            data.globalDict = newglobaldict
        for data in self.adjustDisplayData:
            data.globalDict = newglobaldict


class Parameters(AttributeComparisonEquality):
    def __init__(self):
        self.autoSave = False

    def __setstate__(self, state):
        self.__dict__ = state


class keydefaultdict(defaultdict):
    def __missing__(self, key):
        if self.default_factory is None:
            raise KeyError(key)
        else:
            ret = self[key] = self.default_factory(key)
            return ret


class AutoLoad(UiForm, UiBase):
    ionReappeared = QtCore.pyqtSignal()
    valueChanged = QtCore.pyqtSignal(object)
    def __init__(self, config, dbConnection, pulser, dataAvailableSignal, globalVariablesUi, shutterUi, externalInstrumentObservable, parent=None):
        UiBase.__init__(self,parent)
        UiForm.__init__(self)
        self.globalVariablesUi = globalVariablesUi
        self.shutterUi = shutterUi
        self.pulseProgramUi = PulseProgramUi
        self.config = config
        self.overrideDict = keydefaultdict(lambda key: OverrideRecord(key))
        self.parameters = self.config.get('AutoLoad.Parameters', Parameters() )
        self.settings = self.config.get('AutoLoad.Settings', AutoLoadSettings())
        self.settings.globalDict = self.globalVariablesUi.globalDict
        self.settings.shutterDict = self.shutterUi.shutterTableModel.data
        self.settingsDict = self.config.get('AutoLoad.Settings.dict', dict())
        self.currentSettingsName = self.config.get('AutoLoad.SettingsName', '')
        self.loadingHistory = LoadingHistory(dbConnection)
        self.loadingHistory.open()
        self.loadingHistory.query(now() - timedelta(seconds=self.settings.historyLength.m_as('s')),
                                  now() + timedelta(hours=2), self.currentSettingsName)
        self.timer = None
        self.pulser = pulser
        self.dataSignalConnected = False
        self.outOfRangeCount=0
        self.dataSignal = dataAvailableSignal
        self.numFailedAutoload = 0
        self.constructStatemachine()
        self.timerNullTime = now()
        self.trappingTime = None
        self.voltageControl = None
        self.preheatStartTime = now()
        self.externalInstrumentObservable = externalInstrumentObservable
        self.originalResetValue = 0
        self.tempName = None
        self.revertRecord = None
        wavemeterHardwareSetting = next(iter(getProject().hardware.get('HighFinesse Wavemeter', {None: {}}).values()))
        self.wavemeterAddress = wavemeterHardwareSetting.get('uri', None)
        self.wavemeterAvailable = wavemeterHardwareSetting.get('enabled', False) and bool(self.wavemeterAddress)
        logging.getLogger(__name__).info("Wavemeter URI: {0} {1}".format(self.wavemeterAddress, "available" if self.wavemeterAvailable else "not available"))


    def constructStatemachine(self):
        self.statemachine = Statemachine('AutoLoad', now=now )
        self.statemachine.addState( 'Idle' , self.setIdle, self.exitIdle )
        self.statemachine.addState( 'Preheat', self.setPreheat )
        self.statemachine.addState( 'Load', self.setLoad )
        self.statemachine.addState( 'PeriodicCheck', self.setPeriodicCheck )
        self.statemachine.addState( 'Check', self.setCheck )
        self.statemachine.addState( 'Trapped', self.setTrapped, self.exitTrapped )
        self.statemachine.addState( 'Frozen', self.setFrozen )
        self.statemachine.addState( 'WaitingForComeback', self.setWaitingForComeback )
        self.statemachine.addState( 'AutoReloadFailed', self.setAutoReloadFailed )
        self.statemachine.addState( 'PostSequenceWait', self.setPostSequenceWait )
        self.statemachine.addState('BeyondThreshold', self.setBeyondThreshold)
        self.statemachine.addState('Dump', self.setDump)

        self.statemachine.addTransitionList( 'startButton', ['Idle', 'AutoReloadFailed'], 'Preheat',
                                         description="startButton" )
        self.statemachine.addTransition( 'timer', 'Preheat', 'Load',
                                         lambda state: state.timeInState() > self.settings.preheatTime
                                         , description="preheatOven" )
        self.statemachine.addTransition( 'timer', 'Load', 'AutoReloadFailed',
                                         lambda state: self.ovenLimitReached() and self.settings.autoReload and
                                                       self.numFailedAutoload>=self.settings.maxFailedAutoload,
                                         description="maxTime" )
        self.statemachine.addTransition( 'timer', 'Load', 'Idle',
                                         lambda state: self.ovenLimitReached() and not self.settings.autoReload,
                                         description="maxTime" )
        self.statemachine.addTransition( 'timer', 'Load', 'PeriodicCheck',
                                         lambda state: state.timeInState() > self.settings.periodicCheck,
                                         description="periodicCheck" )
        self.statemachine.addTransition( 'data', 'Load', 'Check',
                                         self.countsConditionSatisfied,
                                         description="checkLoad"  )
        self.statemachine.addTransition('data', 'Load', 'BeyondThreshold',
                                        self.countsOverRange, description='Over range')
        self.statemachine.addTransition( 'timer', 'PeriodicCheck', 'Load',
                                         lambda state: state.timeInState() > self.settings.periodicLoad,
                                         description="periodicLoad" )
        self.statemachine.addTransition( 'data', 'PeriodicCheck', 'Check',
                                         self.countsConditionSatisfied,
                                         description="checkPeriodicCheck" )
        self.statemachine.addTransition('data', 'PeriodicCheck', 'BeyondThreshold',
                                        self.countsOverRange,
                                        description="periodic check over range")
        self.statemachine.addTransition( 'timer', 'Check', 'Trapped',
                                         lambda state: state.timeInState()> self.settings.checkTime,
                                         self.loadingToTrapped,
                                         description="Success!")
        self.statemachine.addTransition('data', 'Check', 'Load',
                                        self.countsUnderRange,
                                        description="backToLoading" )
        self.statemachine.addTransition('data', 'Check', 'BeyondThreshold',
                                        self.countsOverRange,
                                        description="backToLoading")
        self.statemachine.addTransition('data', 'BeyondThreshold', 'Check',
                                        self.countsConditionSatisfied,
                                        description="backToCheck")
        self.statemachine.addTransition( 'data', 'Trapped', 'WaitingForComeback',
                                         self.countsConditionNotSatisfied,
                                         description="waitForIonToReAppear" )
        self.statemachine.addTransition( 'timer', 'WaitingForComeback', 'Idle',
                                         lambda state: state.timeInState() > self.settings.waitForComebackTime and
                                                        ( not self.settings.autoReload or
                                                        self.numFailedAutoload >=self.settings.maxFailedAutoload),
                                         description="waitForComebackTimeExceeded")
        self.statemachine.addTransition( 'timer', 'WaitingForComeback', 'Preheat',
                                         lambda state: state.timeInState() > self.settings.waitForComebackTime and
                                                       self.settings.autoReload and
                                                       self.numFailedAutoload< self.settings.maxFailedAutoload,
                                         description="waitForComebackTimeExceeded")
        self.statemachine.addTransition( 'data', 'WaitingForComeback', 'Trapped', self.countsConditionSatisfied,
                                         description="ionCameBack" )
        self.statemachine.addTransition( 'ppStopped', 'Frozen', 'PostSequenceWait' ,
                                         description="ppStopped" )
        self.statemachine.addTransition( 'timer', 'PostSequenceWait', 'Idle',
                                         lambda state: state.timeInState() > self.settings.postSequenceWaitTime and
                                                        (not self.settings.autoReload or
                                                        self.numFailedAutoload >= self.settings.maxFailedAutoload),
                                         description="postSequenceWaitTimeExceeded" )
        self.statemachine.addTransition( 'timer', 'PostSequenceWait', 'Preheat',
                                         lambda state: state.timeInState() > self.settings.postSequenceWaitTime and
                                                        self.settings.autoReload and
                                                        self.numFailedAutoload < self.settings.maxFailedAutoload,
                                         description="postSequenceWaitTimeExceeded" )
        self.statemachine.addTransition( 'data', 'PostSequenceWait', 'Trapped',
                                         self.countsConditionSatisfied,
                                         description="postSequenceWaitTime" )
        self.statemachine.addTransitionList('stopButton', ['Preheat', 'Load', 'PeriodicCheck', 'Check', 'Trapped',
                                                           'Frozen', 'WaitingForComeback', 'AutoReloadFailed',
                                                           'PostSequenceWait', 'BeyondThreshold', 'Dump'], 'Idle',
                                            description="stopButton" )
        self.statemachine.addTransition( 'ionTrapped', 'Idle', 'Trapped',
                                         transitionfunc = self.idleToTrapped,
                                         description="ionTrappedManually"  )
        self.statemachine.addTransitionList('ppStarted', ['Preheat', 'Load', 'PeriodicCheck', 'Check', 'Trapped',
                                                          'BeyondThreshold', 'WaitingForComeback', 'AutoReloadFailed',
                                                          'PostSequenceWait', 'Dump'], 'Frozen',
                                            description="ppStarted")
        self.statemachine.addTransition( 'ionStillTrapped', 'Idle', 'Trapped', lambda state: len(self.historyTableModel.history)>0 and not self.pulser.ppActive ,
                                         description="ionStillTrapped" )
        self.statemachine.addTransition( 'ionStillTrapped', 'Idle', 'Frozen', lambda state: len(self.historyTableModel.history)>0 and self.pulser.ppActive,
                                         description="ionStillTrapped" )
        self.statemachine.addTransition('timer', 'BeyondThreshold', 'Dump',
                                        lambda state: state.timeInState() > self.settings.beyondThresholdTime,
                                        description="end beyond threshold")
        self.statemachine.addTransition('timer', 'Dump', 'Load',
                                        lambda state: state.timeInState() > self.settings.dumpTime,
                                        description="end dump threshold")

    def parameter(self):
        # re-create the parameters each time to prevent a exception that says the signal is not connected
        self._parameter = Parameter.create(name='Settings', type='group',children=self.settings.paramDef())
        self._parameter.sigTreeStateChanged.connect(self.update, QtCore.Qt.UniqueConnection)
        return self._parameter

    def update(self, *args, **kwargs):
        self.settings.update(*args, **kwargs)
        self.autoSave()

    def ovenLimitReached(self):
        return timedeltaToMagnitude(now() - self.preheatStartTime) > self.settings.maxTime

    def initMagnitude(self, ui, settingsname, dimension=None  ):
        ui.setValue( getattr( self.settings, settingsname  ) )
        ui.valueChanged.connect( functools.partial( self.onValueChanged, settingsname ) )
        if dimension:
            ui.dimension = dimension

    def initCheckBox(self, ui, settingsname):
        ui.setChecked( getattr( self.settings, settingsname  ) )
        ui.stateChanged.connect( functools.partial( self.onStateChanged, settingsname ) )

    def setupUi(self,widget):
        UiForm.setupUi(self,widget)
        #Set the GUI values from the settings stored in the config files, and
        #connect the valueChanged events of each button to the appropriate method

        self.startButton.clicked.connect( self.onStart )
        self.stopButton.clicked.connect( self.onStop )
        self.saveProfileButton.clicked.connect( self.onSaveProfile )
        self.removeProfileButton.clicked.connect( self.onRemoveProfile )
        self.initCheckBox(self.autoReloadBox, 'autoReload')

        self.historyTableModel = LoadingHistoryModel(self.loadingHistory.loadingEvents )
        self.loadingHistory.beginResetModel.subscribe( self.historyTableModel.beginResetModel )
        self.loadingHistory.endResetModel.subscribe( self.historyTableModel.endResetModel )
        self.loadingHistory.beginInsertRows.subscribe( self.historyTableModel.beginInsertRows )
        self.loadingHistory.endInsertRows.subscribe( self.historyTableModel.endInsertRows )
        self.historyTableView.setModel(self.historyTableModel)
        self.keyFilter = KeyFilter(QtCore.Qt.Key_Delete)
        self.keyFilter.keyPressed.connect( self.deleteFromHistory )
        self.historyTableView.installEventFilter( self.keyFilter )

        #Wavemeter interlock setup
        self.useInterlockGui.setChecked(self.settings.useInterlock)
        self.useInterlockGui.stateChanged.connect(self.onUseInterlockClicked)
        self.tableModel = WavemeterInterlockTableModel(self.settings.interlock)
        self.tableModel.edited.connect(self.autoSave)
        self.delegate = MagnitudeSpinBoxDelegate()
        self.interlockTableView.setItemDelegateForColumn(3, self.delegate)
        self.interlockTableView.setItemDelegateForColumn(4, self.delegate)
        self.tableModel.getWavemeterData.connect(self.getWavemeterData)
        self.tableModel.getWavemeterData.connect(self.checkFreqsInRange)
        self.interlockTableView.setModel(self.tableModel)
        self.interlockTableView.resizeColumnsToContents()
        self.interlockTableView.setSortingEnabled(True)
        if self.wavemeterAvailable:
            self.am = QtNetwork.QNetworkAccessManager()
            self.checkFreqsInRange() #Begins the loop which continually checks if frequencies are in range
            for ilChannel in list(self.settings.interlock.values()):
                self.getWavemeterData(ilChannel.channel)
        else:

            self.useInterlockGui.setEnabled(False)
            #end wavemeter interlock setup
        self.interlockTableView.setEnabled(self.wavemeterAvailable)
        self.pulser.ppActiveChanged.connect( self.setDisabled )
        self.statemachine.initialize( 'Idle' )

        # Settings
        self.AdjustTableModel = AutoLoadSettingsTableModel(self.settings.adjustDisplayData, self.settings.shuttlingNodes, self.globalVariablesUi.globalDict,
                                                           self.shutterUi.shutterTableModel.data, self.statemachine.states)
        self.AdjustTableModel.edited.connect(self.calculateOverrides)
        self.AdjustTableView.setModel( self.AdjustTableModel )
        self.comboBoxDelegate = ComboBoxDelegate()
        self.magnitudeSpinBoxDelegate = MagnitudeSpinBoxDelegate(globalDict=self.globalVariablesUi.globalDict)
        self.multiSelectDelegate = MultiSelectDelegate()
        self.AdjustTableView.setItemDelegateForColumn( 0, self.comboBoxDelegate )
        self.AdjustTableView.setItemDelegateForColumn( 1, self.comboBoxDelegate )
        self.AdjustTableView.setItemDelegateForColumn( 2, self.magnitudeSpinBoxDelegate )
        self.AdjustTableView.setItemDelegateForColumn( 3, self.multiSelectDelegate )
        self.AdjustTableView.clicked.connect(self.AdjustTableModel.onClicked)
        self.dropAdjustSettingButton.clicked.connect( self.onAdjustRemoveSetting )
        self.addAdjustSettingButton.clicked.connect( self.AdjustTableModel.addSetting )

        # Counters
        self.CounterTableModel = AutoLoadCounterTableModel( self.settings.counterDisplayData,self.globalVariablesUi.globalDict )
        self.CounterTableModel.edited.connect( self.autoSave )
        self.CounterTableModel.edited.connect( self.updateCounterMask )
        self.CounterTableView.setModel( self.CounterTableModel )
        self.CounterTableView.setItemDelegateForColumn( 0, self.comboBoxDelegate )
        self.CounterTableView.setItemDelegateForColumn( 1, self.multiSelectDelegate )
        self.CounterTableView.setItemDelegateForColumn( 2, self.magnitudeSpinBoxDelegate  )
        self.CounterTableView.setItemDelegateForColumn( 3, self.magnitudeSpinBoxDelegate  )
        self.dropCounterSettingButton.clicked.connect( self.onCounterRemoveSetting )
        self.addCounterSettingButton.clicked.connect( self.CounterTableModel.addSetting )

        # Actions
        self.createAction("Last ion is still trapped", self.onIonIsStillTrapped )
        self.createAction("Trapped an ion now", self.onTrappedIonNow )
        self.createAction("auto save profile", self.onAutoSave, checkable=True, checked=self.parameters.autoSave )
        self.createAction("Add wavemeter channel", self.tableModel.addChannel)
        self.createAction("Remove selected wavemeter channels", self.onRemoveChannel)
        self.setContextMenuPolicy( QtCore.Qt.ActionsContextMenu )
        restoreGuiState( self, self.config.get('AutoLoad.guiState') )

        self.profileComboBox.addItems( self.settingsDict.keys() )
        if self.currentSettingsName in self.settingsDict:
            self.profileComboBox.setCurrentIndex( self.profileComboBox.findText(self.currentSettingsName))
        else:
            self.currentSettingsName = str( self.profileComboBox.currentText() )
        self.profileComboBox.currentIndexChanged[str].connect(self.onLoadProfile)
        self.profileComboBox.lineEdit().editingFinished.connect( self.autoSave )

        self.setProfile( self.currentSettingsName, self.settings )
        self.calculateOverrides()
        self.autoSave()

    def setProfile(self, name, profile):
        self.settings = profile
        self.settings.globalDict = self.globalVariablesUi.globalDict
        self.settings.shutterDict = self.shutterUi.shutterTableModel.data
        self.currentSettingsName = name
        self.parameterWidget.setParameters( self.parameter() )
        self.useInterlockGui.setChecked(self.settings.useInterlock)
        self.autoReloadBox.setChecked(self.settings.autoReload)
        self.loadingHistory.query( now() - timedelta(seconds=self.settings.historyLength.m_as('s')),
                                   now() + timedelta(hours=2), self.currentSettingsName)
        self.AdjustTableModel.setSettings(self.settings.adjustDisplayData)
        self.CounterTableModel.setSettings(self.settings.counterDisplayData)
        self.tableModel.setChannelDict( self.settings.interlock )

    def onLoadProfile(self, name):
        name = str(name)
        if name in self.settingsDict and name!=self.currentSettingsName:
            self.setProfile( name, copy.deepcopy( self.settingsDict[name] ) )

    def onSaveProfile(self):
        name = str(self.profileComboBox.currentText())
        isNew = name not in self.settingsDict
        self.settingsDict[name] = copy.deepcopy( self.settings )
        if isNew:
            updateComboBoxItems( self.profileComboBox, sorted(self.settingsDict.keys()), name)
        self.saveProfileButton.setEnabled( False )

    def onRemoveProfile(self):
        name = str(self.profileComboBox.currentText())
        if name in self.settingsDict:
            self.settingsDict.pop(name)
            updateComboBoxItems( self.profileComboBox, sorted(self.settingsDict.keys()))
            name = str(self.profileComboBox.currentText())
            self.onLoadProfile(name)

    def onAutoSave(self, enable):
        self.parameters.autoSave = enable

    def updateCounterMask(self):
        newCounterMask = functools.reduce(operator.ior, (elem.counterMask for elem in self.settings.counterDisplayData),
                                          0)
        if self.settings.counterMask != newCounterMask:
            self.settings.counterMask = newCounterMask
            self.valueChanged.emit(self.settings)

    def calculateOverrides(self):
        """Calculate the changes necessary in each state.

        This function is called when the program starts, and whenever the overrides table is changed.
        """
        # overrideDict is a defaultDict, key -> state, value -> OverrideRecord associated with state
        # one OverrideRecord for each state, includes all overrides assigned to each state
        self.overrideDict.clear()
        for adjust in self.settings.adjustDisplayData:
            if adjust.adjType == AdjustType.Global:
                for state in adjust.states:
                    self.overrideDict[state].globals[adjust.name] = adjust.value.value
            elif adjust.adjType == AdjustType.Shutter:
                for state in adjust.states:
                    self.overrideDict[state].shutters[adjust.name] = adjust.value
            elif adjust.adjType == AdjustType.Voltage_node:
                for state in adjust.states:
                    self.overrideDict[state].voltages = adjust.name
                    self.overrideDict[state].shuttle = adjust.value
        self.autoSave()

    def autoSave(self):
        if self.parameters.autoSave:
            self.onSaveProfile()
            self.saveProfileButton.setEnabled( False )
        else:
            self.saveProfileButton.setEnabled( self.saveable() )

    def saveable(self):
        name = str(self.profileComboBox.currentText())
        return name != '' and ( name not in self.settingsDict or not (self.settingsDict[name] == self.settings))

    def onAdjustRemoveSetting(self):
        for index in sorted(unique([ i.row() for i in self.AdjustTableView.selectedIndexes() ]),reverse=True):
            self.AdjustTableModel.dropSetting(index)
        self.autoSave()

    def onCounterRemoveSetting(self):
        for index in sorted(unique([ i.row() for i in self.CounterTableView.selectedIndexes() ]),reverse=True):
            self.CounterTableModel.dropSetting(index)
        self.autoSave()

    def setVoltageControl(self, voltageControl ):
        if voltageControl:
            self.voltageControl = voltageControl
            self.voltageControl.shuttlingNodesObservable().subscribe( self.onShuttlingNodesChanged )
            self.onShuttlingNodesChanged()

    def onShuttlingNodesChanged(self):
        self.settings.shuttlingNodes = [""] + self.voltageControl.shuttlingNodes()
        self.AdjustTableModel.nodeList = self.settings.shuttlingNodes
        self.parameterWidget.setParameters( self.parameter() )

    def createAction(self, text, slot, target=None, checkable=False, checked=False ):
        action = QtWidgets.QAction( text, self )
        action.triggered.connect( slot )
        action.setCheckable(checkable)
        action.setChecked(checked)
        if target is not None:
            target.addAction( action )
        else:
            self.addAction( action )

    def deleteFromHistory(self):
        for row in sorted(unique([ i.row() for i in self.historyTableView.selectedIndexes() ]), reverse=False):
            self.historyTableModel.removeRow(row)

    def onRemoveChannel(self):
        for index in sorted(unique([ i.row() for i in self.interlockTableView.selectedIndexes() ]), reverse=True):
            self.tableModel.removeChannel(index)
        self.autoSave()

    def onStateChanged(self, name, state):
        setattr( self.settings, name, state==QtCore.Qt.Checked )
        self.autoSave()

    def onUseInterlockClicked(self):
        """Run if useInterlock button is clicked. Change settings to match."""
        self.settings.useInterlock = self.useInterlockGui.isChecked()
        self.autoSave()

    def onWavemeterError(self, channel, reply, error):
        """Print out received error"""
        logging.getLogger(__name__).warning("Error {0} accessing wavemeter at '{1}'".format(error, self.wavemeterAddress))
        reply.finished.disconnect()  # necessary to make reply garbage collectable
        reply.error.disconnect()
        reply.deleteLater()
        del reply

    def getWavemeterData(self, channel):
        """Get the data from the wavemeter at the specified channel."""
        if channel in self.settings.interlock:
            if self.settings.interlock[channel].enable:
                address = self.wavemeterAddress + "/wavemeter/wavemeter/wavemeter-status?channel={0}".format(int(channel))
                reply = self.am.get( QtNetwork.QNetworkRequest(QtCore.QUrl(address)))
                reply.error.connect(functools.partial(self.onWavemeterError, int(channel),  reply) )
                reply.finished.connect(functools.partial(self.onWavemeterData, int(channel), reply))
            else:
                self.checkFreqsInRange()

    def onWavemeterData(self, channel, reply):
        """Execute when reply is received from the wavemeter. Display it on the
           GUI, and check whether it is in range."""
        if channel in self.settings.interlock:
            ilChannel = self.settings.interlock[channel]
            if reply.error()==0:
                value = float(reply.readAll())
                self.tableModel.setCurrent( channel, round(value, 4) )
                if ilChannel.lastReading==value:
                    ilChannel.identicalCount += 1
                else:
                    ilChannel.identicalCount = 0
                ilChannel.lastReading = value
            #freq_string = "{0:.4f}".format(self.channelResult[channel]) + " GHz"
        #read the wavemeter channel once per second
            if ilChannel.enable:
                QtCore.QTimer.singleShot(1000, functools.partial(self.getWavemeterData, channel))
        self.checkFreqsInRange()
        reply.finished.disconnect()  # necessary to make reply garbage collectable
        reply.error.disconnect()
        reply.deleteLater()
        del reply

    def checkFreqsInRange(self):
        """Check whether all laser frequencies being used by the interlock are in range.

            If they are not, loading is stopped/prevented, and the lock status bar turns
            from green to red. If the lock is not being used, the status bar is black."""
        enabledChannels = sum(1 if x.enable else 0 for x in self.settings.interlock.values() )
        outOfRangeChannels = sum(1 if x.enable and not x.inRange else 0 for x in self.settings.interlock.values() )
        maxIdenticalReading = max_iterable(x.identicalCount if x.enable else 0 for x in self.settings.interlock.values() )
        if enabledChannels==0:
            #if no channels are checked, set bar on GUI to black
            self.allFreqsInRange.setStyleSheet("QLabel {background-color: rgb(0, 0, 0)}")
            self.allFreqsInRange.setToolTip("No channels are selected")
            self.outOfRangeCount = 0
        elif outOfRangeChannels==0:
            if maxIdenticalReading is None or maxIdenticalReading<10:
                #if all channels are in range, set bar on GUI to green
                self.allFreqsInRange.setStyleSheet("QLabel {background-color: rgb(0, 198, 0)}")
                self.allFreqsInRange.setToolTip("All laser frequencies are in range")
                self.outOfRangeCount = 0
            else:
                self.allFreqsInRange.setStyleSheet("QLabel {background-color: rgb(198, 198, 0)}")
                self.allFreqsInRange.setToolTip("All laser frequencies seem in range but some readings are struck")
                self.outOfRangeCount += 1
        else:
            #Because of the bug where the wavemeter reads incorrectly after calibration,
            #Loading is only inhibited after 10 consecutive bad measurements
            if self.outOfRangeCount < 20 : #Count how many times the frequency measures out of range. Stop counting at 20. (why count forever?)
                self.outOfRangeCount += 1
#                 self.allFreqsInRange.setStyleSheet("QLabel {background-color: rgb(255, 255, 0)}")
#                 self.allFreqsInRange.setToolTip("There are laser frequencies temporarily of range")
            if (self.outOfRangeCount >= 10):
                #set bar on GUI to red
                self.allFreqsInRange.setStyleSheet("QLabel {background-color: rgb(255, 0, 0)}")
                self.allFreqsInRange.setToolTip("There are laser frequencies out of range")
                #This is the interlock: loading is inhibited if frequencies are out of range
                if self.settings.useInterlock:
                    self.statemachine.processEvent( 'outOfLock' )

    def onValueChanged(self,attr,value):
        """Change the value of attr in settings to value"""
        setattr( self.settings, attr, value)
        self.autoSave()

    def onArrayValueChanged(self, index, attr, value):
        """Change the value of attr[index] in settings to value"""
        a = getattr(self.settings, attr)
        a[index] = value
        self.autoSave()

    def onStart(self):
        """Execute when start button is clicked. Begin loading if idle."""
        self.tempName = None
        self.settings.shutterAdjustRevertList = list(iteratortools.bits(self.pulser.shutter, 16))
        self.updateCounterMask()
        if self.statemachine.processEvent( 'startButton' ) == 'Preheat':
            self.numFailedAutoload = 0

    def onStop(self):
        """Execute when stop button is clicked. Stop loading."""
        self.statemachine.processEvent( 'stopButton' )

    def countsConditionSatisfied(self, state, data):
        temp = list(e.inRange(data.data[e.counter] / data.integrationTime) for e in self.settings.counterDisplayData if state.name in e.states)
        return all(temp) if temp else False

    def allCountsAboveAboveMin(self, state, data):
        return all(not e.underRange(data.data[e.counter] / data.integrationTime) for e in self.settings.counterDisplayData if state.name in e.states)

    def countsUnderRange(self, state, data):
        temp = list(e.underRange(data.data[e.counter] / data.integrationTime) for e in self.settings.counterDisplayData if state.name in e.states)
        return any(temp) if temp else True

    def countsOverRange(self, state, data):
        return any(e.overRange(data.data[e.counter] / data.integrationTime) for e in self.settings.counterDisplayData if state.name in e.states)

    def countsConditionNotSatisfied(self, state, data):
        return not self.countsConditionSatisfied(state, data)

    def timerConditionSatisfied(self, state):
        return self.state.timeInState()>self.settings.checkTime

    def changeSettings(self, state):
        """change the globals, shutters, and voltages for the new state.

        This function first gets the values that need to be set for this state. Then it calculates how to revert from
        this state, incorporating the reversions required by the previous state.
        """
        override = self.overrideDict[state]  # the overrides requested for this state
        # newrevert is the reversions that will be necessary to undo the changes in this state,
        # taking into account changes from previous states (in self.revertRecord)
        newrevert = override.revertRecord(self.globalVariablesUi.globalDict,
                                          self.shutterUi.dataContainer[0], self.pulser.shutter,
                                          self.voltageControl,
                                          revert=self.revertRecord)

        # updatedOverride is an OverrideRecord that includes both the changes necessary for this state, and the undoing
        # of changes from the previous state, if those parameters are not also being changed in this state.
        updatedOverride = override.setdefault(self.revertRecord)
        #apply the changes
        updatedOverride.apply(self.globalVariablesUi.globalDict,
                              self.shutterUi.dataContainer[0], self.pulser,
                              self.voltageControl)
        self.revertRecord = newrevert
        # self.externalInstrumentObservable( lambda: self.statemachine.processEvent('doneAdjusting') )

    def setIdle(self):
        """Execute when the loading process is set to idle. Disable timer, do not
           pay attention to the count rate, and turn off the ionization laser and oven."""
        self.changeSettings('Idle')
        self.startButton.setEnabled( True )
        self.stopButton.setEnabled( True )
        self.timer = None
        self.elapsedLabel.setStyleSheet("QLabel { color:black; }")
        self.statusLabel.setText("Idle")
        self.disconnectDataSignal()

    def exitIdle(self):
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect( self.onTimer )
        self.timer.start(100)
        self.connectDataSignal()
        self.timerNullTime = now()

    def setPreheat(self):
        """Execute when the loading process begins. Turn on timer, turn on oven."""
        self.changeSettings('Preheat')
        self.startButton.setEnabled( True )
        self.stopButton.setEnabled( True )
        self.elapsedLabel.setStyleSheet("QLabel { color:red; }")
        self.statusLabel.setText("Preheating")
        self.numFailedAutoload += 1
        self.timerNullTime = now()
        self.preheatStartTime = now()

    def setLoad(self):
        """Execute after preheating. Turn on ionization laser, and begin
           monitoring count rate."""
        self.changeSettings('Load')
        self.startButton.setEnabled( True )
        self.stopButton.setEnabled( True )
        self.elapsedLabel.setStyleSheet("QLabel { color:purple; }")
        self.statusLabel.setText("Loading")

    def setPeriodicCheck(self):
        """Execute when periodicly checking for an ion."""
        self.changeSettings('PeriodicCheck')
        self.startButton.setEnabled( True )
        self.stopButton.setEnabled( True )
        self.elapsedLabel.setStyleSheet("QLabel { color:darkCyan; }")
        self.statusLabel.setText("Periodic Check")

    def setCheck(self):
        """Execute when count rate goes over threshold."""
        self.changeSettings('Check')
        self.startButton.setEnabled( True )
        self.stopButton.setEnabled( True )
        self.elapsedLabel.setStyleSheet("QLabel { color:blue; }")
        self.checkStarted = now()
        self.statusLabel.setText("Checking for ion")

    def setPostSequenceWait(self):
        self.changeSettings('PostSequenceWait')
        self.statusLabel.setText("Waiting after sequence finished.")

    def setBeyondThreshold(self):
        self.changeSettings('BeyondThreshold')
        self.statusLabel.setText("Too many ions, waiting to make sure.")

    def setDump(self):
        self.changeSettings('Dump')
        self.statusLabel.setText("Too many ions, dumping the trap.")

    def loadingToTrapped(self, check,trapped):
        logger = logging.getLogger(__name__)
        logger.info("Loading Trapped")
        self.loadingTime = check.enterTime - self.timerNullTime
        self.loadingHistory.addLoadingEvent( LoadingEvent( loadingDuration=self.loadingTime, trappingTime=self.checkStarted, loadingProfile=self.currentSettingsName) )

    def idleToTrapped(self, check, trapped):
        logger = logging.getLogger(__name__)
        logger.info("Idle Trapped")
        self.loadingTime = timedelta(0)
        self.loadingHistory.addLoadingEvent( LoadingEvent( loadingDuration=self.loadingTime, trappingTime=now(), loadingProfile=self.currentSettingsName) )

    def setTrapped(self):
        self.changeSettings('Trapped')
        self.startButton.setEnabled( True )
        self.stopButton.setEnabled( True )
        self.elapsedLabel.setStyleSheet("QLabel { color:green; }")
        self.statusLabel.setText("Trapped :)")
        self.trappingTime = firstNotNone(self.loadingHistory.lastEvent().trappingTime, now())
        self.timerNullTime = self.trappingTime
        self.trappingTime = self.trappingTime
        # self.checkStarted = self.trappingTime
        self.ionReappeared.emit()

    def exitTrapped(self):
        self.updateTrappingTime()

    def updateTrappingTime(self):
        duration = now()-self.trappingTime
        self.loadingHistory.setTrappingDuration(duration)
        self.historyTableModel.updateLast()

    def setFrozen(self):
        self.changeSettings( 'Frozen')
        self.startButton.setEnabled( False )
        self.stopButton.setEnabled( False )
        self.elapsedLabel.setStyleSheet("QLabel { color:grey; }")
        self.statusLabel.setText("Currently running pulse program")

    def setWaitingForComeback(self):
        self.changeSettings( 'WaitingForComeback')
        self.statusLabel.setText("Waiting to see if ion comes back")
        self.timerNullTime = now()

    def setAutoReloadFailed(self):
        self.changeSettings( 'AutoReloadFailed')
        self.startButton.setEnabled( True )
        self.stopButton.setEnabled( True )
        self.timer = None
        self.elapsedLabel.setStyleSheet("QLabel { color:black; }")
        self.statusLabel.setText("Auto reload failed")
        self.disconnectDataSignal()

    def onIonIsStillTrapped(self):
        self.statemachine.processEvent( 'ionStillTrapped' )

    def onTrappedIonNow(self):
        current = now()
        self.timerNullTime = current
        self.trappingTime = current
        self.checkStarted = current
        self.statemachine.processEvent('ionTrapped')

    def onTimer(self):
        """Execute whenever the timer sends a timeout signal, which is every 100 ms.
           Trigger status changes based on elapsed time. This controls the flow
           of the loading process."""
        self.elapsed = now()-self.timerNullTime
        self.elapsedLabel.setText(formatDelta(self.elapsed) )
        self.statemachine.processEvent('timer')

    def onData(self, data ):
        """Execute when count rate data is received. Change state based on count rate."""
        if data:
            if self.settings.counterMask is None:
                self.updateCounterMask()
            self.statemachine.processEvent( 'data', data )

    def onClose(self):
        self.statemachine.processEvent( 'stopButton' )

    def saveConfig(self):
        self.config['AutoLoad.Settings'] = self.settings
        self.config['AutoLoad.guiState'] = saveGuiState(self)
        self.config['AutoLoad.Settings.dict'] = self.settingsDict
        self.config['AutoLoad.SettingsName'] = self.currentSettingsName
        self.config['AutoLoad.Parameters'] = self.parameters
        if self.statemachine.currentState == 'Trapped':
            self.loadingHistory.setTrappingDuration(now() - self.trappingTime)

    def setDisabled(self, disable):
        if disable:
            self.statemachine.processEvent('ppStarted')
        else:
            self.statemachine.processEvent('ppStopped')

    def connectDataSignal(self):
        try:
            self.dataSignal.connect(self.onData, QtCore.Qt.UniqueConnection)
        except TypeError:
            pass  # already connected
        self.dataSignalConnected = True

    def disconnectDataSignal(self):
        if self.dataSignalConnected:
            self.dataSignal.disconnect( self.onData )
            self.dataSignalConnected = False
