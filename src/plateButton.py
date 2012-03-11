# -*- coding: utf-8 -*-

###############################################################################
# Name: PlateButtonDemo.py                                                    #
# Purpose: PlateButton Test and Demo File                                     #
# Author: Cody Precord <cprecord@editra.org>                                  #
# Portions copyright: (c) 2007 Cody Precord <staff@editra.org>                #
# Licence: wxWindows Licence                                                  #
###############################################################################


# Portions copyright (C) 2012 Brian Kyckelhahn
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


#-----------------------------------------------------------------------------#
import binascii
import copy
import Image
import math
import os
import re
import StringIO
import unicodedata
import webbrowser
import wx
from wx.lib.embeddedimage import PyEmbeddedImage
import wx.lib.scrolledpanel as scrolled
#import wx.lib.platebtn as platebtn

import platebtn
import config
import constants
from globals_ import *


def getPrintableKeycodeText(keycodes):
    # for each keycode:
    #     if the keycode is negative or not printable, put two square brackets around the name corresponding to the keycode
    #     elif the keycodes are two or more square brackets, double the number displayed
    #
    text = ""
    for keycode in keycodes:
        if type(keycode) == str:
            # keycode is a true keycode, not a scancode as usual.
            text += "`" + keycode + "`"
        elif 0 > keycode:
            text += "`" + config.KEYEVENT_NAMES[str(-keycode)].upper().replace(' ', '_') + "`"
        elif unicodedata.category(unicode(binascii.a2b_hex(hex(keycode)[2:].zfill(2)))) == 'Cc':
            # (invisible, non-printing) control character. See chosen answer at 
            # http://stackoverflow.com/questions/92438/stripping-non-printable-characters-from-a-string-in-python
            text += "`" + str(keycode) + "`"
        elif unichr(keycode) == '`':
            text += '``'
        else:
            text += unichr(keycode)
    return text


checkForPass = PyEmbeddedImage(
    "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeCAYAAAA7MK6iAAAAAXNSR0IArs4c6QAAAAlwSFlz"
    "AAALEwAACxMBAJqcGAAAAAd0SU1FB9sDChYaIXjf6b8AAAGMSURBVEjHvZe7SgNBFIY/Q0SL"
    "uEYk2GtjkyIIQhARxcK3sBUEX8VOSxstfAMhtc+ghUIwESJoJUKEcI7F7G72MotF5mSXzewl"
    "zLf/ufyZgPWm6XiK8oTQYC5Qd/QQNLO3baHCCsKwAHVXZpvQQvhMQQnUXZ1bQbdQfj3QCcKx"
    "VYi7MU5yGpUPhJZV5R7k8jjdX3PfCwoVuhXQPkINsclpEZqEuW+ptFOh9BuhbtM4wlpcPJLr"
    "UuEHpWkDVdYRxqWWUcYIi1Yts+oJbtI4bTtfUl48OVWEPUvDfyjh3OehpfGflCrYFdNV+LZx"
    "1QvKpje4ym2Yvqx+Psj4boJ9D6NUuUkVZkflvqTU9WoUwuDfYj3PCAsZ6FHhVyZB786qsoYy"
    "Sid303+hLKNEsSEUc3s9e4iFx5LBu7MRSs/TOMNQed2uMHn13BeUnbBmr6X1ke8VhhbmUEcZ"
    "/KM8srLEZrwg84HvbNxpGvYNlInHFpdsli95+H5mpSgol/P52+HGsxQrNOzV5l/iAqFjMfUf"
    "zpzAmXWpANsAAAAASUVORK5CYII=").Image

okForDoneOutlined = PyEmbeddedImage(
    "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeCAYAAAA7MK6iAAAAAXNSR0IArs4c6QAAAAZiS0dE"
    "AP8A/wD/oL2nkwAAAAlwSFlzAAALEwAACxMBAJqcGAAAAAd0SU1FB9sDChEwO++ZymgAAAAZ"
    "dEVYdENvbW1lbnQAQ3JlYXRlZCB3aXRoIEdJTVBXgQ4XAAAEBklEQVRIx+2VXUzVZRzHP9+H"
    "cw4IiMJJYqJRYuV0NqXSfCmbdpProrXMNM2XWrNivay1uVpaqzS31NXI5tStsmm6XHdqgcum"
    "DrM1QYywhIsUExSQFwX+55zn1wUvA9RaF3rF5+bZnt+z/d6+z+8HgwwyyM3CzPqdNwTv/f96"
    "X1p3/WAO1tq/JqKei29qjPl3wJE6u/10MytONDHvYodGhJ2RlayTEzLZWhDlu3uiaio563lk"
    "lAPg2xqb/tdlZsS9kZtK5cKx7JOcB9hYYU/EPPne4P4RdM4eaZsl1wkQAmjqNDKTRe55W/TJ"
    "SW369SJDOxLQE5uwadEUTbs3ymttgS1Jj+j4xQ7PLSmOndXM/vFv3mpP4Kdna/fCsVYMBIsP"
    "2itrynm3NSAyJoM2gxfm5LpOM0NSl+PMZGHmJ8793rZXXhIJD4+Oom5BPltbY2TuqNZLpfXw"
    "03mb+Pxh7TazyZLaAJwjHnK0hzw+yRGTXLDymBVu+4NVV+IWuy2d4L0CLZ43RsVfnupy2psx"
    "wJYqbSpvNEKCabfStO0hGy25GMDpZtuz4ggHqlvEiUbyiip5Eviif/eEA//hcXt9fQVrAk/r"
    "6DTZnjksm5Cl4p3VngX5vZ3FdTc8WlzLuLCTSTArh9WSi8USRizhyRtK6ag0DoORMMInGykw"
    "8xqom8ZO5hRV8k7gaZ2URWLDVJZPyNK+XdXGgnzX73F3xpZV0yo5UGoI0sOcAAgnqVuJPpGa"
    "RG2SIOaNSzENB4WAWF+9VjVruJnFc9PUvm4KL87I0d6tVZ75+bpK3aGeMkkGCDMIO8IDyigJ"
    "Z71Ftb4fove2h+aA5J8v2EwzXyK5oEdQfenJv/6uDHlvWFscGjq4D6Chw2gJjIZO3OU4ed6M"
    "sIPhETWAxQZUWuOGcSk9TKg1hj7/XYXrK/RBd9hXzQjXbWieO5rywJsE/FBrq818djRFZERE"
    "YweP17QwBUSSLJiazS+SG1g9ZSVzoHC83k92ZJy7QvtH5SxfU+Y3dqnfXTNjnhnL0gdzZAjK"
    "G5Uy74DObP/Tdm2pspKXS9lR04pJxgPZOrX0TnZfc/KBe3uyNq4Yx5tpIZICj19foUVry2yt"
    "mUX6Tq4QQEfckFRb1mCPbahg29F6yzlcR+TQeT1lQEgwMg0VRDm0eSbLJMXb48aQkEh4XNxb"
    "UtzkEh5n5iOSip49aG7/WVvVEkibq3i1OUDASkmYWZfjlJAoa/BMimrv/jN+4tP5WvxbE881"
    "dZIXckZmRKVjMvhsclQlki4fu9DlFGDKCOpTQ6oKvNndw6gFeYCvHtanbxy1xJk2W2Iofu4K"
    "syqbfOH4TFc0UGgk/mNJDPm6v/3j8usviXXXsZXW2Y3ddIMMMshN4x9LQ+EVMSbIEAAAAABJ"
    "RU5ErkJggg==").Image

