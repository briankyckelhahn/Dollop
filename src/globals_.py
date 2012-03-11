# -*- coding: utf-8 -*-

# Copyright (C) 2012 Brian Kyckelhahn
#
# Licensed under a Creative Commons Attribution-NoDerivs 3.0 Unported 
# License (the "License"); you may not use this file except in compliance 
# with the License. You may obtain a copy of the License at
#
#      http://creativecommons.org/licenses/by-nd/3.0/
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# Things defined here are used globally but are not constants
# (or configurable values).


import ctypes
from ctypes import wintypes
import inspect
import logging
import os
import sys
import wx

import constants


moveLevel = logging.CRITICAL
traceLevel = logging.CRITICAL
storageLevel = logging.CRITICAL

#formatter = logging.Formatter("%(asctime)s:%(name)s: %(message)s")

FORMAT = "%(asctime)s:%(name)s: %(message)s"
logging.basicConfig(format=FORMAT)


moveLogger = logging.getLogger('movement')
moveLogger.setLevel(moveLevel)
#moveHandler = logging.StreamHandler()
#moveHandler.setLevel(moveLevel)
#moveHandler.setFormatter(formatter)
#moveLogger.addHandler(moveHandler)

# Tracing of the most important statements.
basicTraceLogger = logging.getLogger('basicTrace')
basicTraceLogger.setLevel(logging.CRITICAL)

traceLogger = logging.getLogger('tracing')
traceLogger.setLevel(traceLevel)
#traceHandler = logging.StreamHandler()
#traceHandler.setLevel(traceLevel)
#traceHandler.setFormatter(formatter)
#traceLogger.addHandler(traceHandler)

imageFindingLogger = logging.getLogger('imageFinding')
imageFindingLogger.setLevel(logging.CRITICAL)
# Commenting the imageFindingHandler eliminates duplicate printed
# statements (the dupes that don't appear have timestamps, unlike
# the ones they duplicate).
#imageFindingHandler = logging.StreamHandler()
#imageFindingHandler.setLevel(imageFindingLevel)
#imageFindingHandler.setFormatter(formatter)
#imageFindingLogger.addHandler(imageFindingHandler)

storageLogger = logging.getLogger('tracing')
storageLogger.setLevel(storageLevel)
#storageHandler = logging.StreamHandler()
#storageHandler.setLevel(storageLevel)
#storageHandler.setFormatter(formatter)
#storageLogger.addHandler(storageHandler)

adbLogger = logging.getLogger('adb')
adbLogger.setLevel(logging.CRITICAL)

sendCommandLogger = logging.getLogger('sendCommand')
sendCommandLogger.setLevel(logging.CRITICAL)

profiler = logging.getLogger('profiler')
profiler.setLevel(logging.CRITICAL)
#profilerHandler = logging.StreamHandler()
#profilerHandler.setLevel(logging.CRITICAL)
#profilerHandler.setFormatter(formatter)
#profiler.addHandler(profilerHandler)

keycodeLogger = logging.getLogger('keycode')
keycodeLogger.setLevel(logging.CRITICAL)


# I don't actually know what the /dev files for stdin
# and stdout are on AIX or HP-UX; this is a guess.
if sys.platform.startswith(('linux', 'aix', 'hp-ux')):
    def STDIN():
        return open('/dev/stdin', 'r')
    def STDOUT():
        return open('/dev/stdout', 'w')
elif sys.platform.startswith('win'):
    def STDIN():
        return open('CONIN$', 'r')
    def STDOUT():
        return open('CONOUT$', 'w')


class ADBDeviceNotFoundException(Exception):
    pass

class ADBMisconfigured(Exception):
    pass

class CorruptedDatabaseException(Exception):
    pass


def getExecutableOrRunningModulePath():
    if 'win' in sys.platform and not constants.EXECUTABLE_NAME_REGULAR_CASE + '.exe' in sys.executable:
        return os.path.abspath(__file__)
    elif 'linux' in sys.platform:
        raise Exception("not implemented")
    return os.path.abspath(sys.executable)



