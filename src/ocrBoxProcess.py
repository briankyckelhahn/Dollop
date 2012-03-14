# Copyright (C) 2011 Brian Kyckelhahn
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
import copy
import cv
import Image #PIL
import logging
import math
import multiprocessing
import optparse
import os
import random
import re
import signal
import socket
import StringIO
import subprocess
import sys
import threading
import time
import traceback
import wx
import wx.lib.buttons
import wx.lib.agw.genericmessagedialog as GMD
from wx.lib.embeddedimage import PyEmbeddedImage
import wx.lib.platebtn as platebtn

import adbTransport
import config
import constants
from deviceFiles import allDeviceConstants
from globals_ import *
import globals_
import gui
import recorder
import utils


class OCRBoxProcess(utils.Process):
    # This separate process produces Tesseract box data from all of the events of
    # a session.
    def __init__(self, userDocumentsPath, ocrBoxProcessQueue=None, session=None):
        self.userDocumentsPath = userDocumentsPath
        self.ocrBoxProcessQueue = ocrBoxProcessQueue
        self.session = session

        self.recorder = recorder.Recorder()
        self._request = None
        multiprocessing.Process.__init__(self)
        # It seems that, on Windows, calling id(self) in the run() method
        # produces a different result from doing so here, so we save the
        # value we get here.
        self.id = id(self)
        
        self.start()


    def getQueueMessages(self):
        messages = []
        while True:
            try:
                messages.append(self.ocrBoxProcessQueue.get_nowait())
            except Exception, e:
                break
        globals_.traceLogger.debug("getQueueMessages, returning:" + str(messages))
        return messages


    def run(self):
        globals_.traceLogger.debug("OCRBoxProcess.run() starting...")

        if self.session == constants.OCR_BOX_PROCESS_SESSION_NAME_ALL:
            processingAll = True
            thisSession = self.recorder.getSessionToPostProcess()
        else:
            processingAll = False
            thisSession = self.session

        devices = self.recorder.getDevicesOfSession(thisSession)
        deviceData = {}
        for serialNo, width, lcdHeight, maxADBCommandLength, chinBarHeight, chinBarImageString, orientation in devices:
            deviceData[serialNo] = (width, lcdHeight + chinBarHeight, chinBarHeight, chinBarImageString, orientation)
        click = self.recorder.getUnprocessedEventForSession(thisSession, deviceData)
        if not click:
            globals_.traceLogger.debug("OCRBoxProcess.run() finished.")
            return                

        while click:
            (serialNo, timeWithSubseconds, clickType, x, y, targetImageWidth, targetImageHeight, targetImageString,
             lcdImage, index_, keyEventsSessionID, keycode, text) = click
            # clicks = self.recorder.getEventsForSession(thisSession)
            # for (serialNo, timeWithSubseconds, clickType, x, y, targetImageWidth, targetImageHeight, targetImageString,
            #      savedScreen, index_, keyEventsSessionID, keycode, text) in clicks:
            if clickType != constants.LEFT_DOWN_CLICK:
                # Currently, LEFT_DOWN_CLICK is the only type of event f/
                # which the screen is processed.
                continue

            # XXX we don't need to save all of the screen text, just the target text.
            (width, height, chinBarHeight, chinBarImageString, orientation) = deviceData[serialNo]
            text, success = utils.getOCRText(self.userDocumentsPath, lcdImage, width, height - chinBarHeight, 
                                             serialNo, box=True, lines=False)

            # On an all-blue image, the box text had no newlines and was just gibberish.
            lines = text.split('\n')
            filteredLines = []
            for line in lines:
                try:
                    char, leftX, lowerY, rightX, upperY, _ = line.split()
                except:
                    pass
                else:
                    filteredLines.append(line)
            text = '\n'.join(filteredLines)

            if success == constants.SUB_EVENT_ERRORED:
                dprint('getOCRText failed. Returning.')
                return
            self.recorder.saveOCRBoxData(thisSession, serialNo, timeWithSubseconds, text)

            messages = self.getQueueMessages()
            exitNow = False
            for message in messages:
                if message == (self.id, constants.ABORT_OCR_BOX_PROCESS):
                    dprint('found a message to quit the ocr box process')
                    self.ocrBoxProcessQueue.put((self.id, constants.OCR_BOX_PROCESS_EXITED))
                    globals_.traceLogger.debug("OCRBoxProcess.run(): Abort requested.")
                    exitNow = True
                    # Loop through all messages in case more than one ABORT...
                    # request was placed in the queue.
                else:
                    # The message was for another process. Put it back.
                    self.ocrBoxProcessQueue.put(message)
            if exitNow:
                return

            if processingAll:
                previousSession = thisSession
                thisSession = self.recorder.getSessionToPostProcess()
                if previousSession != thisSession:
                    devices = self.recorder.getDevicesOfSession(thisSession)
                    deviceData = {}
                    for serialNo, width, lcdHeight, maxADBCommandLength, chinBarHeight, chinBarImageString, orientation in devices:
                        deviceData[serialNo] = (width, lcdHeight + chinBarHeight, chinBarHeight, chinBarImageString, orientation)
            click = self.recorder.getUnprocessedEventForSession(thisSession, deviceData)
            if not click:
                globals_.traceLogger.debug("OCRBoxProcess.run() in while: finished.")
                return                

        globals_.traceLogger.debug("OCRBoxProcess.run() finished.")
        return
