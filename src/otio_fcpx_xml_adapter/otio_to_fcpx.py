# SPDX-License-Identifier: Apache-2.0
# Copyright Contributors to the OpenTimelineIO project

"""Converter from OTIO to FCPX XML."""

import opentimelineio as otio
from xml.etree import cElementTree
from xml.dom import minidom
from datetime import date
from . import utils

# FcpxOtio class will be added here

class FcpxOtio:
    """
    This object is responsible for knowing how to convert an otio into an
    FCP X XML
    """

    def __init__(self, otio_timeline):
        self.otio_timeline = otio_timeline
        self.fcpx_xml = cElementTree.Element("fcpxml", version="1.8")
        self.resource_element = cElementTree.SubElement(
            self.fcpx_xml,
            "resources"
        )
        if self.otio_timeline.schema_name() == "Timeline":
            self.timelines = [self.otio_timeline]
        else:
            self.timelines = list(
                self.otio_timeline.find_children(
                    descended_from_type=otio.schema.Timeline
                )
            )

        if len(self.timelines) > 1:
            self.event_resource = cElementTree.SubElement(
                self.fcpx_xml,
                "event",
                {"name": self._event_name()}
            )
        else:
            self.event_resource = self.fcpx_xml

        self.resource_count = 0

    def to_xml(self):
        """
        Convert an otio to an FCP X XML

        Returns:
            str: FCPX XML content
        """

        for project in self.timelines:
            top_sequence = self._stack_to_sequence(project.tracks)

            project_element = cElementTree.Element(
                "project",
                {
                    "name": project.name,
                    "uid": project.metadata.get("fcpx", {}).get("uid", "")
                }
            )
            project_element.append(top_sequence)
            self.event_resource.append(project_element)

        if not self.timelines:
            for clip in self._clips():
                if not clip.parent():
                    self._add_asset(clip)

            for stack in self._stacks():
                ref_element = self._element_for_item(
                    stack,
                    None,
                    ref_only=True,
                    compound=True
                )
                self.event_resource.append(ref_element)
        child_parent_map = {c: p for p in self.fcpx_xml.iter() for c in p}

        for marker in [marker for marker in self.fcpx_xml.iter("marker")]:
            parent = child_parent_map.get(marker)
            marker_attribs = marker.attrib.copy()
            parent.remove(marker)
            cElementTree.SubElement(
                parent,
                "marker",
                marker_attribs
            )

        xml = cElementTree.tostring(
            self.fcpx_xml,
            encoding="UTF-8",
            method="xml"
        )
        dom = minidom.parseString(xml)
        pretty = dom.toprettyxml(indent="    ")
        return pretty.replace(
            '<?xml version="1.0" ?>',
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
        )

    def _stack_to_sequence(self, stack, compound_clip=False):
        format_element = self._find_or_create_format_from(stack)
        sequence_element = cElementTree.Element(
            "sequence",
            {
                "duration": utils.calculate_rational_number(
                    stack.duration().value,
                    stack.duration().rate
                ),
                "format": str(format_element.get("id"))
            }
        )
        spine = cElementTree.SubElement(sequence_element, "spine")
        video_tracks = [
            t for t in stack
            if t.kind == otio.schema.TrackKind.Video
        ]
        audio_tracks = [
            t for t in stack
            if t.kind == otio.schema.TrackKind.Audio
        ]

        for idx, track in enumerate(video_tracks):
            self._track_for_spine(track, idx, spine, compound_clip)

        for idx, track in enumerate(audio_tracks):
            lane_id = -(idx + 1)
            self._track_for_spine(track, lane_id, spine, compound_clip)
        return sequence_element

    def _track_for_spine(self, track, lane_id, spine, compound):
        for child in self._lanable_items(track.find_children()):
            if utils.item_in_compound_clip(child) and not compound:
                continue
            child_element = self._element_for_item(
                child,
                lane_id,
                compound=compound
            )
            if not lane_id:
                spine.append(child_element)
                continue
            if child.schema_name() == "Gap":
                continue

            parent_element = self._find_parent_element(
                spine,
                track.trimmed_range_of_child(child).start_time,
                self._find_or_create_format_from(track).get("id")
            )
            offset = self._offset_based_on_parent(
                child_element,
                parent_element,
                self._find_or_create_format_from(track).get("id")
            )
            child_element.set(
                "offset",
                utils.from_rational_time(offset)
            )

            parent_element.append(child_element)
        return []

    def _find_parent_element(self, spine, trimmed_range, format_id):
        for item in spine.iter():
            if item.tag not in ("clip", "asset-clip", "gap", "ref-clip"):
                continue
            if item.get("lane") is not None:
                continue
            if item.tag == "gap" and item.find("./audio") is not None:
                continue
            offset = utils.to_rational_time(
                item.get("offset"),
                self._frame_rate_from_element(item, format_id)
            )
            duration = utils.to_rational_time(
                item.get("duration"),
                self._frame_rate_from_element(item, format_id)
            )
            total_time = offset + duration
            if offset > trimmed_range:
                continue
            if total_time > trimmed_range:
                return item
        return None

    def _offset_based_on_parent(self, child, parent, default_format_id):
        parent_offset = utils.to_rational_time(
            parent.get("offset"),
            self._frame_rate_from_element(parent, default_format_id)
        )
        child_offset = utils.to_rational_time(
            child.get("offset"),
            self._frame_rate_from_element(child, default_format_id)
        )

        parent_start = utils.to_rational_time(
            parent.get("start"),
            self._frame_rate_from_element(parent, default_format_id)
        )
        return (child_offset - parent_offset) + parent_start

    def _frame_rate_from_element(self, element, default_format_id):
        if element.tag == "gap":
            format_id = default_format_id

        if element.tag == "ref-clip":
            media_element = self._media_by_id(element.get("ref"))
            asset = media_element.find("./sequence")
            format_id = asset.get("format")

        if element.tag == "clip":
            if element.find("./gap") is not None:
                asset_id = element.find("./gap").find("./audio").get("ref")
            else:
                asset_id = element.find("./video").get("ref")
            asset = self._asset_by_id(asset_id)
            format_id = asset.get("format")

        if element.tag == "asset-clip":
            asset = self._asset_by_id(element.get("ref"))
            format_id = asset.get("format")

        format_element = self.resource_element.find(
            f"./format[@id='{format_id}']"
        )
        total, rate = format_element.get("frameDuration").split("/")
        rate = rate.replace("s", "")
        return int(float(rate) / float(total))

    def _element_for_item(self, item, lane, ref_only=False, compound=False):
        element = None
        duration = utils.calculate_rational_number(
            item.duration().value,
            item.duration().rate
        )
        if item.schema_name() == "Clip":
            asset_id = self._add_asset(item, compound_only=compound)
            element = self._element_for_clip(item, asset_id, duration, lane)

        if item.schema_name() == "Gap":
            element = self._element_for_gap(item, duration)

        if item.schema_name() == "Stack":
            element = self._element_for_stack(item, duration, ref_only)

        if element is None:
            return None
        if lane:
            element.set("lane", str(lane))
        for marker in item.markers:
            marker_attribs = {
                "start": utils.from_rational_time(marker.marked_range.start_time),
                "duration": utils.from_rational_time(marker.marked_range.duration),
                "value": marker.name
            }
            marker_element = cElementTree.Element(
                "marker",
                marker_attribs
            )
            if marker.color == otio.schema.MarkerColor.RED:
                marker_element.set("completed", "0")
            if marker.color == otio.schema.MarkerColor.GREEN:
                marker_element.set("completed", "1")
            element.append(marker_element)
        return element

    def _lanable_items(self, items):
        return [
            item for item in items
            if item.schema_name() in ["Gap", "Stack", "Clip"]
        ]

    def _element_for_clip(self, item, asset_id, duration, lane):
        element = cElementTree.Element(
            "clip",
            {
                "name": item.name,
                "offset": utils.from_rational_time(
                    item.trimmed_range_in_parent().start_time
                ),
                "duration": duration
            }
        )
        start = utils.from_rational_time(item.source_range.start_time)
        if start != "0s":
            element.set("start", str(start))
        if item.parent().kind == otio.schema.TrackKind.Video:
            cElementTree.SubElement(
                element,
                "video",
                {
                    "offset": "0s",
                    "ref": asset_id,
                    "duration": self._find_asset_duration(item)
                }
            )
        else:
            gap_element = cElementTree.SubElement(
                element,
                "gap",
                {
                    "name": "Gap",
                    "offset": "0s",
                    "duration": self._find_asset_duration(item)
                }
            )
            audio = cElementTree.SubElement(
                gap_element,
                "audio",
                {
                    "offset": "0s",
                    "ref": asset_id,
                    "duration": self._find_asset_duration(item)
                }
            )
            if lane:
                audio.set("lane", str(lane))
        return element

    def _element_for_gap(self, item, duration):
        element = cElementTree.Element(
            "gap",
            {
                "name": "Gap",
                "duration": duration,
                "offset": utils.from_rational_time(
                    item.trimmed_range_in_parent().start_time
                ),
                "start": "3600s"
            }
        )
        return element

    def _element_for_stack(self, item, duration, ref_only):
        media_element = self._add_compound_clip(item)
        asset_id = media_element.get("id")
        element = cElementTree.Element(
            "ref-clip",
            {
                "name": item.name,
                "duration": duration,
                "ref": str(asset_id)
            }
        )
        if not ref_only:
            element.set(
                "offset",
                utils.from_rational_time(
                    item.trimmed_range_in_parent().start_time
                )
            )
            element.set(
                "start",
                utils.from_rational_time(item.source_range.start_time)
            )
        if item.parent() and item.parent().kind == otio.schema.TrackKind.Audio:
            element.set("srcEnable", "audio")
        return element

    def _find_asset_duration(self, item):
        if (item.media_reference and
                not item.media_reference.is_missing_reference):
            return utils.calculate_rational_number(
                item.media_reference.available_range.duration.value,
                item.media_reference.available_range.duration.rate
            )
        return utils.calculate_rational_number(
            item.duration().value,
            item.duration().rate
        )

    def _find_asset_start(self, item):
        if (item.media_reference and
                not item.media_reference.is_missing_reference):
            return utils.calculate_rational_number(
                item.media_reference.available_range.start_time.value,
                item.media_reference.available_range.start_time.rate
            )
        return utils.calculate_rational_number(
            item.source_range.start_time.value,
            item.source_range.start_time.rate
        )

    def _clip_format_name(self, clip):
        if clip.schema_name() in ("Stack", "Track"):
            return ""
        if not clip.media_reference:
            return ""

        if clip.media_reference.is_missing_reference:
            return ""

        return utils.format_name(
            clip.duration().rate,
            clip.media_reference.target_url
        )

    def _find_or_create_format_from(self, clip):
        frame_duration = utils.framerate_to_frame_duration(
            clip.duration().rate
        )
        format_element = self._format_by_frame_rate(clip.duration().rate)
        if format_element is None:
            format_element = cElementTree.SubElement(
                self.resource_element,
                "format",
                {
                    "id": self._resource_id_generator(),
                    "frameDuration": frame_duration,
                    "name": self._clip_format_name(clip)
                }
            )
        if format_element.get("name", "") == "":
            format_element.set("name", self._clip_format_name(clip))
        return format_element

    def _add_asset(self, clip, compound_only=False):
        format_element = self._find_or_create_format_from(clip)
        asset = self._create_asset_element(clip, format_element)

        if not compound_only and not self._asset_clip_by_name(clip.name):
            self._create_asset_clip_element(
                clip,
                format_element,
                asset.get("id")
            )

        if not clip.parent():
            asset.set("hasAudio", "1")
            asset.set("hasVideo", "1")
            return asset.get("id")
        if clip.parent().kind == otio.schema.TrackKind.Audio:
            asset.set("hasAudio", "1")
        if clip.parent().kind == otio.schema.TrackKind.Video:
            asset.set("hasVideo", "1")
        return asset.get("id")

    def _create_asset_clip_element(self, clip, format_element, resource_id):
        duration = self._find_asset_duration(clip)
        a_clip = cElementTree.SubElement(
            self.event_resource,
            "asset-clip",
            {
                "name": clip.name,
                "format": format_element.get("id"),
                "ref": resource_id,
                "duration": duration
            }
        )
        if (clip.media_reference and not
           clip.media_reference.is_missing_reference):
            fcpx_metadata = clip.media_reference.metadata.get("fcpx", {})
            note_element = utils.create_note_element(
                fcpx_metadata.get("note", None)
            )
            keyword_elements = utils.create_keyword_elements(
                fcpx_metadata.get("keywords", [])
            )
            metadata_element = utils.create_metadata_elements(
                fcpx_metadata.get("metadata", None)
            )

            if note_element is not None:
                a_clip.append(note_element)
            if keyword_elements:
                for keyword_element in keyword_elements:
                    a_clip.append(keyword_element)
            if metadata_element is not None:
                a_clip.append(metadata_element)

    def _create_asset_element(self, clip, format_element):
        target_url = utils.target_url_from_clip(clip)
        asset = self._asset_by_path(target_url)
        if asset is not None:
            return asset

        asset = cElementTree.SubElement(
            self.resource_element,
            "asset",
            {
                "name": clip.name,
                "src": target_url,
                "format": format_element.get("id"),
                "id": self._resource_id_generator(),
                "duration": self._find_asset_duration(clip),
                "start": self._find_asset_start(clip),
                "hasAudio": "0",
                "hasVideo": "0"
            }
        )
        return asset

    def _add_compound_clip(self, item):
        media_element = self._media_by_name(item.name)
        if media_element is not None:
            return media_element
        resource_id = self._resource_id_generator()
        media_element = cElementTree.SubElement(
            self.resource_element,
            "media",
            {
                "name": utils.compound_clip_name(item, resource_id),
                "id": resource_id
            }
        )
        if item.metadata.get("fcpx", {}).get("uid", False):
            media_element.set("uid", item.metadata.get("fcpx", {}).get("uid"))
        media_element.append(self._stack_to_sequence(item, compound_clip=True))
        return media_element

    def _stacks(self):
        return self.otio_timeline.find_children(
            descended_from_type=otio.schema.Stack
        )

    def _clips(self):
        return self.otio_timeline.find_children(
            descended_from_type=otio.schema.Clip
        )

    def _resource_id_generator(self):
        self.resource_count += 1
        return f"r{self.resource_count}"

    def _event_name(self):
        if self.otio_timeline.name:
            return self.otio_timeline.name
        return date.strftime(date.today(), "%m-%e-%y")

    def _asset_by_path(self, path):
        return self.resource_element.find(f"./asset[@src='{path}']")

    def _asset_by_id(self, asset_id):
        return self.resource_element.find(f"./asset[@id='{asset_id}']")

    def _media_by_name(self, name):
        return self.resource_element.find(f"./media[@name='{name}']")

    def _media_by_id(self, media_id):
        return self.resource_element.find(f"./media[@id='{media_id}']")

    def _format_by_frame_rate(self, frame_rate):
        frame_duration = utils.framerate_to_frame_duration(frame_rate)
        return self.resource_element.find(
            f"./format[@frameDuration='{frame_duration}']"
        )

    def _asset_clip_by_name(self, name):
        return self.event_resource.find(
            f"./asset-clip[@name='{name}']"
        )

    # --------------------
    # static methods (already moved to utils.py)
    # --------------------

    @staticmethod
    def _create_note_element(note):
        if not note:
            return None
        note_element = cElementTree.Element(
            "note"
        )
        note_element.text = note
        return note_element 