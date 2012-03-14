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



# ***********************************************************************
# NOTE: SOME METHODS HERE BELONG IN gui.py, BUT WERE ORIGINALLY PLACED 
# HERE SO THAT CYTHON COULD BE RUN ON THEM.
# ***********************************************************************



import binascii
import bz2
import ConfigParser
import copy
import cv
import datetime
import distutils
import errno
import httplib
import Image #PIL
import logging
import math
import multiprocessing
import multiprocessing.forking
import optparse
import os
import pythoncom
import random
import re
import shutil
import signal
import socket
import StringIO
import subprocess
import sys
import tarfile
import threading
import time
import traceback
import urllib
import win32api
import win32con
from win32com.shell import shell
import wx
import wx.lib.buttons
import wx.lib.agw.genericmessagedialog as GMD
from wx.lib.embeddedimage import PyEmbeddedImage
import wx.lib.platebtn as platebtn

from arialBaselineIdentification import arialBaselineIdentification
import config
import constants
import cylevenshtein
from deviceFiles import allDeviceConstants
import globals_
from globals_ import *
import gui
import plateButton
import recorder



# http://stackoverflow.com/questions/977275/during-a-subprocess-call-catch-critical-windows-errors-in-python-instead-of-lett
# Prevent the "tesseract.exe has stopped working" dialog from appearing.
win32api.SetErrorMode(
    #win32con.SEM_FAILCRITICALERRORS |
    #win32con.SEM_NOOPENFILEERRORBOX |
    win32con.SEM_NOGPFAULTERRORBOX)


def _scaleImageAndWriteToFile(userDocumentsPath, image, serialNo, width, height):
    #resize the image
    bigScreen = cv.CreateImageHeader((constants.TESSERACT_RESIZE_FACTOR * width,
                                      constants.TESSERACT_RESIZE_FACTOR * height),
                                     cv.IPL_DEPTH_8U, 3)
    cv.SetData(bigScreen,
               chr(255) * 3 * constants.TESSERACT_RESIZE_FACTOR * width * constants.TESSERACT_RESIZE_FACTOR * height)
    cv.Resize(image, bigScreen)

    #write the resized image to file
    bigScreenImageName = constants.TESSERACT_IMAGE_TEMPLATE.format(ser=serialNo)
    bigScreenPath = os.path.join(userDocumentsPath, constants.APP_DIR, bigScreenImageName)
    try:
        cv.SaveImage(bigScreenPath, bigScreen)
    except:
        None, False
    return bigScreenPath, True


def setImageField(imageString, constName, value):
    # let each character that was originally in the byte become the
    # ASCII representation of the character, so
    # '\x4d', which is one byte long, becomes the two bytes '4d',
    # which are '4' ('\x34') and 'd' ('\x64').
    index = getattr(constants, constName)
    imageString = imageString[:index] + value + imageString[index + 2:]
    return imageString


class TestLog:
    def __init__(self):
        pass


# XXX Make this a nested class if it's only used by one other class.
class InputEvent(object):

    # Cython limitation; see http://docs.cython.org/src/userguide/limitations.html.
    @staticmethod
    def getSecondsFromSQLiteString(timeWithSubseconds):
        timeWithSubseconds_ = timeWithSubseconds.split(' ')
        periodIndex = timeWithSubseconds_[1].find('.')
        if periodIndex == -1:
            return float(timeWithSubseconds_[0])
        return float(timeWithSubseconds_[0]) + float(timeWithSubseconds_[1][periodIndex:])


    def __init__(self, indexInDB=None, serialNo=None, startTime=None, inputType=None, x=None, y=None, characters=None,
                 targetImageWidth=None, targetImageHeight=None, targetImageString=None,
                 savedScreenWidth=None, totalHeight=None, savedScreen=None,
                 keyEventsSessionID=None, keycodes=None, textToVerify=None, wait=None,
                 dragStartRegion=None, dragEndRegion=None, dragRightUnits=None,
                 dragDownUnits=None):
        # x and y are device coords, not test tool GUI coords
        # characters is string to find in a tap target
        # dragEndRegion is redundant b/c it's determined by dragStartRegion, dragRightUnits, and dragDownUnits.
        # Ignore it.
        self.indexInDB = indexInDB
        self.serialNo = serialNo
        if type(startTime) == str:
            self.startTime = self.getSecondsFromSQLiteString(startTime)
        else:
            # startTime was provided from the DB and is already a float.
            self.startTime = startTime
        self.inputType = inputType
        # Note that this x and y are the device's x and y, they are not changed
        # here or elsewhere, except when output is necessary, to be the coords
        # relative to the device's current orientation.
        # This member seems to be used only for creation of this object.
        # It is not used during execution of the InputEvent.
        self.pathAndTime = [(x, y, 0)]
        self.characters = characters
        self.targetImageWidth = targetImageWidth
        self.targetImageHeight = targetImageHeight
        self.targetImageString = targetImageString
        self.keyEventsSessionID = keyEventsSessionID
        # Attributes of particular types of events.
        self.keycodes = keycodes or []
        self.textToVerify = textToVerify
        self.wait = wait
        
        # dragStartRegion and dragEndRegion are (orientation-agnostic)
        # (column, row) locations at which the drag started and ended
        self.dragStartRegion = dragStartRegion
        self.dragEndRegion = dragEndRegion
        # dragRightUnits and dragDownUnits are (orientation-agnostic) the number of
        # regions a drag moved to the right and down. Negative numbers indicate
        # movement left and up.
        self.dragRightUnits = dragRightUnits
        self.dragDownUnits = dragDownUnits

        # If this is a click, has an up-click been recorded for this event,
        # thereby marking it fully populated?
        self.isFinished = False
        self.status = constants.EVENT_NOT_EXECUTED

        
    def __repr__(self):
        if self.inputType == constants.KEY_EVENT:
            return "<{typ}: {codes}>".format(typ=self.inputType, codes=str(self.keycodes))
        return "<{typ}>".format(typ=self.inputType)


    def _getElapsedTime(self, timeWithSubseconds):
        timeWithSubseconds_ = self.getSecondsFromSQLiteString(timeWithSubseconds)
        if self.pathAndTime[-1][-1] == 0:
            elapsed = timeWithSubseconds_ - self.startTime
        else:
            elapsed = timeWithSubseconds_ - self.pathAndTime[-1][-1]
        return elapsed


    def addMovement(self, x, y, timeWithSubseconds):
        # x and y are device coords, not TST GUI screen coords

        # This method is useless at the moment, because the path of a drag
        # is determined only from the endpoints of the drag, not by the
        # waypoints added by this method.
        
        # XXX ??? the events have to be in the repo as floats, not strings of
        # a datetimestamp followed by a space followed by the clock seconds
        # with milliseconds. I've found no way to do this in sqlite, but
        # the DB could be post-processed.
        elapsed = self._getElapsedTime(timeWithSubseconds)
        self.pathAndTime += [(x, y, elapsed)]


    def finishDrag(self, x, y, timeWithSubseconds, screenOrientation, appWindowUpperLeftCoord, appWindowWidth, 
                   appWindowHeight, noUpclick=False):
        # Finish creating an inputEvent that has just been recognized as a
        # drag.

        # x and y are device coords, not TST GUI screen coords

        # The user may be dragging through a list of items that
        # look like the target. Therefore, it may be better to perform
        # the drag as it was originally performed. That's why this
        # method gets the regions at which the drag was begun and
        # ended.

        # If noUpclick == True, we're finishing a drag with no ending 
        # up-click b/c the drag went off the screen. Use the last known 
        # point as the up-click. It would be more accurate to 
        # interpolate a point at the edge
        # of the screen, but that's less critical right now.

        def getRegion(x_, y_, windowWidth, windowHeight):
            # Use a 3 x 3 division of the screen into regions, with numbering
            # like that on a telephone keypad, starting at 1 in the upper left
            # and finishing with 9 in the lower right.
            # XXX the constants NUMBER_OF_REGION_COLUMNS/ROWS encode what's hard-coded here in the if/else blocks. 
            #     Remove the hard-coding.
            if x_ < windowWidth / 3.0:
                column = 1
            elif x_ < (2 * windowWidth) / 3.0:
                column = 2
            elif x_ <= windowWidth:
                column = 3
            else:
                raise Exception("x is not in the specified application")

            if y_ < windowHeight / 3.0:
                row = 1
            elif y_ < (2 * windowHeight) / 3.0:
                row = 2
            elif y_ <= windowHeight:
                row = 3
            else:
                raise Exception("y is not in the specified application")

            return column, row
        
        if not noUpclick:
            self.addMovement(x, y, timeWithSubseconds)

        if screenOrientation == constants.LANDSCAPE:
            x_ = self.pathAndTime[0][1] - appWindowUpperLeftCoord[1]
            y_ = self.pathAndTime[0][0] - appWindowUpperLeftCoord[0]
            startColumn, startRow = getRegion(x_, y_, appWindowHeight, appWindowWidth)
            x_ = y - appWindowUpperLeftCoord[1]
            y_ = x - appWindowUpperLeftCoord[0]
            endColumn, endRow = getRegion(x_, y_, appWindowHeight, appWindowWidth)
        else:
            x_ = self.pathAndTime[0][0] - appWindowUpperLeftCoord[0]
            y_ = self.pathAndTime[0][1] - appWindowUpperLeftCoord[1]
            startColumn, startRow = getRegion(x_, y_, appWindowWidth, appWindowHeight)
            x_ = x - appWindowUpperLeftCoord[0]
            y_ = y - appWindowUpperLeftCoord[1]
            endColumn, endRow = getRegion(x_, y_, appWindowWidth, appWindowHeight)

        self.dragStartRegion = (startColumn, startRow)
        self.dragEndRegion = (endColumn, endRow)
        self.dragRightUnits = endColumn - startColumn
        self.dragDownUnits = endRow - startRow


    def pathTraversedIsShort(self, x, y):
        pathDistance = math.sqrt((self.pathAndTime[0][0] - x) ** 2 +
                                 (self.pathAndTime[0][1] - y) ** 2)
        globals_.moveLogger.debug("pathTraversedIsShort()")
        globals_.moveLogger.debug("self.pathAndTime: " + str(self.pathAndTime))
        globals_.moveLogger.debug("x: " + str(x))
        globals_.moveLogger.debug("y: " + str(y))
        globals_.moveLogger.debug("self.pathAndTime[0][0]: " + str(self.pathAndTime[0][0]))
        globals_.moveLogger.debug("self.pathAndTime[0][1]: " + str(self.pathAndTime[0][1]))
        return pathDistance <= constants.LONGEST_TAP_PATH


def createApplicationDirectory(frame=None, showExitDialog=False):
    applicationDir = os.path.join(wx.StandardPaths_Get().GetDocumentsDir(), constants.APP_DIR)
    originalWorkingDir = os.getcwd()
    if not os.path.exists(applicationDir):
        try:
            os.mkdir(applicationDir)
        except:
            if showExitDialog:
                assert frame is not None
                _presentExitNotice(("We tried to create an application directory at {dir} " +
                                   "but failed. Please check the directory permissions.").format(
                        dir=applicationDir),
                                   frame)
            return None, None, False
    return applicationDir, originalWorkingDir, True


def _presentExitNotice(msg, frame):
    dlg = wx.MessageDialog(frame,
                           msg,
                           "Error", # Dialog title
                           wx.OK)
    dlg.ShowModal()
    dlg.Destroy()
    frame.onClose(None)


def groupCoordssByY(coordss):
    # sort coordss by y location
    def third(atuple):
        return atuple[2]
    def second(atuple):
        return atuple[1]
    coordss.sort(key=third)
    # Group coordss by y location
    coordssInLines = []
    coordssIndex = 0
    # Group characters in the alphabet/code base by their size and position on the line.
    # Write a lookup function that maps from a character's grouping and box dimensions to 
    # the baseline (what 'b', 'e', 'l', '.' sit on).
    # Use this baseline, rather than the box bottom, to group chars on a line.

    def getBaselineAndTolerance(coords):
        character = coords[0]
        boxBottom = coords[2]
        boxHeight = boxBottom - coords[4]
        if not arialBaselineIdentification.has_key(character):
            traceLogger.warn("arialBaselineIdentification does not have the character '" + character + "'.")
            # The character was not found in the module that is used to compute
            # baselines. The character could still be valid; return a guess.                    
            return boxBottom, boxHeight
        baseline = boxBottom - arialBaselineIdentification[character][0] * boxHeight
        tolerance = constants.TOLERANCE_TO_X_HEIGHT_RATIO * (boxHeight / arialBaselineIdentification[character][1])
        return baseline, tolerance

    while coordssIndex < len(coordss):
        # pick the first coords
        coordsToMatch = coordss[coordssIndex]
        baselineToMatch, _ = getBaselineAndTolerance(coordsToMatch)
        coordssInLines.append([coordsToMatch])

        coordssIndex += 1
        while coordssIndex < len(coordss):
            try:
                coordsForY = coordss[coordssIndex]
                baselineForY, tolerance = getBaselineAndTolerance(coordsForY)
                # Coordss was sorted by y height, so we only worry about
                # the one half of the +/- tolerance.
                if (baselineForY - tolerance <= baselineToMatch):
                    coordssInLines[-1].append(coordsForY)
                    coordssIndex += 1
                else:
                    break
            except Exception, e:
                dprint('err')
    
    # Sort each horizontal collection of coordss by x in order to find big gaps later.
    for row in coordssInLines:
        row.sort(key=second)
    return coordssInLines


def groupCoordssByX(row):
    def determineSpaceWidthFromCharacter(coords, previousWidth=None, wasGuess=True):
        if not wasGuess:
            return previousWidth, False
        if not arialBaselineIdentification.has_key(coords[0]):
            charWidth = coords[3] - coords[1]
            return (previousWidth or 1.0 * charWidth), True
        charHeight = coords[2] - coords[4]
        return ((constants.SPACE_WIDTH_TO_X_HEIGHT_RATIO * (charHeight / arialBaselineIdentification[coords[0]][1])), 
                False)

    # Find gaps in chars on the same line that are so big they suggest that
    # the chars are not semantically that related.
    xGroupedYGroupedCoordss = []
    xGroupedYGroupedStrings = []

    if len(row) > 1:
        xGroupedYGroupedCoordss += [[row[0]]]
        xGroupedYGroupedStrings += [row[0][0]] 
        mostRecentLeftX = row[0][1]
        mostRecentRightX = row[0][3]
        spaceWidth, wasGuess = determineSpaceWidthFromCharacter(row[0], wasGuess=True)
        for coords_ in row[1:]:
            if (coords_[1] - mostRecentLeftX <= 
                constants.BIG_CHAR_DISTANCE_SCALAR * (mostRecentRightX - mostRecentLeftX)):
                spaceWidth, wasGuess = determineSpaceWidthFromCharacter(coords_, wasGuess=wasGuess, 
                                                                        previousWidth=spaceWidth)
                #charHeight = coords_[2] - coords_[4]
                #xHeight = charHeight / arialBaselineIdentification[coords_[0]][1]
                #if ((coords_[1] - mostRecentRightX) / xHeight) >= constants.SPACE_WIDTH_TO_X_HEIGHT_RATIO:
                if (coords_[1] - mostRecentRightX) >= spaceWidth:
                    # Insert just a single space; identifying the number of spaces would be tricky.
                    xGroupedYGroupedCoordss[-1] += [(' ', mostRecentRightX, row[0][2], coords_[1], row[0][2])]
                    xGroupedYGroupedStrings[-1] += ' '
                xGroupedYGroupedCoordss[-1] += [coords_]
                xGroupedYGroupedStrings[-1] += coords_[0]
            else:
                xGroupedYGroupedCoordss += [[coords_]]
                xGroupedYGroupedStrings += [coords_[0]]
            mostRecentLeftX = coords_[1]
            mostRecentRightX = coords_[3]
    else:
        xGroupedYGroupedCoordss += [[row[0]]]
        xGroupedYGroupedStrings += [row[0][0]]
    return xGroupedYGroupedCoordss, xGroupedYGroupedStrings

                    
def _s2d(achar):
    return int(binascii.b2a_hex(achar), 16)


def _stringToTuplePixels(string, numChannels):
    # XXX this really needs the number of channels and the bit depth
    pixels = []
    if numChannels == 1:
        for i in range(0, len(string), 4):
            pixels.append((_s2d(string[i:i+4]),))
    elif numChannels == 3:
        for i in range(0, len(string), 3):
            pixels.append((_s2d(string[i]), _s2d(string[i + 1]), _s2d(string[i + 2])))
    return pixels


def showImage(string, width, height, numChannels):
    if numChannels == 1:
        image = Image.new("L", (width, height))
    else:
        image = Image.new("RGB", (width, height))
    pixels = _stringToTuplePixels(string, numChannels)
    image.putdata(pixels)
    image.show()


