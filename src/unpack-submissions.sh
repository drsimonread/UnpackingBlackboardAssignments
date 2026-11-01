#!/usr/bin/env bash
# Run unpack-submissions.py on macOS or Linux, setting up everything it needs.
#
# Usage: ./unpack-submissions.sh GRADEBOOK.zip [GRADEBOOK.zip ...] [-o OUTPUT_DIR] [--force]
#        ./unpack-submissions.sh --help
#
# All arguments are passed straight through to unpack-submissions.py.
# (On Windows use unpack-submissions.cmd instead.)
#
# Before starting the program it makes sure of two things:
#   1. Python 3.8 or later. If it is missing, it explains how to install it
#      on this computer and offers to do it for you where that is possible.
#   2. A private Python environment (.venv, next to this script) holding
#      Pillow, reportlab and certifi; created on the first run.
# The converters, ffmpeg (audio and video) and LibreOffice (Word, Pages and
# other documents), are fetched by the program only when a submission needs
# them: it asks first, downloads them into the Tools folder next to this
# script (no administrator password needed), and if you say no it prints
# step-by-step instructions for installing them yourself.
#
# When you have unpacked all your submissions:
#   ./unpack-submissions.sh --remove-converters
# deletes the Tools folder and the Python environment (everything these
# scripts downloaded). Programs installed on the computer itself are untouched.
#
# Settings (environment variables):
#   UNPACK_INSTALL=yes   install whatever is missing without asking
#   UNPACK_INSTALL=no    never offer to install anything
#   UNPACK_VENV=DIR      keep the Python environment in DIR instead of .venv
#
# Written with Claude Opus 5.5 (Anthropic).

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
program="$script_dir/unpack-submissions.py"
venv="${UNPACK_VENV:-$script_dir/.venv}"
tools="$script_dir/Tools"
packages="pillow reportlab certifi"
optional="pillow-heif"            # iPhone photos; skipped if it will not install
marker="$venv/.installed"
install_mode="${UNPACK_INSTALL:-ask}"

say() { printf '%s\n' "$*" >&2; }

# Ask a yes/no question (default yes). Answers "no" when nobody is there to ask.
ask() {
    case "$install_mode" in
        yes) return 0 ;;
        no)  return 1 ;;
    esac
    [ -t 0 ] || return 1
    local reply
    printf '%s [Y/n] ' "$1" >&2
    read -r reply || return 1
    case "$reply" in [Nn]*) return 1 ;; *) return 0 ;; esac
}

if [ ! -f "$program" ]; then
    say "error: $program not found (keep the scripts together in one folder)"
    exit 1
fi

# --------------------------------------------------------------------------
# Removing the downloaded converters (done here, not in Python, because the
# Python environment itself is removed too)
# --------------------------------------------------------------------------
for arg in "$@"; do
    if [ "$arg" = "--remove-converters" ]; then
        removed=0
        for d in "$tools" "$venv"; do
            if [ -e "$d" ]; then
                size="$(du -sh "$d" 2>/dev/null | cut -f1)"
                rm -rf "$d"
                say "Removed $d ($size)"
                removed=1
            fi
        done
        [ "$removed" = 1 ] || say "Nothing to remove: no converters were downloaded."
        say "Anything still needed is downloaded again next time."
        exit 0
    fi
done

# --------------------------------------------------------------------------
# Which computer is this?
# --------------------------------------------------------------------------
os="$(uname -s)"
distro="other"
case "$os" in
    Darwin)
        os_name="macOS"
        ;;
    Linux)
        os_name="Linux"
        if [ -r /etc/os-release ]; then
            # shellcheck disable=SC1091
            . /etc/os-release
            os_name="${PRETTY_NAME:-Linux}"
            ids=" ${ID:-} ${ID_LIKE:-} "
            if [ "${ID:-}" = "fedora" ]; then
                distro="fedora"
            else
                case "$ids" in
                    *" rhel "*|*" centos "*|*" rocky "*|*" almalinux "*) distro="rhel" ;;
                    *" debian "*|*" ubuntu "*) distro="debian" ;;
                esac
            fi
        fi
        ;;
    MINGW*|MSYS*|CYGWIN*)
        say "This is Windows: please run unpack-submissions.cmd instead"
        say "(double-click it, or type its name in Command Prompt or PowerShell)."
        exit 1
        ;;
    *)
        os_name="$os"
        ;;
esac

run_as_admin() {
    # Run a command with sudo, saying exactly what it is first.
    say "Running: sudo $*"
    sudo "$@"
}

# --------------------------------------------------------------------------
# 1. Python
# --------------------------------------------------------------------------
python_ok() {
    "$1" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1
}

