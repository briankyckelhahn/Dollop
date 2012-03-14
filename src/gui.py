# -*- coding: utf-8 -*-
#
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


import binascii
import ConfigParser
import copy
import cStringIO
import ctypes
import cv
import distutils.spawn
import Image #PIL
import logging
import math
import multiprocessing
import optparse
import os
import random
import re
import shutil
import signal
import socket
import string
import StringIO
import subprocess
import sys
import threading
import time
import traceback
import wx
import wx.lib.buttons
import wx.lib.agw.customtreectrl as customtreectrl
import wx.lib.agw.genericmessagedialog as GMD
from wx.lib.embeddedimage import PyEmbeddedImage
import wx.lib.platebtn as platebtn
import wx.lib.scrolledpanel
import wx.lib.sized_controls as sc
import wxPython.wx

import adbTransport
from arialBaselineIdentification import arialBaselineIdentification
import screenProperties
import subprocess
import ocrBoxProcess
import plateButton
import config
import constants
import cylevenshtein
from deviceFiles import allDeviceConstants
import globals_
from globals_ import *
import recorder
import utils


# XXX Not working when CTRL C is pressed.
#def abortHandler(foo, bar):
#    app.recorder.storage.cur.commit()
#    app.recorder.storage.conn.close()
#signal.signal(signal.SIGABRT, abortHandler)
#signal.signal(signal.SIGINT, abortHandler)
#signal.signal(signal.SIGTERM, abortHandler)


ADB_ERROR_ID = wx.NewId()
CAMERA_RESULT_ID = wx.NewId()
TARGET_IMAGE_UPDATE_ID = wx.NewId()
RELOAD_GUI_ID = wx.NewId()

IMAGE_FINDING_SLEEP=5
KEYEVENT_SPACE = 61
ABORT_REQUESTED, PAUSE_REQUESTED, RESUME_PLAY_REQUESTED = range(3)
[wxID_ENTER_TEXT, wxID_SESSIONSBOX, wxID_RECORD, wxID_ENTER_WAIT_TIME] = [wx.NewId() for _init_ctrls in range(4)]

# The multiprocessing.Queues and Arrays are made global due to a restriction in Windows. If the Queue is passed to a class
# and made a member there, an error will be encountered: "RuntimeError: [Queue|SynchronizedString] objects should only be
# shared between processes through inheritance". See "Ensure that all arguments to Process.__init__() are picklable."
# in http://docs.python.org/library/multiprocessing.html and "Making q global works...:" in
# http://stackoverflow.com/questions/3217002/how-do-you-pass-a-queue-reference-to-a-function-managed-by-pool-map-async.

IMAGE_ARRAY = None


import replayProcess


def EVT_RESULT(window, theID, resultMethod):
    window.Connect(-1, -1, theID, resultMethod)