def getOCRText(userDocumentsPath, image, width, height, serialNo, box=False, lines=False):
    # Warning: cannot be called before the App is created, b/c it uses
    # wx.StandardPaths_Get()... methods.

    # Linux:
    # 'w' permission in a dir gives permission to both write files and
    # to create a directory, and there are many hidden directories in
    # ~/ created by other apps, so just create a dir there. That also
    # ensures that you don't need to check for the existence of
    # eng.arial.box (which could have been created by the user)
    # before each time you want to create it.
    # Assume that if it already exists, this hidden directory was
    # created by us.
    dprint("getOCRText start:", time.time())
    imagePath, success = _scaleImageAndWriteToFile(userDocumentsPath, image, serialNo, width, height)
    appDir = os.path.join(userDocumentsPath, #wx.StandardPaths_Get().GetDocumentsDir(),
                          constants.APP_DIR)
    if not success:
        return None, constants.SUB_EVENT_ERRORED
    if sys.platform.startswith('linux'):
        env = {'LD_LIBRARY_PATH':os.path.dirname(wx.StandardPaths_Get().GetExecutablePath())}
    elif sys.platform.startswith('hp-ux'):
        env = {'SHLIB_PATH':os.path.dirname(wx.StandardPaths_Get().GetExecutablePath())}
    elif sys.platform.startswith('aix'):
        env = {'LIBPATH':os.path.dirname(wx.StandardPaths_Get().GetExecutablePath())}
    else:
        env = None

    if 'win' in sys.platform:
        tesseractPath = os.path.join(os.path.dirname(globals_.getExecutableOrRunningModulePath()), 'tesseract.301.exe')
    else:
        tesseractPath = os.path.join(os.path.dirname(globals_.getExecutableOrRunningModulePath()), 'tesseract')

    if box:
        outPath = os.path.join(appDir, "eng.arial.box")
        if os.path.exists(outPath):
            try:
                # Even with the if statement above, this has failed in the past w/ "The system cannot find the 
                # file specified".
                os.remove(outPath)
            except:
                pass

        commandString = (tesseractPath + " {path} eng.arial batch.nochop makebox").format(path=imagePath).split()
        proc = subprocess.Popen(commandString,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    else:
        outPathMinusTXT = os.path.join(appDir, constants.TESSERACT_OUTPUT_TEMPLATE.format(ser=serialNo))
        outPath = outPathMinusTXT + '.txt'
        if os.path.exists(outPath):
            os.remove(outPath)
        commandString = (tesseractPath + " {image} {textOutput}").format(image=imagePath,
                                                                         textOutput=outPathMinusTXT).split()
        proc = subprocess.Popen(commandString,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

    out, err = proc.communicate()
    if not os.path.exists(outPath):
        dprint("error. is imagepath not present? does tesseract not produce any output?")
        if lines:
            return [], constants.SUB_EVENT_FAILED
        return "", constants.SUB_EVENT_FAILED
    try:  # This path is occasionally missing, f/ some reason.
        with open(outPath, 'r') as fp:
            if lines:
                toReturn = fp.readlines()
            else:
                toReturn = fp.read()
    except:
        if lines:
            return [], constants.SUB_EVENT_FAILED
        return "", constants.SUB_EVENT_FAILED
    return toReturn, constants.SUB_EVENT_PASSED


def _superimposeImage(backgroundString, backgroundWidth, backgroundHeight, cvImage,
                      xCenterInBackground, yCenterInBackground, yMargin):
    resizedHeight = 2 * (backgroundHeight - yCenterInBackground - yMargin)
    resizedWidth = cvImage.width * resizedHeight / cvImage.height
    resizedIFF = cv.CreateImageHeader((resizedWidth, resizedHeight),
                                      cv.IPL_DEPTH_8U, 3)
    cv.SetData(resizedIFF, (chr(0) + chr(0) + chr(0)) * resizedWidth * resizedHeight)
    cv.Resize(cvImage, resizedIFF)

    iffTopY = yCenterInBackground - resizedHeight / 2  #(backgroundHeight - resizedHeight) / 2
    iffBottomY = iffTopY + resizedHeight - 1
    iffLeftX = xCenterInBackground - resizedWidth / 2
    iffRightX = iffLeftX + resizedWidth - 1
    iffString = resizedIFF.tostring()

    newBackgroundString = ""
    for rowNumber in range(backgroundHeight):
        leftIndex = rowNumber * backgroundWidth * 3
        # compose rows of new image from solid color image and those of image from file
        if iffTopY <= rowNumber <= iffBottomY:
            iffStringStart = (rowNumber - iffTopY) * resizedWidth * 3
            backgroundStringStart = leftIndex + iffLeftX * 3 + resizedWidth * 3
            newBackgroundRowString = (backgroundString[leftIndex:leftIndex + iffLeftX * 3] + 
                                      iffString[iffStringStart:(rowNumber - iffTopY + 1) * resizedWidth * 3] + 
                                      backgroundString[backgroundStringStart:leftIndex + backgroundWidth * 3])
        else:
            newBackgroundRowString = backgroundString[leftIndex:leftIndex + backgroundWidth * 3]
        newBackgroundString += newBackgroundRowString

    return newBackgroundString


def findTargetInImageFile(self, imageString, targetImagePath, characters=None):
    def findText(targetCharacters):
        # The chin bar is removed from imageString before performing OCR because there's no
        # need for it then, because OCR is performed when processing a recorded test w/o
        # it and so doing so now will improve reproducibility of results, and b/c it may
        # reduce the quality of results.
        dprint("findText start:", time.time())
        if self.chinBarHeight > 0:
            imageString_ = imageString[:-(self.width * self.chinBarHeight * 3)]
        else:
            imageString_ = imageString
        if self.orientation == constants.LANDSCAPE:
            # Note that, if the image string does not contain an alpha channel, the call can be
            # pilImage = Image.frombuffer("RGB", (self.width, self.height), self.imageString, 'raw', "RGB", 0, 1)
            pilImage = Image.frombuffer("RGBA", (self.width, self.height - self.chinBarHeight), 
                                        imageString_, 'raw', "RGBA", 0, 1)
            pilImage = pilImage.rotate(90)
            imageString_ = pilImage.getdata()

        image = cv.CreateImageHeader((self.width, (self.height - self.chinBarHeight)), cv.IPL_DEPTH_8U, 3)
        cv.SetData(image, imageString_)
        lines, success = getOCRText(globals_.getUserDocumentsPath(), image, self.width, 
                                    (self.height - self.chinBarHeight), self.serialNo, box=True, lines=True)
        if success == constants.SUB_EVENT_ERRORED:
            return [], [], success
        if lines[-1] == '':
            dprint('last line of eng.arial.box is EMPTY!!!!!!!!!!!!!!!!!!!!!!!')
        coordss = _getBoxCoords(lines, self.height, self.chinBarHeight)
        coordssInLines = groupCoordssByY(coordss)
        xGroupedYGroupedCoordss, xGroupedYGroupedStrings = [], []
        for row in coordssInLines:
            coordssGrouping, stringsGrouping = groupCoordssByX(row)
            xGroupedYGroupedCoordss += coordssGrouping
            xGroupedYGroupedStrings += stringsGrouping

        dprint("xgroupedygroupedstrings:", xGroupedYGroupedStrings)

        # Accept substrings of the screen text that have a good Levenshtein distance.
        lenTargetCharacters = len(targetCharacters)
        # matchingString is used only for debugging and could be removed later.
        matchingStrings = []
        # matchingStringLocations is a list, ea. element being (x1, y1, x2, y2),
        # where (x1, y1) is the lower left coordinate of the leftmost character,
        # and (x2, y2) is the upper right coordinate of the rightmost character.
        # The element thereby defines a box around a matching string.
        matchingStringLocations = []
        for index, screenString in enumerate(xGroupedYGroupedStrings):
            if len(screenString) <= lenTargetCharacters:
                if (cylevenshtein.distance(screenString, targetCharacters) <= 
                    constants.MAX_LEVENSHTEIN_FOR_TARGET_IDENTIFICATION_FN(lenTargetCharacters)):
                    coordss_ = xGroupedYGroupedCoordss[index]
                    matchingStrings.append(screenString)
                    matchingStringLocations.append((coordss_[0][1], coordss_[0][2], coordss_[-1][3], coordss_[-1][4]))
            else:
                numSubStrings = len(screenString) - lenTargetCharacters + 1
                for i in range(numSubStrings):
                    try:
                        distance = cylevenshtein.distance(screenString[i:i + lenTargetCharacters], targetCharacters)
                    except Exception, e:
                        dprint('err')
                    if distance <= constants.MAX_LEVENSHTEIN_FOR_TARGET_IDENTIFICATION_FN(lenTargetCharacters):
                        matchingStrings.append(screenString[i:i + lenTargetCharacters])
                        matchingStringLocations.append((xGroupedYGroupedCoordss[index][i][1], 
                                                        xGroupedYGroupedCoordss[index][i][2], 
                                                        xGroupedYGroupedCoordss[index][i + lenTargetCharacters - 1][3], 
                                                        xGroupedYGroupedCoordss[index][i + lenTargetCharacters - 1][4]))

        return matchingStringLocations, matchingStrings, constants.SUB_EVENT_PASSED


    def coordsNearStringLocations(coords, matchingStringLocations):
        for leftX, lowerY, rightX, upperY in matchingStringLocations:
            # A tall box centered on the matching string defines the
            # boundary within which coords must exist.
            tallBox = (max(leftX - constants.TEXT_AND_IMAGE_X_MARGIN, 0),
                       max(lowerY - constants.TEXT_AND_IMAGE_Y_MARGIN, 0),
                       max(rightX + constants.TEXT_AND_IMAGE_X_MARGIN, self.width),
                       max(upperY + constants.TEXT_AND_IMAGE_Y_MARGIN, self.height))
            if (tallBox[0] <= coords[0] <= tallBox[2] and
                tallBox[1] <= coords[1] <= tallBox[3]):
                return True
        return False


    def getImageMatchLocation(minimumMatchValue, resultMap, mask):
        # Returns the highest MatchTemplate match location
        # and the mask to use to find the next match, if desired.
        # The mask prevents old matches from being found repeatedly.
        (minVal, maxVal, minLoc, maxLoc) = cv.MinMaxLoc(resultMap, mask)
        if maxVal < minimumMatchValue:
            #traceLogger.debug("Template match is NOT acceptable. Score: " + str(maxVal))
            return None, maxVal, None

        #traceLogger.debug("Acceptable template match found at " + str(maxVal))

        resultWidth = resultMap.width
        resultHeight = resultMap.height

        # The mask is hard-coded here to be a 5 x 5 square.
        maskLeftX = max(maxLoc[0] - 2, 0)
        maskRightX = min(resultWidth, maxLoc[0] + 2)
        maskWidth = maskRightX - maskLeftX + 1
        maskTopY = max(maxLoc[1] - 2, 0)
        maskBottomY = min(resultHeight, maxLoc[1] + 2)
        maskHeight = maskBottomY - maskTopY + 1

        maskString = mask.tostring()
        newMaskString = ""
        for rowNumber in range(resultHeight):
            leftIndex = rowNumber * resultWidth
            if maskTopY <= rowNumber <= maskBottomY:
                maskStringStart = leftIndex + maskLeftX + maskWidth
                newMaskString += (maskString[leftIndex:leftIndex + maskLeftX] + 
                                  chr(0) * maskWidth + maskString[maskStringStart:leftIndex + resultWidth])
            else:
                newMaskString += maskString[leftIndex:leftIndex + resultWidth]
        maskString = newMaskString
        cv.SetData(mask, maskString)
        return maxLoc, maxVal, mask


    invertedColorTargetImage = cv.LoadImage(targetImagePath, cv.CV_LOAD_IMAGE_COLOR)
    targetImage = cv.CreateImageHeader((invertedColorTargetImage.width, invertedColorTargetImage.height), 
                                       cv.IPL_DEPTH_8U, 3)
    cv.SetData(targetImage, invertedColorTargetImage.tostring())
    # cv.CV_RGB2BGR or cv.CV_BGR2RGB, I don't know which is correct and it doesn't matter; 
    # they do the same thing.
    cv.CvtColor(invertedColorTargetImage, targetImage, cv.CV_RGB2BGR)
    targetImageString = targetImage.tostring()
    dprint("targetImageString[:50]:", targetImageString[:50])
    target = cv.CreateImageHeader((targetImage.width, targetImage.height), cv.IPL_DEPTH_8U, 3)
    cv.SetData(target, targetImageString)
    if constants.DEBUGGING_IMAGE_FINDING:
        showImage(targetImageString, targetImage.width, targetImage.height, 3)
    screen = cv.CreateImageHeader((self.width, self.height), cv.IPL_DEPTH_8U, 3)
    cv.SetData(screen, imageString)

    resultWidth = self.width - targetImage.width + 1
    resultHeight = self.height - targetImage.height + 1
    resultMap = cv.CreateImageHeader((resultWidth, resultHeight),
                                     cv.IPL_DEPTH_32F,
                                     1)
    cv.SetData(resultMap, (chr(0) + chr(0) + chr(0) + chr(0)) * resultWidth * resultHeight * 1)
    if len(imageString) == 0:
        dprint('error')
        bdbg()
    dprint("matchtemplate, len(imageString):", len(imageString))
    dprint("matchtemplate, len(targetImageString):", len(targetImageString))
    #dprint("self.width:", self.width)
    #dprint("self.height:", self.height)
    cv.MatchTemplate(screen, target, resultMap, cv.CV_TM_CCOEFF_NORMED)
    dprint('after matchtemplate')
    mask = cv.CreateImageHeader((resultWidth, resultHeight),
                                cv.IPL_DEPTH_8U,
                                1)
    cv.SetData(mask, chr(255) * resultWidth * resultHeight)

    maxLoc, maxVal, mask = getImageMatchLocation(constants.TEMPLATE_MATCH_MINIMUM, resultMap, mask)
    if maxLoc is None:
        globals_.imageFindingLogger.debug("findTargetFromInputEvent(): no image match was found.")
        return None, constants.SUB_EVENT_FAILED

    if not characters:
        maxLocInScreen = (maxLoc[0] + target.width / 2,
                          maxLoc[1] + target.height / 2)
        logMessage = "findTargetFromInputEvent(): an image match (with score " + str(maxVal) 
        logMessage += ") was found and there are no characters in the inputEvent"
        globals_.imageFindingLogger.debug(logMessage)
        return maxLocInScreen, constants.SUB_EVENT_PASSED
    else:
        traceLogger.debug("characters: " + characters)
        matchingStringLocations, matchingStrings, success = findText(characters)
        if success == constants.SUB_EVENT_ERRORED:
            return None, constants.SUB_EVENT_ERRORED
        elif matchingStringLocations == []:
            globals_.traceLogger.debug("findTargetFromInputEvent(): no matching strings were found.")
            return None, constants.SUB_EVENT_FAILED
        globals_.traceLogger.debug("matching strings:" + '|'.join(matchingStrings))


    while True:
        # The result map is reduced in size by the dimensions of the target.
        maxLocInScreen = (maxLoc[0] + target.width / 2,
                          maxLoc[1] + target.height / 2)

        # If maxLoc is within some range of the text, accept the image match.
        # OCR isn't very reliable, so sorting the candidates by text match
        # distance may not be a good idea. Just return the best image
        # match, which is the first.
        if coordsNearStringLocations(maxLocInScreen, matchingStringLocations):
            imageLoggerMessage = "findTargetFromInputEvent(): a matching string was found near an image match having "
            imageLoggerMessage += "score " + str(maxVal)
            globals_.imageFindingLogger.debug(imageLoggerMessage)
            dprint("maxLocInScreen", maxLocInScreen)
            return maxLocInScreen, constants.SUB_EVENT_PASSED
        else:
            imageLoggerMessage = "findTargetFromInputEvent(): a matching image was found but the required characters "
            imageLoggerMessage += "are not near it. Searching for other matches."
            globals_.imageFindingLogger.debug(imageLoggerMessage)

        maxLoc, maxVal, mask = getImageMatchLocation(constants.TEMPLATE_MATCH_MINIMUM, resultMap, mask)
        if maxLoc is None:
            # There won't be any further matches b/c getImageMatchLocation
            # processes them in order from best to worst.
            imageLoggerMessage = "findTargetFromInputEvent(): there are no more matching images in the screen and "
            imageLoggerMessage += "there are characters in the inputEvent."
            globals_.imageFindingLogger.debug(imageLoggerMessage)
            return None, constants.SUB_EVENT_FAILED


def _getBoxCoords(lines, height, chinBarHeight):
    # Returns the coordinates in lines after scaling down the results to their
    # original, pre-OCR, size and returning the y-coordinates to their original,
    # downward-increasing direction.
    coords = []
    for line in lines:
        try:
            char, leftX, lowerY, rightX, upperY, _ = line.split()
        except Exception, e:
            bdbg()
            dprint("EXCEPTION!!!!!!!!!!!!!!!!!!!!:", e)
            dprint("line!!!!!!!!!!!!!!:", line)
        leftX, lowerY, rightX, upperY = int(leftX), int(lowerY), int(rightX), int(upperY)
        coords += [(char, leftX / constants.TESSERACT_RESIZE_FACTOR, 
                    (height - chinBarHeight) - lowerY / constants.TESSERACT_RESIZE_FACTOR,
                    rightX / constants.TESSERACT_RESIZE_FACTOR, 
                    (height - chinBarHeight) - upperY / constants.TESSERACT_RESIZE_FACTOR)]
    return coords


def identifyTargetFromTap(x, y, screenWidth, totalHeight, chinBarHeight, orientation, savedScreen, ocrBoxText):
    # XXX modify tesseract or my call to it to get the output sent to stdout

    def getCharBoxDistance(atuple, x, y):
        # Keep the calc simple for now.
        char, leftX, lowerY, rightX, upperY = atuple
        return math.sqrt((leftX - x) ** 2 + (lowerY - y) ** 2)

    def getNeighboringChars(atuple, coordss):
        # Initial algorithm, not implemented:
        # get the coords of chars on the same horizontal line
        # order these chars by their leftXs
        # calculate the distance between each adjacent char and order these distances.
        # If a sudden increase is noted in these sorted distances, the increase may be
        # due to going from distances between characters that do not have a space between
        # them and those that do. Use the lowest distance after the increase as the space
        # size.
        # Walk to the left and then to the right, identifying where spaces may be in
        # order to identify words.
        # Return at most X words centered on the word containing the chosen char.
        #
        # New algorithm, below:
        # get the coords of chars on the same horizontal line
        # order these chars by their leftXs
        # Get at most X chars on the left and right of the chosen char.
        # In the algorithm to identify tap targets during replay, use string distance.
        leftX, lowerY, rightX, upperY = atuple
        
        coordssInLines = groupCoordssByY(coordss)

        doBreak = False
        for line in coordssInLines:
            for closestCharIndex, (char_, leftX_, lowerY_, rightX_, upperY_) in enumerate(line):
                if leftX_ == leftX and lowerY_ == lowerY:
                    doBreak = True
                    break
            if doBreak:
                break
        doBreak = False
        xGroupedYGroupedCoordss, xGroupedYGroupedStrings = groupCoordssByX(line)
        for xGrouping in xGroupedYGroupedCoordss:
            for closestCharIndex, (char_, leftX_, lowerY_, rightX_, upperY_) in enumerate(xGrouping):
                if leftX_ == leftX and lowerY_ == lowerY:
                    doBreak = True
                    break
            if doBreak:
                break

        chars = []
        if len(xGrouping) > 0:
            charIndex = closestCharIndex - 1
            numCharsAdded = 0
            xGroupingStart = max(0, closestCharIndex - constants.NUM_CHARS_FOR_TAP_IDENTIFICATION / 2)
            xGroupingStop = min(len(xGrouping), closestCharIndex + constants.NUM_CHARS_FOR_TAP_IDENTIFICATION / 2)
            chars = xGrouping[xGroupingStart:xGroupingStop]
        return chars

    if not ocrBoxText:
        chars = []
    else:
        lines = ocrBoxText.split('\n')

        coordss = _getBoxCoords(lines, totalHeight, chinBarHeight)
        # get the closest box w/in some radius
        closest = ()
        charHeight = 0
        closestDistance = math.sqrt(screenWidth ** 2 + totalHeight ** 2)
        for (char, leftX, lowerY, rightX, upperY) in coordss:
            if (((x - constants.MAX_CHAR_BOX_DISTANCE) <= leftX <= (x + constants.MAX_CHAR_BOX_DISTANCE)) and
                ((y - constants.MAX_CHAR_BOX_DISTANCE) <= lowerY <= (y + constants.MAX_CHAR_BOX_DISTANCE))):
                # The above 'if' serves to reduce computation. May be unnecessary.
                distance = getCharBoxDistance((char, leftX, lowerY, rightX, upperY), x, y)
                if distance < closestDistance:
                    closest = (char, leftX, lowerY, rightX, upperY)
                    closestDistance = distance
                    charHeight = lowerY - upperY
        chars = []
        if (closestDistance == 0 or 
            float(charHeight) / closestDistance >= constants.MINIMUM_CHARACTER_HEIGHT_DISTANCE_RATIO):
            # If the box height of the closest character is greater than some percentage of the distance to the
            # character, the user may in fact have been tapping on the text.
            chars = getNeighboringChars(closest[1:], coordss)

    return chars


def getRegionCenterCoords(self, orientation, region):
    # self is an instance of gui.py:Device.
    regionColumn = region[0]
    regionRow = region[1]
    if orientation in (constants.PORTRAIT, constants.UNKNOWN_SCREEN_ORIENTATION):
        regionWidth = self.width / float(constants.NUMBER_OF_REGION_COLUMNS)
        regionHeight = self.height / float(constants.NUMBER_OF_REGION_ROWS)
    else:
        regionHeight = self.width / float(constants.NUMBER_OF_REGION_COLUMNS)
        regionWidth = self.height / float(constants.NUMBER_OF_REGION_ROWS)

    x = regionWidth * (regionColumn - 1 + 0.5)
    y = regionHeight * (regionRow - 1 + 0.5)
    return x, y


def _getCoordsAtMoveEnd(self, orientation, x, y, rightUnits, downUnits):
    # self is an instance of gui.py:Device.
    if orientation in (constants.PORTRAIT, constants.UNKNOWN_SCREEN_ORIENTATION):
        regionWidth = self.width / float(constants.NUMBER_OF_REGION_COLUMNS)
        regionHeight = self.height / float(constants.NUMBER_OF_REGION_ROWS)

        # For now, just do the simple thing and drag by the number of regions or to the screen
        # edge, whichever is less.
        try:
            newX = x + rightUnits * regionWidth
            newY = y + downUnits * regionHeight
        except Exception, e:
            bdbg()
            dprint('err')

    else:
        regionWidth = self.height / float(constants.NUMBER_OF_REGION_COLUMNS)
        regionHeight = self.width / float(constants.NUMBER_OF_REGION_ROWS)

        # For now, just do the simple thing and drag by the number of regions or to the screen
        # edge, whichever is less.
        # The new x and y can be calculated w/o changing the coordinate system.
        # In this case, dragRightUnits means add to y, and dragDownUnits means subtract
        # from x.
        newX = x - downUnits * regionHeight
        newY = y + rightUnits * regionWidth

    return newX, newY


def dragUsingTargetImage(self, orientation, targetImagePath, screenImageString, dragRightUnits, dragDownUnits, 
                         dragStartRegion, characters=None):
    # self is an instance of gui.py:Device.
    maxLoc, success = findTargetInImageFile(self, screenImageString, targetImagePath, characters=characters)
    if success == constants.SUB_EVENT_PASSED:
        traceLogger.debug("Found drag target at " + str(maxLoc))
        x = maxLoc[0]
        y = maxLoc[1]
        newX, newY = _getCoordsAtMoveEnd(self, orientation, x, y, dragRightUnits, dragDownUnits)
    else:
        # drag inputevents start region to destination region
        if orientation in (constants.PORTRAIT, constants.UNKNOWN_SCREEN_ORIENTATION):
            regionWidth = self.width / float(constants.NUMBER_OF_REGION_COLUMNS)
            regionHeight = self.height / float(constants.NUMBER_OF_REGION_ROWS)

        else:
            regionWidth = self.height / float(constants.NUMBER_OF_REGION_COLUMNS)
            regionHeight = self.width / float(constants.NUMBER_OF_REGION_ROWS)

        x = regionWidth * (dragStartRegion[0] - 1 + 0.5)
        y = regionHeight * (dragStartRegion[1] - 1 + 0.5)
        newX = x + regionWidth * dragRightUnits
        newY = y + regionHeight * dragDownUnits
        traceLogger.debug("Did not find drag target. Dragging from (" + str(x) + ", " + str(y) + ") to (" + str(newX) +
                          ", " + str(newY) + ")")

    # For now, just do the simple thing and drag by the number of regions or to the screen
    # edge, whichever is less.
    if newX < 0:
        newX = 0
    elif newX > self.width:
        newX = self.width
    if newY < 0:
        newY = 0
    elif newY > self.height:
        newY = self.height

    # dragging nowhere serves no purpose and could be interpreted as a tap
    if not (x == newX and y == newY):
        globals_.traceLogger.debug("dragUsingInputEvent: dragging from (%d, %d) to (%d, %d)", x, y, newX, newY)
        self.drag(x, y, newX, newY)
        # True means that the drag was performed
        return True
    return False


# Originally in IndividualTestManager.
def packageInputEvents(self, clicks, deviceData, testFilePath, chinBarImageString):
    globals_.traceLogger.debug("packageInputEvents start")
    def finishPreviousEvent(inputEvents, serialNo, orientation=None, appWindowWidth=None, appWindowHeight=None):
        # orientation, appWindowWidth, appWindowHeight are provided for drags
        # with no final up-click.
        if inputEvents[serialNo] == []:
            # This down-click is handled following this if-else block.
            pass
        elif inputEvents[serialNo][-1].inputType == constants.TAP_DRAG_OR_LONG_PRESS:
            # A mouse drag went off the screen before the up-click occurred.
            # XXX This will not be a concern if the mouse is captured in
            # the future; the up-click will be recorded; at that point we
            # should be able to remove this 'if' block.
            if inputEvents[serialNo][-1].pathAndTime[-1][-1] == 0:
                # There was no point in the previous event following the first click.
                # How odd. Call the previous one a tap.
                inputEvents[serialNo][-1].inputType = constants.DRAG
            else:
                inputEvents[serialNo][-1].inputType = constants.DRAG

            x, y, _ = inputEvents[serialNo][-1].pathAndTime[-1]
            inputEvents[serialNo][-1].finishDrag(x, y, None, orientation, (0, 0),
                                                 appWindowWidth, appWindowHeight, noUpclick=True)
            inputEvents[serialNo][-1].isFinished = True

    serialNumbers = set([x[0] for x in clicks])
    inputEvents = {}

    waitCount = 0

    self.killAllOCRBoxProcesses()
    process = self.startOCRBoxProcess(testFilePath)
    # XXX dangerous if the process doesn't return f/ some reason
    process.join()
    
    ocrBoxLists = self.recorder.getOCRBoxData(testFilePath)
    ocrBoxData = {}
    for serialNo, timeWithSubseconds, text in ocrBoxLists:
        ocrBoxData[(serialNo, timeWithSubseconds)] = text

    bdbg()
    testName = os.path.basename(testFilePath).rsplit('.', 1)[0]
    for serialNo, timeWithSubseconds, clickType, x, y, targetImageWidth, targetImageHeight, imageFilename, index_, keyEventsSessionID, keycode, text, wait in clicks:
        dprint('packageInputEvents, 1')

        if not serialNo:
            # XXX When does this happen?
            (screenWidth, totalHeight, chinBarHeight, chinBarImageString, orientation) = (None, None, None, None, None)
        else:
            (screenWidth, totalHeight, chinBarHeight, chinBarImageString, orientation) = deviceData[serialNo]

        if imageFilename:
            (screenWidth, totalHeight, chinBarHeight, chinBarImageString, orientation) = deviceData[serialNo]
            try:
                image = Image.open(os.path.join('tests', testName, imageFilename))
            except Exception, e:
                dprint("ERROR OPENING FILE!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                bdbg()
            # about 0.01 seconds
            imageString = image.tostring() + chinBarImageString
            targetImageLeftX = max(x - constants.TARGET_IMAGE_SQUARE_WIDTH / 2 + constants.EVEN_WIDTH_ADDITION, 0)
            targetOuter = x + constants.TARGET_IMAGE_SQUARE_WIDTH / 2 + constants.TARGET_IMAGE_SQUARE_WIDTH % 2
            # Subtract 1 from the width because the array is 0-based.
            targetImageRightX = min(screenWidth - 1, targetOuter)
            targetImageWidth = targetImageRightX - targetImageLeftX + 1
            targetImageTopY = max(y - constants.TARGET_IMAGE_SQUARE_WIDTH / 2 + constants.EVEN_HEIGHT_ADDITION, 0)
            targetOuter = y + constants.TARGET_IMAGE_SQUARE_WIDTH / 2 + constants.TARGET_IMAGE_SQUARE_WIDTH % 2
            # Subtract 1 from the height because the array is 0-based.
            targetImageBottomY = min(totalHeight - 1, targetOuter)
            targetImageHeight = targetImageBottomY - targetImageTopY + 1

            # get the rows of the target image into an array
            targetImageString = ""
            # Northwest zero means bottom is larger than top.
            for rowIndex in range(targetImageTopY, targetImageBottomY + 1):
                leftPixelIndex = (rowIndex * screenWidth * constants.NUMBER_OF_IMAGE_CHANNELS + 
                                  targetImageLeftX * constants.NUMBER_OF_IMAGE_CHANNELS)
                # zero-indexed row number * length of row in pixels * number of channels + 
                #     zero-indexed column number * number of channels
                rightPixelIndex = (rowIndex * screenWidth * constants.NUMBER_OF_IMAGE_CHANNELS + 
                                   targetImageRightX * constants.NUMBER_OF_IMAGE_CHANNELS)
                # Adding constants.NUMBER_OF_IMAGE_CHANNELS to add the rightmost pixel.
                imageStringAddition = imageString[leftPixelIndex : rightPixelIndex + constants.NUMBER_OF_IMAGE_CHANNELS]
                targetImageString += imageStringAddition

        # This if-block covers:
        # [start] down down
        # [start] down move
        # [start] down up
        # [start] move down
        # [start] move move
        # [start] move up
        # [start] up [down, move, up - take your pick]
        x_ = int(x)
        y_ = int(y)
        if imageFilename != '' and len(targetImageString) == 0:
            bdbg()
        clickType_ = int(clickType)
        if serialNo not in inputEvents:
            inputEvents[serialNo] = []

        if clickType_ == constants.LEFT_DOWN_CLICK:
            dprint('packageInputEvents, 2')
            try:
                finishPreviousEvent(inputEvents, serialNo, orientation, screenWidth, totalHeight)
            except Exception, e:
                pass

            try:
                ocrBoxText = ocrBoxData[(serialNo, timeWithSubseconds)].rstrip()
            except Exception, e:
                dprint("the ocr box data for this click was not found")
                dprint(str(e))
                dprint("keyEventsSessionID:", keyEventsSessionID)
                characters = []
            else:
                # We're now ignoring targetImage* from the clicks variable above because the functionality has been
                # moved to identifyTargetFromTap. XXX remove the storage of targetImage* to the immeidate storage of 
                # clicks.

                characters = identifyTargetFromTap(x_, y_, screenWidth, totalHeight, chinBarHeight, orientation, 
                                                   None, ocrBoxText)

            inputEvents[serialNo].append(InputEvent(serialNo=serialNo,
                                                    startTime=timeWithSubseconds,
                                                    inputType=constants.TAP_DRAG_OR_LONG_PRESS,
                                                    x=x_, y=y_,
                                                    targetImageWidth=targetImageWidth,
                                                    targetImageHeight=targetImageHeight, 
                                                    targetImageString=targetImageString,
                                                    characters=''.join([x[0] for x in characters]),
                                                    savedScreenWidth=screenWidth, totalHeight=totalHeight))

        elif clickType_ == constants.LEFT_UP_CLICK:
            if inputEvents[serialNo] == []:
                # It's possible that an up-click was registered when recording
                # began b/c the user had been holding the button down.
                # Disregard it.
                continue
            elif inputEvents[serialNo][-1].isFinished:
                # This up-click follows a complete event, such as a full
                # down-and-up-click package or text entry. It may have
                # occurred if the user dragged his mouse onto the GUI and
                # then lifted up. Disregard the event.
                continue
            elif (inputEvents[serialNo][-1].inputType == constants.TAP_DRAG_OR_LONG_PRESS and
                  inputEvents[serialNo][-1].pathTraversedIsShort(x_, y_) and
                  (inputEvents[serialNo][-1].getSecondsFromSQLiteString(timeWithSubseconds) -
                   inputEvents[serialNo][-1].startTime) >= constants.LONG_PRESS_TIME_FOR_RECOGNITION):
                # XXX It would be better to determine whether the event was a long press by
                # the device's response, rather than the duration.
                inputEvents[serialNo][-1].inputType = constants.LONG_PRESS
                inputEvents[serialNo][-1].isFinished = True
            elif (inputEvents[serialNo][-1].inputType == constants.TAP_DRAG_OR_LONG_PRESS and
                  inputEvents[serialNo][-1].pathTraversedIsShort(x_, y_)):
                # event duration is short; this is a tap
                inputEvents[serialNo][-1].inputType = constants.TAP
                inputEvents[serialNo][-1].isFinished = True
            elif inputEvents[serialNo][-1].inputType == constants.TAP_DRAG_OR_LONG_PRESS:
                inputEvents[serialNo][-1].inputType = constants.DRAG
                inputEvents[serialNo][-1].finishDrag(x_, y_, timeWithSubseconds, orientation, (0, 0),
                                                     screenWidth, totalHeight)
                inputEvents[serialNo][-1].isFinished = True                    
            else:
                raise Exception("Unrecognized state.")

        elif clickType_ == constants.LEFT_MOVE:
            if (inputEvents[serialNo] == [] or
                inputEvents[serialNo][-1].isFinished):
                # A move may have been begun from outside the GUI. (It may be
                # possible; I don't know.)
                inputEvents[serialNo].append(InputEvent(serialNo=serialNo, startTime=timeWithSubseconds, 
                                                        inputType=constants.TAP_DRAG_OR_LONG_PRESS, x=x_, y=y_, 
                                                        targetImageWidth=targetImageWidth,
                                                        targetImageHeight=targetImageHeight, 
                                                        targetImageString=targetImageString,
                                                        savedScreenWidth=screenWidth, totalHeight=totalHeight))
            elif inputEvents[serialNo][-1].inputType == constants.TAP_DRAG_OR_LONG_PRESS:
                # Only a down click has been recorded for the event in-progress.
                inputEvents[serialNo][-1].addMovement(x_, y_, timeWithSubseconds)
            else:
                raise Exception("Unrecognized state.")

        elif clickType_ == constants.KEY_EVENT:
            finishPreviousEvent(inputEvents, serialNo)
            if (inputEvents[serialNo] == [] or
                inputEvents[serialNo][-1].inputType != constants.KEY_EVENT or
                inputEvents[serialNo][-1].keyEventsSessionID != keyEventsSessionID):
                inputEvents[serialNo].append(InputEvent(serialNo=serialNo, startTime=timeWithSubseconds,
                                                        inputType=constants.KEY_EVENT,
                                                        keyEventsSessionID=keyEventsSessionID))
            inputEvents[serialNo][-1].keycodes.append(keycode)

        elif clickType_ == constants.TEXT_TO_VERIFY:
            finishPreviousEvent(inputEvents, serialNo)
            inputEvents[serialNo].append(InputEvent(serialNo=serialNo, startTime=timeWithSubseconds,
                                                    inputType=constants.TEXT_TO_VERIFY,
                                                    textToVerify=text))

        elif clickType_ == constants.WAIT:
            finishPreviousEvent(inputEvents, serialNo)
            inputEvents[serialNo].append(InputEvent(serialNo=serialNo, startTime=timeWithSubseconds,
                                                    inputType=constants.WAIT,
                                                    wait=wait))

        else:
            dprint('input type not recognized')
            raise Exception("input type not recognized")

    for click in clicks:
        serialNo = click[0]
        # No harm done if this isn't necessary. I think it's only necessary
        # when the last move was a drag w/ no up click.
        finishPreviousEvent(inputEvents, serialNo, orientation, screenWidth, totalHeight)
    globals_.traceLogger.debug("packageInputEvents end")
    return inputEvents


# Originally in AppFrame.
@profile()
def AppFrame__init__(self, parent, app):
    wx.Frame.__init__(self, parent, -1, self.title, size=(800,600),
                      style=wx.DEFAULT_FRAME_STYLE) #| wx.NO_FULL_REPAINT_ON_RESIZE)

    self.Bind(wx.EVT_CLOSE, self.onClose)

    # Configuration, filesystem, etc.
    self.applicationDir, self.originalWorkingDir, success = createApplicationDirectory(frame=self,
                                                                                       showExitDialog=True)
    if not success:
        return
    os.chdir(self.applicationDir)

    for thing in os.listdir('.'):
        # Just as an explore...png file can arrive at the device
        # object after playback has started, a play...png file
        # can arrive after it has finished. These files should
        # not need to be in the 'plays' directory. They are
        # created after other 'plays...png' files have been 
        # moved to the 'plays' directory, and can be deleted
        # upon startup here.
        if ((thing.startswith('explore') or thing.startswith('play') or thing.startswith('record')
             or thing.startswith('pause'))
            and thing.endswith('.png')):
            try:
                os.remove(thing)
            except:
                pass

    # config.py (user configuration) population. Must come before creation
    # of the keycode combobox.
    success, message = Config.populateConfigModule()
    if not success:
        dlg = wx.MessageDialog(None,
                               message,
                               "Error", # Dialog title
                               wx.OK)
        dlg.ShowModal()
        dlg.Destroy()
        sys.exit(1)

    self.playAndRecordPanel = wx.Panel(self, -1)
    self.playAndRecordPanelSizer = wx.BoxSizer(wx.VERTICAL)

    # Create StaticBox before creating the siblings it contains.
    #playRecordLabel = wx.StaticText(self.playAndRecordPanel, label="Play/Record")
    font = wx.Font(9, family=wx.DEFAULT, style=wx.NORMAL, weight=wx.BOLD)
    #playRecordLabel.SetFont(font)        
    self.playAndRecordBox = wx.StaticBox(self.playAndRecordPanel, -1, "Play && Record")
    self.playAndRecordBox.SetFont(font)
    self.playAndRecordSizer = wx.StaticBoxSizer(self.playAndRecordBox, wx.VERTICAL)
    self.audioBarPanel = self.buildAudioBar(self.playAndRecordPanel)
    self.playAndRecordSizer.Add((constants.PLAY_AND_RECORD_PANEL_WIDTH, 10))
    self.playAndRecordSizer.Add(self.audioBarPanel, 0, wx.ALIGN_CENTER)
    self.playAndRecordSizer.Add(wx.StaticLine(self.playAndRecordPanel, -1, 
                                              size=(constants.PLAY_AND_RECORD_PANEL_WIDTH - 10,-1)),
                                0, wx.ALL, 5)        

    self.keycodeSizer = self.makeKeycodeControls()
    self.playAndRecordSizer.Add(self.keycodeSizer, flag=wx.ALIGN_CENTER)

    self.playAndRecordSizer.Add((1, 20))  

    # Recording Tools
    self.recordingToolsBox = wx.StaticBox(self.playAndRecordPanel, -1, "Record")
    self.recordingToolsBox.SetFont(font)
    self.recordingToolsBox.Disable()
    self.recordingToolsSizer = wx.StaticBoxSizer(self.recordingToolsBox, wx.VERTICAL)
    self.textVerificationSizer = wx.BoxSizer(wx.VERTICAL)
    self.verifyTextLabel = wx.StaticText(self.playAndRecordPanel, label="Find text:")
    self.verifyTextLabel.Disable()
    self.textVerificationSizer.Add(self.verifyTextLabel, border=5, flag=wx.ALIGN_CENTER | wx.TOP)
    self.verifyTextBox = wx.TextCtrl(self.playAndRecordPanel, size=(300, constants.TEXT_BOX_DEFAULT_HEIGHT))
    self.verifyTextBox.Bind(wx.EVT_CHAR, self.onVerifyTextChar)
    self.verifyTextBox.Disable()
    self.enterTextBtn = wx.Button(self.playAndRecordPanel, gui.wxID_ENTER_TEXT, "Verify Text")
    self.textVerificationSizer.Add(self.verifyTextBox, 0, border=5, flag=wx.ALIGN_CENTER | wx.TOP)
    # I've tried a border around the button with no success.
    self.textVerificationSizer.Add(self.enterTextBtn, 0, border=5, flag=wx.ALIGN_CENTER | wx.TOP) 
    self.enterTextBtn.Bind(wx.EVT_BUTTON, self.onVerifyTextEntry, id=gui.wxID_ENTER_TEXT)
    self.enterTextBtn.Disable()
    self.recordingToolsSizer.Add(self.textVerificationSizer)

    self.recordingToolsSizer.Add(wx.StaticLine(self.playAndRecordPanel, -1, 
                                               size=(constants.PLAY_AND_RECORD_PANEL_WIDTH - 10,-1)),
                                 0, wx.ALL, 5)

    self.waitSizer = wx.BoxSizer(wx.HORIZONTAL)
    self.waitTextBox = wx.TextCtrl(self.playAndRecordPanel, size=(40, constants.TEXT_BOX_DEFAULT_HEIGHT))
    self.waitTextBox.Bind(wx.EVT_CHAR, self.onWaitChar)
    self.waitTextBox.Disable()
    self.enterWaitBtn = wx.Button(self.playAndRecordPanel, gui.wxID_ENTER_WAIT_TIME, "Wait (sec.)")
    self.enterWaitBtn.Disable()
    self.waitSizer.Add(self.waitTextBox)
    self.waitSizer.Add(self.enterWaitBtn, 0, wx.ALIGN_RIGHT)

    self.enterWaitBtn.Bind(wx.EVT_BUTTON, self.onWaitEntry, id=gui.wxID_ENTER_WAIT_TIME)
    self.recordingToolsSizer.Add(self.waitSizer, 0, wx.ALIGN_CENTER)
    self.playAndRecordSizer.Add(self.recordingToolsSizer)
    self.recordingToolsSizer.Fit(self.playAndRecordPanel)

    self.eventsBoxQueue = multiprocessing.Queue()

    self.playAndRecordPanelSizer.Add((1, 5))
    self.playAndRecordPanelSizer.Add(self.playAndRecordSizer, border=5, flag=wx.LEFT | wx.RIGHT)
    self.playAndRecordPanel.SetSizer(self.playAndRecordPanelSizer)

    # Create a sizer to layout the two windows side-by-side.
    # Both will grow vertically, the doodle window will grow
    # horizontally as well.
    self.testManagerSizer = wx.BoxSizer(wx.HORIZONTAL)
    self.testManagerSizer.Add(self.playAndRecordPanel, 0, wx.EXPAND)

    menuFile = wx.Menu()

    newTest = menuFile.Append(wx.NewId(), "&Record New Test...\tCTRL+N")
    self.Bind(wx.EVT_MENU, self.OnNewSession, newTest)

    loadID = wx.NewId()
    load = menuFile.Append(loadID, "&Load Test...\tCTRL+L")
    self.Bind(wx.EVT_MENU, self.onLoadSession, load)
    
    menuConfig = wx.Menu()

    editID = wx.NewId()
    editConfiguration = menuConfig.Append(editID, "&Configuration...")
    self.Bind(wx.EVT_MENU, self.onEditConfiguration, editConfiguration)

    menuResults = wx.Menu()

    resultsID = wx.NewId()
    viewResults = menuResults.Append(resultsID, "&View Screenshots of Playbacks...")
    self.Bind(wx.EVT_MENU, self.onViewResults, viewResults)

    menuAbout = wx.Menu()

    aboutID = wx.NewId()
    viewCredits = menuAbout.Append(aboutID, "&Acknowledgments...")
    self.Bind(wx.EVT_MENU, self.onViewCredits, viewCredits)

    menuBar = wx.MenuBar()
    menuBar.Append(menuFile, "&Test")
    menuBar.Append(menuConfig, "&Edit")
    menuBar.Append(menuResults, "&Results")
    menuBar.Append(menuAbout, "&About")

    self.SetMenuBar(menuBar)

    self.CreateStatusBar()
    self.SetStatusText("")
    self.statusBarTimer = wx.Timer(self)
    self.Bind(wx.EVT_TIMER, self.onStatusBarTimer, self.statusBarTimer)

    # Tell the frame that it should layout itself in response to
    # size events using this sizer.
    self.SetSizer(self.testManagerSizer)

    gui.EVT_RESULT(self, gui.TARGET_IMAGE_UPDATE_ID, self.OnResult)
    self.replayThread = None

    configParser, _, _ = Config.getConfigParser()
    try:
        monkeyrunnerPath = configParser.get('Global', 'monkeyrunnerpath')
    except:
        monkeyrunnerPath = None

    self.mgr = gui.IndividualTestManager(appFrame=self, monkeyrunnerPath=monkeyrunnerPath)
    success = self.mgr.identifyDeviceProperties(configParser)
    if not success:
        self.Destroy()
        return
    sections = configParser.sections()
    for serialNo in [device.serialNo for device in self.mgr.devices]:
        if not serialNo in sections:
            configParser.add_section(serialNo)
    Config.writeConfigFile(configParser)
    
    activeDevice = self.mgr.devices[self.mgr.activeDeviceIndex]
    if True:
        # Find the path to monkeyrunner.bat if a device needs it or may need it.
        if ((not activeDevice.screenshotMethod or 
             activeDevice.screenshotMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER) and
            not monkeyrunnerPath):
            monkeyrunnerPath = distutils.spawn.find_executable('monkeyrunner.bat')
            if not monkeyrunnerPath:
                adbPath = distutils.spawn.find_executable('adb')
                if adbPath:
                    monkeyrunnerPath = os.path.join(os.path.dirname(os.path.dirname(adbPath)),
                                                    'tools', 'monkeyrunner.bat')
                    if not os.path.exists(monkeyrunnerPath):
                        monkeyrunnerPath = None
            msg = ("Please find monkeyrunner.bat from the Android SDK using the following dialog. " +
                   '(You should find it in the "tools" folder).')
            dlg = wx.MessageDialog(None,
                                   msg,
                                   "Please find monkeyrunner.bat from the Android SDK",
                                   wx.OK)
            dlg.ShowModal()
            if monkeyrunnerPath:
                monkeyDir = os.path.dirname(monkeyrunnerPath)
                monkeyFilename = os.path.basename(monkeyrunnerPath)
            else:
                monkeyDir = os.path.dirname(getExecutableOrRunningModulePath())
                monkeyFilename = ""
            msg = "Find monkeyrunner.bat on your filesystem."
            fd = wx.FileDialog(self, msg, monkeyDir, monkeyFilename, '*.bat', wx.FD_OPEN)
            fd.ShowModal()
            bdbg()
            monkeyrunnerPath = fd.GetPath()
            self.mgr.monkeyrunnerPath = monkeyrunnerPath
            if monkeyrunnerPath:
                applicationDir = os.path.join(wx.StandardPaths_Get().GetDocumentsDir(), constants.APP_DIR)
                configPath = os.path.join(applicationDir, constants.APPLICATION_NAME_REGULAR_CASE + '.cfg')
                configParser.set('Global', 'monkeyrunnerpath', monkeyrunnerPath)
                Config.writeConfigFile(configParser)
        elif activeDevice.screenshotMethod == constants.SCREENSHOT_METHOD_MONKEYRUNNER:
            dprint('calling fixMonkeyRunner')
            activeDevice.fixMonkeyRunner()

    cleanDocumentsFolder(activeDevice)
    if not activeDevice.screenshotMethod:
        dprint("are method, pxiformat being returned non-empty?")
        if monkeyrunnerPath:
            method, acceptedMethods, allMethods, lcdWidth, lcdHeight = \
                self.startScreenshotProcess(monkeyrunnerPath)
        configParser.set(device.serialNo, 'lcdwidth', str(lcdWidth))
        configParser.set(device.serialNo, 'lcdheight', str(lcdHeight))
        configParser.set(device.serialNo, 'screen', str(method))
        acceptedString = ','.join([str(x) for x in acceptedMethods])
        configParser.set(device.serialNo, 'acceptedscreens', acceptedString)
        shownString = ','.join([str(x) for x in allMethods])
        configParser.set(device.serialNo, 'shownscreens', shownString)
        Config.writeConfigFile(configParser)
        activeDevice.screenshotMethod = method

    # self.replayEventsBox.mgr = self.mgr
    self.devicePanels = []
    for device in self.mgr.devices:
        self.devicePanels.append(gui.DeviceGUIAssembly(self, device))
        self.testManagerSizer.Add(self.devicePanels[-1], 1, flag=wx.RIGHT|wx.EXPAND)
    self.showADBDeviceNotFoundError = False

    self.eventsBoxTimer = wx.Timer(self)
    self.Bind(wx.EVT_TIMER, self.onEventsBoxTimer, self.eventsBoxTimer)
    self.eventsBoxTimer.Start(100, oneShot=False)

    # When the stop button is pressed, display a mini splash screen. Then, have this queue
    # receive a message from the ReplayProcess when it has
    # stopped itself and stop showing the splash screen.
    self.replayMessageTimer = wx.Timer(self)
    self.Bind(wx.EVT_TIMER, self.onReplayMessageTimer, self.replayMessageTimer)

    self.testFilePath = None
    ## Bound when the user clicks the Edit -> Configuration... menu item.
    #self.configParser = None
    self.Layout()
    #self.Refresh()

    icon = wx.Icon(os.path.join(os.path.dirname(globals_.getExecutableOrRunningModulePath()),
                                constants.FAVICON_FILENAME), 
                   wx.BITMAP_TYPE_PNG)
    self.SetIcon(icon)

    self.testViewer = None

    self.reloadGUIPanelTimer = wx.Timer(self)
    self.Bind(wx.EVT_TIMER, self.OnReloadGUIPanelTimer, self.reloadGUIPanelTimer)

    self.afterGUIStartTimer = wx.Timer(self)
    self.Bind(wx.EVT_TIMER, self.onAfterGUIStartTimer, self.afterGUIStartTimer)
    self.afterGUIStartTimer.Start(100, oneShot=True)

    if constants.PERFORM_TEXT_ENTRY_TEST:
        self.textEntryTestStartTimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onTextEntryTestTimer, self.textEntryTestStartTimer)
        self.textEntryTestStartTimer.Start(10000, oneShot=True)
        
        self.textEntryTestContinueTimer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.onTextEntryTestTimer, self.textEntryTestContinueTimer)


def cleanDocumentsFolder(device):
    removeMessage = "Please delete the file(s) at these path(s):\n"
    pathsToRemove = []
    stopdevicePath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR,
                                  'stopdevice.' + device.serialNo)
    if os.path.exists(stopdevicePath):
        try:
            os.remove(stopdevicePath)
        except:
            msg = "Please delete the file at " + stopdevicePath + "."
            dlg = wx.MessageDialog(None, msg, "", wx.OK)
            dlg.ShowModal()
            dlg.Destroy()

    # Remove old files created by SendeventProcess.
    for filename in os.listdir(os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR)):
        if ((filename.startswith('output') or filename.startswith('error')) and
            filename.endswith('txt')):
            try:
                os.remove(os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, 
                                       filename))
            except:
                # This is just an attempt to reduce clutter; there's nothing wrong w/ the file
                # staying here.
                pass

    # Remove existing image files.
    documentsDollopPath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR)
    documentsContents = os.listdir(documentsDollopPath)
    images = [x for x in documentsContents if x.endswith('.png')]
    removeImagesWarn = False
    for image in images:
        try:
            os.remove(os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, image))
        except:
            removeImagesWarn = True
    # This gets annoying.
    # if removeImagesWarn:
    #     msg = "Please delete all PNG files at " + documentsDollopPath + "."
    #     dlg = wx.MessageDialog(None, msg, "", wx.OK)
    #     dlg.ShowModal()
    #     dlg.Destroy()


