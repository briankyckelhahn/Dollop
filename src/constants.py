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


import os
import re
import sys


################################################
# These should all be False in production.
SET_TRACE = False
PRINT_DPRINT = False
PROFILE = False
LOCAL_SERVER = False
DEBUGGING_IMAGE_FINDING = False
DEBUGGING_SHOWING_DEVICE_SCREEN = False
MONKEYRUNNER_PRINT = False


STREAK_DEBUG = False
################################################


VERSION = '0.14.0'


APPLICATION_NAME_REGULAR_CASE = 'Dollop'
APPLICATION_TAR_NAME_TEMPLATE = APPLICATION_NAME_REGULAR_CASE + '.{version}.tar'
APPLICATION_ZIP_NAME_TEMPLATE = APPLICATION_NAME_REGULAR_CASE + '.{version}.zip'
APPLICATION_INNER_TAR_NAME_TEMPLATE = APPLICATION_NAME_REGULAR_CASE + '.inner.{version}.tar'
APPLICATION_INNER_COMPRESSED_TAR_NAME_TEMPLATE = APPLICATION_INNER_TAR_NAME_TEMPLATE + '.bz2'
TRIAL_INSTALLER_BUILD_NAME_TEMPLATE = APPLICATION_NAME_REGULAR_CASE + 'TrialInstaller.{version}.exe'
PERSONALIZED_TRIAL_INSTALLER_NAME_TEMPLATE = APPLICATION_NAME_REGULAR_CASE + 'TrialInstaller.{serial}.{version}.exe'
PAID_INSTALLER_BUILD_NAME_TEMPLATE = APPLICATION_NAME_REGULAR_CASE + 'PaidInstaller.{version}.exe'
PERSONALIZED_PAID_INSTALLER_NAME_TEMPLATE = APPLICATION_NAME_REGULAR_CASE + 'PaidInstaller.{serial}.{version}.exe'

APP_DIR = APPLICATION_NAME_REGULAR_CASE
# The max number of versions of the tool to keep as updates become available.
MAX_NUMBER_VERSIONS_TO_KEEP = 2
APPLICATION_CONFIG_MODULE_NAME = APPLICATION_NAME_REGULAR_CASE + '_config.py'
CORRUPTED_DB_PREFIX = 'POSSIBLY_CORRUPTED_'
# Name of the folder containing the tool executable.
EXECUTABLES_FOLDER_NAME = 'gui'
EXECUTABLE_NAME_REGULAR_CASE = 'gui'
if sys.platform.startswith(('linux', 'aix', 'hp-ux')):
    SYMLINK_NAME = APPLICATION_NAME_REGULAR_CASE + '.run'
elif sys.platform.startswith('win'):
    SYMLINK_NAME = APPLICATION_NAME_REGULAR_CASE + '.lnk'
LAUNCHER_PREFIX = '_launcher'
if sys.platform.startswith(('linux', 'aix', 'hp-ux')):
    LAUNCHER_EXECUTABLE_TEMPLATE = LAUNCHER_PREFIX + '.{version}.run'
elif sys.platform.startswith('win'):
    LAUNCHER_EXECUTABLE_TEMPLATE = LAUNCHER_PREFIX + '.{version}.exe'
# The update routine is run after an update is downloaded.
UPDATE_MODULE_FILE_NAME = 'update.{last6ofserial}.py'
UPDATE_MODULE_FILE_NAME_PLAIN = 'update.py'
if sys.platform.startswith('win'):
    UPDATE_EXECUTABLE_FILE_NAME = 'update.exe'
elif sys.platform.startswith(('linux', 'aix', 'hp-ux')):
    UPDATE_EXECUTABLE_FILE_NAME = 'update.run'
UPDATE_ROUTINE_NAME = 'run'
DO_NOT_RUN_THIS_VERSION_FILENAME = 'DO_NOT_RUN_THIS_VERSION'
MONKEYRUNNER_IMAGE_GRABBER_SCRIPT_NAME = "gi" #"monkeyGrabImages.py"

DB_FILENAME = 'tests.sqlite'
FAVICON_FILENAME = 'favicon.png'

SERVER_DOMAIN_NAME = 'dollopmobile.com'
SERVER_PORT_NUMBER = 80
EMAIL_DOMAIN_NAME = 'dollopmobile.com'