class IndividualTestManager(object):
    @profile("IndividualTestManager")
    def __init__(self, appFrame=None, monkeyrunnerPath=None):
        self.appFrame = appFrame
        self.monkeyrunnerPath = monkeyrunnerPath

        if appFrame:
            self.noGUI = False
        else:
            self.noGUI = True
        self.testFilePaths = []
        # When a test is loaded, this is set to 0. When tests are added, it isn't
        # changed. When the user clicks on a different test within the viewer,
        # it's set to that test's index.
        self.currentTestIndex = -1
        self.viewerToGUISocketPort = 64445
        self.filename = None
        self.recorder = recorder.Recorder(backUpDB=True)
        # XXX this should be a property of the device window so that we don't have to
        # record on all devices at the same time.
        self.isRecording = False
        self.sessionID = ''
        self.recordingTestAtPath = None
        self.playName = None
        self.replayThread = None
        # A list of lists of inputEvents. Each list within the single, outermost list
        # corresponds to the test named at the same index in self.testFilePaths.
        self.inputEvents = []

        self.playStatus = constants.PLAY_STATUS_NO_SESSION_LOADED
        
        self.replayControlQueue = multiprocessing.Queue()
        self.eventsBoxQueue = multiprocessing.Queue()
        self.ocrBoxProcessQueue = multiprocessing.Queue()

        self.ocrBoxProcessIDs = []


    def identifyDeviceProperties(self, configParser):
        attempts = 1
        while attempts < 3:
            try:
                self.adbForkServerProcess = subprocess.Popen([config.adbPath, "start-server"],
                                                             stdout=subprocess.PIPE,
                                                             stderr=subprocess.PIPE)
            except:
                msg  = "Please enter the full path to adb. If you do not have adb, you will find\n"
                msg += "it in the Android SDK. See http://developer.android.com/sdk/."
                dlg = wx.TextEntryDialog(self.appFrame, msg, "Path to adb needed")
                dlgButtonPressed = dlg.ShowModal()
                adbPath = dlg.GetValue()
                config.adbPath = adbPath
                dlg.Destroy()
                configPath = os.path.join(getUserDocumentsPath(), 
                                          constants.APP_DIR, 
                                          constants.APPLICATION_NAME_REGULAR_CASE + '.cfg')
                try:
                    configParser.set('Global', 'adbpath', adbPath)
                except:
                    pass
                try:
                    if os.path.exists(configPath):
                        with open(configPath, 'wb') as fp:
                            configParser.write(fp)
                except:
                    # It's not a deal-breaker if the config file, f/ some strange reason, can't be created.
                    pass
            else:
                break
            attempts += 1


        dt = adbTransport.ADBTransport("", noGUI=self.noGUI)
        tries = 0
        activeDeviceSRE = re.compile("^(.*)\s+device$")
        offlineDeviceSRE = re.compile("^(.*)\s+offline$")
        while tries < constants.MAX_NUMBER_ADB_ATTEMPTS:
            if sys.platform.startswith('linux'):
                proc = subprocess.Popen("ps -e".split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                o, e = proc.communicate()
                outputLines = o.split()
                for line in outputLines:
                    if "adb" in line and "defunct" in line:
                        pass

            # "adb devices" returns within two or three seconds, but sendCommand
            # takes a long time to return when 'adb fork-server server' isn't 
            # already running (it probably only returns in that case once the
            # timeout I created is reached).
            # Calling "adb fork-server server" directly is probably not a good
            # idea, as it doesn't appear in the ADB documentation, and prints 
            # "cannot bind 'tcp:5037'" when the server is already running. By
            # contrast, "adb start-server" is documented as starting the server
            # *if it isn't already running*.
                
            output, e = dt.sendCommand("devices", timeout=10)
            dprint("adb devices output:", output, "and error:", e)
            serialNos, offline = [], []
            if output:
                for line in output.split(os.linesep):
                    m = activeDeviceSRE.match(line)
                    if m:
                        serialNos += [m.groups()[0]]
                    else:
                        m = offlineDeviceSRE.match(line)
                        if m:
                            offline += [m.groups()[0]]
            tries += 1
            if serialNos != []:
                break
            time.sleep(1)

        self.devices = []
        if serialNos == [] and offline == []:
            msg  = "Android Debug Bridge (adb) reports that no devices are connected. One device "
            msg += "(a phone or tablet) needs to be connected via USB to your computer. If "
            msg += "there is no device connected, "
            msg += "please re-start the tool after connecting an Android "
            msg += "device. If that is not correct, try the following:\n\n"
            msg += constants.RECONNECT_INSTRUCTIONS
            dlg = wx.MessageDialog(None,
                                   msg,
                                   "No devices found",
                                   wx.OK)
            dlg.ShowModal()
            dlg.Destroy()

            # In the future, this self.device will probably become self.devices, so it's okay to set it
            # here to nothing; we're not creating a null Device.
            self.activeDeviceIndex = None
            return
        elif serialNos == [] and offline != []:
            msg  = "Android Debug Bridge (adb) reports that there are one or more devices "
            msg += "connected, but that they are 'offline'. To put your device(s) into the "
            msg += "'device' state, try the following:\n\n"
            msg += constants.RECONNECT_INSTRUCTIONS
            dlg = wx.MessageDialog(None,
                                   msg,
                                   "No devices found",
                                   wx.OK)
            dlg.ShowModal()
            dlg.Destroy()

            # In the future, this self.device will probably become self.devices, so it's okay to set it
            # here to nothing; we're not creating a null Device.
            self.activeDeviceIndex = None
            return
        else:
            emulators = [serialNo for serialNo in serialNos if serialNo.startswith('emulator')]
            missingSerialNo = [serialNo for serialNo in serialNos if serialNo == '?']
            msg = ""
            if emulators != []:
                msg += "It appears that you have an emulator running. Sadly, the tool does not yet support "
                msg += "emulators.\n\n"
            if len(serialNos) > 1:
                msg += "ADB reports that more than one Android device is connected. The tool currently "
                msg += "only supports one Android device at a time. Please disconnect all but one device "
                msg += "and re-start the tool.\n\n"
            if offline != []:
                msg += "One or more of your devices has been reported by Android Debug Bridge as 'offline'. "
                msg += "To put your device(s) into the 'device' state, try this:\n\n"
                msg += constants.RECONNECT_INSTRUCTIONS
#            if missingSerialNo:
#                msg += "One or more of your devices does not have a serial number."
            if msg != "":
                dlg = wx.MessageDialog(None,
                                       msg,
                                       "No devices found",
                                       wx.OK)
                dlg.ShowModal()
                dlg.Destroy()

            serialNos = list(set(serialNos) - set(emulators))
            if len(serialNos) > 1:
                sys.exit(1)

        # XXX activeDevice should be chosen by the active deviceguipanel'
        self.activeDeviceIndex = -1
        self.devices.append(Device())
        dprint('before  identifyProperties')
        if missingSerialNo:
            proc = subprocess.Popen((config.adbPath + " shell getprop ro.product.manufacturer").split(),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            o, e = proc.communicate()
            manufacturer = o.lstrip().rstrip()
            proc = subprocess.Popen((config.adbPath + " shell getprop ro.product.name").split(), 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            o, e = proc.communicate()
            name = o.lstrip().rstrip()
            serialNo = manufacturer + '.' + name
            # Replace chars prohibited in Windows filenames. http://support.microsoft.com/kb/177506
            for char in [' ', '\\', '/', ':', '*', '?', '"', '<', '>', '|']:
                serialNo = serialNo.replace(char, '_')
            serialNos = [serialNo]

        success = self.devices[self.activeDeviceIndex].identifyProperties(
            serialNos[self.activeDeviceIndex], self, constants.VNC_PORT, configParser,
            usingAltSerialNo=(missingSerialNo != []), noGUI=self.noGUI)

        dprint('after identifyProperties')
        return success
        
        # Session - A test, essentially, though not called a test because it 
        # could be used for setup or other things. Multiple devices can be 
        # exercised during a session, though that is not supported
        # yet. Multiple device support is only provided to support sessions in 
        # which those devices need to interact with one another. It's not 
        # intended for just running tests on a bunch of devices at the same time.

        # When the recording of a session is finished, OCRBoxProcess for
        # that session is begun.
        # When a user requests that a session be loaded, all OCRBoxProcesses
        # are stopped and the one for that session is loaded.
        # When the app is started, un-processed sessions are processed by an
        # OCRBoxProcess.
        # When the app is closed, no signal needs to be sent to OCRBoxProcesses.
        
        # Typically, there will be at most one OCRBoxProcess at a time to
        # ensure that a session that was just recorded and is likely to
        # be loaded soon gets the processing power it needs and finishes
        # as soon as possible. When a session has not just been recorded,
        # limiting the number of process could also lighten the processing
        # load for the user's other (non-TST) apps.
        # When AppFrame is stopping one and has just started another
        # OCRBoxProcess, there can be two running. If the record button
        # is pressed several times in a row, w/ a future GUI change they
        # could be given the same session name. So, it's possible that
        # several OCRBoxProcesses with the same session name could exist
        # before the signal to abort has been received by each.
        # OCRBoxProcess is stopped when a new session has just been
        # recorded. There's little benefit in checking which session is
        # being OCRBoxProcess'ed before stopping them all, b/c they can
        # all be stopped and the right one started.

        # GUI is started: all sessions are processed
        # Recording starts: all OCR processes are signalled to abort to improve
        #                   responsiveness of the GUI
        # Recording finishes: all processes will have at least been given
        #                     the signal to abort. The process for the just
        #                     recorded session can be started.

        # Here is the procedure for using the queue:
        # When AppFrame wants to start an OCRBoxProcess instance, it clears the queue.
        # When AppFrame wants the instance to stop, it puts (<session name>, ABORT_OCR_BOX_PROCESS)
        # into the queue.
        # As it runs, OCRBoxProcess gets everything from the queue. If it finds
        # (<its session name>, ABORT_OCR_BOX_PROCESS) in the queue, it stops.
        # When OCRBoxProcess finishes, it puts (<its session name>, OCR_BOX_PROCESS_EXITED)
        # in the queue.

        # App puts in ABORT requests, OCRProcess puts in OCR_BOX_PROCESS_EXITED messages.
        # OCRProcess removes ABORT requests, App removes OCR_BOX_PROCESS_EXITED messages.
        
        # Timing problems?:
        # App gets Q contents.
        # OCRProcess gets Q contents.
        # App checks for OCR_BOX_PROCESS_EXITED, finds None.
        # OCRProcess finds that it has not been asked to ABORT.
        # OCRProcess puts OCR_BOX_PROCESS_EXITED message in Q.
        # App puts ABORT request in.
        # App later sees OCR_BOX_PROCESS_EXITED & ABORT in Q, removes process ID from its own list.

        # Guarantees:
        # Only OCRProcess puts OCR_BOX_PROCESS_EXITED messages in. Only OCRProcess can mark itself
        # as finished. App removes from its private list all processes marked as
        # OCR_BOX_PROCESS_EXITED in Q and does not put OCR_BOX_PROCESS_EXITED messages back in Q.
        # 


    def loadTest(self, testFilePath):
        self.playStatus = constants.PLAY_STATUS_READY_TO_PLAY
        self.testFilePaths = [testFilePath]
        self.currentTestIndex = 0
        self.inputEvents = [[]]
        testName = os.path.basename(testFilePath).rsplit('.', 1)[0]
        self.populateInputEvents(0, 
                                 os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, 'tests', testName))


    def addTest(self, testFilePath):
        self.testFilePaths.append(testFilePath)
        # self.currentTestIndex is not changed here.
        self.inputEvents.append([])
        testName = os.path.basename(testFilePath).rsplit('.', 1)[0]
        self.populateInputEvents(len(self.testFilePaths) - 1, 
                                 os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, testName))


    def resetTests(self):
        # The tests are loaded. We want to set the manager's state so that we can
        # play again from the top.
        self.playStatus = constants.PLAY_STATUS_READY_TO_PLAY
        self.currentTestIndex = 0


    def setRecordingTestName(self, sessionName):
        self.recordingTestAtPath = sessionName


    def getRecordingTestPath(self):
        return self.recordingTestAtPath


    def getCurrentPlayingTestName(self):
        return self.testFilePaths[self.currentTestIndex]


    def getCurrentTestRepr(self):
        return "{num}. {name}".format(num=self.currentTestIndex + 1, name=self.testFilePaths[self.currentTestIndex])


    def populateInputEvents(self, testIndex, testFolderPath):
        if self.recorder.isSessionPackaged(self.testFilePaths[testIndex]):
            self.inputEvents[testIndex] = self._getInputEventsForSession(self.testFilePaths[testIndex])
        else:
            self.appFrame.displayMessageInStatusBar(
                "Processing and loading new test. This may take a while. Please wait.")
            deviceData = self.recorder.getDevicesOfSession(self.testFilePaths[testIndex])
            dd = {}
            for serialNo, width, lcdHeight, maxADBCommandLength, chinBarHeight, chinBarImageString, orientation in deviceData:
                dd[serialNo] = (width, lcdHeight + chinBarHeight, chinBarHeight, chinBarImageString, orientation)
            rawInputEvents, chinBarImageString = self.recorder.getEventsForSession(self.testFilePaths[testIndex])
            self.inputEvents[testIndex] = self.packageInputEvents(rawInputEvents, 
                                                                  dd, 
                                                                  self.testFilePaths[testIndex], 
                                                                  chinBarImageString)
            sortedEvents = []
            for serialNo in self.inputEvents[testIndex].keys():
                sortedEvents += self.inputEvents[testIndex][serialNo]
            sortedEvents.sort(key=lambda x: x.startTime)
            self.inputEvents[testIndex] = sortedEvents
            for number, inputEvent in enumerate(self.inputEvents[testIndex]):
                inputEvent.indexInDB = number
            self.saveInputEvents(testIndex, self.inputEvents[testIndex], testFolderPath)
            self.recorder.markSessionPackaged(self.testFilePaths[testIndex])
        

    def _getInputEventsForSession(self, sessionName):
        eventComponentss = self.recorder.getInputEventsForSession(sessionName)
        inputEvents = []
        for eventComponents in eventComponentss:
            inputEvents.append(utils.InputEvent(indexInDB=eventComponents['index'],
                                                serialNo=eventComponents['serialNo'],
                                                startTime=eventComponents['startTime'],
                                                inputType=eventComponents['inputType'],
                                                characters=eventComponents['characters'],
                                                targetImageWidth=eventComponents['targetImageWidth'],
                                                targetImageHeight=eventComponents['targetImageHeight'],
                                                targetImageString=eventComponents['targetImageString'],
                                                keycodes=eventComponents['keycodes'],
                                                textToVerify=eventComponents['textToVerify'],
                                                wait=eventComponents['wait'],
                                                dragStartRegion=eventComponents['dragStartRegion'],
                                                dragEndRegion=eventComponents['dragEndRegion'],
                                                dragRightUnits=eventComponents['dragRightUnits'],
                                                dragDownUnits=eventComponents['dragDownUnits']))
        return inputEvents


    def saveInputEvents(self, testIndex, inputEvents, testFolderPath):

        for index, inputEvent in enumerate(inputEvents):
            waitForImageStabilization = (inputEvent.inputType==constants.DRAG and
                                         len(inputEvents) > (index + 1) and
                                         inputEvents[index + 1].inputType in
                                         (constants.TAP, constants.LONG_PRESS, constants.TEXT_TO_VERIFY))
            self.recorder.saveInputEvent(serialNo=inputEvent.serialNo,
                                         sessionPath=self.testFilePaths[testIndex],
                                         testFolderPath=testFolderPath,
                                         index=index,
                                         numberOfEvents=len(inputEvents),
                                         startTime=inputEvent.startTime,
                                         inputType=inputEvent.inputType,
                                         characters=inputEvent.characters,
                                         targetImageWidth=inputEvent.targetImageWidth,
                                         targetImageHeight=inputEvent.targetImageHeight,
                                         targetImageString=inputEvent.targetImageString,
                                         keycodes=inputEvent.keycodes,
                                         textToVerify=inputEvent.textToVerify,
                                         wait=inputEvent.wait,
                                         dragStartRegion=inputEvent.dragStartRegion,
                                         dragEndRegion=inputEvent.dragEndRegion,
                                         dragRightUnits=inputEvent.dragRightUnits,
                                         dragDownUnits=inputEvent.dragDownUnits,
                                         waitForImageStabilization=waitForImageStabilization)


    def getFakeButtonList(self, ignored):
        imageString = '\xFF\x00\x00' * 30 * 30
        image = Image.frombuffer("RGB",
                                 (30, 30),
                                 imageString,
                                 'raw',
                                 "RGB",
                                 0,
                                 1)
        memoryPNG = StringIO.StringIO()
        image.save(memoryPNG, format='PNG')
        image = memoryPNG.getvalue()
        memoryPNG.close()
        pyimage = PyEmbeddedImage(image, isBase64=False)
        image = pyimage.GetBitmap()

        label = ' ' + 'tap' #+ ' ' * 200
        label += ' ' * 200
        return [(image, label, platebtn.PB_STYLE_SQUARE, wx.WINDOW_VARIANT_LARGE, None, None, True, imageString)]


    def getNewEventsButtonComponents(self, testIndex):
        buttonList = []
        for number, inputEvent in enumerate(self.inputEvents[testIndex]):
            globals_.traceLogger.debug("getNewEventsButtonComponents(): inputEvent number: " + str(number) + 
                                       ", type: " + str(inputEvent.inputType))

            if inputEvent.targetImageString:
                # Every line in this 'if block' executes quickly. I printed time.time()
                # at each line and did not see a change in the value reported over the
                # entire course of the 'if' block.
                globals_.traceLogger.debug("getNewEventsButtonComponents(), targetImageWidth: " + 
                                           str(inputEvent.targetImageWidth))
                globals_.traceLogger.debug("getNewEventsButtonComponents(), targetImageHeight: " + 
                                           str(inputEvent.targetImageHeight))
                globals_.traceLogger.debug("getNewEventsButtonComponents(), targetImageHeight: " + 
                                           str(len(inputEvent.targetImageString)))
                try:
                    image = Image.frombuffer("RGB",
                                             (inputEvent.targetImageWidth, inputEvent.targetImageHeight),
                                             inputEvent.targetImageString,
                                             'raw',
                                             "RGB",
                                             0,
                                             1)
                except Exception, e:
                    bdbg()
                    dprint("ERROR !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                    globals_.traceLogger.debug("getNewEventsButtonComponents(), Exception: " + str(e))
                # XXX this assumes the image is originally square
                image = image.resize((30, 30))
                imageString = image.tostring()
            else:
                imageString = '\xFF\xFF\xFF' * 30 * 30
                image = Image.frombuffer("RGB",
                                         (30, 30),
                                         imageString,
                                         'raw',
                                         "RGB",
                                         0,
                                         1)
            memoryPNG = StringIO.StringIO()
            image.save(memoryPNG, format='PNG')
            image = memoryPNG.getvalue()
            memoryPNG.close()
            image = PyEmbeddedImage(image, isBase64=False).GetBitmap()

            label = ' ' + constants.INPUT_EVENT_TYPE_LABELS[inputEvent.inputType] #+ ' ' * 200
            if inputEvent.characters:
                label += '. Chars to find: ' + inputEvent.characters
            elif inputEvent.keycodes:
                try:
                    label += ': ' + plateButton.getPrintableKeycodeText(inputEvent.keycodes)
                except:
                    pass
            elif inputEvent.inputType == constants.TEXT_TO_VERIFY:
                label += ': ' + inputEvent.textToVerify
            elif inputEvent.inputType == constants.WAIT:
                label += ' ' + str(inputEvent.wait) + ' seconds.'
            if len(label) > 40:
                label = label[:40] + '...'
            label += ' ' * 200
            dprint('getNewEventsButtonComponents, number:', number, 'inputEvent.indexInDB:', inputEvent.indexInDB)
            buttonList.append({'index':inputEvent.indexInDB,
                               'inputType':inputEvent.inputType,
                               'characters':inputEvent.characters,
                               'keycodes':inputEvent.keycodes,
                               'textToVerify':inputEvent.textToVerify,
                               'wait':inputEvent.wait,
                               'dragStartRegion':inputEvent.dragStartRegion,
                               'dragRightUnits':inputEvent.dragRightUnits,
                               'dragDownUnits':inputEvent.dragDownUnits,
                               'dragEndRegion':inputEvent.dragEndRegion,
                               'PyEmbeddedImage':image,
                               'label':label,
                               'buttonStyle':platebtn.PB_STYLE_SQUARE,
                               'textSize':wx.WINDOW_VARIANT_LARGE,
                               'menu':None,
                               'pressColor':None,
                               'isEnabled':True,
                               'imageString':imageString})

        return buttonList


    def setPlayStatus(self, status):
        self.playStatus = status


    def playNextTest(self):
        # This is called even at the very start, before a test is being played.
        self.currentTestIndex += 1
        self.devices[self.activeDeviceIndex].startingPlayback(self.testFilePaths[self.currentTestIndex], 
                                                              self.currentTestIndex)
        self.startReplay()


    def finishingPlayback(self):
        self.devices[self.activeDeviceIndex].finishingPlayback()


    def startSuitePlayRecording(self):
        self.playStatus = constants.PLAY_STATUS_PLAYING
        device = self.devices[self.activeDeviceIndex]
        currentImageFilename = device.imageFilename
        if currentImageFilename.startswith('explore'):
            # device.imageFilename could be updated right at this instant,
            # meaning that, if a click occurs before that newer image is
            # replaced by an even newer one, the click would be assigned to 
            # an old image. Because that would have to come within
            # a very small window while this method executes, the tester
            # would probably be guessing anyway about when to click and
            # the risk is tiny.
            timeFromName = currentImageFilename[-17:-4]
            newImageFilename = ('play.' + str(self.currentTestIndex) + '.' +
                                self.testFilePaths[self.currentTestIndex] + '.' +
                                self.devices[self.activeDeviceIndex].serialNo
                                + '.' + timeFromName + '.png')
            device.setImageFilename(newImageFilename)
            try:
                shutil.copy(currentImageFilename,
                            newImageFilename)
            except:
                # device.imageFilename may have been updated by ScreenshotProcess between the time
                # we assigned to it here and the time the copy() was attempted, which
                # would mean that we attempted to copy a non-existent file.
                # There could also, of course, be no more space left.
                pass
        self.recorder.addDeviceIfNecessary(device.serialNo, device.width,
                                           device.height - device.chinBarHeight,
                                           device.dt.maxADBCommandLength)
        deviceData = {}
        deviceData[device.serialNo] = (device.width,
                                       device.height - device.chinBarHeight,
                                       device.chinBarHeight, device.chinBarImageString,
                                       device.orientation, device.getMaxADBCommandLength(),
                                       device.dt.downText, device.dt.upText)
        self.playName = self.recorder.startSuitePlayRecording(deviceData)


    def startReplay(self):
        deviceData = {}
        # XXX If the device is the same as one in the DB, use the maxADBCommandLength reported
        # for that device there.
        device = self.devices[self.activeDeviceIndex]
        deviceData[device.serialNo] = {'width':device.width, 'lcdHeight':device.height, 
                                       'chinBarHeight':device.chinBarHeight, 
                                       'chinBarImageString':device.chinBarImageString,
                                       'orientation':device.orientation, 
                                       'maxADBCommandLength':constants.DEFAULT_MAX_ADB_COMMAND_LENGTH,
                                       'downText':device.dt.downText, 'upText':device.dt.upText,
                                       'downRepeaterText':device.dt.downRepeaterText,
                                       'repeaterPostfixText':device.dt.repeaterPostfixText,
                                       'screenshotMethod':device.screenshotMethod,
                                       'usingAltSerialNo':device.usingAltSerialNo,
                                       'downUpText':device.dt.downUpText}

        while time.time() > 10 + self.devices[self.activeDeviceIndex].cameraProcess.imageLastAcquiredTime:
            # The image was acquired more than 10 seconds ago.
            traceLogger.debug("Waiting for screenshot to be acquired.")
            time.sleep(0.5)
        activeDevice = self.devices[self.activeDeviceIndex]
        activeDevice.startingPlayback(self.testFilePaths[self.currentTestIndex], self.currentTestIndex)
        self.recorder.startTestPlayRecording(self.playName, self.testFilePaths[self.currentTestIndex])
        if not os.path.exists('plays'):
            try:
                os.mkdir('plays')
            except:
                return
        if os.path.exists(os.path.join('plays', self.playName)):
            shutil.rmtree(os.path.join('plays', self.playName))
        os.mkdir(os.path.join('plays', self.playName))

        dprint('starting replayprocess')
        self.replayThread = replayProcess.ReplayProcess(self.recorder, self.playName, 
                                                        self.testFilePaths[self.currentTestIndex], 
                                                        self.currentTestIndex,
                                                        self.inputEvents[self.currentTestIndex],
                                                        deviceData, xScale=activeDevice.xScale, 
                                                        yScale=activeDevice.yScale, xIntercept=activeDevice.xIntercept, 
                                                        yIntercept=activeDevice.yIntercept,
                                                        replayControlQueue=self.replayControlQueue,
                                                        eventsBoxQueue=self.appFrame.eventsBoxQueue,
                                                        adbPath=config.adbPath,
                                                        noGUI=self.noGUI,
                                                        latestImageFilename=device.imageFilename)

        # XXX support noGUI in the future.
        if self.noGUI:
            while not self.replayThread.isDone:
                time.sleep(1)
            activeDevice.cameraProcess.stopRequested = True
            self.reportResults()
    

    def reportResults(self):
        if self.inputEvents[self.currentTestIndex][-1].status == constants.EVENT_PASSED:
            dprint("ok")
        else:
            for number, inputEvent in enumerate(reversed(self.inputEvents[self.currentTestIndex])):
                if inputEvent.status == constants.EVENT_FAILED:
                    num = len(self.inputEvents[self.currentTestIndex]) - number
                    dprint("Test {name} FAILED at event #{num}".format(name=self.testFilePaths[self.currentTestIndex],
                                                                       num=num))
                    break


    def pauseReplay(self):
        self.playStatus = constants.PLAY_STATUS_PAUSED
        self.replayControlQueue.put('pause')
        for device in self.devices:
            device.startingPause()


    def resumeReplay(self):
        self.playStatus = constants.PLAY_STATUS_PLAYING
        self.replayControlQueue.put('resume')

        currentImageFilename = self.devices[self.activeDeviceIndex].imageFilename
        # if currentImageFilename.startswith('pause'):
        #     # device.imageFilename could be updated right at this instant,
        #     # meaning that, if a click occurs before that newer image is
        #     # replaced by an even newer one, the click would be assigned to
        #     # an old image. Because that would have to come within
        #     # a very small window while this method executes, the tester
        #     # would probably be guessing anyway about when to click and
        #     # the risk is tiny.
        #     newImageFilename = 'play' + currentImageFilename[5:]
        #     device.imageFilename = newImageFilename
        #     try:
        #         shutil.copy(currentImageFilename,
        #                     newImageFilename)
        #     except:
        #         # device.imageFilename may have been updated by ScreenshotProcess between the time
        #         # we assigned to it here and the time the copy() was attempted, which
        #         # would mean that we attempted to copy a non-existent file.
        #         # There could also, of course, be no more space left.
        #         pass

        for device in self.devices:
            device.startingPlayback(self.testFilePaths[self.currentTestIndex], 
                                    self.currentTestIndex)


    def stopReplay(self):
        self.playStatus = constants.PLAY_STATUS_STOPPED
        if self.playName:
            self.replayControlQueue.put('stop')
            for device in self.devices:
                device.startingExplore()
            self.recorder.storeImages(self.playName, 'play')
            self.recorder.finishTestOrPlayStorage(self.playName, 'record')
            self.playName = None


    def startSession(self, testName):
        if self.activeDeviceIndex:

            activeDevice = self.devices[self.activeDeviceIndex]
            
            orientation, success = activeDevice.getScreenOrientation()
            deviceData = [(activeDevice.serialNo, activeDevice.width,
                           activeDevice.height - activeDevice.chinBarHeight,
                           activeDevice.chinBarHeight, activeDevice.chinBarImageString,
                           activeDevice.orientation)]
            self.sessionID = self.recorder.startSession(deviceData, self.recordingTestAtPath)
            activeDevice.startingRecord(testName)

            self.playStatus = constants.PLAY_STATUS_RECORDING

            device = self.devices[self.activeDeviceIndex]
            currentImageFilename = device.imageFilename

            expectedPrefix = self.getExpectedPrefix(currentImageFilename)
            dprint('startSession, currentImageFilename:', currentImageFilename)
            device.setImageFilename(self.getNewImageFilename(expectedPrefix, 
                                                             currentImageFilename, 
                                                             activeDevice.serialNo))

            try:
                shutil.copy(currentImageFilename, device.imageFilename)
            except:
                dprint("startSession failed to copy currentimagefilename")
            # if currentImageFilename.startswith('explore'):
            #     # device.imageFilename could be updated right at this instant,
            #     # meaning that, if a click occurs before that newer image is
            #     # replaced by an even newer one, the click would be assigned to
            #     # an old image. Because that would have to come within
            #     # a very small window while this method executes, the tester
            #     # would probably be guessing anyway about when to click and
            #     # the risk is tiny.
            #     newImageFilename = 'record' + currentImageFilename[7:]
            #     device.imageFilename = newImageFilename
            #     dprint("startSession, made device.imageFilename:", device.imageFilename)
            #     try:
            #         shutil.copy(currentImageFilename,
            #                     newImageFilename)
            #     except:
            #         # device.imageFilename may have been updated by ScreenshotProcess between the time
            #         # we assigned to it here and the time the copy() was attempted, which
            #         # would mean that we attempted to copy a non-existent file.
            #         # There could also, of course, be no more space left.
            #         pass

            # This member is the signal used by others that recording is happening,
            # so we perform the other tasks in this method first.
            self.isRecording = True


    def getExpectedPrefix(self, imageFilename):
        prefixMap = {constants.PLAY_STATUS_NO_SESSION_LOADED:'explore',
                     constants.PLAY_STATUS_READY_TO_PLAY:'explore',
                     constants.PLAY_STATUS_PLAYING:'play',
                     constants.PLAY_STATUS_PAUSED:'pause',
                     constants.PLAY_STATUS_FINISHED:'explore',
                     constants.PLAY_STATUS_STOPPED:'explore',
                     constants.PLAY_STATUS_RECORDING:'record'}
        return prefixMap[self.playStatus]


    def getNewImageFilename(self, expectedPrefix, imageFilename, serialNo):
        dprint("looking for concatenation of multiple recorded filenames in imageFilename")
        dprint("expectedPrefix:", expectedPrefix)
        dprint("self.getRecordingTestPath():", self.getRecordingTestPath())
        dprint("imageFilename[imageFilename.index('.'):]:", imageFilename[imageFilename.index('.'):])
        if expectedPrefix == 'record':
            testName = os.path.basename(self.getRecordingTestPath()).rsplit('.', 1)[0]
            newImageFilename = expectedPrefix + '.' + testName + imageFilename[imageFilename.index('.'):]
            dprint("1 newImageFilename:", newImageFilename)
        elif expectedPrefix == 'play':
            testName = os.path.basename(self.testFilePaths[self.currentTestIndex]).rsplit('.', 1)[0]
            if imageFilename.startswith('pause'):
                newImageFilename = expectedPrefix + imageFilename[5:]
            else:
                newImageFilename = (expectedPrefix + '.' + str(self.currentTestIndex) + '.' + testName + 
                                    imageFilename[imageFilename.index('.'):])
            dprint("2 newImageFilename:", newImageFilename)
        elif expectedPrefix == 'explore':
            if imageFilename.startswith("play"):
                # The replay process is constantly getting the string from 
                # the latest image file (on disk). The ScreenshotProcess may 
                # write the image to a file named 'play...', and, by the time 
                # the device object receives it and copies that file to one 
                # named 'explore...', the replay process may have acted on it. 
                # (The manager's playStatus will turn from 'play' to 'explore'
                # when the replay process has notified the manager of 
                # completion; AFAIK it's possible that the replay process 
                # could act on a file named 'play...' and then notify the 
                # manager of completion and THEN the postevent from the 
                # ScreenshotProcess could arrive, so that renaming the file
                # from 'play...' to 'explore...' would not always be correct.
                # Also, the expectedPrefix for a STOPPED test is also 
                # 'explore' (see getExpectedPrefix()), and, in that case,
                # the manager receives the stop signal and then tells the
                # replay process; the replay process may not act on that
                # signal until after he's acted on the new file's contents.
                newImageFilename = imageFilename
                dprint("image filename is expected to start with explore, but starts with 'play'")
            else:
                numberPeriodsFound = 0
                indexInName = len(imageFilename) - 1
                while numberPeriodsFound < 3 and indexInName > 0:
                    if imageFilename[indexInName] == '.':
                        numberPeriodsFound += 1
                    indexInName -= 1
                suffix = imageFilename[indexInName + 1:]
                newImageFilename = expectedPrefix + '.' + serialNo + suffix
                dprint("3 newImageFilename:", newImageFilename)
        elif expectedPrefix == 'pause':
            # The replay process is constantly getting the string from 
            # the latest image file (on disk). The ScreenshotProcess may 
            # write the image to a file named 'play...', and, by the time 
            # the device object receives it and copies that file to one 
            # named 'pause...', the replay process may have acted on it. 
            # So, it would be incorrect to rename the file in the case of 
            # a paused player.
            newImageFilename = imageFilename #'pause' + imageFilename[imageFilename.find('.'):]
        else:
            dprint("unexpected condition")
            bdbg()
        return newImageFilename


    def stopRecording(self):
        self.playStatus = constants.PLAY_STATUS_STOPPED
        for device in self.devices:
            #device.setTestName(None)
            device.startingExplore()
        self.recorder.finishTestOrPlayStorage(self.getRecordingTestPath(), 'record')
        self.recorder.flushClicks()
        self.isRecording = False
        self.setRecordingTestName(None)


    def addTextToVerify(self, text):
        self.recorder.addTextToVerify(self.sessionID, self.devices[self.activeDeviceIndex].serialNo, text)


    def addWait(self, seconds):
        self.recorder.addWait(self.sessionID, self.devices[self.activeDeviceIndex].serialNo, seconds)


    def killAllOCRBoxProcesses(self):
        # Kill all running sessions.
        messages = []
        while True:
            try:
                messages.append(self.ocrBoxProcessQueue.get_nowait())
            except Exception, e:
                break

        # Send a message to kill each process, but don't add duplicate messages.
        toRemove, toPutBack = [], []
        for (ocrBoxProcessID, status) in messages:
            if status == constants.OCR_BOX_PROCESS_EXITED:
                toRemove.append((ocrBoxProcessID, status))
            elif status == constants.ABORT_OCR_BOX_PROCESS:
                # Only the OCRBoxProcess itself removes the abort requests
                # sent to it in the queue.
                toPutBack.append((ocrBoxProcessID, status))
        for processID, status in toRemove:
            while True:
                try:
                    self.ocrBoxProcessIDs.remove((processID, status))
                except Exception, e:
                    break
        messages = [(processID, constants.ABORT_OCR_BOX_PROCESS) for processID in self.ocrBoxProcessIDs]
        for message in messages:
            globals_.traceLogger.debug("killAllOCRBoxProcesses(), putting this message onto queue:" + str(message))
            self.ocrBoxProcessQueue.put(message)
        #self.Bind(wx.EVT_TIMER, self.OnOCRBoxProcessTimer, self.ocrBoxProcessTimer)
        #self.ocrBoxProcessTimer.Start()
            

    def startOCRBoxProcess(self, sessionName=constants.OCR_BOX_PROCESS_SESSION_NAME_ALL):
        process = ocrBoxProcess.OCRBoxProcess(globals_.getUserDocumentsPath(), self.ocrBoxProcessQueue, 
                                              sessionName)
        self.ocrBoxProcessIDs.append(id(process))

        dprint('added id f/ ocrBoxProcess:', self.ocrBoxProcessIDs[-1])

        return process


    def packageInputEvents(self, clicks, deviceData, testFilePath, chinBarImageString):
        return utils.packageInputEvents(self, clicks, deviceData, testFilePath, chinBarImageString)


class AppFrame(wx.Frame):
    # An IndividualTestManager contains a DeviceWindow for each device being tested
    # and a XXX and manages
    # their layout with a wx.BoxSizer.  A menu and associated event handlers
    # provides for saving a doodle to a file, etc.
    title = "Dollop"
    def __init__(self, parent, app):
        utils.AppFrame__init__(self, parent, app)

    def OnLeftMouseDown(self, event):
        dprint('appframe onleftmousedown')

    def OnLeftMouseUp(self, event):
        dprint('appframe onleftmouseup')

    def OnMouseMove(self, event):
        dprint('appframe onmousemove')

    def OnLeftDClick(self, event):
        dprint('appframe onleftmousedclick')


    def buildAudioBar(self, parent):
        # Builds the audio bar controls

        audioBarPanel = wx.Panel(parent, -1)
        audioBarSizer = wx.BoxSizer(wx.HORIZONTAL)

        # An image toggle button
        self.playPauseBtn = wx.lib.buttons.GenBitmapToggleButton(audioBarPanel, -1, None, size=(50,30))
        self.Bind(wx.EVT_BUTTON, self.OnPlayOrPause, self.playPauseBtn)
        playR35G35B90 = PyEmbeddedImage(
            "iVBORw0KGgoAAAANSUhEUgAAABAAAAASCAYAAABSO15qAAAAAXNSR0IArs4c6QAAAAZiS0dE"
            "AP8A/wD/oL2nkwAAAAlwSFlzAAALEwAACxMBAJqcGAAAAAd0SU1FB9sDAhcPKPLA9dcAAAAZ"
            "dEVYdENvbW1lbnQAQ3JlYXRlZCB3aXRoIEdJTVBXgQ4XAAABRklEQVQ4y52UOy9EYRiEn/mc"
            "JRLR6fyXQ+Iv+AcaIfEPaDRaiUIUElRCNCIhcdtCRBQql7g1LsVWRIjLOaPYXdZm2XNM9zYz"
            "77zfzCeI10EbkMzZxRKAJNk2GSCIr0AF4B7SZXt3Ig+JoOeiZo7ALxCG4bFoH743Iwh18wfQ"
            "CuksdCxIvX1fSpKybFAHB2Afngbtw4d/EAC4ACTADGje3r75y0IjjXfAwAB4TYpHam1l2ODH"
            "NgLagXNgHLQtiC9BJh8CkIJPQtmflZMgBVqA7lDxlwMO4E7QCqg/yuEdUApcw9uQvXdaSV6m"
            "xLeBj0FT0LVqLybVqEfNlRXKF9+Ztr/tVnsS/R4ePYOWIJkst1RqdK66IEngVgi78BZDz5hd"
            "LJXz0riZgvgMKFSe5QjCpL21mbXSESgB7sCjcHtgn79Wm5flP/gEbNKN57EYto8AAAAASUVO"
            "RK5CYII=")
        bmp = playR35G35B90.GetBitmap()
        mask = wx.Mask(bmp, wx.BLUE)
        bmp.SetMask(mask)
        self.playPauseBtn.SetBitmapLabel(bmp)
        pauseR35G35B90ScaledBy2 = PyEmbeddedImage(
            "iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAAAAXNSR0IArs4c6QAAAAlwSFlz"
            "AAALEwAACxMBAJqcGAAAAAd0SU1FB9sDAhcnIKFG008AAAAZdEVYdENvbW1lbnQAQ3JlYXRl"
            "ZCB3aXRoIEdJTVBXgQ4XAAAAhElEQVQ4y+2Uuw3CQBQEZ+2zjWURuAGogRREIzSHRCsQ0Aol"
            "WHzWwVlwDogIuYnealcTPtkGQNq2EE5QbsACangc7MtZ2q2hOoJWsfMThr19vTFR8KZpoFzG"
            "WwZVUPcxtx2w+GyLHrpAQiIKBswMTfluUFoYBn8R/UYWZVEW/Y/oNfsrIynNHY339NBmAAAA"
            "AElFTkSuQmCC")
        bmp = pauseR35G35B90ScaledBy2.GetBitmap()
        mask = wx.Mask(bmp, wx.BLUE)
        bmp.SetMask(mask)
        self.playPauseBtn.SetBitmapSelected(bmp)
        self.playPauseBtn.SetUseFocusIndicator(False)
        self.playPauseBtn.SetToggle(False)
        self.playPauseBtn.Disable()
        audioBarSizer.Add(self.playPauseBtn, 0, wx.ALL, 3)

        stopR35G35B90 = PyEmbeddedImage(
            "iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAAAAXNSR0IArs4c6QAAAAZiS0dE"
            "AP8A/wD/oL2nkwAAAAlwSFlzAAALEwAACxMBAJqcGAAAAAd0SU1FB9sDAhcwBJjGswgAAAAZ"
            "dEVYdENvbW1lbnQAQ3JlYXRlZCB3aXRoIEdJTVBXgQ4XAAAAY0lEQVQ4y+3OsQ2AMAxE0X8x"
            "YiUqlmEJhkRiAkYBjiIpaEOoEL+07CcLhgn6GVKAqO8M2BfBuEEAGKw6zC77XcqIDaj+Iynf"
            "caTboKnES/3QD30a8huQA9Qg2QU6VqB7DklgXz2YFPnWeaWGAAAAAElFTkSuQmCC")
        bmp = stopR35G35B90.GetBitmap()
        self.stopBtn = wx.lib.buttons.GenBitmapButton(audioBarPanel, bitmap=bmp, name='stop button', size=(50,30))
        self.Bind(wx.EVT_BUTTON, self.OnStopReplay, self.stopBtn)
        self.stopBtn.SetUseFocusIndicator(False)
        self.stopBtn.Disable()
        audioBarSizer.Add(self.stopBtn, 0, wx.ALL, 3)
        
        # An image toggle button
        self.recordBtn = wx.lib.buttons.GenBitmapToggleButton(audioBarPanel, -1, None, size=(50,30))
        self.Bind(wx.EVT_BUTTON, self.OnRecordSession, self.recordBtn)
        recordNotActivated = PyEmbeddedImage(
            "iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAAAAXNSR0IArs4c6QAAAAZiS0dE"
            "AP8A/wD/oL2nkwAAAAlwSFlzAAALEwAACxMBAJqcGAAAAAd0SU1FB9sDAhYfOkp5/PkAAAAZ"
            "dEVYdENvbW1lbnQAQ3JlYXRlZCB3aXRoIEdJTVBXgQ4XAAAAyklEQVQ4y62ULQ6DMBhAXz83"
            "MzscjitwgF0AM98jTHMAdI8wj+EaXGGujtplCXbm60IYWYDyZJO+fP+GBR55fgEq4AZcgTfQ"
            "Ay3QWe/D/I+ZCU5AA9z5jwNq6/34I9IonsCZdbyAIkZnJpEMGyRTWWa9H0Ufmh0S9E8DYDSl"
            "gTQy0e6kUom2OJWbAOUBolI4CNGJTaUXHftUWgG6A0Sd6Ii7BImz3odY7FrHnR0rUsdio1tc"
            "bJTFpR2/IpUFIFuZptNlDYv3KOWwfQCLL0USLA19BQAAAABJRU5ErkJggg==")
        bmp = recordNotActivated.GetBitmap()
        mask = wx.Mask(bmp, wx.BLUE)
        bmp.SetMask(mask)
        self.recordBtn.SetBitmapLabel(bmp)
        recordActivated = PyEmbeddedImage(
            "iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAAAAXNSR0IArs4c6QAAAAZiS0dE"
            "AP8A/wD/oL2nkwAAAAlwSFlzAAALEwAACxMBAJqcGAAAAAd0SU1FB9sDAhYdAL5DR8kAAAAZ"
            "dEVYdENvbW1lbnQAQ3JlYXRlZCB3aXRoIEdJTVBXgQ4XAAAA40lEQVQ4y62UMYrCUBRFz/sS"
            "GBDLQMqsIBsI9mmyDDfhAmYTWUYaNzBtCmuLwUYhpQgB+dwpJhFxQMz8f/p3uI/3/zVJPHM2"
            "Sz1UglqwBq4GnUG7gF0m9c8z9ij6NvtYwBbY8JrGw2cuDX9EZ7P0Bl/Aive4JFBO6UzSlGQ/"
            "Q3KXeShyaXAA4zpzJQCrcRY7QXr7TfNvEiich4pAPFROUIeKBLUd4QAsA11XRyScQRcqMeic"
            "QRtB1MY7//jEmwBPk0l93C+SS0MCJXCZI0mgnBrgfv5M6j0Ub67ZeCgee8liFdsPYMlvVG4c"
            "254AAAAASUVORK5CYII=")
        bmp = recordActivated.GetBitmap()
        mask = wx.Mask(bmp, wx.BLUE)
        bmp.SetMask(mask)
        self.recordBtn.SetBitmapSelected(bmp)
        self.recordBtn.SetToggle(False)
        audioBarSizer.Add(self.recordBtn, 0, wx.ALL, 3)

        audioBarPanel.SetSizer(audioBarSizer)
        return audioBarPanel


    def OnPlayOrPause(self, event):
        if self.mgr.playStatus == constants.PLAY_STATUS_PLAYING:
            # Player is playing; user wants to pause.
            self.mgr.pauseReplay()
            testRepr = self.mgr.getCurrentTestRepr()
            self.SetTitle("Paused " + testRepr + " - " + constants.APPLICATION_NAME_REGULAR_CASE)
        elif self.mgr.playStatus == constants.PLAY_STATUS_PAUSED:
            # Player is paused; user wants to resume.
            self.stopBtn.Enable()
            self.mgr.resumeReplay()
        elif self.mgr.playStatus in (constants.PLAY_STATUS_READY_TO_PLAY, constants.PLAY_STATUS_FINISHED, 
                                     constants.PLAY_STATUS_STOPPED):
            self.recordBtn.Disable()
            if self.mgr.playStatus in (constants.PLAY_STATUS_FINISHED, constants.PLAY_STATUS_STOPPED):
                # Refresh the events so that their icons don't have checks and Xes on them.
                #TODO if len(self.buttonList) == 0:
                #    self.playPauseBtn.Disable()
                # The line of the StaticBox for the Play & Record will be
                # partially missing until self.Layout() is called.
                self.resetTests(self.mgr.testFilePaths)
                self.mgr.resetTests()

            # One or two 'play'-prefixed files will be pulled after each test playback has ended.
            # If these files aren't removed at some point, they will be copied into the 'plays'
            # folder for the most recently-executed test when that test has a prefix that
            # matches, so delete them now.
            for thing in os.listdir('.'):
                if thing.startswith('play') and thing.endswith('.png'):
                    try:
                        os.remove(thing)
                    except:
                        pass

            # Start playing again from the top.
            self.mgr.startSuitePlayRecording()

            time.sleep(0.05)
            self.updateGUIToState(self.mgr.playStatus)
            testRepr = self.mgr.getCurrentTestRepr()
            self.mgr.startReplay()
            self.SetTitle("Playing " + testRepr + " - " + constants.APPLICATION_NAME_REGULAR_CASE)            
        else:
            # Player is stopped, but no session has been loaded.
            self.playPauseBtn.SetToggle(False)


    def OnStopReplay(self, _):
        if self.mgr.playStatus in (constants.PLAY_STATUS_PLAYING, constants.PLAY_STATUS_PAUSED):
            # A status msg saying "stopping process..." or sth could be posted to status bar as in LongRunningTasks
            # wxpython page.
            self.updateGUIToState(constants.PLAY_STATUS_STOPPED)
            testRepr = self.mgr.getCurrentTestRepr()
            self.mgr.stopReplay()
            self.SetTitle("Stopped playing " + testRepr + " - " + constants.APPLICATION_NAME_REGULAR_CASE)


    def updateGUIToState(self, state):
        if state in (constants.PLAY_STATUS_READY_TO_PLAY, constants.PLAY_STATUS_STOPPED, 
                     constants.PLAY_STATUS_FINISHED):
            for control in [self.recordingToolsBox, self.waitTextBox, self.enterWaitBtn, self.verifyTextLabel,
                            self.verifyTextBox, self.enterTextBtn, self.stopBtn]:
                control.Disable()            
            for control in [self.playPauseBtn, self.recordBtn]:
                control.Enable()
            self.playPauseBtn.SetToggle(False)
        elif state in (constants.PLAY_STATUS_PLAYING):
            for control in [self.recordingToolsBox, self.waitTextBox, self.enterWaitBtn, self.verifyTextLabel,
                            self.verifyTextBox, self.enterTextBtn, self.stopBtn]:
                control.Disable()            
            for control in [self.playPauseBtn, self.stopBtn]:
                control.Enable()
            for control in [self.recordBtn]:
                control.Disable()
            self.playPauseBtn.SetToggle(True)

               
    onTextEntryTestTimer = utils.onTextEntryTestTimer


    def makeKeycodeControls(self):
        keycodeSizer = wx.BoxSizer(wx.VERTICAL)
        enterKeycodeText = wx.StaticText(self.playAndRecordPanel, label="Keycode:")
        keycodeSizer.Add(enterKeycodeText, 0, flag=wx.ALIGN_CENTER)
        # XXX support multiple keycode maps.
        if len(config.keycodes.keys()) == 0:
            config.keycodes['Default'] = copy.deepcopy(config.DEFAULT_KEYCODES)
            mapName = 'Default'
        else:
            mapName = config.keycodes.keys()[0]
        keycodes = sorted(config.keycodes[mapName].keys())
        self.keycodeHSizer = wx.BoxSizer(wx.HORIZONTAL)
        if keycodes == []:
            default = ""
        else:
            default = keycodes[0]
        self.keycodeMenu = wx.ComboBox(self.playAndRecordPanel, 500, default,
                                       choices=keycodes,
                                       style=wx.CB_DROPDOWN | wx.CB_READONLY)
        keycodeButton = wx.Button(self.playAndRecordPanel, -1, "Send", style=wx.BU_EXACTFIT)
        self.Bind(wx.EVT_BUTTON, self.onKeycodeEntry, keycodeButton)
        self.keycodeHSizer.Add(self.keycodeMenu)
        self.keycodeHSizer.Add(keycodeButton, border=5, flag=wx.LEFT)
        keycodeSizer.Add(self.keycodeHSizer, 0, border=5, flag=wx.LEFT | wx.ALIGN_CENTER)
        return keycodeSizer

    def refreshKeycodeMenu(self):
        self.keycodeHSizer.Clear(True)
        keycodes = sorted(config.keycodes['Default'].keys())
        if keycodes == []:
            default = ""
        else:
            default = keycodes[0]
        self.keycodeMenu = wx.ComboBox(self.playAndRecordPanel, 500, default,
                                       choices=keycodes,
                                       style=wx.CB_DROPDOWN | wx.CB_READONLY)
        keycodeButton = wx.Button(self.playAndRecordPanel, -1, "Send", style=wx.BU_EXACTFIT)
        self.Bind(wx.EVT_BUTTON, self.onKeycodeEntry, keycodeButton)
        self.keycodeHSizer.Add(self.keycodeMenu)
        self.keycodeHSizer.Add(keycodeButton, border=5, flag=wx.LEFT)
        self.Layout()
        

    def onKeycodeEntry(self, event):
        # The model for this method (whether it should go through the
        # IndividualTestManager or directly communicate with the device,
        # should follow that of DeviceWindow.onCharEvent().
        value = self.keycodeMenu.GetValue()
        # OnCharEvent also uses addKeycodeToSend(), so we needn't worry
        # about coordinating keycode entry with text entry.
        self.mgr.devices[self.mgr.activeDeviceIndex].addKeycodeToSend(value)
        window = self.devicePanels[self.mgr.activeDeviceIndex].deviceWindow
        if not window.charTimerSet:
            window.charTimer.Start(50, oneShot=True)
            window.charTimerSet = True
        event.Skip()


    def onLoadSession(self, event):
        for thing in os.listdir('.'):
            # Just as an explore...png file can arrive at the device
            # object after playback has started, a play...png file
            # can arrive after it has finished. These files should
            # not need to be in the 'plays' directory. They are
            # created after other 'plays...png' files have been 
            # moved to the 'plays' directory, and can be deleted
            # upon startup here.
            if ((thing.startswith('explore') or thing.startswith('play')) 
                and thing.endswith('.png')):
                try:
                    os.remove(thing)
                except:
                    pass

        # The default directory of the FileDialog causes the process' current
        # working directory to change. The default directory needs to be set
        # to the 'plays' directory to avoid making the user figure out where
        # the saved playback screenshots are, but the current working
        # directory should be kept as is b/c that's where the screenshots are
        # saved and it makes the programming easier.
        dlg = wx.FileDialog(self, 
                            "Choose a Test File",
                            os.getcwd(),
                            wildcard="*.py",
                            style=wx.FD_OPEN)
        dlg.SetPath = os.getcwd() #os.path.join(wx.StandardPaths_Get().GetDocumentsDir(),
                                  # constants.APP_DIR,
                                  # "plays")
        dlg.CenterOnScreen()
        dlg.ShowModal()
        dlg.Destroy()
        sessionPath = dlg.GetPath()
        if not sessionPath:
            return

        self.mgr.loadTest(sessionPath)

        self.updateGUIToState(self.mgr.playStatus)

#        self.addTestMenuItem.Enable(True)
        self.Layout()

        self.SetTitle("Loaded " + sessionPath + " - " + constants.APPLICATION_NAME_REGULAR_CASE)
#        self.testViewer.Show()
#        self.testViewer.Raise()


    def onAddTest(self, event):
        # Add a test to the current suite (which may not be reified in the DB).
        # Should not be callable if no suite or other test has been loaded.
        existingTestNames = self.mgr.recorder.getSessionNames()

        # Prevent mouse clicks on the test name from being sent down to the device window.
        for devicePanel in self.devicePanels:
            devicePanel.hideFromMouseClicks()
        sessionName, cancelled = LoadTestDialog.showDialog(self, self.mgr, existingTestNames,
                                                           addToExisting=True)
        for devicePanel in self.devicePanels:
            devicePanel.unhideFromMouseClicks()

        if cancelled:
            return

        self.mgr.addTest(sessionName)
#        self.testViewer.addTest(sessionName)
#        self.testViewer.Raise()
        self.SetTitle("Added " + sessionName + " - " + constants.APPLICATION_NAME_REGULAR_CASE)


    def startScreenshotProcess(self, monkeyrunnerPath):
        # This method determines what screenshot method to use for the active
        # device and then starts the local process that gets screenshots using
        # that method. The only method that currently requires a process is
        # monkeyrunner.

        # start a monkey process to get one image b/c it takes a long time
        # get picture of the screen using each approach, timing each one
        # present a dialog showing each pic with a checkbox next to each
        # store the user's request to the config file

        def getAverageTime(timeLst):
            # timeList is a list of floats sorted in reverse order (descending)
            differences = []
            for larger in range(len(timeLst) - 1):
                differences.append(timeLst[larger] - timeLst[larger + 1])
            return sum(differences) / (len(timeLst) - 1)

        device = self.mgr.devices[self.mgr.activeDeviceIndex]
        lcdHeight = device.height - device.chinBarHeight
        pulledBufferName = 'raw.' + device.serialNo
        averageTimes = []

        msg = ("The tool is collecting screenshots from your device using a variety of methods. " +
               "This may take about a minute.")
        utils.showOKMessageDialog(None, "", msg)

        # Try RGB32. Get RGB32 before starting monkeyrunner in case there are problems shutting
        # down monkeyrunner.
        rgb32Times = []
        for i in range(3):
            prefix, unflattenedPNGPath32, flattenedPNGPath32 = utils.getPNGNames(self.mgr, device.serialNo)
            rgb32Times.append(time.time())
            status32, msg = utils.writeImage(device.dt, pulledBufferName, device.serialNo, prefix, 
                                             unflattenedPNGPath32, flattenedPNGPath32, device.width, 
                                             lcdHeight, 'rgb32')
        rgb32Times.append(time.time())
        rgb32Times.reverse()
        averageTimes.append((constants.SCREENSHOT_METHOD_RGB32, getAverageTime(rgb32Times)))
        dprint("RGB32 time:", averageTimes[-1])

        # Try RGB565.
        rgb565Times = []
        for i in range(3):
            prefix, unflattenedPNGPath565, flattenedPNGPath565 = utils.getPNGNames(self.mgr, device.serialNo)
            rgb565Times.append(time.time())
            status565, msg = utils.writeImage(device.dt, pulledBufferName, device.serialNo, prefix, 
                                              unflattenedPNGPath565, flattenedPNGPath565, device.width, 
                                              lcdHeight, 'rgb565')
        rgb565Times.append(time.time())
        rgb565Times.reverse()
        averageTimes.append((constants.SCREENSHOT_METHOD_RGB565, getAverageTime(rgb565Times)))
        dprint("RGB565 time:", averageTimes[-1])

        # Takes a long time to start.
        imageGrabberPath = os.path.join(os.path.dirname(getExecutableOrRunningModulePath()),
                                        constants.MONKEYRUNNER_IMAGE_GRABBER_SCRIPT_NAME)
        documentsDollopPath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR)
        if True:
            outPipe = sys.stdout if constants.MONKEYRUNNER_PRINT else subprocess.PIPE
            self.monkeyrunnerProc = subprocess.Popen([monkeyrunnerPath, imageGrabberPath,
                                                      documentsDollopPath, device.serialNo, 
                                                      'True' if device.usingAltSerialNo else 'False'],
                                                     stdout=outPipe, stderr=outPipe)

        savedMonkeyPath = None
        monkeyImages = []
        imagePaths = []
        startTime = time.time()
        # Wait at most a minute for monkeyrunner to produce a screenshot.
        if True:
            while startTime + 60 > time.time() and not monkeyImages:
                documentsContents = os.listdir(documentsDollopPath)
                monkeyImages = sorted([x for x in documentsContents if x.startswith('device.' + device.serialNo) and 
                                       x.endswith('.png')])
                if monkeyImages and not savedMonkeyPath:
                    monkeyImageFilename = 'saved.' + monkeyImages[-1]
                    # Save the monkey image to a new name so that the monkey script doesn't delete it.
                    savedMonkeyPath = os.path.join(documentsDollopPath, monkeyImageFilename)
                    try:
                        shutil.copy(os.path.join(documentsDollopPath, monkeyImages[-1]), savedMonkeyPath)
                    except:
                        pass
                    else:
                        imagePaths += [(constants.SCREENSHOT_METHOD_MONKEYRUNNER, savedMonkeyPath)]
                else:
                    time.sleep(0.1)

        imagePaths += [(constants.SCREENSHOT_METHOD_RGB565, 
                        os.path.join(documentsDollopPath, flattenedPNGPath565)),
                       (constants.SCREENSHOT_METHOD_RGB32, 
                        os.path.join(documentsDollopPath, flattenedPNGPath32))]

        msg = ("The tool will now show some images of your device's screen and ask you to identify " +
               "which of them look correct. This will tell the tool how to communicate with the " +
               "device.")
        utils.showOKMessageDialog(None, "", msg)
                            
        acceptedMethods = []
        acceptedWidth, acceptedHeight = None, None
        for method, imagePath in imagePaths:
            response = []
            try:
                while True:
                    methodChooser = ScreenshotMethodChooser(self, device.width, lcdHeight, imagePath,
                                                            response)
                    methodChooser.CenterOnScreen()
                    methodChooser.ShowModal()
                    if response[0][0] == True:
                        acceptedWidth = device.width
                        acceptedHeight = lcdHeight
                        acceptedMethods.append(method)
                        break
                    elif response[0][0] == False:
                        break
                    else:
                        temp = device.width
                        device.width = lcdHeight
                        lcdHeight = temp
                        response = []
            except:
                pass

        device.width = acceptedWidth
        lcdHeight = acceptedHeight
        device.height = lcdHeight + device.chinBarHeight

        if savedMonkeyPath:
            try:
                os.remove(savedMonkeyPath)
            except:
                pass

        # Figure out how long it takes to pull images using monkeyrunner by waiting to find three
        # pulled by it.
        if constants.SCREENSHOT_METHOD_MONKEYRUNNER in acceptedMethods:
            monkeyImages = []
            while len(monkeyImages) < 3:
                documentContents = os.listdir(os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR))
                monkeyImages = [x for x in documentContents if x.startswith('device.' + device.serialNo) and 
                                x.endswith('.png')]
            monkeyFilenameSRE = re.compile("device\." + device.serialNo + "\.([0-9]+\.[0-9]+)\.png")
            monkeyTimes = []
            for x in monkeyImages:
                try:
                    monkeyTimes.append(float(monkeyFilenameSRE.match(x).groups()[0]))
                except:
                    pass
            monkeyTimes.sort()
            monkeyTimes.reverse()
            avgMonkeyTime = getAverageTime(monkeyTimes)
            # monkeyrunner isn't as stable, and may require re-starting at times, so penalize its time.
            avgMonkeyTime = 10.0 * avgMonkeyTime
            averageTimes.append((constants.SCREENSHOT_METHOD_MONKEYRUNNER, avgMonkeyTime))
            dprint("Monkeyrunner time:", averageTimes[-1])

        averageTimes.sort(key=lambda x: x[1])
        chosenMethods = [x[0] for x in averageTimes if x[0] in acceptedMethods]
        if chosenMethods:
            if chosenMethods[0] != constants.SCREENSHOT_METHOD_MONKEYRUNNER:
                # Create the file telling the monkeyrunner image grabber to terminate itself.
                stopdevicePath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR,
                                              'stopdevice.' + device.serialNo)
                with open(stopdevicePath, 'w') as fp:
                    # Opening it creates it.
                    pass
                # After monkeyrunner is run and not chosen, the first sendCommand('adb pull /dev/graphics/fb0 ...', ...)
                # call hangs, though the adb command itself exits very quickly. I believe that sendCommand is not 
                # stopping until the timeout is reached and the 'adb pull' command is killed. The adb server
                # "is out of date", according to what I've seen from adb on the command line. So, run 'adb pull'
                # here but don't wait for it to die.
                prefix, unflattenedPNGPath565, flattenedPNGPath565 = utils.getPNGNames(self.mgr, device.serialNo)
                rgb565Times.append(time.time())
                subprocess.Popen((config.adbPath + device.dt.serialNoString + 'pull /dev/graphics/fb0 ' + 
                                  pulledBufferName).split(),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            return (chosenMethods[0], acceptedMethods, [x[0] for x in imagePaths], acceptedWidth, 
                    acceptedHeight)
        else:
            msg = ("Based on your input, the tool doesn't know how to view the screen of your device " +
                   "and must exit.")
            utils.showOKMessageDialog(self, "Exiting", msg)
            self.onClose(None)
        

    def testsUnloaded(self):
#        self.testViewer = None
        self.addTestMenuItem.Enable(False)
        self.recordBtn.Enable()
        self.playPauseBtn.SetToggle(False)
        self.playPauseBtn.Disable()
        self.SetTitle(constants.APPLICATION_NAME_REGULAR_CASE)


    def reload(self, sessionName):
        # Maybe we have to let the OnButton call of the GUI terminate before we can 
        # replace the events box of the GUI.
        wx.PostEvent(self, ReloadGUIEvent(sessionName))


    def resetTest(self, sessionName):
        self.mgr.setPlayStatus(constants.PLAY_STATUS_READY_TO_PLAY)
        self.updateGUIToState(constants.PLAY_STATUS_READY_TO_PLAY)
        self.Layout()


    def resetTests(self, testFilePaths):
        self.Layout()


    def clearSuiteAndLoadTest(self, testFilePath):
        for control in [self.recordingToolsBox, self.waitTextBox, self.enterWaitBtn, self.verifyTextLabel,
                        self.verifyTextBox, self.enterTextBtn]:
            control.Disable()            
        for control in [self.playPauseBtn]: #self.replayEventsBox, self.playPauseBtn]:
            control.Enable()
        self.addTestMenuItem.Enable(True)
        self.Layout()
        self.mgr.setPlayStatus(constants.PLAY_STATUS_READY_TO_PLAY)


    def onDeleteSessions(self, event):
        pass


    def onEditConfiguration(self, event):
        configPath = os.path.join(getUserDocumentsPath(), constants.APP_DIR, 
                                  constants.APPLICATION_NAME_REGULAR_CASE + '.cfg')
        configParser = ConfigParser.RawConfigParser()
        deviceNames = []
        options = []
        if os.path.exists(configPath):
            configParser.read(configPath)
            serialNos = [x for x in configParser.sections() if not x.startswith(('Global', 'KEYCODE_MAPSDefault'))]
            for serialNo in serialNos:
                try:
                    make = configParser.get(serialNo, 'make')
                except:
                    make = ''
                try:
                    model = configParser.get(serialNo, 'model')
                except:
                    model = ''
                deviceNames.append(' '.join([serialNo, make, model]))
                try:
                    chosen = int(configParser.get(serialNo, 'screen'))
                    chosenName = constants.SCREENSHOT_METHOD_NAMES[chosen]
                except:
                    chosen = None
                if chosen == None:
                    accepted = sorted(constants.SCREENSHOT_METHOD_NAMES.values())
                else:
                    try:
                        accepted = configParser.get(serialNo, 'acceptedscreens')
                        accepted = [constants.SCREENSHOT_METHOD_NAMES[int(x.lstrip().rstrip())] 
                                    for x in accepted.split(',')]
                    except:
                        accepted = sorted(constants.SCREENSHOT_METHOD_NAMES.values())
                    accepted.remove(chosenName)
                    accepted = [chosenName] + accepted
                options.append(accepted)
                    
            dlg = ConfigureDialog(self, -1, serialNos=serialNos, deviceNames=deviceNames, 
                                  screenshotOptions=options)
            dlg.CenterOnScreen()

        dlg.ShowModal()
        for serialNo, method in dlg.changedScreenshotMethods:
            if serialNo == self.mgr.devices[self.mgr.activeDeviceIndex].serialNo:
                device = self.mgr.devices[self.mgr.activeDeviceIndex]
                device.cameraProcess.changeScreenshotMethod(method)
        dlg.Destroy()
        self.playAndRecordSizer.Fit(self.playAndRecordPanel)
        self.Layout()


    def onViewResults(self, event):
        # The default directory of the FileDialog causes the process' current
        # working directory to change. The default directory needs to be set
        # to the 'plays' directory to avoid making the user figure out where
        # the saved playback screenshots are, but the current working 
        # directory should be kept as is b/c that's where the screenshots are
        # saved and it makes the programming easier.
        playPath = os.path.join(wx.StandardPaths_Get().GetDocumentsDir(),
                                constants.APP_DIR,
                                "plays")
        if not os.path.exists(playPath):
            try:
                os.mkdir(playPath)
            except:
                msg = ("The directory of previous results, " + playPath + 
                       ", does not exist and could not be created.")
                dlg = wx.MessageDialog(None,
                                       msg,
                                       "Unable to create previous results directory",
                                       wx.OK)
                dlg.ShowModal()
                dlg.Destroy()
                return
        playFolders = [x for x in os.listdir(playPath) if os.path.isdir(os.path.join(playPath, x))]
        for devicePanel in self.devicePanels:
            devicePanel.hideFromMouseClicks()
        dlg = wx.SingleChoiceDialog(self,
                                    "Select Date and Time of Playback",
                                    "View Playback Screenshots",
                                    playFolders)
        dlg.ShowModal()
        for devicePanel in self.devicePanels:
            devicePanel.unhideFromMouseClicks()
        folder = dlg.GetStringSelection()
        if folder == '':
            return
        pngFiles = sorted([x for x in os.listdir(os.path.join(playPath, folder)) if x.endswith('png')])
        if len(pngFiles) == 0:
            path = os.path.join(playPath, folder)
            msg = "There are no screenshot files to be viewed in " + path + "."
            dlg = wx.MessageDialog(None,
                                   msg,
                                   "No screenshots there",
                                   wx.OK)
            dlg.ShowModal()
            dlg.Destroy()
            return
        os.startfile(os.path.join(playPath, folder, pngFiles[0]))
        dprint(folder)
        # dlg = wx.FileDialog(self, 
        #                     "Choose Playback Results", 
        #                     wildcard="*.png",
        #                     style=wx.FD_OPEN)
        # dlg.SetPath=                            os.path.join(wx.StandardPaths_Get().GetDocumentsDir(),
        #                                  constants.APP_DIR,
        #                                  "plays")
        # dlg.CenterOnScreen()

        # # this does not return until the dialog is closed.
        # val = dlg.ShowModal()
        dlg.Destroy()


    def onViewCredits(self, event):
        msg = """The following technologies have been used in creating this Dollop test tool, version {v}:

Cython
FFmpeg (bundled executable; not linked)
Michael Gilleland's Levenshtein distance implementation
NumPy
OpenCV
Python
SQLite
Tesseract
wxPython"""

        dlg = wx.MessageDialog(None,
                               msg.format(v=constants.VERSION),
                               "Acknowledgments",
                               wx.OK)
        dlg.ShowModal()
        dlg.Destroy()

        
    def onReplayStopped(self, event):
        # The buttons could be immediately reset, but to do so would be confusing
        # b/c the user would see the test continue on.
        pass


    def OnResult(self, targetImageUpdate):
        pass
        #self._setTargetImage(targetImageUpdate.width,
        #                     targetImageUpdate.height,
        #                     targetImageUpdate.imageString)


    def OnNewSession(self, _):
        self.OnRecordSession(None)
        

    def OnRecordSession(self, _):
        # XXX On start-up, a new session might be created automatically.
        # THen, the user could later choose to initiate one after he's
        # gotten everything together.
        def createRecordingPaths():
            dlg = wx.FileDialog(self, 
                                "Create a Test File",
                                os.getcwd(),
                                wildcard="*.py",
                                style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
            #dlg.SetPath = os.getcwd() #os.path.join(wx.StandardPaths_Get().GetDocumentsDir(),
                                      # constants.APP_DIR,
                                      # "plays")
            dlg.CenterOnScreen()
            dlg.ShowModal()
            dlg.Destroy()
            sessionPath = dlg.GetPath()
            # The user doesn't know about the entries in the DB. If he overwrites an existing
            # test script with the FileDialog above, he doesn't need the test (aka 'session'), 
            # so delete it from the DB.
            
            if not sessionPath:
                # It doesn't appear that the wxPython user can prevent the record button from appearing
                # depressed when it's first pressed.
                self.recordBtn.SetToggle(False)
            else:
                rootName = os.path.basename(sessionPath)
                if rootName.endswith('.py'):
                    rootName = rootName[:-3]
                testFolderPath = os.path.join(getUserDocumentsPath(), constants.APP_DIR, 'tests', rootName)
                if os.path.exists(testFolderPath):
                    try:
                        shutil.rmtree(testFolderPath)
                    except:
                        buttonStyle = wx.OK
                        dialogStyle = wx.ICON_ERROR
                        dlg = wx.MessageDialog(self,
                                               ("An attempt to remove the earlier test directory path at " + 
                                                testFolderPath + " failed."),
                                               "Error removing directory",
                                               buttonStyle | dialogStyle)
                        dlg.ShowModal()
                        dlg.Destroy()
                        return

                if not os.path.exists(os.path.join(getUserDocumentsPath(), constants.APP_DIR, 'tests')):
                    try:
                        os.mkdir(os.path.join(getUserDocumentsPath(), constants.APP_DIR, 'tests'))
                    except:
                        return

                for thing in os.listdir('.'):
                    if thing.startswith('record.' + rootName):
                        # This is from an earlier test w/ the same name.
                        os.remove(thing)
                os.mkdir(os.path.join('tests', rootName))

                self.mgr.recorder.deleteSessions([sessionPath])
                device = self.mgr.devices[self.mgr.activeDeviceIndex]
                if device.chinBarHeight:
                    chinBar = cv.CreateImageHeader((device.width, device.chinBarHeight),
                                                   cv.IPL_DEPTH_8U, 3)
                    cv.SetData(chinBar, device.chinBarImageString)

                    #write the resized image to file
                    chinBarImageName = constants.CHIN_BAR_IMAGE_TEMPLATE.format(ser=device.serialNo)
                    chinBarImagePath = os.path.join(globals_.getUserDocumentsPath(), 
                                                    constants.APP_DIR, 
                                                    chinBarImageName)
                    try:
                        cv.SaveImage(chinBar, chinBarImagePath)
                    except:
                        None, False

                with open(sessionPath, 'w') as fp:
                    fp.write("\n\n")
                    negativeKeycodeMap = {}
                    for key, value in config.keycodes[self.mgr.devices[self.mgr.activeDeviceIndex].keycodeMap].items():
                        negativeKeycodeMap[key] = -value
                    fp.write("NEGATIVE_KEYCODES=" + str(negativeKeycodeMap) + '\n')
                    fp.write("\n\n")
                    fp.write("def main(device):\n")
                self.recordBtn.SetToggle(True)
                self.mgr.setRecordingTestName(sessionPath)
                #self.testFilePath = name
                record(self, rootName)
                self.SetTitle("Recording " + sessionPath + " - " + constants.APPLICATION_NAME_REGULAR_CASE)


        def record(self, testName):
            for control in [self.recordingToolsBox, self.waitTextBox, self.enterWaitBtn, self.verifyTextLabel,
                            self.verifyTextBox, self.enterTextBtn]:
                control.Enable()
            for control in [self.playPauseBtn, self.stopBtn]: 
                control.Disable()
            
            # Kill OCRBoxProcesses to improve responsiveness of the computer.
            self.mgr.killAllOCRBoxProcesses()
            globals_.traceLogger.debug("Starting recording.")
            self.mgr.startSession(testName)

        if self.mgr.isRecording:
            self.mgr.killAllOCRBoxProcesses()
            globals_.traceLogger.debug("Stopping recording.")
            testPath = self.mgr.getRecordingTestPath()
            self.mgr.stopRecording()
            self.mgr.startOCRBoxProcess(testPath)

            for control in [self.recordingToolsBox, self.waitTextBox, self.enterWaitBtn, self.verifyTextLabel,
                            self.verifyTextBox, self.enterTextBtn]:
                control.Disable()
            self.verifyTextBox.SetValue('')
            self.waitTextBox.SetValue('')
            self.SetTitle(constants.APPLICATION_NAME_REGULAR_CASE)
                
        elif self.mgr.playStatus in (constants.PLAY_STATUS_PLAYING, constants.PLAY_STATUS_PAUSED):
            # The player is playing.
            self.mgr.pauseReplay()
            
            msg = "Do you want to stop playing the current test?"
            dialogStyle = wx.YES_NO
            dlg = wx.MessageDialog(self.devicePanels[self.activeDeviceIndex],
                                   msg,
                                   "Stop playing current test?",
                                   dialogStyle)
            if dlg.ShowModal() == wx.ID_YES:
                self.mgr.stopReplay()
                self.playPauseBtn.SetToggle(False)
                createRecordingPaths()
            else:
                self.mgr.resumeReplay()
                
            dlg.Destroy()

        else:
            createRecordingPaths()


    def onVerifyTextChar(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self.onVerifyTextEntry(event)
        event.Skip()


    def onVerifyTextEntry(self, event, testEntry=''):
        if config.DEBUG:
            text = testEntry
        else:
            text = self.verifyTextBox.GetValue()

        self.displayMessageInStatusBar("Added text to be found in the device screen: " + text)
        self.verifyTextBox.SetValue('')
        self.mgr.addTextToVerify(text)


    def displayMessageInStatusBar(self, message):
        self.SetStatusText(message)
        self.statusBarTimer.Start(3000, oneShot=True)


    def onWaitChar(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self.onWaitEntry(event)
        event.Skip()     


    def onWaitEntry(self, event, testEntry=''):
        if config.DEBUG:
            text = testEntry
        else:
            text = self.waitTextBox.GetValue()
        
        failed = False
        try:
            wait = float(text)
        except Exception, e:
            failed = True
        else:
            if wait <= 0:
                failed = True
                
        if failed: 
            msg = "Please enter a positive number."
            buttonStyle = wx.OK
            dialogStyle = wx.ICON_ERROR
            dlg = wx.MessageDialog(self.devicePanels[self.mgr.activeDeviceIndex],
                                   msg,
                                   "Please enter a number.",
                                   buttonStyle | dialogStyle)
            dlg.ShowModal()
            dlg.Destroy()
            return
        self.SetStatusText("Added wait of " + str(wait) + " seconds.")
        self.statusBarTimer.Start(3000, oneShot=True)
        self.waitTextBox.SetValue('')
        self.mgr.addWait(wait)


    def onStatusBarTimer(self, event):
        self.SetStatusText("")


    def onEventsBoxTimer(self, event):
        if self.mgr.playStatus not in (constants.PLAY_STATUS_PLAYING, constants.PLAY_STATUS_PAUSED):
            # The user may have stopped the test, while the replayProcess
            # had a little more to go before sending the status of the
            # event it just finished running. Because we're not playing
            # any longer, we disregard this status.
            return
        statuses = []
        while True:
            try:
                statuses.append(self.eventsBoxQueue.get_nowait())
            except Exception, e:
                break
            else:
                dprint('got something from eventsboxq', statuses)
        finishedTest = False
        status = None
        for status in statuses:
            if status in (constants.TEST_PASSED, constants.TEST_FAILED, constants.TEST_ERRORED):
                # These are the only statuses being returned now, actually.
                self.mgr.setPlayStatus(constants.PLAY_STATUS_FINISHED)
                self.updateGUIToState(constants.PLAY_STATUS_FINISHED)
                self.SetTitle("Finished playing test - " + constants.APPLICATION_NAME_REGULAR_CASE)
                self.mgr.finishingPlayback()
                self.mgr.recorder.finishTestOrPlayStorage(self.mgr.playName, 'play')
                

    def onAfterGUIStartTimer(self, event):
        self.mgr.startOCRBoxProcess()


    def OnReloadGUIPanelTimer(self, event):
        pass # XXX I don't think this procedure is being used.
        #self.resetTest(self.mgr.getSessionName())


    def onReplayMessageTimer(self, event):
        pass


    def onSetFocus(self, _):
        dprint("appframe onsetfocus")


    def onClose(self, event):
        # This may be called before the tool has been completely brought up and some attributes may
        # not yet exist, so try/except is necessary.
        try:
            dprint('activeDeviceIndex:', self.mgr.activeDeviceIndex)
            activeDevice = self.mgr.devices[self.mgr.activeDeviceIndex]
            try:
                activeDevice.cameraProcess.stopRequested = True
            except:
                pass
            # Create the file telling monkeyrunner to stop.
            try:
                stopdevicePath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR,
                                              'stopdevice.' + activeDevice.serialNo)
                dprint("STOPDEVICE PATH: ", stopdevicePath)
                with open(stopdevicePath, 'w') as fp:
                    # Calling open() creates the file.
                    pass
            except:
                dprint("CREATION OF STOPDEVICE FILE FAILED!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                bdbg()

            self.mgr.stopReplay()
            if self.mgr.isRecording:
                self.mgr.stopRecording()
            # If an exception is raised in this method, the GUI may 
            # (and has previously) fail to close.
            # self.Destroy by itself still requires CTRL+C to be used as well. Let's see if this works.
            try:
                self.eventsBoxTimer.Stop()
            except:
                pass
            self.mgr.killAllOCRBoxProcesses()
            self.mgr.recorder.maybeUpdateDeviceInfo(activeDevice.serialNo,
                                                    activeDevice.dt.maxADBCommandLength)
            self.devicePanels[self.mgr.activeDeviceIndex].deviceWindow.charTimer.Stop()
            os.chdir(self.originalWorkingDir)
            try:
                # I tried windll.kernel32.TerminateProcess() and it only worked when the
                # tool was run as root, while terminate() doesn't require root.
                self.mgr.adbForkServerProcess.terminate()
            except Exception, e:
                dprint("Failed to terminate the adb fork-server process. Exception:", str(e))

        except:
            dprint('EXITED onClose EARLY!!!!!!!!!!!!!!!')
        finally:
            self.Destroy()


class ScreenshotMethodChooser(wx.Dialog):
    def __init__(self, parent, width, height, imagePath, response):
        self.response = response

        self.swapped = False

        wx.Dialog.__init__(self, parent, -1, "Screenshot Method Acceptance")

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add((10, 10))

        textSizer = wx.BoxSizer(wx.HORIZONTAL)
        textSizer.Add((10, 10))
        text = wx.StaticText(self, -1, "Does this image look right?")
        textSizer.Add(text)
        sizer.Add(textSizer)
        sizer.Add((10, 10))

        panelBox = wx.BoxSizer(wx.HORIZONTAL)
        panelBox.Add((10, 10))
        
        panel1 = ImagePanel(self, -1, width, height, imagePath)
        panelBox.Add(panel1)
        panelBox.Add((10, 10))
        sizer.Add(panelBox)
        sizer.Add((10, 10))

        checkboxSizer = wx.BoxSizer(wx.HORIZONTAL)
        checkboxSizer.Add((10, 10))
        self.swapDimensionsCheckbox = wx.CheckBox(self, id=wx.ID_YES)
        self.swapDimensionsCheckbox.Bind(wx.EVT_CHECKBOX, self.onSwapDimensions)
        checkboxSizer.Add(self.swapDimensionsCheckbox, 0, wx.RIGHT)
        text = wx.StaticText(self, -1, "Try Swapping Dimensions")
        checkboxSizer.Add(text, border=5, flag=wx.LEFT)
        checkboxSizer.Add((10, 10))

        sizer.Add(checkboxSizer)
        sizer.Add((10, 10))

        buttonSizer = wx.BoxSizer(wx.HORIZONTAL)
        buttonSizer.Add((10, 10))
        self.yesButton = wx.Button(self, id=wx.ID_YES)
        self.yesButton.Bind(wx.EVT_BUTTON, self.onYes)
        buttonSizer.Add(self.yesButton, 0, wx.RIGHT)
        buttonSizer.Add((10, 10))
        self.noButton = wx.Button(self, id=wx.ID_NO)
        self.noButton.Bind(wx.EVT_BUTTON, self.onNo)
        buttonSizer.Add(self.noButton, 0, wx.RIGHT)
        buttonSizer.Add((10, 10))

        sizer.Add(buttonSizer)

        sizer.Add((10, 10))

        self.SetSizer(sizer)
        sizer.Fit(self)


    def onYes(self, evt):
        self.response.append((True, self.swapped))
        self.Destroy()


    def onNo(self, evt):
        self.response.append((False, self.swapped))
        self.Destroy()


    def onSwapDimensions(self, evt):
        self.swapped = not self.swapped
        self.response.append((None, self.swapped))
        self.Destroy()


class ImagePanel(wx.Panel):
    """ class ImagePanel creates a panel with an image on it, inherits wx.Panel """
    def __init__(self, parent, id, width, height, imagePath):
        wx.Panel.__init__(self, parent, id)
        try:
            # data = open(imagePath, "rb").read()
            # stream = cStringIO.StringIO(data)
            # image = wx.ImageFromStream(stream)
            smallWidth = 300
            smallHeight = int((float(smallWidth) / width) * height)
            # image.Rescale(smallWidth, smallHeight) 
            # bmp = wx.BitmapFromImage(image)
            # wx.StaticBitmap(self, -1, bmp, (5, 5))
            try:
                _image = cv.LoadImage(imagePath, cv.CV_LOAD_IMAGE_UNCHANGED)
                #_image = Image.open(imagePath)
                #imageString = _image.tostring()
            except Exception, e:
                dprint("error!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                bdbg()
                return
            
            _imageColorsCorrect = cv.CreateMat(height, width, cv.CV_8UC3)
            cv.SetData(_imageColorsCorrect, '\x00\x00\x00' * height * width)
            cv.ConvertImage(_image, _imageColorsCorrect, cv.CV_CVTIMG_SWAP_RB)
            #image = cv.CreateImageHeader((width, height),   cv.IPL_DEPTH_8U, 3)
            #cv.SetData(image, imageString)
            reducedScreen = cv.CreateMat(smallHeight, smallWidth,
                                         cv.CV_8UC3)
            cv.Resize(_imageColorsCorrect, reducedScreen)
            reducedImageString = reducedScreen.tostring()
            image = wx.EmptyImage(smallWidth, smallHeight)
            image.SetData(reducedImageString)
            
            bmp = wx.BitmapFromImage(image)
            wx.StaticBitmap(self, -1, bmp)
        except:
            bdbg()


class PlateButtonNoLeftUp(platebtn.PlateButton):
    # I delete PlateButtons in TestViewer; the OnLeftUp method is run after the
    # C++ part of the button has been deleted, creating an error.
    def OnLeftUp(self, evt):
        """Post a button event if the control was previously in a
        pressed state.
        @param evt: wx.MouseEvent

        """
        if self._state['cur'] == PLATE_PRESSED:
            pos = evt.GetPositionTuple()
            size = self.GetSizeTuple()
            if not (self._style & PB_STYLE_DROPARROW and pos[0] >= size[0] - 16):
                self.__PostEvent()

        try:
            if self._pressed:
                self.SetState(PLATE_PRESSED)
            else:
                self.SetState(PLATE_HIGHLIGHT)
        except:
            pass


class AbstractTestDialog(sc.SizedDialog):
    def RightClickCb(self, event):
        menu = wx.Menu()
        for (id,title) in self.menu_title_by_id.items():
            menu.Append(id, title)
            wx.EVT_MENU(menu, id, self.MenuSelectionCb)

        self.PopupMenu(menu, event.GetPoint())
        menu.Destroy() # destroy to avoid mem leak


    def MenuSelectionCb(self, event):
        selectionName = self.menu_title_by_id[event.Id]
        if selectionName == 'Rename':
            oldSessionName = self.selectedName
            while True:
                dlg = wx.TextEntryDialog(self,
                                         "Enter the new name for session '{sn}':".format(sn=oldSessionName),
                                         "Rename Session")
                dlgButtonPressed = dlg.ShowModal()
                newSessionName = dlg.GetValue()
                if dlgButtonPressed == wx.ID_CANCEL:
                    dlg.Destroy()
                    return
                if newSessionName in self.existingTestNames and oldSessionName != newSessionName:
                    msg = ("That name is the same as another test's name. Are you sure that you want to replace that " +
                           "existing test?")
                    deleteExistingTestDlg = wx.MessageDialog(None,
                                                             msg,
                                                             "Replace existing test?",
                                                             wx.YES_NO)
                    if deleteExistingTestDlg.ShowModal() == wx.ID_YES:
                        deleteExistingTestDlg.Destroy()
                        beingReplacedIndex = self.existingTestNames.index(newSessionName)
                        self.existingTestNames.pop(beingReplacedIndex)
                        self.existingTestsCtrl.DeleteItem(beingReplacedIndex)
                        break
                    else:
                        deleteExistingTestDlg.Destroy()
                        # The same 'Enter the new name...' dialog will be displayed again, so delete the current one.
                        dlg.Destroy()
                elif newSessionName == oldSessionName:
                    # There's nothing to be done.
                    dlg.Destroy()
                    return
                elif newSessionName == '':
                    buttonStyle = wx.OK
                    dialogStyle = wx.ICON_ERROR
                    emptyNameDlg = wx.MessageDialog(None,
                                                    "The new test name must not be empty.",
                                                    "Empty Test Name Specified",
                                                    buttonStyle | dialogStyle)
                    emptyNameDlg.ShowModal()
                    emptyNameDlg.Destroy()
                    # The same 'Enter the new name...' dialog will be displayed again, so delete the current one.
                    dlg.Destroy()
                else:
                    break
            dlg.Destroy()
            
            try:
                oldPath = os.path.abspath(os.path.join('tests', oldSessionName))
                newPath = os.path.abspath(os.path.join('tests', newSessionName))
                shutil.move(oldPath, newPath)
            except Exception, e:
                dialogStyle = wx.ICON_ERROR
                emptyNameDlg = wx.MessageDialog(None,
                                                ("The tool failed to rename the folder at " +
                                                 oldPath + " to " + newPath + ". The error " + 
                                                 "given was " + str(e) + "."),
                                                "Attempt to Move Test Folder Failed",
                                                dialogStyle)
                emptyNameDlg.ShowModal()
                emptyNameDlg.Destroy()
                return

            self.mgr.recorder.renameSession(oldSessionName, newSessionName)
            oldIndex = self.existingTestNames.index(oldSessionName)
            self.existingTestNames.pop(oldIndex)
            self.existingTestNames.insert(oldIndex, newSessionName)
            self.existingTestsCtrl.DeleteItem(oldIndex)
            self.existingTestsCtrl.InsertStringItem(oldIndex, newSessionName)
            # ListCtrl does not show an item being selected after a right-click menu
            # action is performed on it, so, to the user, it will not appear that
            # anything has been selected.
            self.selectedName = None

        elif selectionName == 'Delete':
            oldSessionName = self.selectedName
            try:
                oldPath = os.path.abspath(os.path.join('tests', oldSessionName))
                shutil.rmtree(oldPath)
            except Exception, e:
                bdbg()
                dialogStyle = wx.ICON_ERROR
                emptyNameDlg = wx.MessageDialog(None,
                                                ("The tool failed to delete the folder at " +
                                                 oldPath + ". A file in " + 
                                                 "the folder may be open in another " + 
                                                 "application."),
                                                "Attempt to Delete Test Folder Failed",
                                                dialogStyle)
                emptyNameDlg.ShowModal()
                emptyNameDlg.Destroy()
                return
            
            self.mgr.recorder.deleteSessions([oldSessionName])
            oldIndex = self.existingTestNames.index(oldSessionName)
            self.existingTestNames.pop(oldIndex)
            self.existingTestsCtrl.DeleteItem(oldIndex)            
            # ListCtrl does not show an item being selected after a right-click menu
            # action is performed on it, so, to the user, it will not appear that
            # anything has been selected.
            self.selectedName = None


    def onCancel(self, event):
        self.cancelled = True
        self.Destroy()


    def onClose(self, event):
        self.cancelled = True
        self.Destroy()


class LoadTestDialog(AbstractTestDialog):
    @staticmethod
    def showDialog(appFrame, mgr, existingTestNames, addToExisting=False):
        dlg = LoadTestDialog(appFrame, -1, mgr, existingTestNames, addToExisting)
        dlg.CenterOnScreen()
        # this does not return until the dialog is closed.
        dlg.ShowModal()
        cancelled = dlg.cancelled
        return dlg.selectedName, dlg.cancelled


    def __init__(self, appFrame, id, mgr, existingTestNames, addToExisting=False):
        self.appFrame = appFrame
        if addToExisting:
            title = "Add Test To Existing Test Suite"
        else:
            title = "Load Test Into New Test Suite"
        wx.Dialog.__init__(self, None, -1, title=title)

        self.mgr = mgr
        self.existingTestNames = existingTestNames

        self.cancelled = False
        self.selectedName = None
        
        self.Bind(wx.EVT_MOTION, self.onMouseMove)
        self.Bind(wx.EVT_CLOSE, self.onClose)

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.existingTestsCtrl = wx.ListCtrl(self, -1, style=wx.LC_REPORT, size=(100, 300))

        # When this InsertColumn is commented, a Seg Fault occurs.
        # 20 truncates to 2 chars, 50 to 3, 100 to 11, 300 introduces a horiz scrollbar
        self.existingTestsCtrl.InsertColumn( 0, "Existing tests:", width=270) 
        for index, x in enumerate(existingTestNames):
            self.existingTestsCtrl.InsertStringItem(index, x)

        wx.EVT_LIST_ITEM_RIGHT_CLICK(self.existingTestsCtrl, -1, self.RightClickCb )
        self.existingTestsCtrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self.onItemSelected)
        self.existingTestsCtrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.onTestChosen)

        # Clear variables
        self.selectedName = None

        _existingTestNames = []
        for name in existingTestNames:
            _existingTestNames.append((wx.NewId(), name))

        hsizer = wx.BoxSizer(wx.HORIZONTAL)
        hsizer.Add(self.existingTestsCtrl, 1, wx.EXPAND)
        sizer.Add(hsizer, 1, wx.EXPAND)
        
        msizer = wx.BoxSizer(wx.VERTICAL)
        # The parameters:
        # 1, wx.EXPAND | wx.ALL, 20
        # cause the buttons to be moved close to the bottom of the dialog.
        msizer.Add(sizer, 1, wx.EXPAND | wx.ALL, 20)
        # This thin, horizontal spacer prevents the text selection list from being made too narrow.
        msizer.Add((300, 1))
        
        # wx.StdDialogButtonSizer() causes wx.ID_CLOSE to be placed at the top left of the dialog,
        # so avoid it.
        # buttonSizer = wx.StdDialogButtonSizer()
        buttonSizer = wx.BoxSizer(wx.HORIZONTAL)

        self.cancelButton = wx.Button(self, id=wx.ID_CANCEL)
        self.cancelButton.Bind(wx.EVT_BUTTON, self.onCancel)
        # It doesn't matter which order I add them in; Apply always appears
        # to the right of Cancel.
        buttonSizer.Add(self.cancelButton, 0, wx.RIGHT)

        buttonSizer.Add((6, 1), 0, wx.RIGHT)
        
        self.okButton = wx.Button(self, id=wx.ID_OK)
        self.okButton.Bind(wx.EVT_BUTTON, self.onOK)
        # It doesn't matter which order I add them in; Apply always appears
        # to the right of Cancel.
        buttonSizer.Add(self.okButton, 0, wx.RIGHT)

        buttonSizer.Add((20,1), 0, wx.RIGHT)
        
        msizer.Add(buttonSizer, 0, wx.ALIGN_RIGHT, 200)

        msizer.Add((100, 12), 0, wx.ALIGN_RIGHT)
        
        self.SetSizer(msizer)

        # Brian, this Fit() actually works.
        msizer.Fit(self)

        menu_titles = ["Delete", "Rename"]
        self.menu_title_by_id = {}
        for title in menu_titles:
            self.menu_title_by_id[ wx.NewId() ] = title


    def onMouseMove(self, event):
        # Capture mouse movements. On Windows, if this isn't done, the
        # DeviceWindow will receive them instead.
        # event.ShouldPropagate() returns False in this method.
        dprint("LoadTestDialog.onMouseMove(), shouldPropagate:", event.ShouldPropagate())


    def onKeyDown(self, event):
        if event.GetKeyCode() != wx.WXK_RETURN:
            event.Skip()
            return
        self.onOK(event)

        
    def onItemSelected(self, event):
        dprint('onItemSelected, shouldPropagate():', event.ShouldPropagate())
        self.selectedName = event.GetText()
        event.StopPropagation()
        event.StopPropagation()
        event.StopPropagation()


    def OnLeftMouseDownInTextControl(self, event):
        # If this Skip() isn't here, onItemSelected will not be called.
        event.Skip()
        pass
            
    
    def onLeftMouseUpInTextControl(self, event):
        pass


    def OnLeftDoubleClickInTextControl(self, event):
        pass


    def onTestChosen(self, event):
        # Very interestingly, if we call unhideFromMouseClicks() here, rather than at the
        # end of this routine, the down clicks will be sent to the device.
        event.StopPropagation()
        event.StopPropagation()
        event.StopPropagation()
        self.selectedName = event.GetText()
        self.Destroy()
        dprint('onTestChosen, shouldPropagate():', event.ShouldPropagate())
        
        
    def onOK(self, event):
        for devicePanel in self.appFrame.devicePanels:
            devicePanel.unhideFromMouseClicks()
        self.Destroy()
        event.StopPropagation()
        event.StopPropagation()
        event.StopPropagation()
        return


    def onCancel(self, event):
        for devicePanel in self.appFrame.devicePanels:
            devicePanel.unhideFromMouseClicks()
        self.cancelled = True
        self.Destroy()


class NameTestDialog(AbstractTestDialog):
    # This dialog is presented when the user wants to create a new test (and
    # begin recording).
    @staticmethod
    def showDialog(mgr, existingTestNames, suggestedName):
        dlg = NameTestDialog(None, -1, mgr, existingTestNames, suggestedName)
        dlg.CenterOnScreen()
        dlg.ShowModal()
        name = dlg.sessionNameCtrl.GetValue()
        cancelled = dlg.cancelled
        return name, cancelled


    def __init__(self, parent, id, mgr, existingTestNames, suggestedName):
        wx.Dialog.__init__(self, parent, -1, title="New test name")
        self.mgr = mgr
        self.existingTestNames = existingTestNames

        self.suggestedNameClearedAlready = False
        self.cancelled = False
        
        self.Bind(wx.EVT_CLOSE, self.onClose)

        sizer = wx.BoxSizer(wx.VERTICAL)

        self.existingTestsCtrl = wx.ListCtrl(self, -1, style=wx.LC_REPORT, size=(100, 300))
        self.existingTestsCtrl.Bind(wx.EVT_KEY_DOWN, self.onKeyDown)
        # When this InsertColumn is commented, a Seg Fault occurs.
        # 20 truncates to 2 chars, 50 to 3, 100 to 11, 300 introduces a horiz scrollbar
        self.existingTestsCtrl.InsertColumn( 0, "Existing tests:", width=270) 
        for index, x in enumerate(existingTestNames):
            self.existingTestsCtrl.InsertStringItem(index, x)

        ### 1. Register source's EVT_s to invoke launcher. ###
        wx.EVT_LIST_ITEM_RIGHT_CLICK(self.existingTestsCtrl, -1, self.RightClickCb )
        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.onItemSelected)
        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.onTestNameChosen)
        
        # Clear variables
        self.selectedName = None

        _existingTestNames = []
        for name in existingTestNames:
            _existingTestNames.append((wx.NewId(), name))

        hsizer = wx.BoxSizer(wx.HORIZONTAL)
        hsizer.Add(self.existingTestsCtrl, 1, wx.EXPAND)
        sizer.Add(hsizer, 1, wx.EXPAND)

        sizer.Add((1, 10), 0)
        
        sizer.Add(wx.StaticText(self, -1, "Name of the new test:", (20,20)))
        self.sessionNameCtrl = wx.TextCtrl(self, -1, suggestedName, size=(300, 27))
        self.sessionNameCtrl.Bind(wx.EVT_KEY_DOWN, self.onKeyDown)
        self.sessionNameCtrl.Bind(wx.EVT_LEFT_DOWN, self.OnLeftMouseDownInTextControl)
        self.sessionNameCtrl.Bind(wx.EVT_CHAR, self.OnCharEvent)

        sizer.Add(self.sessionNameCtrl)

        msizer = wx.BoxSizer(wx.VERTICAL)
        # The parameters:
        # 1, wx.EXPAND | wx.ALL, 20
        # cause the buttons to be moved close to the bottom of the dialog.
        msizer.Add(sizer, 1, wx.EXPAND | wx.ALL, 20)

        # wx.StdDialogButtonSizer() causes wx.ID_CLOSE to be placed at the top left of the dialog,
        # so avoid it.
        # buttonSizer = wx.StdDialogButtonSizer()
        buttonSizer = wx.BoxSizer(wx.HORIZONTAL)

        self.cancelButton = wx.Button(self, id=wx.ID_CANCEL)
        self.cancelButton.Bind(wx.EVT_BUTTON, self.onCancel)
        # It doesn't matter which order I add them in; Apply always appears
        # to the right of Cancel.
        buttonSizer.Add(self.cancelButton, 0, wx.RIGHT)

        buttonSizer.Add((6, 1), 0, wx.RIGHT)
        
        self.okButton = wx.Button(self, id=wx.ID_OK)
        self.okButton.Bind(wx.EVT_BUTTON, self.onOK)
        # It doesn't matter which order I add them in; Apply always appears
        # to the right of Cancel.
        buttonSizer.Add(self.okButton, 0, wx.RIGHT)
        buttonSizer.Add((20,1), 0, wx.RIGHT)
        msizer.Add(buttonSizer, 0, wx.ALIGN_RIGHT, 200)
        msizer.Add((100, 12), 0, wx.ALIGN_RIGHT)
        self.SetSizer(msizer)
        # This Fit() does indeed work.
        msizer.Fit(self)

        menu_titles = ["Delete", "Rename"]
        self.menu_title_by_id = {}
        for title in menu_titles:
            self.menu_title_by_id[ wx.NewId() ] = title

        self.okButton.SetFocus()


    def onKeyDown(self, event):
        if event.GetKeyCode() != wx.WXK_RETURN:
            event.Skip()
            return
        self.onOK(event)

        
    def OnCharEvent(self, event):
        code = event.GetKeyCode()
        if code < 256:
            char = chr(code)
            # http://msdn.microsoft.com/en-us/library/aa365247%28v=vs.85%29.aspx
            if char not in ['<', '>', ':', '"', '/', '\\', '|', '?', '*', ' ']:
                event.Skip()

        
    def onItemSelected(self, event):
        self.selectedName = event.GetText()
        self.sessionNameCtrl.SetValue(self.selectedName)
        self.suggestedNameClearedAlready = True


    def OnLeftMouseDownInTextControl(self, event):
        if not self.suggestedNameClearedAlready:
            self.sessionNameCtrl.SetValue("")
            self.suggestedNameClearedAlready = True
        event.Skip()
            

    def onTestNameChosen(self, event):
        self.onItemSelected(event)
        self.onOK(event)
        
        
    def onOK(self, event):
        newName = self.sessionNameCtrl.GetValue().lstrip().rstrip()
        if newName in self.existingTestNames:
            msg = "That name is the same as another test's name. Are you sure that you want to replace that existing test?"
            deleteExistingTestDlg = wx.MessageDialog(None,
                                                     msg,
                                                     "Replace existing test?",
                                                     wx.YES_NO)
            if deleteExistingTestDlg.ShowModal() == wx.ID_YES:
                deleteExistingTestDlg.Destroy()
                self.Destroy()
                self.mgr.recorder.deleteSessions([newName])
                return
            else:
                deleteExistingTestDlg.Destroy()
                return
        elif newName != '':
            self.Destroy()
            return


class ConfigureDialog(wx.Dialog):
    def __init__(self, frame, id, serialNos=None, deviceNames=None, screenshotOptions=None):
        wx.Dialog.__init__(self, frame, -1, title=constants.APPLICATION_NAME_REGULAR_CASE + " Configuration")
        self.frame = frame
        self.serialNos = serialNos
        self.deviceNames = deviceNames
        self.screenshotOptions = screenshotOptions

        self.changedScreenshotMethods = []

        self.Bind(wx.EVT_CLOSE, self.onClose)
        self.Bind(wx.EVT_CHAR, self.onCharEvent)

        p = wx.Panel(self)
        nb = wx.Notebook(p)
        self.systemPage = SystemConfigPage(nb, self)
        nb.AddPage(self.systemPage, "System")
        self.keycodesPage = KeycodesConfigPage(nb, self)
        nb.AddPage(self.keycodesPage, "Keycodes")        
        self.screenshotPage = ScreenshotConfigPage(nb, self, serialNos, deviceNames, screenshotOptions)
        nb.AddPage(self.screenshotPage, "Screenshots")
        sizer = wx.BoxSizer()
        sizer.Add(nb, 1, wx.EXPAND)
        p.SetSizer(sizer)
        # This Fit() has been observed and works.
        sizer.Fit(self)


    def onClose(self, event):
        for mapName in self.keycodesPage.scancodeCtrls.keys():
            for keycode, ctrl in self.keycodesPage.scancodeCtrls[mapName].items():
                if ctrl.GetValue() == "":
                    # Neither of these is working:
                    # self.keycodesPage.SetFocus()
                    # ctrl.SetFocus()
                    buttonStyle = wx.OK
                    dialogStyle = wx.ICON_ERROR
                    dlg = wx.MessageDialog(self,
                                           # XXX This message needs to name the keyMap once more than one keyMap is
                                           # supported.
                                           "Please either delete the keycode " + keycode + " or give it a value.",
                                           "Error",
                                           buttonStyle | dialogStyle)
                    dlg.ShowModal()
                    dlg.Destroy()
                    return

        name2Method = {}
        for method, name in constants.SCREENSHOT_METHOD_NAMES.items():
            name2Method[name] = method
        for serialNo, methodName in self.screenshotPage.serialNo2MethodName.items():
            index = self.serialNos.index(serialNo)
            originalMethodName = self.screenshotOptions[index][0]
            if originalMethodName != methodName:
                self.changedScreenshotMethods.append((serialNo, name2Method[methodName]))

        success, message, title, self.configParser = utils.Config.updateConfigModuleAndFile(self)
        if not success:
            buttonStyle = wx.OK
            dialogStyle = wx.ICON_ERROR
            dlg = wx.MessageDialog(self,
                                   message,
                                   "ADB Connection Error",
                                   buttonStyle | dialogStyle)
            dlg.ShowModal()
            dlg.Destroy()
            
        # Hard-coded 'Default' will change when multiple keycode-scancode maps are supported.
        #self.frame.keycodeSizer.Clear(True)
        self.frame.refreshKeycodeMenu()
        # not doing anything: self.frame.keycodeSizer.Remove(self.frame.keycodeMenu)
        #self.frame.playAndRecordSizer.Fit(self.frame.playAndRecordPanel)
        self.Destroy()


    def onCharEvent(self, event):
        #'char:', event.GetKey() #event.GetUnicodeKey()
        event.Skip()        


class SystemConfigPage(wx.Panel):
    def __init__(self, parent, dialog):
        wx.Panel.__init__(self, parent)
        self.dialog = dialog
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, -1, "Name of, or path to, the Android Debug Bridge (adb) executable:", (20,20)))
        self.adbPathCtrl = wx.TextCtrl(self, -1, config.adbPath, size=(300, 27))
        sizer.Add(self.adbPathCtrl)

        msizer = wx.BoxSizer(wx.VERTICAL)
        # The parameters:
        # 1, wx.EXPAND | wx.ALL, 20
        # cause the buttons to be moved close to the bottom of the dialog.
        msizer.Add(sizer, 1, wx.EXPAND | wx.ALL, 20)

        # wx.StdDialogButtonSizer() causes wx.ID_CLOSE to be placed at the top left of the dialog,
        # so avoid it.
        # buttonSizer = wx.StdDialogButtonSizer()
        buttonSizer = wx.BoxSizer(wx.VERTICAL)
        
        # Using an id of wx.ID_CLOSE causes the button to be placed
        # in the top left corner when no pos is given. Using
        # wx.ID_APPLY instead, f.e., allows it to appear in the
        # bottom right.
        self.closeButton = wx.Button(self, id=wx.ID_CLOSE)
        self.closeButton.Bind(wx.EVT_BUTTON, self.dialog.onClose)
        # It doesn't matter which order I add them in; Apply always appears
        # to the right of Cancel.
        buttonSizer.Add(self.closeButton, 1, wx.RIGHT)

        msizer.Add(buttonSizer, 0, wx.ALIGN_RIGHT, 12)
        #buttonSizer.Realize()
        
        self.SetSizer(msizer)