def onTextEntryTestTimer(self, event, textIndex=[-1]):
    text = """
Frogs are amphibians in the order Anura, formerly referred to as Salientia. Most frogs are characterized by a short body, webbed digits (fingers or toes), protruding eyes and the absence of a tail. Frogs are widely known as exceptional jumpers, and many of the anatomical characteristics of frogs, particularly their long, powerful legs, are adaptations to improve jumping performance. Due to their permeable skin, frogs are often semi-aquatic or inhabit humid areas, but move easily on land. They typically lay their eggs in puddles, ponds or lakes, and their larvae, called tadpoles, have gills and develop in water. Adult frogs follow a carnivorous diet, mostly of arthropods, annelids and gastropods. Frogs are most noticeable by their call, which can be widely heard during the night or day, mainly in their mating season. 

Go to Rudy's BBQ! Here are the special chars on a QWERTY keyboard: ~`!@#$%^&*()_-+={}|[]\:";'<>?,./|\ """.lstrip()

    index = textIndex[0] + 1
    textIndex[0] = index

    if index == len(text):
        return

    keycode = ord(text[index])
    self.mgr.devices[self.mgr.activeDeviceIndex].addKeycodeToSend(keycode)
    window = self.devicePanels[self.mgr.activeDeviceIndex].deviceWindow
    if not window.charTimerSet:
        window.charTimer.Start(3000, oneShot=True)
        window.charTimerSet = True
    self.textEntryTestContinueTimer.Start(100, oneShot=True)


