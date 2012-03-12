<h1>License and Copyright Information</h1>
This project was created and is maintained by <a
href="briankyckelhahn.com">Brian Kyckelhahn</a>, an independent mobile
app developer in Austin, Texas. You are welcome to contribute to it,
and you will be acknowledged in the contributors file for doing so,
but you surrender your copyright to Brian when you make contributions.

This project is licensed under a Creative Commons Attribution-NoDerivs
3.0 Unported license. That means that you cannot distribute changes
you make to this project. You are also prohibited from distributing
the binaries, bytecodes, and other derivatives of code that has been
changed. However, if you make changes to this project in the course of
working at a company and want to distribute those changes to your
co-workers at that company so that they can use those changes in the
course of their work at that company, Brian has no intention of
sicking lawyers on you for doing so.


<h1>Installation and Running</h1>
<h2>Pre-requisites</h2>
<p>Dollop runs on Windows. With at most a few hours of effort, it should be possible to edit the code to run on Linux. It was originally written for, and ran well on, Linux and was then ported to Windows.</p>

<p>Install the Android SDK. <span class="important">You might want to experiment with the version of the SDK that you use. I have seen good results with version 12, which is available for Windows via an <a href="http://dl.google.com/android/installer_r12-windows.exe">installer</a> or as a <a href="http://dl.google.com/android/android-sdk_r12-windows.zip">zip file</a>.</span> Later versions have sometimes been sluggish while handling the multiple simultaneous requests that the tool makes. You can install multiple SDKs on a single computer without any conflict. Go to Edit > Configuration after launching the tool and specify the full path to adb in the SDK of your choice. The components the tool uses from the SDK include adb, which is in the platform-tools folder, and monkeyrunner.bat, which is in the tools folder.</p>

<p>Install <a href="http://www.wxpython.org/download.php#stable">wxPython</a>, <a href="http://opencv.willowgarage.com/wiki/InstallGuide">OpenCV</a>.</p>

<h2>Installation</h2>

<p>The tool requires very little configuration. If Android Debug Bridge (adb) is not on your system path, point to it in the field provided within the tool at Edit > Configuration > System. If your device has a custom keycode mapping, you can edit the default one at Edit > Configuration > Device. The tool communicates with your device using adb over USB. Nothing needs to be installed on your device. So that adb can communicate with it, however, you'll need to enable USB debugging on your device; try something similar to this navigation sequence on your device: Settings > Applications > Development and enable "USB Debugging". Also, open the "USB Connection" dialog from the notification bar and select "PC Mode" or something similar.</p>

## To Run
To run the tool:<br/>
    <tt>cd Dollop/src</tt><br/>
    <tt>python gui.py</tt><br/>


<h2 id="recording">Recording &nbsp; and &nbsp; Playing &nbsp; Tests</h2>
<div class="instructions">
<ol class="instructions">
<li>With your device already connected by USB to the workstation on which the Dollop Test Tool is installed, start the tool. If you have not already done so, the tool will ask you to tap or tap-and-hold (i.e. long press) on different 

corners of the screen. It will also ask you point it to the monkeyrunner.bat file of the Android SDK.</li>
<li>Press the record button, the one with the red circle on it. While you're recording, this button will stay depressed until you press it again to stop recording.</li>
<li>A dialog will appear, asking you to provide a name and location for the Python test module that will be automatically created by the tool.</li>
<li>After finishing with the dialog, you have begun recording the test. Interact with your phone or tablet through the tool to create test events, which include taps, drags, long presses, text verification, waits, and text and keycode 

entries. Here is how to create each of these events:</li>
<ul class="indent">
<li>Tap: to tap on something, click your cursor within the device image. A bitmap centered on your cursor point (of maximum size 60 pixels square) will be used as the tap target when the test is played back. If the target image or a 

similar one is found during playback, that image will be tapped. If there is text near the cursor when the test is being recorded, it may be identified and the tool will look for it during playback. If the target image and associated 

