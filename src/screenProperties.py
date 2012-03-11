# Copyright (C) 2012 Brian Kyckelhahn
#
# Licensed under a Creative Commons Attribution-NoDerivs 3.0 Unported 
# License. (the "License"); you may not use this file except in compliance 
# with the License. You may obtain a copy of the License at
#
#      http://creativecommons.org/licenses/by-nd/3.0/
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import cv
import logging
import re
import sys
import time
from wx.lib.embeddedimage import PyEmbeddedImage

from deviceFiles import allDeviceConstants
from globals_ import *
import utils


def getScreenDimensions(self):
    ###
    # Returns:
    # (self.minX, self.xScale, self.minY, self.yScale, self.width,
    #  self.height, dumpsysWindowOutput), success = self._getScreenProperties()
    ###
    traceLogger.debug("Calling 'adb shell dumpsys window'.")
    count = 0
    dumpsysWindowOutput = None
    while count < 3 and not dumpsysWindowOutput:
        count += 1
        dumpsysWindowOutput, e = self.dt.sendCommand("shell dumpsys window", waitForOutput=True)
    if not dumpsysWindowOutput:
        bdbg()
        dprint('err')
    foundX, foundY, foundPixelDims, foundTouchInputMapper = False, False, False, False
    if e:
        # This doesn't portend well for the ability to communicate w/ the
        # device; return nothing useful; don't both with storedVirtualKeys.
        return (foundX, foundY, foundPixelDims, 0, 0, 0, 0, 0, 0, ''), False
    traceLogger.debug("Call to 'adb shell dumpsys window' returned.")   
    output = dumpsysWindowOutput.split('\n')
    xMin, xMax, xScale, yMin, yMax, yScale = 0, 0, 0, 0, 0, 0

    # Scription expiration check:
    # 1302401958 was 20110409 ~8:15 PM.
#    if time.time() > (int("1302401" + str(ord('_')) + '8') + 60 * 60 * 24 * 200):
#        sys.exit()

    def parsePairs(pairs, first, second):
        first_, second_ = 0, 0
        for pair in pairs:
            if pair.startswith(first):
                try:
                    _, value = pair.split('=')
                    first_ = int(value)
                except:
                    return (0, 0), False
            elif pair.startswith(second):
                try:
                    _, value = pair.split('=')
                    second_ = int(value)
                except:
                    return (0, 0), False
        return (first_, second_), True

    width, height = None, None
    for lineNum, line in enumerate(output):
        # Emulator doesn't have absX or absY in 'dumpsys window' output.
        if line.lstrip().startswith("absX"):
            (xMin, xMax), success = parsePairs(line.lstrip().rstrip().split(), "minValue", "maxValue")
            if success:
                foundX = True
        elif line.lstrip().startswith("absY"):
            (yMin, yMax), success = parsePairs(line.lstrip().rstrip().split(), "minValue", "maxValue")
            if success:
                foundY = True
        elif line.lstrip().startswith(("mDisplayWidth", "mDisplayHeight")):
            # Emulator and Droid 2 have both mDisplayWidth and mDisplayHeight, near the top, and
            # DisplayWidth and DisplayHeight, near bottom.
            # Samsung Gem has only DisplayWidth and DisplayHeight, near bottom.
            (width, height), success = parsePairs(line.lstrip().rstrip().split(), "mDisplayWidth", "mDisplayHeight")
            if success:
                foundPixelDims = True
        elif line.lstrip().startswith(("DisplayWidth", "DisplayHeight")):
            # Emulator and Droid 2 have both mDisplayWidth and mDisplayHeight, near the top, and
            # DisplayWidth and DisplayHeight, near bottom.
            # Samsung Gem has only DisplayWidth and DisplayHeight, near bottom.
            (width, height), success = parsePairs(line.lstrip().rstrip().split(), "DisplayWidth", "DisplayHeight")
            if success:
                foundPixelDims = True
