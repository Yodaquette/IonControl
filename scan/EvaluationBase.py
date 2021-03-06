# *****************************************************************
# IonControl:  Copyright 2016 Sandia Corporation
# This Software is released under the GPL license detailed
# in the file "license.txt" in the top-level IonControl directory
# *****************************************************************

from modules.Observable import Observable
from modules.SequenceDict import SequenceDict
from PyQt5 import QtCore
import logging
import copy
import numpy

EvaluationAlgorithms = {}

class EvaluationException(Exception):
    pass

class EvaluationMeta(type):
    def __new__(self, name, bases, dct):
        evalclass = super(EvaluationMeta, self).__new__(self, name, bases, dct)
        if name!='EvaluationBase':
            if 'name' not in dct:
                raise EvaluationException("Evaluation class needs to have class attribute 'name'")
            EvaluationAlgorithms[dct['name']] = evalclass
        return evalclass


class EvaluationBase(Observable, metaclass=EvaluationMeta):
    hasChannel = True
    def __init__(self, globalDict=None, settings= None):
        Observable.__init__(self)
        self.settings = settings if settings else dict()
        self.globalDict = globalDict if globalDict else dict()
        self.setDefault()
        self.settingsName = None

    def setDefault(self):
        pass

    def parameters(self):
        """return the parameter definitions used by the parameterTable"""
        return SequenceDict()
               
    def update(self, parameter):
        """update the parameter changed in the parameterTable"""
        if parameter.dataType != 'action':
            self.settings[parameter.name] = parameter.value
            if parameter.text:
                self.settings[(parameter.name,'text')] = parameter.text
            else:
                self.settings.pop((parameter.name,'text'), None)
            self.firebare()
        else:
            getattr(self, parameter.value)()
            
    def setSettings(self, settings, settingsName):
        try:
            for name, value in self.settings.items():
                settings.setdefault(name, value)
            self.settings = settings
            self.settingsName = settingsName if settingsName else "unnamed"
        except Exception as ex:
            logging.getLogger(__name__).exception(ex)
        
    def setSettingsName(self, settingsName):
        self.settingsName = settingsName

    def __deepcopy__(self, memo=None):
        return type(self)( self.globalDict, settings=copy.deepcopy(self.settings, memo) )
  
    def histogram(self, data, evaluation, histogramBins=50 ):
        countarray = evaluation.getChannelData(data)
        y, x = numpy.histogram( countarray, range=(0, histogramBins), bins=histogramBins)
        return y, x, None   # third parameter is optional function 
    