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


import ctypes
import logging
import os
import re
import subprocess
import sys
import threading
import time
import types

import config
import constants
from globals_ import *
# This import prevents another import bug in a different module.
# Untangling these isn't a high priority.
import gui
import deviceFiles.allDeviceConstants as allDeviceConstants


SENDEVENT_SLEEP=0.1
# SHELL_INPUT_SLEEP of 0.1 was tried on Droid 2 and was too fast.
SHELL_INPUT_SLEEP=0.5


class TextString(object):
    def __init__(self, string):
        self.string = string
    def __repr__(self):
        return self.string
    

class Keyevent(object):
    def __init__(self, keyevent):
        self.keyevent = keyevent    
    def __repr__(self):
        return str(self.keyevent)
    

import deviceFiles.DROID_2 as DROID_2


logging.basicConfig(level=logging.DEBUG)


def sendCommand(command, waitForOutput=False, sendingText=False, timeout=constants.ADB_TIMEOUT,
                debugLevel=constants.DEBUG_DEBUG_LEVEL):
    # If we deal with adb errors here, such as no device found or ADB path
    # misconfigured, then we:
    # 1. keep ourselves from having to deal with them in the many more
    #    places they're encountered in client code
    # 2. or, alternatively, we avoid throwing our hands up and letting the
    #    application crash when the exception gets to the top


    # The best policy when sending text is to try to send it even if it takes
    # unusually long, and to then inform the sender to not send such big 
    # command strings in the future. When sending other types of commands, there
    # may not be a way to cut the command string length, so no additional sleep
    # is performed.
    
    # Second thoughts on the statement above: ADB_TIMEOUT should be avoided if
    # at all possible, considering that killing threads can cause leaks and deadlocks, so set
    # it very high.

    # Adapted from http://stackoverflow.com/questions/1191374/subprocess-with-timeout#answer-4825933.
    def target(process, output, error):
        o, e = process.communicate()
        output += [o]
        error += [e]