text, if any, is not found during playback, the test fails.</li>
<li>Drag: dragging is similar to tapping. However, during playback, if the target image is not found, the tool will still play the drag back, with the point of initial drag contact being in the same general region as the original touch. 

Unlike taps, the test will not fail if the image around the original drag touch cannot be found.</li>
<li>Type: click near the device screen image to be sure that that GUI window is active, and then begin typing with your keyboard. There will be a small delay as the tool buffers input. adb sometimes skips the first few characters in 

input, so it's best to type some characters, then delete them with backspace, and then type the text you want to send.</li>
<li>Send keycodes: use the drop down list to choose the keycode you want to send, and then press the 'Send' button.</li>
<li>Verify text: to verify that particular text appears somewhere in the screen, use the text field at left. Note that the third-party OCR software the tool uses is not very accurate, though you can edit the test script to specify that 

the text match does not have to be perfect. See the <a href=/api.html#verifyText>API</a> for details regarding text verification.</li>
<li>Wait: to insert a point in the test being recorded where the tool will wait before continuing, use the provided text field.</li>
</ul>
<li>Un-press the 'Record' button to stop recording.</li>
<li>To improve the tool's responsiveness during recording, the test is not completely created during recording. Go to Test > Load Test and load the test you just finished recording. This will process the test and make it available for 

running. Simple tests are processed in a few seconds; very large tests may require a few minutes.</li>
<li>Open the Python processed test module in a text editor. The tool makes choices for method parameters that you can override; see the <a href="/api.html">API</a>. Ensure that any text the OCR software found near your taps and drags is 

correct. The OCR software will usually produce the same text for similar input images, so you may want to rely on the image alone if the text found is not what you want.</li>
<li>You can continue to modify the Python test module in any way you like. Add control structures such as for loops, add new routines, import modules, etc.</li>
</ol>


<h1>API</h1>
<p>The tool automatically converts your interaction with your device into a test script in the form of a Python module. It is not necessary to learn the API presented here to use the tool, but it is documented here for those that want to edit test scripts.</p>
<dl class="method">
			    <dt>device.tap(<em>targetImagePath</em>="", <em>characters</em>=None, <em>chinBarImagePath</em>=None, <em>maxWaitTime</em>=11, <em>dragSearchPermitted</em>=True)</dt>
			    <dd>
			      <p>Searches the device screen image, which is constantly being retrieved from the device during playback, for an image within it matching that at <tt>targetImagePath</tt> and containing <tt>characters</tt> 

(if <tt>characters</tt> is provided). This method appends the image of the chin bar (which is created by the tool by default) if it is provided to the device screen image create the image that the tool searches. A chin bar is an 

extension of the LCD that does not display pixels, but does display icons for actions, such as those for Menu, Home, Back, and Search. Most phones do not have chin bars; the <a href="http://en.wikipedia.org/wiki/Droid_2">Droid 2</a> is 

an example of one that does. If the image is found, the tool taps it in its center. If it is not found, a drag search is conducted, which involves attempting to drag the screen forward, and, later, back, to search for the image. (If a 

drag upward was performed before this tap, forward, here, means up, otherwise it means down; the drag search continues the motion of any preceding drag.) <tt>maxWaitTime</tt> is the number of seconds that the tool will search for the 

target image before conducting a drag search or indicating failure.</p>
			  </dd></dl>

<dl class="method">
			  <dd>
			    <dt>device.longPress(<em>targetImagePath</em>="", <em>characters</em>=None, <em>chinBarImagePath</em>=None, <em>maxWaitTime</em>=11, <em>dragSearchPermitted</em>=True)</dt>
			    <dd>This method is just like tap(), though it presses on the target, if found, for long enough to cause the device to interpret the press as a long press, rather than a tap. As you may know, a long press often 

causes the device to respond differently than it would to a tap, such as by popping up a menu, rather than launching an application.
			  </dd></dl>