class ScreenshotConfigPage(wx.Panel):
    def __init__(self, parent, dialog, serialNos, deviceNameStrings, screenshotMethodss):
        wx.Panel.__init__(self, parent)
        self.dialog = dialog
        self.serialNos = serialNos
        self.deviceNames = deviceNameStrings
        self.screenshotMethodss = screenshotMethodss

        self.serialNo2MethodName = {}

        deviceSizer = wx.BoxSizer(wx.VERTICAL)
        deviceSizer.Add((20,10))
        deviceSizer.Add(wx.StaticText(self, -1, "Device:"), flag=wx.LEFT, border=10)
        self.deviceNameCtrl = wx.Choice(self, choices=deviceNameStrings)
        self.deviceNameCtrl.SetSelection(0)
        self.deviceNameCtrl.Bind(wx.EVT_CHOICE, self.onDeviceName)
        deviceSizer.Add(self.deviceNameCtrl, flag=wx.LEFT, border=10)

        methodSizer = wx.BoxSizer(wx.VERTICAL)
        methodSizer.Add(wx.StaticText(self, -1, "Screenshot Method:"), flag=wx.LEFT, border=10)
        self.methodCtrl = wx.Choice(self, choices=screenshotMethodss[0])
        self.methodCtrl.SetSelection(0)
        self.methodCtrl.Bind(wx.EVT_CHOICE, self.onMethodName)
        methodSizer.Add(self.methodCtrl, flag=wx.LEFT, border=10)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(deviceSizer)
        sizer.Add(methodSizer, flag=wx.TOP, border=10)

        msizer = wx.BoxSizer(wx.VERTICAL)
        # The parameters:
        # 1, wx.EXPAND | wx.ALL, 20
        # cause the buttons to be moved close to the bottom of the dialog.
        msizer.Add(sizer, 1, wx.EXPAND|wx.ALL, 20)

        # wx.StdDialogButtonSizer() causes wx.ID_CLOSE to be placed at the top left of the dialog,
        # so avoid it.
        # buttonSizer = wx.StdDialogButtonSizer()
        buttonSizer = wx.BoxSizer(wx.VERTICAL)
        
        # Using an id of wx.ID_CLOSE causes the button to be placed
        # in the top left corner when no pos is given. Using
        # wx.ID_APPLY instead, f.e., allows it to appear in the
        # bottom right.
        self.closeButton = wx.Button(self, id=wx.ID_CLOSE)
        self.closeButton.Bind(wx.EVT_BUTTON, self.dialog.onClose)
        # It doesn't matter which order I add them in; Apply always appears
        # to the right of Cancel.
        buttonSizer.Add(self.closeButton, 1, wx.RIGHT)

        msizer.Add(buttonSizer, 0, flag=wx.ALIGN_RIGHT, border=12)
        #buttonSizer.Realize()

        # msizer.Layout() didn't help
        # msizer.Fit(self) didn't help
        self.SetSizer(msizer)


    def onDeviceName(self, event):
        deviceIndex = self.deviceNameCtrl.GetSelection()
        self.methodCtrl.SetItems(self.screenshotMethodss[deviceIndex])
        self.methodCtrl.SetSelection(0)


    def onMethodName(self, event):
        deviceIndex = self.deviceNameCtrl.GetSelection()
        methodIndex = self.methodCtrl.GetSelection()
        self.serialNo2MethodName[self.serialNos[deviceIndex]] = self.screenshotMethodss[deviceIndex][methodIndex]


