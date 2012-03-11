# -*- coding: utf-8 -*-

# Copyright (C) 2011 Brian Kyckelhahn
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

import binascii
import cv
import Image
import logging
import os
import shutil
import sqlite3
import sys #debugging only
import time
import unicodedata

import constants
import globals_
from globals_ import *


COMMIT_TRY_LIMIT = 5


def establishDBConnection(dbName):
    conn = sqlite3.connect(dbName, timeout=constants.SQLITE_CONNECT_TIMEOUT, isolation_level=None) #'IMMEDIATE')
    conn.text_factory = str
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    return conn, cur


def executeSQL(cur, sqlString, statementParameters=()):
    try:
        cur.execute(sqlString, statementParameters)
    except sqlite3.DatabaseError, e:
        if "file is encrypted or is not a database" in e:
            corruptedDBPath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, constants.DB_FILENAME)
            newCorruptedDBPath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, constants.DB_FILENAME + ".maybeCorrupted")
            showErrorDialog("Database error",
                            "We're sorry, but it seems that the database that is used to store tests on your machine has become corrupted. A backup database will be restored. The possibly-corrupted database is being moved to " + newCorruptedDBPath + ".")
            shutil.move(corruptedDBPath, newCorruptedDBPath)
            shutil.copyfile(corruptedDBPath + '.backup', corruptedDBPath)
            # We raise an exception. If we didn't raise an exception, the method that made the call
            # on the Storage object will continue. For example, if the method that caused the DB to
            # be corrupted was a load session call, the load session dialog, which will be
            # completely empty, will be shown if we don't raise an exception. I do not know,
            # however, where this exception is being caught. The app continues to function after
            # the exception is raised.
            raise CorruptedDatabaseException()
        raise
    except sqlite3.OperationalError, e:
        dprint("executeSQL: retrying due to OperationalError:", e)
        time.sleep(1)
        try:
            cur.execute(sqlString, statementParameters)
        except sqlite3.DatabaseError, e:
            if "file is encrypted or is not a database" in e:
                corruptedDBPath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, constants.DB_FILENAME)
                newCorruptedDBPath = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, constants.DB_FILENAME + ".maybeCorrupted")
                showErrorDialog("Database error",
                                "We're sorry, but it seems that the database that is used to store tests on your machine has become corrupted. A backup database will be restored. The possibly-corrupted database is being moved to " + newCorruptedDBPath + ".")
                shutil.move(corruptedDBPath, newCorruptedDBPath)
                shutil.copyfile(corruptedDBPath + '.backup', corruptedDBPath)
                # We raise an exception. If we didn't raise an exception, the method that made the call
                # on the Storage object will continue. For example, if the method that caused the DB to
                # be corrupted was a load session call, the load session dialog, which will be
                # completely empty, will be shown if we don't raise an exception. I do not know,
                # however, where this exception is being caught. The app continues to function after
                # the exception is raised.
                raise CorruptedDatabaseException()
            raise
        except sqlite3.OperationalError, e:
            dprint("executeSQL: failed again due to OperationalError:", e)
            raise
        except Exception, e:
            dprint("executeSQL: failed again due to this exception:", e)