<dl class="method">
			    <dt>device.drag(<em>targetImagePath</em>=None, <em>dragRightUnits</em>=None, <em>dragDownUnits</em>=None, <em>dragStartRegion</em>=None, <em>characters</em>=None, <em>waitForStabilization</em>=False)</dt>
			  <dd>
			  <p>drag is like tap() in that it searches the device screen image for the smaller, target image and characters, if provided, but it will proceed with the drag even if the target is not found. For this method, 

the screen is conceptually divided into 9 sections, with three divisions across and three vertically. <tt>dragStartRegion</tt> is represented as a binary tuple, the first element being an integer representing the (1-based) index of the 

column in this conceptual matrix, and with the second being the integer representing the index of the row. In other words, <tt>dragStartRegion</tt> is (x, y), with the coordinate system centered at the upper left corner of the screen, 

and with x increasing to the right and y increasing <em>down</em>. Downward-increasing y is a convention often used in the image processing field. For example, (1, 3) represents the section of your screen taking about 1/9<sup>th</sup> 

the total screen area and located in the bottom left corner of the screen.</p>
			  </dd></dl>

<dl class="method">
			    <dt>device.keyEvent(<em>keycodes</em>)</dt>
			    <dd>
			      <p>This method sends key events to the device. You could conceive of three types of key events that can be sent: printing characters, such as 'a', non-printing characters, such as the return command, and 

special device keycodes, such as HOME, which tells the device to go the home screen. For this method, printing characters are placed in quotes, non-printing characters are represented by their ASCII code, and special device keycodes are 

specified using the <tt>NEGATIVE_KEYCODES</tt> dictionary that is written to every test script by the tool. Note that we recommend sending three garbage characters and then immediately removing them with backspace to counteract the 

problem that many devices (or perhaps adb) have of ignoring the first characters sent to it after a period of inactivity. For example, to send the string hello to your device and press enter and then navigate the device to the home 

screen, do the following:</p>
			      <p><tt>device.keyEvent(['aaa', 8, 8, 8, 'hello', 13, NEGATIVE_KEYCODES['HOME']])</tt></p>
			      <p>Here, 'aaa' represents the garbage characters, 8 is the ASCII code for backspace, and 13 is the ASCII code for return.</p>
			      <p>These commands are sent in sequence as fast as adb and the device allow.</p>
			  </dd></dl>

<dl class="method" id="verifyText">
			    <dt>device.verifyText(<em>textToVerify</em>, <em>maxWaitTime</em>=11, <em>dragSearchPermitted</em>=True, <em>isRE</em>=False, <em>maximumAcceptablePercentageDistance</em>=0)</dt>
			    <dd>
			    <p>This method searches the entire device screen image for <tt>textToVerify</tt>, which is a literal string if <tt>isRE</tt> is False, or a string specifying a regular expression if <tt>isRE</tt> is True. 

Characters are produced from the device screen image using optical character recognition (OCR). Because the OCR software used is frequently off by some amount, <tt>maximumAcceptablePercentageDistance</tt> is provided to allow you to 

specify the accuracy you require. If <tt>maximumAcceptablePercentageDistance</tt> is 0, the OCR software must find a string matching <tt>textToVerify</tt> exactly. Otherwise, <tt>maximumAcceptablePercentageDistance</tt> specifies the 

maximum <a href="http://en.wikipedia.org/wiki/Levenshtein_distance">Levenshtein distance</a> between any string found by OCR and <tt>textToVerify</tt>. When <tt>dragSearchPermitted</tt> is True, the tool drags to find 

<tt>textToVerify</tt> just as it does in tap().</p>
			    </dd>
			  </dl>

<dl class="method">
			    <dt>device.wait(<em>seconds</em>)</dt>
			    <dd>
			      <p>This method calls <tt>time.sleep(seconds)</tt>.</p>
			  </dd></dl>