MAX_HTTP_ATTEMPTS = 2
# Should be the same as SERVER_DOMAIN_NAME, but it hasn't been implemented yet.

FEEDBACK_EMAIL_HANDLE = 'feedback'

EMULATOR_DEVICE_TYPE, NON_EMULATOR_DEVICE_TYPE = range(2)

PLAY_STATUS_NO_SESSION_LOADED = 'unloaded'
PLAY_STATUS_READY_TO_PLAY = 'ready'
PLAY_STATUS_PLAYING = 'playing'
PLAY_STATUS_PAUSED = 'paused'
PLAY_STATUS_FINISHED = 'finished'
PLAY_STATUS_STOPPED = 'stopped'
PLAY_STATUS_RECORDING = 'recording'

# Status of an event within a test.
# EVENT_MERELY_EXECUTED applies to events that do not have pass or
# fail status, such as drag. I think the reason I decided to award
# just the MERELY_EXECUTED status to drags is that users verify
# results by comparing bitmaps or text. If the user wants to 
# verify an image using my tool, he'll tap it; he won't drag it.
# Then again, he could want to verify that an icon he drags matches
# some bitmap, and then continue the same test. W/ the current
# scheme, he has to tap it and then drag it. I think that the tool
# drags a similar location on the screen a similar distance if the
# drag target can't be found.
(TEST_PASSED, TEST_FAILED, TEST_ERRORED, RESERVED2, RESERVED3, 
 RESERVED4, RESERVED5, RESERVED6, RESERVED7, RESERVED8, 
RESERVED9, RESERVED10, EVENT_PASSED, EVENT_FAILED, EVENT_ERRORED, 
EVENT_MERELY_EXECUTED, EVENT_NOT_EXECUTED) = range(17)

# These status constants apply to operations performed within an event, not to an entire event.
# Keep in mind the context; if the operation is getOCRText() (from an image), the operation
# PASSES if text is retrieved, not if a particular string is found in the text. So, maybe
# FAILED doesn't even apply here...
(SUB_EVENT_PASSED, SUB_EVENT_FAILED, SUB_EVENT_ERRORED) = range(3)

# The time taken to sleep between down() and up() to ensure
# that the press is interpreted as a long press.
# This is also the minimum time necessary for the tool to
# interpret a press as a long press.
LONG_PRESS_TIME_FOR_RECOGNITION = 0.3
# At least on Samsung Gem, a delay of 0.3 seconds between down and up
# was occassionally found to be insufficient to induce a long press.
LONG_PRESS_DELAY = 1.0

TEMPLATE_MATCH_MINIMUM = 0.85
TARGET_IMAGE_SQUARE_WIDTH=60
NUMBER_OF_IMAGE_CHANNELS = 3
# This is for positioning of the clicked location within the target image. It does not affect the size of the target image.
EVEN_WIDTH_ADDITION = EVEN_HEIGHT_ADDITION = 1 if (TARGET_IMAGE_SQUARE_WIDTH % 2) == 0 else 0


# TAP_OR_DRAG is an intermediate state and should not be present for a finished
# event.
# Always add to the end of the current range and deprecate numbers as needed.
(LEFT_DOWN_CLICK, LEFT_UP_CLICK, LEFT_MOVE, KEY_EVENT, TEXT_TO_VERIFY, TAP, DRAG, LONG_PRESS, TAP_DRAG_OR_LONG_PRESS, WAIT) = range(10)
# Many of these will probably never be displayed and aren't necessary.
INPUT_EVENT_TYPE_LABELS = {LEFT_DOWN_CLICK: 'Left Down Click',
                           LEFT_UP_CLICK: 'Left Up Click',
                           LEFT_MOVE: 'Left Move',
                           KEY_EVENT: 'Key Input',
                           TEXT_TO_VERIFY: 'Verify Text',
                           TAP: 'Tap',
                           DRAG: 'Drag',
                           LONG_PRESS: 'Long Press',
                           TAP_DRAG_OR_LONG_PRESS: 'Tap, Drag, or Long Press',
                           WAIT: 'Wait'}

