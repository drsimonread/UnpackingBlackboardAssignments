# Unpack Submissions: What It Does

Unpack Submissions is a small program for instructors who download student work from Blackboard. Blackboard's "download all" gives you one ZIP file per assignment, full of files with long, mangled names. Unpack Submissions turns those ZIP files into folders you can actually grade from.

For each assignment it:

- makes one folder, named after the assignment;
- renames every file after the student's username (`jdoe.docx`, `jdoe.pdf`), numbering several files of the same type in the order they were submitted;
- keeps source code under its original names in a folder per student (`jdoe/Temperature.java`), so you can compile and run it as submitted;
- unpacks ZIP and JAR files that students submitted, keeping their source code and throwing away compiled files (`.class`, `.exe`, `.o` and the like);
- gives Word, Excel, PowerPoint, Pages and image files a PDF or JPEG copy, and audio and video an MP3 or MP4 copy, so everything opens on any computer;
- fixes files whose names don't match what they really are (an "`essay.doc.pdf`" that is really a PDF becomes `jdoe.pdf`);
- keeps Blackboard's receipts, and any text a student typed into the submission, alongside the work;
- writes a list of every original file name and what became of it.

It runs on Windows, macOS and Linux. You don't need to install anything first: the script sets up what it needs, and downloads the converters it uses (ffmpeg and LibreOffice) only when a batch of submissions needs them, after asking. When you've finished for the semester, one command removes everything it downloaded.

## Warning

This program was "vibe-coded": it was written by an AI assistant (Claude) in conversation, and nobody has reviewed its code line by line. It has been checked only by testing, on real Blackboard downloads from one course and on made-up test cases. The automatic downloads of ffmpeg and LibreOffice have been tested on Linux but not yet on Windows or macOS. Use it at your own risk:

- keep the original ZIP files from Blackboard until you have checked the results;
- look at `manifest.csv` to see what happened to every file, including anything it removed;
- grade from the student's original file, not the converted copy, when anything looks wrong.

## Download and install

You need an internet connection the first time you run it. Nothing else has to be installed in advance.

1. Download [unpack-submissions-1.0.zip](https://github.com/drsimonread/UnpackingBlackboardAssignments/raw/main/Downloads/unpack-submissions-1.0.zip). (It is also attached to the [version 1.0 release](https://github.com/drsimonread/UnpackingBlackboardAssignments/releases/tag/v1.0).)
2. On Windows only: right-click the downloaded file, choose Properties, tick "Unblock" and click OK.
3. Unzip it: double-click it on a Mac, or right-click it and choose "Extract All..." on Windows or "Extract Here" on Linux. You get a folder called `UnpackSubmissions`.
4. Open the user manual for your computer in that folder (`user-manual-windows.pdf`, `user-manual-macos.pdf` or `user-manual-linux.pdf`) and follow "Unpacking a batch of submissions".

The manuals are also online: [Windows](https://github.com/drsimonread/UnpackingBlackboardAssignments/blob/main/Manuals/user-manual-windows.md), [macOS](https://github.com/drsimonread/UnpackingBlackboardAssignments/blob/main/Manuals/user-manual-macos.md) and [Linux](https://github.com/drsimonread/UnpackingBlackboardAssignments/blob/main/Manuals/user-manual-linux.md).

## Licence

Unpack Submissions is free software under the MIT licence; see [LICENSE](https://github.com/drsimonread/UnpackingBlackboardAssignments/blob/main/LICENSE).

---

Written by Simon Read with Claude Opus 5.5 (Anthropic).
