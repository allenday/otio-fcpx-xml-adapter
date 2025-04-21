# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the OpenTimelineIO project

"""Converter from FCPX XML to OTIO."""

import opentimelineio as otio
from xml.etree import cElementTree
from . import utils

COMPOSABLE_ELEMENTS = ("video", "audio", "ref-clip", "asset-clip")

class FcpxXml:
    """
    This object is responsible for knowing how to convert an FCP X XML
    otio into an otio timeline
    """

    def __init__(self, xml_string):
        self.fcpx_xml = cElementTree.fromstring(xml_string)
        self.child_parent_map = {c: p for p in self.fcpx_xml.iter() for c in p}

    def to_otio(self):
        """
        Convert an FCP X XML to an otio

        Returns:
            OpenTimeline: An OpenTimeline Timeline object
        """

        if self.fcpx_xml.find("./library") is not None:
            return self._from_library()
        if self.fcpx_xml.find("./event") is not None:
            return self._from_event(self.fcpx_xml.find("./event"))
        if self.fcpx_xml.find("./project") is not None:
            return self._from_project(self.fcpx_xml.find("./project"))
        if ((self.fcpx_xml.find("./asset-clip") is not None) or
                (self.fcpx_xml.find("./ref-clip") is not None)):
            return self._from_clips()

    def _from_library(self):
        # We are just grabbing the first even in the project for now
        return self._from_event(self.fcpx_xml.find("./library/event"))

    def _from_event(self, event_element):
        container = otio.schema.SerializableCollection(
            name=event_element.get("name")
        )
        for project in event_element.findall("./project"):
            container.append(self._from_project(project))
        return container

    def _from_project(self, project_element):
        timeline = otio.schema.Timeline(name=project_element.get("name", ""))
        timeline.tracks = self._squence_to_stack(
            project_element.find("./sequence", {})
        )
        return timeline

    def _from_clips(self):
        container = otio.schema.SerializableCollection()
        if self.fcpx_xml.find("./asset-clip") is not None:
            for asset_clip in self.fcpx_xml.findall("./asset-clip"):
                container.append(
                    self._build_composable(
                        asset_clip,
                        asset_clip.get("format")
                    )
                )

        if self.fcpx_xml.find("./ref-clip") is not None:
            for ref_clip in self.fcpx_xml.findall("./ref-clip"):
                container.append(
                    self._build_composable(
                        ref_clip,
                        "r1"
                    )
                )
        return container

    def _squence_to_stack(self, sequence_element, name="", source_range=None):
        timeline_items = []
        lanes = []
        stack = otio.schema.Stack(name=name, source_range=source_range)
        for element in sequence_element.iter():
            if element.tag not in COMPOSABLE_ELEMENTS:
                continue
            composable = self._build_composable(
                element,
                sequence_element.get("format")
            )

            offset, lane = self._offset_and_lane(
                element,
                sequence_element.get("format")
            )

            timeline_items.append(
                {
                    "track": lane,
                    "offset": offset,
                    "composable": composable,
                    "audio_only": self._audio_only(element)
                }
            )

            lanes.append(lane)
        sorted_lanes = list(set(lanes))
        sorted_lanes.sort()
        for lane in sorted_lanes:
            sorted_items = utils.sort_items_by_offset(lane, timeline_items)
            track = otio.schema.Track(
                name=lane,
                kind=utils.determine_track_kind(sorted_items)
            )

            for item in sorted_items:
                frame_diff = (
                    int(item["offset"].value) - track.duration().value
                )
                if frame_diff > 0:
                    track.append(
                        self._create_gap(
                            0,
                            frame_diff,
                            sequence_element.get("format")
                        )
                    )
                track.append(item["composable"])
            stack.append(track)
        return stack

    def _build_composable(self, element, default_format):
        timing_clip = self._timing_clip(element)
        source_range = self._time_range(
            timing_clip,
            self._format_id_for_clip(element, default_format)
        )

        if element.tag != "ref-clip":
            otio_composable = otio.schema.Clip(
                name=timing_clip.get("name"),
                media_reference=self._reference_from_id(
                    element.get("ref"),
                    default_format
                ),
                source_range=source_range
            )
        else:
            media_element = self._compound_clip_by_id(element.get("ref"))
            otio_composable = self._squence_to_stack(
                media_element.find("./sequence"),
                name=media_element.get("name"),
                source_range=source_range
            )

        for marker in timing_clip.findall(".//marker"):
            otio_composable.markers.append(
                self._marker(marker, default_format)
            )

        return otio_composable

    def _marker(self, element, default_format):
        if element.get("completed", None) and element.get("completed") == "1":
            color = otio.schema.MarkerColor.GREEN
        if element.get("completed", None) and element.get("completed") == "0":
            color = otio.schema.MarkerColor.RED
        if not element.get("completed", None):
            color = otio.schema.MarkerColor.PURPLE

        otio_marker = otio.schema.Marker(
            name=element.get("value", ""),
            marked_range=self._time_range(element, default_format),
            color=color
        )
        return otio_marker

    def _audio_only(self, element):
        if element.tag == "audio":
            return True
        if element.tag == "asset-clip":
            asset = self._asset_by_id(element.get("ref", None))
            if asset and asset.get("hasVideo", "0") == "0":
                return True
        if element.tag == "ref-clip":
            if element.get("srcEnable", "video") == "audio":
                return True
        return False

    def _create_gap(self, start_frame, number_of_frames, defualt_format):
        fps = self._format_frame_rate(defualt_format)
        source_range = otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(start_frame, fps),
            duration=otio.opentime.RationalTime(number_of_frames, fps)
        )
        return otio.schema.Gap(source_range=source_range)

    def _timing_clip(self, clip):
        while clip.tag not in ("clip", "asset-clip", "ref-clip"):
            clip = self.child_parent_map.get(clip)
        return clip

    def _offset_and_lane(self, clip, default_format):
        clip_format_id = self._format_id_for_clip(clip, default_format)
        clip = self._timing_clip(clip)
        parent = self.child_parent_map.get(clip)

        parent_format_id = self._format_id_for_clip(parent, default_format)

        if parent.tag == "spine" and parent.get("lane", None):
            lane = parent.get("lane")
            parent = self.child_parent_map.get(parent)
            spine = True
        else:
            lane = clip.get("lane", "0")
            spine = False

        clip_offset_frames = self._number_of_frames(
            clip.get("offset"),
            clip_format_id
        )

        if spine:
            parent_start_frames = 0
        else:
            parent_start_frames = self._number_of_frames(
                parent.get("start", None),
                parent_format_id
            )

        parent_offset_frames = self._number_of_frames(
            parent.get("offset", None),
            parent_format_id
        )

        clip_offset_frames = (
            (int(clip_offset_frames) - int(parent_start_frames)) +
            int(parent_offset_frames)
        )

        offset = otio.opentime.RationalTime(
            clip_offset_frames,
            self._format_frame_rate(clip_format_id)
        )

        return offset, lane

    def _format_id_for_clip(self, clip, default_format):
        if not clip.get("ref", None) or clip.tag == "gap":
            return default_format

        resource = self._asset_by_id(clip.get("ref"))

        if resource is None:
            resource = self._compound_clip_by_id(
                clip.get("ref")
            ).find("sequence")

        return resource.get("format", default_format)

    def _reference_from_id(self, asset_id, default_format):
        asset = self._asset_by_id(asset_id)
        if not asset.get("src", ""):
            return otio.schema.MissingReference()

        format_id = asset.get("format", default_format)
        format_element = self._format_by_id(format_id)
        rate = utils.format_to_rate(format_element)

        available_range = otio.opentime.TimeRange(
            start_time=utils.to_rational_time(
                asset.get("start"),
                rate
            ),
            duration=utils.to_rational_time(
                asset.get("duration"),
                rate
            )
        )
        asset_clip = self._assetclip_by_ref(asset_id)
        metadata = {}
        if asset_clip:
            metadata = self._create_metadta(asset_clip)
        return otio.schema.ExternalReference(
            target_url=asset.get("src"),
            available_range=available_range,
            metadata={"fcpx": metadata}
        )

    def _create_metadta(self, item):
        metadata = {}
        for element in item.iter():
            if element.tag == "md":
                metadata.setdefault("metadata", []).append(
                    {element.attrib.get("key"): element.attrib.get("value")}
                )
                # metadata.update(
                #     {element.attrib.get("key"): element.attrib.get("value")}
                # )
            if element.tag == "note":
                metadata.update({"note": element.text})
            if element.tag == "keyword":
                metadata.setdefault("keywords", []).append(element.attrib)
        return metadata

    # --------------------
    # time helpers
    # --------------------
    def _format_frame_duration(self, format_id):
        media_format = self._format_by_id(format_id)
        total, rate = media_format.get("frameDuration").split("/")
        rate = rate.replace("s", "")
        return total, rate

    def _format_frame_rate(self, format_id):
        fd_total, fd_rate = self._format_frame_duration(format_id)
        return int(float(fd_rate) / float(fd_total))

    def _number_of_frames(self, time_value, format_id):
        if time_value == "0s" or time_value is None:
            return 0
        fd_total, fd_rate = self._format_frame_duration(format_id)
        time_value = time_value.split("/")

        if len(time_value) > 1:
            time_value_a, time_value_b = time_value
            return int(
                (float(time_value_a) / float(time_value_b.replace("s", ""))) *
                (float(fd_rate) / float(fd_total))
            )

        return int(
            int(time_value[0].replace("s", "")) *
            (float(fd_rate) / float(fd_total))
        )

    def _time_range(self, element, format_id):
        return otio.opentime.TimeRange(
            start_time=utils.to_rational_time(
                element.get("start", "0s"),
                self._format_frame_rate(format_id)
            ),
            duration=utils.to_rational_time(
                element.get("duration"),
                self._format_frame_rate(format_id)
            )
        )
    # --------------------
    # search helpers
    # --------------------

    def _asset_by_id(self, asset_id):
        return self.fcpx_xml.find(
            f"./resources/asset[@id='{asset_id}']"
        )

    def _assetclip_by_ref(self, asset_id):
        event = self.fcpx_xml.find("./event")
        if event is None:
            return self.fcpx_xml.find(f"./asset-clip[@ref='{asset_id}']")
        else:
            return event.find(f"./asset-clip[@ref='{asset_id}']")

    def _format_by_id(self, format_id):
        return self.fcpx_xml.find(
            f"./resources/format[@id='{format_id}']"
        )

    def _compound_clip_by_id(self, compound_id):
        return self.fcpx_xml.find(
            f"./resources/media[@id='{compound_id}']"
        )

    # --------------------\
    # static methods (now moved to utils.py)
    # --------------------
    # _track_type removed, moved to utils.determine_track_kind
    # _sorted_items removed, moved to utils.sort_items_by_offset