class KeycodesConfigPage(wx.Panel):
    def __init__(self, parent, dialog):
        wx.Panel.__init__(self, parent, -1,
                          style = wx.TAB_TRAVERSAL, name="panel1" )
        self.parent = parent
        self.dialog = dialog
        
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        
        sideBorder = 15

        self.sizer.Add((1, 5))
        defaultKeycodesTitle = wx.StaticText(self, -1, "Default Keycodes:")
        self.sizer.Add(defaultKeycodesTitle, border=sideBorder, flag=wx.LEFT)
        self.sizer.Add((1, 5))
        
        # XXX - Provide a drop-down menu that allows the user to choose which
        # keycode mapping he is editing.
        self.keycodePanels = {}
        #defaultKeycodesBox = wx.StaticBox(self, -1, "Default Keycodes")
        #defaultKeycodesSizer = wx.BoxSizer(wx.VERTICAL) #wx.StaticBoxSizer(defaultKeycodesBox, wx.VERTICAL)
        # Maps the keycode mapping, e.g. 'Default' or 'Mapping 2', to
        # the wx ID of the button that adds a new keycode-scancode
        # pair.
        self.addKeycodeButtons = {}
        self.newKeycodeCtrls = {}
        self.newScancodeCtrls = {}        

        self.scancodeCtrls = {}
        # use this to determine the keycode to update config.py as soon as control is lost
        self.scancodeCtrlIDToMapNameKeycode = {}
        self.deleteButtonIDToMapNameKeycode = {}
        self.keycodesSizers = {}
        # Used to determine the values in config.py's keycodes dict that might need
        # updating.
        self.focusedMapKeycodePairs = []
        mapNames = config.keycodes.keys()
        for mapName in mapNames:
            self.keycodePanels[mapName] = wx.lib.scrolledpanel.ScrolledPanel(self, -1, size=(350, 300),
                                                                             style = wx.TAB_TRAVERSAL|wx.SUNKEN_BORDER, 
                                                                             name=mapName)
            self.keycodesScancodes = {}
            self.scancodeCtrls[mapName] = {}
            keys = sorted(config.keycodes[mapName].keys())
            self.keycodesSizers[mapName] = wx.FlexGridSizer(cols=3, vgap=4, hgap=4)
            
            for name in keys:
                value = config.keycodes[mapName][name]
                #h = wx.BoxSizer(wx.HORIZONTAL)
                keycodeLabel = wx.StaticText(self.keycodePanels[mapName], -1, name + ":")
                self.keycodesSizers[mapName].Add(keycodeLabel, 
                                                 border=5, 
                                                 flag=wx.TOP | wx.ALIGN_BOTTOM | wx.ALIGN_RIGHT)
                ctrlID = wx.NewId()
                ctrl = wx.TextCtrl(self.keycodePanels[mapName], ctrlID, str(value), size=(50, 27))
                ctrl.Bind(wx.EVT_SET_FOCUS, self.onScancodeCtrlFocus)
                ctrl.Bind(wx.EVT_CHAR, self.onScancodeChar)
                self.scancodeCtrlIDToMapNameKeycode[ctrlID] = (mapName, name)
                self.keycodesSizers[mapName].Add(ctrl, border=5, flag=wx.RIGHT | wx.TOP)
                self.scancodeCtrls[mapName][name] = ctrl
                buttonID = wx.NewId()
                button = wx.Button(self.keycodePanels[mapName], buttonID, label="Delete", style=wx.BU_EXACTFIT)
                self.deleteButtonIDToMapNameKeycode[buttonID] = (mapName, name)
                self.keycodesSizers[mapName].Add(button, border=10, flag=wx.ALIGN_BOTTOM | wx.LEFT)
                button.Bind(wx.EVT_BUTTON, self.onDeleteKeycode)
                
            self.keycodePanels[mapName].SetSizer(self.keycodesSizers[mapName])
            self.keycodePanels[mapName].SetAutoLayout(1)
            self.keycodePanels[mapName].SetupScrolling()
            self.sizer.Add(self.keycodePanels[mapName], border=sideBorder, flag=wx.LEFT)

            self.sizer.Add((1,15))
            _ = wx.StaticText(self, -1, "Add new keycode:")
            self.sizer.Add(_, border=sideBorder, flag=wx.LEFT)

            self.sizer.Add((1, 5))

            newKeycodeSizer = wx.BoxSizer(wx.HORIZONTAL)
            keycodeLabel = wx.StaticText(self, -1, "Name:")
            self.newKeycodeCtrls[mapName] = wx.TextCtrl(self, -1, "", size=(100, 27))
            scancodeLabel = wx.StaticText(self, -1, "Value:")
            self.newScancodeCtrls[mapName] = wx.TextCtrl(self, -1, "", size=(50, 27))
            self.newScancodeCtrls[mapName].Bind(wx.EVT_CHAR, self.onScancodeChar)
            buttonID = wx.NewId()
            self.addKeycodeButtons[buttonID] = mapName
            self.button = wx.Button(self, id=buttonID, label="Add")
            self.button.Bind(wx.EVT_BUTTON, self.onAddKeycode)
            newKeycodeSizer.Add(keycodeLabel, flag=wx.ALIGN_BOTTOM)
            newKeycodeSizer.Add(self.newKeycodeCtrls[mapName], border=5, flag=wx.LEFT)
            newKeycodeSizer.Add(scancodeLabel, border=15, flag=wx.LEFT | wx.ALIGN_BOTTOM)
            newKeycodeSizer.Add(self.newScancodeCtrls[mapName], border=5, flag=wx.LEFT)

            self.sizer.Add(newKeycodeSizer, border=sideBorder, flag=wx.LEFT)
            self.sizer.Add((1,5))
            self.sizer.Add(self.button, border=sideBorder, flag=wx.LEFT)
        # self.nameValueCtrls = {}
        # for serialNo in config.DEVICE_KEYCODES.keys():
        #     self.nameValueCtrls[serialNo] = {}
        #     for name, value in config.DEVICE_KEYCODES[serialNo].items():
        #         self.keycodesSizers[mapName].Add(wx.StaticText(self, -1, name + ":", (20,20)))
        #         ctrl = wx.TextCtrl(self, -1, value, size=(300, 27))
        #         self.keycodesSizers[mapName].Add(ctrl)
        #         self.nameValueCtrls[serialNo][name] = ctrl

        # The parameters:
        # 1, wx.EXPAND | wx.ALL, 20
        # cause the buttons to be moved close to the bottom of the dialog.
        #sizer.Add(self.keycodesSizers[mapName], 1, wx.EXPAND | wx.ALL, 20)

        buttonSizer = wx.BoxSizer(wx.VERTICAL)
        
        # Using an id of wx.ID_CLOSE causes the button to be placed
        # in the top left corner when no pos is given. Using
        # wx.ID_APPLY instead, f.e., allows it to appear in the
        # bottom right.
        self.closeButton = wx.Button(self, id=wx.ID_CLOSE)
        self.closeButton.Bind(wx.EVT_BUTTON, self.dialog.onClose)
        # It doesn't matter which order I add them in; Apply always appears
        # to the right of Cancel.
        buttonSizer.Add(self.closeButton, 1, wx.RIGHT)
        self.sizer.Add(buttonSizer, 0, border=sideBorder, flag=wx.RIGHT | wx.BOTTOM | wx.ALIGN_RIGHT)
        self.SetSizer(self.sizer)


    def onAddKeycode(self, event):
        mapName = self.addKeycodeButtons[event.GetId()]
        keycode = self.newKeycodeCtrls[mapName].GetValue()
        self.newKeycodeCtrls[mapName].SetValue('')
        self.keycodesSizers[mapName].Add(wx.StaticText(self.keycodePanels[mapName], -1, keycode + ":"), 
                                         border=5, flag=wx.TOP | wx.ALIGN_BOTTOM | wx.ALIGN_RIGHT)
        value = self.newScancodeCtrls[mapName].GetValue()
        self.newScancodeCtrls[mapName].SetValue('')
        ctrl = wx.TextCtrl(self.keycodePanels[mapName], -1, value, size=(50, 27))
        self.keycodesSizers[mapName].Add(ctrl, border=5, flag=wx.LEFT | wx.TOP)
        self.scancodeCtrls[mapName][keycode] = ctrl
        self.scancodeCtrlIDToMapNameKeycode[ctrl.Id] = (mapName, keycode)
        self.Layout()
        # Set the focus to the new control to scroll the window to
        # where it was added so that the user can see it, and then to
        # the keycode ctrl in case he wants to add another.
        ctrl.SetFocus()
        self.newKeycodeCtrls[mapName].SetFocus()
        config.keycodes[mapName][keycode] = value
        self.focusedMapKeycodePairs.append((mapName, keycode))


    def onDeleteKeycode(self, event):
        mapName, keycodeToDelete = self.deleteButtonIDToMapNameKeycode[event.GetId()]
        del config.keycodes[mapName][keycodeToDelete]
        del self.scancodeCtrls[mapName][keycodeToDelete]
        
        keycodeScancodePairs = []
        for keycode in sorted(self.scancodeCtrls[mapName].keys()):
            if keycode == keycodeToDelete:
                continue
            scancode = self.scancodeCtrls[mapName][keycode].GetValue()
            keycodeScancodePairs.append((keycode, scancode))
            
        self.keycodesSizers[mapName].Clear(True)

        for keycode, scancode in keycodeScancodePairs:
            keycodeLabel = wx.StaticText(self.keycodePanels[mapName], -1, keycode + ":")
            self.keycodesSizers[mapName].Add(keycodeLabel, border=5, flag=wx.TOP | wx.ALIGN_BOTTOM | wx.ALIGN_RIGHT)
            ctrlID = wx.NewId()
            ctrl = wx.TextCtrl(self.keycodePanels[mapName], ctrlID, scancode, size=(50, 27))
            ctrl.Bind(wx.EVT_SET_FOCUS, self.onScancodeCtrlFocus)
            ctrl.Bind(wx.EVT_CHAR, self.onScancodeChar)
            # Don't bother clearing the old values.
            self.scancodeCtrlIDToMapNameKeycode[ctrlID] = (mapName, keycode)
            self.keycodesSizers[mapName].Add(ctrl, border=5, flag=wx.RIGHT | wx.TOP)
            self.scancodeCtrls[mapName][keycode] = ctrl
            buttonID = wx.NewId()
            button = wx.Button(self.keycodePanels[mapName], buttonID, label="Delete", style=wx.BU_EXACTFIT)
            self.deleteButtonIDToMapNameKeycode[buttonID] = (mapName, keycode)
            self.keycodesSizers[mapName].Add(button, border=10, flag=wx.ALIGN_BOTTOM | wx.LEFT)
            button.Bind(wx.EVT_BUTTON, self.onDeleteKeycode)

        self.keycodesSizers[mapName].Fit(self.keycodePanels[mapName])
        self.keycodesSizers[mapName].Layout()
        self.sizer.Layout()
        

    def onScancodeChar(self, event):
        # From wxPython/demo/Validator.py.
        key = event.GetKeyCode()
        if key < wx.WXK_SPACE or key == wx.WXK_DELETE or key > 255:
            event.Skip()
            return

        if chr(key) in string.digits:
            event.Skip()
            return


    def onScancodeCtrlFocus(self, event):
        mapName, keycode = self.scancodeCtrlIDToMapNameKeycode[event.GetId()]
        self.focusedMapKeycodePairs.append((mapName, keycode))


    def onLeaveScancodeCtrl(self, event):
        mapName, keycode = self.scancodeCtrlIDToMapNameKeycode[event.GetId()]
        scancode = self.scancodeCtrls[mapName][keycode].GetValue()
        try:
            scancode = int(scancode)
        except:
            # This should not be necessary because the onScancodeChar()
            # method prevents non-digit chars from being entered.
            self.stopAnyClose = True
            buttonStyle = wx.OK
            dialogStyle = wx.ICON_ERROR
            dlg = wx.MessageDialog(self,
                                   "Please enter an integer for " + keycode + ".",
                                   "Error",
                                   buttonStyle | dialogStyle)
            dlg.ShowModal()
            dlg.Destroy()
            return
    
        mapName, keycode = self.scancodeCtrlIDToMapNameKeycode[event.GetId()]
        config.keycodes[mapName][keycode] = scancode

        
