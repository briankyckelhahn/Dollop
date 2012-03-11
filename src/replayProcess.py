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
import plateButton
import config
import constants
from deviceFiles import allDeviceConstants
import globals_
from globals_ import *
import gui
import recorder
import utils


class EventFailedException(Exception):
     pass


class ReplayProcess(utils.Process):
    """Replays a session."""
    def __init__(self, recorder, playName, testFilePath, testIndex, inputEvents, deviceData, adbPath=None, 
                 xScale=None, yScale=None, xIntercept=None, yIntercept=None,
                 replayControlQueue=None, 
                 eventsBoxQueue=None, 
                 configKeycodes=None,
                 noGUI=False,
                 latestImageFilename=None):

        self.recorder = recorder
        self.playName = playName
        self.testFilePath = testFilePath
        self.testIndex = testIndex
        # XXX there's just one deviceWindow at the momemtn.
        self.inputEvents = inputEvents
        self.deviceData = deviceData
        self.adbPath = adbPath
        self.xScale = xScale
        self.yScale = yScale
        self.xIntercept = xIntercept
        self.yIntercept = yIntercept
        self.replayControlQueue = replayControlQueue        
        self.eventsBoxQueue = eventsBoxQueue
        self.noGUI = noGUI
        self.latestImageFilename = latestImageFilename
        dprint('a2')
        self.configKeycodes = config.keycodes

        self.testName = os.path.basename(testFilePath).rsplit('.', 1)[0]
        # Populated by getNewImageString(). Serves as a cache when no more recent string is available.
        self.__imageString = ''
        dprint('a3')
        multiprocessing.Process.__init__(self)
        dprint('a4')
        self.start()


    def _imagesAreSubstantiallyDifferent(self, width, height, oldImageString, newImageString):
        oldScreen = cv.CreateImageHeader((self.device.width, self.device.height), cv.IPL_DEPTH_8U, 3)
        cv.SetData(oldScreen, oldImageString)
        oldGrey = cv.CreateImage((self.device.width, self.device.height), cv.IPL_DEPTH_8U, 1 )
        cv.CvtColor(oldScreen, oldGrey, cv.CV_RGB2GRAY)

        newScreen = cv.CreateImageHeader((self.device.width, self.device.height), cv.IPL_DEPTH_8U, 3)
        cv.SetData(newScreen, newImageString)
        newGrey = cv.CreateImage((self.device.width, self.device.height), cv.IPL_DEPTH_8U, 1 )
        cv.CvtColor(newScreen, newGrey, cv.CV_RGB2GRAY)

        difference = cv.CreateImageHeader((self.device.width, self.device.height), cv.IPL_DEPTH_8U, 1)
        cv.SetData(difference, chr(0) * self.device.width * self.device.height)

        # Difference the two images
        cv.AbsDiff(oldGrey, newGrey, difference)

        # Convert image to binary (black & white)
        cv.Threshold(difference, difference, 15, 255, cv.CV_THRESH_BINARY)

        # Count the number of white pixels, which are points of difference
        numWhite = 0
        for char in difference.tostring():
            if char == chr(255):
                numWhite += 1

        return (float(numWhite) / (self.device.width * self.device.height) >= constants.IMAGE_CHANGE_THRESHOLD)


    def _getLatestImageFilename(self, serialNo):
        # For the first second or two, the most recent file will be named explore...png.
        # It's okay to ignore this for the sake of simple programming now at the 
        # cost of slower startup.
        playFiles = sorted([x for x in os.listdir('.') if x.startswith('play.' +  str(self.testIndex) + '.' + 
                                                                       self.testName + '.' + serialNo)])
        pauseFiles = sorted([x for x in os.listdir('.') if x.startswith('pause.' +  str(self.testIndex) + '.' + 
                                                                        self.testName + '.' + serialNo)])
        while playFiles == [] and pauseFiles == []:
            time.sleep(0.2)
            playFiles = sorted([x for x in os.listdir('.') if x.startswith('play.' + str(self.testIndex) + '.'
                                                                           + self.testName + '.' + serialNo)])
            pauseFiles = sorted([x for x in os.listdir('.') if x.startswith('pause.' +  str(self.testIndex) + '.' + 
                                                                            self.testName + '.' + serialNo)])
        sinceUTC1, sinceUTC2 = 0, 0
        if playFiles != []:
            sinceUTC1 = playFiles[-1][-17:-4]
        if pauseFiles != []:
            sinceUTC2 = pauseFiles[-1][-17:-4]
        if sinceUTC1 > sinceUTC2:
            latestImageName = playFiles[-1]
        else:
            latestImageName = pauseFiles[-1]
        return latestImageName


    def _getLatestImageStringFromFile(self, serialNo, chinBarImageString):
        #dprint("_getLatestImageStringFromFile")
        latestImageName = self._getLatestImageFilename(serialNo)
        #dprint("_getLatestImageStringFromFile: ", latestImageName)        
        tries = 0
        successful = False
        while tries < 3 and not successful:
            try:
                image = Image.open(os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, latestImageName))
            except Exception, e:
                # Don't know how we'd get here; perhaps the image hasn't been completely written.
                #dprint("_getLatestImageStringFromFile: exception opening image")
                #dprint("image exists?:", 
                #       os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, latestImageName), 
                #       " ", 
                #       os.path.exists(os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, latestImageName)))
                time.sleep(0.1)
            else:
                try:
                    # about 0.01 seconds
                    newImageString = image.tostring()
                except Exception, e:
                    # I sometimes get an error about a broken PNG chunk here,
                    # and I've found that Image.open(...), image.tostring()
                    # works in this case, so go thru the loop again.
                    # This delay is just a guess; it could be appropriate when the image is
                    # still in the process of being created by the ScreenshotProcess.
                    time.sleep(0.1)
                else:
                    successful = True
            tries += 1
        if not successful:
            dprint("_getLatestImage... not successful")
            return "", None
        #dprint("returning string of length at least ", len(newImageString))
        return newImageString + chinBarImageString, latestImageName


    def getNewImageString(self, previousImageString, previousImageFilename, serialNo, chinBarImageString,
                          waitType='stable', tellIfDifferent=False):
        # ReplayProcess.run() should be written so that we only wait for the image to 
        # stabilize when the next event requires looking at the screen to determine
        # whether the event passes or fails. These event types are tap, long press,
        # text verification. The user may insert his own waits in other cases, but
        # I don't recall scenarios where he'd want to.

        # waitType is 'stable', 'newFile', or 'latest'.

        originalImageString = previousImageString
        _previousImageString, _previousImageFilename = previousImageString, previousImageFilename

        if waitType == 'newFile':
            newImageFilename = None
            while not newImageFilename:
                startTime = time.time()
                while ((self._getLatestImageFilename(serialNo) == _previousImageFilename) and 
                       (time.time() < startTime + constants.MAX_WAIT_TIME_FOR_IMAGE_CHANGE)):
                    time.sleep(0.1)
                newImageString, newImageFilename = self._getLatestImageStringFromFile(serialNo, chinBarImageString)

            imagesAreDifferent = None
            if tellIfDifferent:
                imagesAreDifferent = self._imagesAreSubstantiallyDifferent(self.device.width, self.device.height, 
                                                                           originalImageString, 
                                                                           newImageString)
            return imagesAreDifferent, newImageString, newImageFilename

        newImageString, newImageFilename = self._getLatestImageStringFromFile(serialNo, chinBarImageString)
        imagesAreDifferent = None

        if waitType == 'latest':
            imagesAreDifferent = None
            if tellIfDifferent:
                imagesAreDifferent = self._imagesAreSubstantiallyDifferent(self.device.width, self.device.height, 
                                                                           originalImageString, 
                                                                           newImageString)
            return imagesAreDifferent, newImageString, newImageFilename

        # waitType == 'stable'
        timeWaitStart = time.time()
        if not _previousImageString:
            return imagesAreDifferent, newImageString, newImageFilename


        # We consider the image on the device screen to be stable when it has not changed 
        # for a period of time. However, b/c we don't want to hang up the test for long, 
        # we'll abort after a much longer period of time, regardless of whether the image 
        # is stable.
        # So, to be fast
        def getTimeFromImageFilename(filename):
            sre = re.compile(".*\.(.*?)\.(.*?)\.png")
            match = sre.match(filename)
            return float(match.groups()[0] + '.' + match.groups()[1])

        # The earliest time an image was created containing the current device image
        # content.
        startTimeForImageContent = getTimeFromImageFilename(newImageFilename)
        numberOfDistinctFilesRead = 1
        _previousImageFilename = newImageFilename
        _previousImageString = newImageString
        while (time.time() - timeWaitStart) < constants.MAX_WAIT_TIME_FOR_IMAGE_CHANGE:
            newImageString, newImageFilename = self._getLatestImageStringFromFile(serialNo, chinBarImageString)
            if newImageFilename and newImageFilename != _previousImageFilename:
                timeOfLatestImageContent = getTimeFromImageFilename(newImageFilename)
                imagesAreDifferent = self._imagesAreSubstantiallyDifferent(self.device.width, 
                                                                           self.device.height, 
                                                                           _previousImageString,
                                                                           newImageString)
                if imagesAreDifferent:
                    # Start the timer over again for this new content.
                    startTimeForImageContent = timeOfLatestImageContent
                    numberOfDistinctFilesRead = 1
                else:
                    numberOfDistinctFilesRead += 1
                    if ((timeOfLatestImageContent - startTimeForImageContent) >
                        constants.IMAGE_CONSIDERED_STABLE_AFTER_SECONDS and
                        numberOfDistinctFilesRead >= constants.MINIMUM_NUMBER_FILES_FOR_IMAGE_STABILIZATION):
                        # Image is now stable.
                        if tellIfDifferent:
                            imagesAreDifferent = self._imagesAreSubstantiallyDifferent(self.device.width, 
                                                                                       self.device.height, 
                                                                                       originalImageString, 
                                                                                       newImageString)
                            
                        return imagesAreDifferent, newImageString, newImageFilename
                _previousImageFilename = newImageFilename
                _previousImageString = newImageString
            time.sleep(0.1)

        # We've timed out; send what we have.
        if tellIfDifferent:
            imagesAreDifferent = self._imagesAreSubstantiallyDifferent(self.device.width, 
                                                                       self.device.height, 
                                                                       originalImageString, 
                                                                       newImageString)
        return imagesAreDifferent, newImageString, newImageFilename


    def _getControlMessages(self):
        # True returned from this method indicates that the 
        # user wants to stop the replay.
        request = None
        while True:
            # Loop to get the most recent request.
            try:
                #request = gui.REPLAY_CONTROL_QUEUE.get_nowait()
                request = self.replayControlQueue.get_nowait()
            except Exception, e:
                break

        if request == 'pause':
            while True:
                try:
                    #request = gui.REPLAY_CONTROL_QUEUE.get_nowait()
                    request = self.replayControlQueue.get_nowait()
                except Exception, e:
                    pass                    
                time.sleep(0.1)
                globals_.traceLogger.debug("spinning in the PAUSE_REQUESTED loop of ReplayProcess.run()")
                if request == 'stop':
                    globals_.traceLogger.debug("stop request received")
                    return True
                elif request == 'resume':
                    globals_.traceLogger.debug("resume request received")
                    return False
        elif request == 'stop':  
            return True
        return False


    def run(self):
        # On Windows, global variables are not shared from a parent to a multiprocessing.Process
        # child.
        # Kludgy; config should perhaps be property of Device.
        config.adbPath = self.adbPath
        config.keycodes = self.configKeycodes

        serialNo = self.deviceData.keys()[0]
        dd = self.deviceData[serialNo]
        width = dd['width']
        height = dd['lcdHeight']
        chinBarHeight = dd['chinBarHeight']
        chinBarImageString = dd['chinBarImageString']
        orientation = dd['orientation']
        maxADBCommandLength = dd['maxADBCommandLength']
        self.device = gui.Device.makeDevice(serialNo=serialNo, mgr=None, vncPort=None, width=width, height=height, 
                                            chinBarHeight=chinBarHeight, xScale=self.xScale, yScale=self.yScale, 
                                            xIntercept=self.xIntercept, yIntercept=self.yIntercept, 
                                            orientation=orientation, chinBarImageString=chinBarImageString, 
                                            maxADBCommandLength=maxADBCommandLength, downText=dd['downText'],
                                            upText=dd['upText'], repeaterText=dd['downRepeaterText'],
                                            repeaterPostfixText=dd['repeaterPostfixText'],
                                            screenshotMethod=dd['screenshotMethod'],
                                            usingAltSerialNo=dd['usingAltSerialNo'],
                                            downUpText=dd['downUpText'])
        self.device.imageFilename = self.latestImageFilename

        if self._getControlMessages():
            # User wants to stop replay.
            dprint("replayProcess.py:run(): User wants to stop replay")
            return

        # __import__ing the user's module rather than eval()ing it as a flat list of statements
        # shields us from the user accidentally referring to locals in *this* routine.
        sys.path.insert(0, os.path.dirname(self.testFilePath))
        filename = os.path.basename(self.testFilePath)
        moduleName = str(filename[:filename.rfind('.')])
        testModule = __import__(moduleName, [], [], [], -1)
        userDevice = UserDevice(self, self.device, orientation)

        #with open(self.testFilePath, 'r') as fp: # TODO this has to be changed to self.testName, which is substituted into the imageFilenames as they're retreived. 
        #    rawCode = fp.read()
        #objectCode = compile(rawCode, '<string>', 'exec')
        #try:
        #    eval(objectCode)
        try:
            testModule.main(userDevice)
        except EventTimeout, e:
            leftprint(moduleName + " failed")
            self.eventsBoxQueue.put(constants.TEST_FAILED)
        except EventFailedException, e:
            leftprint(moduleName + " failed")
            self.eventsBoxQueue.put(constants.TEST_FAILED)
        except globals_.ADBDeviceNotFoundException, e:
            leftprint(moduleName + " failed")
            #self.device.window.displayADBDeviceNotFoundError()
            # XXX mark the test as failed in the events list
            # XXX show a dialog indicating that the device cannot be connected to 
            self.eventsBoxQueue.put(constants.TEST_FAILED)
            raise
        except Exception, e:
            leftprint(moduleName + " failed")            
            bdbg()
            self.eventsBoxQueue.put(constants.TEST_ERRORED)
        else:
            leftprint(".")
            # These need to be moved after the loop if more than one test is supported.
            leftprint("----------------------------------------------------------------------")
            leftprint("")
            leftprint("OK") 
            self.eventsBoxQueue.put(constants.TEST_PASSED)
        return