#    if debugLevel == constants.DEBUG_DEBUG_LEVEL:
#        logger = adbLogger.debug
#    elif debugLevel == constants.CRITICAL_DEBUG_LEVEL:
#        logger = adbLogger.critical

    logger = sendCommandLogger.debug

    for attempt in range(constants.MAX_NUMBER_ADB_ATTEMPTS):
        if attempt > 0:
            dprint("attempt " + str(attempt) + " for command " + command)
        try:
            process = subprocess.Popen(command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError, e:
            # errno == 2 for both Linux and Windows when adb path is misconfigured
            if e.errno == 2:
                raise ADBMisconfigured(command)
            raise
        output = []
        error = []
        thread = threading.Thread(target=target, args=(process, output, error))
        thread.start()
        if attempt == 0:
            timeout_ = timeout
        elif attempt == 1:
            # Just guessing.
            timeout_ = timeout * 3
        else:
            timeout_ = timeout * 4
        thread.join(timeout_)
        if thread.isAlive():
#            if sendingText:
#                time.sleep(timeout)
            if thread.isAlive():
                # The process hasn't returned and must be killed.
                dprint("The process for command " + command + " hasn't returned and must be killed.")
                if sys.platform in ('win32', 'cygwin'):
                    try:
                        # Notice that [killing a thread] is inherently unsafe. It will likely 
                        # lead to uncollectable garbage (from local variables of the stack 
                        # frames that become garbage), and may lead to deadlocks, if the 
                        # thread being killed has the GIL at the point when it is killed.
                        # -http://stackoverflow.com/questions/323972/
                        #         is-there-any-way-to-kill-a-thread-in-python
                        ctypes.windll.kernel32.TerminateProcess(int(process._handle), -1)
                    except:
                        # This except block was never needed when there was a single
                        # isAlive() check, but it's hard to imagine that it could
                        # not be needed in a small number of very poorly-timed cases.
                        pass
                else:
                    try:
                        process.terminate()
                    except:
                        pass
            return None, constants.PROCESS_DID_NOT_TERMINATE
        else:
            if error[0].rstrip() in (constants.DEVICE_NOT_FOUND_ERROR_MESSAGE,):
                time.sleep(constants.POST_DEVICE_NOT_FOUND_SLEEP)
            else:
                return output[0], error[0]
    if error[0].rstrip() in (constants.DEVICE_NOT_FOUND_ERROR_MESSAGE,):
        raise ADBDeviceNotFoundException()
    assert(False)


def fasterSendCommand(command, timeout=constants.ADB_TIMEOUT):
    def target(process):
        process.communicate()

    for attempt in range(constants.MAX_NUMBER_ADB_ATTEMPTS):
        try:
            process = subprocess.Popen(command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError, e:
            # errno == 2 for both Linux and Windows when adb path is misconfigured
            if e.errno == 2:
                raise ADBMisconfigured(command)
            raise

        thread = threading.Thread(target=target, args=(process,))
        thread.start()
        if attempt == 0:
            timeout_ = timeout
        elif attempt == 1:
            # Just guessing.
            timeout_ = timeout * 3
        else:
            timeout_ = timeout * 4
        thread.join(timeout_)
        if thread.isAlive():
            if thread.isAlive():
                # The process hasn't returned and must be killed.
                if sys.platform in ('win32', 'cygwin'):
                    try:
                        # Notice that [killing a thread] is inherently unsafe. It will likely 
                        # lead to uncollectable garbage (from local variables of the stack 
                        # frames that become garbage), and may lead to deadlocks, if the 
                        # thread being killed has the GIL at the point when it is killed.
                        # -http://stackoverflow.com/questions/323972/
                        #         is-there-any-way-to-kill-a-thread-in-python
                        ctypes.windll.kernel32.TerminateProcess(int(process._handle), -1)
                    except:
                        # This except block was never needed when there was a single
                        # isAlive() check, but it's hard to imagine that it could
                        # not be needed in a small number of very poorly-timed cases.
                        pass
                else:
                    try:
                        process.terminate()
                    except:
                        pass
            return # None, constants.PROCESS_DID_NOT_TERMINATE
        else:
            return


def sendCommandDontKill(command, waitForOutput=False, sendingText=False):
    # In contrast with sendCommand(), this version doesn't use a Thread
    # and doesn't kill the process.
    for attempt in range(constants.MAX_NUMBER_ADB_ATTEMPTS):
        try:
            process = subprocess.Popen(command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError, e:
            # errno of 2 means "The system cannot find the file specified", at least
            # for Linux and Windows.
            if e.errno == 2:
                raise ADBMisconfigured(command)
            raise
        else:
            output, error = process.communicate()
            if error.rstrip() in (constants.DEVICE_NOT_FOUND_ERROR_MESSAGE,):
                time.sleep(constants.POST_DEVICE_NOT_FOUND_SLEEP)
                if 'ZZ' in command: dprint('sendCommand5')
            else:
                return output, error
    if error.rstrip() in (constants.DEVICE_NOT_FOUND_ERROR_MESSAGE,):
        raise ADBDeviceNotFoundException()
    assert(False)


def simpleSendCommandAndKill(command, timeout):
    # I use this routine when it's known that the process won't terminate
    # on its own.
    proc = subprocess.Popen(command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(timeout)
    try:
        # Avoid 'Access is denied' exception.
        proc.kill()
    except:
        pass
    o, e = proc.communicate()
    return o,e


class ADBTransport(object):
    def __init__(self, serialNo="", device=None, deviceType=constants.NON_EMULATOR_DEVICE_TYPE, noGUI=False):
        self.serialNo = serialNo
        self.device = device
        self.deviceType = deviceType

        self.maxADBCommandLength = constants.DEFAULT_MAX_ADB_COMMAND_LENGTH
        if serialNo:
            self.serialNoString = " -s " + self.serialNo + " "
        else:
            self.serialNoString = " "

        self.downText = ""
        self.upText = ""
        self.downUpText = ""

        self.keycodeEntererLock = threading.Lock()
        self.keycodeEntererThread = None

        
    def setSerialNo(self, serialNo):
        self.serialNo = serialNo
        self.serialNoString = " -s " + self.serialNo + " "


    def getADBCommandPrefix(self):
        return config.adbPath + self.serialNoString


    def setText(self, downText, upText, downRepeaterText, repeaterPostfixText, downUpText):
        dprint("setText")
        # The pressing down here at (0,0) explains why the notification bar briefly pops down on the
        # Gem when the tool starts.
        self.downText = downText
        self.upText = upText
        self.downRepeaterText = downRepeaterText
        self.repeaterPostfixText = repeaterPostfixText
        self.downUpText = downUpText

        # See if we've assigned something too long.
        _, eDown = self.down(0, 0)
        if eDown and constants.ERROR_ADB_COMMAND_LENGTH in eDown:
            # maxADBCommandLength is not used by down() or up(). Maybe it's not helpful here.
            self.maxADBCommandLength = self.maxADBCommandLength * constants.ADB_COMMAND_REDUCTION_FACTOR

        eRepeater, ePostfix = None, None
        if downRepeaterText:
            _, eRepeater = self.downRepeater(0, 0)
            if eRepeater and constants.ERROR_ADB_COMMAND_LENGTH in eRepeater:
                # maxADBCommandLength is not used by down() or up(). Maybe it's not helpful here.
                self.maxADBCommandLength = self.maxADBCommandLength * constants.ADB_COMMAND_REDUCTION_FACTOR

            if repeaterPostfixText:
                _, ePostifx = self.repeaterPostfix(0, 0)
                if ePostfix and constants.ERROR_ADB_COMMAND_LENGTH in ePostfix:
                    # maxADBCommandLength is not used by down() or up(). Maybe it's not helpful here.
                    self.maxADBCommandLength = self.maxADBCommandLength * constants.ADB_COMMAND_REDUCTION_FACTOR

        _, eUp = self.up(0, 0)
        if eUp and constants.ERROR_ADB_COMMAND_LENGTH in eUp:
            # maxADBCommandLength is not used by down() or up(). Maybe it's not helpful here.
            self.maxADBCommandLength = self.maxADBCommandLength * constants.ADB_COMMAND_REDUCTION_FACTOR

        _, eDownUp = self.downUp(0, 0)
        if eDownUp and constants.ERROR_ADB_COMMAND_LENGTH in eDownUp:
            self.downUpText = ""

        return eDown, eUp, eRepeater, ePostfix


    def sendCommand(self, command, waitForOutput=False, timeout=constants.ADB_TIMEOUT, debugLevel=constants.DEBUG_DEBUG_LEVEL):
        try:
            result = sendCommand(config.adbPath + self.serialNoString + command, 
                                 waitForOutput=waitForOutput, timeout=timeout, debugLevel=debugLevel)
        except Exception, e:
            raise
        return result

        
    def simpleSendCommandAndKill(self, command, timeout):
        try:
            result = simpleSendCommandAndKill(config.adbPath + self.serialNoString + command, 
                                              timeout)
        except Exception, e:
            raise
        return result


    def down(self, x, y):
        moveLogger.debug("internal down(%d, %d)", x, y)
        # I decided with KeycodeEnterer to use the part after 'adb' as the string to
        # measure the length of; we're sticking to that here.
        thisDownText = "shell " + self.downText.format(x=x, y=y)
        o, e = sendCommandDontKill(config.adbPath + self.serialNoString + thisDownText)
        return o, e


    def downWithKill(self, x, y):
        # I decided with KeycodeEnterer to use the part after 'adb' as the string to
        # measure the length of; we're sticking to that here.
        dprint('downwithkill')
        thisDownText = "shell " + self.downText.format(x=x, y=y)
        o, e = sendCommand(config.adbPath + self.serialNoString + thisDownText,
                           waitForOutput=True, timeout=1,
                           debugLevel=constants.DEBUG_DEBUG_LEVEL)
        return o, e


    def fixMonkeyRunner(self, x, y):
        thisDownText = "shell " + self.downText.format(x=x, y=y)
        o, e = sendCommand(config.adbPath + self.serialNoString + thisDownText,
                           waitForOutput=True, timeout=1,
                           debugLevel=constants.DEBUG_DEBUG_LEVEL)
        thisUpText = "shell " + self.upText.format(x=x, y=y)
        o, e = sendCommand(config.adbPath + self.serialNoString + thisUpText,
                           waitForOutput=True, timeout=1,
                           debugLevel=constants.DEBUG_DEBUG_LEVEL)


    def downUp(self, x, y):
        moveLogger.debug("internal downUp(%d, %d)", x, y)
        # I decided with KeycodeEnterer to use the part after 'adb' as the string to
        # measure the length of; we're sticking to that here.
        thisDownUpText = "shell " + self.downUpText.format(x=x, y=y)
        o, e = sendCommandDontKill(config.adbPath + self.serialNoString + thisDownUpText)
        return o, e


    def downUpWithKill(self, x, y):
        # I decided with KeycodeEnterer to use the part after 'adb' as the string to
        # measure the length of; we're sticking to that here.
        thisDownText = "shell " + self.downUpText.format(x=x, y=y)
        o, e = simpleSendCommandAndKill(config.adbPath + self.serialNoString + thisDownText,
                                        2)
        return o, e


    def downRepeater(self, x, y):
        moveLogger.debug("internal downRepeater(%d, %d)", x, y)

        # I decided with KeycodeEnterer to use the part after 'adb' as the string to
        # measure the length of; we're sticking to that here.
        thisDownText = "shell " + self.downRepeaterText.format(x=x, y=y)
        o, e = sendCommandDontKill(config.adbPath + self.serialNoString + thisDownText)
        return o, e


    def downRepeaterWithKill(self, x, y):
        # I decided with KeycodeEnterer to use the part after 'adb' as the string to
        # measure the length of; we're sticking to that here.
        thisDownText = "shell " + self.downRepeaterText.format(x=x, y=y)
        o, e = sendCommand(config.adbPath + self.serialNoString + thisDownText,
                           waitForOutput=True, timeout=2,
                           debugLevel=constants.DEBUG_DEBUG_LEVEL)
        return o, e


    def repeaterPostfix(self, x, y):
        # I decided with KeycodeEnterer to use the part after 'adb' as the string to
        # measure the length of; we're sticking to that here.
        if self.repeaterPostfixText:
            postfixText = "shell " + self.repeaterPostfixText.format(x=x, y=y)
            o, e = sendCommandDontKill(config.adbPath + self.serialNoString + postfixText)
            return o, e
        else:
            return None, None


    def repeaterPostfixWithKill(self, x, y):
        # I decided with KeycodeEnterer to use the part after 'adb' as the string to
        # measure the length of; we're sticking to that here.
        if self.repeaterPostfixText:
            postfixText = "shell " + self.repeaterPostfixText.format(x=x, y=y)
            o, e = sendCommand(config.adbPath + self.serialNoString + postfixText,
                               waitForOutput=True, timeout=2,
                               debugLevel=constants.DEBUG_DEBUG_LEVEL)
            return o, e
        else:
            return None, None


    def up(self, x=None, y=None):
        dprintParent()
        # XXX left down and left up, for a tap, should be made atomic
        moveLogger.debug("internal up(%d, %d)", x, y)        

        thisUpText = "shell " + self.upText.format(x=x, y=y)
        o, e = sendCommandDontKill(config.adbPath + self.serialNoString + thisUpText)
        #o, e = sendCommand(config.adbPath + self.serialNoString + thisUpText,
        #                   waitForOutput=True, timeout=2,
        #                   debugLevel=constants.DEBUG_DEBUG_LEVEL)
        return o, e


    def upWithKill(self, x=None, y=None):
        # XXX left down and left up, for a tap, should be made atomic
        dprint('upwithkill')
        thisUpText = "shell " + self.upText.format(x=x, y=y)
        o, e = sendCommand(config.adbPath + self.serialNoString + thisUpText,
                           waitForOutput=True, timeout=1,
                           debugLevel=constants.DEBUG_DEBUG_LEVEL)
        return o, e


        # if self.deviceType == constants.NON_EMULATOR_DEVICE_TYPE:
        #     commands = ("sendevent /dev/input/event3 3 48 0 ; " + 
        #                 "sendevent /dev/input/event3 3 50 3 ; " + 
        #                 "sendevent /dev/input/event3 3 53 " + str(x) + " ; " +
        #                 "sendevent /dev/input/event3 3 54 " + str(y) + " ; " +
        #                 "sendevent /dev/input/event3 0 2 0 ; " + 
        #                 "sendevent /dev/input/event3 0 0 0 ")
        #     line = "shell " + commands
        #     sendCommandDontKill(config.adbPath + self.serialNoString + line)
        # elif self.deviceType == constants.EMULATOR_DEVICE_TYPE:
        #     commands = ["shell sendevent /dev/input/event0 1 330 0",
        #                 "shell sendevent /dev/input/event0 0 0 0"]
        #     commands = [x.format(addr=self.serialNo) for x in commands]       
        #     for command in commands:
        #         sendCommandDontKill(config.adbPath + self.serialNoString + command)
        #         time.sleep(SENDEVENT_SLEEP)


    def drag(self, x, y, newX, newY, stepSize, kill=False):
        moveLogger.debug("drag(), x: " + str(x) + " y: " + str(y))
        moveLogger.debug("drag(), newX: " + str(newX) + " newY: " + str(newY))

        xRange = newX - x if newX > x else x - newX
        numIntermediatesX = int(xRange / stepSize) - 1
        yRange = newY - y if newY > y else y - newY
        numIntermediatesY = int(yRange / stepSize) - 1
        numIntermediates = max(numIntermediatesX, numIntermediatesY)
        
        if numIntermediates > 0:
            xStepSize = (newX - x) / (numIntermediates + 1)
            yStepSize = (newY - y) / (numIntermediates + 1)
        
        points = [(x, y)]
        for intermediate in range(numIntermediates):
            points += [(x + xStepSize * (intermediate + 1), y + yStepSize * (intermediate + 1))]
        points += [(newX, newY)]
        
        commands = []
        # At least when there are only two points, a down at the start point and an up at the
        # end point, without a down also at the end point prior to the up, is interpreted by 
        # the device as a tap at the start point. So, add a down at the end point.
        if kill:
            if len(points) == 2:
                self.downWithKill(points[0][0], points[0][1])
                self.downWithKill(points[-1][0], points[-1][1])
                self.upWithKill(points[-1][0], points[-1][1])
            else:
                for point in points:
                    self.downWithKill(point[0], point[1])
                self.upWithKill(points[-1][0], points[-1][1])
        else:
            if len(points) == 2:
                self.down(points[0][0], points[0][1])
                self.down(points[-1][0], points[-1][1])
                self.up(points[-1][0], points[-1][1])
            else:
                for point in points:
                    self.down(point[0], point[1])
                self.up(points[-1][0], points[-1][1])


    def enterKeycodes(self, keycodes):
        self.keycodeEntererLock.acquire()
        if self.keycodeEntererThread and self.keycodeEntererThread.isAlive:
            self.keycodeEntererThread.codesToProcess = self.keycodeEntererThread.codesToProcess + keycodes
            self.keycodeEntererLock.release()
        else:
            # The lock is acquired above for the benefit of the 'if' block
            # above.
            self.keycodeEntererLock.release()
            self.keycodeEntererThread = KeycodeEnterer(self, self.device.keycodeMap, self.serialNo, self.keycodeEntererLock,
                                                       keycodes)


class KeycodeEnterer(threading.Thread):
    def __init__(self, dt, keycodeMap, serialNo, lock, keycodes):
        self.dt = dt
        self.keycodeMap = keycodeMap
        self.serialNo = serialNo
        self.keycodeEntererLock = lock

        if serialNo:
            self.serialNoString = " -s " + self.serialNo + " "
        else:
            self.serialNoString = " "

        keycodeLogger.debug("type(keycodes): %s", str(type(keycodes[0])) if len(keycodes) > 0 else "<empty>")
        keycodeLogger.debug("keycodes:" + str(keycodes))
        # codesToProcess has the earliest-entered codes at its start

        # I have seen problems on both Droid 2 and Samsung Gem with text entry skipping the 
        # first few chars. The tool could be made to correct this problem. However, 
        # *correcting* text entry by entering chars and then backing them out before
        # entering the user's text does cause a problem when the application appears to disallow
        # characters from a-z, such as the dialer app on Samsung Gem. In this case, no chars are
        # entered, but backspace *is* allowed, so existing numbers in the app are removed, which
        # is not a desired behavior.
        self.codesToProcess = keycodes

        threading.Thread.__init__(self)
        self.isAlive = True
        self.start()


    def run(self):
        self._enterKeycodes()


    def _getCodeArgs(self, code):
        codeArgs = DROID_2.text[allDeviceConstants.CONVERT][code]
        codeArgs_ = []
        for codeArg in codeArgs:
            if codeArg.startswith('`'):
                # Substitute the scancode in for this keycode.
                # Is ';' a good substitute when the keycode is not in the map?
                codeArgs_.append(str(config.keycodes[self.dt.device.keycodeMap].get(codeArg[1:-1], ';')))
            else:
                codeArgs_.append(codeArg)
        return codeArgs_


    def _enterKeycodes(self, keycodes=None):
        # _enterKeycodes() assumes a keycode requiring a substitution will be
        # two chars in length.
        def _sendCommand(commandArgs, escapedToOriginalIndices, index, keycodes):
            index_ = index
            originalIndex = escapedToOriginalIndices[index_]
            # self.codesToProcess is emptied at the start of _enterKeycodes. Keep
            # whatever has been since added.
            self.keycodeEntererLock.acquire()
            self.codesToProcess = keycodes[originalIndex:] + self.codesToProcess
            self.keycodeEntererLock.release()
            o, e = sendCommand(config.adbPath + self.serialNoString + ' '.join(commandArgs), waitForOutput=True,
                               sendingText=True)
            if constants.ERROR_ADB_COMMAND_LENGTH in e:
                self.keycodeEntererLock.acquire()
                # Add back the codes we just failed to send (keycodes[:originalIndex]),
                # keep the codes we didn't send (self.codesToProcess), and add
                # whatever has since been added by ADBTransport.enterKeycodes() (which
                # is also added to self.codesToProcess).
                dprint('ERROR_ADB_COMMAND_LENGTH')
                self.codesToProcess = keycodes[:originalIndex] + self.codesToProcess
                self.keycodeEntererLock.release()
            if constants.PROCESS_DID_NOT_TERMINATE in e:
                dprint('PROCESS TO SEND TEXT DID NOT TERMINATE, MEANING THAT AT LEAST SOME, IF NOT ALL, TEXT WAS SENT.')
            if (constants.ERROR_ADB_COMMAND_LENGTH in e) or (constants.PROCESS_DID_NOT_TERMINATE in e):
                # We don't re-send the command when it did not terminate within the
                # initial time allowed because that usually (if not always) means
                # that at least some, if not all, text was sent. There is a second
                # time span allowed for the command to complete.
                self.dt.maxADBCommandLength = self.dt.maxADBCommandLength * constants.ADB_COMMAND_REDUCTION_FACTOR

            #proc = subprocess.Popen(commandArgs)
            #os.waitpid(proc.pid, 0)

        if keycodes is None:
            # Remember that this method calls itself, so, even though the below
            # assignment is at the start of the method, it could be run long
            # after the thread started, making it more likely to run when the
            # parent wants to add to codesToProcess.
            self.keycodeEntererLock.acquire()
            keycodes_ = self.codesToProcess
            self.codesToProcess = []
            self.keycodeEntererLock.release()
        else:
            keycodes_ = keycodes

        # escapedCodes is self.codesToProcess with escape characters added
        escapedCodes = []
        # convertIndices: locations in the escaped keycode string of characters
        # in <device file>.text.CONVERT
        convertIndices = {}
        escapedToOriginalIndices = {}
        # escapedCodeLocations exists to prevent splitting text in the middle of an
        # escaped code, e.g. between '\' and '(' in '\('
        escapedCodeLocations = []
        escapedIndex = 0
        for index, code in enumerate(keycodes_):
            escapedToOriginalIndices[escapedIndex] = index
            if DROID_2.text[allDeviceConstants.ESCAPE].has_key(code):
                escapedCodeLocations += [escapedIndex]
                escapedCode = DROID_2.text[allDeviceConstants.ESCAPE][code]
            else:
                escapedCode = [code]
            if code in DROID_2.text[allDeviceConstants.CONVERT]:
                convertIndices[escapedIndex] = code
            elif code < 0:
                convertIndices[escapedIndex] = -code
            escapedIndex += len(escapedCode)
            escapedCodes += escapedCode
        
        commandArgs = ["shell"]
        # XXX optimize by replacing with len(adb) + len(shell)
        commandArgsLength = len(''.join(commandArgs))
        skipNext = False
        finished = escapedCodes == []
        for index, code in enumerate(escapedCodes):
            if skipNext:
                # Two-character escaped-code length assumption here.
                skipNext = False
                continue

            if index in escapedCodeLocations:
                # We are entering code that has to be escaped, such as a parenthesis or semi-colon.
                if commandArgs == ["shell"] or commandArgs[-1] == ';':
                    # We don't need to close off the last command.
                    # We don't want to split an escaped code sequence.
                    # Two-character escaped code length assumption here.
                    codeArgs = ["input", "text", escapedCodes[index] + escapedCodes[index + 1]]
                    codeArgsLength = len('input') + len('text') + 2
                else:
                    # We can just add the escape char and the escaped char on
                    # to the existing string.
                    # Two-character escaped code length assumption here.
                    codeArgs = escapedCodes[index] + escapedCodes[index + 1]
                    codeArgsLength = 2
                    
                if commandArgsLength + codeArgsLength > self.dt.maxADBCommandLength:
                    # We don't add 1 to the left hand side of the above comparison b/c it's not req'd at the
                    # very end.
                    # We can't send this code b/c the resulting args would be too long.
                    # Send what we already have and put the non-processed codes back on
                    # the front of the queue.
                    _sendCommand(commandArgs, escapedToOriginalIndices, index, keycodes_)
                    self._enterKeycodes()
                    finished = True
                    break
                elif commandArgs == ["shell"] or commandArgs[-1] == ';':
                    commandArgs += codeArgs
                    commandArgsLength += codeArgsLength
                    skipNext = True
                else:
                    commandArgs[-1] = commandArgs[-1] + codeArgs
                    commandArgsLength += codeArgsLength
                    skipNext = True
     
            elif code < 0 or type(code) == str or type(code)==types.UnicodeType:
                if type(code) in (str, types.UnicodeType):
                    # We are entering a keycode that has been saved as a string, rather than
                    # as the int scancode it maps to.
                    code = config.keycodes[self.keycodeMap][code]
                else:
                    code = -code
                # This is a keyevent.
                if commandArgs != ["shell"] and commandArgs[-1] != ';':
                    # the previous command was text and wasn't finished
                    commandArgs += [';']
                    commandArgsLength += 1
                    
                if type(code) in (types.IntType, str):
                    codeArgs = ["input", "keyevent", str(code), ";"]
                else:
                    # unicode
                    codeArgs = ["input", "keyevent", code, ";"]
                codeArgsLength = len(''.join(codeArgs))
                if commandArgsLength + codeArgsLength > self.dt.maxADBCommandLength:
                    # We can't send this code b/c the resulting args would be too long.
                    # Send what we already have and put the non-processed codes back on
                    # the front of the queue.
                    _sendCommand(commandArgs, escapedToOriginalIndices, index, keycodes_)
                    self._enterKeycodes()
                    finished = True
                    break
                else:
                    commandArgs += codeArgs
                    commandArgsLength += codeArgsLength
                
            elif index in convertIndices:
                # We are entering a code that has to be substituted in from the device file.
                if commandArgs != ["shell"] and commandArgs[-1] != ';':
                    # the previous command was text and wasn't finished
                    commandArgs += [';']
                    commandArgsLength += 1

                codeArgs = self._getCodeArgs(code)
                codeArgsLength = len(''.join(codeArgs))
                if commandArgsLength + codeArgsLength > self.dt.maxADBCommandLength:
                    # We can't send this code b/c the resulting args would be too long.
                    # Send what we already have and put the non-processed codes back on
                    # the front of the queue.
                    _sendCommand(commandArgs, escapedToOriginalIndices, index, keycodes_)
                    self._enterKeycodes()
                    finished = True
                    break
                else:
                    commandArgs += codeArgs
                    commandArgsLength += codeArgsLength

            else:
                # We are entering text.
                if commandArgs == ["shell"] or commandArgs[-1] == ';':
                    codeArgs = ["input", "text", unichr(code)] #.encode('utf-8')]
                    codeArgsLength = len(''.join(codeArgs))
                    if commandArgsLength + codeArgsLength > self.dt.maxADBCommandLength:
                        # We don't add 1 to the left hand side of the above comparison b/c it's not req'd at the
                        # very end.
                        # We can't send this code b/c the resulting args would be too long.
                        # Send what we already have and put the non-processed codes back on
                        # the front of the queue.
                        _sendCommand(commandArgs, escapedToOriginalIndices, index, keycodes_)                        
                        self._enterKeycodes()
                        finished = True
                        break
                    else:
                        commandArgs += codeArgs
                        commandArgsLength += codeArgsLength
                else:
                    if commandArgsLength + 1 > self.dt.maxADBCommandLength:
                        # We can't send this code b/c the resulting args would be too long.
                        # Send what we already have and put the non-processed codes back on
                        # the front of the queue.
                        _sendCommand(commandArgs, escapedToOriginalIndices, index, keycodes_)
                        self._enterKeycodes()
                        finished = True
                        break
                    else:
                        commandArgs[-1] = commandArgs[-1] + unichr(code)
                        commandArgsLength += 1

        self.keycodeEntererLock.acquire()
        if not finished or self.codesToProcess != []:
            # The lock acquisition above is for the benefit of the 'else' block
            # below.
            self.keycodeEntererLock.release()
            # We have not sent anything.
            # We don't need to add a finishing ';' to a final 'input text' command.
            #dprint('NOT FINISHED, sending:', ' '.join(commandArgs))
            o, e = sendCommand(config.adbPath + self.serialNoString + ' '.join(commandArgs), waitForOutput=True,
                               sendingText=True)
            # PROCESS_DID_NOT_TERMINATE errors are not recovered from, b/c it's
            # likely that some of the string was successfully sent to the 
            # device, and it would be worse to repeat some of what we've already
            # sent.
            if constants.ERROR_ADB_COMMAND_LENGTH in e:
                self.keycodeEntererLock.acquire()
                # keycodes_ is the local variable, self.codesToProcess is what outsiders
                # use to add keycodes to enter.
                self.codesToProcess = keycodes_ + self.codesToProcess
                self.keycodeEntererLock.release()
            if constants.PROCESS_DID_NOT_TERMINATE in e:
                dprint('PROCESS TO SEND TEXT DID NOT TERMINATE, MEANING THAT AT LEAST SOME, IF NOT ALL, TEXT WAS SENT.')
            if (constants.ERROR_ADB_COMMAND_LENGTH in e) or (constants.PROCESS_DID_NOT_TERMINATE in e):
                dprint('REDUCING COMMAND LENGTH')
                self.dt.maxADBCommandLength = self.dt.maxADBCommandLength * constants.ADB_COMMAND_REDUCTION_FACTOR

            # _enterKeycodes() is run again when ERROR_ADB_COMMAND_LENGTH is found
            # AND even when it isn't b/c codesToProcess might've been added to while
            # sendCommand() was run above.

            # *** NOTE THE RECURSIVE CALL. WE AREN'T RELYING ON SOMETHING EXTERNAL ***
            # *** TO CALL US AGAIN. **************************************************
            self._enterKeycodes()
            # *******************************

        else:
            # For this 'else' block, the lock is acquired above to prevent
            # a parent thread from adding to codesToProcess between the 'if'
            # evaluation just above and here, where codesToProcess is 
            # determined to be empty. Those codes would fall through the 
            # cracks. 
            # I'm hoping that a change to self.isAlive is immediately visible
            # to the parent thread. If not, there is race condition b/c this
            # thread may return and the parent will think it isAlive and will
            # process new codesToProcess.
            self.isAlive = False
            self.keycodeEntererLock.release()
            return

            #proc = subprocess.Popen(commandArgs)
            #os.waitpid(proc.pid, 0)

            #proc = subprocess.Popen(commandArgs)
            #output, error = proc.communicate()
            
            #os.waitpid(proc.pid, 0)
