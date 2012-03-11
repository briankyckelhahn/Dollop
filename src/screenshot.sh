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


adb pull /dev/graphics/fb0 fb0
#dd bs=1920 count=800 if=fb0 of=fb0b
# The -f image2 in the example in stackoverflow f/ the output is unnecessary.
ffmpeg -vframes 1 -vcodec rawvideo -f rawvideo -pix_fmt rgb32 -s 480x854 -i fb0 -vcodec png fb0.png
convert fb0.png -background white -flatten +matte fb0.flat.png
