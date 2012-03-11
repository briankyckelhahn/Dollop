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


(ESCAPE, CONVERT) = range(2)

# To avoid the possibility of overwriting a needed Unicode code point,
# make the device keys the negative of their actual values.
CHIN_HOME = -3
CHIN_BACK = -4
CHIN_MENU = -82
CHIN_SEARCH = -84