#            elif line.lstrip().startswith("Virtual Key #"):
#                virtualKeyNumber = int(line.lstrip()[len("Virtual Key #":].rstrip(': '))
        elif line.lstrip().startswith("Touch Input Mapper"):
            foundTouchInputMapper = True
            touchInputMapperStart = lineNum
        if foundPixelDims and foundX and foundY:
            break

    if not foundX and foundTouchInputMapper:
        text = '\n'.join(output[touchInputMapperStart:touchInputMapperStart + 100])
        sre = re.compile("Touch Input Mapper.*?Raw Axes:.*?X: min=([0-9]*), max=([0-9]*).*?Y: min=([0-9]*), max=([0-9]*)", re.MULTILINE | re.DOTALL)
        match = sre.search(text)
        if match:
            groups = match.groups()
            try:
                xMin, xMax, yMin, yMax = int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3])
            except:
                pass
            else:
                foundX, foundY = True, True
        else:
            sre = re.compile("Touch Input Mapper.*?Raw Axes:.*?Y: min=([0-9]*), max=([0-9]*).*?X: min=([0-9]*), max=([0-9]*)", re.MULTILINE | re.DOTALL)
            match = sre.search(text)
            if match:
                groups = match.groups()
                try:
                    yMin, yMax, xMin, xMax = int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3])
                except:
                    pass
                else:
                    foundX, foundY = True, True

    if not width:
        bdbg()
        dprint('err')
    if not foundX:
        xMin = 0
        xMax = width
    if not foundY:
        yMin = 0
        yMax = height
    return (foundX, foundY, foundPixelDims, xMin, xMax, yMin, 
            yMax, width, height, dumpsysWindowOutput), True


