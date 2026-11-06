# Third-party software

StatTracker itself is licensed under the GNU General Public License v3.0 or later (see `LICENSE`).
The release also carries the following software of others.

## CascLib

`CascLib.dll`, which reads the item pictures from the game files of your own WoW installation, is built from
CascLib by Ladislav Zezula: <https://github.com/ladislav-zezula/CascLib>, version 3.0 (commit
`4971d363e665551ac4142f541e5f2d71f1cda653`). The build fetches the source from GitHub at that commit; the
program itself neither builds nor downloads it and calls only its functions for a local installation.

```
The MIT License (MIT)

Copyright (c) 2014 Ladislav Zezula

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## plotly.js

The history pages embed plotly.js 2.27.0, Copyright 2012-2023 Plotly, Inc., MIT license. Its license notice stays in
the header of the embedded file. It is not part of the repository: the build downloads it once and checks it against
a fixed SHA-256.

## The item pictures

The pictures of the items are the property of Blizzard Entertainment. StatTracker does not ship them: it reads them
on your computer from your own installation and keeps them in the `data` folder. A history page that you pass on
contains the pictures it shows; the Character screenshots of the landing page and the READMEs (`docs/images/character-en.png`,
`character-de.png`) show a few of them, made from invented demo data. World of Warcraft is a trademark of Blizzard Entertainment, which is not affiliated
with this project.

## Qt, PyQt6 and the browser engine of the window

The window of the program and the stats page inside it are made with **PyQt6** and **PyQt6-WebEngine** (Python bindings by Riverbank Computing,
version 6.11.0, license GPL v3: <https://www.riverbankcomputing.com/software/pyqt/>). They use **Qt 6** (version 6.11.2), which the release carries
as the Qt libraries of the packages PyQt6-Qt6 and PyQt6-WebEngine-Qt6 under the **GNU Lesser General Public License v3**; the text is in
`LICENSE-LGPL-3.0.txt` in this folder, and the GPL v3 it builds on is the `LICENSE` file of the release. StatTracker is licensed under the GPL v3 or
later, PyQt6 under the GPL v3: the program together with PyQt6 is distributed under the GPL v3. The glue module **sip** (PyQt6-sip 13.13.0) is under
the BSD 2-Clause license.

**Qt WebEngine**, the browser engine that shows the pages in the window, is part of Qt and is based on **Chromium**. Chromium contains components of
others under several licenses (BSD-style and others); Qt describes them at <https://doc.qt.io/qt-6/qtwebengine-licensing.html>.

Source code and replacing the libraries: the Qt libraries are used unmodified, as DLL files in the program folder (`_internal\PyQt6\Qt6\bin`); the build
only leaves out some files (translations, the developer tools of the engine, language packs other than English and German). The source code of
Qt 6.11.2, including Qt WebEngine, is published by The Qt Company at <https://download.qt.io/official_releases/qt/6.11/6.11.2/> (the source of
the single parts in its `submodules` folder). The source of PyQt6 and PyQt6-WebEngine is at <https://pypi.org/project/PyQt6/6.11.0/> and
<https://pypi.org/project/PyQt6-WebEngine/6.11.0/>. Because the libraries are separate files, a changed version of them can be put in their place.

## Other software in the program

- **Python 3.13** (the runtime in the program folder), PSF License: <https://docs.python.org/3/license.html>.
- **PyInstaller** 6.22.3 makes the program file; its loader (bootloader) is part of `StatTracker.exe`: GPL v2 or later with the exception that allows
  the program built with it to be distributed under its own license: <https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt>.
- **openpyxl** 3.1.5 and **et_xmlfile** 2.0.0 write the Excel file. MIT license, Copyright (c) 2010 openpyxl:

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
