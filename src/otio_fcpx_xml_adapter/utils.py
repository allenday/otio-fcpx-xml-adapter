# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the OpenTimelineIO project

"""Utility functions for the FCPX XML Adapter."""

# Imports will be added as needed when functions are moved here
import opentimelineio as otio # Common import likely needed
from fractions import Fraction # Likely needed for time conversions
from xml.etree import cElementTree # Likely needed for XML elements
import os # Needed for format_name
import subprocess # Needed for format_name
from urllib.parse import unquote # Needed for format_name

FRAMERATE_FRAMEDURATION = {23.98: "1001/24000s",
                           24: "25/600s",
                           25: "1/25s",
                           29.97: "1001/30000s",
                           30: "100/3000s",
                           50: "1/50s",
                           59.94: "1001/60000s",
                           60: "1/60s"}


def format_name(frame_rate, path):
    """
    Helper to get the formatName used in FCP X XML format elements. This
    uses ffprobe to get the frame size of the the clip at the provided path.

    Args:
        frame_rate (int): The frame rate of the clip at the provided path
        path (str): The path to the clip to probe

    Returns:
        str: The format name. If empty, then ffprobe couldn't find the item
    """

    path = path.replace("file://", "")
    path = unquote(path)
    if not os.path.exists(path):
        return ""

    try:
        frame_size = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=height,width",
                "-of",
                "csv=s=x:p=0",
                path
            ]
        ).decode("utf-8")
    except (subprocess.CalledProcessError, OSError):
        frame_size = ""

    if not frame_size:
        return ""

    frame_size = frame_size.rstrip()

    if "1920" in frame_size:
        frame_size = "1080"

    if frame_size.endswith("1280"):
        frame_size = "720"

    return f"FFVideoFormat{frame_size}p{frame_rate}"

def to_rational_time(rational_number, fps):
    """
    This converts a rational number value to an otio RationalTime object

    Args:
        rational_number (str): This is a rational number from an FCP X XML
        fps (int): The frame rate to use for calculating the rational time

    Returns:
        RationalTime: A RationalTime object
    """

    if rational_number == "0s" or rational_number is None:
        frames = 0
    else:
        parts = rational_number.split("/")
        if len(parts) > 1:
            frames = int(
                float(parts[0]) / float(parts[1].replace("s", "")) * float(fps)
            )
        else:
            frames = int(float(parts[0].replace("s", "")) * float(fps))

    return otio.opentime.RationalTime(frames, int(fps))


def from_rational_time(rational_time):
    """
    This converts a RationalTime object to a rational number as a string

    Args:
        rational_time (RationalTime): a rational time object

    Returns:
        str: A rational number as a string
    """

    if int(rational_time.value) == 0:
        return "0s"
    result = Fraction(
        float(rational_time.value) / float(rational_time.rate)
    ).limit_denominator()
    if str(result.denominator) == "1":
        return f"{result.numerator}s"
    return f"{result.numerator}/{result.denominator}s"


def framerate_to_frame_duration(framerate):
    """Converts a framerate to an FCPX frame duration string."""
    try:
        fr = float(framerate)
    except (ValueError, TypeError):
        return from_rational_time(otio.opentime.RationalTime(1, framerate))

    lookup_key = float(f"{fr:.2f}")

    return FRAMERATE_FRAMEDURATION.get(
        lookup_key,
        from_rational_time(otio.opentime.RationalTime(1, fr))
    )


def calculate_rational_number(duration, rate):
    """Converts duration and rate into an FCPX rational number string."""
    if int(duration) == 0:
        return "0s"
    return from_rational_time(otio.opentime.RationalTime(duration, rate))


def format_to_rate(format_element):
    """Extracts the frame rate from an FCPX format element."""
    if format_element is None:
        return 24.0
    frame_duration_str = format_element.get("frameDuration")
    if not frame_duration_str:
        return 24.0
    try:
        parts = frame_duration_str.split("/")
        if len(parts) == 2:
            numerator = float(parts[0])
            denominator = float(parts[1].replace("s", ""))
            if denominator == 0:
                return 24.0
            rate = denominator / numerator
            return rate
        elif len(parts) == 1:
            return 24.0
        else:
            return 24.0
    except (ValueError, AttributeError):
        return 24.0

# --- Static methods moved from FcpxOtio --- #

# ... (Keep previously added static methods below) ...

def target_url_from_clip(clip):
    """
    Helper function to return the target_url from an OTIO Clip object.

    Args:
        clip (otio.schema.Clip): The OTIO Clip object

    Returns:
        str: The URL string if found, otherwise a default temporary path
    """
    if (
        clip.media_reference and
        isinstance(clip.media_reference, otio.schema.ExternalReference) and
        not clip.media_reference.is_missing_reference
    ):
        return clip.media_reference.target_url
    # Provide a default fallback if no valid target_url exists
    return f"file:///tmp/{clip.name}.mov" # Assume .mov or determine based on context if possible 