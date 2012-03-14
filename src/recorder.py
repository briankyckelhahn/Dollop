# -*- coding: utf-8 -*-

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


## Records screen, location, type, and time of click, and other things.
import cPickle
import cv
import logging
import os
import shutil
import time

import constants
from globals_ import *
import storage


class Recorder(object):
    def __init__(self, backUpDB=False):
        self.storage = storage.Storage(backUpDB=backUpDB)
        self.cachedClicks = []
        self.savedClickFilenames = []

    def restoreBackup(self):
        self.storage.restoreBackup()


    def executeRawCommand(self, text):
        # In the current system, 'text' is raw SQL.
        self.storage.executeRawCommand(text)

        
    def getSessionNames(self):
        return self.storage.getSessionNames()


    def getSuggestedSessionName(self):
        # The suggested name is provided to save the user from having to think of one;
        # it may not be a good idea.
        return self.storage.getSuggestedSessionName()

    
    def startSession(self, deviceData, name):
        sessionID = self.storage.startSession(deviceData, name)
        return sessionID


    def renameSession(self, oldName, newName):
        self.storage.renameSession(oldName, newName)


    def deleteSessions(self, sessionNames):
        self.storage.deleteSessions(sessionNames)

        
    def addDeviceIfNecessary(self, serialNo, screenWidth, lcdHeight, maxADBCommandLength):
        self.storage.addDeviceIfNecessary(serialNo, screenWidth, lcdHeight, maxADBCommandLength)


    def saveScreen(self, session, serialNo, imageString):
        self.storage.saveScreen(session, serialNo, imageString)

    
    def recordClick(self, session, serialNo, clickType, x, y, width, height, chinBarHeight, imageFilename,
                    timeOfClick=None):
        self.storage.clearOngoingKeyEventsSessions(session, serialNo)

        # We only start saving when it's an up click that was just performed, otherwise
        # we could turn a tap into a very long press.
        if len(self.cachedClicks) > 30 and self.cachedClicks[-1][2] == constants.LEFT_UP_CLICK:
            # Just in case it's possible self.cachedClicks could be appended to
            # while this code runs, get a known portion of self.cachedClicks
            # and delete that.
            lenClicks = len(self.cachedClicks)
            pickleName = session + str(time.time()) + '.pkl'
            self.savedClickFilenames.append(pickleName)
            output = open(pickleName, 'wb')
            cPickle.dump(self.cachedClicks[:lenClicks], output)
            output.close()
            del self.cachedClicks[:lenClicks]