OCR_BOX_PROCESS_SESSION_NAME_ALL = 'all'
OCR_BOX_PROCESS_EXITED = 100
ABORT_OCR_BOX_PROCESS = 50
TESSERACT_RESIZE_FACTOR = 4
TESSERACT_IMAGE_TEMPLATE='tesseract.{ser}.png'
# Tesseract adds '.txt' to the output name you specify.
TESSERACT_OUTPUT_TEMPLATE='tesseract.{ser}'
CHIN_BAR_IMAGE_TEMPLATE='chinBar.{ser}.png'
ORIENTATION_SRE = re.compile("mOrientation=([0-9]+)", re.MULTILINE)
# The ratio of the tolerance in the number of pixels when finding a horizontal line for
# a character to the computed x-height for that character's size.
TOLERANCE_TO_X_HEIGHT_RATIO = 1

# Orientations
PORTRAIT = 0
LANDSCAPE = 1
UNKNOWN_SCREEN_ORIENTATION = 100

# The farthest in pixels a character box returned by OCR could be and still be
# a candidate for the thing a user tapped on.
MAX_CHAR_BOX_DISTANCE = 100
# The smallest ratio between the height of a character and the distance from
# the user's tap to some point on that character to consider the tap as a tap
# on that character.
MINIMUM_CHARACTER_HEIGHT_DISTANCE_RATIO = 0.5
# The maximum number of pixels by which the y-coordinate of characters can
# differ while the characters are said to be on the same line.
SAME_LINE_Y_PIXEL_DISTANCE = 3
# The number of chars to get via OCR from an image to identify the same target
# during replay.
NUM_CHARS_FOR_TAP_IDENTIFICATION = 10
# So, make the universal ratio to go from x height to space width:
# The 'Contacts' app has smaller spaces. One of the smaller spaces
# was 6, while x height was 16. So, make space width to x height
# ratio:
SPACE_WIDTH_TO_X_HEIGHT_RATIO = 7.0 / 16
# The factor to multiply by a character dimension to determine the distance
# above which a character should not be considered related to another one.
BIG_CHAR_DISTANCE_SCALAR = 5
# The maximum Levenshtein score between a string to use for tap target
# identification and a string in the text.
MAX_LEVENSHTEIN_FOR_TARGET_IDENTIFICATION_FN = lambda (stringLength): int(0.3 * stringLength)
MAX_LEVENSHTEIN_VERIFY_FN = lambda percentageOfStringLength, stringLength: int((percentageOfStringLength / 100.0) * stringLength)
# These margins define a box within which an image must be found around
# text that has been found, if an image has to be found at all.
TEXT_AND_IMAGE_X_MARGIN = 5
TEXT_AND_IMAGE_Y_MARGIN = 35

# For drag replay:
NUMBER_OF_REGION_COLUMNS = 3
NUMBER_OF_REGION_ROWS = 3
# Indicates that the user allows the tool to drag to find a target that
# has not been found. Currently, the click type of the previous event
# is disregarded. If users want it, drag search permission could be
# granted for any type of previous click type and only when the current
# event was preceded by a drag.
DRAG_SEARCH_PERMITTED = True
MAX_FORWARD_DRAG_SEARCH_ATTEMPTS = 3
# Because going backward may have to cover the same ground as
# did going forward and then some, it may be best to have
# BACKWARD = 2 * FORWARD
MAX_BACKWARD_DRAG_SEARCH_ATTEMPTS = 2 * MAX_FORWARD_DRAG_SEARCH_ATTEMPTS

# Greatest distance in pixels of a touch path that can still be
# considered short enough to be a tap.
LONGEST_TAP_PATH = 5

# Intermediate points in a drag should be spaced this many pixels apart.
# To cope with the increased speed w/ which Android 2.3.3 interprets my
# sendevent drag commands (which resulted in a bit of fling) compared
# with Android 2.2, I reduced DRAG_STEP_SIZE_IN_PIXELS from 75 to 37
# pixels. Drags are hence slower and don't travel as far, but they're
# less likely to cause the screen to advance fast enough that something
# is missed.
DRAG_STEP_SIZE_IN_PIXELS=37