class DeviceGUIAssembly(wx.Panel):
    def __init__(self, appFrame, device):
        wx.Panel.__init__(self, appFrame, -1, style=wx.EXPAND)        
        chinSizer = wx.BoxSizer(wx.HORIZONTAL)

        self.deviceWindow = DeviceWindow(appFrame, self, chinSizer, -1)
        self.device = device
        self.deviceWindow.device = device
        self.device.setWindow(self.deviceWindow, 'screenshot')

        self.devicePanelSizer = wx.BoxSizer(wx.VERTICAL)
        self.devicePanelSizer.Add(self.deviceWindow)
        self.devicePanelSizer.Add(chinSizer)
        # "Note that this function [SetSizer] will also call SetAutoLayout implicitly with a True
        # parameter if the sizer is non-None"
        self.SetSizer(self.devicePanelSizer)
        #self.devicePanel.SetAutoLayout(True)
        self.devicePanelSizer.Fit(self)


    def OnLeftMouseDown(self, event):
        dprint('DeviceGUIAssembly: onleftmousedown')

    def OnLeftMouseUp(self, event):
        dprint('DeviceGUIAssembly: onleftmouseup')

    def OnMouseMove(self, event):
        dprint('DeviceGUIAssembly: onmousemove')

    def OnLeftDClick(self, event):
        dprint('DeviceGUIAssembly: onleftmousedclick')


    def onKillFocus(self, _):
        dprint("gui assy on kill focus")
        self.hideFromMouseClicks()


    def onSetFocus(self, _):
        dprint("gui assy on set focus")
        self.unhideFromMouseClicks()


    def hideFromMouseClicks(self):
        dprint("hiding from mouse clicks")
        self.deviceWindow.hideFromMouseClicks()


    def unhideFromMouseClicks(self):
        dprint("UN-hiding from mouse clicks")
        self.deviceWindow.unhideFromMouseClicks()