xForFail = PyEmbeddedImage(
    "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAeCAYAAAA7MK6iAAAAAXNSR0IArs4c6QAAAAlwSFlz"
    "AAALEwAACxMBAJqcGAAAAAd0SU1FB9sDChA2DXe7kkAAAAAZdEVYdENvbW1lbnQAQ3JlYXRl"
    "ZCB3aXRoIEdJTVBXgQ4XAAACH0lEQVRIx+2WPWsUYRSFn91lYwISInHVwlIRLbbzoxER1H8g"
    "ClaJEgvFzkZWWxsrEcRCMJ1YigiCaCEBCyubQARBULQIxKRIVNZzLPIO+zrOZD7WLrmwLAMz"
    "93nPvefeGdiKTR0KvzrhjFwbgsL/hGB82IMbRgRHlXGQLPhOwTPDY8EeKqr2IM92w11DXzBT"
    "RvV1gQU2LAgOJwldEmqYNMx5kKcvmCh6uCW4EcFluJLXuwylXcFKAhV8ExyoUrILgi9eh9tw"
    "T7AjDVcENpwzrEbPzBn2lmqX/oYfE7xOEgleCo5kQFuGm4YfGtz7SDBZe4wMHcNtDUr32XA1"
    "unfM8DRSacM1wyhl3FzQt5ZgSrAWFP0Mju0a5g0Kh1o1nDE0akNz3HrS8CkYLjGfA/ij4fh/"
    "AeYsl92GxVRpFw2HqkCbZaHN9aTtBvQI/YuiDZw3bGsMsWbzyrxL8MrwO6j8Jbhv+O7BvL9w"
    "xsjVBWLYZ3gfLYVlwaVQjY5gPhqjrwplT6rlqv0M4NNxTwUfBKfSqgwP4jk2XNa/LSlloqag"
    "J1iLlD437E+NWqxs2rAUHXLW0CksfVTeUcGsoB8592Gy6LXBu1dwMMx2Al8QdMvAxwRvop7J"
    "cKfoJZFS3zI8ieA2TBWZ6mKkcskwXeVrJOWPW4aVAH7rvN0d9a0neGc4UWc0UqY7G4w3XuZj"
    "YCT5+hh20wV4uxDqguu6cLEVmy3+ANM5fuLQh5uMAAAAAElFTkSuQmCC").Image


def imageStringFromWxImage( wxImage, wantAlpha=True ) :   # 2 ==> 3  Default is to keep any alpha channel
    # Nearly verbatim from http://wiki.wxpython.org/PngWithAlphaChannel.
    image_size = wxImage.GetSize()      # All images here have the same size.
    
    # Create an RGB pilImage and stuff it with RGB data from the wxImage.
    pilImage = Image.new( 'RGB', image_size )
    pilImage.fromstring( wxImage.GetData() )

    if wantAlpha and wxImage.HasAlpha() :   # Only wx.Bitmaps use .ConvertAlphaToMask( [0..255] )
        # Create an L pilImage and stuff it with the alpha data extracted from the wxImage.
        l_pilImage = Image.new( 'L', image_size )
        l_pilImage.fromstring( wxImage.GetAlphaData() )
        
        # Create an RGBA pil image from the 4 bands.
        r_pilImage, g_pilImage, b_pilImage = pilImage.split()
        pilImage = Image.merge( 'RGBA', (r_pilImage, g_pilImage, b_pilImage, l_pilImage) )

    return pilImage.tostring()
                                                                            


