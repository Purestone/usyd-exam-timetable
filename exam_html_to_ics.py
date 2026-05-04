#!/usr/bin/env python3
"""Parse USYD exam timetable HTML into an ICS calendar file."""

from __future__ import annotations

import argparse
import html
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4


SYDNEY_TZ = "Australia/Sydney"


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_duration_minutes(duration_text: str) -> int:
    text = duration_text.lower()
    hours = 0
    minutes = 0

    hour_match = re.search(r"(\d+)\s*hour", text)
    minute_match = re.search(r"(\d+)\s*minute", text)

    if hour_match:
        hours = int(hour_match.group(1))
    if minute_match:
        minutes = int(minute_match.group(1))

    total = hours * 60 + minutes
    if total <= 0:
        raise ValueError(f"Could not parse duration from: {duration_text!r}")
    return total


def build_location(exam: Dict[str, str]) -> str:
    """Build location string from Building Venue, Room, Your Seat format."""
    parts = []

    building = exam.get("Building", "").strip()
    venue = exam.get("Venue", "").strip()
    room = exam.get("Room", "").strip()
    seat = exam.get("Your Seat", "").strip()

    # Building Venue
    if building and venue:
        parts.append(f"{building} {venue}")
    elif building or venue:
        parts.append(building or venue)

    # Room
    if room:
        parts.append(room)

    # Your Seat
    if seat:
        parts.append(seat)

    return ", ".join(parts) if parts else "The University of Sydney"


def ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


class ExamHTMLParser(HTMLParser):
    """Extract key-value rows from the exam timetable table."""

    def __init__(self) -> None:
        super().__init__()
        self.in_table_c = False
        self.in_td = False
        self.current_cell_parts: List[str] = []
        self.current_row_cells: List[str] = []
        self.pending_link: Optional[str] = None
        self.exams: List[Dict[str, str]] = []
        self.current_exam: Dict[str, str] = {}
        self.student_sid: Optional[str] = None
        self.capture_sid = False

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        attrs_dict = dict(attrs)
        if tag == "table" and attrs_dict.get("id") == "table-c":
            self.in_table_c = True
        if self.in_table_c and tag == "td":
            self.in_td = True
            self.current_cell_parts = []
        if self.in_table_c and tag == "br" and self.in_td:
            self.current_cell_parts.append("\n")
        if self.in_table_c and tag == "a":
            href = attrs_dict.get("href")
            if href:
                self.pending_link = href
        if tag == "p" and attrs_dict.get("align") == "center":
            self.capture_sid = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self.in_table_c:
            self.in_table_c = False
            self._flush_exam()
        if self.in_table_c and tag == "td" and self.in_td:
            self.in_td = False
            cell = normalize_whitespace("".join(self.current_cell_parts))
            self.current_row_cells.append(cell)
        if self.in_table_c and tag == "tr":
            self._consume_row()
        if tag == "p":
            self.capture_sid = False

    def handle_data(self, data: str) -> None:
        if self.capture_sid and "Personalised timetable for" in data and "for Final Examinations Timetable" in data:
            match = re.search(
                r"Personalised timetable for\s+(.+?)\s+for Final Examinations Timetable", data)
            if match:
                candidate = normalize_whitespace(match.group(1))
                if candidate:
                    self.student_sid = candidate
        if self.in_table_c and self.in_td:
            self.current_cell_parts.append(html.unescape(data))

    def _consume_row(self) -> None:
        if len(self.current_row_cells) != 2:
            self.current_row_cells = []
            self.pending_link = None
            return

        key, value = self.current_row_cells[0], self.current_row_cells[1]
        self.current_row_cells = []

        if not key:
            return

        if key == "Exam":
            self._flush_exam()
            self.current_exam = {key: value}
            self.pending_link = None
            return

        if key == "Map" and self.pending_link:
            value = self.pending_link

        if self.current_exam:
            self.current_exam[key] = value
        self.pending_link = None

    def _flush_exam(self) -> None:
        if self.current_exam and "Exam" in self.current_exam:
            self.exams.append(self.current_exam)
        self.current_exam = {}


def create_ics(exams: List[Dict[str, str]]) -> str:
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//usyd-exam-timetable//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for exam in exams:
        exam_name = exam.get("Exam", "Exam")
        date_str = exam.get("Date")
        start_str = exam.get("Start Time")
        duration_str = exam.get("Duration", "")
        if not date_str or not start_str:
            continue

        start_dt = datetime.strptime(
            f"{date_str} {start_str}", "%A %d %b %Y %I:%M%p")
        duration_minutes = parse_duration_minutes(
            duration_str) if duration_str else 120
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        location = build_location(exam)

        description_fields = [
            ("Assessment Type", exam.get("Assessment Type", "")),
            ("Duration", duration_str),
            ("Writing Time", exam.get("Writing Time", "")),
            ("Reading Time", exam.get("Reading Time", "")),
            ("Exam Conditions", exam.get("Exam Conditions", "")),
            ("Materials Permitted", exam.get("Materials Permitted", "")),
        ]
        description = "\n\n".join(
            [f"[{label}] {value}" for label,
                value in description_fields if value]
        )

        uid = f"{uuid4()}@usyd-exam"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_utc}",
                f"DTSTART;TZID={SYDNEY_TZ}:{start_dt.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID={SYDNEY_TZ}:{end_dt.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:{ics_escape(exam_name)}",
                f"LOCATION:{ics_escape(location)}",
                f"DESCRIPTION:{ics_escape(description)}",
                f"URL:{ics_escape(exam.get('Map', ''))}" if exam.get(
                    "Map") else "",
                "END:VEVENT",
            ]
        )

    lines = [line for line in lines if line != ""]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert USYD exam timetable HTML into ICS.")
    parser.add_argument("html_file", type=Path,
                        help="Path to the timetable HTML file.")
    parser.add_argument("--sid", required=False,
                        help="Student SID for output filename.")
    parser.add_argument(
        "--output",
        type=Path,
        required=False,
        help="Optional output ICS file path. Defaults to {SID}_exam.ics",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    html_text = args.html_file.read_text(encoding="utf-8")

    parser = ExamHTMLParser()
    parser.feed(html_text)

    if not parser.exams:
        raise SystemExit("No exams found in the HTML file.")

    sid = args.sid or parser.student_sid
    if not sid:
        raise SystemExit("SID not found in HTML. Please provide --sid.")

    output_path = args.output if args.output else Path(f"{sid}_exam.ics")
    ics_content = create_ics(parser.exams)
    output_path.write_text(ics_content, encoding="utf-8")

    print(f"Created {output_path} with {len(parser.exams)} exam event(s).")


if __name__ == "__main__":
    main()