class Device(object):
    @staticmethod
    def makeDevice(serialNo=None, mgr=None, vncPort=None, width=None, height=None, chinBarHeight=None, xScale=None,
                   yScale=None, xIntercept=None, yIntercept=None, orientation=None, chinBarImageString=None, 
                   maxADBCommandLength=None, downText=None, upText=None, repeaterText=None, 
                   repeaterPostfixText=None, screenshotMethod=None, usingAltSerialNo=None,
                   noGUI=False, downUpText=None):
        device = Device()
        device.serialNo=serialNo
        device.mgr= mgr
        device.vncPort= vncPort
        device.width= width
        device.height= height
        device.chinBarHeight = chinBarHeight
        device.xScale= xScale
        device.yScale= yScale
        device.xIntercept = xIntercept
        device.yIntercept = yIntercept
#        device.minX= minX
#        device.minY= minY
        device.orientation = orientation
        device.chinBarImageString= chinBarImageString
        device.screenshotMethod = screenshotMethod
        device.usingAltSerialNo = usingAltSerialNo
        device.noGUI = noGUI

        device.keycodesToSend = []
        
        device.window = None
        device.cameraProcess = None

        device.lastLeftDownX = None
        device.lastLeftDownY = None

        # Only one keycode map is supported right now. XXX support more.
        device.keycodeMap = 'Default'
        device.dt = adbTransport.ADBTransport(device.serialNo if not usingAltSerialNo else "", 
                                              device=device, noGUI=noGUI)
        device.dt.maxADBCommandLength = maxADBCommandLength
        
        if device.xScale and device.yScale:
            device.internalDragStepSize = min(device.xScale * constants.DRAG_STEP_SIZE_IN_PIXELS,
                                              device.yScale * constants.DRAG_STEP_SIZE_IN_PIXELS)
        # Error values returned are ignored for now. Is there any chance they'd be not-okay? XXX
        if downText and upText:
            eDown, eUp, eRepeater, ePostfix = device.dt.setText(downText, upText, repeaterText, repeaterPostfixText, 
                                                                downUpText)

        device.sentFirstDown = False
        device.sentFirstUp = False
        return device


    def identifyProperties(self, serialNo, mgr, vncPort, configParser, usingAltSerialNo=False, 
                           noGUI=False):
        self.serialNo = serialNo
        self.mgr = mgr
        self.vncPort = vncPort
        self.usingAltSerialNo = usingAltSerialNo
        self.noGUI = noGUI

        self.keycodesToSend = []
        # self.imageString includes the chin bar, if any.
        self.imageString = None
        self.imageFilename = None
        # self.imageWidth and self.imageHeight are populated by self.updateImageSize().

        # Set by setWindow().
        self.window = None
        self.cameraProcess = None
        
        self.lastLeftDownX = None
        self.lastLeftDownY = None

        # screenshotMethod is populated from a configuration file later in this method.
        self.screenshotMethod = None

        self.orientation = constants.UNKNOWN_SCREEN_ORIENTATION
        
        self.keycodeMap = config.serialNumberToKeycodeMap.get(self.serialNo, 'Default')

        self.dt = adbTransport.ADBTransport(self.serialNo if not usingAltSerialNo else "", device=self, 
                                            noGUI=noGUI)

        self.sentFirstDown = False
        self.sentFirstUp = False

        data = self.mgr.recorder.getDevice(serialNo)
        if data and data[2]:
            self.dt.maxADBCommandLength = data[2]
        else:
            self.dt.maxADBCommandLength = constants.DEFAULT_MAX_ADB_COMMAND_LENGTH

        (foundX, foundY, foundPixelDims, minX, maxX, minY, maxY, 
         # self.height is the LCD height; it doesn't include the chin bar height
         self.width, lcdHeight, dumpsysWindowOutput), success = screenProperties.getScreenDimensions(self)

        if constants.STREAK_DEBUG:
            foundX = True; foundY = True; foundPixelDims = True;
            minX = 0; maxX = 800; minY = 0; maxY = 480;
            self.width = 800; lcdHeight = 480; dumpsysWindowOutput = ""

        if not success:
            msg = "An attempt to communicate with the device has failed. This is one procedure that often "
            msg += "re-establishes communication with Android devices:"
            msg += "\n\n"
            msg += constants.RECONNECT_INSTRUCTIONS
            buttonStyle = wx.OK
            dialogStyle = wx.ICON_ERROR
            dlg = wx.MessageDialog(None,
                                   msg,
                                   "ADB Connection Error",
                                   buttonStyle | dialogStyle)
            dlg.ShowModal()
            dlg.Destroy()
            return False

        (downText, upText, downRepeaterText, repeaterPostfixText, downUpText, xScale, xIntercept, 
         yScale, yIntercept, width_, lcdHeight_), success = \
            utils.getPropertiesFromConfigFile(self.serialNo)

        # In case they weren't successfully retrieved from the config file.
        self.width = width_ or self.width
        lcdHeight = lcdHeight_ or lcdHeight

        eDown, eUp = '', ''
        saveConfig = False
        try:
            model = configParser.get(serialNo, 'model')
        except:
            model, e = self.dt.sendCommand("shell getprop ro.product.model")
            try:
                configParser.set(serialNo, 'model', model)
            except ConfigParser.NoSectionError:
                configParser.add_section(serialNo)
                configParser.set(serialNo, 'model', model)
            saveConfig = True
        try:
            make = configParser.get(serialNo, 'make')
        except:
            make, e = self.dt.sendCommand("shell getprop ro.product.manufacturer")
            configParser.set(serialNo, 'make', make)
            saveConfig = True
        if saveConfig:
            configPath = os.path.join(getUserDocumentsPath(), constants.APP_DIR,
                                      constants.APPLICATION_NAME_REGULAR_CASE + '.cfg')
            with open(configPath, 'w') as fp:
                configParser.write(fp)

        if success:
            self.xScale = xScale
            self.xIntercept = xIntercept
            self.yScale = yScale
            self.yIntercept = yIntercept
            # todo prevent infinite looping when no more reductions can be made
            eDown, eUp, eRepeater, ePostfix = self.dt.setText(downText, upText, downRepeaterText, repeaterPostfixText, 
                                                              downUpText)

            # This is a guess; it returns '2.2' when run against my Droid 2:
            androidVersion = self.dt.sendCommand("shell getprop ro.build.version.release")

            # todo check make and model; do we already know the sendevent configuration?

        if not success or eDown != '' or eUp != '':
            # "shell getevent -v 63"
            geV63 = (chr(115) + chr(104) + chr(101) + chr(108) + chr(108) + 
                     chr(32) + chr(103) + chr(101) + chr(116) + chr(101) + 
                     chr(118) + chr(101) + chr(110) + chr(116) + chr(32) + 
                     chr(45) + chr(118) + chr(32) + chr(54) + chr(51))
            _deviceData = {}
            _deviceData[self.serialNo] = {'width':self.width, 'totalHeight':lcdHeight + 0,
                                          'chinBarHeight':0, 'chinBarImageString':"",
                                          'orientation':self.orientation, 
                                          'maxADBCommandLength':constants.DEFAULT_MAX_ADB_COMMAND_LENGTH,
                                          'usingAltSerialNo':self.usingAltSerialNo}
            resultsQueue = multiprocessing.Queue()
            controlQueue = multiprocessing.Queue()

            # This is for getting information from Bali:
            getpropOutput, getpropError = self.dt.sendCommand("shell getprop")
            with open(os.path.join(globals_.getUserDocumentsPath(), 
                                   constants.APP_DIR, 'getprop.' + self.serialNo), 'w') as fp:
                fp.write(getpropOutput)
                fp.write('\n\n\n')
                fp.write(getpropError)

            # 'adb shell getevent' doesn't terminate on its own
            dprint('before sendeventprocess for geV63')
            utils.SendeventProcess(geV63, _deviceData, resultsQueue, controlQueue, config.adbPath)
            dprint('after sendeventprocess for geV63')
            time.sleep(5)
            controlQueue.put('stop')
            try:
                geOutput, error = resultsQueue.get(block=True, timeout=10) 
            except Exception, e:
                return False
            if not geOutput:
                return False
            geOutput = geOutput.split("add device")
            eventSRE = re.compile("(/dev/input/event[0-9]+)")
            potentialScreenEventPaths = []
            for deviceOutput in geOutput:
                if ("SYN" in deviceOutput and "KEY" in deviceOutput and "ABS" in deviceOutput):
                    m = eventSRE.search(deviceOutput)
                    if m:
                        potentialScreenEventPaths.append(m.group())
                    
            if constants.STREAK_DEBUG:
                potentialScreenEventPaths = ['/dev/input/event2']

            msg = "With your help, the tool will determine how to send touch events to your phone or tablet. Start "
            msg += "by setting your device down on a flat surface with the USB cable still connected. After you've "
            msg += "set it down, don't touch it."
            msg += "\n\n"
            buttonStyle = wx.OK
            dlg = wx.MessageDialog(None,
                                   msg,
                                   "Configuring Touch Events",
                                   buttonStyle)
            dlg.ShowModal()
            dlg.Destroy()


            touchEventIdentificationSuccess = False
            touchEventIdentificationIterations = 1
            # This is True when the code realizes that touch event identification can't be done.
            touchEventIdentificationImpossible = False
            while (not touchEventIdentificationSuccess and 
                   touchEventIdentificationIterations < 3 and 
                   not touchEventIdentificationImpossible):

                if touchEventIdentificationIterations > 1:
                    msg = "Something didn't go right. Let's try again."
                    dlg = wx.MessageDialog(None,
                                           msg,
                                           "Error",
                                           wx.OK)
                    dlg.ShowModal()

                iterations = 0
                upperRightEventPathData = []
                while iterations < 2 and not upperRightEventPathData:
                    title = "Tap the Upper Right Corner"
                    if iterations > 0:
                        msg = "Something didn't go right. Please try again. Tap the upper right corner of your "
                        msg += "device's touchscreen with your finger, just inside the screen boundaries. Press "
                        msg += "OK when you're done."
                    else:
                        msg = "Now, tap the upper right corner of your device's touchscreen with your finger, just "
                        msg += "inside the screen boundaries. Don't tap the touchscreen anywhere else or press "
                        msg += "anything else on the device. Press OK when you're done."
                    upperRightEventPathData = utils.getEventPathData(self, potentialScreenEventPaths, 
                                                                     lcdHeight, title, msg)
                    iterations += 1

                if not upperRightEventPathData:
                    msg = ("The tool was unable to identify how to configure communication with the " + 
                           "touchscreen. Please contact " + constants.FEEDBACK_EMAIL_HANDLE + "@" +
                           constants.EMAIL_DOMAIN_NAME + ".")
                    dlg = wx.MessageDialog(None,
                                           msg,
                                           "Error",
                                           wx.OK)
                    dlg.ShowModal()
                    return False
                # Does the getevent output show a pattern repeated again and again and nothing
                # else, as with Droid 2, or does it show a pattern repeated at most once with
                # a bunch of control data, as with Streak?
                eventPathsHavingRepeatedSequences = utils.getEventPathsHavingRepeatedSequences(upperRightEventPathData)

                iterations = 0
                lowerLeftEventPathData = []
                while iterations < 2 and not lowerLeftEventPathData:
                    if not eventPathsHavingRepeatedSequences:
                        # Streak-style
                        title = "Press and Hold the Lower Left Corner"
                        if iterations > 0:
                            msg = ("Something didn't go right (and it may not have been your fault). " +
                                   "Please try again. Press and hold the lower " + 
                                   "left corner, just inside the screen boundaries, for about 3 " +
                                   "seconds. Press OK when you're done.")
                        else:
                            msg = ("Now, press the lower left corner of the touchscreen with your finger, " + 
                                   "just inside the screen boundaries, for about 3 seconds. Lift your " + 
                                   "finger and then press OK after you've lifted your finger.")
                    else:
                        # Droid 2-style
                        title = "Tap the Lower Left Corner"
                        if iterations > 0:
                            msg = ("Something didn't go right (and it may not have been your fault). "
                                   "Please try again. With the phone still " +
                                   "lying on the flat surface, tap the lower left corner of your device's " +
                                   "touchscreen, just inside the screen boundaries. Press OK when you're done.")
                        else:
                            msg = ("Okay. Now, with the phone still lying on the flat surface, tap the " +
                                   "lower left corner of your device's touchscreen, just inside the screen " +
                                   "boundaries. Press OK when you're done.")
                    lowerLeftEventPathData = utils.getEventPathData(self, 
                                                                    potentialScreenEventPaths, 
                                                                    lcdHeight, title, msg)
                    iterations += 1

                if not lowerLeftEventPathData:
                    msg = ("The tool was unable to identify how to configure communication with the " +
                           "touchscreen. Please contact " + constants.FEEDBACK_EMAIL_HANDLE + "@" +
                           constants.EMAIL_DOMAIN_NAME + ".")
                    dlg = wx.MessageDialog(None,
                                           msg,
                                           "Error",
                                           wx.OK)
                    dlg.ShowModal()
                    return False

                if len(lowerLeftEventPathData) > 0 and len(lowerLeftEventPathData[0]) > 0:
                    eventPath = lowerLeftEventPathData[0][0]
                    (xc1c2, yc1c2, downText, downRepeaterText, postfixText, upText, downUpText, xOrigin, 
                     yOrigin, keyGroups, success) = \
                        utils.identifyDownUpTextFromStreakStyleData(self, upperRightEventPathData, 
                                                                    lowerLeftEventPathData, lcdHeight, 
                                                                    minX, maxX, minY, maxY)
                else:
                    success = False
                if success:
                    #while not touchEventIdentificationImpossible:
                    eDown, eUp, eRepeater, ePostfix = self.dt.setText(downText, upText, downRepeaterText, 
                                                                      postfixText, downUpText)
                    if not touchEventIdentificationImpossible:
                        touchEventIdentificationSuccess = True

                touchEventIdentificationIterations += 1
            # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
            if not touchEventIdentificationSuccess:
                return False

            if not touchEventIdentificationImpossible:
                utils.saveDownUpTextToConfigFile(self.serialNo, downText, downRepeaterText, repeaterPostfixText,
                                                 upText, downUpText, self.xScale, self.xIntercept, self.yScale,
                                                 self.yIntercept, configParser=configParser)


        # Sending 'BACK' here serves to get the screen back to HOME after
        # adbTransport.py:setText() has pressed down() and then up().
        # On Droid 2, Android 2.3.3, sending just 'HOME' causes the Voice
        # Commands app to be launched.
        self.dt.enterKeycodes(['BACK', 'BACK', 'BACK', 'BACK'])

        storedVirtualKeys = self.mgr.recorder.getVirtualKeys(serialNo)


        (self.chinBarHeight, self.chinBarImageString, virtualKeys), success = \
            screenProperties.getChinBarProperties(self, foundX, foundY, foundPixelDims, minX, maxX,
                                                  self.xScale, minY, maxY, self.yScale, self.width,
                                                  lcdHeight, dumpsysWindowOutput, storedVirtualKeys)
        self.height = lcdHeight + self.chinBarHeight
        self.mgr.recorder.addDeviceIfNecessary(self.serialNo, self.width,
                                               self.height - self.chinBarHeight,
                                               self.dt.maxADBCommandLength)
        if virtualKeys != storedVirtualKeys and virtualKeys != {}:
            self.mgr.recorder.saveVirtualKeys(self.serialNo, virtualKeys)
            
        # This populates self.imageWidth and self.imageHeight for the device
        # when the image is not being resized in a GUI (because the GUI is
        # not being run).
        self.updateImageSize()
        
        self.internalDragStepSize = min(self.xScale * constants.DRAG_STEP_SIZE_IN_PIXELS,
                                        self.yScale * constants.DRAG_STEP_SIZE_IN_PIXELS)
        try:
            self.screenshotMethod = int(configParser.get(self.serialNo, 'screen'))
        except:
            self.screenshotMethod = None
        
        return True


    def getMaxADBCommandLength(self):
        return self.dt.maxADBCommandLength


    def setWindow(self, window, camera):
        self.window = window
        # ??? I think I may have handled this: make recording start on button click b/c 
        # recording while replaying is causing the failure "database is locked"
        if camera == 'vnc':
            self.cameraProcess = VNCProcess(self.mgr, self, self.window, self.mgr.sessionID, self.vncPort, 
                                            self.serialNo, self.mgr.viewerToGUISocketPort, self.chinBarHeight,
                                            self.chinBarImageString)
        elif camera == 'screenshot':
            dprint("Starting ScreenshotProcess")
            self.cameraProcess = ScreenshotProcess(self.mgr, self, self.window, self.mgr.sessionID, 
                                                   self.vncPort, self.serialNo, self.width, 
                                                   self.height - self.chinBarHeight, self.chinBarHeight, 
                                                   self.chinBarImageString, self.screenshotMethod,
                                                   self.mgr.monkeyrunnerPath)
            if self.screenshotMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER:
                dlg = wx.MessageDialog(None,
                                       "The tool will now start the process to grab screen images. Please wait.",
                                       "Please wait",
                                       wx.OK)
                dlg.ShowModal()
                dlg.Destroy()
                # This is a hack to get monkeyrunner to allow other adb connections while it runs.
                # TODO This sleep time prolly doesn't have to be a fixed constant; we could instead
                # look for the files written by monkeyrunner.
                time.sleep(10)
                self.dt.enterKeycodes(['HOME'])
                time.sleep(10)

        else:
            raise Exception("unrecognized camera specified")


    def getImageString(self):
        if self.noGUI:
            return self.cameraProcess.imageString
        return self.imageString


    def _getVirtualKeyKeycodes(self, virtualKeys):
        # The keys have to be tapped in order to appear in 'adb shell dumpsys window'
        # output.
        for key in virtualKeys:
            x = (virtualKeys[key]['hitLeft'] + virtualKeys[key]['hitRight']) / 2
            y = (virtualKeys[key]['hitTop'] + virtualKeys[key]['hitBottom']) / 2
            
            self.dt.down(x, y)
            self.dt.up(x, y)

        o, e = self.dt.sendCommand("shell dumpsys window", waitForOutput=True)
        if e:
            return

        # This if for getting info fr/ Bali:
        with open(os.path.join(globals_.getUserDocumentsPath(), 
                               constants.APP_DIR, 'dumpsys_window.txt'), 'w') as fp:
            fp.write(o)

        output = o.split('\n')
        keySRE = re.compile("Virtual Key #([0-9])")
        keycodeSRE = re.compile("lastKeycode=([0-9]{1,4})")
        lookingForKey = True
        lookingForLastKeycode = False
        lastKey = -1
        keysLookingFor = set(virtualKeys.keys())
        for line in output:
            if "Virtual Key #" in line:
                # Any line containing 'Virtual Key #' must be found, b/c
                # it changes the key w/ which the lastKeycode goes.
                m = keySRE.search(line)
                if m:
                    keyNumber = int(m.groups()[0])
                    if keyNumber in virtualKeys:
                        lastKey = keyNumber
                        lookingForLastKeycode = True
                    else:
                        lookingForLastKeycode = False
                else:
                    # Being cautious
                    lookingForLastKeycode = False
            elif lookingForLastKeycode and "lastKeycode=" in line:
                m = keycodeSRE.search(line)
                if m:
                    keycode = int(m.groups()[0])
                    virtualKeys[lastKey]['lastKeycode'] = keycode
                    keysLookingFor = keysLookingFor - set([lastKey])
                    if keysLookingFor == set([]):
                        break
                    lookingForLastKeycode = False
                else:
                    lookingForLastKeycode = False


    def getScreenOrientation(self):
        o, e = self.dt.sendCommand("shell dumpsys window", waitForOutput=True)
        if type(o) != str or len(o) == 0:
            self.orientation = constants.UNKNOWN_SCREEN_ORIENTATION
            return self.orientation, False            
        m = constants.ORIENTATION_SRE.search(o)
        if not m:
            self.orientation = constants.UNKNOWN_SCREEN_ORIENTATION
            return self.orientation, False
        try:
            self.orientation = int(m.groups()[0])
        except Exception, e:
            self.orientation = constants.UNKNOWN_SCREEN_ORIENTATION            
            return self.orientation, False
        return self.orientation, True


    def updateImageSize(self, width=None, height=None):
        # The image displayed in the GUI is the image retrieved from the device
        # scaled down to fit in the GUI.
        if width is None:
            self.imageWidth = self.width
            self.imageHeight = self.height
        else:
            self.imageWidth = width
            self.imageHeight = height


    def startingExplore(self):
        pass


    def startingPause(self):
        pass


    def startingPlayback(self, testName, indexInSuite):
        dprint("startingPlayback, testName", testName)
        self.cameraProcess.setRecordOrPlayTestName(testName, indexInSuite)


    def startingRecord(self, testName):
        self.cameraProcess.setRecordOrPlayTestName(testName)


    def finishingPlayback(self):
        self.cameraProcess.setRecordOrPlayTestName(None, -1)

        
    def _copyImageFileIfNecessary(self):
        return self.imageFilename

        # filename = self.imageFilename
        # if self.mgr and self.mgr.isRecording:
        #     if not self.imageFilename.startswith('record'):
        #         # The click has been made so soon after starting recording
        #         # that the image was written before recording started.
        #         filename = self.imageFilename[:-3] + str(time.time()) + '.png'
        #         newPath = os.path.join('tests', self.mgr.sessionID, filename)
        #         shutil.copy(self.imageFilename, newPath)
        #         if os.path.getsize(newPath) == 0:
        #             dprint('ERROR FILE SIZE IS ZERO, DEBUG HERE!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
        #             bdbg()
        # return filename


    def fixMonkeyRunner(self):
        # x and y are physical screen coordinates, not coordinates internal
        #to the device nor coordinates within the image displayed in the GUI,
        # which can vary in size.
        # Key events are sent after a delay. Send them now so that their
        # sequence w.r.t. clicks is correct.
        internalX = int(0 * self.xScale + self.xIntercept)
        internalY = int(0 * self.yScale + self.yIntercept)
        self.dt.fixMonkeyRunner(internalX, internalY)


    def down(self, x, y):
        # x and y are physical screen coordinates, not coordinates internal
        #to the device nor coordinates within the image displayed in the GUI,
        # which can vary in size.
        if x > self.width or y > self.height:
            # Click outside of device screen. 
            return
        
        dprint('Device.down() 1')
        # Key events are sent after a delay. Send them now so that their
        # sequence w.r.t. clicks is correct.
        self.sendKeyEvents()
        dprint('Device.down() 2')

        self.lastLeftDownX = x
        self.lastLeftDownY = y

        globals_.moveLogger.debug("down(%d, %d)", x, y)
                
        internalX = int(x * self.xScale + self.xIntercept)
        internalY = int(y * self.yScale + self.yIntercept)

        dprint('Device.down() 3')
        filename = self._copyImageFileIfNecessary()
        dprint('Device.down() 4')
        if self.screenshotMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER and not self.sentFirstDown:
            self.dt.downWithKill(internalX, internalY)
            self.sentFirstDown = True
        else:
            self.dt.down(internalX, internalY)
        dprint('Device.down() 5')

        if self.mgr and self.mgr.isRecording:
            self.mgr.recorder.recordClick(self.mgr.sessionID, self.serialNo, constants.LEFT_DOWN_CLICK,
                                          x, y, self.width, self.height, self.chinBarHeight,
                                          filename, time.time())


    def downUp(self, x, y):
        # x and y are physical screen coordinates, not coordinates internal
        #to the device nor coordinates within the image displayed in the GUI,
        # which can vary in size.
        if x > self.width or y > self.height:
            # Click outside of device screen. 
            return
        
        # Key events are sent after a delay. Send them now so that their
        # sequence w.r.t. clicks is correct.
        self.sendKeyEvents()

        self.lastLeftDownX = x
        self.lastLeftDownY = y

        globals_.moveLogger.debug("downUp(%d, %d)", x, y)
                
        internalX = int(x * self.xScale + self.xIntercept)
        internalY = int(y * self.yScale + self.yIntercept)

        filename = self._copyImageFileIfNecessary()

        if self.screenshotMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER:
            # With Android SDK 15, sending the down command separately from the up caused taps to be interpreted
            # as long presses sometimes, b/c, somehow, running monkeyrunner simultaneously would cause commands
            # to take a long time to complete. downUpWithKill() is preferred over downUp() b/c the kill is
            # used to end these long-running processes.
            self.dt.downUpWithKill(internalX, internalY)
        else:
            self.dt.downUp(internalX, internalY)

        if self.mgr and self.mgr.isRecording:
            self.mgr.recorder.recordClick(self.mgr.sessionID, self.serialNo, constants.LEFT_DOWN_CLICK,
                                          x, y, self.width, self.height, self.chinBarHeight,
                                          filename, time.time())


    def downRepeater(self, x, y):
        # x and y are physical screen coordinates, not coordinates internal
        #to the device nor coordinates within the image displayed in the GUI,
        # which can vary in size.
        if x > self.width or y > self.height:
            # Click outside of device screen. 
            return
        
        # Key events are sent after a delay. Send them now so that their
        # sequence w.r.t. clicks is correct.
        self.sendKeyEvents()

        self.lastLeftDownX = x
        self.lastLeftDownY = y

        globals_.moveLogger.debug("down(%d, %d)", x, y)
                
        internalX = int(x * self.xScale + self.xIntercept)
        internalY = int(y * self.yScale + self.yIntercept)

        filename = self._copyImageFileIfNecessary()

        if self.screenshotMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER:
            self.dt.downRepeaterWithKill(internalX, internalY)
        else:
            self.dt.downRepeater(internalX, internalY)

        if self.mgr and self.mgr.isRecording:
            self.mgr.recorder.recordClick(self.mgr.sessionID, self.serialNo, constants.LEFT_DOWN_CLICK,
                                          x, y, self.width, self.height, self.chinBarHeight,
                                          filename, time.time())


    def repeaterPostfix(self, x, y):
        # This is something required by the nature of the device. It doesn't
        # correspond to a touch event performed by the user. So, we don't
        # record it as a click.

        # x and y are physical screen coordinates, not coordinates internal
        #to the device nor coordinates within the image displayed in the GUI,
        # which can vary in size.
        if x > self.width or y > self.height:
            # Click outside of device screen. 
            return
                
        internalX = int(x * self.xScale + self.xIntercept)
        internalY = int(y * self.yScale + self.yIntercept)

        if self.screenshotMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER:
            self.dt.repeaterPostfixWithKill(internalX, internalY)
        else:
            self.dt.repeaterPostfix(internalX, internalY)


    def up(self, x, y):
        # x and y are physical screen coordinates, not coordinates internal
        # to the device nor coordinates within the image displayed in the GUI,
        # which can vary in size.
        if x > self.width or y > self.height:
            return

        # Get the time before doing an operation that may take considerable time.
        timeOfClick = time.time()

        self.sendKeyEvents()

        if self.lastLeftDownX:
            internalX = int(x * self.xScale + self.xIntercept)
            internalY = int(y * self.yScale + self.yIntercept)   
            if self.screenshotMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER and not self.sentFirstUp:
                self.dt.upWithKill(internalX, internalY)
                self.sentFirstUp = True
            else:
                self.dt.up(internalX, internalY)

        filename = self._copyImageFileIfNecessary()

        self.lastLeftDownX = None
        self.lastLeftDownY = None

        if self.mgr and self.mgr.isRecording:
            # While a more recent image may have been pulled from the phone and exist in the filesystem,
            # the duration between the displaying of an image in the window and the assignment to the
            # device instance's imageFilename member should be very small. The update event is from the
            # camera process to the device window, not from the device window to the device.

            dprint("device.up(), self.imageFilename:", self.imageFilename)
            self.mgr.recorder.recordClick(self.mgr.sessionID, self.serialNo, constants.LEFT_UP_CLICK,
                                          x, y, self.width, self.height, self.chinBarHeight,
                                          filename, timeOfClick)


    def move(self, x, y):
        # x and y are physical screen coordinates, not coordinates internal
        # to the device nor coordinates within the image displayed in the GUI,
        # which can vary in size.
        if x > self.width or y > self.height:
            return
        
        # Get the time before doing an operation that may take considerable time.
        timeOfClick = time.time()

        self.sendKeyEvents()

        self.leftMouseDragging = True

        internalX = int(x * self.xScale + self.xIntercept)
        internalY = int(y * self.yScale + self.yIntercept)

        if self.screenshotMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER:
            self.dt.downWithKill(internalX, internalY)
        else:
            self.dt.down(internalX, internalY)

        filename = self._copyImageFileIfNecessary()

        if self.mgr and self.mgr.isRecording:       
            self.mgr.recorder.recordClick(self.mgr.sessionID, self.serialNo, constants.LEFT_MOVE,
                                          x, y, self.width, self.height, self.chinBarHeight,
                                          filename, timeOfClick)


    def drag(self, x, y, newX, newY):
        # x and y are physical screen coordinates, not coordinates internal
        # to the device nor coordinates within the image displayed in the GUI,
        # which can vary in size.
        dprint('DRAG x, y, newX, newY:', x, y, newX, newY)
        if x > self.width or y > self.height:
            return
        
        internalX = int(x * self.xScale + self.xIntercept)
        internalY = int(y * self.yScale + self.yIntercept)
        internalNewX = int(newX * self.xScale + self.xIntercept)
        internalNewY = int(newY * self.yScale + self.yIntercept)
        kill = self.screenshotMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER
        self.dt.drag(internalX, internalY, internalNewX, internalNewY, self.internalDragStepSize, kill=kill)

        filename = self._copyImageFileIfNecessary()

        if self.mgr and self.mgr.isRecording:
            self.mgr.recorder.recordClick(self.mgr.sessionID, self.serialNo, constants.LEFT_DOWN_CLICK,
                                          x, y, self.width, self.height, self.chinBarHeight,
                                          filename, time.time())
            self.mgr.recorder.recordClick(self.mgr.sessionID, self.serialNo, constants.LEFT_MOVE,
                                          newX, newY, self.width, self.height, self.chinBarHeight,
                                          filename, time.time())


    def tap(self, x, y):
        if x > self.width or y > self.height:
            return

        if self.dt.downUpText:
            self.downUp(x, y)
        else:
            self.down(x, y)
            self.up(x, y)


    def longPress(self, x, y):
        if x > self.width or y > self.height:
            return

        startTime = time.time()
        self.down(x, y)
        pressesMade = 1
        while time.time() < startTime + constants.LONG_PRESS_DELAY:
            pressesMade += 1
            self.downRepeater(x, y)
        self.repeaterPostfix(x, y)
        self.up(x, y)
        dprint("pressesMade:", pressesMade)


    def EnterText(self, keycodes):
        numericKeycodes = []
        for keycode in keycodes:
            if type(keycode) == str:
                numericKeycodes.append(-config.keycodes[self.keycodeMap][keycode])
            else:
                numericKeycodes.append(keycode)
        self.dt.enterKeycodes(numericKeycodes)
        if self.mgr and self.mgr.isRecording:
            self.mgr.recorder.recordKeyEvents(self.mgr.sessionID, self.serialNo, keycodes)


    def EnterTextAndWaitForFinish(self, keycodes):
        self.dt.enterKeycodes(keycodes)
        while self.dt.keycodeEntererThread and self.dt.keycodeEntererThread.isAlive:
            time.sleep(0.1)


    def sendKeyEvents(self):
        if self.keycodesToSend != []:
            self.EnterText(self.keycodesToSend)
            self.keycodesToSend = []
            return True
        return False


    def receiveCameraImageUpdate(self, imageFilename):
        currentPrefix = imageFilename[:imageFilename.index('.')]
        expectedPrefix = self.mgr.getExpectedPrefix(imageFilename)

        if currentPrefix != expectedPrefix:
            # getImageData() must create the filename before the file is created by FFmpeg.
            # The prefix sometimes changes (to 'record') as the file is being created;
            # that means that we must copy the file to its new name.
            dprint('recieveCamera..., imageFilename:', imageFilename)
            newImageFilename = self.mgr.getNewImageFilename(expectedPrefix, imageFilename, self.serialNo)
            if newImageFilename != imageFilename:
                # Read getNewImageFilename(); newImageFilename == imageFilename when 
                # expectedPrefix=='pause' and currentPrefix=='play'.
                try:
                    dprint("copying ", imageFilename, "to", newImageFilename)
                    shutil.copy(imageFilename, newImageFilename)
                except Exception, e:
                    dprint("receiveCameraImageUpdate, exception, e:", e)
                    bdbg()
        else:
            newImageFilename = imageFilename

        #dprint("receiveCameraImageUpdate, time:", time.time(), "imageFilename:", imageFilename)
        try:
            # I don't know why, but upon shutting down the tool, this file
            # may not exist.
            image = Image.open(newImageFilename)
            # about 0.01 seconds
            self.imageString = image.tostring()
        except Exception, e:
            dprint("receiveCameraImageUpdate, exception, e:", e)
            bdbg()

        self.setImageFilename(newImageFilename)


    def setImageFilename(self, filename):
        self.imageFilename = filename


    def isThisTextPresent(self, text, imageString='', isRE=False, maximumAcceptablePercentageDistance=0):
        #make an image of the current image string
        imageString_ = imageString or self.imageString
        screen = cv.CreateImageHeader((self.width, self.height - self.chinBarHeight), cv.IPL_DEPTH_8U, 3)
        if self.chinBarHeight > 0:
            cv.SetData(screen, imageString_[:-(self.width * self.chinBarHeight * 3)])
        else:
            cv.SetData(screen, imageString_)
        contents, success = utils.getOCRText(globals_.getUserDocumentsPath(), screen, self.width, 
                                             self.height - self.chinBarHeight, self.serialNo, box=False, 
                                             lines=False)
        dprint("isThisTextPresent, contents:", contents)
        if success == constants.SUB_EVENT_ERRORED:
            return None, success
        #look for text
        if isRE:
            sre = re.compile(text)
            return None, constants.SUB_EVENT_PASSED if sre.search(contents) is not None else constants.SUB_EVENT_FAILED
        else:
            if maximumAcceptablePercentageDistance == 0:
                if contents.find(text) != -1:
                    return None, constants.SUB_EVENT_PASSED
                else:
                    return None, constants.SUB_EVENT_ERRORED

            lenContents = len(contents)
            lenText = len(text)
            defaultMaxDistance = constants.MAX_LEVENSHTEIN_VERIFY_FN(maximumAcceptablePercentageDistance, lenText)
            for index in range(lenContents):
                if (index + lenText) < lenContents:
                    endpoint_ = (index + lenText)
                    maxDistance = defaultMaxDistance
                else:
                    endpoint_ = lenContents
                    maxDistance = constants.MAX_LEVENSHTEIN_VERIFY_FN(maximumAcceptablePercentageDistance, 
                                                                      endpoint_ - (index + 1))
                if cylevenshtein.distance(contents[index:endpoint_], text) <= maxDistance:
                    return None, constants.SUB_EVENT_PASSED
            return None, constants.SUB_EVENT_FAILED


    def addKeycodeToSend(self, keycode):
        # In the case of a special keycode, keycode is a string, such as 'HOME'.
        self.keycodesToSend.append(keycode)


    def findTargetFromInputEvent(self, inputEvent, imageString):
        if constants.DEBUGGING_SHOWING_DEVICE_SCREEN:
            utils.show3ChannelImageFromString(imageString=imageString + self.chinBarImageString, width=self.width, 
                                              height=self.height)
        return utils.findTargetFromInputEvent(self, inputEvent, imageString + self.chinBarImageString)


    def findTargetInImageFile(self, imageString, targetImagePath, characters=None, unusedArg=None):
        if constants.DEBUGGING_SHOWING_DEVICE_SCREEN:
            utils.show3ChannelImageFromString(imageString=imageString + self.chinBarImageString, width=self.width, 
                                              height=self.height)
        return utils.findTargetInImageFile(self, imageString, targetImagePath, characters)
        