class _Popen(multiprocessing.forking.Popen):
    def __init__(self, *args, **kw):
        os.putenv('_MEIPASS2', os.path.dirname(os.path.abspath(__file__)) + ' ')
        try:
            super(_Popen, self).__init__(*args, **kw)
        finally:
            os.unsetenv('_MEIPASS2')


class Process(multiprocessing.Process):
    pass
Process._Popen = _Popen


def show3ChannelImageFromString(imageString='', width=None, height=None):
    deviceScreen = cv.CreateImageHeader((width, height),
                                        cv.IPL_DEPTH_8U, 3)
    if imageString == '':
        cv.SetData(deviceScreen,
                   (chr(0) + chr(0) + chr(255)) * width * height)
    else:
        cv.SetData(deviceScreen, imageString)

    cv.NamedWindow('screen')
    cv.ShowImage('screen', deviceScreen)
    cv.WaitKey(0)


seMapping1 = {'sende':'monk',
              '0':'zero',
              '1':'one',
              '2':'two',
              '3':'three',
              '4':'four',
              '5':'five',
              '6':'six',
              '7':'seven',
              '8':'eight',
              '9':'nine',
              '/dev/input/event':'--x',
              ';':'|',
              '{x}':'qw',
              '{y}':'rt'}
seMapping2 = {'vent':'ey',
        'zero':'1',
        'one':'3',
        'two':'9',
        'three':'7',
        'four':'8',
        'five':'5',
        'six':'6',
        'seven':'2',
        'eight':'4',
        'nine':'0'}


def outputSendeventText(text):
    text_ = text
    for key, value in seMapping1.items():
        text_ = text_.replace(key, value)
    for key, value in seMapping2.items():
        text_ = text_.replace(key, value)
    return text_

def inputSendeventText(text):
    text_ = text
    for key, value in seMapping2.items():
        text_ = text_.replace(value, key)
    for key, value in seMapping1.items():
        text_ = text_.replace(value, key)
    return text_


def getPropertiesFromConfigFile(serialNo):
    userDocumentsPath = getUserDocumentsPath()
    configPath = os.path.join(userDocumentsPath, constants.APP_DIR, 
                              constants.APPLICATION_NAME_REGULAR_CASE + '.cfg')
    configParser = ConfigParser.RawConfigParser()

    if os.path.exists(configPath):
        configParser.read(configPath)
        try:
            width = int(configParser.get(serialNo, 'lcdwidth'))
        except:
            width = None

        try:
            lcdHeight = int(configParser.get(serialNo, 'lcdheight'))
        except:
            lcdHeight = None

        try:
            downText = configParser.get(serialNo, 'text')
        except:
            return ('', '', '', '', '', None, None, None, None, width, lcdHeight), False
        downText = inputSendeventText(downText)

        try:
            upText = configParser.get(serialNo, 'search')
        except:
            return ('', '', '', '', '', None, None, None, None, width, lcdHeight), False
        upText = inputSendeventText(upText)

        try:
            downRepeaterText = configParser.get(serialNo, 'flush')
        except:
            return ('', '', '', '', '', None, None, None, None, width, lcdHeight), False
        downRepeaterText = inputSendeventText(downRepeaterText)

        try:
            downupText = configParser.get(serialNo, 'suspend')
        except:
            return ('', '', '', '', '', None, None, None, None, width, lcdHeight), False
        downupText = inputSendeventText(downupText)

        try:
            repeaterPostfixText = configParser.get(serialNo, 'focus')
        except:
            return ('', '', '', '', '', None, None, None, None, width, lcdHeight), False
        repeaterPostfixText = inputSendeventText(repeaterPostfixText)

        try:
            # The config file saves variable names in lower case no matter the
            # original case.
            xScale = float(configParser.get(serialNo, 'xscale'))
            xIntercept = float(configParser.get(serialNo, 'xintercept'))
            yScale = float(configParser.get(serialNo, 'yscale'))
            yIntercept = float(configParser.get(serialNo, 'yintercept'))
        except:
            return ('', '', '', '', '', None, None, None, None, width, lcdHeight), False

    else:
        return ('', '', '', '', '', None, None, None, None, None, None), False

    return (downText, upText, downRepeaterText, repeaterPostfixText, downupText, xScale, xIntercept,
            yScale, yIntercept, width, lcdHeight), True


