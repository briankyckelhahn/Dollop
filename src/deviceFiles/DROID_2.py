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


# The GUI gets the code point for characters as they are
# input from the input event that is passed to the handler for
# keyboard events. wx overwrites some existing code 
# points with its control characters. For example, wx.WXK_LEFT
# has the value 314 (x13a), which is some character that looks 
# like a capital I with an accent. This character is not likely
# to be used, so it is not worth worrying about now. Keycodes
# are stored to the user's DB as the code received by
# onCharEvent(). This means that BACKSPACE, if it is typed by
# the user on his physical keyboard, is stored as the
# ASCII code for BACKSPACE, rather than the Android keyevent
# code for BACKSPACE. However, if the user uses the simulated
# device keyboard in the GUI to enter the code, it is stored
# as the negative of the keyevent.


import sys
import wx

import adbTransport
from allDeviceConstants import *


text = {
    # Backslash is first so that the substituted backslashes in front of the
    # other characters aren't themselves escaped with backslashes.
    #ESCAPE:{("\\", "\\\\"),
    #                  ("(","\("), (")", "\)"), ("`", "\`"), ("!", "\!"), ("&", "\&"),
    #                  (";", "\;"), ("|", "\|"), ("<", "\<"), (">", "\>"),
    #                  ('"', "\""), ("'", "\'")],
    ESCAPE:{ord("\\"):"\\\\",
            ord("("):"\(", ord(")"):"\)", ord("`"):"\`", ord("!"):"\!", ord("&"):"\&",
            ord(";"):"\;", ord("|"):"\|", ord("<"):"\<", ord(">"):"\>",
            ord('"'):'\\"', ord("'"):"\\'"},
    # CONVERT includes both printable and control (forward, backward) keys,
    # so the dictionary keys below are codes so that the routine that uses
    # this dictionary is simple and doesn't have to deal with two types.
    CONVERT:{ord('?'):["input", "text", "\\\\?", ";",
                       "input", "keyevent", '`DPAD_LEFT`', ";",
                       "input", "keyevent", '`BACKSPACE`', ";",
                       "input", "keyevent", '`DPAD_RIGHT`', ";"],
             ord(' '):["input", "keyevent", '`SPACE`', ";"],
             ord('*'):["input", "keyevent", '`STAR`', ";"],
             ord('#'):["input", "keyevent", '`POUND`', ";"],             
             wx.WXK_BACK:["input", "keyevent", '`BACKSPACE`', ";"],
             wx.WXK_DOWN:["input", "keyevent", '`DPAD_DOWN`', ";"],
             wx.WXK_LEFT:["input", "keyevent", '`DPAD_LEFT`', ";"],
             wx.WXK_NUMPAD_ENTER:["input", "keyevent", '`RETURN`', ";"],
             wx.WXK_RETURN:["input", "keyevent", '`RETURN`', ";"],             
             wx.WXK_RIGHT:["input", "keyevent", '`DPAD_RIGHT`', ";"],
             wx.WXK_UP:["input", "keyevent", '`DPAD_UP`', ";"],
             }
    
    }


