# Unpack Submissions: User Manual for macOS

Unpack Submissions turns the gradebook ZIP files you download from Blackboard into tidy folders: one per assignment, with each student's work named after their username. Source code is kept under its original name in a folder per student, so you can compile and run it as submitted. Documents, images, audio and video get PDF, JPEG, MP3 or MP4 copies you can open anywhere (plain-text files such as `.txt`, `.md` and `.csv` are kept as they are), and compiled files (`.class`, `.o` and the like) are thrown away.

You don't need to install anything first (Homebrew included). The script checks what it needs and helps you get it.

## Two extra programs

Most files are converted by the script itself, but two kinds need a separate program:

| Files | Program needed for the PDF, MP3 or MP4 copy |
|---|---|
| Word, Excel and PowerPoint (`.docx`, `.xlsx`, `.pptx` and older `.doc`, `.xls`, `.ppt`), OpenDocument, RTF, Pages, Numbers and Keynote | LibreOffice |
| Audio and video (`.wav`, `.m4a`, `.mov`, `.webm` and the like) | ffmpeg |

You don't need to install either in advance. The first time a batch contains such files, the script offers to download the program it needs (see below).

## What you get

Put these files together in one folder:

- `unpack-submissions.sh` (the file you run)
- `unpack-submissions.py`

## Unpacking a batch of submissions

1. Download the assignment ZIP files from Blackboard and move them into the folder with the scripts.
2. Open Terminal (in Applications > Utilities).
3. Type `cd` followed by a space, drag the folder from the Finder onto the Terminal window, and press Return.
4. Type the following and press Return:

   ```
   bash unpack-submissions.sh gradebook_*.zip -o Grading
   ```

5. Answer any questions (see below).
6. When it has finished, type `open Grading` and press Return to see the results in the Finder.

## Questions it may ask

- **Python is missing.** The script needs Python 3. It offers to start installing Apple's command line tools, which include Python; type `Y`, press Return and follow the window that appears. It also gives step-by-step instructions for installing Python from python.org instead. Afterwards, run the script again.
- **ffmpeg is missing.** This is asked only when a batch contains audio or video. Type `Y` to download it (about 150 MB). It goes into a `Tools` folder beside the scripts and needs no password.
- **LibreOffice is missing.** This is asked only when a batch contains Word, Excel, PowerPoint, Pages, Numbers, Keynote or similar files, which can't be converted without it. Type `Y` to download it (about 350 MB) into the same `Tools` folder.

If you answer `N`, the script prints instructions for installing that program yourself and carries on. Those files are still saved, but without a PDF or MP3/MP4 copy: Word, Excel and PowerPoint files in particular stay as originals only. Pages, Numbers and Keynote files still get the preview picture stored inside them.

## What is in each assignment folder

| Item | What it is |
|---|---|
| `jdoe` (a folder) | jdoe's source code, under its original file names |
| `jdoe.pages`, `jdoe.mov` | jdoe's other files, renamed after the username |
| `jdoe-00.docx`, `jdoe-01.docx` | several files of the same type, in the order submitted |
| `jdoe.pdf`, `jdoe.mp4` | converted copies, for reading or playing; called `jdoe-docx.pdf` and so on only when two files would otherwise share a name |
| `Receipts` | Blackboard's receipt for each attempt |
| `manifest.csv` | every original file name, what it became and what was removed |

## Options

| Option | What it does |
|---|---|
| `-o FOLDER` | where to put the assignment folders (normally the current folder) |
| `--force` | replace assignment folders left over from an earlier run |
| `--download yes` | download any missing converter without asking |
| `--download no` | never download; just give instructions |
| `--instructions` | show how to install ffmpeg and LibreOffice by hand |
| `--remove-converters` | delete everything the scripts downloaded (see below) |
| `--help` | list every option |

## When you have finished

When you've unpacked all your submissions, free up the space the converters use (several hundred megabytes):

```
bash unpack-submissions.sh --remove-converters
```

This deletes the `Tools` folder and the script's private copy of the Python libraries. It doesn't touch programs in your Applications folder, or the folders of submissions you've made. Anything needed later is downloaded again.

## If something goes wrong

- **"already exists"**: an earlier run left that assignment folder. Add `--force` to replace it, or choose a different `-o` folder.
- **"cannot be opened because the developer cannot be verified"** for ffmpeg you installed by hand: run the script again, as it clears that flag for files in its `Tools` folder.
- **A download fails**: check your internet connection and run the script again. On a college network that blocks downloads, use the instructions the script prints.

---

Written by Simon Read with Claude Opus 5.5 (Anthropic).