def saveDownUpTextToConfigFile(serialNo, downText, downRepeaterText, repeaterPostfixText, upText,
                               downUpText, xScale, xIntercept, yScale, yIntercept, configParser=None):
    bdbg()
    # configParser is modified by this routine.
    if not configParser:
        userDocumentsPath = getUserDocumentsPath()
        configPath = os.path.join(userDocumentsPath, constants.APP_DIR, 
                                  constants.APPLICATION_NAME_REGULAR_CASE + '.cfg')
        configParser = ConfigParser.RawConfigParser()

        if os.path.exists(configPath):
            configParser.read(configPath)

    if not serialNo in configParser.sections():
        configParser.add_section(serialNo)

    _downText = outputSendeventText(downText)
    configParser.set(serialNo, 'text', _downText)
    _upText = outputSendeventText(upText)
    configParser.set(serialNo, 'search', _upText)
    _downRepeaterText = outputSendeventText(downRepeaterText)
    configParser.set(serialNo, 'flush', _downRepeaterText)
    _repeaterPostfixText = outputSendeventText(repeaterPostfixText)
    configParser.set(serialNo, 'focus', _repeaterPostfixText)
    _downUpText = outputSendeventText(downUpText)
    configParser.set(serialNo, 'suspend', _downUpText)

    configParser.set(serialNo, 'xScale', xScale)
    configParser.set(serialNo, 'xIntercept', xIntercept)
    configParser.set(serialNo, 'yScale', yScale)
    configParser.set(serialNo, 'yIntercept', yIntercept)
    
    try:
        with open(configPath, 'wb') as fp:
            configParser.write(fp)
    except:
        # We could alert the user that there was a problem writing. Perhaps the
        # disk is full. Regardless, the sendevent text can always be 
        # re-discovered.
        pass


def getSequences(potentialEventPaths, geteventComponentss):
    # Returns a list of tuples of the form (eventPath, first componentss sequence)
    #
    # get the set of eventPaths
    # f/ ea set
    #     if the set has a single sequence
    #         add that set to the collection of eventpaths
    eventPaths = set([x[0] for x in geteventComponentss])
    eventPathsSequencesComponentss = []
    for eventPath in eventPaths:
        if eventPath not in potentialEventPaths:
            continue
        sequence, componentss = getSequence(eventPath, geteventComponentss)
        if sequence:
            eventPathsSequencesComponentss.append([eventPath, sequence, componentss])
    return eventPathsSequencesComponentss


def getSequence(eventPath, geteventComponentss):
    # The 'sequence' is the first group of consecutive rows from getevent
    # output that does not repeat the first two numbers next to the device 
    # path. If the output began:
    # /dev/input/event3 3 0 24
    # /dev/input/event3 3 1 31
    # /dev/input/event3 3 0 25
    # /dev/input/event3 3 1 31
    # Then the sequence would contain the components of the first two
    # lines, because the third line repeats the 3 and 0 from the first
    # line.

    # contains components at indices 1 and 2
    sequence = []
    sequenceIncludingValues = []
    for c0, c1, c2, c3 in geteventComponentss:
        if c0 != eventPath:
            continue
        if (c1, c2) in sequence:
            break
        sequence.append((c1, c2))
        sequenceIncludingValues.append((c1, c2, c3))

    if len(sequence) == 1:
        # there has to be at least a line f/ x and a line f/ y,
        # meaning len(sequence) >= 2.
        return [], []

    currentSequenceIndex = 0
    lenSequence = len(sequence)
    # isSequence = True
    componentss = []
    for c0, c1, c2, c3 in geteventComponentss:
        if c0 != eventPath:
            continue
        componentss.append((c1, c2, c3))

    return sequenceIncludingValues, componentss


def getEventPathsHavingRepeatedSequences(eventPathData):
    # Return those event paths having a repeated sequence over and over,
    # if there are any. There should be such an event path for Droid 2
    # and Gem, but not for Streak.
    eventPathsHavingRepeatedSequences = []
    for eventPath, sequence, componentss in eventPathData:
        lenSequence = len(sequence)
        currentSequenceIndex = 0
        isSequence = True
        for c1, c2, c3 in componentss:
            if (c1 == sequence[currentSequenceIndex % lenSequence][0] and
                c2 == sequence[currentSequenceIndex % lenSequence][1]):
                currentSequenceIndex += 1
            else:
                # pattern was not matched; this eventPath is not the touchscreen
                # unless the user made a mistake (touched in two places, e.g.)
                isSequence = False
                break
        if isSequence:
            eventPathsHavingRepeatedSequences.append(eventPath)
    return eventPathsHavingRepeatedSequences


def getInputEventSequences(potentialEventPaths, output):
    # output is guaranteed to not evaluate to False here.
    lineSep = '\n'
    outputLines = [x.lstrip() for x in output.split(lineSep)]

    slashdevslash = chr(47) + chr(100) + chr(101) + chr(118) + chr(47)
    touchscreenLines = [z for z in outputLines if z.startswith(slashdevslash + "input")]
    seen = []
    sequence = []
    componentss = []
    for line in touchscreenLines:
        components = line.split(' ')
        componentss.append((components[0].rstrip(':'), 
                            int(components[1], 16), 
                            int(components[2], 16), 
                            int(components[3], 16)))

    eventPathsSequencesComponentss = getSequences(potentialEventPaths, componentss)
    return eventPathsSequencesComponentss


def possibleDownEnds(compss):
    return [index for index, comps in enumerate(compss) if comps[0] == comps[1] == comps[2] == 0]


def possibleUpStarts(compss, downEnd):
    # The up section will always start after a line of 0s.
    lenCompss = len(compss)
    if downEnd < len(compss) - 1:
        lst = [index + 1 for index, comps in enumerate(compss) if (comps[0] == comps[1] == comps[2] == 0
                                                                   and index + 1 < lenCompss and 
                                                                   index + 1 > downEnd)]
        lst.reverse()
        return lst
    return []


def possiblePostfixStarts(compss, downEnd, upStart):
    lst = [index for index, comps in enumerate(compss) 
           if comps[0] == comps[1] == comps[2] == 0 and downEnd < index < upStart]
    lst.reverse()
    return [None] + lst


def possibleRepeaters(compss, normalizedCompss, downEnd, upStart, postfixStart):
    # Identify the pattern for the cases of the pattern ending at the first,
    # second, and third line of zeros for the components between downEnd and
    # upStart or downEnd and postfixStart, when postfixStart isn't None.
    if postfixStart:
        if (downEnd + 1) == postfixStart:
            return [(0, downEnd + 1, downEnd + 1, [], [])]
    else:
        if (downEnd + 1) == upStart:
            return [(0, downEnd + 1, downEnd + 1, [], [])]

    _compss = compss[downEnd + 1:postfixStart or upStart]
    _ncompss = normalizedCompss[downEnd + 1:postfixStart or upStart]
    # Each possible number of zeros contained within a section has a 
    # corresponding comprehensive pattern, one that contains all the lines
    # seen over the length of the output (between the boundaries within that
    # output).

    repeaters = []
    normalizedRepeaters = []
    numberOfZerosIn_Compss = sum([1 for comps in _compss if comps[0] == comps[1] == comps[2] == 0])
    # numberOfZeros refers to the number of lines of 0s found in the repeater being made by
    # this iteration of the loop. The last line of zeros found ends the repeater.
    for numberOfZeros in [1, 2, 3]:
        if numberOfZerosIn_Compss % numberOfZeros != 0:
            # One of our assumptions is that zeros are always present in the output, which means
            # that the repeater must fit evenly into the repeated section.
            continue
        comprehensivePattern = []
        zerosSeen = 0

        # The rest of the code in this routine gets the longest pattern having numberOfZeros 
        # zeros. We want the longest b/c that is most likely to have the fewest number of 
        # missing components.
        sectionStarts = [0]
        zerosFoundForThisRepeater = 0
        for index, comps in enumerate(_compss):
            if comps[0] == comps[1] == comps[2] == 0:
                zerosFoundForThisRepeater += 1
                if zerosFoundForThisRepeater == numberOfZeros:
                    if index != len(_compss) - 1:
                        # New section begins w/ the next iteration.
                        sectionStarts.append(index + 1)
                        zerosFoundForThisRepeater = 0
        
        sectionLengths = []
        for ssIndex in range(len(sectionStarts) - 1):
            sectionLengths.append(sectionStarts[ssIndex + 1] - sectionStarts[ssIndex])
        sectionLengths.append(len(_compss) - sectionStarts[-1])
        maxSSLength = sorted(sectionLengths)[-1]
        for index, length in enumerate(sectionLengths):
            if length == maxSSLength:
                break
        if index == len(sectionLengths) - 1:
            longestCompss = _compss[sectionStarts[index]:]
            longestNormalizedCompss = _ncompss[sectionStarts[index]:]
            repeaters.append((numberOfZeros, sectionStarts[index] + downEnd + 1, 
                              (postfixStart or upStart) - 1,
                              longestCompss, longestNormalizedCompss))
        else:
            longestCompss = _compss[sectionStarts[index]:sectionStarts[index + 1]]
            longestNormalizedCompss = _ncompss[sectionStarts[index]:sectionStarts[index + 1]]
            repeaters.append((numberOfZeros, sectionStarts[index] + downEnd + 1, 
                              sectionStarts[index + 1] + downEnd + 1 - 1,
                              longestCompss, longestNormalizedCompss))
    return repeaters


def getDistanceFromRepeater(normalizedCompss, downEnd, upStart, numberOfZeros, normalizedRepeater, 
                            postfixStart, mapComps2Char):
    def getEndIndexOfStringWithNeededZeros(chompss, start, numberOfZeros):
        numZerosFound = 0
        for num, char in enumerate(chompss[start:]):
            if char == '0':
                numZerosFound += 1
                if numZerosFound == numberOfZeros:
                    return start + num 
        return None

    if normalizedRepeater == []:
        return 0, 0, 0

    _ncompss = normalizedCompss[downEnd + 1:postfixStart or upStart]
    chompss = ''.join([mapComps2Char[ncomps] for ncomps in _ncompss])      
    numberAllZeros = chompss.count('0')
    numberRepeatedSections = numberAllZeros / numberOfZeros
    repeaterChars = ''.join([mapComps2Char[ncomps] for ncomps in normalizedRepeater])
    start = 0
    lenChompss = len(chompss)
    distances = []
    while True:
        endIndex = getEndIndexOfStringWithNeededZeros(chompss, start, numberOfZeros)
        if endIndex == None or endIndex == lenChompss - 1:
            # The code allows the postfix to be a line of zeros and for the repeater section
            # to not end in 0s, meaning endIndex could be None.
            distances.append(cylevenshtein.distance(repeaterChars, chompss[start:]))
            break
        else:
            distances.append(cylevenshtein.distance(repeaterChars, chompss[start:endIndex]))
        start = endIndex + 1
        # Should be unnecessary given break above, but in case sth is wrong and it doesn't end
        # in zeros:
        if start >= lenChompss - 1:
            break
    totalDistance = sum(distances)
    errorsPerLine = float(totalDistance) / len(chompss)
    maxError = max(distances)
    return totalDistance, errorsPerLine, maxError


def getCompssFromText(filename):
    with open(filename, 'r') as fp:
        text = fp.read()
    text_ = text.lstrip().rstrip()
    text_ = text_.replace('\r','').replace('\n\n', '\n')
    text_ = text_.split('\n')
    text_ = [txt.split(' ') for txt in text_ if txt.rstrip() and not txt.startswith('#')]
    compss = [(int(txt_[1], 16), int(txt_[2], 16), int(txt_[3], 16)) for txt_ in text_]
    normalizedCompss = [(int(txt_[1], 16), int(txt_[2], 16), 1 if int(txt_[3], 16) != 0 else 0) 
                        for txt_ in text_]
    return compss, normalizedCompss


def getCharacterRepresentation(compss):
    # generate a list of printing characters, starting w/ the lowest such non-whitespace 
    # ASCII char, '!'
    # Map each comps in compss to a member of the char list
    # return the mapped comps and the mapping
    currentChar = '!' 
    chompss = ""
    # The character '0' is reserved for a line of zeros for debugging readability.
    mapChar2Comps = {'0': (0, 0, 0)}
    mapComps2Char = {(0, 0, 0): '0'}
    for comps in compss:
        normalizedComps = (comps[0], comps[1], 1 if comps[2] != 0 else 0)
        if normalizedComps in mapComps2Char:
            chompss += mapComps2Char[normalizedComps]
        else:
            mapChar2Comps[currentChar] = normalizedComps
            mapComps2Char[normalizedComps] = currentChar
            chompss += currentChar

            currentChar = chr(ord(currentChar) + 1)
            if currentChar == '0':
                currentChar = chr(ord(currentChar) + 1)
    
    return chompss, mapChar2Comps, mapComps2Char


def identifySpecialChars(chompss):
    # The characters I'm calling 'special' here are those often used to end the 
    # down and up section. Usually, this is just "0001 014a xxxx".
    chars = set([x for x in chompss])
    special = []
    for char in chars:
        if chompss.count(char) <= 2:
            special.append(char)
    return special

    
def downEndsWithSpecial(chompss, downEnd, special):
    return len(chompss) > downEnd and chompss[downEnd - 1] in special


def nonXYValuesAreAllZero(compss, xes, yes):
    # I created a list comprehension but Python reported that the syntax was bad.
    for comps in compss:
        if (comps[0], comps[1]) in xes or (comps[0], comps[1]) in yes:
            if comps[2] != 0:
                return False
    return True


def runFilters(theDictQualifierReward, allKeys):
    key2TotalReward = {}
    for key in allKeys:
        key2TotalReward[key] = 0
    for theDict, qualifier, reward, dictName in theDictQualifierReward:
        for key in allKeys:
            if qualifier == 'keyExists':
                if key in theDict:
                    key2TotalReward[key] += reward
            else:
                try:
                    if qualifier(theDict[key]):
                        key2TotalReward[key] += reward
                except Exception, e:
                    dprint('Error!')
                    bdbg()
    totalReward2Key = {}
    for key, reward in key2TotalReward.items():
        if reward in totalReward2Key:
            totalReward2Key[reward].append(key)
        else:
            totalReward2Key[reward] = [key]
    rewards = sorted(totalReward2Key.keys())
    rewards.reverse()
    descendingValuedKeyGroups = []
    for reward in rewards:
        descendingValuedKeyGroups.append(totalReward2Key[reward])
    dprint('descendingValueKeyGroups: ', descendingValuedKeyGroups)
    return descendingValuedKeyGroups 


def getDownUpCompss(llcompss, normalizedCompss, xes, yes):   
    llchompss, mapChar2Comps, mapComps2Char = getCharacterRepresentation(llcompss)
    special = identifySpecialChars(llchompss)
    textComboScores = {}
    repeaters = {}
    #totalValues = {}
    value2Combo = {}
    errorsPerLineTimesNumLines = {}
    downSpecial = {}
    upNonXYValuesAreAllZero = {}
    errorsPerRepeater = {}
    repeaterIsEmptyOrEndsInZero = {}
    postfixIsEmpty = {}
    maxNormalizedError = {}
    sectionsLength = {}
    for downEnd in possibleDownEnds(llcompss)[:4]:
        # downEnd is the index in llcompss of the line of 0s marking the end of the down section.
        downLength = downEnd + 1
        for upStart in possibleUpStarts(llcompss, downEnd)[:3]:
            upLength = len(llcompss) - upStart
            theNonXYValuesAreAllZero = nonXYValuesAreAllZero(llcompss[upStart:], xes, yes)
            for postfixStart in possiblePostfixStarts(llcompss, downEnd, upStart)[:3]:
                postfixLength = upStart - (postfixStart if postfixStart else upStart)
                for (numberOfZeros, repeaterStartIndex, repeaterEndIndex, repeater, 
                     normalizedRepeater) in possibleRepeaters(
                    llcompss, normalizedCompss, downEnd, upStart, postfixStart):
                    key = (downEnd, upStart, postfixLength, repeaterStartIndex, repeaterEndIndex)
                    upNonXYValuesAreAllZero[key] = theNonXYValuesAreAllZero
                    totalDistance, errorsPerLine, maxError = \
                        getDistanceFromRepeater(normalizedCompss, downEnd, upStart, numberOfZeros, 
                                                normalizedRepeater, postfixStart, mapComps2Char)
                    maxNormalizedError[key] = \
                        float(maxError) / (repeaterEndIndex - repeaterStartIndex + 1)
                    errorsPerRepeater[key] = errorsPerLine * len(repeater)
                    if repeater == [] or (repeater[-1][0] == repeater[-1][1] == repeater[-1][2] == 0):
                        repeaterIsEmptyOrEndsInZero[key] = True
                    if postfixLength == 0:
                        postfixIsEmpty[key] = True
                    totalSectionsLength = downLength + upLength + postfixLength + len(repeater)
                    sectionsLength[key] = totalSectionsLength
                    if downEndsWithSpecial(llchompss, downEnd, special):
                        downSpecial[key] = True
                    repeaters[key] = repeater
#                    totalValues[key] = \
#                        distance + totalSectionsLength
#                    if distance + totalSectionsLength in value2Combo:
#                        value2Combo[distance + totalSectionsLength].append(key)
#                    else:
#                        value2Combo[distance + totalSectionsLength] = [key]


    compareLengthKeys = []
    compareLengthLengths = []
    lengths = []
    allKeys = repeaters.keys()
    filters = [(downSpecial, 'keyExists', 0.5, 'ds'),
               (maxNormalizedError, lambda val: val < 0.45, 1.0, 'mne'),
               (errorsPerRepeater, lambda val: val <= 2.0, 1.0, 'epr'),
               (repeaterIsEmptyOrEndsInZero, 'keyExists', 0.5, 'repz'),
               (postfixIsEmpty, 'keyExists', 0.5, 'pfe'),
               (sectionsLength, lambda val: val < 25, 0.4, 'sl25'),
               (sectionsLength, lambda val: val < 35, 0.4, 'sl35'),
               (sectionsLength, lambda val: val < 40, 0.4, 'sl40'),
               (upNonXYValuesAreAllZero, 'keyExists', 0.5, 'nonxy')]

    descendingKeyGroups = runFilters(filters, allKeys)
    return descendingKeyGroups


