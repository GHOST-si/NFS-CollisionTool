NFS CollisionTool
=================


NFS CollisionTool is a tool for viewing and editing vehicle collision bounds
from an extracted .bin file. Open a file and the bounds are shown in an
interactive 3D view, where you can add, remove, rotate, move and resize boxes
and spheres, then save the changes back into the same binary file.


FEATURES
--------

- Interactive 3D view of the collision bounds (drag to rotate, scroll to zoom)
- Tree view with parent/child hierarchy, per-bound color swatches, collapsible
  groups and child counts
- Click a bound to pin/resize it, or click its name to edit its fields
  (Position, HalfDimension, Orientation, etc.)
- Import an .obj model as a visual reference for the car body
- Add or delete bounds (right-click in the tree) and edit collision clouds and
  their vertices. Deleting a bound also deletes its children
- Edit BoundType flags. The Resolve panel detects and fixes broken child
  ranges and cloud references
- SurfaceName dropdown. Known hashes can be added in Engine\SurfaceNames.txt,
  custom hashes are supported too
- Saves edits back into the .bin file (structural changes re-serialise the
  chunk)
- Undo/Redo (Ctrl+Z / Ctrl+Y), save with Ctrl+S, Reload
- Body/Model frame display modes (preview only), axis gizmo to snap the view
- Show/hide individual meshes of the imported model
- Supports both Binarius and Binary .bin files
- Supports NFS Most Wanted and NFS Carbon (experimental) collision formats


REQUIREMENTS
------------

- Windows 10 or 11 (64-bit)
- .NET 8 Desktop Runtime (x64)
  https://dotnet.microsoft.com/download/dotnet/8.0
- WebView2 Runtime (already installed on most up-to-date Windows 10/11
  machines)
  https://developer.microsoft.com/microsoft-edge/webview2/


USAGE
-----

1. Extract the zip and run "NFS CollisionTool.exe".
2. Click "Import Collision" and pick the vehicle's .bin file (the one
   extracted with Binary/Binarius). You can try the files in the Samples
   folder as examples.
3. Check the bounds in the 3D view. Click a dot or a name to edit a bound.
4. Optionally use "Import Model" to load an .obj as a visual reference
   (CarToolkit by nfsu360 can extract car models to .obj).
5. Use "Reload" if the file was changed elsewhere.
6. Saving overwrites the original file, so always keep a backup.

Windows SmartScreen may show a warning the first time, because the app is
not code-signed. Click "More info", then "Run anyway".


WHY SOME NUMBERS DON'T MATCH THE RAW BINARY/BINARIUS
----------------------------------------------------

Position, HalfDimension and Pivot are stored as int16 in the file and have to
be divided to get the real value. This tool divides by 1000 (raw/1000.0),
because that's the scale the game (Most Wanted) itself actually uses, checked
against the game's own decompiled source. Some other tools use a scale of 1024
instead, so the same file shows values about 2.4% off from what you see here.
The values shown in this tool are the ones the game actually reads.

Orientation is a real compressed quaternion (x, y, z, w), each stored as int16
divided by 32767. Some tools instead treat X/Y/Z as a rotation axis and W as
an angle in degrees (raw*180/32768); this tool reads all four values on the
same scale, as an actual quaternion. If you looked at this file somewhere that
uses the other convention, the numbers or the displayed orientation won't
match what you see here.

Values beyond +/-32.767 (+/-1 for orientation) can't be stored and get
clamped. Radius is a float in Most Wanted (spheres follow it) but a hash in
Carbon, so sphere editing differs slightly between the two. The tool detects
this automatically.

This tool is meant for the vehicle collision chunk, not world/track collision.


USEFUL LINKS
------------

- Binarius: https://github.com/nlgxzef/Binarius/releases
- NFS CarToolkit: https://nfs-tools.blogspot.com/p/downloads.html


CREDITS
-------

Thanks to everyone involved in the NFS: Most Wanted decompilation project
(https://github.com/dbalatoni13/nfsmw) for making the source code available,
and to everyone who worked on Binary/Binarius and the Nikki/Darius libraries.
Thanks to the NFS community for sharing information and research, and to
everyone who helped with testing.

If you come across any bugs, inconsistencies or unexpected behavior, feel free
to open an issue on the project's GitHub page.

An LLM was used to accelerate the UI/core integration and as a research aid.


DISCLAIMER
----------

This is an unofficial, fan-made tool. It is not affiliated with, endorsed by
or sponsored by Electronic Arts Inc. or any of its subsidiaries. Need for
Speed, Most Wanted and Carbon are trademarks of Electronic Arts Inc. No game
files or game code are included. The tool is provided as is, without warranty.


LICENSE
-------

Released under the MIT License with the Commons Clause (see the LICENSE
file). You can use, modify and share the code, but the copyright notice and
license text have to stay in every copy, and selling it is not allowed.
Third-party components are listed in THIRD-PARTY-NOTICES.md.


SUPPORT
-------

Donations are always appreciated! If you'd like to support the project,
you'll find the wallet addresses in the project's GitHub README.