def getApplicationPath():
    # Returns the path to the uppermost application directory, i.e. that which contains
    # the versions of the application.
    if 'win' in sys.platform and not constants.EXECUTABLE_NAME_REGULAR_CASE + '.exe' in sys.executable:
        # returns tst of tst/d/src/globals_.py
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    elif 'linux' in sys.platform:
        raise Exception("not implemented")
    # returns TST of TST/TST.0.8.1/gui/gui
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(sys.executable))))    


def bdbg():
    # From blog.mfabrik.com.
    if constants.SET_TRACE:
        import pdb
        import sys
        # Does not work in a spawned multiprocessing.Process:
        # pdb.Pdb(stdin=getattr(sys, '__stdin__'), stdout=getattr(sys, '__stderr__')).set_trace(sys._getframe().f_back)
        pdb.Pdb(stdin=STDIN(), stdout=STDOUT()).set_trace(sys._getframe().f_back)


def dprint(*args):
    if constants.PRINT_DPRINT:
        args_ = ' '.join([repr(x) if type(x) != str else x for x in args]) + '\n'
        sys.stdout.write(args_); sys.stdout.flush()


def dprintParent():
    if constants.PRINT_DPRINT:
        sys.stdout.write("Current routine: " + inspect.getframeinfo(sys._getframe().f_back).function + "\nParent of current routine: " + inspect.getframeinfo(sys._getframe().f_back.f_back).function + "\n")
        sys.stdout.flush()


def leftprint(*args):
    # This is a print statement that is meant for the user, not debugging.
    args_ = ' '.join([repr(x) if type(x) != str else x for x in args]) + '\n'
    sys.stdout.write(args_); sys.stdout.flush()


def okprint(*args):
    # This is a print statement that is meant for the user, not debugging.
    args_ = '\t' + ' '.join([repr(x) if type(x) != str else x for x in args]) + '\n'
    sys.stdout.write(args_); sys.stdout.flush()


def profile(prefix=""):
    def calledOnRoutine(fun):
        if constants.PROFILE:
            def innerdec(*args, **kwargs):
                print 'STARTING ' + prefix + ' ' + fun.__name__
                returned = fun(*args, **kwargs)
                print 'ENDING ' + prefix + ' ' + fun.__name__
                return returned
        else:
            def innerdec(*args, **kwargs):
                returned = fun(*args, **kwargs)
                return returned
        return innerdec
    return calledOnRoutine


# From utils/wxhelloworld.py, which is from http://wiki.wxpython.org/wxPython%20by%20Example.
def showErrorDialog(title, msg):
    dlg = wx.MessageDialog(None,
                           msg,
                           title,
                           wx.OK | wx.ICON_ERROR)
    dlg.ShowModal()
    dlg.Destroy()


def showErrorDialogCreateApp(title, msg):
    app = wx.App(redirect=True)   # Error messages go to popup window
    showErrorDialog(title, msg)


def getUserDocumentsPath():
    # http://stackoverflow.com/questions/3927259/how-do-you-get-the-exact-path-to-my-documents
    dll = ctypes.windll.shell32
    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    dll.SHGetSpecialFolderPathW(None, buf, 0x0005, False)
    return buf.value


def getValueFromConfigFile(section, parameter):
    import ConfigParser
    configPath = os.path.join(getUserDocumentsPath(), 
                              constants.APP_DIR, 
                              constants.APPLICATION_NAME_REGULAR_CASE + '.cfg')
    configParser = ConfigParser.RawConfigParser()
    
    if os.path.exists(configPath):
        try:
            configParser.read(configPath)
        except:
            return None, None
        try:
            theValue = configParser.get(section, parameter)
        except:
            return configParser, None
        return configParser, theValue
    else:
        return None, None