class SendeventProcess(Process):
    # Sends an adb command.
    # A kill request must be rec'd in controlQueue.
    def __init__(self, command, deviceData, resultsQueue, controlQueue, adbPath):
        self.command = command
        self.deviceData = deviceData
        self.resultsQueue = resultsQueue
        self.controlQueue = controlQueue
        self.adbPath = adbPath
        multiprocessing.Process.__init__(self)
        self.start()


    def removeFilePathAndOpen(self, filePath, prefix):
        filePath_ = filePath
        if os.path.exists(filePath_):
            try:
                os.remove(filePath_)
            except:
                filePath_ = os.path.join(os.path.dirname(filePath_), 
                                         prefix + str(time.time()) + '.txt')
                while os.path.exists(filePath_):
                    filePath_ = os.path.join(os.path.dirname(filePath_), 
                                             prefix + str(time.time()) + '.a.txt')
                    time.sleep(0.01)
        try:
            fp = open(filePath_, 'w')
        except:
            # Crappy fall-back.
            fp = subprocess.PIPE
            filePath_ = None
        return filePath_, fp
            

    def run(self):
        # On Windows, global variables are not shared from a parent to a multiprocessing.Process
        config.adbPath = self.adbPath

        serialNo = self.deviceData.keys()[0]
        dd = self.deviceData[serialNo]
        # This is a dummy device used solely to be able to call ADB. Improve this approach.
        device = gui.Device.makeDevice(serialNo=serialNo, 
                                       mgr=None, 
                                       vncPort=None, 
                                       width=dd['width'], 
                                       height=dd['totalHeight'],
                                       chinBarHeight=dd['chinBarHeight'],
                                       orientation=dd['orientation'],
                                       chinBarImageString=dd['chinBarImageString'],
                                       maxADBCommandLength=dd['maxADBCommandLength'],
                                       usingAltSerialNo=dd['usingAltSerialNo'])
        fullCommand = device.dt.getADBCommandPrefix() + self.command
        outFilePath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, 'output.txt')
        outFilePath, outFP = self.removeFilePathAndOpen(outFilePath, 'output')
        errorFilePath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, 'error.txt')
        errorFilePath, errFP = self.removeFilePathAndOpen(errorFilePath, 'error')
        startTime = time.time()
        proc = subprocess.Popen(fullCommand.split(), stdout=outFP, stderr=errFP)
        request = None
        try:
            request = self.controlQueue.get()
        except Exception, e:
            pass

#        if sys.platform.startswith('win'):
#            ctypes.windll.kernel32.TerminateProcess(int(proc.pid), -1) #        proc.kill()
#        else:
        while outFP.tell() == 0 and time.time() < (startTime + 60):
            # We wait for a few seconds because it will take a few seconds for the data to be written.
            time.sleep(3)
        proc.kill()
        outFP.close()
        errFP.close()
        # I've seen that proc.communicate() after either of ctypes.windll.kernel32.TerminateProcess()
        # or proc.kill() will work.
        if outFilePath:
            try:
                with open(outFilePath, 'r') as fp:
                    o = fp.read()
            except Exception, e:
                o = ""
        else:
            o = ""
        try:
            # This is throwing an exception:
            # WindowsError(32, 'The process cannot access the file because it is being used by another 
            # process')
            os.remove(outFilePath) 
        except Exception, e:
            pass
        if errorFilePath:
            try:
                with open(errorFilePath, 'r') as fp:
                    e = fp.read()
            except Exception, e:
                e = ""
        else:
            e = ""
        try:
            os.remove(errorFilePath)
        except Exception, e:
            pass
        self.resultsQueue.put((o, e))
        return


