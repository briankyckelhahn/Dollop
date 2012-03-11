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


def distance(s, t):
    # int *d; // pointer to matrix
    # int n; // length of s
    # int m; // length of t
    # int i; // iterates through s
    # int j; // iterates through t
    # char s_i; // ith character of s
    # char t_j; // jth character of t
    # int cost; // cost
    # int result; // result
    # int cell; // contents of target cell
    # int above; // contents of cell immediately above
    # int left; // contents of cell immediately to left
    # int diag; // contents of cell immediately above and to left
    # int sz; // number of cells in matrix

    # Step 1
    cdef int n = len(s)
    cdef int m = len(t)
    if n == 0:
      return m

    if m == 0:
      return n

    # Step 2
    d = []
    # String s has n characters; i here is the row index of the table.
    cdef int i
    for i in range(0, n + 1):
        d.append([i] + [None] * m)

    # String t has m characters; j here is the column index of the table.
    cdef int j
    for j in range(m + 1):
        d[0][j] = j

    # Step 3
    cdef char* s_i
    cdef char* t_j
    cdef int cost, above, left, diag, cell
    for i in range(1, n + 1):
        s_i = s[i-1]
        # Step 4
        for j in range(1, m + 1):
            t_j = t[j-1]

            # Step 5
            if (s_i == t_j):
                cost = 0
            else:
                cost = 1

            # Step 6 
            above = d[i - 1][j]
            left = d[i][j - 1]
            diag = d[i - 1][j - 1]
            cell = min(above + 1, left + 1, diag + cost)
            d[i][j] = cell

    # Step 7
    result = d[n][m]
    return result


def runMuch():
    for i in xrange(1000):
        distance("cat","hat")