find_python() {
    local candidate
    for candidate in python3 python \
            /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
            /usr/local/bin/python3 /opt/homebrew/bin/python3; do
        command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ] || continue
        candidate="$(command -v "$candidate" 2>/dev/null || echo "$candidate")"
        # On a Mac without Apple's command line tools, /usr/bin/python3 is only
        # a stub that pops up an installer: skip it rather than set that off.
        if [ "$os" = "Darwin" ] && [ "$candidate" = "/usr/bin/python3" ] &&
           ! xcode-select -p >/dev/null 2>&1; then
            continue
        fi
        if python_ok "$candidate"; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

python_help() {
    say ""
    say "Python 3 (version 3.8 or later) is needed and was not found on $os_name."
    say ""
    case "$os:$distro" in
        Darwin:*)
            say "To install it:"
            say "1. Open https://www.python.org/downloads/ in Safari."
            say '2. Click the yellow "Download Python 3..." button.'
            say "3. Open the downloaded .pkg file from your Downloads folder."
            say "4. Click Continue on each screen, then Install, and enter your"
            say "   Mac password when asked."
            say '5. When it finishes, a Finder window opens: double-click'
            say '   "Install Certificates.command" in it.'
            say "6. Open a new Terminal window and run this script again."
            say ""
            say "(Apple's own Python also works: it comes with the command line"
            say "developer tools, which this script can start installing for you.)"
            ;;
        Linux:debian)
            say "To install it:"
            say "1. Open a terminal."
            say "2. Type:  sudo apt update"
            say "3. Type:  sudo apt install python3 python3-venv"
            say "4. Run this script again."
            ;;
        Linux:fedora|Linux:rhel)
            say "To install it:"
            say "1. Open a terminal."
            say "2. Type:  sudo dnf install python3"
            say "3. Run this script again."
            ;;
        *)
            say "Install Python 3 from https://www.python.org/downloads/ or your"
            say "system's package manager, then run this script again."
            ;;
    esac
    say ""
}

python=""
if ! python="$(find_python)"; then
    python_help
    case "$os:$distro" in
        Darwin:*)
            if ask "Start installing Apple's command line tools (which include Python) now?"; then
                xcode-select --install || true
                say "Follow the window that opens. When it has finished, run this script again."
            fi
            exit 1
            ;;
        Linux:debian)
            if ask "Install Python now (this uses sudo and asks for your password)?"; then
                run_as_admin apt-get update && run_as_admin apt-get install -y python3 python3-venv
            fi
            ;;
        Linux:fedora|Linux:rhel)
            if ask "Install Python now (this uses sudo and asks for your password)?"; then
                run_as_admin dnf install -y python3
            fi
            ;;
    esac
    python="$(find_python)" || exit 1
fi

# --------------------------------------------------------------------------
# 2. The private Python environment
# --------------------------------------------------------------------------
if [ ! -x "$venv/bin/python" ]; then
    say "Creating a Python environment in $venv ..."
    if ! "$python" -m venv "$venv" >/dev/null 2>&1; then
        rm -rf "$venv"
        if [ "$distro" = "debian" ]; then
            # Debian and Ubuntu split the venv module into its own package.
            pyver="$("$python" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
            say ""
            say "Python's environment module is missing. To add it:"
            say "1. Open a terminal."
            say "2. Type:  sudo apt install python3-venv python${pyver}-venv"
            say "3. Run this script again."
            say ""
            if ask "Install it now (this uses sudo and asks for your password)?"; then
                run_as_admin apt-get install -y python3-venv "python${pyver}-venv" ||
                    run_as_admin apt-get install -y python3-venv
                "$python" -m venv "$venv"
            else
                exit 1
            fi
        else
            say "error: could not create a Python environment with $python"
            exit 1
        fi
    fi
    rm -f "$marker"
fi

if [ ! -f "$marker" ] || [ "$(cat "$marker")" != "$packages" ]; then
    say "Installing $packages ..."
    "$venv/bin/python" -m pip install --quiet --upgrade pip >&2
    # shellcheck disable=SC2086
    "$venv/bin/python" -m pip install --quiet $packages >&2
    "$venv/bin/python" -m pip install --quiet $optional >/dev/null 2>&1 ||
        say "note: $optional not installed; HEIC photos will not be converted"
    printf '%s' "$packages" > "$marker"
fi
py="$venv/bin/python"

if [ "$os" = "Darwin" ] && [ -d "$tools" ]; then
    # Files dragged in from a web download carry a quarantine flag that stops
    # them running from the Terminal (the ffmpeg builds offered are signed).
    xattr -dr com.apple.quarantine "$tools" 2>/dev/null || true
fi

if [ "$#" -eq 0 ]; then
    say "Set-up is complete. Now give it your gradebook ZIP files, for example:"
    say "  ./unpack-submissions.sh gradebook_*.zip -o Grading"
    exit 0
fi
exec "$py" "$program" "$@"