class DeviceWindow(wx.Window, wx.EvtHandler):
    def __init__(self, appFrame, devicePanel, chinSizer, ID):
        wx.Window.__init__(self, devicePanel, ID)
        self.appFrame = appFrame
        self.devicePanel = devicePanel
        self.chinSizer = chinSizer

        self.buffer = wx.EmptyBitmap(337, 600)
        
        self.Bind(wx.EVT_LEFT_DOWN, self.OnLeftMouseDown)
        self.Bind(wx.EVT_LEFT_UP, self.OnLeftMouseUp)
        self.Bind(wx.EVT_LEFT_DCLICK, self.OnLeftDClick)
        self.Bind(wx.EVT_MOTION, self.OnMouseMove)

        # and the refresh event
        self.Bind(wx.EVT_PAINT, self.OnPaint)

        self.Bind(wx.EVT_CHAR, self.OnCharEvent)

        self.__set_properties()
        self.__do_layout()

        EVT_RESULT(self, ADB_ERROR_ID, self.OnADBError)
        EVT_RESULT(self, CAMERA_RESULT_ID, self.OnCameraUpdate)
        self.timeOfLastScreenUpdate = 0
        self.lastLeftDownX = None
        self.lastLeftDownY = None
        self.leftMouseDown = False
        self.leftMouseDragging = False
        self.charTimerSet = False
        self.charTimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnTimer)


    def onKillFocus(self, _):
        dprint("devicewindow on kill focus")
        self.hideFromMouseClicks()


    def onSetFocus(self, _):
        dprint("devicewindow on set focus")
        self.unhideFromMouseClicks()

        
    def setDevice(self, device):
        self.device = device

    
    def __set_properties(self):
        pass


    def __do_layout(self):
        sizer_2 = wx.BoxSizer(wx.VERTICAL)
        sizer_3 = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(sizer_2)
        sizer_2.Fit(self)
        self.Layout()


    # These are a kluge to avoid having double-clicks in the Load Test dialog
    # transferred to the device. I don't know how to do it more cleanly.
    def FakeOnLeftMouseDown(self, event):
        pass
    def FakeOnLeftMouseUp(self, event):
        pass
    def FakeOnLeftDClick(self, event):
        pass
    def FakeOnMouseMove(self, event):
        pass
    def hideFromMouseClicks(self):
        self.Bind(wx.EVT_LEFT_DOWN, self.FakeOnLeftMouseDown)
        self.Bind(wx.EVT_LEFT_UP, self.FakeOnLeftMouseUp)
        self.Bind(wx.EVT_LEFT_DCLICK, self.FakeOnLeftDClick)
        self.Bind(wx.EVT_MOTION, self.FakeOnMouseMove)
    def unhideFromMouseClicks(self):
        self.Bind(wx.EVT_LEFT_DOWN, self.OnLeftMouseDown)
        self.Bind(wx.EVT_LEFT_UP, self.OnLeftMouseUp)
        self.Bind(wx.EVT_LEFT_DCLICK, self.OnLeftDClick)
        self.Bind(wx.EVT_MOTION, self.OnMouseMove)


    def OnLeftMouseDown(self, event):
        # During a double-click, this routine is called by wx for only the first
        # down event. The callbacks run are down(), up(), doubleclick(), up().
        self.SetFocus()
        x = int(float(event.m_x) * self.device.width / self.device.imageWidth)
        y = int(float(event.m_y) * self.device.height / self.device.imageHeight)        
        globals_.moveLogger.debug("OnLeftMouseDown, x: {x}, y: {y}".format(x=x,
                                                                           y=y))
        self.device.down(x, y)

        # self.c1 = event.GetPosition()
        # if event.LeftIsDown():
        #     self.leftMouseDown = True
        #     #self.leftMouseStartPoint = (event.m_x, event.m_y)
        #     self.dt.down((event.m_x, event.m_y))


    def OnLeftMouseUp(self, event):
        # Double-clicking quickly produces two 'up's in a row, in
        # which case we don't call up again b/c we've already set
        # the coords to None.
        #        if self.HasCapture():
        #            self.ReleaseMouse()
            
        windowWidth, windowHeight = self.appFrame.GetClientSize()
        if not (windowWidth == self.device.imageWidth or windowHeight == self.device.imageHeight):
            # The appFrame has just been resized, which could be the result of double-
            # clicking on the title bar, rather than clicking on the deviceWindow.
            dprint("OnLeftMouseUp: returning early b/c suspect appFrame resize")
            return
        x = int(float(event.m_x) * self.device.width / self.device.imageWidth)
        y = int(float(event.m_y) * self.device.height / self.device.imageHeight)        
        globals_.moveLogger.debug("OnLeftMouseUp, x: {x}, y: {y}".format(x=x,
                                                                         y=y))
        self.device.up(x, y)


    def OnMouseMove(self, event):