def getChinBarProperties(self, foundX, foundY, foundPixelDims, xMin, xMax, xScale, yMin, yMax, yScale, width, 
                         height, dumpsysWindowOutput, storedVirtualKeys):
    # Returns (self.chinBarHeight, self.chinBarImageString, virtualKeys), success
    hitLeftSRE = re.compile("Virtual Key #([0-9]):.*?hitLeft=([0-9]{1,4})", re.MULTILINE | re.DOTALL)
    hitTopSRE = re.compile("Virtual Key #([0-9]):.*?hitTop=([0-9]{1,4})", re.MULTILINE | re.DOTALL)
    hitRightSRE = re.compile("Virtual Key #([0-9]):.*?hitRight=([0-9]{1,4})", re.MULTILINE | re.DOTALL)
    hitBottomSRE = re.compile("Virtual Key #([0-9]):.*?hitBottom=([0-9]{1,4})", re.MULTILINE | re.DOTALL)

    def populateVirtualKeys(virtualKeys, number, parameter, value):
        if not virtualKeys.has_key(number):
            virtualKeys[number] = {}
        if not virtualKeys[number].has_key(parameter):
            virtualKeys[number][parameter] = value

    # Store hitLefts found to later eliminate misattributed values, which
    # will appear more than once.
    hitLefts, hitRights = [], []

    virtualKeyIndex = 0
    virtualKeys = {} # {0: {'hitLeft':495, 'hitTop':1012, ...} ...}
    while True:
        virtualKeyIndex = dumpsysWindowOutput.find("Virtual Key #", virtualKeyIndex)
        if virtualKeyIndex == -1:
            break

        for (sre, parameter) in [(hitLeftSRE, 'hitLeft'),
                                 (hitTopSRE, 'hitTop'),
                                 (hitRightSRE, 'hitRight'),
                                 (hitBottomSRE, 'hitBottom')]:
            m = sre.search(dumpsysWindowOutput[virtualKeyIndex:])
            if m:
                number, value = m.groups()
                number = int(number)
                value = int(value)
                populateVirtualKeys(virtualKeys, number, parameter, value)
                if parameter == 'hitLeft':
                    hitLefts.append(value)
                elif parameter == 'hitRight':
                    hitRights.append(value)
        virtualKeyIndex += 1

    def removeKeysMissingValue(values, parameter, virtualKeys):
        # Duplicate values will appear for hitLeft if hitLeft 
        # is not given in dumpsys for a virtual key.
        for value in values:
            index = values.index(value)
            timesFound = 0
            while True:
                timesFound += 1
                index += 1
                try:
                    index = values.index(value, index)
                except ValueError:
                    break
            if timesFound > 1:
                # One or more dupes was found. Delete the entire key.
                numRemoved = 0
                keysDeleted = []
                for key in virtualKeys:
                    if virtualKeys[key][parameter] == value:
                        keysDeleted += [key]
                        numRemoved += 1
                        if numRemoved == timesFound - 1:
                            break
                for key in keysDeleted:
                    del virtualKeys[key]

    removeKeysMissingValue(hitLefts, 'hitLeft', virtualKeys)
    removeKeysMissingValue(hitRights, 'hitRight', virtualKeys)
    deleteKeys = []
    for key in virtualKeys:
        if (virtualKeys[key].get('hitTop', None) is None or
            virtualKeys[key].get('hitBottom', None) is None):
            deleteKeys.append(key)
    for key in deleteKeys:
        del virtualKeys[key]
    # At this point, all entries in virtualKeys have all of hitLeft, hitRight, hitTop, hitBottom.

    if foundPixelDims and foundX and foundY:
        self._getVirtualKeyKeycodes(virtualKeys)
        # get the height of the virtual key bar
        # ASSUMPTION: hitTop and hitBottom are the same for all keys
        hitBottom = 0
        hitTop = 0

        # Could the number assigned to the key in dumpsys output ever
        # change? It's possible, so do this:
        virtualKeysByKeycode = {}
        for number in virtualKeys:
            keycode = virtualKeys[number].get('lastKeycode', 'Unknown-' + str(number))
            virtualKeysByKeycode[keycode] = {}
            virtualKeysByKeycode[keycode]['hitBottom'] = virtualKeys[number].get('hitBottom', None)
            virtualKeysByKeycode[keycode]['hitTop'] = virtualKeys[number].get('hitTop', None)
            virtualKeysByKeycode[keycode]['hitLeft'] = virtualKeys[number].get('hitLeft', None)
            virtualKeysByKeycode[keycode]['hitRight'] = virtualKeys[number].get('hitRight', None)


        def clash(retL, retR, retT, retB, stL, stR, stT, stB):
            """A boolean function indicating that the box retrieved from dumpsys during
            this run of the tool, indicated by ret*, overlaps with, but doesn't
            completely match, the stored box indicated by st*.
            To understand this function, draw:
            1. two boxes with an overlapping corner
            2. two boxes with left and right the same but overlapping vertically
            3. two boxes with top and bottom the same but overlapping laterally
            """
            one = retL < stL < retR
            two = retL < stR < retR
            three = retB < stB < retT
            four = retB < stT < retT
            five = retL == stL
            six = retR == stR
            seven = retT == stT
            eight = retB == stB
            return (((five or six) and (three or four)) or
                    ((one or two) and (three or four)) or
                    ((seven or eight) and (one or two)))

        # Pseudocode for the code that follows
        # go throught retrd keys
        # is there a clash with a stored key?
        #     disregard stored keys entirely
        # elif there is a match on left, right, top, bottom
        #     if the retrd keycode is unknown
        #         use that of the stored key
        #     elif the retrd keycode is different
        #         use that of the retrd key
        #     add the key to consolidatedKeys
        #     remove the stored key from its dictionary
        # # there will be no clashes with the remaining stored keys, b/c all have been checked
        # go through remaining stored keys
        #     if the stored keycode is also in the retrieved keys:
        #         this keycode wasn't removed, so delete
        #     add the key to consolidatedkeys

        disregardStoredProperties = False
        consolidatedVirtualKeys = {}
        for keycode in virtualKeysByKeycode:
            matchedStored = None

            retL = virtualKeysByKeycode[keycode]['hitLeft']
            retR = virtualKeysByKeycode[keycode]['hitRight']
            retT = virtualKeysByKeycode[keycode]['hitTop']
            retB = virtualKeysByKeycode[keycode]['hitBottom']

            if storedVirtualKeys == {}:
                consolidatedVirtualKeys[keycode] = {}
                consolidatedVirtualKeys[keycode]['hitLeft'] = virtualKeysByKeycode[keycode]['hitLeft']
                consolidatedVirtualKeys[keycode]['hitRight'] = virtualKeysByKeycode[keycode]['hitRight']
                consolidatedVirtualKeys[keycode]['hitTop'] = virtualKeysByKeycode[keycode]['hitTop']
                consolidatedVirtualKeys[keycode]['hitBottom'] = virtualKeysByKeycode[keycode]['hitBottom']
            else:
                for stKey in storedVirtualKeys:
                    if clash(retL, retR, retT, retB, storedVirtualKeys[stKey]['hitLeft'],
                             storedVirtualKeys[stKey]['hitRight'], storedVirtualKeys[stKey]['hitTop'],
                             storedVirtualKeys[stKey]['hitBottom']):
                        disregardStoredProperties = True
                        break
                    elif (retL == storedVirtualKeys[stKey]['hitLeft'] and
                          retR == storedVirtualKeys[stKey]['hitRight'] and
                          retT == storedVirtualKeys[stKey]['hitTop'] and
                          retB == storedVirtualKeys[stKey]['hitBottom']):
                        if str(keycode).startswith('Unknown'):
                            finalKeycode = stKey
                        elif keycode != stKey:
                            finalKeycode = keycode
                        else:
                            finalKeycode = keycode
                        consolidatedVirtualKeys[finalKeycode] = {}
                        consolidatedVirtualKeys[finalKeycode]['hitLeft'] = storedVirtualKeys[stKey]['hitLeft']
                        consolidatedVirtualKeys[finalKeycode]['hitRight'] = storedVirtualKeys[stKey]['hitRight']
                        consolidatedVirtualKeys[finalKeycode]['hitTop'] = storedVirtualKeys[stKey]['hitTop']
                        consolidatedVirtualKeys[finalKeycode]['hitBottom'] = storedVirtualKeys[stKey]['hitBottom']                        
                        matchedStored = stKey
                if disregardStoredProperties:
                    break
                elif matchedStored:
                    del storedVirtualKeys[matchedStored]
                else:
                    consolidatedVirtualKeys[keycode] = {}
                    consolidatedVirtualKeys[keycode]['hitLeft'] = virtualKeysByKeycode[keycode]['hitLeft']
                    consolidatedVirtualKeys[keycode]['hitRight'] = virtualKeysByKeycode[keycode]['hitRight']
                    consolidatedVirtualKeys[keycode]['hitTop'] = virtualKeysByKeycode[keycode]['hitTop']
                    consolidatedVirtualKeys[keycode]['hitBottom'] = virtualKeysByKeycode[keycode]['hitBottom']

        if disregardStoredProperties:
            consolidatedVirtualKeys = virtualKeysByKeycode
        else:
            # there will be no clashes with the remaining stored keys, b/c all have been checked                
            for keycode in storedVirtualKeys:
                if keycode in virtualKeysByKeycode:
                    # The virtual key has moved to a different location.
                    pass
                else:
                    consolidatedVirtualKeys[keycode] = {}
                    consolidatedVirtualKeys[keycode]['hitLeft'] = storedVirtualKeys[keycode]['hitLeft']
                    consolidatedVirtualKeys[keycode]['hitRight'] = storedVirtualKeys[keycode]['hitRight']
                    consolidatedVirtualKeys[keycode]['hitTop'] = storedVirtualKeys[keycode]['hitTop']
                    consolidatedVirtualKeys[keycode]['hitBottom'] = storedVirtualKeys[keycode]['hitBottom']                        

        for key in consolidatedVirtualKeys:
            if consolidatedVirtualKeys[key].has_key('hitBottom'):
                hitBottom = consolidatedVirtualKeys[key]['hitBottom']
            if consolidatedVirtualKeys[key].has_key('hitTop'):
                hitTop = consolidatedVirtualKeys[key]['hitTop']
            if hitBottom != 0 and hitTop != 0:
                break

        if hitBottom != 0 and hitTop != 0:
            for key in consolidatedVirtualKeys:
                consolidatedVirtualKeys[key]['hitBottom'] = hitBottom
                consolidatedVirtualKeys[key]['hitTop'] = hitTop
            internalBarHeight = hitBottom - yMax
            barHeightInPixels = (height * internalBarHeight) / (yMax - yMin)
            # internalY = pixelY * yScale + internalMinY
            # (internalY - internalMinY) / yScale = pixelY
            # yScale = (yMax - yMin) / height
            internalBarYCenter = ((hitTop + hitBottom) / 2)
            pixelBarYCenter = int((internalBarYCenter - yMin) / (float(yMax - yMin) / height))
        else:
            return (0, '', {}), True
        # calculate the center of image key in the bar
        # create the image of the bar
        barString = width * barHeightInPixels * '\x00\x00\x00'
        yMargin = 10 # XXX
        homeX, homeY = 0, 0
        for key in consolidatedVirtualKeys:
            if not str(key).startswith("Unknown"):
                if key == -allDeviceConstants.CHIN_HOME:
                    image = PyEmbeddedImage(
                        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeCAIAAAC0Ujn1AAAAAXNSR0IArs4c6QAAAAlwSFlz"
                        "AAALEwAACxMBAJqcGAAAAAd0SU1FB9sCFBQrLTkWf1QAAAAZdEVYdENvbW1lbnQAQ3JlYXRl"
                        "ZCB3aXRoIEdJTVBXgQ4XAAAAgklEQVRIx+2USQ7AIAwDMcr/v5weKnHoAo4VUCXqIwqTDVPK"
                        "XnJ3d5+b4NvcCyiTex9unw6hXoC6VXluI54nwxcCjct0UENcfho99CM3REeUy8dA4zKRkLnD"
                        "eNMqYqxobysifdxpzrTt57hRzmr8HKNfXS3TZNGSE4y+dI17oH+t0wFcSGAI8QDPqQAAAABJ"
                        "RU5ErkJggg==").GetBitmap()
                    #path = os.path.join(wx.StandardPaths_Get().GetDataDir(), 'images/chinHome.png')
                elif key == -allDeviceConstants.CHIN_BACK:
                    image = PyEmbeddedImage(
                        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeCAIAAAC0Ujn1AAAAAXNSR0IArs4c6QAAAAlwSFlz"
                        "AAALEwAACxMBAJqcGAAAAAd0SU1FB9sCFBQmCMe81V4AAAAZdEVYdENvbW1lbnQAQ3JlYXRl"
                        "ZCB3aXRoIEdJTVBXgQ4XAAAAfElEQVRIx+2SOQ4AIAgE3Y3/f7JYmNhIVEA7pvQYEbaUxI6I"
                        "iIj1Fm+8voJw6QXwUh3x7tRBr64G0FqzWbTn8WRuqlpJCMknkQ31en+Gxz+6c83VOIjbcRzI"
                        "TMs6g7mlNqQeEwJgrFhrr+5smXvtHpqnIW5YvvFRnSSJiQ7RbjkfssvqRQAAAABJRU5ErkJg"
                        "gg==").GetBitmap()
                elif key == -allDeviceConstants.CHIN_MENU:
                    image = PyEmbeddedImage(
                        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeCAIAAAC0Ujn1AAAAAXNSR0IArs4c6QAAAAlwSFlz"
                        "AAALEwAACxMBAJqcGAAAAAd0SU1FB9sCFBQwJgfybUYAAAAZdEVYdENvbW1lbnQAQ3JlYXRl"
                        "ZCB3aXRoIEdJTVBXgQ4XAAAAPUlEQVRIx2NgGAWjYIAAI6bQ////STaFEYs5TKMBMhogwzBA"
                        "GCgMkP///+NSz0Sh6VhDeTSFjIJRMAooBwCUkxgGgO9fQAAAAABJRU5ErkJggg==").GetBitmap()
                elif key == -allDeviceConstants.CHIN_SEARCH:
                    image = PyEmbeddedImage(
                        "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeCAIAAAC0Ujn1AAAAAXNSR0IArs4c6QAAAAlwSFlz"
                        "AAALEwAACxMBAJqcGAAAAAd0SU1FB9sCFBQtOuyfXRUAAAAZdEVYdENvbW1lbnQAQ3JlYXRl"
                        "ZCB3aXRoIEdJTVBXgQ4XAAAAm0lEQVRIx+2WSwrAIAxEHfH+V54uSkXUaj4KLTgLF6KPZBLT"
                        "hnD0cZEkOT4DA7RGAF50hpase/ONvsCBqTkuZy30lstHY3qU0FtzJUq2NLt1qzaj1h9XM5jr"
                        "Y/F645tem5z6Wnsm7ssMqmsASOYmGQ8QTKE3ruy87pyypFmuKqVxvJ7qR+GrW/MIyxgl41Qd"
                        "tf8Lgmm3nX+MH+gCIr590umFWkkAAAAASUVORK5CYII=").GetBitmap()

                image = image.ConvertToImage()
                cvImage = cv.CreateImageHeader((image.Width, image.Height),
                                               cv.IPL_DEPTH_8U, 3)
                cv.SetData(cvImage, image.Data)
                internalXCenter = (consolidatedVirtualKeys[key]['hitRight'] + consolidatedVirtualKeys[key]['hitLeft']) / 2
                pixelXCenter = int((internalXCenter - xMin) / (float(xMax - xMin) / width))
                barString = utils._superimposeImage(barString, width, barHeightInPixels, cvImage, pixelXCenter,
                                                    pixelBarYCenter - height, yMargin)
                if key == -allDeviceConstants.CHIN_HOME:
                    # Tap home again so that the test starts from the home screen for
                    # appearance's sake.
                    x = (consolidatedVirtualKeys[key]['hitLeft'] + consolidatedVirtualKeys[key]['hitRight']) / 2
                    y = (consolidatedVirtualKeys[key]['hitTop'] + consolidatedVirtualKeys[key]['hitBottom']) / 2
                    self.dt.down(x, y)
                    self.dt.up(x, y)
        return (barHeightInPixels, barString, consolidatedVirtualKeys), True
    elif foundPixelDims:
        return (0, '', {}), True
    return (0, '', {}), False