#            for _ in range(len(self.cachedClicks)):
#                (_session, _serialNo, _clickType, _x, _y, _targetImageWidth,
#                 _targetImageHeight, _imageFilename, _timeOfClick) = self.cachedClicks[0]
#                self.storage.saveClick(_session, _serialNo, _clickType, _x, _y, _targetImageWidth,
#                                       _targetImageHeight, _imageFilename, _timeOfClick)
#                del self.cachedClicks[0]


        # When timeOfClick is provided, it's a floating-point number,
        # as returned by time.time().
        # XXX At the momemnt, recordclick has only one device per recorder. keep it that way until more pressing 
        #     problmes solved

        # Add 1 to TARGET_IMAGE_SQUARE_WIDTH / 2 so that the number of pixels to
        # the left of the center pixel
        # will be one less than the number to its right if the target image
        # has even width. Arbitrary.

        # OpenCV's GetRectSubPix may do this.
        targetImageLeftX = max(x - constants.TARGET_IMAGE_SQUARE_WIDTH / 2 + constants.EVEN_WIDTH_ADDITION, 0)
        # Subtract 1 from the width because the array is 0-based.
        targetImageRightX = min(width - 1, 
                                x + constants.TARGET_IMAGE_SQUARE_WIDTH / 2 + constants.TARGET_IMAGE_SQUARE_WIDTH % 2)
        targetImageWidth = targetImageRightX - targetImageLeftX + 1
        targetImageTopY = max(y - constants.TARGET_IMAGE_SQUARE_WIDTH / 2 + constants.EVEN_HEIGHT_ADDITION, 0)
        # Subtract 1 from the height because the array is 0-based.
        targetImageBottomY = min(height - 1, 
                                 y + constants.TARGET_IMAGE_SQUARE_WIDTH / 2 + constants.TARGET_IMAGE_SQUARE_WIDTH % 2)
        targetImageHeight = targetImageBottomY - targetImageTopY + 1

        self.cachedClicks.append((session, serialNo, clickType, x, y, targetImageWidth,
                                  targetImageHeight, imageFilename, timeOfClick))


    def flushClicks(self):
        lenClicks = len(self.cachedClicks)
        for index in range(lenClicks):
            (_session, _serialNo, _clickType, _x, _y, _targetImageWidth,
             _targetImageHeight, _imageFilename, _timeOfClick) = self.cachedClicks[index]
            self.storage.saveClick(_session, _serialNo, _clickType, _x, _y, _targetImageWidth,
                                   _targetImageHeight, _imageFilename, _timeOfClick)

        del self.cachedClicks[:lenClicks]


    def recordKeyEvents(self, session, serialNo, keycodes):
        self.storage.addKeyEvents(session, serialNo, keycodes)


    def addTextToVerify(self, session, serialNo, text):
        self.storage.clearOngoingKeyEventsSessions(session, serialNo)
        self.storage.addTextToVerify(session, serialNo, text)


    def addWait(self, session, serialNo, wait):
        self.storage.clearOngoingKeyEventsSessions(session, serialNo)
        self.storage.addWait(session, wait)


    def saveInputEvent(self,
                       sessionPath=None,
                       testFolderPath=None,
                       chinBarImagePath=None,
                       index=None,
                       numberOfEvents=None,
                       serialNo=None, 
                       startTime=None,
                       inputType=None,
                       characters=None,
                       targetImageWidth=None,
                       targetImageHeight=None,
                       targetImageString=None,
                       keyEventsSessionID=None,
                       keycodes=None,
                       textToVerify=None,
                       wait=None,
                       dragStartRegion=None,
                       dragEndRegion=None,
                       dragRightUnits=None,
                       dragDownUnits=None,
                       waitForImageStabilization=False):
        self.storage.saveInputEvent(sessionPath=sessionPath,
                                    testFolderPath=testFolderPath,
                                    chinBarImagePath=chinBarImagePath,
                                    index=index,
                                    numberOfEvents=numberOfEvents,
                                    serialNo=serialNo,
                                    startTime=startTime,
                                    inputType=inputType,
                                    characters=characters,
                                    targetImageWidth=targetImageWidth,
                                    targetImageHeight=targetImageHeight,
                                    targetImageString=targetImageString,
                                    keycodes=keycodes,
                                    textToVerify=textToVerify,
                                    wait=wait,
                                    dragStartRegion=dragStartRegion,
                                    dragEndRegion=dragEndRegion,
                                    dragRightUnits=dragRightUnits,
                                    dragDownUnits=dragDownUnits,
                                    waitForImageStabilization=waitForImageStabilization)


    def updateInputEvent(self,
                         sessionName=None,
                         index=None,
                         inputType=None,
                         characters=None,
                         targetImageWidth=None,
                         targetImageHeight=None,
                         targetImageString=None,
                         keycodes=None,
                         textToVerify=None,
                         wait=None,
                         dragStartRegion=None,
                         dragEndRegion=None,
                         dragRightUnits=None,
                         dragDownUnits=None):
        self.storage.updateInputEvent(sessionName=sessionName,
                                      index=index,
                                      inputType=inputType,
                                      characters=characters,
                                      targetImageWidth=targetImageWidth,
                                      targetImageHeight=targetImageHeight,
                                      targetImageString=targetImageString,
                                      keycodes=keycodes,
                                      textToVerify=textToVerify,
                                      wait=wait,
                                      dragStartRegion=dragStartRegion,
                                      dragEndRegion=dragEndRegion,
                                      dragRightUnits=dragRightUnits,
                                      dragDownUnits=dragDownUnits)


    def finishTestOrPlayStorage(self, testOrPlayName, interactionType):
        for filename in self.savedClickFilenames:
            fp = open(filename, 'rb')
            clicks = cPickle.load(fp)
            fp.close()

            for click in clicks:
                (_session, _serialNo, _clickType, _x, _y, _targetImageWidth,
                 _targetImageHeight, _imageFilename, _timeOfClick) = click
                if not _imageFilename:
                    dprint("not imagefilename!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                    bdbg()
                self.storage.saveClick(_session, _serialNo, _clickType, _x, _y, _targetImageWidth,
                                       _targetImageHeight, _imageFilename, _timeOfClick)

            try:
                os.remove(filename)
            except:
                pass
        self.savedClickFilenames = []

        self.storeImages(testOrPlayName, interactionType)

        
    def storeImages(self, testOrPlayPath, interactionType):
        testOrPlayName = os.path.basename(testOrPlayPath).rsplit('.', 1)[0]
        # interactionType is 'play' or 'record'
        assert interactionType in ['play', 'record']
        # On my Windows machine, the list from listdir() is already sorted; but maybe
        # not on all versions of Windows.
        couldNotMove = []
        if interactionType == 'record':
            for thing in os.listdir('.'):
                if thing.startswith('record.' + testOrPlayName):
                    try:
                        shutil.move(thing, os.path.join('tests', testOrPlayName, thing))
                    except:
                        couldNotMove.append(thing)
            if couldNotMove != []:
                time.sleep(1)
                for thing in couldNotMove:
                    try:
                        shutil.move(thing, os.path.join('tests', testOrPlayName, thing))
                    except:
                        # XXX We'll bomb somewhere else later.
                        pass
        else:
            for thing in os.listdir('.'):
                if thing.startswith('play.') and thing.endswith('png'):
                    try:
                        shutil.move(thing, os.path.join('plays', testOrPlayName, thing))
                    except:
                        couldNotMove.append(thing)
            if couldNotMove != []:
                time.sleep(1)
                for thing in couldNotMove:
                    try:
                        shutil.move(thing, os.path.join('plays', testOrPlayName, thing))
                    except:
                        # XXX We'll bomb somewhere else later.
                        pass
        dprint("finished storeImages()")


    def deleteInputEvent(self, sessionName, index):
        self.storage.deleteInputEvent(sessionName, index)


    def getInputEventsForSession(self, sessionName):
        return self.storage.getInputEventsForSession(sessionName)


    def markSessionPackaged(self, sessionName):
        self.storage.markSessionPackaged(sessionName)


    def isSessionPackaged(self, sessionName):
        return self.storage.isSessionPackaged(sessionName)


    def getEventsForSession(self, sessionName):
        return self.storage.getEventsForSession(sessionName)


    def getDevice(self, serialNo):
        return self.storage.getDevice(serialNo)
    
    
    def maybeUpdateDeviceInfo(self, serialNo, maxADBCommandLength):
        self.storage.updateDeviceInfo(serialNo, maxADBCommandLength)
        
        
    def getDevicesOfSession(self, sessionName):
        return self.storage.getDevicesOfSession(sessionName)


    def getVirtualKeys(self, serialNo):
        properties = self.storage.getVirtualKeys(serialNo)
        keys = {}
        for keycode, hitTop, hitBottom, hitLeft, hitRight in properties:
            keys[keycode] = {}
            keys[keycode]['hitTop'] = hitTop
            keys[keycode]['hitBottom'] = hitBottom
            keys[keycode]['hitLeft'] = hitLeft
            keys[keycode]['hitRight'] = hitRight           
        return keys


    def saveVirtualKeys(self, serialNo, virtualKeys):
        self.storage.saveVirtualKeys(serialNo, virtualKeys)


    def startSuitePlayRecording(self, deviceData):
        return self.storage.startSuitePlayRecording(deviceData)


    def startTestPlayRecording(self, playName, testName):
        return self.storage.startTestPlayRecording(playName, testName)


    def savePlayClick(self, session, playStartTime, serialNo, clickType, x, y, imageString, targetFound):
        self.storage.savePlayClick(session, playStartTime, serialNo, clickType, x, y, imageString,
                                   targetFound)


    def saveOCRBoxData(self, session, serialNo, timeWithSubseconds, text):
        self.storage.saveOCRBoxData(session, serialNo, timeWithSubseconds, text)


    def getOCRBoxData(self, session):
        return self.storage.getOCRBoxData(session)


    def getSessionToPostProcess(self):
        return self.storage.getSessionToPostProcess()


    def getAllSessionsToPostProcess(self):
        return self.storage.getAllSessionsToPostProcess()


    def getUnprocessedEventForSession(self, sessionID, deviceData):
        return self.storage.getUnprocessedEventForSession(sessionID, deviceData)