#        if self.FindFocus() != self:
#            # This event is not intended for the device screen. The load test
#            # dialog may instead be in front of the device screen, for example.
#            return

        if event.Dragging() and event.LeftIsDown():
            windowWidth, windowHeight = self.appFrame.GetClientSize()
            if not (windowWidth == self.device.imageWidth or windowHeight == self.device.imageHeight):
                # The appFrame has just been resized, which could be the result of double-
                # clicking on the title bar, rather than clicking on the deviceWindow.
                dprint("OnMouseMove: returning early b/c suspect appFrame resize")
                return

            self.SetFocus()
            
            x = int(float(event.m_x) * self.device.width / self.device.imageWidth)
            y = int(float(event.m_y) * self.device.height / self.device.imageHeight)        
            globals_.moveLogger.debug("OnMouseMove, x: {x}, y: {y}".format(x=x,
                                                                           y=y))
            self.device.move(x, y)
            #wx.SafeYield() # works but screen is whiter
            #wx.Yield() # fails: wx._core.PyAssertionError: C++ assertion "wxAssertFailure"...
            #    ...failed at ../src/gtk/app.cpp(82) in Yield(): wxYield called recursively
            #wx.Usleep(5) # doesn't change behavior at all
            #wx.YieldIfNeeded() # doesn't change behavior at all


    def OnLeftDClick(self, event):
        dprint('DeviceWindow: onleftmousedclick')

    
    def OnADBError(self, adbError):
        dlg = wx.MessageDialog(None,
                               adbError.errorMessage,
                               "ADB Error",
                               wx.OK)
        dlg.ShowModal()
        dlg.Destroy()


    def OnCameraUpdate(self, cameraUpdate):
        # The camera update contains only the pixels from the 'LCD';
        # it does not include the chin bar depiction.
        if not os.path.exists(cameraUpdate.imageFilename):
            # The file has been moved already because the 'record' button has 
            # been un-depressed, which causes all image files for the test
            # to be moved.
            return
        #dprint("calling receiveCameraImageUpdate from OnCameraUpdate")
        self.device.receiveCameraImageUpdate(cameraUpdate.imageFilename)
        height = cameraUpdate.height + self.device.chinBarHeight
        try:
            _image = Image.open(cameraUpdate.imageFilename)
            imageString = _image.tostring()
        except Exception, e:
            dprint("error!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            bdbg()
            return
        image = cv.CreateImageHeader((cameraUpdate.width, height),
                                     cv.IPL_DEPTH_8U, 3)
        cv.SetData(image, imageString + self.device.chinBarImageString)
        
        frameWidth, frameHeight = self.appFrame.GetClientSize()

        availableWidth, availableHeight = frameWidth, frameHeight
        widthRatio = float(availableWidth) / cameraUpdate.width
        heightRatio = float(availableHeight) / height
        ratio = min(widthRatio, heightRatio)
        smallerWidth = int(ratio * cameraUpdate.width)
        smallerHeight = int(ratio * height)     

        # Refresh() causes self.OnPaint() to be called asynchronously, which
        # I determined by putting print_statements throughout this method and
        # in OnPaint(). The statements showed that this method was getting interrupted
        # by OnPaint(), not always at the same point.
        if self.device.imageWidth != smallerWidth and self.device.imageWidth != 0:
            # This call to self.devicePanel.Refresh() is the only thing that clears
            # the panel so that previous images are no longer visible. If this call
            # is commented, those images stick around so long as they aren't smaller
            # than the one currently being written. 
            # I believe that I also tried drawing an EmptyBitmap to the dc and drawing an
            # EmptyImage to the dc, both with no success.
            self.devicePanel.Refresh()

        self.SetInitialSize((availableWidth, availableHeight))

        if smallerHeight < 0 or smallerWidth < 0:
            # This can happen when the app's window has been re-sized to a tiny spec.
            # It causes an error if left to continue.
            return
        reducedScreen = cv.CreateMat(smallerHeight, smallerWidth,
                                     cv.CV_8UC3)
        cv.Resize(image, reducedScreen)
        reducedImageString = reducedScreen.tostring()
        # Pushes the chin sizer back to the device window if a resize has occurred.
        activeDeviceIndex = self.appFrame.mgr.activeDeviceIndex
        try:
            # When the dialog of setWindow() pops up but the user doesn't dismiss it, this throws
            # an exception. Ignore it for now. XXX
            devicePanel = self.appFrame.devicePanels[activeDeviceIndex]
            self.appFrame.devicePanels[activeDeviceIndex].devicePanelSizer.Fit(devicePanel)
        except Exception, e:
            return
        #dc.SetBackground( wx.Brush("White") )
        #dc.Clear()
            #image = wx.EmptyImage(self.device.imageWidth, self.device.imageHeight)
            #image.SetData('\xFF\xFF\xFF' * self.device.imageWidth * self.device.imageHeight)
            #dc.DrawBitmap(wx.BitmapFromImage(image), 0, 0)
        self.buffer = wx.EmptyBitmap(smallerWidth, smallerHeight)
        dc = wx.BufferedDC(wx.ClientDC(self), self.buffer)
        dc.BeginDrawing()
        image = wx.EmptyImage(smallerWidth, smallerHeight)
        image.SetData(reducedImageString)
        dc.DrawBitmap(wx.BitmapFromImage(image), 0, 0)
        dc.EndDrawing()

        # Putting the call self.devicePanel.Refresh() here immediately causes the
        # error "PyAssertionError: C++ assertion ... invalid backing store".

        self.timeOfLastScreenUpdate = time.time()
        #globals_.traceLogger.debug("OnCameraUpdate(): updated the screen")
        self.device.updateImageSize(smallerWidth, smallerHeight)


    def OnPaint(self, event):
        # Called when the window is exposed.

        # Create a buffered paint DC.  It will create the real
        # wx.PaintDC and then blit the bitmap to it when dc is
        # deleted.  Since we don't need to draw anything else
        # here that's all there is to it.

        # Note that we don't call self.devicePanel.Refresh() here
        # because that "causes an EVT_PAINT event to be 
        # generated and sent to the window" according to 
        # wxPython.org, which would result in a loop.
        dc = wx.BufferedPaintDC(self, self.buffer)


    def OnCharEvent(self, event):
        # The unicode value for a key is the same as its keycode
        # when the key is in KEY_MAP, so we don't have to deal with
        # KEY_MAP here.
        # The database stores as numbers everything except
        # keycodes that are entered via one of the special controls
        # as the named keycode, such as DPAD_LEFT.
        # I think that when the codes are re-constructed from the
        # DB, this will work because they will be re-interpreted
        # according to the inverse of the rule by which they were
        # stored. event.GetKeyCode() returns an ord(), and chr()
        # is run on the DB value. The user's key mapping does not
        # come into play.
        
        # Let the rule be, if the key code is an ASCII-printable
        # code, the code will be played as text via 'adb shell input
        # text ...'.
        code = event.GetKeyCode()
        if code > 127:
            # Prevents 
            # UnicodeEncodeError: 'ascii' codec can't encode character u'\u0139' in 
            # position 202: ordinal not in range(128)
            dprint("not passing code: " + str(code) + " on to the device")
        else:
            controlDown = event.CmdDown()
            altDown = event.AltDown()
            if (not (altDown or controlDown)):
                self.device.addKeycodeToSend(code)
                if not self.charTimerSet:
                    self.charTimer.Start(3000, oneShot=True)
                    self.charTimerSet = True

        event.Skip()


    def OnTimer(self, event):
        # I don't think we need a lock; I think events are only allowed to
        # occur when the main thread, which this is in, is inactive.
        # In fact, wx.Yield() exists to allow the thread to be interrupted,
        # right?
        # get a lock
        # keycodesToSend = self.keycodesToSend
        # self.keycodesToSend = []
        # self.EnterText(keycodesToSend)
        # release lock
        wereSent = self.device.sendKeyEvents()     
        if wereSent:
            self.charTimerSet = False


    def displayADBDeviceNotFoundError(self):
        # This method is a property of the device window rather than the App frame
        # b/c we don't want to block other running tests.
        
        # From wxpython-src/wxPython-src-2.8.11.0/wxPython/demo/agw/GenericMessageDialog.py.
        dprint('displayADBDeviceNotFoundError(self)')
        msg = "Android Debug Bridge (adb) reported that the device "
        msg += "was not found."
        buttonStyle = wx.OK
        dialogStyle = wx.ICON_ERROR
        dlg = wx.MessageDialog(self.devicePanel,
                               msg,
                               "ADB Connection Error",
                               buttonStyle | dialogStyle)
        dlg.ShowModal()
        dlg.Destroy()


class ScreenshotProcess(threading.Thread):
    # A screenshot-taking thread specific to a device.
    def __init__(self, mgr, device, notify_window, testName, port, serialNo, width, height, chinBarHeight, 
                 chinBarImageString, screenshotMethod, monkeyrunnerPath):
        self.mgr = mgr
        self.device = device # At this point, device.usingAltSerialNo == True, device.dt.serialNo == ''.
        self.notify_window = notify_window
        # The test being played or recorded.
        self.testName = testName
        self.port = port # XXX serves as device ID for now
        self.serialNo = serialNo
        self.width = width
        # Here, self.height is the height of the 'LCD' screen,
        # b/c that is what this process captures.
        self.height = height
        self.chinBarImageString = chinBarImageString
        self.screenshotMethod = screenshotMethod
        self.monkeyrunnerPath = monkeyrunnerPath

        # Kept to 5 in length.
        self.previousExploreImageFilenames = [x for x in os.listdir('.') if x.startswith('explore.') 
                                              and x.endswith('.png')]
        # Allows us to know
        self.imageLastAcquiredTime = 0
        things = os.listdir(os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR))
        deviceFiles = sorted([x for x in things if x.startswith('device.' + self.serialNo)])
        self.lastMonkeyrunnerImageFilename = deviceFiles[-1] if deviceFiles else ""
        self.recorder = None
        self.stopRequested = False
        dtSerialNo = device.serialNo if not device.usingAltSerialNo else ''
        self.adbTransport = adbTransport.ADBTransport(serialNo=dtSerialNo, noGUI=(notify_window is None))

        # True when screenshots should no longer be taken.
        self.stopped = False

        if self.screenshotMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER:
            imageGrabberPath = os.path.join(os.path.dirname(getExecutableOrRunningModulePath()),
                                            constants.MONKEYRUNNER_IMAGE_GRABBER_SCRIPT_NAME)
            outPipe = sys.stdout if constants.MONKEYRUNNER_PRINT else subprocess.PIPE
            self.monkeyrunnerProc = subprocess.Popen([monkeyrunnerPath, imageGrabberPath,
                                                      os.path.join(globals_.getUserDocumentsPath(), 
                                                                   constants.APP_DIR),
                                                      device.serialNo, 
                                                      'True' if device.usingAltSerialNo else 'False'],
                                                     stdout=outPipe, stderr=outPipe)

        threading.Thread.__init__(self)
        self.start()


    def changeScreenshotMethod(self, newMethod):
        oldMethod = self.screenshotMethod
        if oldMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER:
            try:
                stopdevicePath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR,
                                              'stopdevice.' + self.device.serialNo)
                with open(stopdevicePath, 'w') as fp:
                    # Calling open() creates the file.
                    pass
            except:
                dprint("CREATION OF STOPDEVICE FILE FAILED!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                bdbg()
        self.screenshotMethod = newMethod
        if newMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER:
            imageGrabberPath = os.path.join(os.path.dirname(getExecutableOrRunningModulePath()),
                                            constants.MONKEYRUNNER_IMAGE_GRABBER_SCRIPT_NAME)
            outPipe = sys.stdout if constants.MONKEYRUNNER_PRINT else subprocess.PIPE
            self.monkeyrunnerProc = subprocess.Popen([self.monkeyrunnerPath, imageGrabberPath,
                                                      os.path.join(globals_.getUserDocumentsPath(), 
                                                                   constants.APP_DIR),
                                                      self.device.serialNo, 
                                                      'True' if self.device.usingAltSerialNo else 'False'],
                                                     stdout=outPipe, stderr=outPipe)


    def setRecordOrPlayTestName(self, testName=None, indexInSuite=None):
        dprint("setRecordOrPlayTestName", testName)
        #self.testName = testName
        #self.indexInSuite = indexInSuite


    class FakeCameraUpdate():
        def __init__(self, width, height, imageFilename):
            self.width = width
            self.height = height
            self.imageFilename = imageFilename


    def run(self):
        while not self.stopRequested:
            flattenedPNGPath, errorMsg = self.getImageData()
            if errorMsg:
                wx.PostEvent(self.notify_window, ADBError(errorMsg))
            #self.device.receiveCameraImageUpdate(flattenedPNGName)
            # XXX This is only necessary when we're replaying. It takes 0.15 - 0.3 seconds.
            # XXX Make it faster by making the client code add the chinbar.
            if not self.notify_window:
                # As the tool is being shut down, self.notify_window
                # becomes None (or equivalent) apparently, causing
                # this block to execute.
                try:
                    self.device.receiveCameraImageUpdate(self.imageString)
                except:
                    pass
            else:
                # On Windows, it seems that when this block is encountered after the close button
                # of the dialog is pressed, execution hangs at the PostEvent call. notify_window
                # is the DeviceGUIAssembly; perhaps it doesn't exist, so the PostEvent hangs.
                if self.stopRequested:
                    return
                if flattenedPNGPath:
                    wx.PostEvent(self.notify_window, ScreenshotUpdate(self.port, self.serialNo, self.width, 
                                                                      self.height, os.path.basename(flattenedPNGPath)))
        if self.stopRequested:
            dprint('screenshotprocess, stoprequested')
            return


    def getImageData(self):
        pulledBufferName = 'raw.' + self.serialNo
        if self.screenshotMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER:
            # Find the name of the existing file that tells monkeyrunner what to do.
            # If the new file is named differently, meaning that monkeyrunner needs
            # to write the image to a different filename, write the new file and
            # delete the old one.
            # The framebuffer-pulling approach doesn't have to sleep b/c it is the one creating
            # the image. The monkeyrunner approach sleeps b/c it isn't.
            try:
                while True:
                    things = os.listdir(os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR))
                    deviceFiles = sorted([x for x in things if x.startswith('device.' + self.serialNo)])
                    if len(deviceFiles) > 5:
                        for thing in deviceFiles[:len(deviceFiles) - 5]:
                            try:
                                os.remove(os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR,
                                                       thing))
                            except:
                                pass
                    if (deviceFiles and deviceFiles[-1] != self.lastMonkeyrunnerImageFilename):                    
                        self.lastMonkeyrunnerImageFilename = deviceFiles[-1]
                        try:
                            image = Image.open(os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR,
                                                            deviceFiles[-1]))
                            # about 0.03 seconds
                            image = image.convert("RGB")
                            # unknown seconds
                            prefix, unflattenedPNGPath, flattenedPNGPath = utils.getPNGNames(self.mgr, self.serialNo)
                            image.save(flattenedPNGPath)
                        except Exception, e:
                            time.sleep(0.05)
                        else:
                            break
                    else:
                        time.sleep(0.05)
            except Exception, e:
                dprint('err')
                bdbg()
                pass
        else:
            prefix, unflattenedPNGPath, flattenedPNGPath = utils.getPNGNames(self.mgr, self.serialNo)
            # XXX this has to be the pix format from the config file
            pixformat = constants.SCREENSHOT_METHOD_PIXFORMAT[self.screenshotMethod]
            utils.writeImage(self.adbTransport, pulledBufferName, self.serialNo, prefix, unflattenedPNGPath,
                             flattenedPNGPath, self.width, self.height, pixformat)
        if prefix in ['explore', 'pause']:
            self.previousExploreImageFilenames.append(flattenedPNGPath)

        if constants.STREAK_DEBUG:
            pass

        lenPreviousFilenames = len(self.previousExploreImageFilenames)
        while lenPreviousFilenames > 5:
            try:
                oldFilename = self.previousExploreImageFilenames.pop(0)
            except Exception, e:
                dprint('error')
                bdbg()
            try:
                os.remove(oldFilename)
            except Exception, e:
                # e.g. WindowsError(2, 'The system cannot find the file specified')
                pass
            lenPreviousFilenames -= 1

        self.imageLastAcquiredTime = time.time()
        try:
            # This prevents the unflattened image file from being copied over to the
            # tests directory by recorder.py's storeImages().
            os.remove(unflattenedPNGPath)
        except:
            pass
        if self.mgr.isRecording:
            if self.recorder is None:
                self.recorder = recorder.Recorder()
            # self.recorder.saveScreen(self.mgr.sessionName, self.serialNo, imageString)
        return flattenedPNGPath, ""


class TargetImageUpdate(wx.PyEvent):
    def __init__(self, width, height, imageString):
        wx.PyEvent.__init__(self)
        self.SetEventType(TARGET_IMAGE_UPDATE_ID)
        self.width = width
        self.height = height
        self.imageString = imageString


class ADBError(wx.PyEvent):
    def __init__(self, errorMessage):
        wx.PyEvent.__init__(self)
        self.SetEventType(ADB_ERROR_ID)
        self.errorMessage = errorMessage


class ScreenshotUpdate(wx.PyEvent):
    def __init__(self, port, serialNo, width, height, imageFilename):
        wx.PyEvent.__init__(self)
        self.SetEventType(CAMERA_RESULT_ID)
        self.port = port
        self.serialNo = serialNo
        self.width = width
        self.height = height
        self.imageFilename = imageFilename


class ReloadGUIEvent(wx.PyEvent):
    def __init__(self, sessionName):
        wx.PyEvent.__init__(self)
        self.SetEventType(RELOAD_GUI_ID)
        self.sessionName = sessionName


class VNCProcess(threading.Thread):
    # XXX  A VNC thread specific to a device.
    def __init__(self, mgr, device, notify_window, session, vncPort, serialNo, viewerToGUISocketPort, chinBarHeight, 
                 chinBarImageString):
        self.mgr = mgr
        self.device = device
        self.notify_window = notify_window
        self.session = session
        self.vncPort = vncPort
        self.serialNo = serialNo
        self.viewerToGUISocketPort = viewerToGUISocketPort
        self.chinBarImageString = chinBarImageString

        self.imageString = ""
        self.recorder = None
        self.stopRequested = False
        # XXX
        java = ("java -cp /homep/tst/d/tigervnc-1.0.1/java/src com/tigervnc/vncviewer/VncViewer HOST localhost PORT " +
                str(vncPort))
        self.javaProcess = subprocess.Popen(java.split())
        self.vncviewerSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # XXX move port defn to config tab. change the VncCanvas.java to take port as input if it doesn't already.
        # XXX Then, modify GUI class to scan for VNC devices and suggest these in the config tab.
        self.vncviewerSocket.bind(('127.0.0.1', self.viewerToGUISocketPort))
        self.vncviewerSocket.listen(5)

        threading.Thread.__init__(self)
        self.start()


    def run(self):
        while True:
            width, height, self.imageString = self.getImageData()
            if not self.notify_window:
                self.device.receiveCameraImageUpdate(self.imageString)
            else:
                # On Windows, it seems that when this block is encountered after the close button
                # of the dialog is pressed, execution hangs at the PostEvent call. notify_window
                # is the DeviceGUIAssembly; perhaps it doesn't exist, so the PostEvent hangs.
                if self.stopRequested:
                    return
                wx.PostEvent(self.notify_window, VNCUpdate(self.port, self.serialNo, width, height, self.imageString))
            if self.stopRequested:
                dprint('screenshotprocess, stoprequested')
                return


    def getImageData(self):
        client, addr = self.vncviewerSocket.accept()  # blocks til it gets something
        outputNumber = 0
        imageString = ''
        while True:
            _imageString = client.recv(2000000) # small enough: 1000000000, too large: 1000000000000
            if _imageString:
                outputNumber += 1
                imageString += _imageString
            else:
                break

        # Only the final _imageString in a transmission has '\n' appended to it.
        imageString = imageString.rstrip('\n')

        if imageString.startswith('WIDTH:'):
            firstSpace = imageString.find(' ', 0)
            secondSpace = imageString.find(' ', firstSpace + 1)
            thirdSpace = imageString.find(' ', secondSpace + 1)
            fourthSpace = imageString.find(' ', thirdSpace + 1)
            width = int(imageString[firstSpace:secondSpace])
            height = int(imageString[thirdSpace:fourthSpace])
            imageString = imageString[fourthSpace + 1:].decode('hex')
            if self.notify_window.parent.isRecording:
                if self.recorder is None:
                    self.recorder = recorder.Recorder()

                if self.session == '':
                    raise Exception()
                #self.recorder.saveScreen(self.session, self.serialNo, imageString)
            return width, height, imageString
        else:
            return None, None, None


class VNCUpdate(wx.PyEvent):
    def __init__(self, port, serialNo, width, height, imageString):
        wx.PyEvent.__init__(self)
        self.SetEventType(CAMERA_RESULT_ID)
        self.port = port
        self.serialNo = serialNo
        self.width = width
        self.height = height
        self.imageString = imageString


class ReplayApp(wx.App):
    # Device instances are not picklable, and neither are adbTransport instances. They must be picklable
    # if they are to be members of ReplayProcess due to Windows restrictions on the multiprocessing module. That means
    # that adbTransport must be created within ReplayProcess. adbTransport has a wx.Timer member; but such members
    # must be part of a wx.App, so we create a simple wx.App here.
    pass


class MyApp(wx.App):
    def OnInit(self):
        self.SetAppName("Dollop")
        wx.InitAllImageHandlers()
        try:
            self.frame = AppFrame(None, self) #camera='screenshot', device=device)
        except ADBMisconfigured, e:
            message = "An attempt to call Android Debug Bridge (adb) failed. The command the tool tried to execute "
            message += "was:\n\n" + e.message + '\n\n'
            message += "Please check that adbpath in the configuration file for this tool, at " 
            message += os.path.join(wx.StandardPaths_Get().GetDocumentsDir(), constants.APP_DIR, 
                                    constants.APPLICATION_NAME_REGULAR_CASE + '.cfg')
            message += ", is set correctly.\n"
            dlg = wx.MessageDialog(None,
                                   message,
                                   "Error", # Dialog title
                                   wx.OK)
            dlg.ShowModal()
            dlg.Destroy()

            sys.exit(1)
        self.SetTopWindow(self.frame)
        self.frame.Show()
        return 1


if __name__ == '__main__':
    parser = optparse.OptionParser(usage=constants.APPLICATION_NAME_REGULAR_CASE)
    # parser.add_option("-d",
    #                   dest='deviceType',
    #                   default='D2',
    #                   help='D2 or emulator')
    
    parser.add_option("-i",
                      dest='inspector',
                      default=False,
                      action='store_true',
                      help='launch the wx inspection tool')
    # parser.add_option("-m",
    #                   dest='noGUI',
    #                   default=False,
    #                   action='store_true',
    #                   help='do not display a GUI')
    # parser.add_option("-s",
    #                   dest='session',
    #                   help='the session to run (when a GUI is not being used)')
    # parser.add_option("-p",
    #                   dest='printSessions',
    #                   default=False,
    #                   action='store_true',
    #                   help='list the session names and exit')

    options, args = parser.parse_args()
    #options.inspector = False

    # if options.deviceType == 'D2':
    #     device = constants.NON_EMULATOR_DEVICE_TYPE
    # elif options.deviceType == 'emulator':
    #     device = constants.EMULATOR_DEVICE_TYPE
    # else:
    #     raise Exception()

    options.noGUI = False
    options.printSessions = False
    if options.printSessions:
        mgr = IndividualTestManager()
        sessions = mgr.recorder.getSessionNames()
        dprint(sessions)
        sys.exit(0)
    else:

        # XXX noGUI has fallen out of use but could be supported in the future.
        if options.noGUI:
            mgr = IndividualTestManager()
            mgr.device.setWindow(None, 'screenshot')
            okprint(options.session)
            mgr.setSessionName(options.session)
            mgr.populateInputEvents() # XXX Broken; old usage.
            try:
                mgr.startReplay()
            except Exception, e:
                (_, _, tracebackObject) = sys.exc_info()
                traceback.print_tb(tracebackObject)
        else:
            app = MyApp(0)

            if options.inspector:
                import wx.lib.inspection
                wx.lib.inspection.InspectionTool().Show()

            app.MainLoop()