class Storage(object):
    def __init__(self, backUpDB=False):
        # backUpDB exists so that, when the tool is first run, the DB is backed up.
        # Multiple instances of Storage are created as the tool runs, however, and
        # performing this op every time f/ every instantiation isn't necessary.

        # XXX read DB name fr/ config file?
        dprint("STARTING Storage __init__")
        self.db = os.path.join(globals_.getUserDocumentsPath(), constants.APP_DIR, constants.DB_FILENAME)

        conn, cur = establishDBConnection(self.db)
        try:
            executeSQL(cur, "SELECT * FROM sessions LIMIT 1")
        except sqlite3.OperationalError, e:
            # The table doesn't exist.
            # XXX I've been unable to make timeWithSubseconds a primary key, as in
            # (timeWithSubseconds text PRIMARY KEY, ...
            sessionsCreationText = '''create table sessions
            (name text PRIMARY KEY,
             fineDateTime text,
             inputEventsProcessed int DEFAULT 0)'''
            executeSQL(cur, sessionsCreationText)
            executeSQL(cur, """CREATE INDEX sessionsIndex ON
            sessions(name)""")
            if backUpDB:
                dprint('beginning the copying of the database (1)')
                shutil.copyfile(self.db, self.db + '.backup')
                dprint('finished the copying of the database')
        except sqlite3.DatabaseError, e:
            # The DB is corrupted.
            if os.path.exists(self.db + '.backup'):
                try:
                    shutil.copyfile(self.db + '.backup', self.db)
                    conn, cur = establishDBConnection(self.db)
                    executeSQL(cur, "SELECT * FROM sessions LIMIT 1")
                except sqlite3.DatabaseError, e:
                    raise
                except sqlite3.OperationalError, e:
                    executeSQL(cur, sessionsCreationText)
                    executeSQL(cur, """CREATE INDEX sessionsIndex ON
                    sessions(name)""")
                else:
                    shutil.copyfile(self.db, self.db + '.backup')
            else:
                raise
        else:
            # XXX If the DB backup file is as new as the DB file, don't copy.
            if backUpDB:
                dprint('beginning the copying of the database (2)')
                shutil.copyfile(self.db, self.db + '.backup')
                dprint('finished the copying of the database')
            
        try:
            executeSQL(cur, "SELECT * FROM perSessionDeviceData LIMIT 1")
        except sqlite3.OperationalError, e:
            # Some attributes of the device may change between
            # sessions.
            # XXX If this is the case, why are we storing this data
            # (and then relying on it to be up-to-date when the
            #  test is run)?
            # XXX When a device is recognized by the GUI (as on
            # startup), that device should be registered in memory,
            # and its attributes as determined at that time should
            # be used if a test is run against it.
            # Because a small chance exists that the internal height
            # given to the device's chin bar could change with an
            # update to the device OS/firmware, chinBarHeight is a
            # per-session attribute.
            # chinBarImageString is much more likely to change, most
            # likely due to an update to TST that makes it prettier.
            executeSQL(cur, '''create table perSessionDeviceData
            (session text REFERENCES sessions(name) ON DELETE CASCADE ON UPDATE CASCADE,
             serialNo text,
             keycodeMapName text,
             orientation int,
             chinBarHeight int,
             chinBarImageString blob)''')
        try:
            executeSQL(cur, "SELECT * FROM clicks LIMIT 1")
        except sqlite3.OperationalError, e:
            # A session may involve more than one device, so we record the
            # device for each click.
            # x and y are screen coords, not those transmitted to the device to perform the tap.
            # Also, the coordinate system doesn't change
            # with changes in device orientation.
            executeSQL(cur, """CREATE TABLE clicks
            (session text REFERENCES sessions(name) ON DELETE CASCADE ON UPDATE CASCADE,
             serialNo text,
             timeWithSubseconds text,
             clickType int,
             x text,
             y text,
             targetWidth int,
             targetHeight int,
             imageFilename text,
             PRIMARY KEY (session, serialNo, timeWithSubseconds, clickType))""")

        # A text entry session is a period during which only text is
        # entered (and no clicks or other input is received). Characters
        # entered during the session can be separated by long times.
        try:
            executeSQL(cur, "SELECT * FROM keyEventsSessions LIMIT 1")
        except sqlite3.OperationalError, e:
            # A session may involve more than one device, so we record the
            # device for each click.
            executeSQL(cur, """CREATE TABLE keyEventsSessions
            (session text REFERENCES sessions(name) ON DELETE CASCADE ON UPDATE CASCADE,
             serialNo text,
             startSeconds text,
             PRIMARY KEY (session, serialNo, startSeconds))""")

        # Create a row for each individual keystroke and keycode entered
        # during the text entry session.
        # Only one of keycode and scancode is non-NULL in each row.
        # keycode is the name of the keycode if one was sent.
        # scancode is a number and is sent to represent individual chars.
        try:
            executeSQL(cur, "SELECT * FROM keyEvents LIMIT 1")
        except sqlite3.OperationalError, e:
            executeSQL(cur, """CREATE TABLE keyEvents
            (keyEventsSessionID int,
             index_ int,
             keycode text,
             scancode int)""")
             #PRIMARY KEY (keyEventsSessionID, index_))""")

        try:
            executeSQL(cur, "SELECT * FROM textToVerify LIMIT 1")
        except sqlite3.OperationalError, e:
            executeSQL(cur, """CREATE TABLE textToVerify
            (session text REFERENCES sessions(name) ON DELETE CASCADE ON UPDATE CASCADE,
             serialNo text,
             timeWithSubseconds text,
             text_ text,
             PRIMARY KEY (session, serialNo, timeWithSubseconds))""")

        try:
            executeSQL(cur, "SELECT * FROM waits LIMIT 1")
        except sqlite3.OperationalError, e:
            executeSQL(cur, """CREATE TABLE waits
            (session text REFERENCES sessions(name) ON DELETE CASCADE ON UPDATE CASCADE,
             timeWithSubseconds text,
             seconds float,
             PRIMARY KEY (session, timeWithSubseconds))""")

        try:
            executeSQL(cur, "SELECT * FROM savedScreens LIMIT 1")
        except sqlite3.OperationalError, e:
            executeSQL(cur, """CREATE TABLE savedScreens
            (session text REFERENCES sessions(name) ON DELETE CASCADE ON UPDATE CASCADE,
             serialNo text,             
             timeWithSubseconds text,
             lcdImageString blob)""")
            executeSQL(cur, """CREATE INDEX savedScreensIndex ON
            savedScreens(session)""")
        try:
            executeSQL(cur, "SELECT * FROM events LIMIT 1")
        except sqlite3.OperationalError, e:
            # characters and keycodes are space-separated strings of character codes
            # dragStartRegion and dragEndRegion are binary tuples of 1-based coordinates in the form (column, row),
            # where row numbering increases down.
            # dragEndRegion is redundant b/c it's determined by dragStartRegion, dragRightUnits, and dragDownUnits. Ignore it.
            
            # index_ is of type real so that (in the future) an event can be inserted between existing events
            # w/o updating all of the events that follow it.
            # e.g. If an event is insert between events 1 and 2, that new event could be given index_ 1.5.
            # THIS MEANS THAT index_ CANNOT BE RELIED ON TO BE A COUNTING SEQUENCE.
            executeSQL(cur, """CREATE TABLE events
            (session text REFERENCES sessions(name) ON DELETE CASCADE ON UPDATE CASCADE,
             index_ real,
             serialNo text,
             startTime int,
             inputType int,
             characters text,
             targetImageWidth int,
             targetImageHeight int,
             targetImageString blob,
             keycodes text,
             textToVerify text,
             wait float,
             dragStartRegion text,
             dragEndRegion text,
             dragRightUnits int,
             dragDownUnits int,
             PRIMARY KEY (session, index_))""")

        # XXX might create a session-devices mapping table
        try:
            executeSQL(cur, "SELECT * FROM devices LIMIT 1")
        except sqlite3.OperationalError, e:
            # totalHeight = height of LCD screen + height of chin bar
            # Because a small chance exists that the internal height
            # given to the device could change with an update to the
            # device OS/firmware, chinBarHeight is a per-session
            # attribute.
            executeSQL(cur, """CREATE TABLE devices
            (serialNo text PRIMARY KEY,
             width INTEGER,
             lcdHeight INTEGER,
             maxADBCommandLength INTEGER)""")

        try:
            executeSQL(cur, "SELECT * FROM deviceData LIMIT 1")
        except sqlite3.OperationalError, e:
            # timeWithSubseconds is the time that this entry and
            # those in deviceData pointing to it were added. It
            # doesn't necessarily mean that the test was started
            # then.
            executeSQL(cur, """CREATE TABLE deviceData
            (serialNo text REFERENCES devices(serialNo) ON DELETE CASCADE ON UPDATE CASCADE,
             timeWithSubseconds text,
             PRIMARY KEY (serialNo, timeWithSubseconds))""")

        try:
            executeSQL(cur, "SELECT * FROM deviceVirtualKeys LIMIT 1")
        except sqlite3.OperationalError, e:
            # It's possible that internal values for the virtual keys
            # could change with new builds of the OS, so this table is
            # made a per-build table.
            executeSQL(cur, """CREATE TABLE deviceVirtualKeys
            (serialNo text REFERENCES devices(serialNo) ON DELETE CASCADE ON UPDATE CASCADE,
             timeWithSubseconds INTEGER,
             keycode INTEGER,
             hitTop INTEGER,
             hitBottom INTEGER,
             hitLeft INTEGER,
             hitRight INTEGER,
             FOREIGN KEY (serialNo, timeWithSubseconds) REFERENCES deviceData(serialNo, timeWithSubseconds) ON DELETE CASCADE ON UPDATE CASCADE)""")

        try:
            executeSQL(cur, "SELECT * FROM plays LIMIT 1")
        except sqlite3.OperationalError, e:
            # A session may involve more than one device, so we record the
            # device for each click.
            # x and y are screen coords, not those transmitted to the device to perform the tap.
            # Also, the coordinate system doesn't change
            # with changes in device orientation.
            executeSQL(cur, '''create table plays
            (name text PRIMARY KEY)''')

        try:
            executeSQL(cur, "SELECT * FROM testsInPlays LIMIT 1")
        except sqlite3.OperationalError, e:
            # A session may involve more than one device, so we record the
            # device for each click.
            # x and y are screen coords, not those transmitted to the device to perform the tap.
            # Also, the coordinate system doesn't change
            # with changes in device orientation.
            executeSQL(cur, '''create table testsInPlays
            (play text,
             session text,
             indexInPlayBaseZero int DEFAULT 0,
             FOREIGN KEY (session) REFERENCES sessions(name) ON DELETE CASCADE ON UPDATE CASCADE,
             FOREIGN KEY (play) REFERENCES plays(name) ON DELETE CASCADE ON UPDATE CASCADE,
             PRIMARY KEY (play, session, indexInPlayBaseZero))''')

        try:
            executeSQL(cur, "SELECT * FROM perPlayDeviceData LIMIT 1")
        except sqlite3.OperationalError, e:
            # Some attributes of the device may change between
            # sessions.
            # Because a small chance exists that the internal height
            # given to the device's chin bar could change with an
            # update to the device OS/firmware, chinBarHeight is a
            # per-session attribute.
            # chinBarImageString is much more likely to change, most
            # likely due to an update to TST that makes it prettier.
            executeSQL(cur, '''create table perPlayDeviceData
            (play text,
             serialNo text,
             orientation int,
             chinBarHeight int,
             FOREIGN KEY (play) REFERENCES plays(name))''')

        try:
            executeSQL(cur, "SELECT * FROM playClicks LIMIT 1")
        except sqlite3.OperationalError, e:
            # imageString includes the LCD and the chin bar, if any.
            # SQLite has no boolean data type; int is used instead.
            executeSQL(cur, """CREATE TABLE playClicks
            (session text REFERENCES sessions(name) ON DELETE CASCADE ON UPDATE CASCADE,
             play text,
             serialNo text,
             timeWithSubseconds text,
             clickType text,
             x text,
             y text,
             imageString blob,
             targetFound int,
             PRIMARY KEY (session, play, serialNo, timeWithSubseconds, clickType))""")

        try:
            executeSQL(cur, "SELECT * FROM processedTests LIMIT 1")
        except sqlite3.OperationalError, e:
            executeSQL(cur, """CREATE TABLE processedTests
            (session text REFERENCES sessions(name) ON DELETE CASCADE ON UPDATE CASCADE,
             serialNo text,
             timeWithSubseconds text,
             textOutput text,
             PRIMARY KEY (session, serialNo, timeWithSubseconds))""")

        # try:
        #     executeSQL(cur, "SELECT * FROM rawInputEvents LIMIT 1")
        # except sqlite3.OperationalError, e:
        #     executeSQL(cur, """CREATE VIEW rawInputEvents AS SELECT clicks.session AS session, clicks.serialNo AS serialNo, clicks.timeWithSubseconds AS time,
        #     clickType AS type, x, y, targetWidth, targetHeight, targetImageString, lcdImageString,
        #     0 AS index_, 0 AS keyEventsSessionID, 0 AS keycode, '' AS text_, 0 AS wait FROM clicks join
        #     savedScreens on clicks.session=savedScreens.session AND clicks.serialNo=savedScreens.serialNo
        #     AND clicks.timeWithSubseconds=savedScreens.timeWithSubseconds UNION
        #     SELECT keyEventsSessions.session AS session, keyEventsSessions.serialNo AS serialNo, keyEventsSessions.startSeconds AS time,
        #     {KEYEVENT} AS type, 0 AS x, 0 AS y, 0 AS targetWidth, 0 AS targetHeight, 0 AS targetImageString,
        #     0 AS lcdImageString, keyEvents.index_ AS index_, keyEvents.keyEventsSessionID AS
        #     keyEventsSessionID, keyEvents.keycode AS keycode, '' AS text_, 0 AS wait FROM keyEventsSessions JOIN
        #     keyEvents ON keyEventsSessions.ROWID=keyEvents.keyEventsSessionID 
        #     UNION SELECT textToVerify.session AS session, textToVerify.serialNo, textToVerify.timeWithSubseconds
        #     AS time, {TEXTVERIFY} AS type, 0 AS x, 0 AS y, 0 AS targetWidth, 0 AS targetHeight, 0 AS
        #     targetImageString, 0 AS lcdImageString, 0 AS index_, 0 AS keyEventsSessionID, 0 AS keycode,
        #     textToVerify.text_ AS text_, 0 AS wait FROM textToVerify UNION SELECT waits.session AS session,
        #     '' AS serialNo, waits.timeWithSubseconds AS time, {WAIT} AS type, 0 AS x, 0 AS y, 0 AS
        #     targetWidth, 0 AS targetHeight, 0 AS targetImageString, 0 AS lcdImageString, 0 AS index_,
        #     0 AS keyEventsSessionID, 0 AS keycode, '' AS text_, seconds AS wait FROM waits ORDER BY time,
        #     index_""".format(KEYEVENT=constants.KEY_EVENT, TEXTVERIFY=constants.TEXT_TO_VERIFY, WAIT=constants.WAIT),
        #           )
            
        conn.commit()
        cur.close()
        dprint('ENDING Storage __init__')
        # (session name, device serial number) -> [ROWID, index of last entered key]
        self.ongoingKeyEventsSessions = {}


    def restoreBackup(self):
        copyDest = os.path.join(os.path.dirname(self.db),
                                constants.CORRUPTED_DB_PREFIX + os.path.basename(self.db))
        dprint("copyDest:", copyDest)
        dprint("os.path.basename(self.db):", os.path.basename(self.db))
        dprint("os.path.dirname(self.db):", os.path.dirname(self.db))
        dprint("self.db:", self.db)
        shutil.copyfile(self.db, copyDest)
        # The old backup is the new DB and is still the backup, too (this is a copy, not a move).
        shutil.copyfile(self.db + '.backup', self.db)


    def executeRawCommand(self, text):
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, text)
        returned = cur.fetchall()
        conn.commit()
        cur.close()
        return returned

        
    def getDevice(self, serialNo):
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT width, lcdHeight, maxADBCommandLength FROM devices WHERE devices.serialNo=?",
                   (serialNo,))
        device = cur.fetchone()
        cur.close()
        return device


    def getDevicesOfSession(self, sessionID):
        #dprint('STARTING getDevicesofSession')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT devices.serialNo, width, lcdHeight, maxADBCommandLength, chinBarHeight, chinBarImageString, orientation FROM devices JOIN perSessionDeviceData ON devices.serialNo=perSessionDeviceData.serialNo WHERE perSessionDeviceData.session=?",
                   (sessionID,))
        devices = cur.fetchall()
        cur.close()
        devices_ = []
        for serialNo, width, lcdHeight, maxADBCommandLength, chinBarHeight, chinBarImageString, orientation in devices:
            # I do str(chinBarImageString) here b/c buffer objects are not picklable, which the
            # args to gui.py:ReplayProcess must be due to an MS Windows restriction when multiprocessing
            devices_.append((serialNo, width, lcdHeight, maxADBCommandLength, chinBarHeight, str(chinBarImageString), orientation))
        #dprint('ENDING getDevicesofSession')
        return devices_
        

    def getEventsForSession(self, sessionID):
