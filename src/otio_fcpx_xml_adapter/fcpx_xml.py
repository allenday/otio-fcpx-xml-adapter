# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the OpenTimelineIO project

"""OpenTimelineIO Final Cut Pro X XML Adapter. """
# import os
# import subprocess
from xml.etree import cElementTree
from xml.dom import minidom
# from fractions import Fraction
from datetime import date
# import urllib.parse import unquote

import opentimelineio as otio
from otio_fcpx_xml_adapter import utils
from otio_fcpx_xml_adapter.fcpx_to_otio import FcpxXml
from otio_fcpx_xml_adapter.otio_to_fcpx import FcpxOtio # Add top-level import

META_NAMESPACE = "fcpx_xml"

# COMPOSABLE_ELEMENTS moved to fcpx_to_otio.py

# FcpxOtio class moved to otio_to_fcpx.py


# FcpxXml class moved to fcpx_to_otio.py


# --------------------
# adapter requirements
# --------------------
def read_from_string(input_str):
    """
    Necessary read method for otio adapter

    Args:
        input_str (str): An FCP X XML string

    Returns:
        OpenTimeline: An OpenTimeline object
    """
    # Use the imported FcpxXml
    return FcpxXml(input_str).to_otio()


def write_to_string(input_otio):
    """
    Necessary write method for otio adapter

    Args:
        input_otio (OpenTimeline): An OpenTimeline object

    Returns:
        str: The string contents of an FCP X XML
    """
    # Use the imported FcpxOtio
    return FcpxOtio(input_otio).to_xml()