# The proportion of changed to same-value pixels in two images
# that indicate movement while dragging something between the
# two of them. Used to determine whether dragging is
# accomplishing anything.
IMAGE_CHANGE_THRESHOLD = 0.10
# 
MAX_WAIT_TIME_FOR_IMAGE_CHANGE = 10
MAX_DEFAULT_WAIT_TIME_TO_FIND_TARGET = MAX_WAIT_TIME_FOR_IMAGE_CHANGE + 1
# This might be best as a function of the frequency at which we can
# pull images, rather than a hard constant. If we can only pull two
# images over the duration of this constant, it may not a good 
# constant, b/c only half of this declared time elapsed between
# pulling the first and pulling the second.
IMAGE_CONSIDERED_STABLE_AFTER_SECONDS = 3
MINIMUM_NUMBER_FILES_FOR_IMAGE_STABILIZATION = 3

ADB_TIMEOUT=60 
MAX_NUMBER_ADB_ATTEMPTS=3
POST_DEVICE_NOT_FOUND_SLEEP = 5
DEVICE_NOT_FOUND_ERROR_MESSAGE = "error: device not found"
DEVICE_OFFLINE_ERROR_MESSAGE = "error: device offline"
PROCESS_DID_NOT_TERMINATE='Process did not terminate.'
DEFAULT_MAX_ADB_COMMAND_LENGTH=1000
# reduces maxADBCommandLength
ADB_COMMAND_REDUCTION_FACTOR=0.75
ERROR_ADB_COMMAND_LENGTH='error: service name too long'

DEBUG_DEBUG_LEVEL=0
CRITICAL_DEBUG_LEVEL=1

VNC_PORT = 5900

SCREENSHOT_METHOD_MONKEYRUNNER = 1
#SCREENSHOT_METHOD_VNC = 2 # Not implemented yet.
SCREENSHOT_METHOD_RGB32 = 100
SCREENSHOT_METHOD_RGB565 = 101
DEFAULT_SCREENSHOT_METHOD = SCREENSHOT_METHOD_MONKEYRUNNER
SCREENSHOT_METHOD_PIXFORMAT = {SCREENSHOT_METHOD_MONKEYRUNNER:'monkeyrunner',
                               SCREENSHOT_METHOD_RGB32:'rgb32',
                               SCREENSHOT_METHOD_RGB565:'rgb565'}
SCREENSHOT_METHOD_NAMES = {SCREENSHOT_METHOD_MONKEYRUNNER:'monkeyrunner',
                           SCREENSHOT_METHOD_RGB32:'RGB 32',
                           SCREENSHOT_METHOD_RGB565:'RGB 565'}

# From docs.python.org:
# When a database is accessed by multiple connections, and one of the
# processes modifies the database, the SQLite database is locked
# until that transaction is committed. The timeout parameter specifies
# how long the connection should wait for the lock to go away until
# raising an exception. The default for the timeout parameter is 5.0
# (five seconds).
SQLITE_CONNECT_TIMEOUT=60


# The height of a text entry box (wx.TextCtrl) when no size is provided.
TEXT_BOX_DEFAULT_HEIGHT = 27
PLAY_AND_RECORD_PANEL_WIDTH = 300

# Fat width in dialogs and frames on the left and right sides.
SIDE_BORDER = 15


RECONNECT_INSTRUCTIONS = "Access the \"USB connection\" menu on the device by pulling down the status bar. "
RECONNECT_INSTRUCTIONS += "Choose \"USB Mass Storage\" or something similar if that exact "
RECONNECT_INSTRUCTIONS += "option is not present. Disconnect the device. Turn off USB "
RECONNECT_INSTRUCTIONS += "debugging by unclicking the checkbox at Settings -> Applications -> "
RECONNECT_INSTRUCTIONS += "Development -> USB debugging. Re-connect the device. Wait for the "
RECONNECT_INSTRUCTIONS += "computer to recognize that a device has been connected. Turn USB "
RECONNECT_INSTRUCTIONS += "debugging back on, and then change the USB connection back to \"PC "
RECONNECT_INSTRUCTIONS += "Mode\" or the equivalent.\n\n"
RECONNECT_INSTRUCTIONS += "Also, most devices require drivers from the manufacturer. Ensure that you have "
RECONNECT_INSTRUCTIONS += "installed the appropriate ones."


# Purely for debugging:
PERFORM_TEXT_ENTRY_TEST = False