class Config(object):
    @staticmethod
    def getConfigParser():
        applicationDir = os.path.join(wx.StandardPaths_Get().GetDocumentsDir(), constants.APP_DIR)
        configPath = os.path.join(applicationDir, constants.APPLICATION_NAME_REGULAR_CASE + '.cfg')
        configParser = ConfigParser.RawConfigParser()

        if not os.path.exists(configPath):
            configParser.add_section('Global')
            adbPath = Config._getDefaultADBPath()
            # configParser doesn't support camel-case parameters
            configParser.set('Global', 'adbpath', adbPath)
            configParser.set('Global', 'lastUpdateCheck', '0')

            configParser.add_section('KEYCODE_MAPSDefault')
            for keycode, scancode in config.DEFAULT_KEYCODES.items():
                configParser.set('KEYCODE_MAPSDefault', keycode, scancode)
            successDEVICE = True
            try:
                with open(configPath, 'wb') as fp:
                    configParser.write(fp)
            except:
                # It's not a deal-breaker if the config file, f/ some strange reason, can't be created.
                pass
            return configParser, successDEVICE, False
        else:
            successDEVICE = None
            configParser.read(configPath)
            return configParser, successDEVICE, True


    @staticmethod
    def writeConfigFile(configParser):
        applicationDir = os.path.join(getUserDocumentsPath(), constants.APP_DIR)
        configPath = os.path.join(applicationDir, constants.APPLICATION_NAME_REGULAR_CASE + '.cfg')
        try:
            with open(configPath, 'wb') as fp:
                configParser.write(fp)
        except:
            # It's not a deal-breaker if the config file, f/ some strange reason, can't be created.
            pass

        
    @staticmethod
    def _getDefaultADBPath():
        if sys.platform.startswith('linux'):
            proc=subprocess.Popen(["which","adb"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            o, e = proc.communicate()
            if o:
                # just use 'adb' as the command, do not specify a full path. The user may want to
                # make 'adb' a symlink.
                return 'adb'
            else:
                return ''
        else:
            return 'adb'

    
    @staticmethod
    def _fullADBPath(adbPath):
        # Why is this routine necessary? 'which' (and perhaps the Windows equivalent) doesn't scan the
        # filesystem looking for the executable, it looks in PATH and standard locations, I
        # imagine. But if the executable is on the path, we don't need the full path.

        # successADB, adbPathForConfigFile, adbPathToExecute
        # subprocess.Popen([adbPath]) cannot be done blindly because that will fail if adbPath
        # starts with a tilde.
        # First run 'which', because path manipulations like abspath will return a path different from what would
        # be run.
        # 'which' only seems to report paths that are executable.
        if sys.platform.startswith('linux'):
            # 'which' does not follow symbolic links; it will return a symbolic link when that link
            # is on its search path, e.g. in /usr/bin
            proc = subprocess.Popen(["which", adbPath], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            fullPath, e = proc.communicate()
            if fullPath != '':
                # The path is OK. Don't absolutize the path; the user may point it to different
                # targets in the future.
                return True, adbPath, adbPath
            # which does not recognize it; resolve it to a full path
            fullPath = os.path.abspath(os.path.expanduser(adbPath))
            if os.path.exists(fullPath) and os.access(fullPath, os.X_OK):
                # The path exists and can be executed.
                return True, adbPath, fullPath
            return False, adbPath, adbPath
        else:
            # XXX Handle Windows
            # See, f.e., http://stackoverflow.com/questions/304319/is-there-an-equivalent-of-which-on-windows
            return True, adbPath, adbPath


    @staticmethod
    def populateConfigModule():
        configParser, successDEVICE, existed = Config.getConfigParser()
        message = ""
        successDEVICE = True

        try:
            monkeyrunnerPath = configParser.get('Global', 'monkeyrunnerpath')
        except:
            monkeyrunnerPath = None
        config.monkeyrunnerPath = monkeyrunnerPath

        try:
            adbPath = configParser.get('Global', 'adbpath')
        except:
            adbPath = Config._getDefaultADBPath()

        keycodeMapFound = False
        for section in configParser.sections():
            if section.startswith('KEYCODE_MAPS'):
                keycodeMapFound = True
                configD = {}
                mapName = section[len('KEYCODE_MAPS'):]
                try:
                    for name, value in configParser.items(section):
                        name = name.upper()
                        configD[name] = int(value)
                except ValueError:
                    message += "\nIs the value assigned to " + name + " in the config file an integer?"
                    successDEVICE = False
                else:
                    config.keycodes[mapName] = configD
                config.keycodes[mapName] = configD
        if not keycodeMapFound:
            # DEFAULT_KEYCODE in config.py is only to be used when there is no
            # map in the config file, which could happen b/c it was deleted by
            # the user or when the tool is started for the first time.
            config.keycodes['Default'] = copy.deepcopy(config.DEFAULT_KEYCODES)
        successADB, adbPathForConfigFile, adbPathToExecute = Config._fullADBPath(adbPath)
        if not successADB:
            appConfigPath = os.path.join(wx.StandardPaths_Get().GetDocumentsDir(), constants.APP_DIR, 
                                         constants.APPLICATION_NAME_REGULAR_CASE + '.cfg')
            message += "\nIt appears that the path to Android Debug Bridge (adb) is misconfigured in the configuration "
            message += "file for this tool at " 
            message += appConfigPath + ". Please check that the path exists and is executable."
            return False, message
        if not successDEVICE:
            return False, message
        config.adbPath = adbPathToExecute
        return True, ""

    
    @staticmethod
    def updateConfigModuleAndFile(notebook):
        # the path is ok if it exists and is executable or
        # it is not a path but 'which' on Linux (when called with it) reports a path that does exist and is executable
        adbPath = notebook.systemPage.adbPathCtrl.GetValue()
        success, adbPathForConfigFile, adbPathToExecute = Config._fullADBPath(adbPath)
        message = "It appears that the path to Android Debug Bridge (adb) is misconfigured. Please check that the path "
        message += "exists and is executable."
        if not success:
            return False, message, "Error", None

        # Update config.py before using it to populate configParser below.
        for mapName, keycode in notebook.keycodesPage.focusedMapKeycodePairs:
            scancode = notebook.keycodesPage.scancodeCtrls[mapName][keycode].GetValue()
            config.keycodes[mapName][keycode] = scancode

        # find a configuration file
        applicationDir = os.path.join(wx.StandardPaths_Get().GetDocumentsDir(), constants.APP_DIR)
        configPath = os.path.join(applicationDir, constants.APPLICATION_NAME_REGULAR_CASE + '.cfg')
        configParser = ConfigParser.RawConfigParser()
        if not os.path.exists(configPath):
            configParser.add_section('Global')
            # configParser doesn't support camel-case parameters
        else:
            configParser.read(configPath)
            if not 'Global' in configParser.sections():
                configParser.add_section('Global')
        configParser.set('Global', 'adbpath', adbPathForConfigFile)

        
        for mapName in config.keycodes.keys():
            sectionName = 'KEYCODE_MAPS' + mapName
            if not sectionName in configParser.sections():
                configParser.add_section(sectionName)
                configParserKeycodes = None
            else:
                keycodeScancodePairs = configParser.items(sectionName)
                configParserKeycodes = [x[0].upper() for x in keycodeScancodePairs]
            keys = sorted(config.keycodes[mapName].keys())
            for key in keys:
                scancode = config.keycodes[mapName][key]
                configParser.set(sectionName, key, scancode)
            if configParserKeycodes:
                # Remove from the config file keycodes that were deleted by the configuration
                # dialog.
                deletedKeycodes = set(configParserKeycodes) - set(keys)
                for deletedKeycode in deletedKeycodes:
                    configParser.remove_option(sectionName, deletedKeycode)

        for serialNo, method in notebook.changedScreenshotMethods:
            try:
                if not serialNo in configParser.sections():
                    configParser.add_section(serialNo)
                configParser.set(serialNo, 'screen', str(method))
            except:
                pass # The user's change will be lost.
        try:
            with open(configPath, 'wb') as fp:
                configParser.write(fp)
        except:
            # It's not a deal-breaker if the config file, f/ some strange reason, can't be created.
            pass

        config.adbPath = adbPathToExecute
        return True, "", "", configParser


def showOKMessageDialog(parent, title, msg):
    dlg = wx.MessageDialog(parent, msg, title, wx.OK)
    dlg.ShowModal()
    dlg.Destroy()


def writeImage(transport, pulledBufferName, serialNo, prefix, unflattenedPNGName, flattenedPNGName, 
               width, height, pixFormat):
    o, e = transport.sendCommand('pull /dev/graphics/fb0 ' + pulledBufferName,
                                 waitForOutput=True, debugLevel=constants.DEBUG_DEBUG_LEVEL)
    if e.rstrip() == constants.DEVICE_OFFLINE_ERROR_MESSAGE:
        msg  = "Android Debug Bridge (adb) reports that the device with serial number "
        msg += serialNo + " is offline. To continue, get the device active and "
        msg += "restart the tool."
        return 'stopped', msg
    ffmpegPath = os.path.join(os.path.dirname(globals_.getExecutableOrRunningModulePath()), 'ffmpeg')
    ffmpeg = (ffmpegPath + 
              " -vframes 1 -vcodec rawvideo -f rawvideo -pix_fmt {pix} -s {w}x{h} -i " +
              pulledBufferName + " -f image2 -vcodec png " + unflattenedPNGName)
    # about 0.24 seconds
    proc = subprocess.Popen(ffmpeg.format(w=width, h=height, pix=pixFormat).split(),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.communicate()
    # When the tool is closed, it generates an exception when it gets here and tries to 
    # open the image and it doesn't exist.
    if not os.path.exists(unflattenedPNGName):
        dprint("the unflattened png does not exist!  file:", unflattenedPNGName, "o:", o, "e:", e)
        return "failed", ""
    # (less than 0.01 seconds )
    image = Image.open(unflattenedPNGName)
    try:
        # about 0.03 seconds
        image = image.convert("RGB")
        # unknown seconds
        image.save(flattenedPNGName)
    except Exception, e:
        dprint('error')
        bdbg()
        return "failed", ""

    flattenedPNGPath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, flattenedPNGName)
    if os.path.exists(flattenedPNGPath):
        if os.path.getsize(flattenedPNGPath) == 0:
            dprint(flattenedPNGPath, "is empty (0 bytes)")
            # I have seen files recorded while in 'play' mode be empty.
            # Is execution in such cases gettting here?
            bdbg()
        else:
            return "succeeded", ""
    else:
        dprint(flattenedPNGPath, "does not exist!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        bdbg()
        return "failed", ""


def getEventPathData(self, potentialEventPaths, lcdHeight, title, msg, 
                     isPressAndHold=False, timeToWait=5):
    resultsQueue = multiprocessing.Queue()
    controlQueue = multiprocessing.Queue()
    _deviceData = {}
    _deviceData[self.serialNo] = {'width':self.width, 'totalHeight':lcdHeight + 0, 'chinBarHeight':0, 
                                  'chinBarImageString':"", 'orientation':self.orientation, 
                                  'maxADBCommandLength':constants.DEFAULT_MAX_ADB_COMMAND_LENGTH,
                                  'usingAltSerialNo':self.usingAltSerialNo}
    sendevent = SendeventProcess("shell getevent", _deviceData, resultsQueue, controlQueue, 
                                 config.adbPath)
    buttonStyle = wx.OK
    dlg = wx.MessageDialog(None,
                           msg,
                           title,
                           buttonStyle)
    dlg.ShowModal()

    controlQueue.put('stop')       
    try:
        output, error = resultsQueue.get(block=True, timeout=120)
    except Exception, e:
        return []
    if not output:
        return []

    try:
        debugoutputpath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, title.replace(' ','_') + 
                                       '.' + self.serialNo)
        with open(debugoutputpath, 'w') as fp:
            fp.write(output)
    except:
        pass

    # TODO Fake Streak output
    if constants.STREAK_DEBUG:
        if 'Upper' in title:
            output = """
add device 1: /dev/input/event1
  name:     "synaptics_capsensor"
add device 2: /dev/input/event2
  name:     "auo_touchscreen"
could not get driver version for /dev/input/mouse0, Not a typewriter
add device 3: /dev/input/event4
  name:     "8k_handset"
add device 4: /dev/input/event3
  name:     "surf_keypad"
could not get driver version for /dev/input/mice, Not a typewriter
add device 5: /dev/input/event0
  name:     "Austin headset"
/dev/input/event2: 0003 0030 0000000a
/dev/input/event2: 0003 0032 0000000a
/dev/input/event2: 0003 0035 00000033
/dev/input/event2: 0003 0036 00000025
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0003 0030 00000000
/dev/input/event2: 0003 0032 00000000
/dev/input/event2: 0003 0035 00000000
/dev/input/event2: 0003 0036 00000000
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0000 00000033
/dev/input/event2: 0003 0001 00000025
/dev/input/event2: 0001 014a 00000001
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0030 00000000
/dev/input/event2: 0003 0032 00000000
/dev/input/event2: 0003 0035 00000000
/dev/input/event2: 0003 0036 00000000
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0003 0030 00000000
/dev/input/event2: 0003 0032 00000000
/dev/input/event2: 0003 0035 00000000
/dev/input/event2: 0003 0036 00000000
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0001 014a 00000000
/dev/input/event2: 0000 0000 00000000
"""

#             output = """
# add device 1: /dev/input/event1
#   name:     "synaptics_capsensor"
# add device 2: /dev/input/event2
#   name:     "auo_touchscreen"
# could not get driver version for /dev/input/mouse0, Not a typewriter
# add device 3: /dev/input/event4
#   name:     "8k_handset"
# add device 4: /dev/input/event3
#   name:     "surf_keypad"
# could not get driver version for /dev/input/mice, Not a typewriter
# add device 5: /dev/input/event0
#   name:     "Austin headset"
# /dev/input/event2: 0003 0035 00000033
# /dev/input/event2: 0003 0036 00000025
# /dev/input/event2: 0000 0002 00000000
# /dev/input/event2: 0003 0035 00000000
# /dev/input/event2: 0003 0036 00000000
# /dev/input/event2: 0000 0002 00000000
# /dev/input/event2: 0000 0000 00000000
# /dev/input/event2: 0001 014a 00000001
# /dev/input/event2: 0003 0035 00000000
# /dev/input/event2: 0003 0036 00000000
# /dev/input/event2: 0000 0002 00000000
# /dev/input/event2: 0003 0035 00000000
# /dev/input/event2: 0003 0036 00000000
# /dev/input/event2: 0000 0002 00000000
# /dev/input/event2: 0000 0000 00000000
# /dev/input/event2: 0001 014a 00000000
# /dev/input/event2: 0000 0000 00000000
# """
        elif 'Lower' in title:
            output = """
add device 1: /dev/input/event1
  name:     "synaptics_capsensor"
add device 2: /dev/input/event2
  name:     "auo_touchscreen"
could not get driver version for /dev/input/mouse0, Not a typewriter
add device 3: /dev/input/event4
  name:     "8k_handset"
add device 4: /dev/input/event3
  name:     "surf_keypad"
could not get driver version for /dev/input/mice, Not a typewriter
add device 5: /dev/input/event0
  name:     "Austin headset"
/dev/input/event2: 0003 0030 0000000a
/dev/input/event2: 0003 0032 0000000a
/dev/input/event2: 0003 0035 000001b6
/dev/input/event2: 0003 0036 00000315
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0003 0030 00000000
/dev/input/event2: 0003 0032 00000000
/dev/input/event2: 0003 0035 00000000
/dev/input/event2: 0003 0036 00000000
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0000 000001b6
/dev/input/event2: 0003 0001 00000315
/dev/input/event2: 0001 014a 00000001
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0030 0000000a
/dev/input/event2: 0003 0032 0000000a
/dev/input/event2: 0003 0035 000001b6
/dev/input/event2: 0003 0036 0000030f
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0003 0030 00000000
/dev/input/event2: 0003 0032 00000000
/dev/input/event2: 0003 0035 00000000
/dev/input/event2: 0003 0036 00000000
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0000 000001b6
/dev/input/event2: 0003 0001 0000030f
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0030 0000000a
/dev/input/event2: 0003 0032 0000000a
/dev/input/event2: 0003 0035 000001b5
/dev/input/event2: 0003 0036 0000030a
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0003 0030 00000000
/dev/input/event2: 0003 0032 00000000
/dev/input/event2: 0003 0035 00000000
/dev/input/event2: 0003 0036 00000000
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0000 000001b5
/dev/input/event2: 0003 0001 0000030a
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0030 0000000a
/dev/input/event2: 0003 0032 0000000a
/dev/input/event2: 0003 0035 000001b6
/dev/input/event2: 0003 0036 00000305
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0003 0030 00000000
/dev/input/event2: 0003 0032 00000000
/dev/input/event2: 0003 0035 00000000
/dev/input/event2: 0003 0036 00000000
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0000 000001b6
/dev/input/event2: 0003 0001 00000305
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0030 0000000a
/dev/input/event2: 0003 0032 0000000a
/dev/input/event2: 0003 0035 000001b8
/dev/input/event2: 0003 0036 00000301
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0003 0030 00000000
/dev/input/event2: 0003 0032 00000000
/dev/input/event2: 0003 0035 00000000
/dev/input/event2: 0003 0036 00000000
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0000 000001b8
/dev/input/event2: 0003 0001 00000301
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0030 0000000a
/dev/input/event2: 0003 0032 0000000a
/dev/input/event2: 0003 0035 000001b7
/dev/input/event2: 0003 0036 000002fc
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0003 0030 00000000
/dev/input/event2: 0003 0032 00000000
/dev/input/event2: 0003 0035 00000000
/dev/input/event2: 0003 0036 00000000
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0000 000001b7
/dev/input/event2: 0003 0001 000002fc
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0003 0030 00000000
/dev/input/event2: 0003 0032 00000000
/dev/input/event2: 0003 0035 00000000
/dev/input/event2: 0003 0036 00000000
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0003 0030 00000000
/dev/input/event2: 0003 0032 00000000
/dev/input/event2: 0003 0035 00000000
/dev/input/event2: 0003 0036 00000000
/dev/input/event2: 0000 0002 00000000
/dev/input/event2: 0000 0000 00000000
/dev/input/event2: 0001 014a 00000000
/dev/input/event2: 0000 0000 00000000
"""

#             output = """
# add device 1: /dev/input/event1
#   name:     "synaptics_capsensor"
# add device 2: /dev/input/event2
#   name:     "auo_touchscreen"
# could not get driver version for /dev/input/mouse0, Not a typewriter
# add device 3: /dev/input/event4
#   name:     "8k_handset"
# add device 4: /dev/input/event3
#   name:     "surf_keypad"
# could not get driver version for /dev/input/mice, Not a typewriter
# add device 5: /dev/input/event0
#   name:     "Austin headset"
# /dev/input/event2: 0003 0035 000001b6
# /dev/input/event2: 0003 0036 00000315
# /dev/input/event2: 0000 0002 00000000
# /dev/input/event2: 0003 0035 00000000
# /dev/input/event2: 0003 0036 00000000
# /dev/input/event2: 0000 0002 00000000
# /dev/input/event2: 0000 0000 00000000
# /dev/input/event2: 0001 014a 00000001
# /dev/input/event2: 0003 0035 000001b6
# /dev/input/event2: 0003 0036 00000315
# /dev/input/event2: 0003 0035 000001b6
# /dev/input/event2: 0003 0036 00000315
# /dev/input/event2: 0003 0035 00000000
# /dev/input/event2: 0003 0036 00000000
# /dev/input/event2: 0000 0002 00000000
# /dev/input/event2: 0003 0035 00000000
# /dev/input/event2: 0003 0036 00000000
# /dev/input/event2: 0000 0002 00000000
# /dev/input/event2: 0000 0000 00000000
# /dev/input/event2: 0001 014a 00000000
# /dev/input/event2: 0000 0000 00000000
# """




#     if 'Upper' in title:
#         output = """
# add device 1: /dev/input/event1
#   name:     "synaptics_capsensor"
# add device 2: /dev/input/event3
#   name:     "auo_touchscreen"
# could not get driver version for /dev/input/mouse0, Not a typewriter
# add device 3: /dev/input/event4
#   name:     "8k_handset"
# add device 4: /dev/input/event2
#   name:     "surf_keypad"
# could not get driver version for /dev/input/mice, Not a typewriter
# add device 5: /dev/input/event0
#   name:     "Austin headset"
# /dev/input/event3: 0003 0030 0000000a
# /dev/input/event3: 0003 0032 0000000a
# /dev/input/event3: 0003 0035 00000027
# /dev/input/event3: 0003 0036 00000016
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0000 00000027
# /dev/input/event3: 0003 0001 00000016
# /dev/input/event3: 0001 014a 00000001
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0001 014a 00000000
# /dev/input/event3: 0000 0000 00000000"""
#     elif 'Lower' in title:
#         outputWithNoPostfix = """
# add device 1: /dev/input/event1
#   name:     "synaptics_capsensor"
# add device 2: /dev/input/event3
#   name:     "auo_touchscreen"
# could not get driver version for /dev/input/mouse0, Not a typewriter
# add device 3: /dev/input/event4
#   name:     "8k_handset"
# add device 4: /dev/input/event2
#   name:     "surf_keypad"
# could not get driver version for /dev/input/mice, Not a typewriter
# add device 5: /dev/input/event0
#   name:     "Austin headset"
# /dev/input/event3: 0003 0030 0000000a
# /dev/input/event3: 0003 0032 0000000a
# /dev/input/event3: 0003 0035 000001cb
# /dev/input/event3: 0003 0036 000002ed
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0000 000001cb
# /dev/input/event3: 0003 0001 000002ed
# /dev/input/event3: 0001 014a 00000001
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0030 0000000a
# /dev/input/event3: 0003 0032 0000000a
# /dev/input/event3: 0003 0035 000001c8
# /dev/input/event3: 0003 0036 000002ea
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0000 000001c8
# /dev/input/event3: 0003 0001 000002ea
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0030 0000000a
# /dev/input/event3: 0003 0032 0000000a
# /dev/input/event3: 0003 0035 000001c8
# /dev/input/event3: 0003 0036 000002ea
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0000 000001c8
# /dev/input/event3: 0003 0001 000002ea
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0001 014a 00000000
# /dev/input/event3: 0000 0000 00000000
# """

#         outputWithPostfix = """
# add device 1: /dev/input/event1
#   name:     "synaptics_capsensor"
# add device 2: /dev/input/event3
#   name:     "auo_touchscreen"
# could not get driver version for /dev/input/mouse0, Not a typewriter
# add device 3: /dev/input/event4
#   name:     "8k_handset"
# add device 4: /dev/input/event2
#   name:     "surf_keypad"
# could not get driver version for /dev/input/mice, Not a typewriter
# add device 5: /dev/input/event0
#   name:     "Austin headset"
# /dev/input/event3: 0003 0030 0000000a
# /dev/input/event3: 0003 0032 0000000a
# /dev/input/event3: 0003 0035 000001cb
# /dev/input/event3: 0003 0036 000002ed
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0000 000001cb
# /dev/input/event3: 0003 0001 000002ed
# /dev/input/event3: 0001 014a 00000001
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0030 0000000a
# /dev/input/event3: 0003 0032 0000000a
# /dev/input/event3: 0003 0035 000001c8
# /dev/input/event3: 0003 0036 000002ea
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0030 0000000a
# /dev/input/event3: 0003 0032 0000000a
# /dev/input/event3: 0003 0035 000001c8
# /dev/input/event3: 0003 0036 000002ea
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0000 000001c8
# /dev/input/event3: 0003 0001 000002ea
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0003 0030 00000000
# /dev/input/event3: 0003 0032 00000000
# /dev/input/event3: 0003 0035 00000000
# /dev/input/event3: 0003 0036 00000000
# /dev/input/event3: 0000 0002 00000000
# /dev/input/event3: 0000 0000 00000000
# /dev/input/event3: 0001 014a 00000000
# /dev/input/event3: 0000 0000 00000000
# """
#         output = outputWithPostfix

    #there will probably be only one candidate after both upper right and lower left corners have been done
    eventPathsSequencesComponentss = getInputEventSequences(potentialEventPaths, output)
    return eventPathsSequencesComponentss


# def identifyDownUpTextFromSimpleSequenceData(self, upperRightEventPathData, lowerLeftEventPathData,
#                                              lcdHeight, minX, maxX, minY, maxY):
#     # Figure out where the coordinate system is centered so that we can assign xScale, xIntercept, etc.
#     # Calculate the ranges for the max and min values of x and y.
#     # Identify (c1, c2) pairs having values within the ranges.
#     # There should be just one possible coordinate system center.
#     # Assign xScale, xIntercept, etc w/ knowledge of this center.
#     # Create up and down text based on these values.
#     eventPathsUR = set([x[0] for x in upperRightEventPathData])
#     eventPathsLL = set([x[0] for x in lowerLeftEventPathData])
#     eventPaths = list(eventPathsUR.intersection(eventPathsLL))
#     if len(eventPaths) > 1:
#         # todo ask for a third tap? use monkey?
#         eventPath = eventPaths[0]
#     elif len(eventPaths) < 1:
#         # todo use monkey?
#         return None, None, None, None, None, None, None, None, False
#     else:
#         urComponentss, llComponentss = [], []
#         eventPath = eventPaths[0]
#         for eventPath_, sequence, componentss in lowerLeftEventPathData:
#             if eventPath_ == eventPath:
#                 llComponentss = componentss
#                 break
#         for eventPath_, sequence, componentss in upperRightEventPathData:
#             if eventPath_ == eventPath:
#                 urComponentss = componentss
#                 break
#         xc1c2s, yc1c2s, xOrigin, yOrigin, success = \
#             determineXAndYKeys(self, urComponentss, llComponentss, lcdHeight, minX, maxX, minY, maxY)
#         if not success:
#             return None, None, None, None, None, None, None, None, False        

#         # Find the last sequence. Make it the up sequence. Replace the x, y values 
#         # in all sequences when their values are not zero.
#         # With the Samsung Gem, I've noticed that using two down events, rather than
#         # one, before the up event conclusively leads to the tap being more 
#         # frequently interpreted as a long press. Therefore, I'll only allow at most
#         # two down events.
#         numSequences = len(urComponentss) / len(sequence)
#         if numSequences > 2:
#             # Use two sequences for down.
#             # 2 = numSequences - numNotUsedForDown
#             # numNotUsedForDown = numSequences - 2
#             downComponentss = urComponentss[:-(len(sequence) * (numSequences - 2))]
#         else:
#             # Use one sequence for down.
#             downComponentss = urComponentss[:-(len(sequence) * (numSequences - 1))]
#         upComponentss = urComponentss[-len(sequence):]
        
#         downText, repeaterText, repeaterPostfixText, upText = \
#             getDownAndUpTextForStreak(self, xc1c2s, yc1c2s,
#                                       eventPath, downComponentss, upComponentss,
#                                       downComponentss, [])
#         return xc1c2s, yc1c2s, downText, repeaterText, repeaterPostfixText, upText, xOrigin, yOrigin, True



def identifyDownUpTextFromStreakStyleData(self, upperRightEventPathData, lowerLeftEventPathData,
                                          lcdHeight, minX, maxX, minY, maxY):    
    eventPathsUR = set([x[0] for x in upperRightEventPathData])
    eventPathsLL = set([x[0] for x in lowerLeftEventPathData])
    eventPaths = list(eventPathsUR.intersection(eventPathsLL))
    if len(eventPaths) > 1:
        # XXX ask for a third tap? use monkey?
        pass
    elif len(eventPaths) < 1:
        # XXX use monkey?
        pass
    else:
        eventPath = eventPaths[0]
    for eventPath_, sequence, componentss in upperRightEventPathData:
        if eventPath_ == eventPath:
            urComponentss = componentss
            break
    for eventPath_, sequence, componentss in lowerLeftEventPathData:
        if eventPath_ == eventPath:
            llComponentss = componentss
            break
    xc1c2s, yc1c2s, xOrigin, yOrigin, success = \
        determineXAndYKeys(self, urComponentss, llComponentss, lcdHeight, minX, maxX, minY, maxY)
    if not success:
        return None, None, None, None, None, None, None, None, None, False

    llnComponentss = [(comps[0], comps[1], 1 if comps[2] != 0 else 0) 
                      for comps in llComponentss]

    dprint('upperRightEventPathData:', upperRightEventPathData)
    dprint('lowerLeftEventPathData:', lowerLeftEventPathData)
    dprint('llComponentss:', llComponentss)
    dprint('llnComponentss:', llnComponentss)
    dprint('xc1c2s:', xc1c2s)
    dprint('yc1c2s:', yc1c2s)
    llDescendingKeyGroups = getDownUpCompss(llComponentss, llnComponentss, xc1c2s, yc1c2s)

    # From getDownUpCompss: key: (downEnd, upStart, postfixLength, repeaterStartIndex, repeaterEndIndex)
    key = llDescendingKeyGroups[0][0]
    beginningDownComponents = llComponentss[:key[0] + 1]
    upComponents = llComponentss[key[1]:]
    downSequenceToRepeat = llComponentss[key[3]:key[4] + 1]
    postfixComponentss = llComponentss[key[1] - key[2]:key[1]] if key[2] != 0 else []
    downText, repeaterText, repeaterPostfixText, upText, downUpText = \
        getDownAndUpTextForStreak(self, xc1c2s, yc1c2s,
                                  eventPath, beginningDownComponents, upComponents, 
                                  downSequenceToRepeat, postfixComponentss)
    return (xc1c2s, yc1c2s, downText, repeaterText, repeaterPostfixText, upText, downUpText, xOrigin, yOrigin, 
            llDescendingKeyGroups, True)


def getPNGNames(mgr, serialNo):
    prefixMap = {constants.PLAY_STATUS_NO_SESSION_LOADED:'explore',
                 constants.PLAY_STATUS_READY_TO_PLAY:'explore',
                 constants.PLAY_STATUS_PLAYING:'play',
                 constants.PLAY_STATUS_PAUSED:'pause',
                 constants.PLAY_STATUS_FINISHED:'explore',
                 constants.PLAY_STATUS_STOPPED:'explore',
                 constants.PLAY_STATUS_RECORDING:'record'}

    prefix = prefixMap[mgr.playStatus]
    #dprint("getImageData(), prefix:", prefix)
    #if prefix.startswith("explore") and mgr.playStatus.startswith('record'):

    # Spaces in the file names aren't written by the subprocess.Popen("ffmpeg ...")
    # correctly, even when quoted.
    if mgr.playStatus == constants.PLAY_STATUS_RECORDING:
        unflattenedPNGName = ('unflat.' + os.path.basename(mgr.getRecordingTestPath()).rsplit('.', 1)[0] + '.' 
                              + serialNo + '.png').replace(' ', '_')
        flattenedPNGName = (prefix + '.' + os.path.basename(mgr.getRecordingTestPath()).rsplit('.', 1)[0] + '.' 
                            + serialNo + '.' + str(time.time()) + '.png')
        flattenedPNGName = flattenedPNGName.replace(' ', '_')
        #dprint("block 1  flattenedPNGName:", flattenedPNGName)
    elif mgr.playStatus in [constants.PLAY_STATUS_PLAYING, constants.PLAY_STATUS_PAUSED]:
        unflattenedPNGName = ('unflat.' + os.path.basename(mgr.testFilePaths[mgr.currentTestIndex]).rsplit('.', 1)[0] + 
                              '.' + serialNo + '.png').replace(' ', '_')
        flattenedPNGName = (prefix + '.' + str(mgr.currentTestIndex) + '.' + 
                            os.path.basename(mgr.testFilePaths[mgr.currentTestIndex]).rsplit('.', 1)[0] + '.' + 
                            serialNo + '.' + str(time.time()) + '.png')
        flattenedPNGName = flattenedPNGName.replace(' ', '_')
        #dprint("block 2  flattenedPNGName:", flattenedPNGName)
    else:
        # In the case of playStatus == 'stop' or 'pause', the 
        # files named here are not made unique w/ the time,
        # so they'll be overwritten to avoid taking space.
        unflattenedPNGName = 'unflat.' + serialNo + '.png'
        flattenedPNGName = prefix + '.' + serialNo + '.' + str(time.time()) + '.png'
        #dprint("block 3  flattenedPNGName:", flattenedPNGName)

    unflattenedPNGPath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, unflattenedPNGName)
    flattenedPNGPath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, flattenedPNGName)
    return prefix, unflattenedPNGPath, flattenedPNGPath


def determineXAndYKeys(self, urComponentss, llComponentss, lcdHeight, minX, maxX, minY, maxY):
    # This method identifies the keys in getevent output that
    # correspond to x and y. It also sets <device>.xScale and
    # <device>.yScale.

    # calculate the expected values for x and y
    # get the keys from the xcomponents
    # go thru the urcomponents
    #   if a key has a value within the range for the max:
    #       add it to urfoundMax
    #   if a key does not have either the value 0 or a value within some percentage of the max:
    #       remove that key from those collected
    # the remaining candidates must appear in urfoundMax (otherwise they could be 0 all the time)
    # go thru the llcomponents
    #   if a key has a value within the range for the max:
    #       add it to llfoundMax
    #   if a key does not have either the value 0 or a value within some percentage of the max:
    #       remove that key from those collected
    # the remaining candidates must appear in llfoundMax (otherwise they could be 0 all the time)
    # no key can appear in both ur and ll candidates
    
    # The Streak shows the value 0 for keys to reflect an up-press, so 
    # the value in this case should be disregarded for the purpose of
    # identifying the x and y keys.
    def getPossible(componentss):
        # In the case of the Streak, two event and key pairs are used for both of x and y.
        # (3, 1), and (3, 54) encode the x-coordinate, while (3, 0), and (3, 53) encode the y-
        # coordinate.
        foundMaxX, foundMaxY = [], []
        removeMaxX, removeMaxY = [], []
        foundMinX, foundMinY = [], []
        removeMinX, removeMinY = [], []
        for c1, c2, c3 in componentss:
            if maxXLowerBound <= c3 <= maxXUpperBound:
                foundMaxX.append((c1, c2))
            elif c3 != 0: 
                removeMaxX.append((c1, c2))

            if maxYLowerBound <= c3 <= maxYUpperBound:
                foundMaxY.append((c1, c2))
            elif c3 != 0:
                removeMaxY.append((c1, c2))

            if minXLowerBound <= c3 <= minXUpperBound:
                foundMinX.append((c1, c2))
            elif c3 != 0: 
                removeMinX.append((c1, c2))

            if minYLowerBound <= c3 <= minYUpperBound:
                foundMinY.append((c1, c2))
            elif c3 != 0:
                removeMinY.append((c1, c2))

        possibleMaxX = set(foundMaxX) - set(removeMaxX)
        possibleMaxY = set(foundMaxY) - set(removeMaxY)
        possibleMinX = set(foundMinX) - set(removeMinX)
        possibleMinY = set(foundMinY) - set(removeMinY)
        return possibleMaxX, possibleMaxY, possibleMinX, possibleMinY

    # max and min x and y values are the same regardless of where the coordinate system
    # origin is. Here we calculate them using a coordinate system centered at the upper
    # left corner, though, again, it doesn't matter. (Later we'll assign scale and 
    # intercept based on where we identify the origin being.)
    leftSidedXScale = float(maxX - minX) / self.width
    leftSidedXIntercept = minX
    maxXUpperBound = (self.width * leftSidedXScale) + leftSidedXIntercept
    # dumpsys window on Droid2 reports absX minimum of 6, but 0 appears in the getevent output 
    # when tapped at the extreme edge, so we have to allow for less than the min X reported
    # by dumpsys window. The screen sensor allows one to tap outside of the LCD portion of the
    # screen.
    minXLowerBound = max(0, leftSidedXIntercept - (maxXUpperBound - leftSidedXIntercept) * 0.05)
    maxXLowerBound = (maxXUpperBound - minXLowerBound) * 0.75 + leftSidedXIntercept
    minXUpperBound = (maxXUpperBound - minXLowerBound) * 0.25 + leftSidedXIntercept
    
    # Devices with chin bars have a y-range greater than the visible
    # screen, so, b/c the user may accidentally tap part of the chin 
    # bar when he taps the corner, add to the total height that can 
    # be tapped.
    topSidedYScale = float(maxY - minY) / lcdHeight
    topSidedYIntercept = minY
    maxYUpperBoundNoChin = (lcdHeight * topSidedYScale) + topSidedYIntercept
    minYLowerBound = max(0, topSidedYIntercept - (maxYUpperBoundNoChin - topSidedYIntercept) * 0.05)
    # 1.1 for a reading that's actually in the chin bar.
    maxYUpperBound = 1.1 * (maxYUpperBoundNoChin - minYLowerBound) + topSidedYIntercept
    maxYLowerBound = (maxYUpperBoundNoChin - minYLowerBound) * 0.75 + topSidedYIntercept
    minYUpperBound = (maxYUpperBoundNoChin - minYLowerBound) * 0.25 + topSidedYIntercept

    urPossibleMaxX, urPossibleMaxY, urPossibleMinX, urPossibleMinY = getPossible(urComponentss)
    llPossibleMaxX, llPossibleMaxY, llPossibleMinX, llPossibleMinY = getPossible(llComponentss)

    # Because there are more likely to be minimum expected values close to 
    # zero, it may be more often correct to identify x and y by using the
    # corner of the screen where they have their max values rather than 
    # their min ones (eg urPossibleMinX). Also, b/c 
    # ll prolly has more values than ur, prefer ll to ur.
    # todo this isn't going to work when values for non-x and non-y keys
    # mimic those for x and y. temporary soln.
    # Return [(Xc1, Xc2), (Yc1, Yc2)]
    # Here, we assign scale and intercept based on where we identify the origin being.
    success = True
    xOrigin, yOrigin = None, None
    # There are four possible corners where the coordinate system can be centered. 
    # (Hopefully, no device has the center along an edge or in the middle). Intersecting 
    # the min and max keys for each corner will hopefully produce non-empty sets 
    # for x and y only for the one correct corner.
    # Let's write the code to assume that is the case. The force data could be 
    # confused with coordinate data, or TODO the device could have x and y maxes
    # and mins equal to each other, which would produce additional corner candidates. 
    # This could be solved in the future by asking the user to tap a third corner.
    upperLeftCenterX = urPossibleMaxX.intersection(llPossibleMinX)
    upperLeftCenterY = llPossibleMaxY.intersection(urPossibleMinY)
    if upperLeftCenterX != set([]) and upperLeftCenterY != set([]):
        xOrigin = 'left'
        yOrigin = 'top'
        self.xScale = leftSidedXScale
        self.xIntercept = leftSidedXIntercept
        self.yScale = topSidedYScale
        self.yIntercept = topSidedYIntercept
        return upperLeftCenterX, upperLeftCenterY, xOrigin, yOrigin, True
    else:
        upperRightCenterX = urPossibleMinX.intersection(llPossibleMaxX)
        upperRightCenterY = llPossibleMaxY.intersection(urPossibleMinY)
        if upperRightCenterX != set([]) and upperRightCenterY != set([]):
            xOrigin = 'right'
            yOrigin = 'top'
            self.xScale = float(minX - maxX) / self.width
            self.xIntercept = maxX
            self.yScale = topSidedYScale
            self.yIntercept = topSidedYIntercept
            return upperRightCenterX, upperRightCenterY, xOrigin, yOrigin, True
        else:
            lowerRightCenterX = urPossibleMinX.intersection(llPossibleMaxX)
            lowerRightCenterY = llPossibleMinY.intersection(urPossibleMaxY)
            if lowerRightCenterX != set([]) and lowerRightCenterY != set([]):
                xOrigin = 'right'
                yOrigin = 'bottom'
                self.xScale = float(minX - maxX) / self.width
                self.xIntercept = maxX
                self.yScale = float(minY - maxY) / lcdHeight
                self.yIntercept = maxY
                return lowerRightCenterX, lowerRightCenterY, xOrigin, yOrigin, True
            else:
                lowerLeftCenterX = urPossibleMaxX.intersection(llPossibleMinX)
                lowerLeftCenterY = llPossibleMinY.intersection(urPossibleMaxY)
                if lowerLeftCenterX != set([]) and lowerLeftCenterY != set([]):
                    self.xScale = leftSidedXScale
                    self.xIntercept = leftSidedXIntercept
                    self.yScale = float(minY - maxY) / lcdHeight
                    self.yIntercept = maxY
                    return lowerLeftCenterX, lowerLeftCenterY, xOrigin, yOrigin, True
                else:
                    return None, None, None, None, False

    # if llPossibleMaxX:
    #     xc1, xc2 = llPossibleMaxX[0]
    #     xOrigin = 'right'
    #     self.xScale = float(minX - maxX) / self.width
    #     self.xIntercept = maxX
    # elif urPossibleMaxX:
    #     xc1, xc2 = urPossibleMaxX[0]
    #     xOrigin = 'left'
    #     self.xScale = leftSidedXScale
    #     self.xIntercept = leftSidedXIntercept
    # else:
    #     success = False
    # if success and llPossibleMaxY:
    #     yc1, yc2 = llPossibleMaxY[0]
    #     yOrigin = 'top'
    #     self.yScale = topSidedYScale
    #     self.yIntercept = topSidedYIntercept
    # elif urPossibleMaxX:
    #     yc1, yc2 = urPossibleMaxY[0]
    #     yOrigin = 'bottom'
    #     self.yScale = float(minY - maxY) / lcdHeight
    #     self.yIntercept = maxY
    # else:
    #     success = False


    # # if xOrigin == 'left':
    # #     self.xScale = float(maxX - minX) / self.width
    # #     self.xIntercept = minX
    # #     maxXUpperBound = (self.width * self.xScale) + self.xIntercept
    # #     minXLowerBound = self.xIntercept
    # #     maxXLowerBound = (maxXUpperBound - minXLowerBound) * 0.75 + self.xIntercept
    # #     minXUpperBound = (maxXUpperBound - minXLowerBound) * 0.25 + self.xIntercept
    # # else:
    # #     self.xScale = float(minX - maxX) / self.width
    # #     self.xIntercept = maxX
    # #     maxXUpperBound = self.xIntercept
    # #     minXLowerBound = self.xIntercept + self.xScale * self.width
    # #     maxXLowerBound = 0.75 * (maxXUpperBound - minXLowerBound) + minXLowerBound
    # #     minXUpperBound = 0.25 * (maxXUpperBound - minXLowerBound) + minXLowerBound
    
    # # if yOrigin == 'top':
    # #     # Devices with chin bars have a y-range greater than the visible
    # #     # screen, so, b/c the user may accidentally tap part of the chin 
    # #     # bar when he taps the corner, add to the total height that can 
    # #     # be tapped.
    # #     self.yScale = float(maxY - minY) / lcdHeight
    # #     self.yIntercept = minY
    # #     maxYUpperBoundNoChin = (lcdHeight * self.yScale) + self.yIntercept
    # #     minYLowerBound = self.yIntercept
    # #     # 1.1 for a reading that's actually in the chin bar.
    # #     maxYUpperBound = 1.1 * (maxYUpperBoundNoChin - minYLowerBound) + self.yIntercept
    # #     maxYLowerBound = (maxYUpperBoundNoChin - minYLowerBound) * 0.75 + self.yIntercept
    # #     minYUpperBound = (maxYUpperBoundNoChin - minYLowerBound) * 0.25 + self.yIntercept
    # # else:
    # #     self.yScale = float(minY - maxY) / lcdHeight
    # #     self.yIntercept = maxY
    # #     maxYUpperBound = self.yIntercept
    # #     minYLowerBoundNoChin = self.yIntercept + self.yScale * lcdHeight
    # #     minYLowerBound = max(0, maxYUpperBound - 1.1 * (maxYUpperBound - minYLowerBoundNoChin))
    # #     maxYLowerBound = 0.75 * (maxYUpperBound - minYLowerBoundNoChin) + minYLowerBoundNoChin
    # #     minYUpperBound = 0.25 * (maxYUpperBound - minYLowerBoundNoChin) + minYLowerBoundNoChin



def getDownAndUpTextForStreak(self, xc1c2s, yc1c2s, eventPath, 
                              beginningDownComponentss, upComponentss, downRepeaterComponentss,
                              postfixComponentss):
    # Replace values not equal to 0 in beginningDownComponents, 
    # upComponents, and downRepeaterComponentss, and postfixComponentss with '{x}' and '{y}' to 
    # create the up and down and repeater text

    # 'ZZ="sendevent <eventPath>" ; '
    sendeventText = (chr(90) + chr(90) + chr(61) + chr(34) + chr(115) + chr(101) + 
                     chr(110) + chr(100) + chr(101) + chr(118) + chr(101) + 
                     chr(110) + chr(116) + chr(32) + eventPath + '" ; ')
    downText = sendeventText
    for c1, c2, c3 in beginningDownComponentss:
        downText += "$ZZ "
        if (c1, c2) in xc1c2s and c3 != 0:
            downText += str(c1) + " " + str(c2) + " {x} ; "
        elif (c1, c2) in yc1c2s and c3 != 0:
            downText += str(c1) + " " + str(c2) + " {y} ; "
        else:
            downText += str(c1) + " " + str(c2) + " " + str(c3) + " ; "
    downText = downText.rstrip(" ;") + " "

    upText = sendeventText
    for c1, c2, c3 in upComponentss:
        upText += "$ZZ "
        if (c1, c2) in xc1c2s and c3 != 0:
            upText += str(c1) + " " + str(c2) + " {x} ; "
        elif (c1, c2) in yc1c2s and c3 != 0:
            upText += str(c1) + " " + str(c2) + " {y} ; "
        else:
            upText += str(c1) + " " + str(c2) + " " + str(c3) + " ; "
    upText = upText.rstrip(" ;") + " "

    downUpText = sendeventText
    for c1, c2, c3 in beginningDownComponentss:
        downUpText += "$ZZ "
        if (c1, c2) in xc1c2s and c3 != 0:
            downUpText += str(c1) + " " + str(c2) + " {x} ; "
        elif (c1, c2) in yc1c2s and c3 != 0:
            downUpText += str(c1) + " " + str(c2) + " {y} ; "
        else:
            downUpText += str(c1) + " " + str(c2) + " " + str(c3) + " ; "
    for c1, c2, c3 in upComponentss:
        downUpText += "$ZZ "
        if (c1, c2) in xc1c2s and c3 != 0:
            downUpText += str(c1) + " " + str(c2) + " {x} ; "
        elif (c1, c2) in yc1c2s and c3 != 0:
            downUpText += str(c1) + " " + str(c2) + " {y} ; "
        else:
            downUpText += str(c1) + " " + str(c2) + " " + str(c3) + " ; "
    downUpText = downUpText.rstrip(" ;") + " "

    if downRepeaterComponentss:
        downSequenceText = sendeventText
        for c1, c2, c3 in downRepeaterComponentss:
            downSequenceText += "$ZZ "
            if (c1, c2) in xc1c2s and c3 != 0:
                downSequenceText += str(c1) + " " + str(c2) + " {x} ; "
            elif (c1, c2) in yc1c2s and c3 != 0:
                downSequenceText += str(c1) + " " + str(c2) + " {y} ; "
            else:
                downSequenceText += str(c1) + " " + str(c2) + " " + str(c3) + " ; "
        downSequenceText = downSequenceText.rstrip(" ;") + " "
    else:
        downSequenceText = ""

    if postfixComponentss:
        postfixText = sendeventText
        for c1, c2, c3 in postfixComponentss:
            postfixText += "$ZZ "
            if (c1, c2) in xc1c2s and c3 != 0:
                postfixText += str(c1) + " " + str(c2) + " {x} ; "
            elif (c1, c2) in yc1c2s and c3 != 0:
                postfixText += str(c1) + " " + str(c2) + " {y} ; "
            else:
                postfixText += str(c1) + " " + str(c2) + " " + str(c3) + " ; "
        postfixText = postfixText.rstrip(" ;") + " "
    else:
        postfixText = ""
    return downText, downSequenceText, postfixText, upText, downUpText


def getDownUpText(eventPath, sequence, componentss, xComponents, yComponents):
    numberOfSequences = len(componentss) / len(sequence)

    # Find the last sequence. Make it the up sequence. Replace the x, y values 
    # in all sequences.
    # With the Samsung Gem, I've noticed that using two down events, rather than
    # one, before the up event conclusively leads to the tap being more 
    # frequently interpreted as a long press. Therefore, I'll only allow at most
    # two down events.
    numSequences = len(componentss) / len(sequence)
    if numSequences > 2:
        # Use two sequences for down.
        # 2 = numSequences - numNotUsedForDown
        # numNotUsedForDown = numSequences - 2
        downComponentss = componentss[:-(len(sequence) * (numSequences - 2))]
    else:
        # Use one sequence for down.
        downComponentss = componentss[:-(len(sequence) * (numSequences - 1))]
    downText = ""
    sendeventText = "sendevent"
    for c1, c2, c3 in downComponentss:
        downText += sendeventText + " " + eventPath + " "
        if (c1 == xComponents[0] and 
            c2 == xComponents[1]):
            downText += str(c1) + " " + str(c2) + " {x} ; "
        elif (c1 == yComponents[0] and 
              c2 == yComponents[1]):
            downText += str(c1) + " " + str(c2) + " {y} ; "
        else:
            downText += str(c1) + " " + str(c2) + " " + str(c3) + " ; "
    downText = downText.rstrip(" ;") + " "

    upComponentss = componentss[-len(sequence):]
    upText = ""
    for c1, c2, c3 in upComponentss:
        upText += sendeventText + " " + eventPath + " "
        if (c1 == xComponents[0] and 
            c2 == xComponents[1]):
            upText += str(c1) + " " + str(c2) + " {x} ; "
        elif (c1 == yComponents[0] and 
              c2 == yComponents[1]):
            upText += str(c1) + " " + str(c2) + " {y} ; "
        else:
            upText += str(c1) + " " + str(c2) + " " + str(c3) + " ; "
    upText = upText.rstrip(" ;") + " "
    return (downText, upText), True


def reduceDown(eventPath, oneDownSequence, numberOfSequences, xComponents, yComponents):
    # 'ZZ="sendevent <eventPath>" ; '
    sendeventText = (chr(90) + chr(90) + chr(61) + chr(34) + chr(115) + chr(101) + 
                     chr(110) + chr(100) + chr(101) + chr(118) + chr(101) + 
                     chr(110) + chr(116) + chr(32) + eventPath + '" ; ')
    downText = sendeventText
    for c1, c2, c3 in oneDownSequence:
        downText += "$ZZ "
        if (c1 == xComponents[0] and 
            c2 == xComponents[1]):
            downText += str(c1) + " " + str(c2) + " {x} ; "
        elif (c1 == yComponents[0] and 
              c2 == yComponents[1]):
            downText += str(c1) + " " + str(c2) + " {y} ; "
        else:
            downText += str(c1) + " " + str(c2) + " " + str(c3) + " ; "

    if numberOfSequences == 2:
        downText = downText.rstrip(" ;") + " "
        _numberOfSequences = 1
    else:
        # just make it two
        downText = downText + downText.rstrip(" ;") + " "
        _numberOfSequences = 2
    return downText, _numberOfSequences