def quotify(thing):
    return '"' + thing + '"' if type(thing) in (str, type(u'')) else thing


class UserDevice(object):
    def __init__(self, replayProcess, device, orientation):
        self.replayProcess = replayProcess
        self.device = device
        self.orientation = orientation

        chinBarImageName = constants.CHIN_BAR_IMAGE_TEMPLATE.format(ser=device.serialNo)
        chinBarImagePath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, chinBarImageName)
        if os.path.exists(chinBarImagePath):
             _image = cv.LoadImage(chinBarImagePath, cv.CV_LOAD_IMAGE_COLOR)
             self.chinBarImageString = _image.tostring()
        elif self.device.chinBarImageString:
             self.chinBarImageString = self.device.chinBarImageString
        else:
             self.chinBarImageString = (chr(255) + chr(255) + chr(255)) * self.device.chinBarHeight * self.device.width

        # Used by _dragSearch to know whether the previous event was a drag and we may need to continue
        # dragging in the same direction.
        self.previousInputType = None
        self.previousDragStartRegion = None
        self.previousDragRightUnits = None
        self.previousDragDownUnits = None


#find all instances of inputeventnumber and ensure they're being determined appropriately

    def _dragSearch(self, findingRoutine, oldImageString, oldImageFilename, findingRoutineArg2=None,
                    findingRoutineArg3=None, findingRoutineArg4=None):
        imageString = oldImageString
        imageFilename = oldImageFilename
        globals_.traceLogger.debug("orientation: %d", self.orientation)
        forwardDragAttempts, backwardDragAttempts = 0, 0
        #showImage(imageString, self.device.width, self.device.height, 3)
        while (forwardDragAttempts < constants.MAX_FORWARD_DRAG_SEARCH_ATTEMPTS or
               backwardDragAttempts < constants.MAX_BACKWARD_DRAG_SEARCH_ATTEMPTS):
            if self.previousInputType == constants.DRAG:
                # The previous event was a drag. We may not have dragged to the correct
                # area of the app. Continue dragging in the direction of the drag
                # that got us here. If that fails, drag in the opposite direction.
                startRegion = self.previousDragStartRegion
                sx, sy = utils.getRegionCenterCoords(self.device, self.orientation, 
                                                     startRegion)
                endRegion = (startRegion[0] + self.previousDragRightUnits,
                             startRegion[1] + self.previousDragDownUnits)
                ex, ey = utils.getRegionCenterCoords(self.device, self.orientation, endRegion)
            else:
                sx, sy = utils.getRegionCenterCoords(self.device, self.orientation, (2, 3))
                ex, ey = utils.getRegionCenterCoords(self.device, self.orientation, (2, 1))

            if forwardDragAttempts < constants.MAX_FORWARD_DRAG_SEARCH_ATTEMPTS:
                dprint("dragging forward")
                #timeOfLastScreenUpdate = self.device.window.timeOfLastScreenUpdate
                if not (sx == ex and sy == ey):
                    self.device.drag(sx, sy, ex, ey)
                forwardDragAttempts += 1
            else:
                # We've already failed to find the target image while dragging
                # in the direction of the DRAG preceding this TAP. Try going
                # the other way.
                dprint("dragging backward")
                #timeOfLastScreenUpdate = self.device.window.timeOfLastScreenUpdate
                if not (sx == ex and sy == ey):
                    self.device.drag(ex, ey, sx, sy)
                backwardDragAttempts += 1

            startTime = time.time()
            imagesAreDifferent = False
            try:
                while time.time() < startTime + 10 and not imagesAreDifferent:
                    if self.replayProcess._getControlMessages():
                        # User wants to stop replay.
                        dprint("replayProcess.py:_dragSearch(): User wants to stop replay")
                        return None, 'stop', imageString, imageFilename
                    # I experimented here with waitForNewFile=True & waitTilStable=False, and
                    # this was not a sufficient wait. The target image would be found in a screen
                    # image that was out-of-date; this method had already dragged past it and so
                    # the previous location would be tapped.
                    imagesAreDifferent, imageString, imageFilename = \
                        self.replayProcess.getNewImageString(imageString, imageFilename, self.device.serialNo,
                                                             self.chinBarImageString, waitType='stable',
                                                             tellIfDifferent=True)
            except Exception, e:
                 bdbg()
                 dprint('err1')
            #showImage(imageString, self.device.width, self.device.height, 3)
            if imagesAreDifferent:
                try:
                    # The drag may have succeeded in moving the screen.
                    dprint("_dragSearch(): images are different. Calling the finding routine.")
                    value, status = findingRoutine(imageString, findingRoutineArg2, findingRoutineArg3, findingRoutineArg4)
                    dprint("_dragSearch(): images are different. The finding routine returned " + str(status))
                    if status == constants.SUB_EVENT_PASSED:
                        dprint('findingRoutine reported success')
                        return value, 'found', imageString, imageFilename
                    else:
                        pass #showImage(imageString, self.device.width, self.device.height, 3)
                except Exception, e:
                    bdbg()
                    dprint('err2')

            else:
                try:
                    # The drag might not have moved the screen.
                    dprint("The drag did not move the screen.")
                    if backwardDragAttempts == 0:
                        forwardDragAttempts = constants.MAX_FORWARD_DRAG_SEARCH_ATTEMPTS
                    else:
                        backwardDragAttempts = constants.MAX_BACKWARD_DRAG_SEARCH_ATTEMPTS
                        # We dragged in both directions, and now we've dragged backward
                        # but haven't gotten anywhere, and every time we HAVE gotten
                        # somewhere, we've looked for the tap/long press target and
                        # haven't found it. Fail.
                        return None, 'not found', imageString, imageFilename
                except Exception, e:
                    bdbg()
                    dprint('err3')

        return None, False, imageString, imageFilename


    def tap(self, targetImagePath="", characters=None, chinBarImagePath=None, 
            maxWaitTime=constants.MAX_DEFAULT_WAIT_TIME_TO_FIND_TARGET,
            dragSearchPermitted=constants.DRAG_SEARCH_PERMITTED):
        bdbg()
        if characters:
             okprint("Looking for an image near these characters:", characters)
        self._tapOrLongPress(constants.TAP, targetImagePath, characters, chinBarImagePath,
                             maxWaitTime=maxWaitTime, dragSearchPermitted=dragSearchPermitted)
        self.previousInputType = constants.TAP


    def longPress(self, targetImagePath="", characters=None, chinBarImagePath=None, 
                  maxWaitTime=constants.MAX_DEFAULT_WAIT_TIME_TO_FIND_TARGET,
                  dragSearchPermitted=constants.DRAG_SEARCH_PERMITTED):
        if characters:
             okprint("Looking for an image near these characters:", characters)
        self._tapOrLongPress(constants.LONG_PRESS, targetImagePath, characters, chinBarImagePath,
                             maxWaitTime=maxWaitTime, dragSearchPermitted=dragSearchPermitted)
        self.previousInputType = constants.LONG_PRESS


    def _tapOrLongPress(self, inputType, targetImagePath, characters, chinBarImagePath, 
                        maxWaitTime=constants.MAX_DEFAULT_WAIT_TIME_TO_FIND_TARGET,
                        dragSearchPermitted=constants.DRAG_SEARCH_PERMITTED):
        dprint("_tapOrLongPress, start time:", time.time())
        screenImageString, imageFilename = self.replayProcess._getLatestImageStringFromFile(self.device.serialNo, self.chinBarImageString)
        dprint("screenImageString[:50]:", screenImageString[:50])
        maxLoc, success = utils.findTargetInImageFile(self.device, screenImageString, targetImagePath, characters=characters)
        userWantsToStop = self.replayProcess._getControlMessages()
        if userWantsToStop:
            return

        if success == constants.SUB_EVENT_PASSED:
            x = maxLoc[0]
            y = maxLoc[1]

            if inputType == constants.TAP:
                self.device.tap(x, y) 
            elif inputType == constants.LONG_PRESS:
                self.device.longPress(x, y)

            self.replayProcess.recorder.savePlayClick(self.replayProcess.testFilePath, self.replayProcess.playName, self.device.serialNo,
                                                      inputType, x, y, "", True)
            return

        else:
            # There is no point in running findTargetFromInputEvent() on the same image
            # more than once, and doing so in a loop causes the pulling of the image
            # from the device to take several seconds, so we call getNewImageString()
            # with waitForNewFile=True.
            startTime = time.time()
            # Prevent a user-specified wait time of 0 from preventing the loop from running.
            maxWaitTime_ = 1 if maxWaitTime == 0 else maxWaitTime
            success = constants.SUB_EVENT_FAILED
            while time.time() < startTime + maxWaitTime and success != constants.SUB_EVENT_PASSED:
                userWantsToStop = self.replayProcess._getControlMessages()
                if userWantsToStop:
                    return
                # XXX It might be faster here to wait until the images are different, rather
                # than simply grabbing the new image file and running findTargetFromInputEvent()
                # on it, b/c findTargetFromInputEvent() prolly takes longer than does the differencing
                # code.
                _, screenImageString, imageFilename = \
                    self.replayProcess.getNewImageString(screenImageString, imageFilename, self.device.serialNo,
                                                         self.chinBarImageString, waitType='newFile')
                maxLoc, success = utils.findTargetInImageFile(self.device, screenImageString, targetImagePath, characters=characters)
                if success == constants.SUB_EVENT_PASSED:
                    x = maxLoc[0]
                    y = maxLoc[1]
                    if inputType == constants.TAP:
                        self.device.tap(x, y) 
                    elif inputType == constants.LONG_PRESS:
                        self.device.longPress(x, y)
                        self.replayProcess.recorder.savePlayClick(self.replayProcess.testFilePath, self.replayProcess.playName, self.device.serialNo,
                                                                  inputType, x, y, "", True)
                    else:
                        pass
                            #if characters:
                            # Even though this is a separate Process, we apparently have to sleep to allow
                            # the newest image from the device screen to be pulled.
                            #    time.sleep(2)
                    return

            if dragSearchPermitted:
                # _dragSearch calls getNewImageString with waitTilStable=True, so we don't 
                # need to wait further.
                maxLoc, status, screenImageString, imageFilename = \
                    self._dragSearch(self.device.findTargetInImageFile, screenImageString,    # findTargetFromInputEvent has to be changed to sth else.
                                     imageFilename, targetImagePath, characters)
                if status == 'found':
                    x = maxLoc[0]
                    y = maxLoc[1]
                    if inputType == constants.TAP:
                        self.device.tap(x, y) 
                    elif inputType == constants.LONG_PRESS:
                        self.device.longPress(x, y)

                    self.replayProcess.recorder.savePlayClick(self.replayProcess.testFilePath, self.replayProcess.playName, self.device.serialNo,
                                                              inputType, x, y, "", True)
                    return
                elif status == 'not found':
                    globals_.traceLogger.debug("Failed to find the target image, even after drag-searching.")
                elif status == 'stop':
                    globals_.traceLogger.debug("User stopped test.")
                    return
            else:
                globals_.traceLogger.debug("Failed to find the target image. Drag search not permitted by configuration.")

                dprint("_tapOrLongPress, bottom of finding loop:", time.time())

            methodRepr = "tap" if inputType == constants.TAP else "longPress"
            callRepr = "{method}(targetImagePath={imgPath}, characters={chars}, chinBarImagePath={chin}, maxWaitTime={wait}, dragSearchPermitted={drag})"
            callRepr = callRepr.format(method=methodRepr, imgPath=quotify(targetImagePath), chars=quotify(characters), chin=quotify(chinBarImagePath), 
                                       wait=maxWaitTime, drag=dragSearchPermitted)
            okprint("failed: " + callRepr)
            raise EventFailedException()


    def _isThisTextPresent(self, imageString, text, isRE=False, maximumAcceptablePercentageDistance=0):
        return self.device.isThisTextPresent(text, imageString, isRE=isRE, maximumAcceptablePercentageDistance=maximumAcceptablePercentageDistance)


    def drag(self, targetImagePath=None, dragRightUnits=None, dragDownUnits=None, dragStartRegion=None, characters=None, 
             waitForStabilization=False):
        # The user or the method writing the output of the recording session should make waitForStabilization 
        # True if there is a tap, long press, or text verification after this drag.