class TestPanel(scrolled.ScrolledPanel):
    def __init__(self, parent, frame, log, mgr, testName, onButtonHandler, buttonClass=platebtn.PlateButton,
                 selectedIndex=None, title="", buttonComponentss=None):
        self.log = log
        scrolled.ScrolledPanel.__init__(self, parent, size=(constants.PLAY_AND_RECORD_PANEL_WIDTH, 300))
        self.frame = frame
        self.mgr = mgr
        self.testName = testName
        self.buttonClass = buttonClass
        # The button representing the event that is currently being played.
        self.selectedButtonIndex = selectedIndex

        # Raw data from which the buttons will be constructed.
        self.buttonComponentss = buttonComponentss or []
        # The buttons themselves.
        self.buttons = []

        self.buttonIDToListIndex = {}
        
        # Layout
        self.SetupScrolling(scroll_x=False)

        # Event Handlers
        self.Bind(wx.EVT_BUTTON, onButtonHandler)
        self.Bind(wx.EVT_TOGGLEBUTTON, self.OnToggleButton)
        self.Bind(wx.EVT_MENU, self.OnMenu)

        self.checkForPass = imageStringFromWxImage(checkForPass)
        self.okForDoneOutlined = imageStringFromWxImage(okForDoneOutlined)
        self.xForFail = imageStringFromWxImage(xForFail)

        self.Bind(wx.EVT_MOTION, self.onMouseMove)

        self.PopulateButtons(title, buttonComponentss)


    def PopulateButtons(self, title, buttonComponentss):
        # Layout the panel
        p1 = wx.Panel(self)
        self.buttonComponentss = buttonComponentss

        self.LayoutPanel(p1, title)
        # if sessionName:
        #     if len(sessionName) > 20:
        #         sessionName_ = sessionName[:20] + '...'
        #     else:
        #         sessionName_ = sessionName
        #     self.LayoutPanel(p1, "Events in test {name}:".format(name=sessionName_))
        # else:
        #     self.LayoutPanel(p1, "") #"No test loaded.")

        hsizer = wx.BoxSizer(wx.HORIZONTAL)
        hsizer.Add(p1, 1, wx.EXPAND)
        self.SetSizer(hsizer)
        self.SetAutoLayout(True)


    def LayoutPanel(self, panel, label, exstyle=False):
        # Puts a set of controls in the panel
        # @param panel: panel to layout
        # @param label: panels title
        # @param exstyle: Set the PB_STYLE_NOBG or not
        vsizer = wx.BoxSizer(wx.VERTICAL)

        # Button Styles
        default = platebtn.PB_STYLE_DEFAULT
        square  = platebtn.PB_STYLE_SQUARE
        sqgrad  = platebtn.PB_STYLE_SQUARE | platebtn.PB_STYLE_GRADIENT
        gradient = platebtn.PB_STYLE_GRADIENT
        droparrow = platebtn.PB_STYLE_DROPARROW
        toggle = default | platebtn.PB_STYLE_TOGGLE

        txt_sz = wx.BoxSizer(wx.HORIZONTAL)
        txt_sz.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_LEFT)
        vsizer.Add(txt_sz, 0, wx.ALIGN_LEFT)

        for index, btn in enumerate(self.buttonComponentss):
            if exstyle:
                # With this style flag set the button can appear transparent on
                # on top of a background that is not solid in color, such as the
                # gradient panel in this demo.
                #
                # Note: This flag only has affect on wxMSW and should only be
                #       set when the background is not a solid color. On wxMac
                #       it is a no-op as this type of transparency is achieved
                #       without any help needed. On wxGtk it doesn't hurt to
                #       set but also unfortunatly doesn't help at all.
                bstyle = btn['buttonStyle'] | platebtn.PB_STYLE_NOBG
            else:
                bstyle = btn['buttonStyle']

            buttonID = wx.NewId()
            self.buttonIDToListIndex[buttonID] = index
            tbtn = self.buttonClass(panel, buttonID, btn['label'], copy.copy(btn['PyEmbeddedImage']), style=bstyle|wx.ALIGN_LEFT)
            if index == self.selectedButtonIndex:
                tbtn.SetLabelColor(wx.RED, hlight=wx.RED)
            else:
                tbtn.SetLabelColor(wx.BLACK, hlight=wx.BLACK)
            # This has failed to avoid the button getting the highlight
            # state: tbtn.SetState(platebtn.PLATE_NORMAL).
            self.buttons.append(tbtn)

            # Set a custom window size variant?
            if btn['textSize'] is not None:
                tbtn.SetWindowVariant(btn['textSize'])

            # Make a menu for the button?
            if btn['menu'] is not None:
                menu = wx.Menu()
                menu.Append(wx.NewId(), "Menu Item 1")
                menu.Append(wx.NewId(), "Menu Item 2")
                menu.Append(wx.NewId(), "Menu Item 3")
                tbtn.SetMenu(menu)

#            # Set a custom colour?
#            if btn['pressColor'] is not None:
#                tbtn.SetPressColor(btn['pressColor'])

            # Enable/Disable button state
            tbtn.Enable(btn['isEnabled'])

            vsizer.Add(tbtn, 0, wx.ALIGN_LEFT)

        panel.SetSizer(vsizer)


    def advanceSelectedButton(self, status=None, previousColor=None):
        # Returns True if it has been advanced past the end of the list,
        # meaning that all entries have been evaluated.
        previousButtonIndex = self.selectedButtonIndex
        if self.selectedButtonIndex in (None, -1):
            if len(self.buttons) > 0:
                self.selectedButtonIndex = 0
            elif len(self.buttons) == 0:
                return True
        elif self.selectedButtonIndex == len(self.buttons):
            # This is a programming error.
            dprint('XXX ERROR - selectedButton advanced too far')
            self.selectedButtonIndex = None
            return
        else:
            # If status is None, we're simply highlighting the next entry in the list w/o
            # changing the status of the one we're "done with".
            if status != None:
                originalString = self.buttonComponentss[self.selectedButtonIndex]['imageString']
                imageString = {constants.EVENT_PASSED:self.checkForPass,
                               constants.EVENT_FAILED:self.xForFail,
                               constants.EVENT_ERRORED:self.xForFail,
                               constants.EVENT_MERELY_EXECUTED:self.okForDoneOutlined,
                               constants.TEST_PASSED:self.checkForPass,
                               constants.TEST_FAILED:self.xForFail}[status]
                combinedImageString = superimposeImageWithAlpha(originalString, imageString)
                memoryPNG = StringIO.StringIO()
                image = Image.frombuffer("RGB",
                                         (30, 30),
                                         combinedImageString,
                                         'raw',
                                         "RGB",
                                         0,
                                         1)
                image.save(memoryPNG, format='PNG')
                image = memoryPNG.getvalue()
                memoryPNG.close()
                image = PyEmbeddedImage(image, isBase64=False).GetBitmap()
                self.buttons[self.selectedButtonIndex].SetBitmap(image)
                self.buttons[self.selectedButtonIndex].SetBackgroundColour(previousColor)
                self.buttonComponentss[self.selectedButtonIndex]['PyEmbeddedImage'] = image
            self.selectedButtonIndex += 1

        if len(self.buttons) > 0:
            if self.selectedButtonIndex > 0:
                # We're on the second or later entry; de-highlight the previous one.
                self.buttons[previousButtonIndex].SetLabelColor(wx.BLACK, hlight=wx.BLACK)
            if self.selectedButtonIndex < len(self.buttons):
                self.buttons[self.selectedButtonIndex].SetLabelColor(wx.RED, hlight=wx.RED)

        return self.selectedButtonIndex == len(self.buttons)


    def unselectSelectedButton(self):
        if self.selectedButtonIndex is None:
            return
        else:
            try:
                self.buttons[self.selectedButtonIndex].SetLabelColor(wx.BLACK, hlight=wx.BLACK)
            except Exception, e:
                dprint('XXX ERROR - e:', str(e))
            self.selectedButtonIndex = None


    def reset(self):
        self.selectedButtonIndex = None
        self.buttons = []
        

    def OnDropArrowPressed(self, evt):
        # self.log.write("DROPARROW PRESSED")
        pass


    def OnButton(self, evt):
        index = self.buttonIDToListIndex[evt.GetId()]
        components = self.buttonComponentss[index]

        class Temp(object):
            def __init__(self, components):
                self.inputType = components['inputType']
                self.characters = components['characters']
                self.keycodes = components['keycodes']
                self.textToVerify = components['textToVerify']
                self.wait = components['wait']
                self.image = components['PyEmbeddedImage'] if components['inputType'] in (constants.TAP, constants.DRAG, constants.LONG_PRESS) else None
                self.dragStartRegion = components['dragStartRegion']
                #self.dragEndRegion = components['dragEndRegion'] # missing 7/5
                self.dragRightUnits = components['dragRightUnits']
                self.dragDownUnits = components['dragDownUnits']
                
        dlg = Temp(components)
        inputType = dlg.inputType
        characters = dlg.characters
        keycodes = dlg.keycodes
        textToVerify = dlg.textToVerify
        wait = dlg.wait
        image = dlg.image
        dragStartRegion = dlg.dragStartRegion
        #dragEndRegion = dlg.dragEndRegion
        dragRightUnits = dlg.dragRightUnits
        dragDownUnits = dlg.dragDownUnits
        dbIndex = components['index']
        dprint('OnButton, dbIndex:', dbIndex)
        inputTypeInDB = components['inputType']
        charactersInDB = components['characters']
        keycodesInDB = components['keycodes']
        textToVerifyInDB = components['textToVerify']
        waitInDB = components['wait']
        try:
            imageInDB = components['PyEmbeddedImage'] if components['inputType'] in (constants.TAP, constants.DRAG, constants.LONG_PRESS) else None
        except Exception, e:
            dprint('err')
        dragStartRegionInDB = components['dragStartRegion']
        dragEndRegionInDB = components['dragEndRegion']
        dragRightUnitsInDB = components['dragRightUnits']
        dragDownUnitsInDB = components['dragDownUnits']
        
        while True:
            #
            dlg = InputEventDialog(self, -1, index, dbIndex, len(self.buttons), self.frame, self.mgr,
                                   self.testName,
                                   inputType=inputType,
                                   characters=characters,
                                   keycodes=keycodes,
                                   textToVerify=textToVerify,
                                   wait=wait,
                                   image=image,
                                   dragStartRegion=dragStartRegion,
                                   #dragEndRegion=dragEndRegion,
                                   dragRightUnits=dragRightUnits,
                                   dragDownUnits=dragDownUnits,
                                   inputTypeInDB=inputTypeInDB,
                                   charactersInDB=charactersInDB,
                                   keycodesInDB=keycodesInDB,
                                   textToVerifyInDB=textToVerifyInDB,
                                   waitInDB=waitInDB,
                                   imageInDB=imageInDB,
                                   dragStartRegionInDB=dragStartRegionInDB,
                                   dragEndRegionInDB=dragEndRegionInDB,
                                   dragRightUnitsInDB=dragRightUnitsInDB,
                                   dragDownUnitsInDB=dragDownUnitsInDB)
            dlg.ShowModal()
            
            if not dlg.doLayoutAgain:
                break
            inputType=dlg.inputType
            characters=dlg.characters
            keycodes=dlg.keycodes
            textToVerify=dlg.textToVerify
            wait=dlg.wait
            image=dlg.image
            dragStartRegion=dlg.dragStartRegion
            #dragEndRegion=dlg.dragEndRegion
            dragRightUnits=dlg.dragRightUnits
            dragDownUnits=dlg.dragDownUnits

        #self.log.write("BUTTON CLICKED: Id: %d, Label: %s" % \
        #               (evt.GetId(), evt.GetEventObject().LabelText))

        if dlg.modified:
            return True
        return False
                                                                                                

    def OnToggleButton(self, evt):
        #self.log.write("TOGGLE BUTTON CLICKED: Id: %d, Label: %s, Pressed: %s" % \
        #               (evt.GetId(), evt.GetEventObject().LabelText,
        #                evt.GetEventObject().IsPressed()))
        pass


    def OnChildFocus(self, evt):
        # Override ScrolledPanel.OnChildFocus to prevent erratic
        # scrolling on wxMac.
        if wx.Platform != '__WXMAC__':
            evt.Skip()

        child = evt.GetWindow()
        self.ScrollChildIntoView(child)


    def OnMenu(self, evt):
        # Events from button menus
        # self.log.write("MENU SELECTED: %d" % evt.GetId())
        e_obj = evt.GetEventObject()
        mitem = e_obj.FindItemById(evt.GetId())
        if mitem != wx.NOT_FOUND:
            label = mitem.GetLabel()
            if label.startswith('http://'):
                webbrowser.open(label, True)


    def onMouseMove(self, event):
        self.SetFocus()


