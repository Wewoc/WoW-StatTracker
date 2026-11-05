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