#        dragUsingTargetImage(self, self.orientation, targetImagePath, screenImageString, dragRightUnits, dragDownUnits, dragStartRegion, characters=None):
        if characters:
             okprint("Looking for an image near these characters:", characters)
        screenImageString, screenImageFilename = self.replayProcess._getLatestImageStringFromFile(self.device.serialNo, self.chinBarImageString)
        traceLogger.debug("inputType == constants.DRAG:")
        dragWasPerformed = utils.dragUsingTargetImage(self.device, self.orientation, targetImagePath, screenImageString, 
                                                      dragRightUnits, dragDownUnits, dragStartRegion, characters=characters)
        userWantsToStop = self.replayProcess._getControlMessages()
        if userWantsToStop:
            return

        if dragWasPerformed and waitForStabilization:
            _, _, _ = \
                self.replayProcess.getNewImageString(screenImageString, screenImageFilename, self.device.serialNo, 
                                                     self.chinBarImageString, waitType='stable')
        self.previousInputType = constants.DRAG
        self.previousDragStartRegion = dragStartRegion
        self.previousDragRightUnits = dragRightUnits
        self.previousDragDownUnits = dragDownUnits
        

    def keyEvent(self, keycodes):
        keycodes_ = []
        for thing in keycodes:
            if type(thing) == str:
                for char in thing:
                    keycodes_.append(ord(char))
            else:
                keycodes_.append(thing)
        self.device.EnterTextAndWaitForFinish(keycodes_)
        # XXX Getting the image string after merely entering text may not be necessary.
        # XXX Should we wait a bit?
        userWantsToStop = self.replayProcess._getControlMessages()
        if userWantsToStop:
            return
        self.previousInputType = constants.KEY_EVENT


    def verifyText(self, textToVerify, maxWaitTime=constants.MAX_DEFAULT_WAIT_TIME_TO_FIND_TARGET,
                   dragSearchPermitted=constants.DRAG_SEARCH_PERMITTED, isRE=False,
                   maximumAcceptablePercentageDistance=0):
        # The logic of this test was inefficient and wrong in the master branch (before editable scripts were implemented).
        def callRepr():
             call = "verifyText({txt}, maxWaitTime={wait}, dragSearchPermitted={drag}, isRE={isRE}, "
             call += "maximumAcceptablePercentageDistance={dist})"
             call = call.format(txt=textToVerify, wait=maxWaitTime, dragSearchPermitted=drag, isRE=isRE, 
                                dist=maximumAcceptablePercentageDistance)
             return call

        screenImageString, screenImageFilename = self.replayProcess._getLatestImageStringFromFile(self.device.serialNo,
                                                                                                  self.chinBarImageString)
        _, success = self.device.isThisTextPresent(textToVerify, screenImageString, isRE=isRE,
                                                   maximumAcceptablePercentageDistance=maximumAcceptablePercentageDistance)
        userWantsToStop = self.replayProcess._getControlMessages()
        if userWantsToStop:
            return

        self.previousInputType = constants.TEXT_TO_VERIFY
        if success == constants.SUB_EVENT_PASSED:
            globals_.traceLogger.debug("Found text.")
            status = constants.EVENT_PASSED
            return
        else:
            startTime = time.time()
            success = constants.SUB_EVENT_FAILED
            while time.time() < startTime + maxWaitTime and success != constants.SUB_EVENT_PASSED:
                userWantsToStop = self.replayProcess._getControlMessages()
                if userWantsToStop:
                    return

                _, screenImageString, screenImageFilename = \
                    self.replayProcess.getNewImageString(screenImageString, screenImageFilename, self.device.serialNo,
                                                         self.chinBarImageString, waitType='newFile')
                _, success = self.device.isThisTextPresent(textToVerify, screenImageString, isRE=isRE,
                                                           maximumAcceptablePercentageDistance=maximumAcceptablePercentageDistance)
                if success == constants.SUB_EVENT_PASSED:
                    globals_.traceLogger.debug("Found text.")
                    return
                else:
                    if dragSearchPermitted:
                        try:
                             maxLoc, status, screenImageString, screenImageFilename = \
                                 self._dragSearch(self._isThisTextPresent,
                                                  screenImageString, screenImageFilename,
                                                  textToVerify, isRE, maximumAcceptablePercentageDistance)
                        except Exception, e:
                             dprint('dragsearch exception')
                             bdbg()
                        if status == 'found':
                            globals_.traceLogger.debug("Found text while drag-searching.")                        
                            return
                        elif status == 'not found':
                            globals_.traceLogger.debug("Failed to verify the text, even after drag-searching.")
                        elif status == 'stop':
                            globals_.traceLogger.debug("User stopped test.")
                            return
                    else:
                        globals_.traceLogger.debug("Failed to verify the text. Drag search not permitted by configuration.")
                        okprint("failed: " + callRepr())
                        raise EventFailedException()
            okprint("failed: " + callRepr())
            raise EventFailedException()


    def wait(self, seconds):
        time.sleep(seconds)
        userWantsToStop = self.replayProcess._getControlMessages()
        if userWantsToStop:
            return
        self.previousInputType = constants.WAIT


#         dprint('UserDevice.tap 1, SN', self.device.serialNo)
#         screenImageString, imageFilename = self.replayProcess._getLatestImageStringFromFile(self.device.serialNo, self.device.chinBarImageString)
#         dprint('UserDevice.tap 2')
#         maxLoc, success = utils.tapTargetInImageFile(self.device, screenImageString, targetImagePath, characters=characters)
#         dprint('UserDevice.tap 3')
#         userWantsToStop = self.replayProcess._getControlMessages()
#         dprint('UserDevice.tap 4')
#         if userWantsToStop:
#             return

#         if success == constants.SUB_EVENT_PASSED:
#             dprint('UserDevice.tap 5')
#             # inputEvent.status = constants.EVENT_PASSED
#             x = maxLoc[0]
#             y = maxLoc[1]

#             self.device.tap(x, y) 
# #            self.replayProcess.recorder.savePlayClick(self.replayProcess.testFilePath, self.replayProcess.playName, self.device.serialNo,
# #                                                      inputEvent.inputType, x, y, "", True)


class EventTimeout(Exception):
    pass