class InputEventDialog(wx.Dialog):
    # Parameters also appearing in the DB should have the type expected in
    # gui.py, not that expected in the DB. For example, dragStartRegion
    # should be a tuple here, not a string; the DB type should be internal
    # to the DB code.
    def __init__(self, parent, id, index, dbIndex, numEvents, frame, mgr, testName,
                 inputType=None,
                 characters=None,
                 keycodes=None,
                 textToVerify=None,
                 wait=None,
                 image=None,
                 dragStartRegion=None,
                 dragEndRegion=None,                 
                 dragRightUnits=None,
                 dragDownUnits=None,
                 inputTypeInDB=None,
                 charactersInDB=None,
                 keycodesInDB=None,
                 textToVerifyInDB=None,
                 waitInDB=None,
                 imageInDB=None,
                 dragStartRegionInDB=None,
                 dragEndRegionInDB=None,
                 dragRightUnitsInDB=None,
                 dragDownUnitsInDB=None):
        wx.Dialog.__init__(self, parent, -1)
        self.frame = frame
        self.mgr = mgr
        self.index = index
        self.dbIndex = dbIndex
        self.numEvents = numEvents
        self.testName = testName
        self.inputType = inputType
        self.characters = characters
        self.keycodes = keycodes or []
        self.textToVerify = textToVerify
        self.wait = wait
        self.image = image
        self.dragStartRegion = dragStartRegion