#        dprint('STARTING getEventsForSession')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, """SELECT clicks.serialNo AS serialNo, clicks.timeWithSubseconds AS time, 
        clickType AS type, x, y, targetWidth, targetHeight, imageFilename, 
        0 AS index_, 0 AS keyEventsSessionID, 0 AS keycode, 0 AS scancode, '' AS text_, 0 AS wait 
        FROM clicks WHERE clicks.session=? UNION 

        SELECT keyEventsSessions.serialNo AS serialNo, keyEventsSessions.startSeconds AS time, 
        {KEYEVENT} AS type, 0 AS x, 0 AS y, 0 AS targetWidth, 0 AS targetHeight, '' AS imageFilename, 
        keyEvents.index_ AS index_, keyEvents.keyEventsSessionID AS keyEventsSessionID, 
        keyEvents.keycode AS keycode, keyEvents.scancode AS scancode, '' AS text_, 0 AS wait FROM keyEventsSessions JOIN 
        keyEvents ON keyEventsSessions.ROWID=keyEvents.keyEventsSessionID WHERE 
        keyEventsSessions.session=? UNION 

        SELECT textToVerify.serialNo, textToVerify.timeWithSubseconds AS time, {TEXTVERIFY} AS type, 
        0 AS x, 0 AS y, 0 AS targetWidth, 0 AS targetHeight, '' AS 
        imageFilename, 0 AS index_, 0 AS keyEventsSessionID, 0 AS keycode, 0 AS scancode,
        textToVerify.text_ AS text_, 0 AS wait FROM textToVerify WHERE textToVerify.session=? UNION 

        SELECT '' AS serialNo, waits.timeWithSubseconds AS time, {WAIT} AS type, 0 AS x, 0 AS y, 0 AS 
        targetWidth, 0 AS targetHeight, '' AS imageFilename, 0 AS index_, 
        0 AS keyEventsSessionID, 0 AS keycode, 0 AS scancode, '' AS text_, seconds AS wait FROM waits WHERE 
        waits.session=? ORDER BY time, 
        index_""".format(KEYEVENT=constants.KEY_EVENT, TEXTVERIFY=constants.TEXT_TO_VERIFY, WAIT=constants.WAIT),
                    (sessionID, sessionID, sessionID, sessionID))
        clicks = cur.fetchall()
        clicks_ = []
        for (serialNo, timeWSs, clickType, x, y, targetWidth, targetHeight, imageFilename, index_, keyEventsSessionID, keycode, scancode, text_, wait) in clicks:
            # I made x and y of type 'text' in the DB; don't know why. 
            # In case floats are used in the future, use float here.
            clicks_.append((serialNo, timeWSs, clickType, int(x), int(y), targetWidth, targetHeight, 
                            imageFilename, index_, keyEventsSessionID, keycode or scancode, text_, wait))
#        dprint('ENDING getEventsForSession')

        executeSQL(cur, """SELECT chinBarImageString FROM perSessionDeviceData WHERE session=?""",
                   (sessionID,))
        chinBarImageString = cur.next()
        if len(chinBarImageString) == 1:
            chinBarImageString = chinBarImageString[0]
        cur.close()
        return clicks_, chinBarImageString


    def saveVirtualKeys(self, serialNo, virtualKeys):
        dprint('STARTING saveVirtualKeys')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT strftime('%s %f', 'now')")
        seconds = cur.next()[0]

        executeSQL(cur, "INSERT INTO deviceData (serialNo, timeWithSubseconds) VALUES (?, ?)",
                    (serialNo, seconds))

        keys = []
        for key in virtualKeys:
            keys += [serialNo, seconds, key, virtualKeys[key]['hitLeft'],
                     virtualKeys[key]['hitRight'], virtualKeys[key]['hitTop'],
                     virtualKeys[key]['hitBottom']]
        keys = tuple(keys)
        select = " SELECT ? AS serialNo, ? as timeWithSubseconds, ? as keycode, ? as hitLeft, ? as hitRight, ? as hitTop, ? as hitBottom "
        troublesomeInsertString = ("INSERT INTO deviceVirtualKeys (serialNo, timeWithSubseconds, keycode, hitLeft, hitRight, hitTop, hitBottom) " +
                                   "union".join([select] * len(virtualKeys.keys())))
        traceLogger.debug(troublesomeInsertString)
        executeSQL(cur, troublesomeInsertString,
                    keys)
        conn.commit()
        cur.close()
        dprint('ENDING saveVirtualKeys')


    def getVirtualKeys(self, serialNo):
        dprint('STARTING getVirtualKeys')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT keycode, hitTop, hitBottom, hitLeft, hitRight FROM (SELECT serialNo, timeWithSubseconds FROM deviceData WHERE serialNo=? ORDER BY timeWithSubseconds DESC LIMIT 1) deviceData JOIN deviceVirtualKeys ON deviceData.timeWithSubseconds=deviceVirtualKeys.timeWithSubseconds AND deviceData.serialNo=deviceVirtualKeys.serialNo",
                    (serialNo,))
        data = cur.fetchall()
        cur.close()
        dprint('ENDING getVirtualKeys')
        return data

        
    def getSessionNames(self):
        dprint('STARTING getSessionNames')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT name FROM sessions ORDER BY name")
        sessionNames = [x[0] for x in cur.fetchall()]
        cur.close()
        dprint('ENDING getSessionNames')
        return sessionNames


    def renameSession(self, oldName, newName):
        conn, cur = establishDBConnection(self.db)
        #executeSQL(cur, "SELECT name FROM sessions WHERE name=?", (oldName,))
        #foo=cur.fetchall()
        # The user may be deleting another, existing test in the process of renaming the test. Delete
        # all occurrences of the old one, which has the new name, first.
        executeSQL(cur, "DELETE FROM sessions WHERE name=?", (newName,))  # yes, newName, not oldName
        #conn.commit()
        executeSQL(cur, "UPDATE sessions SET name=? WHERE name=?", (newName, oldName))
        conn.commit()
        cur.close()

        
    def deleteSessions(self, sessionNames):
        dprint('STARTING deleteSessions')
        conn, cur = establishDBConnection(self.db)
        #sessionsString = ','.join(sessionNames)
        #executeSQL(cur, "DELETE FROM sessions WHERE name IN " + sessionsString)
        if len(sessionNames) == 1:
            questionMarks = '(?)'
        else:
            questionMarks = str(('?',) * len(sessionNames)).replace("'", '')
        executeSQL(cur, "SELECT ROWID FROM keyEventsSessions WHERE session IN " + questionMarks, tuple(sessionNames))
        keyEventsSessionIDs = cur.fetchall()
        keyEventsSessionIDs = tuple([x[0] for x in keyEventsSessionIDs])
        executeSQL(cur, "DELETE FROM sessions WHERE name IN " + questionMarks, tuple(sessionNames))
        if len(keyEventsSessionIDs) == 1:
            questionMarks = '(?)'
        else:
            questionMarks = str(('?',) * len(keyEventsSessionIDs)).replace("'", '')        
        executeSQL(cur, "DELETE FROM keyEvents WHERE keyEventsSessionID IN " + questionMarks, keyEventsSessionIDs)
        conn.commit()
        cur.close()
        dprint('ENDING deleteSessions')


    def getSuggestedSessionName(self):
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT dateTime('now', 'localtime')")
        dateTime = cur.next()[0].replace(':', '_').replace(' ', '_')
        return dateTime


    def startSession(self, deviceData, name):
        # deviceData is a tuple of the form:
        # serialNo, width, lcdHeight, chinBarHeight, chinBarImageString, orientation
        traceLogger.debug("startSession()")
        dprint('STARTING startSession')
        conn, cur = establishDBConnection(self.db)
        # XXX I have not been able to combine the following two SELECTs.
        executeSQL(cur, "SELECT strftime('%s %f', 'now')")
        seconds = cur.next()[0]
        executeSQL(cur, "SELECT dateTime('now')")
        #seconds = '234.234'
        #dateTime = '234 234'
        dateTime = cur.next()[0]
        subSeconds = seconds[seconds.rfind('.'):]
        fineDateTime = dateTime + subSeconds
        executeSQL(cur, "INSERT INTO sessions (fineDateTime, name) VALUES (?, ?)",
                   (None, name))
                    #(fineDateTime, name))
        for serialNo, width, lcdHeight, chinBarHeight, chinBarImageString, orientation in deviceData:
            executeSQL(cur, ("INSERT INTO perSessionDeviceData (session, serialNo, orientation, chinBarHeight, " +
                         "chinBarImageString) VALUES (?, ?, ?, ?, ?)"),
                        (name, serialNo, orientation, chinBarHeight, sqlite3.Binary(chinBarImageString)))
        conn.commit() # this commit() was missing and may have been the source of the 'database is locked' msg
        cur.close()
        dprint('ENDING startSession')
        return name


    def addDeviceIfNecessary(self, serialNo, screenWidth, lcdHeight, maxADBCommandLength):
        dprint('STARTING addDeviceIfNecessary')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT ROWID FROM devices WHERE serialNo=?", (serialNo,))
        try:
            id = cur.next()[0]
        except StopIteration:
            executeSQL(cur, "INSERT INTO devices (serialNo, width, lcdHeight, maxADBCommandLength) VALUES (?, ?, ?, ?)", (serialNo, screenWidth, lcdHeight, maxADBCommandLength))
            conn.commit()
        cur.close()
        dprint('ENDING addDeviceIfNecessary')


    def updateDeviceInfo(self, serialNo, maxADBCommandLength):
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "UPDATE devices SET maxAdbCommandLength=? WHERE serialNo=?", (maxADBCommandLength, serialNo,))
        conn.commit()
        cur.close()
        
            
    def saveScreen(self, session, serialNo, imageString):
        # sqlite3.Binary is used to store blobs because it prevents sqlite from
        # thinking that it has reached the end of the string when it finds a null
        # byte.
        dprint('STARTING saveScreen')
        conn, cur = establishDBConnection(self.db)
        numTries = 0        
        while True:
            # This while loop guards against a rare error; the savedScreens table
            # is said not to exist.
            try:
                executeSQL(cur, "INSERT INTO savedScreens (session, serialNo, timeWithSubseconds, lcdImageString) VALUES (?, ?, strftime('%s %f', 'now'), ?)",
                            (session, serialNo, sqlite3.Binary(imageString)))
            except sqlite3.OperationalError, e:
                numTries += 1
                # Just use COMMIT_TRY_LIMIT.
                if numTries == COMMIT_TRY_LIMIT:
                    # XXX Comment this exception and degrade gracefully in the production
                    # code, or pop up a dialog asking the user to handle this.
                    raise Exception("failure to execute an INSERT statement into savedScreens")
            else:
                break
                
        numTries = 0
        while True:
            try:
                conn.commit()
            except sqlite3.OperationalError, e:
                numTries += 1
                if numTries == COMMIT_TRY_LIMIT:
                    raise Exception("failure to commit to sqlite")
            else:
                break
        cur.close()
        dprint('ENDING saveScreen')


    def clearOngoingKeyEventsSessions(self, session, serialNo):
        if self.ongoingKeyEventsSessions.has_key((session, serialNo)):
            del self.ongoingKeyEventsSessions[(session, serialNo)]

        
    def saveClick(self, session, serialNo, clickType, x, y, targetWidth, targetHeight, 
                  imageFilename, timeOfClick=None):
        if self.ongoingKeyEventsSessions.has_key((session, serialNo)):
            del self.ongoingKeyEventsSessions[(session, serialNo)]

        conn, cur = establishDBConnection(self.db)
        if not timeOfClick:
            executeSQL(cur, "SELECT strftime('%s %f', 'now')")
            timeWithSubseconds = cur.next()[0]
        else:
            seconds = round(timeOfClick % 60, 3)
            if seconds < 10:
                seconds = '0' + str(seconds)
            else:
                seconds = str(seconds)
            timeWithSubseconds = str(int(timeOfClick)) + ' ' + seconds

     
        try:
            executeSQL(cur, "INSERT INTO clicks (session, serialNo, timeWithSubseconds, clickType, x, y, targetWidth, targetHeight, imageFilename) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (session, serialNo, timeWithSubseconds, clickType, x, y, targetWidth, targetHeight, 
                        imageFilename))
        except Exception, e:
            dprint("saveclick failed, debug here" + "!" * 20)
            bdbg()
        conn.commit()

        dprint('saveClick, session, serialNo, timeWithSubseconds, clickType, x, y, targetWidth, targetHeight, imageFilename', session, serialNo, timeWithSubseconds, clickType, x, y, targetWidth, targetHeight, imageFilename)

        if clickType == constants.LEFT_DOWN_CLICK:
            # Creating this row now allows the OCRBoxProcess to merely UPDATE ... WHERE, rather than INSERT INTO, the table.
            # UPDATE ... WHERE will not create a FOREIGN KEY constraint exception when the row has been deleted, which may
            # happen when the session has been deleted.
            executeSQL(cur, "INSERT INTO processedTests (session, serialNo, timeWithSubseconds, textOutput) VALUES (?, ?, ?, ?)",
                        (session, serialNo, timeWithSubseconds, None))
            conn.commit()

#        executeSQL(cur, "INSERT INTO savedScreens (session, serialNo, timeWithSubseconds, lcdImageString) VALUES (?, ?, ?, ?)",
#                    (session, serialNo, timeWithSubseconds, sqlite3.Binary(lcdImageString)))
        conn.commit()
        cur.close()


    def _startKeyEventsSession(self, session, serialNo):
        dprint('STARTING _startKeyEventsSession')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT strftime('%s %f', 'now')")
        timeWithSubseconds = cur.next()[0]
        executeSQL(cur, "INSERT INTO keyEventsSessions (session, serialNo, startSeconds) VALUES (?, ?, ?)",
                    (session, serialNo, timeWithSubseconds))
        conn.commit()
        executeSQL(cur, "SELECT ROWID FROM keyEventsSessions WHERE session=? AND serialNo=? AND startSeconds=?",
                    (session, serialNo, timeWithSubseconds))
        rowID = cur.next()[0]
        cur.close()
        dprint('ENDING _startKeyEventsSession')
        self.ongoingKeyEventsSessions[(session, serialNo)] = [rowID, -1]


    def addKeyEvents(self, session, serialNo, keycodes):
        if not self.ongoingKeyEventsSessions.has_key((session, serialNo)):
            self._startKeyEventsSession(session, serialNo)

        dprint('STARTING addKeyEvents')
        conn, cur = establishDBConnection(self.db)
        rowID = self.ongoingKeyEventsSessions[(session, serialNo)][0]
        startingIndex = self.ongoingKeyEventsSessions[(session, serialNo)][1] + 1
        select = " SELECT ? AS keyEventsSessionID, ? as index_, ? as keycode, ? as scancode "
        values = []
        for number, key in enumerate(keycodes):
            number_ = number + startingIndex
            if type(key) == str:
                # keycode
                values += [rowID, number_, key, None]
            else:
                # scancode
                values += [rowID, number_, None, key]
        executeSQL(cur, ("INSERT INTO keyEvents (keyEventsSessionID, index_, keycode, scancode) " +
                         "union".join([select] * len(keycodes))),
                    values)
        conn.commit()
        cur.close()
        dprint('ENDING addKeyEvents')
        self.ongoingKeyEventsSessions[(session, serialNo)][1] += len(keycodes)


    def addTextToVerify(self, session, serialNo, text):
        if self.ongoingKeyEventsSessions.has_key((session, serialNo)):
            del self.ongoingKeyEventsSessions[(session, serialNo)]

        dprint('STARTING addTextToVerify')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, ("INSERT INTO textToVerify (session, serialNo, timeWithSubseconds, " +
                     "text_) VALUES (?, ?, strftime('%s %f', 'now'), ?)"),
                    (session, serialNo, text))
        conn.commit()
        cur.close()
        dprint('ENDING addTextToVerify')
        

    def addWait(self, session, seconds):
        dprint('STARTING addWait')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "INSERT INTO waits (session, timeWithSubseconds, seconds) VALUES " + 
                    "(?, strftime('%s %f', 'now'), ?)",
                    (session, seconds))
        conn.commit()
        cur.close()
        dprint('ENDING addWait')


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
                       keycodes=None,
                       textToVerify=None,
                       wait=False,
                       dragStartRegion=None,
                       dragEndRegion=None,
                       dragRightUnits=None,
                       dragDownUnits=None,
                       waitForImageStabilization=False):
        
        conn, cur = establishDBConnection(self.db)
        try:
            with open(sessionPath, 'a') as fp:
                if characters:
                    characters_ = characters.encode('string_escape')
                else:
                    characters_ = ''
                if targetImageString:
                    targetImagePath = os.path.join(testFolderPath, "target." + str(index) + ".png")
                    targetImage = cv.CreateImageHeader((targetImageWidth, targetImageHeight),
                                                       cv.IPL_DEPTH_8U, 3)
                    cv.SetData(targetImage, targetImageString)
                    convertedImage = cv.CreateImageHeader((targetImageWidth, targetImageHeight),
                                                          cv.IPL_DEPTH_8U, 3)
                    cv.SetData(convertedImage, (chr(0) + chr(0) + chr(0)) * targetImageWidth * targetImageHeight)
                    cv.CvtColor(targetImage, convertedImage, cv.CV_BGR2RGB)
                    cv.SaveImage(targetImagePath, convertedImage)
                if inputType == constants.TAP:
                    fp.write(("    device.tap(targetImagePath=r'{img}', characters='{chars}', maxWaitTime={wait}, " +
                              "dragSearchPermitted={ds})").format(img=targetImagePath,
                                                                  chars=characters_,
                                                                  wait=constants.MAX_DEFAULT_WAIT_TIME_TO_FIND_TARGET,
                                                                  ds=constants.DRAG_SEARCH_PERMITTED))

                elif inputType == constants.LONG_PRESS:
                    fp.write(("    device.longPress(targetImagePath=r'{img}', characters='{chars}', maxWaitTime={wait}, " +
                              "dragSearchPermitted={ds})").format(img=targetImagePath,
                                                                  chars=characters_,
                                                                  wait=constants.MAX_DEFAULT_WAIT_TIME_TO_FIND_TARGET,
                                                                  ds=constants.DRAG_SEARCH_PERMITTED))

                elif inputType == constants.DRAG:
                    str1 = "    device.drag(targetImagePath=r'{img}', dragRightUnits={right}, dragDownUnits={down}, dragStartRegion={start}, characters='{chars}', "
                    str2 = "waitForStabilization={wait})"
                    fp.write((str1 + str2).format(img=targetImagePath,
                                                  right=dragRightUnits,
                                                  down=dragDownUnits,
                                                  start=dragStartRegion,
                                                  chars=characters_,
                                                  wait=waitForImageStabilization))
                elif inputType == constants.KEY_EVENT:
                    fp.write('    # Devices often skip the first few key events. We recommend adding "junk" characters\n')
                    fp.write('    # and then backing them out before entering the real characters you want, like so:\n')
                    fp.write("    # device.keyEvent('aaa', 8, 8, 8, 'chars I want', 13])\n")
                    fp.write("    device.keyEvent([")
                    keycodes_ = []
                    currentString = ''
                    numKeycodes = len(keycodes)
                    for keycodeNumber, keycode in enumerate(keycodes):
                        # Writing the comma is done by the thing preceding the comma.
                        if type(keycode) == str:
                            if currentString != '':
                                fp.write("'{kstr}', ".format(kstr=currentString))
                                currentString = ''
                            fp.write("NEGATIVE_KEYCODES['{kc}']".format(kc=keycode))
                            if keycodeNumber + 1 < numKeycodes:
                                fp.write(", ")    
                            elif keycodeNumber + 1 == numKeycodes:
                                fp.write("])")
                        elif unicodedata.category(unicode(binascii.a2b_hex(hex(keycode)[2:].zfill(2)))) == 'Cc':
                            if currentString != '':
                                fp.write("'{kstr}', ".format(kstr=currentString))
                                currentString = ''
                            fp.write(str(keycode))
                            if keycodeNumber + 1 < numKeycodes:
                                fp.write(", ")
                            elif keycodeNumber + 1 == numKeycodes:
                                fp.write("])")
                        else:
                            currentString += unichr(keycode)
                            if keycodeNumber + 1 == numKeycodes:
                                # This is the last keycode, so finish the string.
                                fp.write("'{kstr}'])".format(kstr=currentString))

                elif inputType == constants.TEXT_TO_VERIFY:
                    fp.write(('    device.verifyText("' + textToVerify + '", maxWaitTime={wait}, ' +
                              'dragSearchPermitted={ds}, isRE=False, maximumAcceptablePercentageDistance=0)').format(wait=constants.MAX_DEFAULT_WAIT_TIME_TO_FIND_TARGET,
                                                                                                                     ds=constants.DRAG_SEARCH_PERMITTED))

                elif inputType == constants.WAIT:
                    fp.write("    device.wait(" + str(wait) + ")")

                fp.write('\n')

#            executeSQL(cur, "INSERT INTO events (session, index_, startTime, inputType, characters, targetImageWidth, targetImageHeight, targetImageString, keycodes, textToVerify, wait, dragStartRegion, dragEndRegion, dragRightUnits, dragDownUnits) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
#                       (sessionPath, index, startTime, inputType, characters, targetImageWidth, targetImageHeight, None if not targetImageString else sqlite3.Binary(targetImageString), None if not keycodes else ' '.join([str(x) for x in keycodes]), textToVerify, wait, None if not dragStartRegion else str(dragStartRegion), None if not dragEndRegion else str(dragEndRegion), dragRightUnits, dragDownUnits))
        except Exception, e:
            bdbg()
            dprint('err')
        conn.commit()
        cur.close()


    def updateInputEvent(self,
                         sessionName=(0,),
                         index=(0,),
                         inputType=(0,),
                         characters=(0,),
                         targetImageWidth=(0,),
                         targetImageHeight=(0,),
                         targetImageString=(0,),
                         keycodes=(0,),
                         textToVerify=(0,),
                         wait=(0,),
                         dragStartRegion=(0,),
                         dragEndRegion=(0,),
                         dragRightUnits=(0,),
                         dragDownUnits=(0,)):
        # XXX It would be better to use None as a value indicating that the parameter should be
        # set to NULL in the DB. 'NULL' cannot be used for string parameters b/c that is a
        # valid string value the user might use. (0,) might be a good default value that allows
        # keywords to be used, as they are now, while also allowing us to use either None
        # to indicate NULL or a value, w/o creating a separate parameter, a la
        # targetImageWidthIsNULL.

        # index is the index in the database, not the index of the event in the dialog.
        conn, cur = establishDBConnection(self.db)
        thingsToChange = []
        setClauseConstituents = []
        bindings = []
        for name, thing in [('inputType', inputType), ('characters', characters), ('targetImageWidth', targetImageWidth), ('targetImageHeight', targetImageHeight), ('targetImageString', targetImageString), ('keycodes', keycodes), ('textToVerify', textToVerify), ('wait', wait), ('dragStartRegion', dragStartRegion), ('dragEndRegion', dragEndRegion), ('dragRightUnits', dragRightUnits), ('dragDownUnits', dragDownUnits)]:
            if thing != (0,):
                setClauseConstituents.append(name + "=?")
                if name in ('dragStartRegion', 'dragEndRegion'):
                    bindings.append(str(thing))
                else:
                    bindings.append(thing)                        

        setClause = ', '.join(setClauseConstituents)
        executeSQL(cur, "UPDATE events SET " + setClause + " WHERE session=? AND index_=?",
                   bindings + [sessionName, index])
        conn.commit()
        cur.close()


    def deleteInputEvent(self,
                         sessionName=None,
                         index=None):
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "DELETE FROM events WHERE session=? AND index_=?",
                    (sessionName, index))
        conn.commit()
        cur.close()
        

    def markSessionPackaged(self, sessionName):
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "UPDATE sessions SET inputEventsProcessed=1 WHERE name=?",
                    (sessionName,))
        conn.commit()
        cur.close()
        

    def isSessionPackaged(self, sessionName):
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT inputEventsProcessed FROM sessions WHERE name=?",
                    (sessionName,))
        processed = cur.fetchone()
        cur.close()
        if processed is None:
            # This is prolly a programmatic error. I know of no use of this method
            # that checks that the session actually exists.
            bdbg()
        return len(processed) == 1 and processed[0] == 1


    def getInputEventsForSession(self, sessionName):
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT serialNo, startTime, inputType, characters, targetImageWidth, targetImageHeight, targetImageString, keycodes, textToVerify, wait, dragStartRegion, dragEndRegion, dragRightUnits, dragDownUnits, index_ FROM events WHERE session=? ORDER BY index_",
                    (sessionName,))
        events = cur.fetchall()
        events_ = []
        for event in events:
            events_.append({})
            if event[7]:
                keycodes_ = event[7].split(' ')
                keycodes = []
                for keycode in keycodes_:
                    if keycode.isdigit():
                        # The keycode is really a scancode.
                        keycodes.append(int(keycode))
                    else:
                        # The keycode is a keycode, such as DPAD_LEFT.
                        keycodes.append(keycode)
            else:
                keycodes = None
            events_[-1]['index'] = event[14]
            events_[-1]['serialNo'] = event[0]
            events_[-1]['startTime'] = event[1]
            events_[-1]['inputType'] = event[2]
            events_[-1]['characters'] = event[3]
            events_[-1]['targetImageWidth'] = event[4]
            events_[-1]['targetImageHeight'] = event[5]
            # targetImageString is converted to a string from a buffer because making a
            # member of such an object in ReplayProcess produces a message that an
            # argument needs to be provided to the buffer.
            events_[-1]['targetImageString'] = str(event[6]) if event[6] else None
            events_[-1]['keycodes'] = keycodes
            events_[-1]['textToVerify'] = event[8]
            events_[-1]['wait'] = event[9]
            events_[-1]['dragStartRegion'] = None if not event[10] else eval(event[10])
            events_[-1]['dragEndRegion'] = None if not event[11] else eval(event[11])
            events_[-1]['dragRightUnits'] = event[12]
            events_[-1]['dragDownUnits'] = event[13]
        cur.close()
        return events_

    
    def close(self):
        assert 'not called' == True


    def startSuitePlayRecording(self, deviceData):
        # deviceData is a tuple of the form:
        # serialNo, width, lcdHeight, chinBarHeight, chinBarImageString, orientation
        traceLogger.debug("startSession()")
        dprint('STARTING startPlayRecording')
        conn, cur = establishDBConnection(self.db)
        # XXX I have not been able to combine the following two SELECTs.
        executeSQL(cur, "SELECT dateTime('now', 'localtime')")
        
        #executeSQL(cur, "SELECT strftime('%s %f', 'now')")
        #seconds = cur.next()[0]
        #executeSQL(cur, "SELECT dateTime('now')")
        # Colons are confused for sth signifying volumes/drives when used on Windows.
        dateTime = cur.next()[0].replace(':', '_')
        #subSeconds = seconds[seconds.rfind('.'):]
        #playStartTimeFine = dateTime + subSeconds
        executeSQL(cur, "INSERT INTO plays (name) VALUES (?)", 
                   (dateTime,))
        for serialNo in deviceData.keys():
            (width, lcdHeight, chinBarHeight, chinBarImageString, orientation, maxADBCommandLength, 
             downText, upText) = deviceData[serialNo]
            # ignoring downText, upText
            executeSQL(cur, ("INSERT INTO perPlayDeviceData (play, serialNo, orientation, chinBarHeight) " +
                         "VALUES (?, ?, ?, ?)"),
                        (dateTime, serialNo, orientation, chinBarHeight))
        conn.commit()
        cur.close()
        dprint('ENDING startPlayRecording')
        return dateTime


    def startTestPlayRecording(self, playName, testName):
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT max(indexInPlayBaseZero) FROM testsInPlays WHERE play=?", 
                   (playName,))
        thing = cur.next()
        if thing != (None,) and len(thing) != 0:
            #bdbg()
            newIndex = thing[0] + 1
        else:
            newIndex = 0
        executeSQL(cur, "INSERT INTO testsInPlays (play, session, indexInPlayBaseZero) VALUES (?, ?, ?)",
                   (playName, testName, newIndex))


    def savePlayClick(self, session, playStartTime, serialNo, clickType, x, y, imageString, targetFound):
        dprint('STARTING savePlayClick')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT strftime('%s %f', 'now')")
        timeWithSubseconds = cur.next()[0]
        executeSQL(cur, "INSERT INTO playClicks (session, play, serialNo, timeWithSubseconds, clickType, x, y, imageString, targetFound) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (session, playStartTime, serialNo, timeWithSubseconds, clickType, x, y, sqlite3.Binary(imageString), targetFound))
        conn.commit()
        cur.close()
        dprint('ENDING savePlayClick')
        

    def saveOCRBoxData(self, session, serialNo, timeWithSubseconds, text):
        # The ProcessedTests entries associated with the old session, including
        # those that are placeholders for the processed results that are yet to
        # be added, are removed, and when the OCRBoxProcess attempts later to
        # update them, it fails but does not generate a foreign key constraint
        # error, which would happen if an INSERT, rather than an UPDATE were
        # tried (b/c the INSERT would cause the SQL 'engine' to look in the
        #       sessions table for the deleted session name).
        conn, cur = establishDBConnection(self.db)
        try:
            executeSQL(cur, "UPDATE processedTests SET textOutput=? WHERE session=? AND serialNo=? AND timeWithSubseconds=?",
                        (text, session, serialNo, timeWithSubseconds))
        except Exception, e:
            # This error can happen when the session has been deleted but the OCRBoxProcess has continued to run.
            dprint('error, prolly not unique key, e:', str(e))
        conn.commit()
        cur.close()
        dprint('ENDING saveOCRBoxData')
        

    def getOCRBoxData(self, session):
        dprint('STARTING getOCRBoxData')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT serialNo, timeWithSubseconds, textOutput FROM processedTests WHERE session=?",
                   (session,))
        textData = cur.fetchall()
        cur.close()
        dprint('ENDING getOCRBoxData')
        return textData


    def getSessionToPostProcess(self):
        dprint('STARTING getSessionToPostProcess')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT clicks.session FROM clicks LEFT JOIN processedTests ON clicks.session=processedTests.session AND clicks.serialNo=processedTests.serialNo AND clicks.timeWithSubseconds=processedTests.timeWithSubseconds WHERE clicks.clickType=? AND processedTests.textOutput IS NULL ORDER BY clicks.timeWithSubseconds LIMIT 1",
                   (constants.LEFT_DOWN_CLICK,))
        session = cur.fetchall()
        dprint("storage.py, session:", session)
        #import traceback
        #traceback.print_stack()
        if len(session) > 0:
            session = session[0][0]
        else:
            session = None
        cur.close()
        dprint('ENDING getSessionToPostProcess')
        return session


    def getAllSessionsToPostProcess(self):
        dprint('STARTING getAllSessionsToPostProcess')
        conn, cur = establishDBConnection(self.db)
        executeSQL(cur, "SELECT clicks.session FROM clicks LEFT JOIN processedTests ON clicks.session=processedTests.session AND clicks.serialNo=processedTests.serialNo AND clicks.timeWithSubseconds=processedTests.timeWithSubseconds WHERE clicks.clickType=? AND processedTests.textOutput IS NULL GROUP BY clicks.session ORDER BY clicks.timeWithSubseconds",
                   (constants.LEFT_DOWN_CLICK,))
        sessions = cur.fetchall()
        cur.close()
        dprint('ENDING getAllSessionsToPostProcess')
        return [session[0] for session in sessions]


    def getUnprocessedEventForSession(self, testPath, deviceData, needTargetImageString=False):
        dprint('STARTING getUnprocessedEventForSession')
        conn, cur = establishDBConnection(self.db)
        startTime = time.time()
        while time.time() < startTime + 60 * 5:
            try:
                executeSQL(cur, "SELECT clicks.serialNo AS serialNo, clicks.timeWithSubseconds AS time, clickType AS type, x, y, targetWidth, targetHeight, imageFilename, 0 AS index_, 0 AS keyEventsSessionID, 0 AS keycode, '' AS text_ FROM clicks LEFT JOIN processedTests ON clicks.session=processedTests.session AND clicks.serialNo=processedTests.serialNo AND clicks.timeWithSubseconds=processedTests.timeWithSubseconds WHERE clicks.clickType=? AND clicks.session=? AND processedTests.textOutput IS NULL ORDER BY time, index_ LIMIT 1",
                           (constants.LEFT_DOWN_CLICK, testPath))
            except Exception, e:
                dprint('getUnProcessed...: ERROR IN GETUNPROCESSEDEVENTFORSESSION. ERROR IN GETUNPROCESSEDEVENTFORSESSION. ERROR IN GETUNPROCESSEDEVENTFORSESSION:')
                dprint('getUnProcessed...: ', str(e))
                dprint('getUnProcessed...: RETRYING')
                cur.close()
                time.sleep(5)
                conn = sqlite3.connect(self.db, timeout=constants.SQLITE_CONNECT_TIMEOUT, isolation_level=None) #'IMMEDIATE')
                conn.text_factory = str
                cur = conn.cursor()
            else:
                break
        try:
            click = cur.next()
        except StopIteration:
            cur.close()
            dprint('ENDING getUnprocessedEventForSession')
            return 

        cur.close()

        serialNo, _, _, x, y, _, _, imageFilename, _, _, _, _ = click
        x = int(x)
        y = int(y)

        testName = os.path.basename(testPath).rsplit('.', 1)[0]
        try:
            image = Image.open(os.path.join('tests', testName, imageFilename))
        except Exception, e:
            dprint("ERROR!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!:", e)
            dprint("path:", os.path.join('tests', testName, imageFilename))
            bdbg()

        screenWidth, totalHeight, chinBarHeight, chinBarImageString, orientation = deviceData[serialNo]
        try:
            lcdImageString = image.tostring()
        except Exception, e:
            dprint("ERROR!1!!!!!!!! EMPTY IMAGE FILE????!!!!!!!!!!!!!!!!!!!!")
            bdbg()

        targetImageString = ""
        if needTargetImageString:
            imageString = lcdImageString + chinBarImageString

            targetImageLeftX = max(x - constants.TARGET_IMAGE_SQUARE_WIDTH / 2 + constants.EVEN_WIDTH_ADDITION, 0)
            # Subtract 1 from the width because the array is 0-based.
            targetImageRightX = min(screenWidth - 1, x + constants.TARGET_IMAGE_SQUARE_WIDTH / 2 + constants.TARGET_IMAGE_SQUARE_WIDTH % 2)
            targetImageWidth = targetImageRightX - targetImageLeftX + 1
            targetImageTopY = max(y - constants.TARGET_IMAGE_SQUARE_WIDTH / 2 + constants.EVEN_HEIGHT_ADDITION, 0)
            # Subtract 1 from the height because the array is 0-based.
            targetImageBottomY = min(totalHeight - 1, y + constants.TARGET_IMAGE_SQUARE_WIDTH / 2 + constants.TARGET_IMAGE_SQUARE_WIDTH % 2)
            targetImageHeight = targetImageBottomY - targetImageTopY + 1

            # get the rows of the target image into an array
            # Northwest zero means bottom is larger than top.
            for rowIndex in range(targetImageTopY, targetImageBottomY + 1):
                leftPixelIndex = rowIndex * screenWidth * constants.NUMBER_OF_IMAGE_CHANNELS + targetImageLeftX * constants.NUMBER_OF_IMAGE_CHANNELS
                # zero-indexed row number * length of row in pixels * number of channels + zero-indexed column number * number of channels
                rightPixelIndex = rowIndex * screenWidth * constants.NUMBER_OF_IMAGE_CHANNELS + targetImageRightX * constants.NUMBER_OF_IMAGE_CHANNELS
                # Adding constants.NUMBER_OF_IMAGE_CHANNELS to add the rightmost pixel.
                imageStringAddition = imageString[leftPixelIndex : rightPixelIndex + constants.NUMBER_OF_IMAGE_CHANNELS]
                targetImageString += imageStringAddition

        if orientation == constants.LANDSCAPE:
            image = image.rotate(90)
            savedScreen_ = image.tostring()
        else:
            savedScreen_ = lcdImageString
        image = cv.CreateImageHeader((screenWidth, totalHeight - chinBarHeight), cv.IPL_DEPTH_8U, 3)
        cv.SetData(image, savedScreen_)

        dprint('ENDING getUnprocessedEventForSession')
        return click[:7] + (targetImageString, image) + click[8:]
