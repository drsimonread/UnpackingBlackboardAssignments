# Unpack Submissions: User Manual for Windows

Unpack Submissions turns the gradebook ZIP files you download from Blackboard into tidy folders: one per assignment, with each student's work named after their username. Source code is kept under its original name in a folder per student, so you can compile and run it as submitted. Documents, images, audio and video get PDF, JPEG, MP3 or MP4 copies you can open anywhere (plain-text files such as `.txt`, `.md` and `.csv` are kept as they are), and compiled files (`.class`, `.exe` and the like) are thrown away.

You don't need to install anything first. The script checks what it needs and helps you get it.

## Two extra programs

Most files are converted by the script itself, but two kinds need a separate program:

| Files | Program needed for the PDF, MP3 or MP4 copy |
|---|---|
| Word, Excel and PowerPoint (`.docx`, `.xlsx`, `.pptx` and older `.doc`, `.xls`, `.ppt`), OpenDocument, RTF, Pages, Numbers and Keynote | LibreOffice |
| Audio and video (`.wav`, `.m4a`, `.mov`, `.webm` and the like) | ffmpeg |

You don't need to install either in advance. The first time a batch contains such files, the script offers to download the program it needs (see below).

## What you get

Put these files together in one folder:

- `unpack-submissions.cmd` (the file you run)
- `unpack-submissions.ps1`
- `unpack-submissions.py`

## Before you start (once only)

Windows marks files that came from the internet. To stop it asking about these scripts every time:

1. Right-click the ZIP file the scripts came in and choose Properties.
2. Tick "Unblock" at the bottom of the General tab and click OK.
3. Right-click the ZIP file again, choose "Extract All..." and click Extract.

## Unpacking a batch of submissions

1. Download the assignment ZIP files from Blackboard and move them into the folder with the scripts.
2. Open that folder in File Explorer.
3. Click in the address bar at the top, type `cmd` and press Enter. A Command Prompt window opens in that folder.
4. Type the following and press Enter:

   ```
   unpack-submissions.cmd gradebook_*.zip -o Grading
   ```

5. Answer any questions (see below).
6. When it has finished, open the `Grading` folder.

## Questions it may ask

- **Python is missing.** The script needs Python 3. If this computer has `winget`, it offers to install Python for you; type `Y` and press Enter. If not, it gives step-by-step instructions. Either way, close the window afterwards, open a new one and start again.
- **ffmpeg is missing.** This is asked only when a batch contains audio or video. Type `Y` to download it (about 150 MB). It goes into a `Tools` folder beside the scripts and needs no administrator rights.
- **LibreOffice is missing.** This is asked only when a batch contains Word, Excel, PowerPoint or similar files, which can't be converted without it. Type `Y` to download it (about 350 MB) into the same `Tools` folder.

If you answer `N`, the script prints instructions for installing that program yourself and carries on. Those files are still saved, but without a PDF or MP3/MP4 copy: Word, Excel and PowerPoint files in particular stay as originals only.

## What is in each assignment folder

| Item | What it is |
|---|---|
| `jdoe` (a folder) | jdoe's source code, under its original file names |
| `jdoe.docx`, `jdoe.mov` | jdoe's other files, renamed after the username |
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
unpack-submissions.cmd --remove-converters
```

This deletes the `Tools` folder and the script's private copy of the Python libraries. It doesn't touch programs installed on the computer in the usual way, or the folders of submissions you've made. Anything needed later is downloaded again.

## If something goes wrong

- **A security warning** when you run the script: click Run, or unblock the ZIP as described above so it stops appearing.
- **"already exists"**: an earlier run left that assignment folder. Add `--force` to replace it, or choose a different `-o` folder.
- **A download fails**: check your internet connection and run the script again. On a college network that blocks downloads, use the instructions the script prints.

---

Written by Simon Read with Claude Opus 5.5 (Anthropic).