#        self.dragEndRegion = dragEndRegion        
        self.dragRightUnits = dragRightUnits
        self.dragDownUnits = dragDownUnits
           
        self.inputTypeInDB = inputTypeInDB
        self.charactersInDB = charactersInDB
        self.keycodesInDB = keycodesInDB or []
        self.textToVerifyInDB = textToVerifyInDB
        self.waitInDB = waitInDB
        self.imageInDB = imageInDB
        self.dragStartRegionInDB = dragStartRegionInDB
        self.dragEndRegionInDB = dragEndRegionInDB
        self.dragRightUnitsInDB = dragRightUnitsInDB
        self.dragDownUnitsInDB = dragDownUnitsInDB
           
        self.Bind(wx.EVT_CLOSE, self.onClose)
        self.Bind(wx.EVT_CHAR, self.onCharEvent)

        self.modified = False
        self.doLayoutAgain = False
        self.doLayout()

        
    def doLayout(self):
        self.SetTitle("Editing event " + str(self.index + 1) + " of " + str(self.numEvents) + " (a " + constants.INPUT_EVENT_TYPE_LABELS[self.inputType].lower() + " event)")
        self.SetAutoLayout(True)

        sideBorder = 15
        # Used for processing char events.
        self.addBacktick = False

        inputTypeText = wx.StaticText(self, label="Change to input type:")
        allChoices = [("Drag", constants.DRAG),
                      ("Long Press", constants.LONG_PRESS),
                      ("Tap", constants.TAP),
                      ("Key Input", constants.KEY_EVENT),
                      ("Verify Text", constants.TEXT_TO_VERIFY),
                      ("Wait", constants.WAIT)]
        inputTypeChoiceText = [x[0] for x in allChoices if x[1] == self.inputType][0]
        # Don't allow the user to change from an event w/o an image to one with an image,
        # b/c I'm not going to go through the hassle of allowing them to upload images.
        # In the future, I could make it possible to simply insert a single, newly-
        # recorded event.
        # The matching algorithm works by matching pixel to pixel, not shape to shape, I
        # think. If the user uploads an image file that has been scaled (as with taking
        # a screenshot of the tool when it was displaying an image he wanted), it won't
        # match one of the same picture but of different scale.
        if self.inputType in (constants.KEY_EVENT, constants.TEXT_TO_VERIFY, constants.WAIT):
            self.inputTypeChoices = [("Key Input", constants.KEY_EVENT),
                                     ("Verify Text", constants.TEXT_TO_VERIFY),
                                     ("Wait", constants.WAIT)]
        else:
            self.inputTypeChoices = allChoices
        self.inputTypeChoice = wx.ComboBox(self, -1, inputTypeChoiceText,
                                           (90, 50), (160, -1),
                                           [x[0] for x in self.inputTypeChoices],
                                           wx.CB_DROPDOWN | wx.CB_READONLY)
        self.inputTypeChoice.Bind(wx.EVT_COMBOBOX, self.onInputType)
            
        if self.inputType in (constants.DRAG, constants.LONG_PRESS, constants.TAP):
            self.bitmapSizer = wx.BoxSizer(wx.HORIZONTAL)
            self.bitmapSizer.Add(wx.StaticText(self, label="Image to find:"), 0, flag=wx.ALIGN_BOTTOM)
            staticBitmap = wx.StaticBitmap(self, -1, self.image, size=(self.image.GetWidth(), self.image.GetHeight()))
            self.bitmapSizer.Add(staticBitmap, 0, border=5, flag=wx.LEFT)
            # A tap, drag, or long press can be accompanied by characters.
            charactersSizer = wx.BoxSizer(wx.HORIZONTAL)
            charactersSizer.Add(wx.StaticText(self, label="String to match:"), 0, flag=wx.ALIGN_BOTTOM)
            self.charactersCtrl = wx.TextCtrl(self, -1, str(self.characters) if self.characters else '', size=(150, constants.TEXT_BOX_DEFAULT_HEIGHT))
            charactersSizer.Add(self.charactersCtrl, border=5, flag=wx.LEFT)

            if self.inputType == constants.DRAG:
                self.dragSizer = wx.BoxSizer(wx.VERTICAL)
                dragText1 = wx.StaticText(self, label="""
For the purpose of dragging, the screen is divided
into three rows and three columns, making nine
equally-sized sections. If the image (and text, if
any) cannot be found, the drag will start at the:""".lstrip())
                self.dragSizer.Add(dragText1, border=5, flag=wx.TOP)

                self.rowChoices = ['upper', 'middle', 'lower']
                self.columnChoices = ['left', 'center', 'right']
                rowIndex = 0 if self.dragStartRegion is None else self.dragStartRegion[1] - 1
                columnIndex = 0 if self.dragStartRegion is None else self.dragStartRegion[0] - 1
                self.startRow = wx.ComboBox(self, -1, self.rowChoices[rowIndex], (90, 50), (80, -1), self.rowChoices, wx.CB_DROPDOWN | wx.CB_READONLY)
                self.startColumn = wx.ComboBox(self, -1, self.columnChoices[columnIndex], (90, 50), (80, -1), self.columnChoices, wx.CB_DROPDOWN | wx.CB_READONLY)
                startRegionSizer = wx.BoxSizer(wx.HORIZONTAL)
                startRegionSizer.Add(self.startRow, 0)
                startRegionSizer.Add(self.startColumn, 0, border=5, flag=wx.LEFT)
                self.dragSizer.Add(startRegionSizer, border=5, flag=wx.TOP)
                
                dragText2 = wx.StaticText(self, label="section of the screen.")
                self.dragSizer.Add(dragText2, border=5, flag=wx.TOP)

                dragText2andahalf = wx.StaticText(self, label="The drag will move to the:")
                self.dragSizer.Add(dragText2andahalf, border=5, flag=wx.TOP)
                
                rightOrLeft = "right" if self.dragRightUnits is None or self.dragRightUnits >= 0 else "left"
                rightOrLeftUnits = 0 if self.dragRightUnits is None else int(math.sqrt((self.dragRightUnits) ** 2))
                self.rightOrLeftCtrl = wx.ComboBox(self, -1, rightOrLeft, (90, 50), (80, -1), ["left", "right"], wx.CB_DROPDOWN | wx.CB_READONLY)
                dragText3 = wx.StaticText(self, label="by at most")
                self.rightOrLeftUnitsCtrl = wx.ComboBox(self, -1, str(rightOrLeftUnits), (90, 50), (80, -1), ['0', '1', '2'], wx.CB_DROPDOWN | wx.CB_READONLY)
                dragText4 = wx.StaticText(self, label="sections,")
                rightOrLeftSizer = wx.BoxSizer(wx.HORIZONTAL)
                rightOrLeftSizer.Add(self.rightOrLeftCtrl)
                rightOrLeftSizer.Add(dragText3, border=5, flag=wx.LEFT | wx.ALIGN_BOTTOM)
                rightOrLeftSizer.Add(self.rightOrLeftUnitsCtrl, border=5, flag=wx.LEFT)
                rightOrLeftSizer.Add(dragText4, border=5, flag=wx.LEFT | wx.ALIGN_BOTTOM)
                self.dragSizer.Add(rightOrLeftSizer, border=5, flag=wx.TOP)

                dragText5 = wx.StaticText(self, label="and:")
                self.dragSizer.Add(dragText5, border=5, flag=wx.TOP)
                
                downOrUp = "down" if self.dragDownUnits is None or self.dragDownUnits >= 0 else "up"
                downOrUpUnits = 0 if self.dragDownUnits is None else int(math.sqrt((self.dragDownUnits) ** 2))
                self.downOrUpCtrl = wx.ComboBox(self, -1, downOrUp, (90, 50), (80, -1), ["up", "down"], wx.CB_DROPDOWN | wx.CB_READONLY)
                dragText6 = wx.StaticText(self, label="by at most")                
                self.downOrUpUnitsCtrl = wx.ComboBox(self, -1, str(downOrUpUnits), (90, 50), (80, -1), ['0', '1', '2'], wx.CB_DROPDOWN | wx.CB_READONLY)
                dragText7 = wx.StaticText(self, label="sections,")
                downOrUpSizer = wx.BoxSizer(wx.HORIZONTAL)
                downOrUpSizer.Add(self.downOrUpCtrl)
                downOrUpSizer.Add(dragText6, border=5, flag=wx.LEFT | wx.ALIGN_BOTTOM)
                downOrUpSizer.Add(self.downOrUpUnitsCtrl, border=5, flag=wx.LEFT)
                downOrUpSizer.Add(dragText7, border=5, flag=wx.LEFT | wx.ALIGN_BOTTOM)
                self.dragSizer.Add(downOrUpSizer, border=5, flag=wx.TOP)

                dragText8 = wx.StaticText(self, label="as permitted by the starting point.")
                self.dragSizer.Add(dragText8, border=5, flag=wx.TOP)
                
            else:
                self.dragSizer = None
        else:
            self.charactersCtrl = None
            self.dragSizer = None            
            
        if self.inputType == constants.KEY_EVENT:
            instructions = """
Write the text that you want to be sent to the device. Use the drop-down menu
to send special characters (many of which aren't on your computer keyboard). 
The device you are testing may not support all of the keys in the menu, and 
it may use different numbers for the keyevent. You can edit these numbers in
this tool's configuration.

These special characters are shown in the text field below between backticks
(`), as are non-printing characters such as backspace (ASCII code 8) and
carriage return (ASCII code 13). If you want a non-printing character to be 
part of this keycode stream, enter the ASCII code between backticks.

If you need a backtick to appear in your text, it will be escaped with
another backtick for you."""
            keycodeSizer = wx.BoxSizer(wx.VERTICAL)
            keycodeSizer.Add(wx.StaticText(self, label=instructions.lstrip()), 0, border=sideBorder, flag=wx.ALIGN_LEFT | wx.ALIGN_BOTTOM | wx.LEFT | wx.BOTTOM | wx.RIGHT)

            charSizer = wx.BoxSizer(wx.HORIZONTAL)
            charSizer.Add(wx.StaticText(self, label="Text to enter:"), 0, border=sideBorder, flag=wx.ALIGN_LEFT | wx.ALIGN_TOP | wx.LEFT)
            self.displayedKeycodeText = getPrintableKeycodeText(self.keycodes)
            self.keycodesCtrl = wx.TextCtrl(self, -1, self.displayedKeycodeText, size=(300, 50), style=wx.TE_MULTILINE)
            charSizer.Add(self.keycodesCtrl, border=5, flag=wx.LEFT)
            self.keycodesCtrl.Bind(wx.EVT_CHAR, self.onCharEvent)
            self.keycodesCtrl.Bind(wx.EVT_TEXT, self.onTextEvent)
            keycodeSizer.Add(charSizer)

            simulatedKeySizer = wx.BoxSizer(wx.HORIZONTAL)
            simulatedKeySizer.Add(wx.StaticText(self, label="Special device keys:"), 0, flag=wx.ALIGN_BOTTOM)
            self.simulatedKeys = sorted(config.KEYEVENT_NAMES.values())
            self.simulatedKeyboard = wx.ComboBox(self, 500, self.simulatedKeys[0], (90, 50), 
                                                 (160, -1), self.simulatedKeys,
                                                 wx.CB_DROPDOWN | wx.CB_READONLY)
            self.Bind(wx.EVT_COMBOBOX, self.onSimulatedKeyboard, self.simulatedKeyboard)
            simulatedKeySizer.Add(self.simulatedKeyboard, 0, border=5, flag=wx.LEFT)
            keycodeSizer.Add(simulatedKeySizer, border=sideBorder, flag=wx.LEFT | wx.BOTTOM | wx.TOP)
            
        else:
            self.keycodesCtrl = None

        if self.inputType == constants.TEXT_TO_VERIFY:
            textToVerifySizer = wx.BoxSizer(wx.HORIZONTAL)
            textToVerifySizer.Add(wx.StaticText(self, label="Text to verify:"), 0, flag=wx.ALIGN_BOTTOM)
            self.textToVerifyCtrl = wx.TextCtrl(self, -1, self.textToVerify or '', size=(300, constants.TEXT_BOX_DEFAULT_HEIGHT))
            textToVerifySizer.Add(self.textToVerifyCtrl, border=5, flag=wx.LEFT)
        else:
            self.textToVerifyCtrl = None
            
        if self.inputType == constants.WAIT:
            waitSizer = wx.BoxSizer(wx.HORIZONTAL)
            waitSizer.Add(wx.StaticText(self, label="Time to wait (seconds):"), 0, flag=wx.ALIGN_LEFT | wx.ALIGN_BOTTOM)
            self.waitCtrl = wx.TextCtrl(self, -1, str(self.wait if self.wait is not None else ''), size=(54, constants.TEXT_BOX_DEFAULT_HEIGHT))
            waitSizer.Add(self.waitCtrl, border=5, flag=wx.LEFT)
        else:
            self.waitCtrl = None

        buttons = wx.BoxSizer(wx.HORIZONTAL)                                                                                      
        b = wx.Button(self, label="Delete")
        b.Bind(wx.EVT_BUTTON, self.onDelete)
        buttons.Add(b, flag=wx.ALIGN_RIGHT)
        buttons.AddStretchSpacer()
        self.closeBtn = wx.Button(self, label="Close")
        buttons.Add(self.closeBtn, border=15, flag=wx.ALIGN_RIGHT | wx.LEFT)
        self.closeBtn.Bind(wx.EVT_BUTTON, self.onClose) # XXX do we need this?:, id=wxID_ENTER_TEXT)

        self.border = wx.BoxSizer(wx.VERTICAL)
        inputTypeSizer = wx.BoxSizer(wx.HORIZONTAL)
        inputTypeSizer.Add(inputTypeText, flag=wx.ALIGN_LEFT | wx.ALIGN_BOTTOM)
        inputTypeSizer.Add(self.inputTypeChoice, border=5, flag=wx.ALIGN_LEFT | wx.LEFT)
        # For showing the full title of the dialog when it's a long press.
        inputTypeSizer.Add((50, 1))
        self.border.Add(inputTypeSizer, border=sideBorder, flag=wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM)
        if self.image:
            self.border.Add(self.bitmapSizer, 0, border=sideBorder, flag=wx.LEFT | wx.RIGHT | wx.TOP)
            self.border.Add(charactersSizer, border=sideBorder, flag=wx.LEFT | wx.RIGHT | wx.TOP)
            if self.dragSizer:
                self.border.Add(self.dragSizer, border=sideBorder, flag=wx.LEFT | wx.RIGHT | wx.TOP)
        if self.keycodesCtrl:
            self.border.Add(keycodeSizer)
        if self.textToVerifyCtrl:
            self.border.Add(textToVerifySizer, border=sideBorder, flag=wx.LEFT | wx.RIGHT | wx.TOP)
        if self.waitCtrl:
            self.border.Add(waitSizer, border=sideBorder, flag=wx.LEFT | wx.RIGHT | wx.TOP)
            
        self.border.Add(buttons, border=sideBorder, flag=wx.ALIGN_RIGHT | wx.TOP | wx.RIGHT | wx.BOTTOM)
        self.border.Add((-1,-1), proportion=1)
        self.SetSizer(self.border)
        self.border.Fit(self)
        self.Layout()
        self.closeBtn.SetFocus()


    def onCharEvent(self, event):
        # The unicode value for a key is the same as its keycode
        # when the key is in KEY_MAP, so we don't have to deal with
        # KEY_MAP here.

        # I think it may be easiest for the user to keep a record of
        # both what is displayed on the screen and what it
        # represents. Display the control characters as, for example,
        # '[BACKSPACE]'. If the user then deletes text, the coordinate
        # in the displayed text is compared with the known displayed
        # text characters, and, if the user is deleted a character
        # within a control character, such as the 'K' within
        # '[BACKSPACE]', the entire string representing the control
        # character is deleted. This saves the user from the hassle of
        # trying to understand even more escape sequences. This
        # requires that the code know whether the user is. The event
        # object passed to the onCharEvent handler, however, does not
        # seem to have a method that allows us to readily determine
        # the location, although the handler for the EVT_TEXT event
        # (see http://docs.wxwidgets.org/stable/wx_wxtextctrl.html)
        # does, but that event is generated after the character has
        # already been placed in the string. GetLastPosition of the
        # onCharEvent handler gets the position where the cursor was
        # the last time a character was entered; if the mouse clicked
        # in a different location since then, the current position
        # will be different. So it may be possible to use the two
        # different handlers together to make entry easier on the
        # user, or to use the EVT_TEXT event and somehow figure out
        # what was pressed, but I think it would take longer than I
        # care to spend on it now.

        # Instead, I'm going to escape control characters with backtick. If backtick is entered by the user, two backticks will be generated.
        # If the user modifies the text as it's produced and messes with the representation of a control character, I'll alert the user that
        # the text cannot be parsed.
        #if CTRL is down or ALT is down:
        #    event.Skip()
        #    return
        # if the character is a control character and Verbatim is on:
        #     set a member to a representation of the control character and do not skip the character
        # elif the character is a backtick:

        # It looks like a hassle to modify text as it is sent to the TextCtrl. If a control character like
        # home is pressed, the old position has to be known. I think it's possible, however, to have a
        # backquote re-written as two backquotes.
        # self.keycodesCtrl.InsertionPoint

        # It seems like the simplest thing for the user and for me is to use a simulated keyboard to allow the user to enter
        # control characters, and to otherwise pass on the keys as they are entered to the TextCtrl, so that, f.e., a 
        # backspace causes a character to be deleted. This is easy for the user to understand and easy to implement.
        # Use cases:
        # Left arrow on the device keypad - use the simulated keyboard. `LEFT` appears in the TextCtrl. This is
        #     implemented by getting the insertion point
        # Left arrow on the 

        controlDown = event.CmdDown()
        altDown = event.AltDown()
        #self.modifyKeycodesCtrl = False
        if (not (altDown or controlDown)):
            if unichr(event.GetKeyCode()) == '`':
                self.addBacktick = True
                
        event.Skip()


    def onTextEvent(self, event):
        if self.addBacktick:
            self.addBacktick = False
            value = self.keycodesCtrl.GetValue()
            insertionPoint = self.keycodesCtrl.InsertionPoint
            value = value[:self.keycodesCtrl.InsertionPoint] + "`" + value[self.keycodesCtrl.InsertionPoint:]
            self.keycodesCtrl.SetValue(value)
            self.keycodesCtrl.InsertionPoint = insertionPoint + 1

        event.Skip()
        

    def onSimulatedKeyboard(self, event):
        value = self.keycodesCtrl.GetValue()
        value = value[:self.keycodesCtrl.InsertionPoint] + "`" + self.simulatedKeys[event.Selection].upper().replace(' ', '_') + "`" + value[self.keycodesCtrl.InsertionPoint:]
        dprint(value)
        self.keycodesCtrl.SetValue(value)


    def onClose(self, event):
        # No matter how many times the input type menu's chosen value is changed, we are assured
        # that the values from the database are passed to each instance of InputEvent dialog and
        # are not changed.
        # Here, a value of (0,) means "don't update the value in the DB". A value of None means
        # "set this value to NULL in the DB".
        characters = (0,)
        dragStartRegion = (0,)
        dragRightUnits = (0,)
        dragDownUnits = (0,)
        
        if self.charactersCtrl:
            characters = self.charactersCtrl.GetValue()
            try:
                if characters == self.charactersInDB:
                    characters = (0,)
            except:
                # Seen this occassionally: "UnicodeWarning: Unicode equal comparison failed to convert both 
                # arguments to Unicode - interpreting them as being unequal".
                pass
            if self.dragSizer:
                startRow = self.rowChoices.index(self.startRow.GetValue()) + 1
                startColumn = self.columnChoices.index(self.startColumn.GetValue()) + 1
                if (startColumn, startRow) != self.dragStartRegionInDB:
                    dragStartRegion = (startColumn, startRow)
                dragRightSign = -1 if ["left", "right"].index(self.rightOrLeftCtrl.GetValue()) == 0 else 1
                dragRightUnits = dragRightSign * int(self.rightOrLeftUnitsCtrl.GetValue())
                if dragRightUnits == self.dragRightUnitsInDB:
                    dragRightUnits = (0,)
                dragDownSign = -1 if ["up", "down"].index(self.downOrUpCtrl.GetValue()) == 0 else 1
                dragDownUnits = dragDownSign * int(self.downOrUpUnitsCtrl.GetValue())
                if dragDownUnits == self.dragDownUnitsInDB:
                    dragDownUnits = (0,)
        else:
            if self.charactersInDB is not None:
                characters = None
            if self.dragStartRegionInDB is not None:
                dragStartRegion = None
                dragRightUnits = None
                dragDownUnits = None
            
        keycodes = (0,)
        if self.keycodesCtrl:
            regexes = []
            for label in self.simulatedKeys:
                regexes.append("^`" + label.upper().replace(" ", "_") + "`")
            regexString = "|".join(regexes)
            keycodeSRE = re.compile(regexString)
            nonPrintingCodeSRE = re.compile("^`([0-9]+)`")
            # When the user hits ENTER while recording a test, i.e.
            # while he is NOT using a text field, the enter is
            # interpreted as a carriage return. However, when he presses
            # ENTER in a text field, as when editing these keycodes in a 
            # dialog, it's interpreted as a newline. Newline is not
            # interpreted like ENTER is by some if not all applications
            # when it's sent to the phone. I think it's less likely that
            # the user will be entering long text with newlines in it,
            # so interpret newlines in the text from the field as
            # carriage return. (There is no 'right' way to interpret the
            # newline.)
            text = self.keycodesCtrl.GetValue().replace('\n', '`13`')
            output = []
            index = 0
            lenText = len(text)
            while index < lenText:
                char = text[index]
                if char == '`':
                    if lenText > (index + 1) and text[index + 1] == '`':
                        output.append(ord('`'))
                        index += 2
                    elif nonPrintingCodeSRE.search(text[index:]):
                        match = nonPrintingCodeSRE.search(text[index:])
                        try:
                            code = int(match.groups()[0])
                        except:
                            pass
                        else:
                            output.append(code)
                        index += len(match.group())
                    elif keycodeSRE.search(text[index:]):
                        match = keycodeSRE.search(text[index:])
                        code = match.group()
                        lenMatch = len(code)
                        output.append(code[1:-1])
                        index += lenMatch
                    else:
                        buttonStyle = wx.OK
                        dialogStyle = wx.ICON_ERROR
                        dlg = wx.MessageDialog(self,
                                               "When backticks (`) do not appear around the code for a special key (such as LEFT_ARROW) or a numerical code representing a non-printing character (such as 13 for carriage return), they should appear in multiples of two. These groups of backticks will be reduced back down to the number of backticks you originally intended. There is no need to edit the automatic escaping of backticks that the input event dialog performs. Ensure that your backticks appear in even numbers when not surrounding the code for a special key.",
                                               "Syntax error",
                                               buttonStyle | dialogStyle)
                        dlg.ShowModal()
                        dlg.Destroy()
                        return
                else:
                    output.append(ord(char))
                    index += 1
            keycodes = " ".join([str(x) for x in output])
            if keycodes == self.keycodesInDB:
                keycodes = (0,)
        else:
            if self.keycodesInDB is not None:
                keycodes = None

        textToVerify = (0,)
        if self.textToVerifyCtrl:
            textToVerify = self.textToVerifyCtrl.GetValue()
            if textToVerify == self.textToVerifyInDB:
                textToVerify = (0,)
        else:
            if self.textToVerifyInDB is not None:
                textToVerify = None

        wait = (0,)
        if self.waitCtrl:
            try:
                wait = float(self.waitCtrl.GetValue())
            except:
                buttonStyle = wx.OK
                dialogStyle = wx.ICON_ERROR
                dlg = wx.MessageDialog(self,
                                       "It appears that the value in the wait field is not a number.",
                                       "Error",
                                       buttonStyle | dialogStyle)
                dlg.ShowModal()
                dlg.Destroy()
                return
            else:
                if wait == self.waitInDB:
                    wait = (0,)
        else:
            if self.waitInDB is not None:
                wait = None

        inputType = (0,)
        if self.inputType != self.inputTypeInDB:
            inputType = self.inputType

        targetImageHeight, targetImageWidth, targetImageString = (0,), (0,), (0,)
        if self.inputType in (constants.KEY_EVENT, constants.TEXT_TO_VERIFY, constants.WAIT):
            targetImageHeight = None
            targetImageWidth = None
            targetImageString = None
        if inputType != (0,) or characters != (0,) or keycodes != (0,) or textToVerify != (0,) or wait != (0,) or dragStartRegion != (0,) or dragRightUnits != (0,) or dragDownUnits != (0,) or targetImageHeight != (0,) or targetImageWidth != (0,) or targetImageString != (0,):
            self.mgr.recorder.updateInputEvent(sessionName=self.testName,
                                               index=self.dbIndex,
                                               inputType=inputType,
                                               dragStartRegion=dragStartRegion,
                                               dragRightUnits=dragRightUnits,
                                               dragDownUnits=dragDownUnits,
                                               targetImageHeight=targetImageHeight,
                                               targetImageWidth=targetImageWidth,
                                               targetImageString=targetImageString,
                                               characters=characters,
                                               keycodes=keycodes,
                                               textToVerify=textToVerify,
                                               wait=wait)
            self.modified = True
            # XXX set a flag to tell the replayeventsbox to update the panel
        self.Destroy()


    def onDelete(self, event):
        dprint('onDelete, dbIndex:', self.dbIndex)
        self.mgr.recorder.deleteInputEvent(self.testName, self.dbIndex)
        self.modified = True # XXX set a flag to tell the replayeventsbox to update the panel
        self.numEvents -= 1
        self.Destroy()


    def onInputType(self, event):
        if self.inputTypeChoices[self.inputTypeChoice.Selection][1] != self.inputType:
            oldInputType = self.inputType
            self.inputType = self.inputTypeChoices[self.inputTypeChoice.Selection][1]
            if not (oldInputType in (constants.TAP, constants.DRAG, constants.LONG_PRESS) and
                    self.inputType in (constants.TAP, constants.DRAG, constants.LONG_PRESS)):
                self.image = None
                self.characters = None
                self.targetImageHeight = None
                self.targetImageWidth = None
                self.targetImageString = None
            self.dragStartRegion = None
            self.dragEndRegion = None
            self.dragRightUnits = None
            self.dragDownUnits = None
            self.keycodes = []
            self.textToVerify = None
            self.wait = None

            self.doLayoutAgain = True
            self.Destroy()
            #self.doLayout()


def superimposeImageWithAlpha(backgroundString, foregroundString):
    """backgroundString is an image without an alpha channel and which has
    the pixels laid out...hmm..."""
    # OpenCV can't currently be used to load images w/ alpha channels. 
    # http://opencv.willowgarage.com/documentation/python/reading_and_writing_images_and_video.html
    
    outString = ''
    for pixelIndex in range(len(foregroundString) / 4):
        fr, fg, fb, fa = foregroundString[pixelIndex * 4:(pixelIndex + 1) * 4]
        # If the alpha channel is non-zero, get the pixels from the foreground
        # image, otherwise, use the background image.
        if fa != '\x00':
            outString += fr + fg + fb
        else:
            outString += backgroundString[pixelIndex * 3:(pixelIndex + 1) * 3]
    return outString


def runTest(frame, nb, log):
    win = TestPanel(nb, log)
    return win



